"""Start action wiring: emulator problems surface as errors from run(), not at launch."""

import pytest

import roguebot.__main__ as main
from roguebot.emulator import EmulatorError
from roguebot.request import RunRequest
from roguebot.screens import Mode


def test_runner_does_not_connect_until_start(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("connected too early")
    monkeypatch.setattr(main, "Device", boom)
    main.make_runner(dry_run=True)  # building the runner must not touch the emulator


class FakeEmulator:
    """Emulator already started, game in front: (serial, adb, game_was_launched)."""
    launched = False

    def __init__(self, folder, stop=None):
        FakeEmulator.folder, FakeEmulator.stop = folder, stop

    shutdowns = 0

    def start(self):
        return "127.0.0.1:16384", "adb.exe", FakeEmulator.launched

    def shutdown(self):
        FakeEmulator.shutdowns += 1


@pytest.fixture(autouse=True)
def fake_emulator(monkeypatch):
    FakeEmulator.launched, FakeEmulator.shutdowns = False, 0
    monkeypatch.setattr(main, "Emulator", FakeEmulator)
    FakeRoutine.patrols = 0
    monkeypatch.setattr(main, "Routine", FakeRoutine)


def test_emulator_problems_are_reported(monkeypatch):
    class Broken(FakeEmulator):
        def start(self):
            raise EmulatorError("err_game_missing")
    monkeypatch.setattr(main, "Emulator", Broken)
    with pytest.raises(EmulatorError) as e:
        main.make_runner(dry_run=True)(RunRequest(Mode.NORMAL, None, mumu_folder="C:/MuMu"))
    assert e.value.key == "err_game_missing" and Broken.folder == "C:/MuMu"


def test_device_uses_the_emulators_serial_and_adb(monkeypatch):
    seen = []

    class Dev:
        def __init__(self, serial, stop=None, adb=None):
            seen.append((serial, adb))
            raise RuntimeError("enough")
    monkeypatch.setattr(main, "Device", Dev)
    with pytest.raises(RuntimeError):
        main.make_runner(dry_run=True)(RunRequest(Mode.NORMAL, None))
    assert seen == [("127.0.0.1:16384", "adb.exe")]


def test_freshly_opened_game_waits_for_its_lobby(monkeypatch):
    FakeEmulator.launched = True
    nav = FakeNav(energy=20)
    waited = []
    nav.wait_for_lobby = lambda timeout: waited.append(timeout)
    run_with(monkeypatch, nav, [V], RunRequest(Mode.NORMAL, 4))
    assert waited == [main.config.GAME_LOAD_TIMEOUT] and nav.started[0] == "detect"


class FakeLobby:
    def __init__(self, energy):
        self.energy = energy


class FakeNav:
    """Energy drops 5 per run; claiming free energy adds `claimable` once."""
    def __init__(self, energy, claimable=0, latest=13):
        self.energy, self.claimable, self.latest = energy, claimable, latest
        self.started = []
        self.claims = 0

    def go_to_lobby(self):
        return FakeLobby(self.energy)

    def level_in_progress(self):
        return getattr(self, "in_level", False)

    def detect_language(self):
        self.started.append("detect")
        return "es"

    def claim_free_energy(self):
        self.claims += 1
        self.energy += self.claimable
        self.claimable = 0
        return self.energy

    def start_latest(self, mode):
        self.started.append(("latest", self.latest))
        self.energy -= 5
        return self.latest

    def start_star_challenge(self, mode, level):
        self.started.append(("stars", level))
        self.energy -= 5


def run_with(monkeypatch, nav, results, request):
    class Dev:
        def __init__(self, serial, stop=None, adb=None):
            pass

    class FakePlayer:
        def __init__(self, *a):
            pass

        def play_level(self):
            return results.pop(0)

    monkeypatch.setattr(main, "Device", Dev)
    monkeypatch.setattr(main, "Ocr", lambda: object())
    monkeypatch.setattr(main, "Navigator", lambda *a, **k: nav)
    monkeypatch.setattr(main, "Player", FakePlayer)
    return main.make_runner(dry_run=False)(request)


V, D = main.LevelScreen.VICTORY, main.LevelScreen.DEFEAT


def test_single_run(monkeypatch):
    nav = FakeNav(energy=20)
    report = run_with(monkeypatch, nav, [V], RunRequest(Mode.NORMAL, 4))
    assert report.results == [V] and not report.repeat
    assert nav.started == ["detect", ("stars", 4)]  # language first


def test_repeat_until_out_of_energy_claims_free_energy_first(monkeypatch):
    nav = FakeNav(energy=10, claimable=5)
    report = run_with(monkeypatch, nav, [V, D, V], RunRequest(Mode.NORMAL, 4, repeat=True))
    assert nav.started == ["detect"] + [("stars", 4)] * 3
    assert nav.claims == 2  # once successfully, once finding nothing left
    assert report.results == [V, D, V] and report.repeat


def test_repeat_latest_pins_level_after_victory(monkeypatch):
    nav = FakeNav(energy=15)
    run_with(monkeypatch, nav, [D, V, V], RunRequest(Mode.NORMAL, None, repeat=True))
    # Defeat: still the latest level. Victory unlocks 14, so replay 13 from Desafío de Estrellas.
    assert nav.started == ["detect", ("latest", 13), ("latest", 13), ("stars", 13)]


def test_repeat_without_any_energy_is_an_error(monkeypatch):
    nav = FakeNav(energy=2)
    with pytest.raises(main.NavigationError, match="Not enough energy"):
        run_with(monkeypatch, nav, [], RunRequest(Mode.NORMAL, 4, repeat=True))


class FakeRoutine:
    calls = patrols = 0
    patrol_wait = None  # unreadable counter: the patrol is opened after every level

    def __init__(self, device=None, ocr=None, nav=None, ads=False, play_level=None, build=None, catalog=None):
        self.play_level = play_level
        self.nav = nav
        self.build = build

    def run_parts(self, progress=None):
        FakeRoutine.calls += 1
        FakeRoutine.had_player = self.play_level is not None  # Dungeon Dive plays levels with the Player
        FakeRoutine.had_build = self.build is not None  # Dojo / raid skill picks follow the build
        progress = {} if progress is None else progress
        progress.setdefault("parts", []).extend([("arena", "done"), ("raid", "skipped")])
        return progress["parts"]

    def patrol(self):
        FakeRoutine.patrols += 1
        return "done"


def test_full_routine_runs_parts_then_levels(monkeypatch):
    FakeRoutine.calls = 0
    monkeypatch.setattr(main, "Routine", FakeRoutine)
    nav = FakeNav(energy=10)
    report = run_with(monkeypatch, nav, [V, V], RunRequest(Mode.NORMAL, 4, repeat=True, full=True))
    assert FakeRoutine.calls == 1 and FakeRoutine.had_player and FakeRoutine.had_build
    assert report.parts == [("arena", "done"), ("raid", "skipped")]
    assert report.results == [V, V] and report.repeat


def test_full_routine_without_energy_is_not_an_error(monkeypatch):
    monkeypatch.setattr(main, "Routine", FakeRoutine)
    report = run_with(monkeypatch, FakeNav(energy=0), [], RunRequest(Mode.NORMAL, 4, repeat=True, full=True))
    assert report.results == [] and report.parts


def test_routine_not_run_without_full(monkeypatch):
    FakeRoutine.calls = 0
    monkeypatch.setattr(main, "Routine", FakeRoutine)
    run_with(monkeypatch, FakeNav(energy=20), [V], RunRequest(Mode.NORMAL, 4))
    assert FakeRoutine.calls == 0


def test_stop_event_reaches_the_device_and_is_cleared_on_start(monkeypatch):
    import threading
    stop = threading.Event()
    stop.set()  # left over from a previous stopped run
    seen = []

    class Dev:
        def __init__(self, serial, stop=None, adb=None):
            seen.append((stop, stop.is_set()))
            raise RuntimeError("enough")
    monkeypatch.setattr(main, "Device", Dev)
    with pytest.raises(RuntimeError):
        main.make_runner(dry_run=True, stop=stop)(RunRequest(Mode.NORMAL, None))
    assert seen == [(stop, False)] and FakeEmulator.stop is stop  # the emulator waits can be stopped too


def run_loop(monkeypatch, nav, results, on_wait, full=True):
    """Loop request; the device's wait() (energy refill time) is simulated by on_wait."""
    class Dev:
        def __init__(self, serial, stop=None, adb=None):
            pass

        def wait(self, seconds):
            on_wait()

    class FakePlayer:
        def __init__(self, *a):
            pass

        def play_level(self):
            return results.pop(0)

    FakeRoutine.calls = 0
    monkeypatch.setattr(main, "Device", Dev)
    monkeypatch.setattr(main, "Ocr", lambda: object())
    monkeypatch.setattr(main, "Navigator", lambda *a, **k: nav)
    monkeypatch.setattr(main, "Player", FakePlayer)
    monkeypatch.setattr(main, "Routine", FakeRoutine)
    return main.make_runner(dry_run=False)(RunRequest(Mode.NORMAL, 4, repeat=True, full=full, loop=True))


def test_loop_waits_for_energy_then_runs_the_whole_routine_again(monkeypatch):
    from roguebot.device import Stopped
    nav = FakeNav(energy=5)
    waits = []

    def on_wait():
        waits.append(nav.energy)
        if len(waits) == 1:
            nav.energy += 2   # not enough yet: keep waiting
        elif len(waits) == 2:
            nav.energy += 3   # 5: one more run
        else:
            raise Stopped("Stopped by the user")
    with pytest.raises(Stopped):
        run_loop(monkeypatch, nav, [V, D], on_wait)
    assert FakeRoutine.calls == 2  # modes again on the second cycle
    assert nav.started == ["detect", ("stars", 4), ("stars", 4)]
    assert waits == [0, 2, 0]


def test_keep_running_without_the_full_routine_only_replays_levels(monkeypatch):
    from roguebot.device import Stopped
    nav = FakeNav(energy=5, claimable=5)
    waits = []

    def on_wait():
        waits.append(nav.energy)
        if len(waits) == 1:
            nav.energy += 5  # refilled while waiting
        else:
            raise Stopped("Stopped by the user")
    with pytest.raises(Stopped):
        run_loop(monkeypatch, nav, [V, V, V], on_wait, full=False)
    assert FakeRoutine.calls == 0  # never the routine
    assert nav.started == ["detect", ("stars", 4), ("stars", 4), ("stars", 4)]  # 5 + 5 claimed, then 5 refilled
    assert nav.claims == 3 and waits == [0, 0]  # free energy claimed before every wait


def test_loop_survives_a_failed_cycle(monkeypatch):
    from roguebot.device import Stopped
    nav = FakeNav(energy=5)
    calls = []

    def flaky_start(mode, level):
        calls.append(level)
        if len(calls) == 1:
            raise main.NavigationError("Level did not start")
        nav.energy -= 5

    nav.start_star_challenge = flaky_start

    def on_wait():
        if len(calls) > 1:
            raise Stopped("Stopped by the user")
    with pytest.raises(Stopped):
        run_loop(monkeypatch, nav, [V], on_wait)
    assert calls == [4, 4]  # the failed cycle: MuMu restarted, then the next try played
    assert FakeEmulator.shutdowns == 1


def test_device_wait_is_interrupted_by_stop():
    import threading
    import time
    from roguebot.device import Device, Stopped
    dev = Device.__new__(Device)  # no adb connection needed
    dev._stop = threading.Event()
    threading.Timer(0.05, dev._stop.set).start()
    t0 = time.monotonic()
    with pytest.raises(Stopped):
        dev.wait(30)
    assert time.monotonic() - t0 < 5


def test_repeat_last_beaten_replays_it(monkeypatch):
    nav = FakeNav(energy=10)

    def start_last_beaten(mode):
        nav.started.append(("beaten", 12))
        nav.energy -= 5
        return 12
    nav.start_last_beaten = start_last_beaten
    report = run_with(monkeypatch, nav, [V, V], RunRequest(Mode.NORMAL, None, repeat=True, last_beaten=True))
    assert nav.started == ["detect", ("beaten", 12), ("beaten", 12)]  # no pinning: it never unlocks anything
    assert report.results == [V, V]


def test_waiting_for_energy_logs_each_check(caplog):
    """Loop mode idles for long; a log line per check shows it is alive (the UI log, stall watchers)."""
    import logging
    nav = FakeNav(energy=2)

    class Dev:
        def wait(self, seconds):
            nav.energy += 3
    with caplog.at_level(logging.INFO, logger="roguebot"):
        main._wait_for_energy(nav, Dev())
    assert "Waiting for energy (2/5)" in caplog.text


def test_patrol_is_checked_before_every_level(monkeypatch):
    nav = FakeNav(energy=10)

    class R(FakeRoutine):
        def patrol(self):
            nav.started.append("patrol")
            return super().patrol()
    monkeypatch.setattr(main, "Routine", R)
    run_with(monkeypatch, nav, [V, D], RunRequest(Mode.NORMAL, 4, repeat=True))
    # before each level (its quick patrols spend energy, so before the energy check too)
    assert nav.started == ["detect", "patrol", ("stars", 4), "patrol", ("stars", 4), "patrol"]


def test_patrol_opened_by_the_routine_is_not_opened_again_before_the_first_level(monkeypatch):
    class R(FakeRoutine):
        patrol_wait = 3600
    monkeypatch.setattr(main, "Routine", R)
    report = run_with(monkeypatch, FakeNav(energy=5), [V], RunRequest(Mode.NORMAL, 4, repeat=True, full=True))
    assert report.results == [V] and FakeRoutine.patrols == 0  # the routine's own patrol part counts


def test_a_patrol_problem_never_stops_the_run(monkeypatch):
    class Failing(FakeRoutine):
        def patrol(self):
            raise main.NavigationError("Expected the patrol popup")
    monkeypatch.setattr(main, "Routine", Failing)
    nav = FakeNav(energy=10)
    report = run_with(monkeypatch, nav, [V, V], RunRequest(Mode.NORMAL, 4, repeat=True))
    assert report.results == [V, V]


def test_any_error_restarts_the_emulator_and_keeps_going(monkeypatch):
    nav = FakeNav(energy=15)
    starts = []

    def flaky_start(mode, level):
        starts.append(level)
        if len(starts) in (1, 3):
            raise main.PlayError("Tapping (511, 2030) on event has no effect")  # frozen game, stuck screen...
        nav.energy -= 5
    nav.start_star_challenge = flaky_start
    report = run_with(monkeypatch, nav, [V, V, D], RunRequest(Mode.NORMAL, 4, repeat=True))
    assert FakeEmulator.shutdowns == 2 and report.results == [V, V, D]  # results kept across restarts


def test_the_same_error_too_many_times_stops_the_bot(monkeypatch):
    nav = FakeNav(energy=15)

    def broken(mode, level):
        raise main.NavigationError(f"Level did not start (screenshot: debug/fail_{len(nav.started)}.png)")
    nav.start_star_challenge = broken
    with pytest.raises(main.NavigationError, match="Level did not start"):
        run_with(monkeypatch, nav, [], RunRequest(Mode.NORMAL, 4, repeat=True))
    assert FakeEmulator.shutdowns == main.config.MAX_SAME_ERROR  # then the 4th time it gives up


def test_a_resumed_level_counts_as_progress_but_not_as_the_requested_level(monkeypatch):
    """The "¿Continuar la aventura?" dialog after a restart: the interrupted level is played out
    (go_to_lobby -> nav.resume_level). It resets the same-error count, and a single-level request
    still plays its own level afterwards."""
    nav = FakeNav(energy=20)
    tries = []

    def detect():
        tries.append(1)
        if len(tries) == main.config.MAX_SAME_ERROR + 1:
            nav.resume_level()
        return "es"

    def start(mode, level):
        if len(tries) <= main.config.MAX_SAME_ERROR + 1:
            raise main.NavigationError("Level did not start")
        nav.started.append(("stars", level))
    nav.detect_language, nav.start_star_challenge = detect, start
    report = run_with(monkeypatch, nav, [D, V], RunRequest(Mode.NORMAL, 4))
    assert report.results == [V] and nav.started == [("stars", 4)]
    assert FakeEmulator.shutdowns == main.config.MAX_SAME_ERROR + 1  # never gave up


def test_permanent_problems_are_not_retried(monkeypatch):
    class NeedsUpdate(FakeEmulator):
        def start(self):
            raise EmulatorError("err_game_update")
    monkeypatch.setattr(main, "Emulator", NeedsUpdate)
    with pytest.raises(EmulatorError):
        main.make_runner(dry_run=False)(RunRequest(Mode.NORMAL, 4))
    assert FakeEmulator.shutdowns == 0


def test_error_key_ignores_numbers_and_screenshots():
    a = main._error_key(main.NavigationError("Tapping (511, 2030) on event (screenshot: debug/a_1.png)"))
    b = main._error_key(main.NavigationError("Tapping (510, 2029) on event (screenshot: debug/b_2.png)"))
    assert a == b and "screenshot" not in a


def test_device_calls_have_timeouts_and_an_empty_screenshot_is_an_error():
    """A frozen emulator once made screencap hang (or return nothing): it must raise, so the bot recovers."""
    from roguebot.device import Device, DeviceError
    calls = []

    class FakeAdb:
        def shell(self, cmd, encoding="utf-8", timeout=None):
            calls.append((cmd, timeout))
            return b""
    dev = Device.__new__(Device)
    dev._stop, dev._d, dev._scale = None, FakeAdb(), 1.0
    with pytest.raises(DeviceError, match="not responding"):
        dev.screenshot()
    dev.tap(10, 20, settle=0)
    assert all(t == main.config.ADB_TIMEOUT for _, t in calls) and calls[1][0] == ["input", "tap", "10", "20"]
    dev.back(settle=0)  # leaving the browser the daily rewards open
    assert calls[-1] == (["input", "keyevent", "4"], main.config.ADB_TIMEOUT)


def test_an_unavailable_level_is_not_retried(monkeypatch):
    """Live: elite star level 8 requested with only elite 1-2 unlocked; restarting MuMu cannot help."""
    nav = FakeNav(energy=15)

    def missing(mode, level):
        raise main.LevelUnavailable("Level 8 not found (list ends at 2)")
    nav.start_star_challenge = missing
    with pytest.raises(main.LevelUnavailable):
        run_with(monkeypatch, nav, [], RunRequest(Mode.ELITE, 8, repeat=True))
    assert FakeEmulator.shutdowns == 0


def test_a_single_run_is_not_replayed_after_an_error_past_the_level(monkeypatch):
    """Review: one requested level, the lobby fails afterwards -> the retry must not play it again."""
    nav = FakeNav(energy=20)
    lobby_calls = []
    real = nav.go_to_lobby

    def flaky_lobby():
        lobby_calls.append(1)
        if len(lobby_calls) == 1:  # right after the level
            raise main.NavigationError("Could not reach the Aventura lobby")
        return real()
    nav.go_to_lobby = flaky_lobby
    report = run_with(monkeypatch, nav, [V], RunRequest(Mode.NORMAL, 4))
    assert report.results == [V] and nav.started.count(("stars", 4)) == 1
    assert FakeEmulator.shutdowns == 1


def test_a_retry_does_not_run_the_routine_again(monkeypatch):
    """Review: an error while clearing levels used to re-run every part (Tower spent another ticket)."""
    nav = FakeNav(energy=10)
    starts = []

    def flaky_start(mode, level):
        starts.append(level)
        if len(starts) == 1:
            raise main.PlayError("Stuck on an unknown screen")
        nav.energy -= 5
    nav.start_star_challenge = flaky_start
    FakeRoutine.calls = 0
    report = run_with(monkeypatch, nav, [V, V], RunRequest(Mode.NORMAL, 4, repeat=True, full=True))
    assert FakeRoutine.calls == 1 and report.parts  # parts kept from the first try


def test_unreadable_energy_is_read_again_not_taken_as_zero(monkeypatch):
    class Lobby:
        def __init__(self, energy):
            self.energy = energy
    reads = iter([None, None, 12])

    class Nav:
        def go_to_lobby(self):
            return Lobby(next(reads))
    assert main._energy(Nav()) == 12
    reads = iter([None] * 3)
    with pytest.raises(main.NavigationError, match="energy counter"):
        main._energy(Nav())


def test_pending_stars_falls_back_to_the_last_beaten_level(monkeypatch):
    nav = FakeNav(energy=10)
    nav.start_pending_stars = lambda mode: None  # every level has 3 stars
    nav.start_last_beaten = lambda mode: nav.started.append(("beaten", 13)) or 13
    run_with(monkeypatch, nav, [V], RunRequest(Mode.NORMAL, None, last_beaten=True, pending_stars=True))
    assert ("beaten", 13) in nav.started


def test_patrol_is_skipped_until_its_reward_is_due(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(main.time, "time", lambda: clock[0])
    monkeypatch.setattr(main, "_patrol_next", lambda wait, now: now + wait)

    class R(FakeRoutine):
        patrol_wait = 3600
    FakeRoutine.patrols, state = 0, {}
    main._claim_patrol(R(), state)
    clock[0] += 1800
    main._claim_patrol(R(), state)  # 30 min later: still nothing to claim
    assert FakeRoutine.patrols == 1
    clock[0] += 1800
    main._claim_patrol(R(), state)
    assert FakeRoutine.patrols == 2


def test_patrol_next_check_is_the_claim_time_or_midnight():
    from datetime import datetime
    evening = datetime(2026, 10, 12, 20, 0).timestamp()
    assert main._patrol_next(3600, evening) == evening + 3600
    assert main._patrol_next(6 * 3600, evening) == datetime(2026, 10, 13, 0, 0).timestamp()  # quick patrols reset
    assert main._patrol_next(None, evening) == evening  # unreadable counter: check after the next level


def test_missing_star_challenge_plays_the_last_unlocked_level(monkeypatch):
    class Nav(FakeNav):
        def start_pending_stars(self, mode):
            raise main.StarsUnavailable("Desafio de Estrellas is not unlocked on this account")
    nav = Nav(energy=10)
    report = run_with(monkeypatch, nav, [V], RunRequest(Mode.NORMAL, None, last_beaten=True, pending_stars=True))
    assert report.results == [V] and nav.started == ["detect", ("latest", 13)]


def test_missing_elite_mode_stops_without_restarting(monkeypatch):
    from roguebot.navigation import EliteUnavailable
    class Nav(FakeNav):
        def start_latest(self, mode):
            raise EliteUnavailable("Elite mode is not unlocked on this account")
    FakeEmulator.shutdowns = 0
    with pytest.raises(EliteUnavailable):
        run_with(monkeypatch, Nav(energy=10), [], RunRequest(Mode.ELITE, None))
    assert FakeEmulator.shutdowns == 0


def test_without_star_challenge_a_won_level_is_not_pinned(monkeypatch):
    """Review: "last unlocked" + repeat pins the won level and replays it from the star list, which this
    account doesn't have: fall back to the last unlocked level and stop trying the star list."""
    class Nav(FakeNav):
        def start_star_challenge(self, mode, level):
            self.started.append(("stars?", level))
            raise main.StarsUnavailable("Desafio de Estrellas is not unlocked on this account")
    nav = Nav(energy=15)
    report = run_with(monkeypatch, nav, [V, V, V], RunRequest(Mode.NORMAL, None, repeat=True))
    assert report.results == [V, V, V]
    assert nav.started == ["detect", ("latest", 13), ("stars?", 13), ("latest", 13), ("latest", 13)]


def test_failed_patrol_is_retried_much_later(monkeypatch):
    class R(FakeRoutine):
        def patrol(self):
            FakeRoutine.patrols += 1
            raise main.NavigationError("Patrol button not found in the lobby")

    class Nav:
        def go_to_lobby(self):
            pass
    clock = [1_000_000.0]
    monkeypatch.setattr(main.time, "time", lambda: clock[0])
    FakeRoutine.patrols, state = 0, {}
    main._claim_patrol(R(nav=Nav()), state)
    main._claim_patrol(R(nav=Nav()), state)  # one failure can be a hiccup: tried again after the next level
    clock[0] += 3600
    main._claim_patrol(R(nav=Nav()), state)  # two in a row: not before the reward could be due
    assert FakeRoutine.patrols == 2


def test_a_restart_during_the_routine_resumes_it_with_the_parts_done_so_far(monkeypatch):
    """The routine gets the run's state: after an emulator restart it continues at the part that broke."""
    seen = []

    class Breaks(FakeRoutine):
        def run_parts(self, progress=None):
            seen.append(list(progress.get("parts", [])))
            if len(seen) == 1:
                progress.setdefault("parts", []).append(("vip", "done"))
                raise main.NavigationError("the emulator froze in the arena")  # not a part failure: a restart
            return super().run_parts(progress)
    monkeypatch.setattr(main, "Routine", Breaks)
    report = run_with(monkeypatch, FakeNav(energy=10), [V], RunRequest(Mode.NORMAL, 4, repeat=True, full=True))
    assert seen == [[], [("vip", "done")]]  # the second try knows VIP is done
    assert report.parts == [("vip", "done"), ("arena", "done"), ("raid", "skipped")]


def test_a_level_left_running_is_played_out_first(monkeypatch):
    """Live 2026-10-15: started while a level was running (bot stopped mid-level), go_to_lobby could not leave
    the level board and MuMu was restarted. Now the level is played out first."""
    nav = FakeNav(energy=10)
    nav.in_level = True
    report = run_with(monkeypatch, nav, [D, V], RunRequest(Mode.NORMAL, 4))
    assert report.results == [V]  # the leftover level (D) is played, then the requested run
    assert nav.started == ["detect", ("stars", 4)]
