# AGENTS.md

Guide for coding agents working on this repository (Codex, cloud or local). Read this file and `specs/2.0.5/BUGS.md` before changing code.

## Project

Python bot that farms **Rogue Legend** (PocketHaven) in **MuMu Player 12** on Windows. It works only from the screen: ADB screenshots, RapidOCR, and taps. No memory reading or network tampering. It plays in Spanish or English.

- Python 3.13, deps in `requirements.txt` (`adbutils`, `opencv-python`, `numpy`, `rapidocr`, `onnxruntime`, `pytest`, `pytest-xdist`)
- Frames are portrait 9:16, reference size **1440×2560** (`config.SCREEN_SIZE`). Other 9:16 sizes are resized to that; taps are scaled back.
- Tkinter GUI (`python -m roguebot`). Tk is not pip-installable; the official Python installer must include tcl/tk.
- One-file exe: `.\build.ps1` (PyInstaller, `dist\RogueLegendBot.exe`).

`CLAUDE.md` has longer architecture and game-knowledge notes. This file is the short contract for a 2.0.5 change.

## Module map

```
roguebot/
  __init__.py      __version__ (currently 2.0.4 — bump to 2.0.5)
  __main__.py      entry point, Start runner
  config.py        constants only: ADB, 1440×2560 coords, timings (WATCHDOG_*, EVENT_CLEAR_TAP, FOOTER_Y)
  emulator.py      MuMu Player start / open the game
  settings.py      data/settings.json (MuMu folder)
  device.py        ADB screenshot / tap / swipe; no game knowledge
  labels.py        every game text (Spanish + English), including CONTINUE_BUTTONS
  vision.py        RapidOCR wrapper, Text, normalize / matches / find, templates
  templates/       close_x.png, back_arrow.png
  screens.py       pure recognition: OCR -> typed states; close_button / close_button_any_size
  navigation.py    lobby -> mode -> level start; go_to_lobby
  play.py          in-level loop (classify -> tap or wait) until victory/defeat; Treasure Miner dig loop
  request.py       RunRequest + form validation
  mode_screens.py  routine screen recognition (Arena, Tower, Dive, Mines, raid, …)
  routine.py       full routine parts; dojo / raid skill offers use build.offer_is_unfavorable
  skills.py        data/skills.json catalog; infer_tags, name_is_support, skill_key
  build.py         Build preferences + pure choice rules (ranked, choose, shop_order, core_index, offer_is_unfavorable)
  world2.py        World 2 decisions (statue, miner grid, coin flip, is_core_skill, is_skills_overlay, StuckWatch, progress_signature)
  ui.py            Tkinter window
  report.py        run summary text
data/skills.json   skill catalog (damage_type, role, rarity, auto)
tests/             pytest on real screenshots; see tests/conftest.py (fixture_image, cached OCR)
tests/fixtures/    existing 1440×2560 (and some cropped) shots
specs/2.0.5/       2.0.5 bug list, fixtures, and OCR dumps for this release
tools/             dev helpers
phone/             Android port — out of scope unless a change truly requires it
build.ps1          PyInstaller one-file exe
```

Layers: `device` (I/O) → `vision` (perception) → `screens` / `world2` / `build` (pure decisions) → `navigation` / `play` / `routine` (behavior) → `ui`. Keep game knowledge out of `device`, and keep taps out of `screens` / `world2` / `build`.

## How to run tests (no emulator)

```bash
pip install -r requirements.txt
python -m pytest -q
```

`pytest.ini` defaults to `pytest-xdist` (`-n auto`). Use `-n 0` to debug. `tests/conftest.py` provides `fixture_image(path)` (decoded 1440×2560 PNG) and a session-scoped cached `ocr` fixture so repeated reads do not reload RapidOCR.

Follow the existing 2.0.4 pattern in `tests/test_release_204.py` and `tests/test_world2.py`. For 2.0.5, add something like `tests/test_release_205.py` and load images from `specs/2.0.5/` (or copy into `tests/fixtures/w2_205/` if that is cleaner). Prefer offline tests that classify a fixture, check a close-button coordinate, or unit-test `build` / `world2` / miner logic. Do not delete or weaken existing tests.

A full live farm is not available to the coding agent. Mark anything that still needs a live run on Brian's PC as **live-unverified** in the pull request.

## Hard rules

- **Never auto-spend gems, gold, or diamonds.** Shops buy with event tokens only. Prize-strip gem/coin amounts (see `specs/2.0.5/BUGS.md` item #10) are rewards, not purchases. Do not tap offer, price, or gem-spend buttons. Close purchase popups only through their "tap to close" / ✕ affordances.
- **Arena and VIP stay untouched.** Do not change Arena or VIP behavior, screens, or settings in this release.
- **Version is 2.0.5.** Bump every version string this repo uses for the desktop bot: at least `roguebot/__init__.py` (`__version__`), the assertion in `tests/test_logic.py`, and a `## 2.0.5` section in `CHANGELOG.md` (and README if it still names 2.0.4). Leave the phone app version alone unless it is generated from the same string.
- **Stay scoped to `specs/2.0.5/BUGS.md`.** Implement numbered items #1–#10, including §5a (Game's poison ranking and protected core). Leftovers at the bottom of that file (vendor curse/blessing weights, catalog junk names) are reference only — do not invent weights.
- **Ninja Dodge stays not core** (Brian, 2.0.4). Heal Shuriken likewise.
- **Add offline tests with the fixtures where possible.** Every code change needs tests, and `python -m pytest -q` must pass.
- Do not rewrite unrelated modules, and do not start "cleanup" refactors outside the bug list.

## Pull request

Open **one** pull request targeting `main`, titled `2.0.5: <short summary of the fixes>`.

The PR body must include:

- A checklist of items #1–#10 (and §5a) with what changed for each.
- A **live-unverified** section listing behavior that still needs a farm on Brian's PC (for example miner visits with no fixture, statue offerings, dojo/raid 4-card offers with no screenshot, watchdog timing on a real hang).
- Confirmation that gems/gold are never auto-spent and that Arena and VIP were not changed.
- How to run the new tests.

Farm and exe rebuilds are handled outside this PR, after review.
