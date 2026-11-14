"""Fail-closed recognition for the verified Season 25 popup layout.

The template is a 1/10 area-resized copy of the verified static offer fixture.
Only the timer changes; prices, offer geometry and the clear outside area must match.
"""
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from roguebot.vision import Text

OUTSIDE_TAP = (720, 2453)
_ANCHORS = {
    'luxury pass': (471, 158, 966, 272),
    'new season': (551, 313, 885, 365),
    'season 25': (509, 1220, 928, 1316),
    '$29.99': (576, 2032, 860, 2141),
}


@cache
def _template():
    return cv2.imread(str(Path(__file__).parent / 'templates' / 'luxury_pass_25.png'))


def _difference(img):
    if img is None or getattr(img, 'shape', None) != (2560, 1440, 3):
        return None
    reference = _template()
    if reference is None:
        return None
    small = cv2.resize(img, (144, 256), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(small, reference)
    diff[111:119, 65:85] = 0  # countdown only; never the season, price or outside region
    return diff


def is_luxury_pass(img, texts: list[Text]) -> bool:
    """Block on the modal's title, never shared season/banner or price text.

    An unreadable or changed offer body can still be identified by its captured
    title artwork. Presence alone never authorizes dismissal.
    """
    if any('luxury pass' in t.norm for t in texts):
        return True
    diff = _difference(img)
    return diff is not None and (float(diff.mean()) < 5
                                 or float(diff[14:30, 18:126].mean()) < 3)


def dismissal_tap(img, texts: list[Text]) -> tuple[int, int] | None:
    diff = _difference(img)
    if diff is None:
        return None
    for anchor, bounds in _ANCHORS.items():
        hits = [t for t in texts if t.norm == anchor]
        if len(hits) != 1:
            return None
        t = hits[0]
        if any(abs(actual - expected) > 20
               for actual, expected in zip((t.x1, t.y1, t.x2, t.y2), bounds)):
            return None
    prices = [t for t in texts if any(c in t.text for c in '$€£¥')]
    if len(prices) != 1 or prices[0].norm != '$29.99':
        return None
    # Match the captured offer and its entire outside area. A new panel/button, a
    # shifted price, a missing border, or an obstruction below the panel fails closed.
    if float(diff.mean()) > 3 or float(np.quantile(diff, .99)) > 18 or int(diff.max()) > 30:
        return None
    outside = diff[226:, :]
    if float(outside.mean()) > 1 or float(outside.max()) > 18:
        return None
    if any(t.y2 >= 2260 for t in texts):
        return None
    return OUTSIDE_TAP


class LuxuryPassBlocked(Exception):
    """Stop automation without lobby recovery, speculative Back, or emulator restart."""
