"""OCR on screenshots and helpers to query the recognized text."""

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property

import cv2
import numpy as np
from rapidocr import RapidOCR

log = logging.getLogger(__name__)

_LEVEL_RE = re.compile(r"^\s*(\d+)\s*\.")


@dataclass(frozen=True)
class Text:
    text: str
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2

    @cached_property
    def norm(self) -> str:  # cached: matched against dozens of labels per frame
        return normalize(self.text)


def normalize(s: str) -> str:
    """Lowercase without accents, so 'Desafío' == 'desafio'."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def parse_level_number(s: str) -> int | None:
    """'12. Arenas Movedizas II' -> 12."""
    m = _LEVEL_RE.match(s)
    return int(m.group(1)) if m else None


def matches(t: Text, label, exact: bool = False) -> bool:
    """True if the text matches a plain string or a labels.Label (any variant of the active language)."""
    variants = (normalize(label),) if isinstance(label, str) else label.variants  # Label variants are normalized
    return any((t.norm == v) if exact else (v in t.norm) for v in variants)


def find(texts: list[Text], label, exact: bool = False) -> Text | None:
    return next((t for t in texts if matches(t, label, exact)), None)


def match_template(img: np.ndarray, template: np.ndarray, threshold: float) -> tuple[int, int] | None:
    """Center of the best match of template in img, or None if its score is below threshold."""
    scores = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
    _, best, _, (x, y) = cv2.minMaxLoc(scores)
    if best < threshold:
        return None
    h, w = template.shape[:2]
    return x + w // 2, y + h // 2


class Ocr:
    def __init__(self, threads: int = -1):  # -1: onnxruntime's default (every core); tests in parallel share them
        self._engine = RapidOCR(params={"Global.log_level": "error", "EngineConfig.onnxruntime.intra_op_num_threads": threads})

    def read(self, img: np.ndarray, region: tuple[int, int, int, int] | None = None) -> list[Text]:
        """OCR the image, or only region=(x1, y1, x2, y2). Coordinates are always full-frame."""
        ox, oy = 0, 0
        if region:
            x1, y1, x2, y2 = region
            img, ox, oy = img[y1:y2, x1:x2], x1, y1
        result = self._engine(img)
        if result.boxes is None:
            return []
        texts = []
        for box, txt in zip(result.boxes, result.txts):
            xs, ys = box[:, 0], box[:, 1]
            texts.append(Text(txt, int(xs.min()) + ox, int(ys.min()) + oy,
                              int(xs.max()) + ox, int(ys.max()) + oy))
        return texts
