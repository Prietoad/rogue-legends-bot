"""Entry point: python -m roguebot [--dry-run] [-v]"""

import argparse
import logging
import os
import re
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from roguebot import config, settings
from roguebot.device import Device, Stopped
from roguebot.emulator import PERMANENT_ERRORS, Emulator, EmulatorError
from roguebot.navigation import LevelUnavailable, StarsUnavailable, NavigationError, Navigator
from roguebot.play import Player, PlayError
from roguebot.report import Report
from roguebot.request import RunRequest
from roguebot.routine import Routine
from roguebot.screens import LevelScreen
from roguebot.vision import parse_level_number
from roguebot.skills import Catalog
from roguebot.vision import Ocr

log = logging.getLogger("roguebot")
ENERGY_READS = 3
LOG_FILE_BYTES = 5_000_000
PATROL_FAILS_TO_BACK_OFF = 2  # after-level patrol failures in a row before trying it only hours later

def next_farm_level(played: int | None, won: bool, lobby_level: int | None,
                    replaying: int | None) -> int | None:
    """Star-challenge level to run next, or None to start the lobby's last unlocked level.

    Last-unlocked farming: a win moves on to the new frontier (the lobby start button;
    that level is not in the star list yet). A loss on the frontier falls back to the
    previous beaten level. A loss while already replaying that beaten level stays there.
    A stale low start read loses to a higher lobby title (38 read, lobby on 80 → 79).
    """
    if won:
        return None
    if replaying is not None:
        return replaying
    frontier = played
    if lobby_level is not None and (frontier is None or lobby_level > frontier):
        frontier = lobby_level
    if frontier is None or frontier < 2:
        return None
    return frontier - 1


def _start_level(nav: Navigator, request: RunRequest, state: dict | None = None) -> int | None:
    """Start the requested level; returns its number when known.

    Missing stars plays a beaten level that still has fewer than 3 stars. Only when that
    scan has reached level 1 and found none does it fall through to the last beaten level
    (lobby level − 1), and it keeps doing that — same mode, same keep-running loop — until
    energy runs out. It does not switch the run over to Last unlocked.
    """
    state = state if state is not None else {}
    if request.pending_stars and not state.get("stars_cleared"):
        played = nav.start_pending_stars(request.mode)
        if played is not None:
            return played
        log.info("Missing stars: no card left under 3 stars; playing the last beaten level")
        state["stars_cleared"] = True
    if request.last_beaten or state.get("stars_cleared"):
        return nav.start_last_beaten(request.mode)
    if request.level is None:
        return nav.start_latest(request.mode)
    nav.start_star_challenge(request.mode, request.level)
    return request.level


class NoEnergyError(NavigationError):
    """A normal end (nothing to play), not a fault: never retried."""


def _error_key(e: Exception) -> str:
    """Errors that differ only in numbers or screenshot paths count as the same error."""
    return re.sub(r"\(screenshot:.*?\)|\d+", "", f"{type(e).__name__}: {e}").strip()


def _energy(nav: Navigator) -> int:
    """Lobby energy. An unreadable counter is read again, never taken as 0 (that would waste the
    free energy claims and could end the run early)."""
    for _ in range(ENERGY_READS):
        energy = nav.go_to_lobby().energy
        if energy is not None:
            return energy
    raise NavigationError("Could not read the energy counter")


def _patrol_next(wait: float | None, now: float) -> float:
    """When the patrol is worth opening again: its reward reaches PATROL_CLAIM_AFTER, or local midnight
    (the daily quick patrols come back), whichever is first. Unknown wait: next time."""
    if wait is None:
        return now
    midnight = (datetime.fromtimestamp(now) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return min(now + wait, midnight.timestamp())


def _claim_patrol(routine: Routine, state: dict) -> None:
    """Before each level: patrol reward and free/energy quick patrols. A problem here never stops the run.
    Skipped while nothing can be there (it costs ~10 s per level otherwise)."""
    if time.time() < state.get("patrol_next", 0):
        return
    try:
        routine.patrol()
        state["patrol_next"] = _patrol_next(routine.patrol_wait, time.time())
        state["patrol_fails"] = 0
    except (NavigationError, PlayError) as e:
        log.error("Patrol failed: %s", e)
        state["patrol_fails"] = state.get("patrol_fails", 0) + 1
        if state["patrol_fails"] >= PATROL_FAILS_TO_BACK_OFF:  # likely not unlocked on this account: much later
            state["patrol_next"] = _patrol_next(config.PATROL_CLAIM_AFTER, time.time())
        routine.nav.go_to_lobby()


def _wait_for_energy(nav: Navigator, device: Device) -> None:
    """Loop mode: idle in the lobby until a run is affordable again (energy refills over time)."""
    while True:
        try:
            energy = nav.go_to_lobby().energy or 0
            if energy >= config.MIN_RUN_ENERGY:
                return
            log.info("Waiting for energy (%d/%d)", energy, config.MIN_RUN_ENERGY)
        except NavigationError as e:  # e.g. a screen that settles later: check again next time
            log.error("Waiting for energy: %s", e)
        device.wait(config.ENERGY_WAIT_POLL)


def make_runner(dry_run: bool, stop: threading.Event | None = None,
                pause: threading.Event | None = None) -> Callable[[RunRequest], Report]:
    """The UI's Start action: starts MuMu Player and opens Rogue Legend if needed (emulator.py), so
    a missing emulator or game shows up as an error in the window instead of crashing at launch.
    Setting `stop` makes the run raise device.Stopped at its next wait, screenshot or tap.
    Setting `pause` holds that same call until Resume, without ending the run."""
    ocr: Ocr | None = None
    catalog: Catalog | None = None

    def attempt(state: dict) -> Report:
        """One try: emulator and game up, then the requested work. `state` keeps the results (and the
        pinned level) across tries, so a recovery continues instead of starting over."""
        nonlocal ocr, catalog
        request = state["request"]
        serial, adb, launched = Emulator(request.mumu_folder, stop).start()
        device = Device(serial, stop=stop, adb=adb, pause=pause)
        ocr = ocr or Ocr()
        catalog = catalog or Catalog()
        nav = Navigator(device, ocr, dry_run=dry_run, ads=request.ads, elite_cost=request.elite_cost)
        play_level = lambda: Player(device, ocr, request.build, catalog, request.ads,
                                    getattr(nav, "level_title", None)).play_level()

        def resume_level():  # an interrupted run (its energy is spent): play it out; progress for run()
            play_level()
            state["resumed"] = state.get("resumed", 0) + 1

        nav.resume_level = resume_level
        if not launched and nav.level_in_progress():  # left running by a stopped bot: play it out first
            log.info("A level is in progress: playing it out")
            play_level()
        elif launched:
            nav.wait_for_lobby(config.GAME_LOAD_TIMEOUT)
        nav.detect_language()
        if dry_run:
            _start_level(nav, request, state)
            return Report(dry_run=True)
        results = state["results"]
        cycle = 0
        while True:
            cycle += 1
            if request.full and not state["routine_done"]:  # a retry after an error resumes at the part that broke
                routine = Routine(device, ocr, nav, request.ads, play_level, request.build, catalog,
                                  skip_fights=request.skip_fights)
                routine.run_parts(state)
                if routine.patrol_wait is not None:  # just opened by the routine: not again before the first level
                    state["patrol_next"] = _patrol_next(routine.patrol_wait, time.time())
            state["routine_done"] = True
            while True:
                if not request.repeat and results:  # a retry after an error must not replay the one level
                    return Report(results)
                # Quick Patrol spends energy. Only when the routine (that task) is on,
                # not on every start of a runs-only session.
                if request.full:
                    _claim_patrol(Routine(device, ocr, nav, request.ads), state)
                if request.repeat and _energy(nav) < config.MIN_RUN_ENERGY:
                    if nav.claim_free_energy() < config.MIN_RUN_ENERGY:
                        break
                try:
                    played = _start_level(nav, request, state)
                except StarsUnavailable as e:  # the star list is not on this account (yet)
                    # A finished missing-stars scan already chose last beaten. Do not turn that
                    # into Last unlocked because one lobby read missed the button.
                    if state.get("stars_cleared"):
                        raise
                    log.warning("%s: playing the last unlocked level instead", e)
                    state["no_stars"] = True  # remembered: no pinning, no more star list attempts
                    request = state["request"] = replace(request, level=None, last_beaten=False, pending_stars=False)
                    played = nav.start_latest(request.mode)
                results.append(Player(device, ocr, request.build, catalog, request.ads,
                                       getattr(nav, "level_title", None)).play_level())
                lobby = nav.go_to_lobby()
                if state.get("latest_farm") and not state.get("no_stars"):
                    # Win the frontier → the new last unlocked (lobby start). Lose it → the
                    # previous beaten level. A win of that fallback tries the frontier again.
                    nxt = next_farm_level(played, results[-1] is LevelScreen.VICTORY,
                                          parse_level_number(lobby.level_title or ""), request.level)
                    if nxt != request.level:
                        request = state["request"] = replace(request, level=nxt)
                log.info("Level finished: %s (run %d)", results[-1].value, len(results))
                if not request.repeat:
                    return Report(results)
            if not request.loop:
                break
            log.info("Cycle %d finished (%d runs so far), waiting for energy", cycle, len(results))
            _wait_for_energy(nav, device)
            state.update(routine_done=False, parts=[], part_tries={})
        if not results and not request.full:
            raise NoEnergyError("Not enough energy to start a run, and no free energy to claim")
        return Report(results, repeat=True, parts=state["parts"])

    def run(request: RunRequest) -> Report:
        """attempt() until it finishes. On an error the emulator is closed and the next attempt starts
        it again (frozen emulator or game, crash, stuck screen). The same error more than
        MAX_SAME_ERROR times in a row (no level or routine part finished in between) stops the bot with that error."""
        if stop is not None:
            stop.clear()
        if pause is not None:
            pause.clear()
        state = {"request": request, "results": [], "parts": [], "routine_done": False,
                 "latest_farm": request.level is None and not request.last_beaten and not request.pending_stars}
        errors: dict[str, int] = {}
        progress = 0
        while True:
            try:
                return attempt(state)
            except Stopped:
                raise
            except Exception as e:
                if dry_run or isinstance(e, (NoEnergyError, LevelUnavailable)) or (
                        isinstance(e, EmulatorError) and e.key in PERMANENT_ERRORS):
                    raise
                done = len(state["results"]) + len(state["parts"]) + state.get("resumed", 0)
                if done > progress:  # a level or routine part finished since the last error: start counting again
                    errors.clear()
                    progress = done
                key = _error_key(e)
                errors[key] = errors.get(key, 0) + 1
                if errors[key] > config.MAX_SAME_ERROR:
                    log.error("Same error %d times, giving up: %s", errors[key], e)
                    raise
                log.exception("Error (MuMu is left running, try %d/%d): %s",
                              errors[key], config.MAX_SAME_ERROR, e)

    return run


class _FlushFileHandler(logging.Handler):
    """Append-only log that flushes every line. The GUI logger and this one must be the same logger:
    a handler on the root only was leaving debug/bot.log at 0 bytes while the window showed lines."""

    def __init__(self, path: Path):
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8", buffering=1)
        self.path = path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._fh.write(self.format(record) + "\n")
            self._fh.flush()
            if record.levelno >= logging.ERROR:
                os.fsync(self._fh.fileno())
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except OSError:
            pass
        super().close()


def log_file_path() -> Path:
    """debug/bot.log next to the exe when frozen, else next to the repo. Not the process's cwd."""
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parent.parent
    return root / "debug" / "bot.log"


def _log_to_file(level: int, path: Path | None = None) -> None:
    """Every roguebot log line, including tracebacks, flushed to debug/bot.log."""
    path = log_file_path() if path is None else path
    try:
        handler = _FlushFileHandler(path)
    except OSError as e:  # a read-only folder: the window still shows the log
        log.warning("No log file: %s", e)
        return
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S"))
    logger = logging.getLogger("roguebot")
    logger.setLevel(level)
    logger.addHandler(handler)


def main() -> int:
    parser = argparse.ArgumentParser(prog="roguebot")
    parser.add_argument("--dry-run", action="store_true",
                        help="navigate to the level but do not start it (no energy spent)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _log_to_file(logging.DEBUG if args.verbose else logging.INFO)

    try:
        from roguebot.ui import App
    except ImportError:
        log.error("tkinter is missing. Re-run the Python installer -> Modify -> tick 'tcl/tk and IDLE'.")
        return 1

    if getattr(sys, "frozen", False):
        settings.seed_data(settings.DATA_DIR, Path(sys._MEIPASS) / "data" / "skills.json")
    stop = threading.Event()
    pause = threading.Event()

    def set_paused(paused: bool) -> None:
        if paused:
            pause.set()
        else:
            pause.clear()

    App(make_runner(args.dry_run, stop, pause), stop=stop.set, pause=set_paused).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
