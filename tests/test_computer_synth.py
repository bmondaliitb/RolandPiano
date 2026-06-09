import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mido

from src.roland_piano.computer_synth import FluidSynthOutput, find_soundfont


class FakeProcess:
    def __init__(self):
        self.stdin = io.StringIO()

    def poll(self):
        return None


class TestComputerSynth(unittest.TestCase):
    def test_configured_soundfont_is_discovered(self):
        path = Path(tempfile.gettempdir()) / "roland-piano-test.sf2"
        path.write_bytes(b"soundfont")

        with patch.dict(os.environ, {"PIANO_SOUNDFONT": str(path)}):
            self.assertEqual(find_soundfont(), path.resolve())

    def test_midi_messages_translate_to_fluidsynth_commands(self):
        synth = FluidSynthOutput()
        synth.process = FakeProcess()

        synth.send(mido.Message("note_on", channel=0, note=60, velocity=80))
        synth.send(mido.Message("control_change", channel=0, control=64, value=127))
        synth.send(mido.Message("note_off", channel=0, note=60, velocity=0))

        self.assertEqual(
            synth.process.stdin.getvalue().splitlines(),
            ["noteon 0 60 80", "cc 0 64 127", "noteoff 0 60"],
        )


if __name__ == "__main__":
    unittest.main()
