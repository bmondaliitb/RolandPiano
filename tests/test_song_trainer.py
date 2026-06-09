import tempfile
import unittest
from pathlib import Path

import mido

from src.roland_piano.roland_address_map import RolandAddressMap
from src.roland_piano.roland_messages import RolandMessageRequest
from src.roland_piano.roland_utils import RolandCmd
from src.roland_piano.song_trainer import (
    PracticeStep,
    build_practice_steps,
    load_song,
    note_name,
    practice_step_matches,
    shape_velocity,
    staff_note_position,
    suggest_fingering,
)


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

    def test_practice_steps_group_notes_that_start_together(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_trainer_chords_test.mid"
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.Message("note_on", note=60, velocity=80, time=0))
        track.append(mido.Message("note_on", note=64, velocity=80, time=0))
        track.append(mido.Message("note_on", note=67, velocity=80, time=0))
        track.append(mido.Message("note_off", note=60, velocity=0, time=240))
        track.append(mido.Message("note_off", note=64, velocity=0, time=0))
        track.append(mido.Message("note_off", note=67, velocity=0, time=0))
        track.append(mido.Message("note_on", note=62, velocity=80, time=240))
        track.append(mido.Message("note_off", note=62, velocity=0, time=240))
        midi.save(path)

        steps = build_practice_steps(load_song(path))

        self.assertEqual(steps[0].notes, (60, 64, 67))
        self.assertEqual(steps[0].names, ("C4", "E4", "G4"))
        self.assertEqual(steps[1].notes, (62,))

    def test_note_name(self):
        self.assertEqual(note_name(21), "A0")
        self.assertEqual(note_name(108), "C8")

    def test_practice_step_requires_an_exact_match(self):
        step = PracticeStep(start=1.0, notes=(60, 64, 67))

        self.assertFalse(practice_step_matches(step, {60, 64}))
        self.assertFalse(practice_step_matches(step, {60, 64, 67, 72}))
        self.assertTrue(practice_step_matches(step, {60, 64, 67}))

    def test_fingering_suggests_standard_triad_shapes(self):
        left = suggest_fingering(PracticeStep(start=0.0, notes=(48, 52, 55)))
        right = suggest_fingering(PracticeStep(start=0.0, notes=(60, 64, 67)))

        self.assertEqual([(item.note, item.label) for item in left], [(48, "L5"), (52, "L3"), (55, "L1")])
        self.assertEqual([(item.note, item.label) for item in right], [(60, "R1"), (64, "R3"), (67, "R5")])

    def test_fingering_assigns_single_notes_by_hand(self):
        left = suggest_fingering(PracticeStep(start=0.0, notes=(48,)))
        right = suggest_fingering(PracticeStep(start=0.0, notes=(60,)))

        self.assertEqual(left[0].label, "L1")
        self.assertEqual(right[0].label, "R1")

    def test_playback_events_preserve_pedal_and_note_identity(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_trainer_playback_test.mid"
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.Message("control_change", control=64, value=127, time=0))
        track.append(mido.Message("note_on", note=60, velocity=20, time=0))
        track.append(mido.Message("note_on", note=60, velocity=40, time=120))
        track.append(mido.Message("note_off", note=60, velocity=0, time=120))
        track.append(mido.Message("note_off", note=60, velocity=0, time=120))
        track.append(mido.Message("control_change", control=64, value=0, time=0))
        midi.save(path)

        events = load_song(path).playback_events

        note_ons = [event for event in events if event.kind == "note_on"]
        pedal = [event.value for event in events if event.kind == "control_change" and event.control == 64]
        self.assertEqual(len({event.note_id for event in note_ons}), 2)
        self.assertEqual(pedal, [127, 0])

    def test_percussion_channel_is_not_treated_as_piano(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_trainer_percussion_test.mid"
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.Message("note_on", channel=9, note=36, velocity=127, time=0))
        track.append(mido.Message("note_off", channel=9, note=36, velocity=0, time=120))
        track.append(mido.Message("note_on", channel=0, note=60, velocity=80, time=0))
        track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=120))
        midi.save(path)

        song = load_song(path)

        self.assertEqual([note.note for note in song.notes], [60])

    def test_velocity_shaping_does_not_force_quiet_notes_louder(self):
        self.assertEqual(shape_velocity(20, 85), 17)
        self.assertEqual(shape_velocity(127, 110), 127)

    def test_roland_master_volume_message(self):
        message = RolandMessageRequest(
            register=RolandAddressMap.masterVolume,
            cmd=RolandCmd.WRITE,
            data_as_int=42,
        ).as_mido_message

        self.assertEqual(message.type, "sysex")
        self.assertEqual(tuple(message.data[7:11]), tuple(RolandAddressMap.masterVolume.address))
        self.assertEqual(message.data[11], 42)

    def test_staff_note_positions(self):
        self.assertEqual(staff_note_position(64, "treble"), (0, False))  # E4 bottom line
        self.assertEqual(staff_note_position(67, "treble"), (2, False))  # G4 second line
        self.assertEqual(staff_note_position(43, "bass"), (0, False))  # G2 bottom line
        self.assertEqual(staff_note_position(61, "treble"), (-2, True))  # C#4 ledger line

        with self.assertRaises(ValueError):
            staff_note_position(60, "alto")


if __name__ == "__main__":
    unittest.main()
