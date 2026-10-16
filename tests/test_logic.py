"""Pure logic that needs no screenshots."""

import sys
from pathlib import Path

import pytest

from roguebot import config, labels
from roguebot.device import Device, DeviceError, Frozen, device_scale, focused_package
from roguebot.navigation import NavigationError, Navigator
from roguebot.play import Player
from roguebot.screens import Card, Mode
from roguebot.request import RunRequest, build_request
from roguebot.vision import Text


def card(number: int, header_y: int) -> Card:
    return Card(number, Text(f"{number}. Level", 40, header_y - 25, 600, header_y + 25), None)


def test_scroll_delta_towards_lower_level():
    # Cards 11-13 visible, target 2 is 9+ cards above: scroll up, capped at MAX_DRAG.
    assert Navigator._scroll_delta([card(11, 700), card(12, 1267)], 2) == -1100


def test_scroll_delta_small_adjustment():
    # Target header just below the aim point: small downward scroll, at least MIN_DRAG.
    assert Navigator._scroll_delta([card(7, 750)], 7) == 150


def test_scroll_delta_one_card_down():
    assert Navigator._scroll_delta([card(5, 700)], 6) == 567


def test_build_request_latest_ignores_level():
    assert build_request("elite", "latest", "") == RunRequest(Mode.ELITE, None)


def test_build_request_stars():
    assert build_request("normal", "stars", " 7 ") == RunRequest(Mode.NORMAL, 7)


@pytest.mark.parametrize("level", ["", "abc", "0", "-3"])
def test_build_request_rejects_bad_level(level):
    with pytest.raises(ValueError):
        build_request("normal", "stars", level)


@pytest.mark.parametrize("w, h, scale", [(1440, 2560, 1.0), (1080, 1920, 0.75), (720, 1280, 0.5)])
def test_device_scale(w, h, scale):
    assert device_scale(w, h) == scale


@pytest.mark.parametrize("w, h", [(1080, 2400), (1600, 900)])
def test_device_scale_rejects_other_aspect_ratios(w, h):
    with pytest.raises(DeviceError):
        device_scale(w, h)


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _watched_device(monkeypatch) -> tuple[Device, _Clock]:
    """A Device without adb: only its freeze watchdog."""
    clock = _Clock()
    monkeypatch.setattr("roguebot.device.time.monotonic", clock)
    device = Device.__new__(Device)
    device._thumb, device._active = None, clock()
    return device, clock


def _frame(value: int):
    import numpy as np
    return np.full((2560, 1440, 3), value, np.uint8)


def test_freeze_watchdog_raises_on_the_same_frame_with_no_input(monkeypatch):
    device, clock = _watched_device(monkeypatch)
    device._watch(_frame(50))
    clock.t += config.FREEZE_TIMEOUT - 1
    device._watch(_frame(50))
    clock.t += 2
    with pytest.raises(Frozen):
        device._watch(_frame(50))


def test_freeze_watchdog_screen_changes_and_input_keep_it_alive(monkeypatch):
    device, clock = _watched_device(monkeypatch)
    for i in range(5):  # auto-play: no input, but the screen moves
        clock.t += config.FREEZE_TIMEOUT - 1
        device._watch(_frame(50 + 10 * (i % 2)))
    clock.t += config.FREEZE_TIMEOUT - 1
    device._touch()  # a tap
    clock.t += config.FREEZE_TIMEOUT - 1
    device._watch(_frame(50))


def test_freeze_watchdog_ignores_sparkles():
    import cv2
    from roguebot.device import frame_changed
    thumb = lambda n: cv2.resize(cv2.cvtColor(cv2.imread(str(Path(__file__).parent / "fixtures" / n)), cv2.COLOR_BGR2GRAY),
                                 config.FREEZE_THUMB, interpolation=cv2.INTER_AREA)
    # Two frames of the revive countdown differ; the same frame does not.
    assert frame_changed(thumb("level_revive.png"), thumb("level_revive_last_second.png"))
    assert not frame_changed(thumb("level_revive.png"), thumb("level_revive.png"))


@pytest.mark.parametrize("dump, package", [
    ("  mCurrentFocus=Window{450bd u0 app.lawnchair/app.lawnchair.LawnchairLauncher}\n"
     "  mFocusedApp=ActivityRecord{c2e9e40 u0 app.lawnchair/.LawnchairLauncher t2}", "app.lawnchair"),
    ("  mCurrentFocus=null\n  mFocusedApp=ActivityRecord{c2 u0 com.pockethaven.roguelegend/com.unity3d.A t9}",
     "com.pockethaven.roguelegend"),
    ("  mCurrentFocus=null\n  mFocusedApp=null", ""),
])
def test_focused_package(dump, package):
    assert focused_package(dump) == package


def test_overlay_packages_finds_the_mumu_store_ad_only():
    from roguebot.device import overlay_packages
    dump = (Path(__file__).parent / "fixtures" / "dumpsys_windows_mumu_store_overlay.txt").read_text()
    # Hidden system overlays and the game itself are never listed.
    assert overlay_packages(dump) == ["com.mumu.store"]
    assert overlay_packages(dump.replace("mViewVisibility=0x0 mHaveFrame=true mObscured=false\n    mHasSurface=true isReadyForDisplay()=true mWindowRemovalAllowed=false\n  Window #5",
                                         "mViewVisibility=0x8 mHaveFrame=true mObscured=false\n    mHasSurface=false isReadyForDisplay()=false mWindowRemovalAllowed=false\n  Window #5")) == []


def test_screenshot_force_stops_an_overlay_ad_and_takes_a_new_frame(monkeypatch):
    import cv2
    import numpy as np
    dump = (Path(__file__).parent / "fixtures" / "dumpsys_windows_mumu_store_overlay.txt").read_text()
    png = cv2.imencode(".png", np.zeros((2560, 1440, 3), np.uint8))[1].tobytes()
    calls = []

    class Adb:
        def shell(self, cmd, encoding="utf-8", timeout=None):
            calls.append(cmd)
            if cmd == ["dumpsys", "window", "windows"]:
                return dump if not any(c[:2] == ["am", "force-stop"] for c in calls) else ""
            return png if cmd == "screencap -p" else ""

    monkeypatch.setattr("roguebot.device.time.sleep", lambda s: None)
    device = Device.__new__(Device)
    device._d, device._stop, device._scale = Adb(), None, 1
    device._thumb, device._active, device._overlay_check = None, 0.0, 0.0
    device.screenshot()
    assert ["am", "force-stop", "com.mumu.store"] in calls
    assert calls.count("screencap -p") == 2  # the frame with the ad is dropped
    device.screenshot()  # checked again only after OVERLAY_CHECK_INTERVAL
    assert calls.count(["dumpsys", "window", "windows"]) == 1


class FakeDevice:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, settle=0):
        self.taps.append((x, y))


def speed_texts(speed):
    return [Text(f"» x{speed}", 80, 2410, 230, 2460)]


def test_speed_x1_is_switched_once():
    device = FakeDevice()
    player = Player(device, ocr=None)
    assert player._ensure_double_speed(speed_texts(1)) is True
    assert device.taps == [config.SPEED_BUTTON]
    assert player._ensure_double_speed(speed_texts(2)) is False
    assert device.taps == [config.SPEED_BUTTON]


def test_speed_locked_is_not_retried():
    device = FakeDevice()
    player = Player(device, ocr=None)
    player._ensure_double_speed(speed_texts(1))
    assert player._ensure_double_speed(speed_texts(1)) is False  # still x1 after tapping: locked
    assert player._ensure_double_speed(speed_texts(1)) is False
    assert device.taps == [config.SPEED_BUTTON]


def test_speed_absent_does_nothing():
    device = FakeDevice()
    assert Player(device, ocr=None)._ensure_double_speed([]) is False
    assert device.taps == []


def test_build_request_repeat_flag():
    assert build_request("elite", "stars", "3", repeat=True) == RunRequest(Mode.ELITE, 3, True)
    assert build_request("normal", "latest", "", repeat=False).repeat is False


@pytest.mark.parametrize("s, value", [("534,8k", 534800), ("3,4m", 3400000), ("339k", 339000), ("1045", 1045),
                                      ("62,9b", 62900000000), ("70.7K", 70700), ("Win:", None), ("x1", None)])
def test_parse_power(s, value):
    from roguebot.mode_screens import parse_power
    assert parse_power(s) == value


def test_pick_opponent_closest_not_stronger():
    from roguebot.mode_screens import Opponent, pick_opponent
    opponents = [Opponent(p, None) for p in (600, 100, 499, 500, 501)]
    assert pick_opponent(500, opponents).power == 500
    assert pick_opponent(50, opponents) is None  # all stronger: caller refreshes (if free) or takes the weakest


def test_build_request_full_routine_implies_repeat():
    request = build_request("normal", "latest", "", repeat=False, full=True)
    assert request.full and request.repeat


def test_skill_choice_prefers_highest_rarity():
    from roguebot import labels
    from roguebot.mode_screens import parse_skill_choice
    from roguebot.vision import Text
    labels.set_language("en")
    try:
        texts = [Text("Select a Skill to learn!", 400, 560, 1040, 600),
                 Text("Common", 280, 740, 360, 770), Text("Epic", 280, 1050, 360, 1080),
                 Text("Mythic", 280, 1360, 360, 1390), Text("Epic", 280, 1660, 360, 1690),
                 Text("Learn Skills (0/2)", 700, 2130, 1080, 2170)]
        choice = parse_skill_choice(texts)
    finally:
        labels.set_language(None)
    assert [y for _, y in choice.cards] == [1465, 1155, 1765, 845]  # mythic, epic (top first), epic, common
    assert (choice.chosen, choice.needed) == (0, 2)


def test_device_raises_stopped_once_stop_is_set():
    import threading
    from roguebot.device import Device, Stopped
    d = Device.__new__(Device)  # no emulator: only the stop check is exercised
    d._stop = threading.Event()
    d._check_stop()
    d._stop.set()
    with pytest.raises(Stopped):
        d.tap(10, 10)
    with pytest.raises(Stopped):
        d.screenshot()


class _TapLog:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, settle=0):
        self.taps.append((x, y))

    def foreground_package(self):
        return config.PACKAGE


def _start_with_frames(monkeypatch, frames):
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation, "START_RETAP_AFTER", 0)
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    nav = Navigator(_TapLog(), None)
    frames = iter(frames)
    black = np.zeros((2560, 1440, 3), np.uint8)
    nav._capture = lambda: (black, next(frames))
    return nav


START = Text("INICIO", 600, 2060, 716, 2120)
LOBBY = [START, Text("Patrulla", 650, 1900, 790, 1945)]
LOADING = [Text("Cargando...", 600, 1260, 840, 1320)]
IN_LEVEL = [Text("Toca para continuar", 500, 2320, 940, 2370)]


def test_start_tap_is_repeated_when_it_did_not_register(monkeypatch):
    nav = _start_with_frames(monkeypatch, [LOBBY, LOADING, IN_LEVEL])
    nav._press_start(START, Mode.NORMAL)
    assert nav.device.taps == [START.center, START.center]  # first tap + one retap; loading = registered


def test_start_tap_is_retried_at_most_twice(monkeypatch):
    from roguebot import navigation
    nav = _start_with_frames(monkeypatch, [LOBBY] * 5 + [IN_LEVEL])
    nav._press_start(START, Mode.NORMAL)
    assert len(nav.device.taps) == 1 + navigation.START_RETAPS


def test_jittering_taps_count_as_repeats():
    from roguebot.play import _same_tap
    from roguebot.screens import LevelScreen
    event = LevelScreen.EVENT
    assert _same_tap((event, (76, 1991)), (event, (78, 1990)))  # OCR jitter: still the same tap
    assert not _same_tap((event, (76, 1991)), (event, (500, 1991)))  # another option
    assert not _same_tap((event, (76, 1991)), (LevelScreen.SHOP, (76, 1991)))
    assert not _same_tap((event, (76, 1991)), None)


def test_energy_claim_closes_a_late_promo_and_reopens_the_energy_popup(monkeypatch, tmp_path):
    import numpy as np
    from roguebot import labels, navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "DEBUG_DIR", tmp_path)
    labels.set_language("es")
    promo = [Text("Oferta limitada!", 600, 850, 840, 890), Text("Toca en cualquier lugar para cerrar", 440, 2440, 1000, 2480)]
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945), Text("3/32", 820, 70, 890, 100)]
    popup = [Text("Comprar", 660, 745, 780, 785), Text("Intentos Restantes Hoy:", 330, 1255, 650, 1290),
             Text("0", 480, 1295, 500, 1330)]
    frames = iter([lobby, promo, lobby, popup, lobby])
    black = np.zeros((2560, 1440, 3), np.uint8)
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (black, next(frames))
    try:
        assert nav.claim_free_energy() == 3
    finally:
        labels.set_language(None)
    energy_icon, close_text = config.ENERGY_ICON, (720, 2460)
    assert nav.device.taps == [energy_icon, close_text, energy_icon, config.ENERGY_POPUP_CLOSE]


def test_go_to_lobby_prefers_the_back_arrow_over_the_footer(monkeypatch):
    """On mode screens the footer tab spot is their Challenge button: never tap it while a back arrow shows."""
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "footer_visible", lambda img: True)  # e.g. a transition frame
    monkeypatch.setattr(navigation, "back_arrow", lambda img: (120, 2447))
    monkeypatch.setattr(navigation, "close_button", lambda img: None)
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945)]
    tower = [Text("Tower of Heroes 16", 560, 245, 880, 290), Text("Challenge", 620, 2395, 820, 2440)]
    frames = iter([tower, lobby])
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    nav.go_to_lobby()
    assert nav.device.taps == [(120, 2447)]


def test_detect_language_retries_when_the_game_leaves_the_lobby(monkeypatch):
    """After the daily reset the game once opened the Fishing event right after the lobby showed."""
    import numpy as np
    from roguebot import labels, navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "back_arrow", lambda img: (120, 2447))
    monkeypatch.setattr(navigation, "close_button", lambda img: None)
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945)]
    event = [Text("Evento de Pesca", 60, 60, 370, 100), Text("Viaje de Pesca", 540, 1660, 900, 1710)]
    frames = iter([lobby, event, event, lobby, lobby])
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    try:
        assert nav.detect_language() == "es"
    finally:
        labels.set_language(None)
    assert nav.device.taps == [(120, 2447)]  # left the event through its back arrow


def test_build_request_loop_implies_full_routine():
    request = build_request("normal", "latest", "", loop=True)
    assert request.loop and request.full and request.repeat
    assert not build_request("normal", "latest", "", full=True).loop


def test_build_request_last_beaten_ignores_level():
    request = build_request("elite", "beaten", "")
    assert request == RunRequest(Mode.ELITE, None, last_beaten=True)
    assert not build_request("normal", "latest", "").last_beaten
    assert not build_request("normal", "stars", "4").last_beaten


def _lobby_nav(monkeypatch, title):
    import numpy as np
    from roguebot import labels, navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    labels.set_language("es")
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945),
             Text(title, 480, 560, 960, 600)]
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), lobby)
    nav.device.screenshot = lambda: np.zeros((2560, 1440, 3), np.uint8)
    return nav


def test_last_beaten_is_the_level_before_the_lobby_level(monkeypatch):
    nav = _lobby_nav(monkeypatch, "13. Bosque Embrujado II")
    started = []
    monkeypatch.setattr(nav, "start_star_challenge", lambda mode, level: started.append((mode, level)))
    try:
        assert nav.start_last_beaten(Mode.NORMAL) == 12
    finally:
        labels.set_language(None)
    assert started == [(Mode.NORMAL, 12)]


def test_last_beaten_fails_on_level_one(monkeypatch, tmp_path):
    from roguebot import navigation
    monkeypatch.setattr(navigation, "DEBUG_DIR", tmp_path)
    nav = _lobby_nav(monkeypatch, "1. Bosque")
    try:
        with pytest.raises(navigation.LevelUnavailable, match="No beaten"):
            nav.start_last_beaten(Mode.NORMAL)
    finally:
        labels.set_language(None)


def test_go_to_lobby_closes_a_long_popup_chain(monkeypatch):
    """Unlocking a new chapter chained 6+ popups (album, events...) after the victory."""
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "close_button", lambda img: None)
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945)]
    popup = lobby + [Text("Toca en cualquier lugar para cerrar", 440, 2340, 1000, 2380)]
    frames = iter([popup] * 10 + [lobby])
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    nav.go_to_lobby()
    assert len(nav.device.taps) == 10



def test_go_to_lobby_follows_the_tutorial_hand(monkeypatch):
    """A forced tutorial hand (new Album button) made every routine tap do nothing for a whole run."""
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "close_button", lambda img: None)
    hands = iter([(1377, 285), None, None])
    monkeypatch.setattr(navigation, "tutorial_hand", lambda img: next(hands))
    monkeypatch.setattr(navigation, "back_arrow", lambda img: (120, 2447))
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945)]
    album = [Text("Completa todos los conjuntos para elegir:", 400, 530, 1040, 575)]
    frames = iter([lobby, album, lobby])
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    nav.go_to_lobby()
    assert nav.device.taps == [(1377, 285), (120, 2447)]  # the hand's button, then back out of the album


def test_energy_claim_rereads_while_videos_are_left_without_a_button(monkeypatch, tmp_path):
    """Live: after one video the bot stopped ("No free energy left") with video chances still left."""
    import numpy as np
    from roguebot import navigation
    from roguebot.screens import EnergyOffers
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "DEBUG_DIR", tmp_path)
    offers = iter([EnergyOffers(None, None, 2), EnergyOffers(None, (480, 1450), 2), EnergyOffers(None, None, 0)])
    monkeypatch.setattr(navigation, "parse_energy_popup", lambda img, texts: next(offers))
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945), Text("20/32", 820, 70, 890, 100)]
    nav = Navigator(_TapLog(), None, ads=True)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), lobby)
    labels.set_language("es")
    try:
        assert nav.claim_free_energy() == 20
    finally:
        labels.set_language(None)
    assert nav.device.taps == [config.ENERGY_ICON, (480, 1450), config.ENERGY_POPUP_CLOSE]  # waited, then the video
    assert len(list(tmp_path.glob("energy_cooldown_*.png"))) == 1


def test_energy_claim_gives_up_after_rereads(monkeypatch, tmp_path):
    import numpy as np
    from roguebot import navigation
    from roguebot.screens import EnergyOffers
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "DEBUG_DIR", tmp_path)
    monkeypatch.setattr(navigation, "parse_energy_popup", lambda img, texts: EnergyOffers(None, None, 2))
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945), Text("3/32", 820, 70, 890, 100)]
    nav = Navigator(_TapLog(), None, ads=True)  # rereads wait for a video: only with ads
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), lobby)
    labels.set_language("es")
    try:
        assert nav.claim_free_energy() == 3
    finally:
        labels.set_language(None)
    assert nav.device.taps == [config.ENERGY_ICON, config.ENERGY_POPUP_CLOSE]
    assert len(list(tmp_path.glob("energy_none_*.png"))) == 1  # the popup is kept to diagnose missed videos


def _resume_nav(monkeypatch, frames):
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "close_button", lambda img: None)
    monkeypatch.setattr(navigation, "DEBUG_DIR", __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    nav = Navigator(_TapLog(), None)
    frames = iter(frames)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    return nav


RESUME = [Text("Continue Adventure?", 520, 875, 920, 920), Text("You have an ongoing", 520, 1140, 920, 1190),
          Text("Abandon", 470, 1395, 630, 1440), Text("OK", 860, 1395, 920, 1440)]
EN_LOBBY = [Text("Patrol", 650, 1900, 790, 1945), Text("OFF", 900, 2060, 970, 2095),
            Text("START", 600, 2070, 716, 2115), Text("Challenge", 840, 1910, 960, 1945)]


def test_go_to_lobby_resumes_an_interrupted_level(monkeypatch):
    nav = _resume_nav(monkeypatch, [RESUME, EN_LOBBY])
    played = []
    nav.resume_level = lambda: played.append("level")
    labels.set_language("en")
    try:
        nav.go_to_lobby()
    finally:
        labels.set_language(None)
    assert nav.device.taps == [(890, 1417)] and played == ["level"]  # OK (resume), never Abandon


def test_go_to_lobby_plays_out_a_level_left_on_screen(monkeypatch):
    nav = _resume_nav(monkeypatch, [[], EN_LOBBY])
    monkeypatch.setattr(Navigator, "_on_board", staticmethod(lambda img, texts: not texts))
    played = []
    nav.resume_level = lambda: played.append("level")
    labels.set_language("en")
    try:
        nav.go_to_lobby()
    finally:
        labels.set_language(None)
    assert played == ["level"] and nav.device.taps == []


def test_go_to_lobby_without_a_player_stops_at_the_resume_prompt(monkeypatch):
    nav = _resume_nav(monkeypatch, [RESUME])
    labels.set_language("en")
    try:
        with pytest.raises(NavigationError, match="interrupted level"):
            nav.go_to_lobby()
    finally:
        labels.set_language(None)
    assert nav.device.taps == []


def test_star_list_waits_until_the_target_card_stops_moving(monkeypatch):
    """Live: the START tap landed while the list was still gliding, and the level never started."""
    import numpy as np
    from roguebot import navigation
    from roguebot.screens import Card
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)

    def card(y):
        return [Card(10, Text("10. Runelight Caverns", 100, y - 400, 460, y - 360), Text("START", 640, y - 20, 800, y + 20))]
    frames = iter([card(1700), card(1571), card(1571)])
    monkeypatch.setattr(navigation, "parse_star_list", lambda img, texts, ocr: next(frames))
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), [])
    target = nav._scroll_to(10)
    assert target.button.center == (720, 1571)  # the settled position, not the first (moving) one


def test_go_to_lobby_stops_with_an_error_when_the_game_needs_an_update(monkeypatch):
    from roguebot.emulator import EmulatorError
    nav = _resume_nav(monkeypatch, [[Text("Nueva Actualización", 520, 900, 920, 950), Text("ACTUALIZAR", 600, 1360, 840, 1410)]])
    labels.set_language(None)  # before the language is known
    with pytest.raises(EmulatorError) as e:
        nav.go_to_lobby()
    assert e.value.key == "err_game_update" and nav.device.taps == []  # never taps ACTUALIZAR itself


def test_repeated_taps_need_time_too_before_giving_up(monkeypatch):
    """Taps are fast now: a slow screen change must not look stuck after 6 quick taps."""
    import numpy as np
    from roguebot import play
    from roguebot.screens import LevelScreen, LevelState
    clock = iter(range(0, 1000))
    monkeypatch.setattr(play.time, "monotonic", lambda: next(clock) * 0.2)  # 0.2 s per tick
    monkeypatch.setattr(play.time, "sleep", lambda s: None)
    states = iter([LevelState(LevelScreen.CONTINUE, (720, 2380))] * 9 + [LevelState(LevelScreen.VICTORY, (720, 2300))])
    monkeypatch.setattr(play, "classify_level_screen", lambda img, texts: next(states))

    class Dev:
        taps = []

        def screenshot(self):
            return np.zeros((10, 10, 3), np.uint8)

        def tap(self, x, y, settle=0):
            Dev.taps.append((x, y))

    class NoOcr:
        def read(self, img):
            return []
    player = play.Player(Dev(), NoOcr())
    assert player.play_level() is LevelScreen.VICTORY  # 9 quick repeats (< 10 s): not stuck


def test_elite_cost_waits_for_the_new_cost_before_pressing_again(monkeypatch):
    """A stale frame (still x5) right after "+" must not lead to a second "+" (15 instead of 10)."""
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)

    def dialog(cost):
        return [Text("Modo Élite", 560, 600, 880, 650), Text("INICIO", 600, 1880, 840, 1930),
                Text(f"x{cost}", 690, 1960, 750, 2000), Text("12/32", 820, 70, 890, 100)]
    frames = iter([dialog(5), dialog(5), dialog(10)])  # first read, stale frame after "+", updated
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    labels.set_language("es")
    try:
        nav._set_elite_cost()
    finally:
        labels.set_language(None)
    assert nav.device.taps == [config.ELITE_COST_PLUS]  # one "+" only: 5 -> 10 (energy 12)


def test_build_request_pending_stars():
    r = build_request("normal", "pending", "", mumu_folder="C:/MuMu")
    assert r.pending_stars and r.last_beaten and r.level is None and r.mumu_folder == "C:/MuMu"
    assert not build_request("normal", "beaten", "").pending_stars
    assert build_request("normal", "stars", "4", loop=True, mumu_folder="X").mumu_folder == "X"


def _star_nav(monkeypatch, pages):
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    pages = iter(pages)
    monkeypatch.setattr(navigation, "parse_star_list", lambda img, texts, ocr: next(pages))
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), [])
    nav._open_star_list = lambda mode: None
    nav.drags, nav.started = [], []
    nav._drag_list = lambda delta: nav.drags.append(delta)
    nav._press_start = lambda button, mode: nav.started.append(button.center)
    return nav


def _card(n, stars, y):
    from roguebot.screens import Card
    return Card(n, Text(f"{n}. Level", 100, y - 400, 460, y - 360), Text("INICIO", 640, y - 20, 800, y + 20), stars)


def test_pending_stars_plays_a_level_missing_stars(monkeypatch):
    from roguebot.screens import Mode
    nav = _star_nav(monkeypatch, [[_card(12, 2, 1080), _card(13, 3, 1650)]])
    nav._scroll_to = lambda level: _card(level, 2, 1080)
    assert nav.start_pending_stars(Mode.NORMAL) == 12
    assert nav.started == [(720, 1080)] and nav.drags == []


def test_pending_stars_scrolls_up_then_gives_up_at_level_1(monkeypatch):
    from roguebot.screens import Mode
    nav = _star_nav(monkeypatch, [[_card(12, 3, 1080), _card(13, 3, 1650)], [_card(1, 3, 600), _card(2, 3, 1170)]])
    assert nav.start_pending_stars(Mode.NORMAL) is None
    assert nav.started == [] and len(nav.drags) == 1 and nav.drags[0] < 0  # dragged towards lower levels


def test_version():
    import roguebot
    assert roguebot.__version__ == "1.5.1"


def test_data_dir_is_next_to_the_exe_when_frozen(monkeypatch, tmp_path):
    from roguebot import settings
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "RogueLegendBot.exe"))
    assert settings.data_dir() == tmp_path / "data"


def test_data_dir_is_the_repo_data_folder_from_source():
    from roguebot import settings
    assert settings.data_dir() == Path(settings.__file__).parent.parent / "data"


def test_seed_data_copies_skills_once(tmp_path):
    from roguebot import settings
    bundled = tmp_path / "bundled.json"
    bundled.write_text('{"a": 1}', encoding="utf-8")
    target = tmp_path / "data"
    settings.seed_data(target, bundled)
    assert (target / "skills.json").read_text(encoding="utf-8") == '{"a": 1}'
    (target / "skills.json").write_text('{"edited": 1}', encoding="utf-8")
    settings.seed_data(target, bundled)
    assert (target / "skills.json").read_text(encoding="utf-8") == '{"edited": 1}'


def _play(monkeypatch, kinds, texts=()):
    """Run Player.play_level over a list of screen states (OCR reads `texts`); returns the device's (action, point) log."""
    import numpy as np
    from roguebot import play
    from roguebot.screens import LevelState
    monkeypatch.setattr(play.time, "sleep", lambda s: None)
    states = iter(LevelState(k, t) for k, t in kinds)
    monkeypatch.setattr(play, "classify_level_screen", lambda img, texts: next(states))

    class Dev:
        actions = []

        def screenshot(self):
            return np.zeros((10, 10, 3), np.uint8)

        def tap(self, x, y, settle=0):
            Dev.actions.append(("tap", (x, y)))

        def hold(self, x, y, seconds, settle=0):
            Dev.actions.append(("hold", (x, y)))

    class NoOcr:
        def read(self, img):
            return list(texts)
    play.Player(Dev(), NoOcr()).play_level()
    return Dev.actions


def test_red_dice_is_held_for_auto_play_then_left_alone(monkeypatch):
    from roguebot.screens import LevelScreen as S
    dice = config.DICE_BUTTON
    actions = _play(monkeypatch, [(S.BOARD_READY, dice), (S.AUTO_PLAY, None), (S.AUTO_PLAY, None),
                                  (S.SKILL_PICK, (720, 1052)), (S.AUTO_PLAY, None), (S.VICTORY, (720, 2220))])
    assert actions == [("hold", dice), ("tap", (720, 1052)), ("tap", (720, 2220))]


def test_auto_play_stopping_mid_level_is_turned_on_again(monkeypatch):
    from roguebot.screens import LevelScreen as S
    dice = config.DICE_BUTTON
    actions = _play(monkeypatch, [(S.BOARD_READY, dice), (S.AUTO_PLAY, None), (S.BOARD_READY, dice),
                                  (S.AUTO_PLAY, None), (S.VICTORY, (720, 2220))])
    assert actions == [("hold", dice), ("hold", dice), ("tap", (720, 2220))]


def test_without_auto_play_the_dice_is_tapped(monkeypatch):
    """Holding brought the red dice back (no auto-play on this game version): roll by taps from then on."""
    from roguebot.screens import LevelScreen as S
    dice = config.DICE_BUTTON
    actions = _play(monkeypatch, [(S.BOARD_READY, dice), (S.BOARD_READY, dice), (S.FIGHT, None),
                                  (S.BOARD_READY, dice), (S.VICTORY, (720, 2220))])
    assert actions == [("hold", dice), ("tap", dice), ("tap", dice), ("tap", (720, 2220))]


def test_without_ads_x2_rewards_is_skipped_and_revive_waits(monkeypatch):
    from roguebot.screens import LevelScreen as S
    actions = _play(monkeypatch, [(S.REVIVE, (990, 1455)), (S.REVIVE, (990, 1455)), (S.DOUBLE_REWARD, (1150, 2220)),
                                  (S.VICTORY, (720, 2220))])
    assert actions == [("tap", (720, 2220))]  # no revive video, no x2 video: just Continue


def test_watch_ads_is_off_by_default():
    assert RunRequest(Mode.NORMAL, None).ads is False
    assert build_request("normal", "latest", "1").ads is False
    assert build_request("normal", "latest", "1", ads=True).ads is True


def _lobby_texts(*extra):
    return [Text("Patrulla", 650, 1900, 790, 1945), Text("INICIO", 600, 2070, 716, 2115),
            Text("20/32", 820, 70, 890, 100), *extra]


def test_lobby_without_elite_or_star_challenge_is_still_the_lobby():
    """Other accounts may not have unlocked elite mode or Desafío de Estrellas yet."""
    from roguebot.screens import parse_lobby
    labels.set_language("es")
    try:
        lobby = parse_lobby(_lobby_texts())
    finally:
        labels.set_language(None)
    assert lobby.mode is Mode.NORMAL and not lobby.has_elite and lobby.stars_button is None and lobby.energy == 20


def _nav_on(texts):
    import numpy as np
    from roguebot import navigation
    nav = Navigator(_TapLog(), None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), texts)
    nav.device.screenshot = lambda: np.zeros((10, 10, 3), np.uint8)
    nav.saved = []
    nav._save = lambda img, name: nav.saved.append(name) or "debug/x.png"
    return nav, navigation


def test_missing_elite_or_star_challenge_raise_their_own_errors():
    nav, navigation = _nav_on(_lobby_texts())
    labels.set_language("es")
    try:
        with pytest.raises(navigation.EliteUnavailable):
            nav.start_latest(Mode.ELITE)
        with pytest.raises(navigation.StarsUnavailable):
            nav.start_star_challenge(Mode.NORMAL, 3)
    finally:
        labels.set_language(None)
    assert nav.device.taps == []  # never tapped the skull spot or a missing button


def test_lobby_is_read_again_before_a_button_counts_as_missing():
    """Review: one frame where OCR misses the stars button must not mean "not unlocked"."""
    from roguebot.screens import Lobby
    nav, navigation = _nav_on([])
    reads = iter([Lobby(Mode.NORMAL, None, None, None, 20), Lobby(Mode.NORMAL, None, None, Text("de Estrellas", 840, 1910, 960, 1945), 20)])
    nav.go_to_lobby = lambda: next(reads)
    assert nav._lobby_until(lambda lobby: lobby.stars_button is not None).stars_button is not None


def test_without_ads_a_revive_popup_that_stays_still_times_out(monkeypatch, tmp_path):
    """Review: waiting out the revive (no ads) must not wait forever if the popup never goes away."""
    from roguebot import play
    from roguebot.screens import LevelScreen as S
    clock = iter(range(1000))
    monkeypatch.setattr(play.time, "monotonic", lambda: next(clock) * 5.0)
    monkeypatch.setattr(play, "DEBUG_DIR", tmp_path)
    with pytest.raises(play.PlayError, match="unknown screen"):
        _play(monkeypatch, [(S.REVIVE, (990, 1455))] * 50)


def test_energy_videos_are_not_watched_without_ads(monkeypatch):
    import numpy as np
    from roguebot import navigation
    from roguebot.screens import EnergyOffers
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "parse_energy_popup", lambda img, texts: EnergyOffers(None, (480, 1450), 2))
    nav, _ = _nav_on(_lobby_texts(Text("APAGADO", 880, 2060, 990, 2095), Text("de Estrellas", 840, 1910, 960, 1945)))
    labels.set_language("es")
    try:
        assert nav.claim_free_energy() == 20
    finally:
        labels.set_language(None)
    assert nav.device.taps == [config.ENERGY_ICON, config.ENERGY_POPUP_CLOSE]  # the video button left alone
    assert nav.saved == []  # no "energy_none" screenshot for videos that are just switched off


def test_without_ads_the_level_end_continues_instead_of_doubling(monkeypatch):
    from roguebot.screens import LevelScreen as S
    labels.set_language("es")
    try:
        actions = _play(monkeypatch, [(S.DOUBLE_REWARD, (1150, 2220)), (S.VICTORY, (720, 2220))],
                        [Text("Continuar", 600, 2360, 840, 2400), Text("x2 Recompensas", 1000, 2200, 1300, 2240)])
    finally:
        labels.set_language(None)
    assert actions == [("tap", (720, 2380)), ("tap", (720, 2220))]  # Continuar, never the x2 ad button


class _OtherAppDevice(_TapLog):
    """The game is in front again after `backs` Back presses, `launches` launches or a tap on the ad."""
    def __init__(self, backs=None, launches=None, ad_tap=False):
        super().__init__()
        self.actions, self.backs, self.launches, self.ad_tap = [], backs, launches, ad_tap

    def _game(self):
        return (self.actions.count("back") == self.backs or self.actions.count("launch") == self.launches
                or (self.ad_tap and self.taps))

    def foreground_package(self):
        return config.PACKAGE if self._game() else "com.other.ad"

    def back(self, settle=0):
        self.actions.append("back")

    def launch(self, package, settle=0):
        assert package == config.PACKAGE
        self.actions.append("launch")


def _other_app_nav(monkeypatch, device):
    import numpy as np
    from roguebot import navigation
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "close_button", lambda img: None)
    monkeypatch.setattr(navigation, "back_arrow", lambda img: None)
    monkeypatch.setattr(navigation, "footer_visible", lambda img: False)
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945)]
    ad = [Text("Install now", 600, 1500, 840, 1550)]
    frames = iter([ad, lobby])
    nav = Navigator(device, None)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    return nav


def test_go_to_lobby_leaves_another_app_with_back(monkeypatch):
    device = _OtherAppDevice(backs=1)
    _other_app_nav(monkeypatch, device).go_to_lobby()
    assert device.actions == ["back"] and device.taps == []


def test_go_to_lobby_brings_the_game_back_when_back_does_nothing(monkeypatch):
    device = _OtherAppDevice(launches=1)
    _other_app_nav(monkeypatch, device).go_to_lobby()
    assert device.actions == ["back"] * config.BROWSER_BACK_MAX + ["launch"] and device.taps == []


def test_go_to_lobby_taps_an_ad_that_only_closes_by_tapping_it(monkeypatch):
    device = _OtherAppDevice(ad_tap=True)
    _other_app_nav(monkeypatch, device).go_to_lobby()
    assert device.taps == [config.OTHER_APP_AD_TAP]
    assert device.actions == ["back"] * config.BROWSER_BACK_MAX + ["launch"]


def test_go_to_lobby_waits_on_an_unknown_game_screen(monkeypatch):
    device = _OtherAppDevice()
    device.foreground_package = lambda: config.PACKAGE
    _other_app_nav(monkeypatch, device).go_to_lobby()
    assert device.actions == [] and device.taps == []  # the game's own screen: never tap blindly


def test_energy_claim_takes_the_reward_shown_over_the_popup_before_reading_it(monkeypatch, tmp_path):
    """Live 2026-10-15: the Daily Pack's "x15 / Toca en cualquier lugar para reclamar" banner covered the
    video button and its counter, and the bot stopped with 3 videos left (fixture energy_popup_pack_reward)."""
    import numpy as np
    from roguebot import navigation
    from roguebot.screens import EnergyOffers
    monkeypatch.setattr(navigation.time, "sleep", lambda s: None)
    monkeypatch.setattr(navigation, "DEBUG_DIR", tmp_path)
    offers = iter([EnergyOffers(Text("Gratis", 900, 1650, 1100, 1720), None, 3), EnergyOffers(None, (480, 1390), 3),
                   EnergyOffers(None, None, 0)])
    monkeypatch.setattr(navigation, "parse_energy_popup", lambda img, texts: next(offers))
    reward = [Text("Toca en cualquier lugar para reclamar", 320, 2300, 1120, 2345)]
    lobby = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
             Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945), Text("47/34", 820, 70, 890, 100)]
    frames = iter([lobby, lobby, reward, lobby, reward, lobby, lobby])  # lobby: the popup (offers are faked)
    nav = Navigator(_TapLog(), None, ads=True)
    nav._capture = lambda: (np.zeros((2560, 1440, 3), np.uint8), next(frames))
    labels.set_language("es")
    try:
        assert nav.claim_free_energy() == 47
    finally:
        labels.set_language(None)
    claim = (720, 2322)
    assert nav.device.taps == [config.ENERGY_ICON, (1000, 1685), claim, (480, 1390), claim, config.ENERGY_POPUP_CLOSE]
