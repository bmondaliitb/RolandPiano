from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


STATE_VERSION = 1
PROJECT_VERSION = 1


def state_file_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "roland-piano" / "trainer-state.json"


def load_app_state(path: Optional[Path] = None) -> Dict[str, Any]:
    state_path = path or state_file_path()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return {}
    return data


def save_app_state(state: Dict[str, Any], path: Optional[Path] = None) -> None:
    state_path = path or state_file_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["version"] = STATE_VERSION
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(state_path)


def load_project(path: Path) -> Dict[str, Any]:
    project_path = path.expanduser().resolve()
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if (
        not isinstance(data, dict)
        or data.get("type") != "roland-piano-project"
        or data.get("version") != PROJECT_VERSION
    ):
        return {}

    song = data.get("song")
    if isinstance(song, str):
        song_path = Path(song).expanduser()
        if not song_path.is_absolute():
            song_path = project_path.parent / song_path
        data["song"] = str(song_path.resolve())
    return data


def save_project(state: Dict[str, Any], path: Path) -> None:
    project_path = path.expanduser().resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["type"] = "roland-piano-project"
    payload["version"] = PROJECT_VERSION

    song = payload.get("song")
    if isinstance(song, str):
        try:
            payload["song"] = os.path.relpath(Path(song).expanduser().resolve(), project_path.parent)
        except ValueError:
            payload["song"] = str(Path(song).expanduser().resolve())

    temporary = project_path.with_suffix(project_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(project_path)
