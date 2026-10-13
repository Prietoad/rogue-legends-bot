"""Thin wrapper over ADB: screenshots and input. No game knowledge lives here.

The rest of the code works in reference coordinates (config.SCREEN_SIZE, 1440x2560).
Any portrait 9:16 device works: screenshots are resized to the reference size and
taps/swipes are scaled back to device pixels.
"""

import logging
import subprocess
import threading
import time

import adbutils
import cv2
import numpy as np

from roguebot import config

log = logging.getLogger(__name__)


class DeviceError(Exception):
    pass


class Stopped(Exception):
    """The user pressed Stop: raised by the next screenshot/tap/swipe."""


def device_scale(width: int, height: int) -> float:
    """Factor from reference to device pixels. Raises DeviceError for other aspect ratios."""
    ref_w, ref_h = config.SCREEN_SIZE
    if abs(width * ref_h - height * ref_w) > config.ASPECT_TOLERANCE * ref_w * height:
        raise DeviceError(f"Screen is {width}x{height}; set the emulator to a portrait 9:16 "
                          f"resolution (e.g. 1080x1920 or 1440x2560)")
    return width / ref_w


class Device:
    def __init__(self, serial: str = config.SERIAL, stop: threading.Event | None = None, adb: str = config.ADB_PATH):
        self._stop = stop
        # MuMu's own adb starts the server (if needed) and connects to the instance.
        subprocess.run([adb, "connect", serial], capture_output=True, check=True)
        self._d = adbutils.AdbClient().device(serial)

        size = self._d.window_size(landscape=False)
        self._scale = device_scale(size.width, size.height)
        log.info("Device %dx%d (scale %.3f)", size.width, size.height, self._scale)

    def _check_stop(self) -> None:
        if self._stop is not None and self._stop.is_set():
            raise Stopped("Stopped by the user")

    def wait(self, seconds: float) -> None:
        """Sleep, but raise Stopped as soon as the stop Event is set."""
        if self._stop is None:
            time.sleep(seconds)
        elif self._stop.wait(seconds):
            raise Stopped("Stopped by the user")

    def _px(self, x: int, y: int) -> tuple[int, int]:
        return round(x * self._scale), round(y * self._scale)

    def foreground_package(self) -> str:
        return self._d.app_current().package

    def screenshot(self) -> np.ndarray:
        """Full frame as BGR, resized to the reference resolution."""
        self._check_stop()
        png = self._d.shell("screencap -p", encoding=None, timeout=config.ADB_TIMEOUT)
        if not png:
            raise DeviceError("Empty screenshot (the emulator is not responding)")
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if self._scale != 1:
            img = cv2.resize(img, config.SCREEN_SIZE, interpolation=cv2.INTER_CUBIC)
        return img

    def tap(self, x: int, y: int, settle: float = config.UI_SETTLE) -> None:
        self._check_stop()
        log.debug("tap (%d, %d)", x, y)
        self._d.shell(["input", "tap", *map(str, self._px(x, y))], timeout=config.ADB_TIMEOUT)
        time.sleep(settle)

    def back(self, settle: float = config.UI_SETTLE) -> None:
        """Android Back key (leaves the browser the game opens for its web store)."""
        self._check_stop()
        self._d.shell(["input", "keyevent", "4"], timeout=config.ADB_TIMEOUT)
        time.sleep(settle)

    def hold(self, x: int, y: int, seconds: float, settle: float = config.UI_SETTLE) -> None:
        """Long press: a swipe that does not move."""
        self.swipe((x, y), (x, y), duration=seconds, settle=settle)

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration: float = 0.6,
              settle: float = config.SCROLL_SETTLE) -> None:
        self._check_stop()
        log.debug("swipe %s -> %s", start, end)
        self._d.shell(["input", "swipe", *map(str, (*self._px(*start), *self._px(*end), int(duration * 1000)))],
                      timeout=config.ADB_TIMEOUT + duration)
        time.sleep(settle)
