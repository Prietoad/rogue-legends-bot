"""The tkinter window: info, translations, form behaviour (skipped if Tk is unavailable)."""

import pytest

tk = pytest.importorskip("tkinter")

from roguebot.i18n import TEXTS  # noqa: E402
from roguebot.report import Report  # noqa: E402
from roguebot.screens import LevelScreen  # noqa: E402
from roguebot.ui import App  # noqa: E402


@pytest.fixture(scope="module")
def _window(tmp_path_factory):
    # One window for all tests: creating several Tk roots in one process fails randomly on Windows.
    try:
        a = App(run=lambda request: Report([LevelScreen.VICTORY]), settings_path=tmp_path_factory.mktemp("ui") / "settings.json")
    except tk.TclError as e:  # no display available
        pytest.skip(f"Tk cannot open a window: {e}")
    yield a
    a.root.destroy()


@pytest.fixture
def app(_window):
    _window.set_language("en")
    _window.source.set("latest")
    _window._toggle_level()
    _window.level.set("1")
    return _window


def test_info_section_lists_requirements(app):
    shown = app.info.cget("text")
    assert shown == TEXTS["en"]["info"]
    for needed in ("MuMu Player 12 with Rogue Legend installed", "Spanish or English", "never spends gems",
                   "skips it and moves on", "options are saved"):
        assert needed in shown


def test_language_switch_translates_every_widget(app):
    app.set_language("es")
    assert app.info.cget("text") == TEXTS["es"]["info"]
    assert app.start.cget("text") == "Iniciar"
    assert app.root.title() == TEXTS["es"]["title"]
    for widget, key in app._texts:
        assert widget.cget("text") == TEXTS["es"][key]


def test_status_follows_language(app):
    app._finish(("report", {"report": Report([LevelScreen.VICTORY])}, "green"))
    assert app.status.cget("text") == "Level finished: Victory"
    app.set_language("es")
    assert app.status.cget("text") == "Nivel terminado: Victoria"


def test_level_entry_enabled_only_for_star_challenge(app):
    assert str(app.level_entry.cget("state")) == "disabled"
    app.source.set("stars")
    app._toggle_level()
    assert str(app.level_entry.cget("state")) == "normal"


def test_invalid_level_shows_error_status(app):
    app.source.set("stars")
    app.level.set("abc")
    app._start()
    assert app.status.cget("text") == TEXTS["en"]["bad_level"]
    assert str(app.start.cget("state")) != "disabled"


def test_repeat_checkbox_defaults_off(app):
    assert app.repeat.get() is False


class InlineThread:
    """Runs the worker right away on the test thread (Tk calls from other threads need a mainloop)."""
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_full_routine_checkbox_builds_a_full_request(app, monkeypatch):
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)
    assert app.full.get() is False
    requests = []
    monkeypatch.setattr(app, "run", lambda request: requests.append(request) or Report([LevelScreen.VICTORY]))
    app.full.set(True)
    try:
        app._start()
        app.root.update()
    finally:
        app.full.set(False)
    assert requests[0].full and requests[0].repeat


def test_stop_button(app, monkeypatch):
    from roguebot.device import Stopped
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)
    assert str(app.stop_button.cget("state")) == "disabled"  # idle
    seen = {}

    def run(request):  # the user presses Stop mid-run; the device then raises Stopped
        seen["stop_enabled"] = str(app.stop_button.cget("state"))
        app.stop_button.invoke()
        seen["status"] = app.status.cget("text")
        raise Stopped("Stopped by the user")
    stops = []
    monkeypatch.setattr(app, "run", run)
    monkeypatch.setattr(app, "stop", lambda: stops.append(1))
    app._start()
    app.root.update()
    assert seen == {"stop_enabled": "normal", "status": TEXTS["en"]["stopping"]}
    assert stops == [1]
    assert app.status.cget("text") == TEXTS["en"]["stopped"]
    assert str(app.start.cget("state")) == "normal"
    assert str(app.stop_button.cget("state")) == "disabled"


def test_build_section(app):
    from roguebot.build import Build
    assert app.build() == Build()  # defaults: physical, default order, no support
    app.order_list.selection_clear(0, "end")
    app.order_list.selection_set(2)  # fire
    app._move(-1)
    app._move(-1)
    app.nature.set("magic")
    app.support.set(True)
    app.support_every.set("2")
    try:
        assert app.build() == Build("magic", ("fire", "ice", "lightning", "shuriken", "venom", "bleed"), 2)
        assert app.order_list.get(0) == "1. Fire"
        app.set_language("es")
        assert app.order_list.get(0) == "1. Fuego"  # the list follows the UI language
    finally:
        app.damage_order = list(Build().order)
        app._refresh_order()
        app.nature.set("physical")
        app.support.set(False)


def test_loop_checkbox_builds_a_loop_request(app, monkeypatch):
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)
    assert app.loop.get() is False
    requests = []
    monkeypatch.setattr(app, "run", lambda request: requests.append(request) or Report([LevelScreen.VICTORY]))
    app.loop.set(True)
    try:
        app._start()
        app.root.update()
    finally:
        app.loop.set(False)
    assert requests[0].loop and requests[0].full and requests[0].repeat


def test_last_beaten_source_builds_a_last_beaten_request(app, monkeypatch):
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)
    requests = []
    monkeypatch.setattr(app, "run", lambda request: requests.append(request) or Report([LevelScreen.VICTORY]))
    app.source.set("beaten")
    app._toggle_level()
    try:
        assert str(app.level_entry.cget("state")) == "disabled"  # no number needed
        app._start()
        app.root.update()
    finally:
        app.source.set("latest")
        app._toggle_level()
    assert requests[0].last_beaten and requests[0].level is None


def test_mumu_folder_field_marks_valid_folders(app, tmp_path):
    good = tmp_path / "MuMuPlayer"
    (good / "nx_main").mkdir(parents=True)
    for exe in ("MuMuManager.exe", "adb.exe"):
        (good / "nx_main" / exe).write_bytes(b"")
    old = app.mumu_folder.get()
    try:
        app.mumu_folder.set(str(good))
        assert app.mumu_status.cget("text").startswith("✓")
        app.mumu_folder.set(str(tmp_path / "nothing"))
        assert app.mumu_status.cget("text").startswith("✗")
    finally:
        app.mumu_folder.set(old)


def test_start_passes_and_saves_the_mumu_folder(app, monkeypatch, tmp_path):
    from roguebot import settings
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)
    monkeypatch.setattr(app, "settings_path", tmp_path / "settings.json")
    good = tmp_path / "MuMu"
    (good / "shell").mkdir(parents=True)  # older MuMu 12 layout
    for exe in ("MuMuManager.exe", "adb.exe"):
        (good / "shell" / exe).write_bytes(b"")
    requests = []
    monkeypatch.setattr(app, "run", lambda request: requests.append(request) or Report([LevelScreen.VICTORY]))
    old = app.mumu_folder.get()
    try:
        app.mumu_folder.set(str(good))
        app._start()
        app.root.update()
    finally:
        app.mumu_folder.set(old)
    assert requests[0].mumu_folder == str(good)
    assert settings.load(tmp_path / "settings.json")["mumu_folder"] == str(good)


def test_emulator_errors_are_shown_translated(app, monkeypatch):
    from roguebot.emulator import EmulatorError
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)

    def fail(request):
        raise EmulatorError("err_mumu_boot", seconds=240)
    monkeypatch.setattr(app, "run", fail)
    app._start()
    app.root.update()
    assert app.status.cget("text").endswith(TEXTS["en"]["err_mumu_boot"].format(seconds=240))


def test_missing_stars_source_builds_a_pending_request(app, monkeypatch):
    monkeypatch.setattr("roguebot.ui.threading.Thread", InlineThread)
    requests = []
    monkeypatch.setattr(app, "run", lambda request: requests.append(request) or Report([LevelScreen.VICTORY]))
    app.source.set("pending")
    app._toggle_level()
    try:
        app._start()
        app.root.update()
    finally:
        app.source.set("latest")
        app._toggle_level()
    assert requests[0].pending_stars and requests[0].level is None


def test_window_has_the_game_icon(app):
    from roguebot.ui import ICON
    assert ICON.exists()
    assert (app.icon.width(), app.icon.height()) == (192, 192)
    assert app.header_icon.width() == 64


def test_header_shows_version(app):
    from roguebot import __version__
    assert app.header_title.cget("text") == f"Rogue Legend bot v{__version__}"


def test_changelog_is_hidden_until_toggled(app):
    from roguebot import __version__
    assert not app.changelog.winfo_ismapped() and not app.changelog_shown
    assert app.changelog_toggle.cget("text") == "▸ Changelog"
    app._toggle_changelog()
    assert app.changelog_shown and app.changelog.grid_info()
    assert f"## {__version__}" in app.changelog.get("1.0", "end")
    app.set_language("es")
    assert app.changelog_toggle.cget("text") == "▾ Novedades"
    app._toggle_changelog()
    assert not app.changelog_shown and not app.changelog.grid_info()


def test_watch_ads_option_explains_it_needs_ad_skip(app):
    assert app.ads.get() is False  # off by default
    assert "(only if the account has bought the skip ads option)" in TEXTS["en"]["ads"]
    assert "(solo si" in TEXTS["es"]["ads"]


def test_every_option_is_saved_and_restored(app, tmp_path, monkeypatch):
    from roguebot import settings
    monkeypatch.setattr(app, "settings_path", tmp_path / "settings.json")
    chosen = {"mode": "elite", "source": "stars", "level": "7", "repeat": True, "full": True, "loop": True,
              "ads": True, "nature": "magic", "support": True, "support_every": "4"}
    defaults = {k: getattr(app, k).get() for k in chosen}
    order = list(reversed(app.damage_order))
    try:
        for key, value in chosen.items():
            getattr(app, key).set(value)
        app.damage_order = list(order)
        app._save_options()
        saved = settings.load(tmp_path / "settings.json")
        assert {k: saved[k] for k in chosen} == chosen and saved["damage_order"] == order and saved["lang"] == "en"
        for key, value in defaults.items():  # a fresh window, then last session's choices
            getattr(app, key).set(value)
        app.damage_order = sorted(order)
        app._restore_options(saved)
        assert {k: getattr(app, k).get() for k in chosen} == chosen and app.damage_order == order
        assert str(app.level_entry.cget("state")) == "normal"  # "stars" enables the level box
    finally:
        for key, value in defaults.items():
            getattr(app, key).set(value)
        app.damage_order = sorted(order, key=list(reversed(order)).index)
        app._toggle_level()


def test_invalid_saved_options_keep_the_defaults(app):
    before = app.options()
    app._restore_options({"mode": "hard", "source": 3, "level": "-1", "repeat": "yes", "damage_order": ["fire"]})
    assert app.options() == before
