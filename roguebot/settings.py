"""UI settings kept between sessions (data/settings.json): only the MuMu Player folder for now."""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"


def load(path: Path = SETTINGS_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(values: dict, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**load(path), **values}, ensure_ascii=False, indent=1), encoding="utf-8")
