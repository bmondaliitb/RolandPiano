from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Iterable, Optional

import mido


class ComputerSynthError(RuntimeError):
    pass


SOUNDFONT_CANDIDATES = (
    "/usr/share/soundfonts/FluidR3_GM.sf2",
    "/usr/share/soundfonts/default.sf2",
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/default-GM.sf2",
)


def find_soundfont() -> Optional[Path]:
    configured = os.environ.get("PIANO_SOUNDFONT")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path.resolve()

    for candidate in SOUNDFONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path

    for directory in (Path("/usr/share/soundfonts"), Path("/usr/share/sounds/sf2")):
        if directory.is_dir():
            matches = sorted(directory.glob("*.sf2"))
            if matches:
                return matches[0]
    return None


class FluidSynthOutput:
    def __init__(self, soundfont: Optional[Path] = None) -> None:
        self.soundfont = soundfont
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return

        executable = shutil.which("fluidsynth")
        if executable is None:
            raise ComputerSynthError(
                "Computer playback needs FluidSynth.\n\n"
                "Install it on Fedora with:\n"
                "sudo dnf install fluidsynth fluid-soundfont-gm"
            )

        soundfont = self.soundfont or find_soundfont()
        if soundfont is None:
            raise ComputerSynthError(
                "No SoundFont was found.\n\n"
                "Install one on Fedora with:\n"
                "sudo dnf install fluid-soundfont-gm\n\n"
                "Or set PIANO_SOUNDFONT=/path/to/piano.sf2"
            )

        configured_driver = os.environ.get("FLUIDSYNTH_AUDIO_DRIVER")
        drivers: Iterable[str] = (configured_driver,) if configured_driver else ("pipewire", "pulseaudio", "alsa")
        errors = []
        for driver in drivers:
            command = [executable, "-q", "-a", driver, "-g", "0.7", str(soundfont)]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            time.sleep(0.15)
            if process.poll() is None:
                self.process = process
                self.soundfont = soundfont
                for channel in range(16):
                    self._write(f"prog {channel} 0")
                return

            stderr = process.stderr.read().strip() if process.stderr else ""
            errors.append(f"{driver}: {stderr or 'could not start'}")

        raise ComputerSynthError("FluidSynth could not open a computer audio output.\n" + "\n".join(errors))

    def send(self, message: mido.Message) -> None:
        self.start()
        if message.type == "note_on" and message.velocity > 0:
            self._write(f"noteon {message.channel} {message.note} {message.velocity}")
        elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            self._write(f"noteoff {message.channel} {message.note}")
        elif message.type == "control_change":
            self._write(f"cc {message.channel} {message.control} {message.value}")

    def reset(self, channels: Iterable[int]) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        for channel in channels:
            self._write(f"cc {channel} 64 0")
            self._write(f"cc {channel} 66 0")
            self._write(f"cc {channel} 67 0")
            self._write(f"cc {channel} 123 0")

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self._write("quit")
                self.process.wait(timeout=1)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.terminate()
        self.process = None

    def _write(self, command: str) -> None:
        if self.process is None or self.process.stdin is None or self.process.poll() is not None:
            raise ComputerSynthError("FluidSynth stopped unexpectedly.")
        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except BrokenPipeError as exc:
            raise ComputerSynthError("FluidSynth stopped unexpectedly.") from exc
