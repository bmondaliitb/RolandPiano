import json
import tempfile
import unittest
from pathlib import Path

from src.roland_piano.app_state import load_app_state, load_project, save_app_state, save_project


class TestAppState(unittest.TestCase):
    def test_state_round_trip(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_state_test.json"
        state = {
            "geometry": "1180x760+20+30",
            "song": "/music/song.mid",
            "position": 12.5,
            "tempo": 0.8,
            "practice_mode": True,
            "loop_start": 10.0,
            "loop_end": 14.0,
            "loop_enabled": True,
        }

        save_app_state(state, path)

        self.assertEqual(load_app_state(path)["position"], 12.5)
        self.assertEqual(load_app_state(path)["geometry"], "1180x760+20+30")

    def test_invalid_state_is_ignored(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_invalid_state_test.json"
        path.write_text("{broken", encoding="utf-8")

        self.assertEqual(load_app_state(path), {})

    def test_unknown_state_version_is_ignored(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_version_state_test.json"
        path.write_text(json.dumps({"version": 999, "position": 12}), encoding="utf-8")

        self.assertEqual(load_app_state(path), {})

    def test_project_round_trip_resolves_song_relative_to_project(self):
        directory = Path(tempfile.mkdtemp(prefix="roland-piano-project-"))
        song = directory / "song.mid"
        project = directory / "lesson.roland-project.json"
        song.write_bytes(b"MThd")

        save_project({"song": str(song), "position": 8.5, "practice_mode": True}, project)
        loaded = load_project(project)

        self.assertEqual(loaded["song"], str(song.resolve()))
        self.assertEqual(loaded["position"], 8.5)
        self.assertTrue(loaded["practice_mode"])
        saved_json = json.loads(project.read_text(encoding="utf-8"))
        self.assertEqual(saved_json["song"], "song.mid")

    def test_non_project_json_is_rejected(self):
        path = Path(tempfile.gettempdir()) / "roland_piano_not_project_test.json"
        path.write_text(json.dumps({"version": 1, "song": "song.mid"}), encoding="utf-8")

        self.assertEqual(load_project(path), {})


if __name__ == "__main__":
    unittest.main()
