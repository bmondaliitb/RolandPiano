from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Union

import mido


MIDI_EXTENSIONS = {".mid", ".midi"}
AUDIO_EXTENSIONS = {".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}


class SongConversionError(RuntimeError):
    pass


@dataclass(frozen=True)
class NoteEvent:
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
    path: Path
    notes: tuple[NoteEvent, ...]
    duration: float


@dataclass(frozen=True)
class PracticeStep:
    start: float
    notes: tuple[int, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(note_name(note) for note in self.notes)


def note_name(note: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    octave = note // 12 - 1
    return f"{names[note % 12]}{octave}"


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
    return Song(path=midi_path, notes=notes, duration=duration)


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


def practice_step_matches(step: PracticeStep, pressed_notes: Set[int]) -> bool:
    return pressed_notes == set(step.notes)


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
