"""UI settings kept between sessions (data/settings.json): only the MuMu Player folder for now."""

import json
import shutil
import sys
from pathlib import Path


def data_dir() -> Path:
    """The writable data folder: next to the exe when frozen (PyInstaller unpacks the package into a
    temp folder deleted on exit), else the repo's data/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return Path(__file__).parent.parent / "data"


def seed_data(target: Path, bundled: Path) -> None:
    """First run of the exe: copy the bundled skill database next to it (never overwrites user edits)."""
    if bundled.exists() and not (target / "skills.json").exists():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundled, target / "skills.json")


DATA_DIR = data_dir()
SETTINGS_PATH = DATA_DIR / "settings.json"


def load(path: Path = SETTINGS_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(values: dict, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**load(path), **values}, ensure_ascii=False, indent=1), encoding="utf-8")
