"""MuMu Player detection and the start sequence (emulator on, game installed and in front), with a
scripted fake of MuMuManager.exe / adb.exe instead of the real tools."""

import json
import threading

import pytest

from roguebot import config, emulator
from roguebot.device import Stopped
from roguebot.emulator import Emulator, EmulatorError

PKG = config.PACKAGE


def install(tmp_path, layout="nx_main"):
    folder = tmp_path / "MuMuPlayer"
    (folder / layout).mkdir(parents=True)
    for exe in ("MuMuManager.exe", "adb.exe"):
        (folder / layout / exe).write_bytes(b"")
    return folder


@pytest.mark.parametrize("layout", ["nx_main", "shell"])
def test_tools_in_both_mumu_layouts(tmp_path, layout):
    folder = install(tmp_path, layout)
    manager, adb = emulator.tools(folder)
    assert manager.name == "MuMuManager.exe" and adb.parent.name == layout


def test_tools_rejects_other_folders(tmp_path):
    assert emulator.tools(tmp_path) is None
    assert emulator.tools(tmp_path / "missing") is None


def test_find_install_uses_the_registry_first(tmp_path, monkeypatch):
    folder = install(tmp_path)
    monkeypatch.setattr(emulator, "_registry_folders", lambda: [tmp_path / "stale", folder])
    assert emulator.find_install() == folder


def test_find_install_none_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.setattr(emulator, "_registry_folders", lambda: [])
    monkeypatch.setattr(emulator, "INSTALL_GUESSES", ("no-such-mumu-folder",))
    assert emulator.find_install() is None


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "EMULATOR_POLL", 0)
    monkeypatch.setattr(config, "EMULATOR_BOOT_TIMEOUT", 0.05)
    monkeypatch.setattr(config, "GAME_OPEN_TIMEOUT", 0.05)
    monkeypatch.setattr(config, "EMULATOR_SHUTDOWN_TIMEOUT", 0.05)


class FakeMuMu:
    """Answers MuMuManager / adb commands from a little state machine; records every command."""

    def __init__(self, started=True, boots_after=0, installed=True, front=True, opens=True, connects=True):
        self.started, self.boots_after, self.installed = started, boots_after, installed
        self.front, self.opens, self.connects = front, opens, connects
        self.calls = []

    def __call__(self, args, timeout):
        cmd = " ".join(str(a) for a in args[1:])
        self.calls.append(cmd)
        if cmd == "info -v 0":
            if not self.started and self.boots_after is not None and "control -v 0 launch" in self.calls:
                self.boots_after -= 1
                self.started = self.boots_after <= 0
            info = {"is_android_started": self.started, "player_state": "start_finished" if self.started else "starting"}
            if self.started:
                info.update(adb_host_ip="127.0.0.1", adb_port=16416)
            return json.dumps(info)
        if cmd.startswith("connect"):
            return "connected to 127.0.0.1:16416" if self.connects else "cannot connect"
        if cmd.endswith("getprop sys.boot_completed"):
            return "1\n"
        if "pm list packages" in cmd:
            return f"package:{PKG}\n" if self.installed else ""
        if cmd.endswith("app launch -pkg " + PKG):
            self.front = self.opens
            return '{"errcode": 0}'
        if cmd.endswith("dumpsys window"):  # only this form prints mCurrentFocus on MuMu's Android
            app = PKG if self.front else "com.android.launcher"
            return f"  mCurrentFocus=Window{{1 u0 {app}/com.unity3d.player.UnityPlayerActivity}}\n"
        return ""


def test_everything_already_running(tmp_path):
    mumu, folder = FakeMuMu(), install(tmp_path)
    assert Emulator(folder, run=mumu).start() == ("127.0.0.1:16416", str(folder / "nx_main" / "adb.exe"), False)
    assert not any("launch" in c for c in mumu.calls)  # nothing started or opened


def test_starts_the_emulator_then_opens_the_game(tmp_path):
    mumu = FakeMuMu(started=False, boots_after=2, front=False)
    serial, _, launched = Emulator(install(tmp_path), run=mumu).start()
    assert serial == "127.0.0.1:16416" and launched
    assert "control -v 0 launch" in mumu.calls and f"control -v 0 app launch -pkg {PKG}" in mumu.calls


@pytest.mark.parametrize("mumu, key", [
    (FakeMuMu(started=False, boots_after=None), "err_mumu_boot"),   # never finishes booting
    (FakeMuMu(connects=False), "err_mumu_adb"),
    (FakeMuMu(installed=False), "err_game_missing"),
    (FakeMuMu(front=False, opens=False), "err_game_open"),
])
def test_each_failing_step_has_its_error(tmp_path, mumu, key):
    with pytest.raises(EmulatorError) as e:
        Emulator(install(tmp_path), run=mumu).start()
    assert e.value.key == key


@pytest.mark.parametrize("folder", ["", "C:/definitely/not/mumu"])
def test_bad_folder(folder):
    with pytest.raises(EmulatorError) as e:
        Emulator(folder, run=FakeMuMu())
    assert e.value.key == "err_mumu_folder" and e.value.values == {"folder": folder}


def test_stop_interrupts_the_boot_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EMULATOR_BOOT_TIMEOUT", 60)
    stop = threading.Event()
    stop.set()
    with pytest.raises(Stopped):
        Emulator(install(tmp_path), stop, run=FakeMuMu(started=False, boots_after=None)).start()


def test_registry_folders_on_this_machine_are_paths():
    assert all(hasattr(p, "parent") for p in emulator._registry_folders())


def test_shutdown_closes_the_player_and_waits(tmp_path):
    mumu = FakeMuMu()

    def run(args, timeout):
        if args[1:] == ["control", "-v", "0", "shutdown"]:
            mumu.started = False
        return mumu(args, timeout)
    Emulator(install(tmp_path), run=run).shutdown()
    assert "control -v 0 shutdown" in mumu.calls and not mumu.started


def test_shutdown_kills_a_player_that_ignores_it(tmp_path):
    """A frozen MuMu ignores "shutdown": its processes are killed, or start() would reconnect to it."""
    mumu = FakeMuMu()

    def run(args, timeout):
        if args[0] == "taskkill":
            mumu.calls.append(" ".join(args))
            mumu.started = False
            return ""
        out = mumu(args, timeout)
        if args[1:] == ["info", "-v", "0"] and mumu.started:
            out = json.dumps({**json.loads(out), "pid": 2168, "headless_pid": 12564})
        return out
    Emulator(install(tmp_path), run=run).shutdown()
    assert "taskkill /F /T /PID 2168" in mumu.calls and "taskkill /F /T /PID 12564" in mumu.calls
    assert not mumu.started


def test_shutdown_does_not_kill_a_player_that_closes(tmp_path):
    mumu = FakeMuMu()

    def run(args, timeout):
        if args[1:] == ["control", "-v", "0", "shutdown"]:
            mumu.started = False
        return mumu(args, timeout)
    Emulator(install(tmp_path), run=run).shutdown()
    assert not any(c.startswith("taskkill") for c in mumu.calls)
