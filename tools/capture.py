"""Dev helper: save a screenshot (and optionally dump its OCR) to captures/.

    python -m tools.capture NAME [--ocr]
"""

import argparse
from pathlib import Path

import cv2

from roguebot.device import Device
from roguebot.vision import Ocr

OUT = Path("captures")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--ocr", action="store_true", help="print recognized text with boxes")
    args = parser.parse_args()

    img = Device().screenshot()
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{args.name}.png"
    cv2.imwrite(str(path), img)
    print(f"saved {path}")
    if args.ocr:
        for t in Ocr().read(img):
            print(f"({t.x1:4d},{t.y1:4d})-({t.x2:4d},{t.y2:4d})  {t.text}")


if __name__ == "__main__":
    main()
