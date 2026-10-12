"""Entry point: python -m roguebot [--dry-run] [-v]"""

import argparse
import logging
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
from roguebot.skills import Catalog
from roguebot.vision import Ocr

log = logging.getLogger("roguebot")
ENERGY_READS = 3
PATROL_FAILS_TO_BACK_OFF = 2  # after-level patrol failures in a row before trying it only hours later

def _start_level(nav: Navigator, request: RunRequest) -> int | None:
    """Start the requested level; returns its number when known."""
    if request.pending_stars:
        played = nav.start_pending_stars(request.mode)
        if played is not None:
            return played
    if request.last_beaten:
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
    """After each level: patrol reward and free/energy quick patrols. A problem here never stops the run.
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


def make_runner(dry_run: bool, stop: threading.Event | None = None) -> Callable[[RunRequest], Report]:
    """The UI's Start action: starts MuMu Player and opens Rogue Legend if needed (emulator.py), so
    a missing emulator or game shows up as an error in the window instead of crashing at launch.
    Setting `stop` makes the run raise device.Stopped at its next wait, screenshot or tap."""
    ocr: Ocr | None = None
    catalog: Catalog | None = None

    def attempt(state: dict) -> Report:
        """One try: emulator and game up, then the requested work. `state` keeps the results (and the
        pinned level) across tries, so a recovery continues instead of starting over."""
        nonlocal ocr, catalog
        request = state["request"]
        serial, adb, launched = Emulator(request.mumu_folder, stop).start()
        device = Device(serial, stop=stop, adb=adb)
        ocr = ocr or Ocr()
        nav = Navigator(device, ocr, dry_run=dry_run, ads=request.ads)
        nav.resume_level = lambda: Player(device, ocr, request.build, catalog or Catalog(), request.ads).play_level()
        if launched:
            nav.wait_for_lobby(config.GAME_LOAD_TIMEOUT)
        nav.detect_language()
        if dry_run:
            _start_level(nav, request)
            return Report(dry_run=True)
        results = state["results"]
        cycle = 0
        while True:
            cycle += 1
            if request.full and not state["routine_done"]:  # a retry after an error skips what was done
                state["parts"] = Routine(device, ocr, nav, request.ads).run_parts()
            state["routine_done"] = True
            while True:
                if not request.repeat and results:  # a retry after an error must not replay the one level
                    return Report(results)
                if request.repeat and _energy(nav) < config.MIN_RUN_ENERGY:
                    if nav.claim_free_energy() < config.MIN_RUN_ENERGY:
                        break
                try:
                    played = _start_level(nav, request)
                except StarsUnavailable as e:  # no star list or no beaten level on this account (yet)
                    log.warning("%s: playing the last unlocked level instead", e)
                    state["no_stars"] = True  # remembered: no pinning, no more star list attempts
                    request = state["request"] = replace(request, level=None, last_beaten=False, pending_stars=False)
                    played = nav.start_latest(request.mode)
                catalog = catalog or Catalog()
                results.append(Player(device, ocr, request.build, catalog, request.ads).play_level())
                if (request.level is None and not request.last_beaten and results[-1] is LevelScreen.VICTORY
                        and played is not None and not state.get("no_stars")):
                    # Winning unlocked the next level; keep replaying this one from Desafío de Estrellas.
                    request = state["request"] = replace(request, level=played)
                nav.go_to_lobby()
                log.info("Level finished: %s (run %d)", results[-1].value, len(results))
                _claim_patrol(Routine(device, ocr, nav, request.ads), state)
                if not request.repeat:
                    return Report(results)
            if not request.loop:
                break
            log.info("Cycle %d finished (%d runs so far), waiting for energy", cycle, len(results))
            _wait_for_energy(nav, device)
            state["routine_done"] = False
        if not results and not request.full:
            raise NoEnergyError("Not enough energy to start a run, and no free energy to claim")
        return Report(results, repeat=True, parts=state["parts"])

    def run(request: RunRequest) -> Report:
        """attempt() until it finishes. On an error the emulator is closed and the next attempt starts
        it again (frozen emulator or game, crash, stuck screen). The same error more than
        MAX_SAME_ERROR times in a row (no level finished in between) stops the bot with that error."""
        if stop is not None:
            stop.clear()
        state = {"request": request, "results": [], "parts": [], "routine_done": False}
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
                if len(state["results"]) > progress:  # a level finished since the last error: start counting again
                    errors.clear()
                    progress = len(state["results"])
                key = _error_key(e)
                errors[key] = errors.get(key, 0) + 1
                if errors[key] > config.MAX_SAME_ERROR:
                    log.error("Same error %d times, giving up: %s", errors[key], e)
                    raise
                log.error("Error: %s. Restarting MuMu Player and trying again (%d/%d)",
                          e, errors[key], config.MAX_SAME_ERROR)
                Emulator(request.mumu_folder, stop).shutdown()

    return run


def main() -> int:
    parser = argparse.ArgumentParser(prog="roguebot")
    parser.add_argument("--dry-run", action="store_true",
                        help="navigate to the level but do not start it (no energy spent)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        from roguebot.ui import App
    except ImportError:
        log.error("tkinter is missing. Re-run the Python installer -> Modify -> tick 'tcl/tk and IDLE'.")
        return 1

    if getattr(sys, "frozen", False):
        settings.seed_data(settings.DATA_DIR, Path(sys._MEIPASS) / "data" / "skills.json")
    stop = threading.Event()
    App(make_runner(args.dry_run, stop), stop=stop.set).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
