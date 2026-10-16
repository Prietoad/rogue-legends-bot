"""Thin wrapper over ADB: screenshots and input. No game knowledge lives here.

The rest of the code works in reference coordinates (config.SCREEN_SIZE, 1440x2560).
Any portrait 9:16 device works: screenshots are resized to the reference size and
taps/swipes are scaled back to device pixels.
"""

import logging
import re
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


class Frozen(DeviceError):
    """No input and the same frame for FREEZE_TIMEOUT: the emulator or the game froze (recovery restarts MuMu)."""


class Stopped(Exception):
    """The user pressed Stop: raised by the next screenshot/tap/swipe."""


def device_scale(width: int, height: int) -> float:
    """Factor from reference to device pixels. Raises DeviceError for other aspect ratios."""
    ref_w, ref_h = config.SCREEN_SIZE
    if abs(width * ref_h - height * ref_w) > config.ASPECT_TOLERANCE * ref_w * height:
        raise DeviceError(f"Screen is {width}x{height}; set the emulator to a portrait 9:16 "
                          f"resolution (e.g. 1080x1920 or 1440x2560)")
    return width / ref_w


def frame_changed(a: np.ndarray, b: np.ndarray) -> bool:
    """Two small grey frames differ (animation, new screen); a frozen emulator repeats the same one."""
    return float(cv2.absdiff(a, b).mean()) > config.FREEZE_MIN_DIFF


def focused_package(dumpsys_window: str) -> str:
    """Package of the focused window in `dumpsys window`; between windows (focus null) the focused app's."""
    m = (re.search(r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+)", dumpsys_window)
         or re.search(r"mFocusedApp=ActivityRecord\{\S+ \S+ ([\w.]+)", dumpsys_window))
    return m.group(1) if m else ""


def overlay_packages(dumpsys_windows: str) -> list[str]:
    """Packages drawing a visible overlay window over everything (`dumpsys window windows`), e.g. MuMu's
    store ad "Claim Your Free SSR Goddess" (com.mumu.store): the game keeps the focus, but the overlay
    covers the screen and takes every tap. System UI and the game itself are never listed."""
    found = []
    for block in re.split(r"\n\s*Window #\d+ ", dumpsys_windows):
        package = re.search(r"package=([\w.]+)", block)
        if (package and "ty=APPLICATION_OVERLAY" in block and "mViewVisibility=0x0" in block
                and "mHasSurface=true" in block and package.group(1) not in config.OVERLAY_KEEP
                and package.group(1) not in found):
            found.append(package.group(1))
    return found


class Device:
    def __init__(self, serial: str = config.SERIAL, stop: threading.Event | None = None, adb: str = config.ADB_PATH):
        self._stop = stop
        # MuMu's own adb starts the server (if needed) and connects to the instance.
        subprocess.run([adb, "connect", serial], capture_output=True, check=True, timeout=config.ADB_TIMEOUT)
        self._d = adbutils.AdbClient().device(serial)

        size = self._d.window_size(landscape=False)
        self._scale = device_scale(size.width, size.height)
        log.info("Device %dx%d (scale %.3f)", size.width, size.height, self._scale)
        self._thumb = None                      # last frame, small (freeze watchdog)
        self._active = time.monotonic()         # last input, intentional wait or screen change
        self._overlay_check = 0.0               # last overlay ad check

    def _touch(self) -> None:
        self._active = time.monotonic()

    def _check_stop(self) -> None:
        if self._stop is not None and self._stop.is_set():
            raise Stopped("Stopped by the user")

    def wait(self, seconds: float) -> None:
        """Sleep, but raise Stopped as soon as the stop Event is set."""
        if self._stop is None:
            time.sleep(seconds)
        elif self._stop.wait(seconds):
            raise Stopped("Stopped by the user")
        self._touch()  # an intentional idle (waiting for energy) is not a freeze

    def _px(self, x: int, y: int) -> tuple[int, int]:
        return round(x * self._scale), round(y * self._scale)

    def foreground_package(self) -> str:
        """Package of the focused window ("" if none). With a timeout: app_current() hangs on a frozen emulator."""
        out = self._d.shell(["dumpsys", "window"], timeout=config.ADB_TIMEOUT)
        return focused_package(out)

    def close_overlays(self) -> bool:
        """Close ads another app draws over the game (they ignore Back and open a store when tapped):
        force-stop that app. True if one was closed."""
        self._overlay_check = time.monotonic()
        out = self._d.shell(["dumpsys", "window", "windows"], timeout=config.ADB_TIMEOUT)
        packages = overlay_packages(out)
        for package in packages:
            log.info("Closing an overlay ad from %s", package)
            self._d.shell(["am", "force-stop", package], timeout=config.ADB_TIMEOUT)
        if packages:
            self._touch()
            time.sleep(config.UI_SETTLE)
        return bool(packages)

    def screenshot(self) -> np.ndarray:
        """Full frame as BGR, resized to the reference resolution."""
        self._check_stop()
        png = self._d.shell("screencap -p", encoding=None, timeout=config.ADB_TIMEOUT)
        if not png:
            raise DeviceError("Empty screenshot (the emulator is not responding)")
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if time.monotonic() - self._overlay_check > config.OVERLAY_CHECK_INTERVAL and self.close_overlays():
            return self.screenshot()  # the frame showed the ad
        if self._scale != 1:
            img = cv2.resize(img, config.SCREEN_SIZE, interpolation=cv2.INTER_CUBIC)
        self._watch(img)
        return img

    def _watch(self, img: np.ndarray) -> None:
        """Freeze watchdog: a frozen emulator still answers screenshots, with the same frame forever, and
        some waits (auto-play, fights) send no input. No input and no screen change for FREEZE_TIMEOUT
        raises Frozen."""
        thumb = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), config.FREEZE_THUMB, interpolation=cv2.INTER_AREA)
        if self._thumb is None or frame_changed(self._thumb, thumb):
            self._touch()
        self._thumb = thumb
        idle = time.monotonic() - self._active
        if idle > config.FREEZE_TIMEOUT:
            raise Frozen(f"The screen has not changed for {idle:.0f} s with no input (emulator or game frozen)")

    def tap(self, x: int, y: int, settle: float = config.UI_SETTLE) -> None:
        self._check_stop()
        log.debug("tap (%d, %d)", x, y)
        self._d.shell(["input", "tap", *map(str, self._px(x, y))], timeout=config.ADB_TIMEOUT)
        self._touch()
        time.sleep(settle)

    def back(self, settle: float = config.UI_SETTLE) -> None:
        """Android Back key (leaves the browser the game opens for its web store)."""
        self._check_stop()
        self._d.shell(["input", "keyevent", "4"], timeout=config.ADB_TIMEOUT)
        self._touch()
        time.sleep(settle)

    def launch(self, package: str, settle: float = config.VIDEO_SETTLE) -> None:
        """Bring an app to the front (starts it if it is not running)."""
        self._check_stop()
        self._d.shell(["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], timeout=config.ADB_TIMEOUT)
        self._touch()
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
        self._touch()
        time.sleep(settle)
