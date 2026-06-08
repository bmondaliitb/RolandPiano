from __future__ import annotations

import argparse
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Set, Tuple

import mido

from .song_trainer import Song, SongConversionError, is_black_key, load_song, note_name, open_output_port


LOW_NOTE = 21
HIGH_NOTE = 108
WHITE_KEY_PATTERN = {0, 2, 4, 5, 7, 9, 11}


class PianoTrainerApp(tk.Tk):
    def __init__(self, initial_song: Optional[str] = None, send_to_piano: bool = False) -> None:
        super().__init__()
        self.title("Roland FP-10 Piano Trainer")
        self.geometry("1180x760")
        self.minsize(900, 620)

        self.song: Optional[Song] = None
        self.playing = False
        self.started_at = 0.0
        self.paused_at = 0.0
        self.tempo = tk.DoubleVar(value=1.0)
        self.follow = tk.BooleanVar(value=True)
        self.send_to_piano = tk.BooleanVar(value=send_to_piano)
        self.output_port = None
        self.sent_note_ons: Set[Tuple[int, int]] = set()
        self.preview_seconds = 5.0

        self._build_ui()
        self.after(16, self._tick)

        if initial_song:
            self.load_file(Path(initial_song))

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(7, weight=1)

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

        ttk.Checkbutton(toolbar, text="Send to Roland", variable=self.send_to_piano).grid(row=0, column=6, padx=(0, 10))
        ttk.Checkbutton(toolbar, text="Follow", variable=self.follow).grid(row=0, column=7, sticky="w")

        self.status = ttk.Label(toolbar, text="Open a MIDI file, or an audio file if Basic Pitch is installed.")
        self.status.grid(row=0, column=8, sticky="e")

        self.roll = tk.Canvas(self, background="#15171a", highlightthickness=0)
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
        self.paused_at = 0.0
        self.sent_note_ons.clear()
        self.play_button.configure(state="normal", text="Play")
        self.status.configure(text=f"{song.path.name}: {len(song.notes)} notes, {song.duration:.1f}s")
        self.draw()

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
        self.playing = True
        self.started_at = time.monotonic() - (self.paused_at / self.tempo.get())
        self.play_button.configure(text="Pause")
        if self.send_to_piano.get() and self.output_port is None:
            try:
                self.output_port = open_output_port()
            except OSError as exc:
                self.send_to_piano.set(False)
                messagebox.showwarning("Roland output unavailable", str(exc))
            else:
                if self.output_port is not None:
                    return
                self.send_to_piano.set(False)
                messagebox.showwarning("Roland output unavailable", "No Roland Digital Piano MIDI output port was found.")

    def stop_playback(self, send_off: bool = False) -> None:
        if self.playing:
            self.paused_at = self.current_time()
        self.playing = False
        self.play_button.configure(text="Play")
        if send_off:
            self._all_notes_off()

    def restart(self) -> None:
        self.stop_playback(send_off=True)
        self.paused_at = 0.0
        self.sent_note_ons.clear()
        self.draw()

    def seek_relative(self, seconds: float) -> None:
        if self.song is None:
            return
        self.paused_at = min(max(0.0, self.current_time() + seconds), self.song.duration)
        self.sent_note_ons.clear()
        if self.playing:
            self.started_at = time.monotonic() - (self.paused_at / self.tempo.get())
        self._all_notes_off()
        self.draw()

    def current_time(self) -> float:
        if self.playing:
            return max(0.0, (time.monotonic() - self.started_at) * self.tempo.get())
        return self.paused_at

    def _tick(self) -> None:
        self.tempo_label.configure(text=f"{round(self.tempo.get() * 100):d}%")
        if self.song and self.playing:
            now = self.current_time()
            self._send_due_notes(now)
            if now >= self.song.duration:
                self.paused_at = self.song.duration
                self.stop_playback(send_off=True)
            self.draw()
        self.after(16, self._tick)

    def _send_due_notes(self, now: float) -> None:
        if not self.send_to_piano.get() or self.output_port is None or self.song is None:
            return
        for note in self.song.notes:
            key = (note.channel, note.note)
            if note.start <= now <= note.end and key not in self.sent_note_ons:
                self.output_port.send(mido.Message("note_on", note=note.note, velocity=max(note.velocity, 30), channel=note.channel))
                self.sent_note_ons.add(key)
            elif now > note.end and key in self.sent_note_ons:
                self.output_port.send(mido.Message("note_off", note=note.note, velocity=0, channel=note.channel))
                self.sent_note_ons.remove(key)

    def _all_notes_off(self) -> None:
        if self.output_port is not None:
            for channel, note in list(self.sent_note_ons):
                self.output_port.send(mido.Message("note_off", note=note, velocity=0, channel=channel))
        self.sent_note_ons.clear()

    def draw(self) -> None:
        self.roll.delete("all")
        self.keyboard.delete("all")
        self._draw_roll()
        self._draw_keyboard()

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

        visible_notes = [note for note in self.song.notes if start_time - 0.4 <= note.end and note.start <= start_time + self.preview_seconds]
        for note in visible_notes:
            x1 = (note.note - LOW_NOTE) * key_width
            x2 = x1 + key_width
            y2 = height - 42 - ((note.start - start_time) * pixels_per_second)
            y1 = height - 42 - ((note.end - start_time) * pixels_per_second)
            fill = "#2f80ed" if note.note < 60 else "#27ae60"
            if note.start <= now <= note.end:
                fill = "#f2c14e"
            self.roll.create_rectangle(x1, y1, x2, y2, fill=fill, outline="")

        next_notes = [note for note in self.song.notes if note.start >= now][:8]
        if next_notes:
            text = "  ".join(note.name for note in next_notes)
            self.roll.create_text(14, 16, text=f"Next: {text}", fill="#e8e8e8", anchor="nw", font=("TkDefaultFont", 14))
        self.roll.create_text(width - 14, 16, text=f"{now:.1f} / {self.song.duration:.1f}s", fill="#e8e8e8", anchor="ne")

    def _draw_keyboard(self) -> None:
        width = max(self.keyboard.winfo_width(), 1)
        height = max(self.keyboard.winfo_height(), 1)
        active = self._active_notes()
        white_notes = [note for note in range(LOW_NOTE, HIGH_NOTE + 1) if note % 12 in WHITE_KEY_PATTERN]
        white_width = width / len(white_notes)
        white_positions: Dict[int, Tuple[float, float]] = {}

        for index, note in enumerate(white_notes):
            x1 = index * white_width
            x2 = x1 + white_width
            white_positions[note] = (x1, x2)
            fill = "#f2c14e" if note in active else "#f7f7f3"
            self.keyboard.create_rectangle(x1, 0, x2, height, fill=fill, outline="#444")
            if note % 12 == 0:
                self.keyboard.create_text((x1 + x2) / 2, height - 16, text=note_name(note), fill="#30343a", font=("TkDefaultFont", 9))

        for note in range(LOW_NOTE, HIGH_NOTE + 1):
            if not is_black_key(note):
                continue
            previous_white = max(candidate for candidate in white_positions if candidate < note)
            x1, x2 = white_positions[previous_white]
            black_width = white_width * 0.62
            center = x2
            fill = "#f2c14e" if note in active else "#15171a"
            self.keyboard.create_rectangle(center - black_width / 2, 0, center + black_width / 2, height * 0.62, fill=fill, outline="#111")

    def _active_notes(self) -> Set[int]:
        if self.song is None:
            return set()
        now = self.current_time()
        return {note.note for note in self.song.notes if note.start <= now <= note.end}

    def destroy(self) -> None:
        self._all_notes_off()
        if self.output_port is not None:
            self.output_port.close()
        super().destroy()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Show how to play MIDI/audio songs on a Roland FP-10 style keyboard.")
    parser.add_argument("song", nargs="?", help="MIDI file, or audio file when basic-pitch is installed")
    parser.add_argument("--send-to-piano", action="store_true", help="play MIDI notes through the first Roland output port")
    args = parser.parse_args(argv)

    app = PianoTrainerApp(initial_song=args.song, send_to_piano=args.send_to_piano)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
