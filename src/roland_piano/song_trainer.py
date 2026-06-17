from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple, Union

import mido


MIDI_EXTENSIONS = {".mid", ".midi"}
AUDIO_EXTENSIONS = {".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}


class SongConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NoteEvent:
    __slots__ = ("note", "start", "end", "velocity", "channel")

    note: int
    start: float
    end: float
    velocity: int
    channel: int

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def name(self) -> str:
        return note_name(self.note)


@dataclass(frozen=True)
class Song:
    __slots__ = ("path", "notes", "duration", "playback_events")

    path: Path
    notes: tuple[NoteEvent, ...]
    duration: float
    playback_events: tuple["PlaybackEvent", ...]


class PlaybackEvent(NamedTuple):
    time: float
    kind: str
    channel: int
    note: int = 0
    velocity: int = 0
    control: int = 0
    value: int = 0
    note_id: int = -1


@dataclass(frozen=True)
class PracticeStep:
    __slots__ = ("start", "notes")

    start: float
    notes: tuple[int, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(note_name(note) for note in self.notes)


@dataclass(frozen=True)
class FingerSuggestion:
    __slots__ = ("note", "hand", "finger")

    note: int
    hand: str
    finger: int

    @property
    def label(self) -> str:
        return f"{self.hand}{self.finger}"


def note_name(note: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    octave = note // 12 - 1
    return f"{names[note % 12]}{octave}"


def staff_note_position(note: int, clef: str) -> Tuple[int, bool]:
    pitch_class = note % 12
    octave = note // 12 - 1
    letter_by_pitch_class = (0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)
    accidental = pitch_class in {1, 3, 6, 8, 10}
    diatonic_index = octave * 7 + letter_by_pitch_class[pitch_class]

    if clef == "treble":
        bottom_line = 4 * 7 + 2  # E4
    elif clef == "bass":
        bottom_line = 2 * 7 + 4  # G2
    else:
        raise ValueError(f"Unknown clef: {clef}")
    return diatonic_index - bottom_line, accidental


def is_black_key(note: int) -> bool:
    return note % 12 in {1, 3, 6, 8, 10}


PathLike = Union[str, Path]


def convert_to_midi(source: PathLike, output_dir: Optional[PathLike] = None) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    suffix = source_path.suffix.lower()
    if suffix in MIDI_EXTENSIONS:
        return source_path
    if suffix not in AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(MIDI_EXTENSIONS | AUDIO_EXTENSIONS))
        raise SongConversionError(f"Unsupported file type '{suffix}'. Supported: {supported}")

    destination = Path(output_dir).expanduser().resolve() if output_dir else source_path.parent / "converted-midi"
    destination.mkdir(parents=True, exist_ok=True)

    converter_command = os.environ.get("AUDIO_TO_MIDI_COMMAND")
    basic_pitch = os.environ.get("BASIC_PITCH") or shutil.which("basic-pitch")
    if converter_command:
        command = _audio_converter_command(converter_command, source_path, destination)
    elif basic_pitch:
        command = [basic_pitch, str(destination), str(source_path)]
    else:
        raise SongConversionError(
            "Audio-to-MIDI conversion needs an external converter command.\n\n"
            "MIDI files work directly. For audio files, either convert the song to MIDI first, or set "
            "AUDIO_TO_MIDI_COMMAND to a command that writes a .mid/.midi file into {output_dir}.\n\n"
            'Example format: AUDIO_TO_MIDI_COMMAND=\'converter "{input}" "{output_dir}"\''
        )

    before = set(_midi_files(destination))
    with tempfile.TemporaryDirectory(prefix="roland-piano-basic-pitch-") as work_dir:
        try:
            subprocess.run(command, cwd=work_dir, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "").strip()
            raise SongConversionError(f"The audio-to-MIDI converter failed.\n{details}") from exc

    after = set(_midi_files(destination))
    new_files = sorted(after - before, key=lambda item: item.stat().st_mtime, reverse=True)
    candidates = new_files or sorted(after, key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise SongConversionError("The audio-to-MIDI converter finished, but no MIDI file was produced.")
    return candidates[0]


def load_song(source: PathLike) -> Song:
    midi_path = convert_to_midi(source)
    midi = mido.MidiFile(midi_path)
    notes = tuple(_extract_notes(midi))
    duration = max((note.end for note in notes), default=midi.length if midi.length else 0.0)
    playback_events = tuple(_build_playback_events(midi, notes))
    return Song(path=midi_path, notes=notes, duration=duration, playback_events=playback_events)


def shape_velocity(velocity: int, dynamics_percent: int) -> int:
    if velocity <= 0:
        return 0
    return max(1, min(127, round(velocity * dynamics_percent / 100)))


def build_practice_steps(song: Song, chord_tolerance: float = 0.04) -> Tuple[PracticeStep, ...]:
    steps: List[PracticeStep] = []
    group_start: Optional[float] = None
    group_notes: Set[int] = set()

    for event in song.notes:
        if group_start is None or event.start - group_start <= chord_tolerance:
            if group_start is None:
                group_start = event.start
            group_notes.add(event.note)
            continue

        steps.append(PracticeStep(start=group_start, notes=tuple(sorted(group_notes))))
        group_start = event.start
        group_notes = {event.note}

    if group_start is not None:
        steps.append(PracticeStep(start=group_start, notes=tuple(sorted(group_notes))))
    return tuple(steps)


def practice_step_for_hand(step: PracticeStep, hand: str) -> Optional[PracticeStep]:
    if hand == "both":
        return step
    left_notes, right_notes = _split_hands(step.notes)
    if hand == "left":
        notes = left_notes
    elif hand == "right":
        notes = right_notes
    else:
        raise ValueError(f"Unknown practice hand: {hand}")
    if not notes:
        return None
    return PracticeStep(start=step.start, notes=notes)


def practice_step_matches(step: PracticeStep, pressed_notes: Set[int], hand: str = "both") -> bool:
    target = practice_step_for_hand(step, hand)
    if target is None:
        return True
    if hand == "both":
        relevant_pressed = pressed_notes
    elif hand == "left":
        relevant_pressed = {note for note in pressed_notes if note < 60 or note in target.notes}
    elif hand == "right":
        relevant_pressed = {note for note in pressed_notes if note >= 60 or note in target.notes}
    else:
        raise ValueError(f"Unknown practice hand: {hand}")
    return relevant_pressed == set(target.notes)


def suggest_fingering(step: PracticeStep) -> Tuple[FingerSuggestion, ...]:
    left_notes, right_notes = _split_hands(step.notes)
    suggestions = _finger_hand(left_notes, hand="L")
    suggestions.extend(_finger_hand(right_notes, hand="R"))
    return tuple(sorted(suggestions, key=lambda suggestion: suggestion.note))


def _split_hands(notes: Tuple[int, ...]) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    ordered = tuple(sorted(notes))
    if len(ordered) <= 5:
        left = tuple(note for note in ordered if note < 60)
        right = tuple(note for note in ordered if note >= 60)
        return left, right

    split = sum(note < 60 for note in ordered)
    split = max(len(ordered) - 5, min(5, split))
    return ordered[:split], ordered[split:]


def _finger_hand(notes: Tuple[int, ...], hand: str) -> List[FingerSuggestion]:
    if not notes:
        return []
    if len(notes) == 1:
        finger = _single_note_finger(notes[0], hand)
        return [FingerSuggestion(note=notes[0], hand=hand, finger=finger)]

    right_patterns = {
        2: (1, 5),
        3: (1, 3, 5),
        4: (1, 2, 3, 5),
        5: (1, 2, 3, 4, 5),
    }
    fingers = right_patterns.get(len(notes), tuple(min(index + 1, 5) for index in range(len(notes))))
    if hand == "L":
        fingers = tuple(reversed(fingers))
    return [
        FingerSuggestion(note=note, hand=hand, finger=finger)
        for note, finger in zip(sorted(notes), fingers)
    ]


def _single_note_finger(note: int, hand: str) -> int:
    right_by_pitch_class = (1, 2, 2, 3, 3, 1, 2, 2, 3, 3, 4, 4)
    left_by_pitch_class = (1, 2, 2, 3, 3, 4, 4, 5, 4, 3, 2, 2)
    return right_by_pitch_class[note % 12] if hand == "R" else left_by_pitch_class[note % 12]


def _midi_files(directory: Path) -> List[Path]:
    return [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in MIDI_EXTENSIONS]


def _audio_converter_command(template: str, source_path: Path, destination: Path) -> List[str]:
    formatted = template.format(input=str(source_path), output_dir=str(destination))
    return shlex.split(formatted)


def _extract_notes(midi: mido.MidiFile) -> Iterable[NoteEvent]:
    events: List[NoteEvent] = []
    absolute_seconds = 0.0
    active: Dict[Tuple[int, int], List[Tuple[float, int]]] = {}

    for message in midi:
        absolute_seconds += message.time

        if hasattr(message, "channel") and message.channel == 9:
            continue

        if message.type == "note_on" and message.velocity > 0:
            active.setdefault((message.channel, message.note), []).append((absolute_seconds, message.velocity))
            continue

        if message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            key = (message.channel, message.note)
            starts = active.get(key)
            if not starts:
                continue
            start, velocity = starts.pop(0)
            if not starts:
                active.pop(key, None)
            events.append(
                NoteEvent(
                    note=message.note,
                    start=start,
                    end=max(start, absolute_seconds),
                    velocity=velocity,
                    channel=message.channel,
                )
            )

    for (channel, note), starts in active.items():
        for start, velocity in starts:
            events.append(NoteEvent(note=note, start=start, end=absolute_seconds, velocity=velocity, channel=channel))

    return sorted(events, key=lambda event: (event.start, event.note))


def _build_playback_events(midi: mido.MidiFile, notes: Tuple[NoteEvent, ...]) -> Iterable[PlaybackEvent]:
    events: List[PlaybackEvent] = []
    for note_id, note in enumerate(notes):
        events.append(
            PlaybackEvent(
                time=note.start,
                kind="note_on",
                channel=note.channel,
                note=note.note,
                velocity=note.velocity,
                note_id=note_id,
            )
        )
        events.append(
            PlaybackEvent(
                time=note.end,
                kind="note_off",
                channel=note.channel,
                note=note.note,
                note_id=note_id,
            )
        )

    absolute_seconds = 0.0
    for message in midi:
        absolute_seconds += message.time
        if message.type == "control_change" and message.channel != 9 and message.control in {64, 66, 67}:
            events.append(
                PlaybackEvent(
                    time=absolute_seconds,
                    kind="control_change",
                    channel=message.channel,
                    control=message.control,
                    value=message.value,
                )
            )

    priority = {"note_off": 0, "control_change": 1, "note_on": 2}
    return sorted(events, key=lambda event: (event.time, priority[event.kind], event.note))


def open_output_port(name: Optional[str] = None):
    if name:
        return mido.open_output(name)

    roland_ports = [port for port in mido.get_output_names() if port.startswith("Roland Digital Piano")]
    if roland_ports:
        return mido.open_output(roland_ports[0])
    return None


def open_input_port(callback: Callable, name: Optional[str] = None):
    if name:
        return mido.open_input(name, callback=callback)

    input_names = mido.get_input_names()
    roland_ports = [port for port in input_names if "roland" in port.lower()]
    if roland_ports:
        return mido.open_input(roland_ports[0], callback=callback)
    if len(input_names) == 1:
        return mido.open_input(input_names[0], callback=callback)
    return None
