"""OCR on screenshots and helpers to query the recognized text."""

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import cached_property

import cv2
import numpy as np
from rapidocr import RapidOCR
from rapidocr.inference_engine.onnxruntime.main import OrtInferSession

from roguebot import config

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
    """Center of the best match of template in img, or None if its score is below threshold.
    Coarse to fine: the best MATCH_PEAKS spots of a search at 1/MATCH_SHRINK size are scored again at full
    size around them (a full-size search of a whole frame took ~0.3 s; this ~0.02 s, same results on every
    fixture). Several peaks, because a frame can show two ✕ and the coarse search may rank them the other way."""
    f = config.MATCH_SHRINK
    small = cv2.matchTemplate(cv2.resize(img, None, fx=1 / f, fy=1 / f, interpolation=cv2.INTER_AREA),
                              cv2.resize(template, None, fx=1 / f, fy=1 / f, interpolation=cv2.INTER_AREA),
                              cv2.TM_CCOEFF_NORMED)
    h, w = template.shape[:2]
    best, center = -1.0, None
    for _ in range(config.MATCH_PEAKS):
        _, _, _, (sx, sy) = cv2.minMaxLoc(small)
        small[max(0, sy - h // f // 2):sy + h // f // 2 + 1, max(0, sx - w // f // 2):sx + w // f // 2 + 1] = -1
        x0, y0 = max(0, (sx - 1) * f), max(0, (sy - 1) * f)
        scores = cv2.matchTemplate(img[y0:(sy + 1) * f + h, x0:(sx + 1) * f + w], template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score > best:
            best, center = score, (x0 + x + w // 2, y0 + y + h // 2)
    return center if best >= threshold else None


def _without_spinning(build_options):
    """onnxruntime's worker threads spin (busy-wait) between operators and for a while after each run: with
    every core that was ~3.7 s of CPU per 0.47 s OCR plus ~0.2 s while the bot waits. Without it, half the CPU
    and no slower. rapidocr has no option for it, so its session options get the setting here."""
    def build(cfg):
        options = build_options(cfg)
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        return options
    return staticmethod(build)


OrtInferSession._init_sess_opts = _without_spinning(OrtInferSession._init_sess_opts)


class Ocr:
    def __init__(self, threads: int = config.OCR_THREADS):  # tests in parallel share the cores
        # No angle classifier: the game's text is never upside down, and it turned short texts around
        # ("x1" -> "LX", "Modos" -> "sodo", "3,3m" -> "'mε").
        self._engine = RapidOCR(params={"Global.log_level": "error", "Global.use_cls": False,
                                        "EngineConfig.onnxruntime.intra_op_num_threads": threads})

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
