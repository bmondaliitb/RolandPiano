from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Set, Tuple

import mido

from .app_state import load_app_state, load_project, save_app_state, save_project
from .computer_synth import ComputerSynthError, FluidSynthOutput
from .roland_address_map import RolandAddressMap
from .roland_messages import RolandMessageRequest
from .roland_utils import RolandCmd
from .song_trainer import (
    PracticeStep,
    Song,
    SongConversionError,
    build_practice_steps,
    is_black_key,
    load_song,
    note_name,
    open_input_port,
    open_output_port,
    practice_step_matches,
    practice_step_for_hand,
    shape_velocity,
    staff_note_position,
    suggest_fingering,
)


LOW_NOTE = 21
HIGH_NOTE = 108
WHITE_KEY_PATTERN = {0, 2, 4, 5, 7, 9, 11}
PRACTICE_EARLY_PRESS_GRACE = 1.5


class PianoTrainerApp(tk.Tk):
    def __init__(
        self,
        initial_song: Optional[str] = None,
        send_to_piano: bool = False,
        play_on_computer: bool = False,
    ) -> None:
        super().__init__()
        self.saved_state = load_app_state()
        self.pending_song_state = None
        self.title("Roland FP-10 Piano Trainer")
        self.app_icon = None
        icon_path = Path(__file__).parent / "assets" / "roland-piano-trainer.png"
        if icon_path.is_file():
            try:
                self.app_icon = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, self.app_icon)
            except tk.TclError:
                self.app_icon = None
        try:
            self.geometry(self.saved_state.get("geometry", "1180x760"))
        except tk.TclError:
            self.geometry("1180x760")
        self.minsize(900, 620)

        self.song: Optional[Song] = None
        self.playing = False
        self.started_at = 0.0
        self.paused_at = 0.0
        self.tempo = tk.DoubleVar(value=self._saved_number("tempo", 1.0, 0.4, 1.5))
        self.dynamics = tk.IntVar(value=round(self._saved_number("dynamics", 85, 50, 110)))
        self.piano_volume = tk.IntVar(value=round(self._saved_number("piano_volume", 50, 0, 100)))
        self.piano_volume_after_id = None
        self.follow = tk.BooleanVar(value=self._saved_bool("follow", True))
        self.send_to_piano = tk.BooleanVar(value=send_to_piano or self._saved_bool("send_to_piano", False))
        self.play_on_computer = tk.BooleanVar(
            value=play_on_computer or self._saved_bool("play_on_computer", False)
        )
        self.practice_mode = tk.BooleanVar(value=self._saved_bool("practice_mode", False))
        self.show_fingers = tk.BooleanVar(value=self._saved_bool("show_fingers", False))
        saved_hand = self.saved_state.get("practice_hand", "both")
        self.practice_hand = tk.StringVar(value=saved_hand if saved_hand in {"both", "left", "right"} else "both")
        saved_view = self.saved_state.get("view_mode", "roll")
        self.view_mode = tk.StringVar(value=saved_view if saved_view in {"roll", "sheet"} else "roll")
        self.loop_enabled = tk.BooleanVar(value=False)
        self.loop_start = 0.0
        self.loop_end: Optional[float] = None
        self.loop_text = tk.StringVar(value="Loop: not set")
        self.position = tk.DoubleVar(value=0.0)
        self.position_text = tk.StringVar(value="0.0s")
        self.updating_position = False
        self.output_port = None
        self.computer_synth: Optional[FluidSynthOutput] = None
        self.input_port = None
        self.input_messages: queue.Queue = queue.Queue()
        self.active_output_notes: Dict[Tuple[int, int], int] = {}
        self.playback_event_index = 0
        self.pressed_notes: Set[int] = set()
        self.recent_practice_presses: Dict[int, float] = {}
        self.practice_steps: Tuple[PracticeStep, ...] = tuple()
        self.practice_step_starts: Tuple[float, ...] = tuple()
        self.practice_index = 0
        self.practice_waiting = False
        self.preview_seconds = 5.0
        self.note_starts: Tuple[float, ...] = tuple()
        self.playback_event_times: Tuple[float, ...] = tuple()
        self.max_note_duration = 0.0
        self.last_render_time = 0.0
        self.render_interval = 1.0 / 24.0
        self.last_position_update_time = 0.0
        self.position_update_interval = 1.0 / 20.0
        self.control_label_signature = None
        self.keyboard_signature = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._close_app)
        self.after_idle(self._restore_window_state)
        self.after(16, self._tick)

        if initial_song:
            self.load_file(Path(initial_song))
        else:
            saved_song = self.saved_state.get("song")
            if isinstance(saved_song, str) and Path(saved_song).is_file():
                self.pending_song_state = self.saved_state
                self.load_file(Path(saved_song))

    def _saved_number(self, key: str, default: float, minimum: float, maximum: float) -> float:
        value = self.saved_state.get(key, default)
        if not isinstance(value, (int, float)):
            return default
        return min(maximum, max(minimum, float(value)))

    def _saved_bool(self, key: str, default: bool) -> bool:
        value = self.saved_state.get(key, default)
        return value if isinstance(value, bool) else default

    def _restore_window_state(self) -> None:
        if not self._saved_bool("maximized", False):
            return
        try:
            self.attributes("-zoomed", True)
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(8, weight=1)

        ttk.Button(toolbar, text="Open", command=self.open_file).grid(row=0, column=0, padx=(0, 6))
        self.play_button = ttk.Button(toolbar, text="Play", command=self.toggle_playback)
        self.play_button.grid(row=0, column=1, padx=(0, 6))
        ttk.Button(toolbar, text="Restart", command=self.restart).grid(row=0, column=2, padx=(0, 14))

        ttk.Label(toolbar, text="Tempo").grid(row=0, column=3, padx=(0, 4))
        ttk.Scale(toolbar, variable=self.tempo, from_=0.4, to=1.5, orient="horizontal", length=160).grid(
            row=0, column=4, padx=(0, 8)
        )
        self.tempo_label = ttk.Label(toolbar, text="100%")
        self.tempo_label.grid(row=0, column=5, padx=(0, 12))
        ttk.Label(toolbar, text="Dynamics").grid(row=0, column=6, padx=(0, 4))
        ttk.Scale(
            toolbar,
            variable=self.dynamics,
            from_=50,
            to=110,
            orient="horizontal",
            length=120,
        ).grid(row=0, column=7, padx=(0, 6))
        self.dynamics_label = ttk.Label(toolbar, text="85%")
        self.dynamics_label.grid(row=0, column=8, sticky="e")
        ttk.Label(toolbar, text="View").grid(row=0, column=9, padx=(12, 4))
        ttk.Radiobutton(
            toolbar,
            text="Roll",
            variable=self.view_mode,
            value="roll",
            command=self._view_mode_changed,
        ).grid(row=0, column=10, sticky="w")
        ttk.Radiobutton(
            toolbar,
            text="Sheet",
            variable=self.view_mode,
            value="sheet",
            command=self._view_mode_changed,
        ).grid(row=0, column=11, sticky="w")

        ttk.Checkbutton(toolbar, text="Send to Roland", variable=self.send_to_piano).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(7, 0)
        )
        ttk.Checkbutton(
            toolbar,
            text="Play on computer",
            variable=self.play_on_computer,
            command=self._computer_output_changed,
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=(7, 0))
        ttk.Checkbutton(
            toolbar,
            text="Wait for keys",
            variable=self.practice_mode,
            command=self._practice_mode_changed,
        ).grid(row=1, column=4, columnspan=2, sticky="w", pady=(7, 0))
        ttk.Checkbutton(
            toolbar,
            text="Show fingers",
            variable=self.show_fingers,
            command=self.draw,
        ).grid(row=1, column=6, columnspan=2, sticky="w", pady=(7, 0))
        ttk.Checkbutton(toolbar, text="Follow", variable=self.follow).grid(
            row=1, column=8, sticky="w", pady=(7, 0)
        )
        ttk.Label(toolbar, text="Practice").grid(row=1, column=9, sticky="e", padx=(10, 4), pady=(7, 0))
        ttk.Radiobutton(
            toolbar,
            text="Both",
            variable=self.practice_hand,
            value="both",
            command=self._practice_hand_changed,
        ).grid(row=1, column=10, sticky="w", pady=(7, 0))
        ttk.Radiobutton(
            toolbar,
            text="Left",
            variable=self.practice_hand,
            value="left",
            command=self._practice_hand_changed,
        ).grid(row=1, column=11, sticky="w", pady=(7, 0))
        ttk.Radiobutton(
            toolbar,
            text="Right",
            variable=self.practice_hand,
            value="right",
            command=self._practice_hand_changed,
        ).grid(row=1, column=12, sticky="w", pady=(7, 0))
        ttk.Button(toolbar, text="Save Project", command=self.save_project_file).grid(
            row=4, column=9, sticky="e", padx=(10, 4), pady=(7, 0)
        )
        ttk.Button(toolbar, text="Load Project", command=self.load_project_file).grid(
            row=4, column=10, sticky="e", pady=(7, 0)
        )

        ttk.Button(toolbar, text="Set A", command=self.set_loop_start).grid(
            row=2, column=0, sticky="w", pady=(7, 0)
        )
        ttk.Button(toolbar, text="Set B", command=self.set_loop_end).grid(
            row=2, column=1, sticky="w", pady=(7, 0)
        )
        ttk.Checkbutton(
            toolbar,
            text="Loop",
            variable=self.loop_enabled,
            command=self._loop_enabled_changed,
        ).grid(row=2, column=2, sticky="w", pady=(7, 0))
        ttk.Button(toolbar, text="Clear", command=self.clear_loop).grid(
            row=2, column=3, sticky="w", pady=(7, 0)
        )
        ttk.Label(toolbar, textvariable=self.loop_text).grid(
            row=2, column=4, columnspan=4, sticky="w", padx=(10, 0), pady=(7, 0)
        )
        ttk.Label(toolbar, text="Piano volume").grid(row=2, column=8, sticky="e", padx=(10, 4), pady=(7, 0))
        ttk.Scale(
            toolbar,
            variable=self.piano_volume,
            from_=0,
            to=100,
            orient="horizontal",
            length=120,
            command=self._piano_volume_changed,
        ).grid(row=2, column=9, sticky="ew", pady=(7, 0))
        self.piano_volume_label = ttk.Label(toolbar, text="50")
        self.piano_volume_label.grid(row=2, column=10, sticky="e", padx=(6, 0), pady=(7, 0))

        ttk.Label(toolbar, text="Position").grid(row=3, column=0, sticky="w", pady=(7, 0))
        self.position_scale = ttk.Scale(
            toolbar,
            variable=self.position,
            from_=0.0,
            to=1.0,
            command=self._position_changed,
            state="disabled",
        )
        self.position_scale.grid(row=3, column=1, columnspan=7, sticky="ew", padx=(6, 8), pady=(7, 0))
        ttk.Label(toolbar, textvariable=self.position_text).grid(row=3, column=8, sticky="e", pady=(7, 0))

        self.status = ttk.Label(toolbar, text="Open a MIDI file to begin.")
        self.status.grid(row=4, column=0, columnspan=9, sticky="ew", pady=(7, 0))

        canvas_background = "#faf9f5" if self.view_mode.get() == "sheet" else "#15171a"
        self.roll = tk.Canvas(self, background=canvas_background, highlightthickness=0)
        self.roll.grid(row=1, column=0, sticky="nsew")
        self.keyboard = tk.Canvas(self, height=150, background="#2b2f35", highlightthickness=0)
        self.keyboard.grid(row=2, column=0, sticky="ew")

        self.bind("<space>", lambda _event: self.toggle_playback())
        self.bind("<Left>", lambda _event: self.seek_relative(-5))
        self.bind("<Right>", lambda _event: self.seek_relative(5))

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open piano song",
            filetypes=[
                ("Songs", "*.mid *.midi *.wav *.mp3 *.flac *.ogg *.m4a *.aac *.aif *.aiff *.opus"),
                ("MIDI", "*.mid *.midi"),
                ("Audio", "*.wav *.mp3 *.flac *.ogg *.m4a *.aac *.aif *.aiff *.opus"),
                ("All files", "*"),
            ],
        )
        if path:
            self.load_file(Path(path))

    def save_project_file(self) -> None:
        if self.song is None:
            messagebox.showwarning("No project to save", "Open a song before saving a project.")
            return
        path = filedialog.asksaveasfilename(
            title="Save piano trainer project",
            defaultextension=".roland-project.json",
            filetypes=[
                ("Roland piano project", "*.roland-project.json"),
                ("JSON", "*.json"),
            ],
            initialfile=f"{self.song.path.stem}.roland-project.json",
        )
        if not path:
            return
        try:
            save_project(self._session_state(include_window=False), Path(path))
        except OSError as exc:
            messagebox.showerror("Could not save project", str(exc))
            return
        self.status.configure(text=f"Project saved: {Path(path).name}")

    def load_project_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Load piano trainer project",
            filetypes=[
                ("Roland piano project", "*.roland-project.json"),
                ("JSON", "*.json"),
                ("All files", "*"),
            ],
        )
        if not path:
            return
        project = load_project(Path(path))
        if not project:
            messagebox.showerror("Could not load project", "This is not a valid Roland piano trainer project.")
            return
        song = project.get("song")
        if not isinstance(song, str) or not Path(song).is_file():
            messagebox.showerror("Song not found", f"The project song could not be found:\n{song or 'No song path'}")
            return

        self.stop_playback(send_off=True)
        self._apply_control_state(project)
        self.pending_song_state = project
        self.load_file(Path(song))

    def _apply_control_state(self, state: dict) -> None:
        numeric_controls = (
            (self.tempo, "tempo", 0.4, 1.5),
            (self.dynamics, "dynamics", 50, 110),
            (self.piano_volume, "piano_volume", 0, 100),
        )
        for variable, key, minimum, maximum in numeric_controls:
            value = state.get(key)
            if isinstance(value, (int, float)):
                variable.set(min(maximum, max(minimum, value)))

        boolean_controls = (
            (self.follow, "follow"),
            (self.send_to_piano, "send_to_piano"),
            (self.play_on_computer, "play_on_computer"),
            (self.practice_mode, "practice_mode"),
            (self.show_fingers, "show_fingers"),
        )
        for variable, key in boolean_controls:
            value = state.get(key)
            if isinstance(value, bool):
                variable.set(value)
        view_mode = state.get("view_mode")
        if view_mode in {"roll", "sheet"}:
            self.view_mode.set(view_mode)
        practice_hand = state.get("practice_hand")
        if practice_hand in {"both", "left", "right"}:
            self.practice_hand.set(practice_hand)

    def _view_mode_changed(self) -> None:
        self.roll.configure(background="#faf9f5" if self.view_mode.get() == "sheet" else "#15171a")
        self.draw()

    def load_file(self, path: Path) -> None:
        self.stop_playback(send_off=True)
        self.status.configure(text=f"Loading {path.name}...")
        self.play_button.configure(state="disabled")

        def worker() -> None:
            try:
                song = load_song(path)
            except (OSError, SongConversionError, ValueError) as exc:
                self.after(0, lambda error=exc: self._load_failed(error))
                return
            self.after(0, lambda: self._load_finished(song))

        threading.Thread(target=worker, daemon=True).start()

    def _load_finished(self, song: Song) -> None:
        self.song = song
        self.note_starts = tuple(note.start for note in song.notes)
        self.playback_event_times = tuple(event.time for event in song.playback_events)
        self.max_note_duration = max((note.duration for note in song.notes), default=0.0)
        self.practice_steps = build_practice_steps(song)
        self.practice_step_starts = tuple(step.start for step in self.practice_steps)
        self.practice_index = 0
        self.practice_waiting = False
        self.pressed_notes.clear()
        self.recent_practice_presses.clear()
        self.paused_at = 0.0
        self._reset_output_playback(0.0)
        self.clear_loop()
        self.position_scale.configure(to=max(song.duration, 0.1), state="normal")
        if self.pending_song_state is not None:
            self._restore_song_state(self.pending_song_state)
            self.pending_song_state = None
        self._update_position_display(force=True)
        self.play_button.configure(state="normal", text="Play")
        self._update_status()
        self.draw()

    def _restore_song_state(self, state: dict) -> None:
        position = state.get("position", 0.0)
        if isinstance(position, (int, float)):
            self.paused_at = min(max(0.0, float(position)), self.song.duration)

        loop_start = state.get("loop_start", 0.0)
        loop_end = state.get("loop_end")
        if isinstance(loop_start, (int, float)):
            self.loop_start = min(max(0.0, float(loop_start)), self.song.duration)
        if isinstance(loop_end, (int, float)) and self.loop_start + 0.05 < float(loop_end) <= self.song.duration:
            self.loop_end = float(loop_end)
            self.loop_enabled.set(bool(state.get("loop_enabled", False)))

        self.practice_waiting = False
        self._set_practice_index_for_time(self.paused_at)
        self._reset_output_playback(self.paused_at)
        self._update_loop_text()

    def _load_failed(self, exc: BaseException) -> None:
        self.play_button.configure(state="normal")
        self.status.configure(text="Could not load song.")
        messagebox.showerror("Could not load song", str(exc))

    def toggle_playback(self) -> None:
        if self.song is None:
            self.open_file()
            return
        if self.playing:
            self.stop_playback(send_off=True)
        else:
            self.start_playback()

    def start_playback(self) -> None:
        if self.practice_mode.get() and not self._ensure_input_port():
            return
        if self._loop_is_active() and not self.loop_start <= self.paused_at < self.loop_end:
            self._move_to_loop_start()
        self.playing = True
        self.started_at = time.monotonic() - (self.paused_at / self.tempo.get())
        self.play_button.configure(text="Pause")
        self._update_status()
        if self.practice_mode.get():
            self.recent_practice_presses.clear()
            return
        if self.send_to_piano.get() and not self._ensure_output_port():
            self.send_to_piano.set(False)
        if self.play_on_computer.get() and not self._ensure_computer_synth():
            self.play_on_computer.set(False)
        if self.send_to_piano.get() or self.play_on_computer.get():
            self._reset_output_playback(self.paused_at)

    def stop_playback(self, send_off: bool = False) -> None:
        if self.playing:
            self.paused_at = self.current_time()
        self.playing = False
        self.play_button.configure(text="Play")
        if send_off:
            self._all_notes_off()
        self._update_status()

    def restart(self) -> None:
        self.stop_playback(send_off=True)
        self.paused_at = 0.0
        self._reset_output_playback(0.0)
        self.pressed_notes.clear()
        self.recent_practice_presses.clear()
        self.practice_index = 0
        self.practice_waiting = False
        self._update_status()
        self.draw()

    def seek_relative(self, seconds: float) -> None:
        if self.song is None:
            return
        self._seek_to(self.current_time() + seconds)

    def _position_changed(self, value: str) -> None:
        if self.updating_position or self.song is None:
            return
        self._seek_to(float(value))

    def _seek_to(self, position: float) -> None:
        if self.song is None:
            return
        self.paused_at = min(max(0.0, position), self.song.duration)
        self._all_notes_off()
        self._reset_output_playback(self.paused_at)
        self._set_practice_index_for_time(self.paused_at)
        self.practice_waiting = False
        self.recent_practice_presses.clear()
        if self.playing:
            self.started_at = time.monotonic() - (self.paused_at / self.tempo.get())
        self._update_position_display(force=True)
        self._update_status()
        self.draw()

    def current_time(self) -> float:
        if self.practice_mode.get() and self.practice_waiting:
            return self.paused_at
        if self.playing:
            return max(0.0, (time.monotonic() - self.started_at) * self.tempo.get())
        return self.paused_at

    def _tick(self) -> None:
        self._update_control_labels()
        if self.song and self.playing:
            now = self.current_time()
            if self._loop_is_active() and now >= self.loop_end:
                self._restart_loop()
                now = self.loop_start
            if self.practice_mode.get():
                now = self._update_practice_wait(now)
            else:
                self._send_due_events(now)
            self._drain_input_messages()
            if self.playing and now >= self.song.duration:
                self.paused_at = self.song.duration
                self.stop_playback(send_off=True)
            self._draw_playback_frame(now)
        else:
            self._drain_input_messages()
        self._update_position_display()
        self.after(16 if self.playing else 50, self._tick)

    def _update_control_labels(self) -> None:
        signature = (
            round(self.tempo.get() * 100),
            self.dynamics.get(),
            round(self.piano_volume.get()),
        )
        if signature == self.control_label_signature:
            return
        self.control_label_signature = signature
        self.tempo_label.configure(text=f"{signature[0]:d}%")
        self.dynamics_label.configure(text=f"{signature[1]}%")
        self.piano_volume_label.configure(text=str(signature[2]))

    def _piano_volume_changed(self, value: str) -> None:
        volume = max(0, min(100, round(float(value))))
        self.piano_volume.set(volume)
        self.piano_volume_label.configure(text=str(volume))
        if self.piano_volume_after_id is not None:
            self.after_cancel(self.piano_volume_after_id)
        self.piano_volume_after_id = self.after(120, self._send_piano_volume)

    def _send_piano_volume(self) -> None:
        self.piano_volume_after_id = None
        if not self._ensure_output_port():
            return
        volume = max(0, min(100, round(self.piano_volume.get())))
        connection_message = RolandMessageRequest(
            register=RolandAddressMap.connection,
            cmd=RolandCmd.WRITE,
            data_as_int=1,
        )
        message = RolandMessageRequest(
            register=RolandAddressMap.masterVolume,
            cmd=RolandCmd.WRITE,
            data_as_int=volume,
        )
        try:
            self.output_port.send(connection_message.as_mido_message)
            self.output_port.send(message.as_mido_message)
        except Exception as exc:
            messagebox.showwarning("Piano volume unavailable", str(exc))

    def _ensure_output_port(self) -> bool:
        if self.output_port is not None:
            return True
        try:
            self.output_port = open_output_port()
        except Exception as exc:
            messagebox.showwarning("Roland output unavailable", str(exc))
            return False
        if self.output_port is None:
            messagebox.showwarning(
                "Roland output unavailable",
                "No Roland Digital Piano MIDI output port was found.",
            )
            return False
        return True

    def _computer_output_changed(self) -> None:
        if not self.play_on_computer.get() and self.computer_synth is not None:
            self.computer_synth.reset(self._playback_channels())
            self.computer_synth.close()
            self.computer_synth = None

    def _ensure_computer_synth(self) -> bool:
        if self.computer_synth is None:
            self.computer_synth = FluidSynthOutput()
        try:
            self.computer_synth.start()
        except ComputerSynthError as exc:
            self.computer_synth.close()
            self.computer_synth = None
            messagebox.showwarning("Computer playback unavailable", str(exc))
            return False
        return True

    def _update_position_display(self, force: bool = False) -> None:
        monotonic_now = time.monotonic()
        if not force and monotonic_now - self.last_position_update_time < self.position_update_interval:
            return
        self.last_position_update_time = monotonic_now
        position = self.current_time()
        self.updating_position = True
        self.position.set(position)
        self.updating_position = False
        self.position_text.set(f"{position:.2f}s")

    def set_loop_start(self) -> None:
        if self.song is None:
            return
        self.loop_start = min(self.current_time(), self.song.duration)
        if self.loop_end is not None and self.loop_end <= self.loop_start + 0.05:
            self.loop_end = None
            self.loop_enabled.set(False)
        self._update_loop_text()
        self._update_status()
        self.draw()

    def set_loop_end(self) -> None:
        if self.song is None:
            return
        position = min(self.current_time(), self.song.duration)
        if position <= self.loop_start + 0.05:
            messagebox.showwarning("Invalid loop", "Loop end B must be after loop start A.")
            return
        self.loop_end = position
        self.loop_enabled.set(True)
        self._update_loop_text()
        self._update_status()
        self.draw()

    def clear_loop(self) -> None:
        self.loop_enabled.set(False)
        self.loop_start = 0.0
        self.loop_end = None
        self._update_loop_text()
        if self.song is not None:
            self._update_status()
            self.draw()

    def _loop_enabled_changed(self) -> None:
        if self.loop_enabled.get() and self.loop_end is None:
            self.loop_enabled.set(False)
            messagebox.showwarning("Loop not set", "Set loop start A and loop end B first.")
        self._update_loop_text()
        self._update_status()

    def _loop_is_active(self) -> bool:
        return self.loop_enabled.get() and self.loop_end is not None and self.loop_end > self.loop_start

    def _restart_loop(self) -> None:
        self._all_notes_off()
        self.pressed_notes.clear()
        self._move_to_loop_start()
        self._reset_output_playback(self.loop_start)
        self.started_at = time.monotonic() - (self.loop_start / self.tempo.get())
        self._update_status()

    def _move_to_loop_start(self) -> None:
        self.paused_at = self.loop_start
        self.practice_waiting = False
        self._set_practice_index_for_time(self.loop_start)

    def _update_loop_text(self) -> None:
        if self.loop_end is None:
            self.loop_text.set(f"Loop: A {self.loop_start:.2f}s, B not set")
            return
        state = "on" if self.loop_enabled.get() else "off"
        self.loop_text.set(f"Loop: A {self.loop_start:.2f}s - B {self.loop_end:.2f}s ({state})")

    def _send_due_events(self, now: float) -> None:
        if self.song is None:
            return
        if not self.send_to_piano.get() and not self.play_on_computer.get():
            return
        events = self.song.playback_events
        while self.playback_event_index < len(events) and events[self.playback_event_index].time <= now:
            event = events[self.playback_event_index]
            self.playback_event_index += 1
            if event.kind == "control_change":
                self._send_playback_message(
                    mido.Message("control_change", control=event.control, value=event.value, channel=event.channel)
                )
                continue

            key = (event.channel, event.note)
            if event.kind == "note_on":
                if key in self.active_output_notes:
                    self._send_playback_message(
                        mido.Message("note_off", note=event.note, velocity=0, channel=event.channel)
                    )
                velocity = shape_velocity(event.velocity, self.dynamics.get())
                self._send_playback_message(
                    mido.Message("note_on", note=event.note, velocity=velocity, channel=event.channel)
                )
                self.active_output_notes[key] = event.note_id
            elif self.active_output_notes.get(key) == event.note_id:
                self._send_playback_message(
                    mido.Message("note_off", note=event.note, velocity=0, channel=event.channel)
                )
                self.active_output_notes.pop(key, None)

    def _send_playback_message(self, message: mido.Message) -> None:
        if self.send_to_piano.get() and self.output_port is not None:
            self.output_port.send(message)
        if self.play_on_computer.get() and self.computer_synth is not None:
            try:
                self.computer_synth.send(message)
            except ComputerSynthError as exc:
                self.play_on_computer.set(False)
                self.computer_synth.close()
                self.computer_synth = None
                messagebox.showwarning("Computer playback stopped", str(exc))

    def _reset_output_playback(self, position: float) -> None:
        self.active_output_notes.clear()
        self.playback_event_index = bisect_left(self.playback_event_times, position)

    def _practice_mode_changed(self) -> None:
        self.stop_playback(send_off=True)
        self.paused_at = 0.0
        self.practice_index = 0
        self.practice_waiting = False
        self.pressed_notes.clear()
        self.recent_practice_presses.clear()
        self._update_status()
        self.draw()

    def _practice_hand_changed(self) -> None:
        if self.song is not None:
            self.stop_playback(send_off=True)
            self.practice_waiting = False
            self._set_practice_index_for_time(self.paused_at)
            self.recent_practice_presses.clear()
        self._update_status()
        self.draw()

    def _ensure_input_port(self) -> bool:
        if self.input_port is not None:
            return True
        try:
            self.input_port = open_input_port(self.input_messages.put)
        except Exception as exc:
            messagebox.showwarning("Piano input unavailable", str(exc))
            return False
        if self.input_port is None:
            messagebox.showwarning(
                "Piano input unavailable",
                "No Roland piano MIDI input was found. Connect the FP-10 by USB and restart the app.",
            )
            return False
        return True

    def _drain_input_messages(self) -> None:
        changed = False
        while True:
            try:
                message = self.input_messages.get_nowait()
            except queue.Empty:
                break
            if message.type == "note_on" and message.velocity > 0:
                self.pressed_notes.add(message.note)
                self.recent_practice_presses[message.note] = time.monotonic()
                changed = True
                self._try_complete_practice_step()
            elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
                self.pressed_notes.discard(message.note)
                changed = True
                self._try_complete_practice_step()
        if changed and self.practice_mode.get():
            self.draw()

    def _update_practice_wait(self, now: float) -> float:
        while self.practice_index < len(self.practice_steps):
            step = self.practice_steps[self.practice_index]
            target = self._practice_target_step(step)
            if target is None and now >= step.start:
                self.practice_index += 1
                continue
            if target is not None and now >= target.start:
                self.paused_at = target.start
                self.practice_waiting = True
                self._update_status()
                self._try_complete_practice_step()
                return target.start
            break
        return now

    def _try_complete_practice_step(self) -> None:
        if not self.playing or not self.practice_mode.get() or not self.practice_waiting:
            return
        step = self._current_practice_step()
        match_notes = self._practice_match_notes()
        if step is None or not practice_step_matches(step, match_notes, self.practice_hand.get()):
            return

        target = self._practice_target_step(step)
        if target is not None:
            for note in target.notes:
                self.recent_practice_presses.pop(note, None)
        self.practice_index += 1
        self.practice_waiting = False
        if self.practice_index >= len(self.practice_steps):
            if self._loop_is_active():
                self._restart_loop()
            else:
                self.paused_at = self.song.duration if self.song else self.paused_at
                self.playing = False
                self.play_button.configure(text="Play")
        else:
            self.started_at = time.monotonic() - (self.paused_at / self.tempo.get())
        self._update_status()

    def _current_practice_step(self) -> Optional[PracticeStep]:
        if 0 <= self.practice_index < len(self.practice_steps):
            return self.practice_steps[self.practice_index]
        return None

    def _current_practice_target_step(self) -> Optional[PracticeStep]:
        step = self._current_practice_step()
        if step is None:
            return None
        return self._practice_target_step(step)

    def _next_practice_target_step(self) -> Optional[PracticeStep]:
        for step in self.practice_steps[self.practice_index :]:
            target = self._practice_target_step(step)
            if target is not None:
                return target
        return None

    def _practice_target_step(self, step: PracticeStep) -> Optional[PracticeStep]:
        return practice_step_for_hand(step, self.practice_hand.get())

    def _practice_match_notes(self) -> Set[int]:
        now = time.monotonic()
        expired = [
            note
            for note, pressed_at in self.recent_practice_presses.items()
            if now - pressed_at > PRACTICE_EARLY_PRESS_GRACE
        ]
        for note in expired:
            self.recent_practice_presses.pop(note, None)
        return set(self.pressed_notes) | set(self.recent_practice_presses)

    def _set_practice_index_for_time(self, position: float) -> None:
        self.practice_index = bisect_left(self.practice_step_starts, position)

    def _update_status(self) -> None:
        if self.song is None:
            self.status.configure(text="Open a MIDI file to begin.")
            return
        if self.practice_mode.get():
            step = self._current_practice_target_step() if self.practice_waiting else self._next_practice_target_step()
            hand_label = self._practice_hand_label()
            if step is None:
                text = f"{self.song.path.name}: practice complete"
            elif self.practice_waiting:
                text = f"Play {hand_label}: {self._step_text(step)}"
            else:
                text = f"{self.song.path.name}: next {hand_label} {self._step_text(step)}"
        else:
            text = f"{self.song.path.name}: {len(self.song.notes)} notes, {self.song.duration:.1f}s"
        if self._loop_is_active():
            text += f" | Loop {self.loop_start:.2f}-{self.loop_end:.2f}s"
        self.status.configure(text=text)

    def _all_notes_off(self) -> None:
        channels = self._playback_channels()
        for channel, note in list(self.active_output_notes):
            self._send_playback_message(mido.Message("note_off", note=note, velocity=0, channel=channel))
        if self.output_port is not None:
            for channel in channels:
                for control in (64, 66, 67):
                    self.output_port.send(
                        mido.Message("control_change", control=control, value=0, channel=channel)
                    )
                self.output_port.send(mido.Message("control_change", control=123, value=0, channel=channel))
        if self.computer_synth is not None:
            self.computer_synth.reset(channels)
        self.active_output_notes.clear()

    def _playback_channels(self) -> Set[int]:
        return {event.channel for event in self.song.playback_events} if self.song else {0}

    def draw(self) -> None:
        self.last_render_time = time.monotonic()
        self.roll.delete("all")
        self.keyboard.delete("all")
        self._draw_main_view()
        self._draw_keyboard()
        self.keyboard_signature = self._current_keyboard_signature()

    def _draw_playback_frame(self, now: float) -> None:
        monotonic_now = time.monotonic()
        if monotonic_now - self.last_render_time < self.render_interval:
            return
        self.last_render_time = monotonic_now

        self.roll.delete("all")
        self._draw_main_view()

        signature = self._current_keyboard_signature(now)
        if signature != self.keyboard_signature:
            self.keyboard.delete("all")
            self._draw_keyboard(now)
            self.keyboard_signature = signature

    def _current_keyboard_signature(self, now: Optional[float] = None) -> tuple:
        if now is None:
            now = self.current_time()
        step = self._current_practice_step()
        target = self._current_practice_target_step()
        expected = tuple(target.notes) if self.practice_waiting and target else tuple()
        finger_labels = tuple(sorted(self._finger_labels(step, set(expected) if expected else None).items()))
        return (
            self.keyboard.winfo_width(),
            self.keyboard.winfo_height(),
            tuple(sorted(self._active_notes_at(now))),
            tuple(sorted(self.pressed_notes)),
            expected,
            finger_labels,
            self.practice_mode.get(),
            self.practice_hand.get(),
        )

    def _draw_main_view(self) -> None:
        if self.view_mode.get() == "sheet":
            self.roll.configure(background="#faf9f5")
            self._draw_sheet_music()
        else:
            self.roll.configure(background="#15171a")
            self._draw_roll()

    def _draw_roll(self) -> None:
        width = max(self.roll.winfo_width(), 1)
        height = max(self.roll.winfo_height(), 1)
        self.roll.create_line(0, height - 42, width, height - 42, fill="#f2c14e", width=2)

        if self.song is None:
            self.roll.create_text(width / 2, height / 2, text="Open a song to begin", fill="#f4f4f4", font=("TkDefaultFont", 22))
            return

        now = self.current_time()
        start_time = now if self.follow.get() else max(0.0, self.paused_at)
        pixels_per_second = (height - 70) / self.preview_seconds
        key_width = width / (HIGH_NOTE - LOW_NOTE + 1)

        visible_notes = self._notes_in_window(start_time - 0.4, start_time + self.preview_seconds)
        for note in visible_notes:
            x1 = (note.note - LOW_NOTE) * key_width
            x2 = x1 + key_width
            y2 = height - 42 - ((note.start - start_time) * pixels_per_second)
            y1 = height - 42 - ((note.end - start_time) * pixels_per_second)
            fill = "#2f80ed" if note.note < 60 else "#27ae60"
            if note.start <= now <= note.end:
                fill = "#f2c14e"
            self.roll.create_rectangle(x1, y1, x2, y2, fill=fill, outline="")

        self._draw_loop_marker(self.loop_start, "A", "#27ae60", start_time, pixels_per_second, width, height)
        if self.loop_end is not None:
            self._draw_loop_marker(self.loop_end, "B", "#d64545", start_time, pixels_per_second, width, height)

        next_index = bisect_left(self.note_starts, now)
        next_notes = self.song.notes[next_index : next_index + 8]
        step = self._current_practice_target_step() if self.practice_mode.get() else None
        if self.practice_waiting and step is not None:
            text = self._step_text(step)
            self.roll.create_text(
                width / 2,
                height - 68,
                text=f"PLAY  {text}",
                fill="#f2c14e",
                anchor="s",
                font=("TkDefaultFont", 20, "bold"),
            )
        elif next_notes:
            text = "  ".join(note.name for note in next_notes)
            self.roll.create_text(14, 16, text=f"Next: {text}", fill="#e8e8e8", anchor="nw", font=("TkDefaultFont", 14))
        self.roll.create_text(width - 14, 16, text=f"{now:.1f} / {self.song.duration:.1f}s", fill="#e8e8e8", anchor="ne")

    def _draw_loop_marker(
        self,
        position: float,
        label: str,
        color: str,
        start_time: float,
        pixels_per_second: float,
        width: int,
        height: int,
    ) -> None:
        if self.loop_end is None:
            return
        y = height - 42 - ((position - start_time) * pixels_per_second)
        if not 0 <= y <= height:
            return
        self.roll.create_line(0, y, width, y, fill=color, width=2, dash=(6, 4))
        self.roll.create_text(8, y - 4, text=label, fill=color, anchor="sw", font=("TkDefaultFont", 10, "bold"))

    def _draw_sheet_music(self) -> None:
        width = max(self.roll.winfo_width(), 1)
        height = max(self.roll.winfo_height(), 1)
        ink = "#24272c"
        muted = "#777b82"
        staff_left = 72
        staff_right = width - 24
        line_spacing = max(10, min(16, height // 34))
        treble_top = max(52, int(height * 0.20))
        bass_top = min(height - line_spacing * 5 - 42, int(height * 0.58))

        for top, label in ((treble_top, "TREBLE"), (bass_top, "BASS")):
            for line in range(5):
                y = top + line * line_spacing
                self.roll.create_line(staff_left, y, staff_right, y, fill=ink, width=1)
            self.roll.create_text(
                staff_left - 10,
                top + line_spacing * 2,
                text=label,
                fill=muted,
                anchor="e",
                font=("TkDefaultFont", 9, "bold"),
            )
        self.roll.create_line(
            staff_left,
            treble_top,
            staff_left,
            bass_top + line_spacing * 4,
            fill=ink,
            width=2,
        )

        if self.song is None:
            self.roll.create_text(
                width / 2,
                height / 2,
                text="Open a song to begin",
                fill=ink,
                font=("TkDefaultFont", 22),
            )
            return

        now = self.current_time()
        past_seconds = 1.5
        future_seconds = 5.0
        usable_width = max(1, staff_right - staff_left)
        play_x = staff_left + usable_width * past_seconds / (past_seconds + future_seconds)
        pixels_per_second = usable_width / (past_seconds + future_seconds)
        self.roll.create_line(
            play_x,
            treble_top - 28,
            play_x,
            bass_top + line_spacing * 4 + 28,
            fill="#d39b22",
            width=2,
        )

        visible_notes = self._notes_in_window(now - past_seconds, now + future_seconds)
        target_step = self._current_practice_target_step() if self.practice_waiting else None
        target_notes = set(target_step.notes) if target_step else set()

        for note in visible_notes:
            x = play_x + (note.start - now) * pixels_per_second
            clef = "treble" if note.note >= 60 else "bass"
            top = treble_top if clef == "treble" else bass_top
            step, accidental = staff_note_position(note.note, clef)
            bottom_line_y = top + line_spacing * 4
            y = bottom_line_y - step * (line_spacing / 2)

            is_active = note.start <= now <= note.end
            is_target = (
                target_step is not None
                and note.note in target_notes
                and abs(note.start - target_step.start) <= 0.04
            )
            if is_target and note.note in self.pressed_notes:
                color = "#278a52"
            elif is_target:
                color = "#2374c6"
            elif is_active:
                color = "#d39b22"
            else:
                color = ink

            self._draw_ledger_lines(x, y, step, bottom_line_y, line_spacing, color)
            if accidental:
                self.roll.create_text(
                    x - 11,
                    y,
                    text="#",
                    fill=color,
                    anchor="e",
                    font=("TkDefaultFont", 10, "bold"),
                )

            note_width = max(8, line_spacing * 0.9)
            note_height = max(6, line_spacing * 0.62)
            fill = color if note.duration < 0.8 else "#faf9f5"
            self.roll.create_oval(
                x - note_width / 2,
                y - note_height / 2,
                x + note_width / 2,
                y + note_height / 2,
                fill=fill,
                outline=color,
                width=2,
            )
            stem_up = step < 4
            stem_x = x + note_width / 2 if stem_up else x - note_width / 2
            stem_end = y - line_spacing * 2.8 if stem_up else y + line_spacing * 2.8
            self.roll.create_line(stem_x, y, stem_x, stem_end, fill=color, width=2)

        self._draw_sheet_loop_marker(
            self.loop_start,
            "A",
            "#278a52",
            now,
            play_x,
            pixels_per_second,
            treble_top,
            bass_top + line_spacing * 4,
        )
        if self.loop_end is not None:
            self._draw_sheet_loop_marker(
                self.loop_end,
                "B",
                "#c74747",
                now,
                play_x,
                pixels_per_second,
                treble_top,
                bass_top + line_spacing * 4,
            )

        if target_step is not None:
            self.roll.create_text(
                width / 2,
                18,
                text=f"PLAY  {self._step_text(target_step)}",
                fill="#2374c6",
                anchor="n",
                font=("TkDefaultFont", 16, "bold"),
            )
        self.roll.create_text(
            width - 14,
            16,
            text=f"{now:.1f} / {self.song.duration:.1f}s",
            fill=muted,
            anchor="ne",
        )

    def _draw_ledger_lines(
        self,
        x: float,
        y: float,
        step: int,
        bottom_line_y: float,
        line_spacing: int,
        color: str,
    ) -> None:
        ledger_width = line_spacing * 1.35
        if step <= -2:
            for ledger_step in range(-2, step - 1, -2):
                ledger_y = bottom_line_y - ledger_step * (line_spacing / 2)
                self.roll.create_line(x - ledger_width, ledger_y, x + ledger_width, ledger_y, fill=color)
        elif step >= 10:
            for ledger_step in range(10, step + 1, 2):
                ledger_y = bottom_line_y - ledger_step * (line_spacing / 2)
                self.roll.create_line(x - ledger_width, ledger_y, x + ledger_width, ledger_y, fill=color)

    def _draw_sheet_loop_marker(
        self,
        position: float,
        label: str,
        color: str,
        now: float,
        play_x: float,
        pixels_per_second: float,
        top: float,
        bottom: float,
    ) -> None:
        if self.loop_end is None:
            return
        x = play_x + (position - now) * pixels_per_second
        if not 0 <= x <= self.roll.winfo_width():
            return
        self.roll.create_line(x, top - 12, x, bottom + 12, fill=color, width=2, dash=(5, 4))
        self.roll.create_text(x + 4, top - 14, text=label, fill=color, anchor="sw", font=("TkDefaultFont", 10, "bold"))

    def _draw_keyboard(self, now: Optional[float] = None) -> None:
        width = max(self.keyboard.winfo_width(), 1)
        height = max(self.keyboard.winfo_height(), 1)
        active = self._active_notes_at(self.current_time() if now is None else now)
        step = self._current_practice_step()
        target = self._current_practice_target_step()
        expected = set(target.notes) if self.practice_waiting and target else set()
        finger_labels = self._finger_labels(step, expected if expected else None)
        white_notes = [note for note in range(LOW_NOTE, HIGH_NOTE + 1) if note % 12 in WHITE_KEY_PATTERN]
        white_width = width / len(white_notes)
        white_positions: Dict[int, Tuple[float, float]] = {}

        for index, note in enumerate(white_notes):
            x1 = index * white_width
            x2 = x1 + white_width
            white_positions[note] = (x1, x2)
            fill = self._key_fill(note, active, expected, black=False)
            self.keyboard.create_rectangle(x1, 0, x2, height, fill=fill, outline="#444")
            if note % 12 == 0:
                self.keyboard.create_text((x1 + x2) / 2, height - 16, text=note_name(note), fill="#30343a", font=("TkDefaultFont", 9))

        black_positions: Dict[int, Tuple[float, float]] = {}
        for note in range(LOW_NOTE, HIGH_NOTE + 1):
            if not is_black_key(note):
                continue
            previous_white = max(candidate for candidate in white_positions if candidate < note)
            x1, x2 = white_positions[previous_white]
            black_width = white_width * 0.62
            center = x2
            fill = self._key_fill(note, active, expected, black=True)
            self.keyboard.create_rectangle(center - black_width / 2, 0, center + black_width / 2, height * 0.62, fill=fill, outline="#111")
            black_positions[note] = (center - black_width / 2, center + black_width / 2)

        for note, label in finger_labels.items():
            if note in black_positions:
                x1, x2 = black_positions[note]
                y = height * 0.47
                fill = "#ffffff"
            elif note in white_positions:
                x1, x2 = white_positions[note]
                y = height - 38
                fill = "#20242a"
            else:
                continue
            self.keyboard.create_text(
                (x1 + x2) / 2,
                y,
                text=label,
                fill=fill,
                font=("TkDefaultFont", 9, "bold"),
            )

    def _step_text(self, step: PracticeStep) -> str:
        labels = self._finger_labels(self._current_practice_step() or step, set(step.notes))
        return " + ".join(
            f"{note_name(note)} ({labels[note]})" if note in labels else note_name(note)
            for note in step.notes
        )

    def _finger_labels(self, step: Optional[PracticeStep], notes: Optional[Set[int]] = None) -> Dict[int, str]:
        if not self.practice_mode.get() or not self.show_fingers.get() or step is None:
            return {}
        return {
            suggestion.note: suggestion.label
            for suggestion in suggest_fingering(step)
            if notes is None or suggestion.note in notes
        }

    def _key_fill(self, note: int, active: Set[int], expected: Set[int], black: bool) -> str:
        if self.practice_mode.get():
            if note in self.pressed_notes and note not in expected and self._practice_note_is_relevant(note, expected):
                return "#d64545"
            if note in self.pressed_notes and note in expected:
                return "#27ae60"
            if note in expected:
                return "#2f80ed"
        if note in active:
            return "#f2c14e"
        return "#15171a" if black else "#f7f7f3"

    def _practice_hand_label(self) -> str:
        return {
            "both": "both hands",
            "left": "left hand",
            "right": "right hand",
        }.get(self.practice_hand.get(), "both hands")

    def _practice_note_is_relevant(self, note: int, expected: Set[int]) -> bool:
        hand = self.practice_hand.get()
        if hand == "left":
            return note < 60 or note in expected
        if hand == "right":
            return note >= 60 or note in expected
        return True

    def _active_notes(self) -> Set[int]:
        return self._active_notes_at(self.current_time())

    def _active_notes_at(self, now: float) -> Set[int]:
        return {note.note for note in self._notes_in_window(now, now) if note.start <= now <= note.end}

    def _notes_in_window(self, window_start: float, window_end: float):
        if self.song is None or not self.song.notes:
            return tuple()
        first_possible_start = window_start - self.max_note_duration
        first = bisect_left(self.note_starts, first_possible_start)
        last = bisect_right(self.note_starts, window_end)
        return tuple(note for note in self.song.notes[first:last] if note.end >= window_start)

    def _session_state(self, include_window: bool) -> dict:
        state = {
            "song": str(self.song.path) if self.song is not None else None,
            "position": self.current_time(),
            "tempo": self.tempo.get(),
            "dynamics": self.dynamics.get(),
            "piano_volume": self.piano_volume.get(),
            "follow": self.follow.get(),
            "send_to_piano": self.send_to_piano.get(),
            "play_on_computer": self.play_on_computer.get(),
            "practice_mode": self.practice_mode.get(),
            "practice_hand": self.practice_hand.get(),
            "show_fingers": self.show_fingers.get(),
            "view_mode": self.view_mode.get(),
            "loop_start": self.loop_start,
            "loop_end": self.loop_end,
            "loop_enabled": self.loop_enabled.get(),
        }
        if not include_window:
            return state
        try:
            maximized = bool(self.attributes("-zoomed"))
        except tk.TclError:
            maximized = False
        state["geometry"] = self.geometry()
        state["maximized"] = maximized
        return state

    def _close_app(self) -> None:
        try:
            save_app_state(self._session_state(include_window=True))
        except OSError:
            pass
        self.destroy()

    def destroy(self) -> None:
        if self.piano_volume_after_id is not None:
            self.after_cancel(self.piano_volume_after_id)
        self._all_notes_off()
        if self.output_port is not None:
            self.output_port.close()
        if self.computer_synth is not None:
            self.computer_synth.close()
        if self.input_port is not None:
            self.input_port.close()
        super().destroy()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show how to play MIDI/audio songs on a Roland FP-10 style keyboard.")
    parser.add_argument("song", nargs="?", help="MIDI file, or audio file when an external converter is configured")
    parser.add_argument("--send-to-piano", action="store_true", help="play MIDI notes through the first Roland output port")
    parser.add_argument("--play-on-computer", action="store_true", help="play MIDI through FluidSynth and computer audio")
    args = parser.parse_args(argv)

    app = PianoTrainerApp(
        initial_song=args.song,
        send_to_piano=args.send_to_piano,
        play_on_computer=args.play_on_computer,
    )
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
