import tempfile
import unittest
from pathlib import Path

import mido

from src.roland_piano.song_trainer import load_song, note_name


class TestSongTrainer(unittest.TestCase):
    def test_load_song_extracts_notes_from_multitrack_midi(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_trainer_test.mid"
        midi = mido.MidiFile(ticks_per_beat=480)
        tempo_track = mido.MidiTrack()
        note_track = mido.MidiTrack()
        midi.tracks.extend([tempo_track, note_track])
        tempo_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
        note_track.append(mido.Message("note_on", note=60, velocity=80, time=0))
        note_track.append(mido.Message("note_off", note=60, velocity=0, time=480))
        note_track.append(mido.Message("note_on", note=64, velocity=90, time=0))
        note_track.append(mido.Message("note_off", note=64, velocity=0, time=240))
        midi.save(path)

        song = load_song(path)

        self.assertEqual([note.name for note in song.notes], ["C4", "E4"])
        self.assertAlmostEqual(song.notes[0].duration, 0.5, places=3)
        self.assertAlmostEqual(song.duration, 0.75, places=3)

    def test_note_name(self):
        self.assertEqual(note_name(21), "A0")
        self.assertEqual(note_name(108), "C8")


if __name__ == "__main__":
    unittest.main()
