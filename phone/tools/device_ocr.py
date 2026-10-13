"""Record the app's OCR on a device for every fixture, for DeviceOcrTest (the device must read like the PC).

Needs a device (or MuMu Player) on adb with the debug app installed and its accessibility service on:
pushes tests/fixtures, runs the app's OcrFixturesReceiver and pulls device_ocr_raw.json into the test resources.
  python phone/tools/device_ocr.py [adb.exe] [serial]
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADB = sys.argv[1] if len(sys.argv) > 1 else r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe"
SERIAL = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1:16384"
FILES = "/sdcard/Android/data/com.diego.roguebot_phone/files"
OUT = ROOT / "phone" / "android" / "bot" / "src" / "test" / "resources" / "device_ocr.json"


def adb(*args, check=True):
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, check=check).stdout


adb("shell", "mkdir", "-p", f"{FILES}/fixtures")
adb("push", f"{ROOT / 'tests' / 'fixtures'}/.", f"{FILES}/fixtures/")
adb("shell", "rm", "-f", f"{FILES}/device_ocr_raw.json")
adb("shell", "am", "broadcast", "-a", "com.diego.roguebot_phone.OCR_FIXTURES", "-n",
    "com.diego.roguebot_phone/.OcrFixturesReceiver")
for _ in range(300):
    if "device_ocr_raw.json" in adb("shell", "ls", FILES, check=False):
        break
    time.sleep(2)
adb("pull", f"{FILES}/device_ocr_raw.json", str(OUT))
print("->", OUT)
