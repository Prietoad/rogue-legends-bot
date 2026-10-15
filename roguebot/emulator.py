"""MuMu Player: find the installation, start the emulator and open Rogue Legend.

Only MuMu's own tools are used: MuMuManager.exe (start the player, open an app, read its state)
and its adb.exe. Every failing step raises EmulatorError with an i18n key for the UI.
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from roguebot import config

log = logging.getLogger(__name__)

TOOL_DIRS = ("nx_main", "shell")  # MuMu Player 12 layouts (current, older)
INSTALL_GUESSES = (r"Netease\MuMuPlayer", r"Netease\MuMuPlayer-12.0", r"Netease\MuMu Player 12", "MuMuPlayer")


PERMANENT_ERRORS = ("err_mumu_folder", "err_game_missing", "err_game_update")  # restarting cannot fix these


class EmulatorError(Exception):
    """A start step failed. `key` is an i18n key (roguebot.i18n), `values` fill its {placeholders}."""

    def __init__(self, key: str, **args):
        super().__init__(f"{key} {args}" if args else key)
        self.key, self.values = key, args


def tools(folder: str | Path) -> tuple[Path, Path] | None:
    """(MuMuManager.exe, adb.exe) inside a MuMu installation folder, or None if it is not one."""
    for sub in TOOL_DIRS:
        manager, adb = Path(folder) / sub / "MuMuManager.exe", Path(folder) / sub / "adb.exe"
        if manager.is_file() and adb.is_file():
            return manager, adb
    return None


def _registry_folders() -> list[Path]:
    """Install folders of programs named MuMu in the Windows uninstall registry."""
    try:
        import winreg
    except ImportError:  # not Windows
        return []
    folders = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                key = winreg.OpenKey(root, winreg.EnumKey(root, i))
                name = winreg.QueryValueEx(key, "DisplayName")[0]
            except OSError:
                continue
            if "mumu" not in str(name).lower():
                continue
            for value in ("InstallLocation", "UninstallString"):  # MuMu leaves InstallLocation empty
                try:
                    raw = str(winreg.QueryValueEx(key, value)[0]).strip().strip('"')
                except OSError:
                    continue
                if raw:
                    folders.append(Path(raw) if value == "InstallLocation" else Path(raw).parent)
    return folders


def find_install() -> Path | None:
    """Auto-detect the MuMu Player folder: the registry first, then the usual install places."""
    guesses = [Path(os.environ.get(var, "")) / g for var in ("ProgramFiles", "ProgramFiles(x86)") for g in INSTALL_GUESSES]
    guesses += [Path(f"{drive}:\\") / g for drive in "CDE" for g in INSTALL_GUESSES]
    for folder in _registry_folders() + guesses:
        if tools(folder):
            return folder
    return None


def _run(args: list[str], timeout: float) -> str:
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout).stdout.decode("utf-8", "ignore")
    except (OSError, subprocess.TimeoutExpired):
        return ""


class Emulator:
    """Start sequence on MuMu instance 0 (the default one). `run(args, timeout) -> stdout` and
    `stop` are injectable for tests; waits end early (raising device.Stopped) once `stop` is set."""

    def __init__(self, folder: str | Path, stop: threading.Event | None = None,
                 run: Callable[[list[str], float], str] = _run):
        found = tools(folder) if str(folder).strip() else None
        if not found:
            raise EmulatorError("err_mumu_folder", folder=str(folder))
        self.manager, self.adb = (str(p) for p in found)
        self.stop = stop
        self.run = run

    def start(self, package: str = config.PACKAGE) -> tuple[str, str, bool]:
        """Emulator on, game installed and in front. Returns (serial, adb path, game_was_launched)."""
        info = self._info()
        if not info.get("is_android_started"):
            log.info("Starting MuMu Player")
            self.run([self.manager, "control", "-v", "0", "launch"], 60)
            info = self._wait(lambda: (i := self._info()).get("is_android_started") and
                              i.get("player_state") == "start_finished" and i, config.EMULATOR_BOOT_TIMEOUT)
            if not info:
                raise EmulatorError("err_mumu_boot", seconds=config.EMULATOR_BOOT_TIMEOUT)
        serial = f"{info.get('adb_host_ip') or '127.0.0.1'}:{info.get('adb_port') or config.SERIAL.split(':')[1]}"
        if "connected" not in self.run([self.adb, "connect", serial], 30) or not self._wait(
                lambda: self._adb(serial, "getprop", "sys.boot_completed").strip() == "1", config.EMULATOR_BOOT_TIMEOUT):
            raise EmulatorError("err_mumu_adb", serial=serial)
        if f"package:{package}" not in self._adb(serial, "pm", "list", "packages", package):
            raise EmulatorError("err_game_missing")
        if self._in_front(serial, package):
            return serial, self.adb, False
        log.info("Opening Rogue Legend")
        self.run([self.manager, "control", "-v", "0", "app", "launch", "-pkg", package], 60)
        if not self._wait(lambda: self._in_front(serial, package), config.GAME_OPEN_TIMEOUT):
            raise EmulatorError("err_game_open")
        return serial, self.adb, True

    def shutdown(self) -> None:
        """Close the emulator (recovery from a frozen emulator or game); start() boots it again. A frozen
        player can ignore "shutdown": then its processes are killed, or start() would reconnect to it."""
        log.info("Closing MuMu Player")
        info = self._info()
        self.run([self.manager, "control", "-v", "0", "shutdown"], 60)
        if self._wait(lambda: not self._info().get("is_android_started"), config.EMULATOR_SHUTDOWN_TIMEOUT):
            return
        pids = [str(info[k]) for k in ("pid", "headless_pid") if info.get(k)]
        log.warning("MuMu Player did not close, killing it (pids %s)", ", ".join(pids) or "unknown")
        for pid in pids:
            self.run(["taskkill", "/F", "/T", "/PID", pid], 30)
        if not self._wait(lambda: not self._info().get("is_android_started"), config.EMULATOR_SHUTDOWN_TIMEOUT):
            log.error("MuMu Player is still running after the kill")

    def _info(self) -> dict:
        try:
            return json.loads(self.run([self.manager, "info", "-v", "0"], 30) or "{}")
        except json.JSONDecodeError:
            return {}

    def _adb(self, serial: str, *args: str) -> str:
        return self.run([self.adb, "-s", serial, "shell", *args], 30)

    def _in_front(self, serial: str, package: str) -> bool:
        return package in self._adb(serial, "dumpsys", "window").split("mCurrentFocus", 1)[-1][:300]

    def _wait(self, check: Callable, timeout: float):
        """Poll check() until it returns something truthy (returned) or timeout (None)."""
        from roguebot.device import Stopped
        deadline = time.monotonic() + timeout
        while True:
            result = check()
            if result or time.monotonic() > deadline:
                return result or None
            if self.stop is not None and self.stop.wait(config.EMULATOR_POLL):
                raise Stopped("Stopped by the user")
            if self.stop is None:
                time.sleep(config.EMULATOR_POLL)
