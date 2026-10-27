"""Shared test setup: one OCR for the whole session, cached by image content.

OCR is ~0.5-1 s per screenshot and the same fixtures are read by many tests, so it was most of the
suite's time. The cache key is the image's pixels + the crop region + the OCR engine (rapidocr and
onnxruntime versions, roguebot/vision.py source): a changed fixture, engine or wrapper is read again.
Results also persist in .pytest_cache/ocr (git-ignored), so later runs skip OCR; `pytest --cache-clear`
empties it."""

import functools
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

import cv2
import numpy as np
import pytest

from roguebot import vision
from roguebot.vision import Ocr, Text

_ENGINE = hashlib.sha1("|".join((version("rapidocr"), version("onnxruntime"),
                                 Path(vision.__file__).read_text(encoding="utf-8"))).encode()).hexdigest()


class CachedOcr(Ocr):
    def __init__(self, cache_dir: Path):
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, list[Text]] = {}
        self._real: Ocr | None = None  # the model loads only on a cache miss

    def read(self, img: np.ndarray, region: tuple[int, int, int, int] | None = None) -> list[Text]:
        h = hashlib.sha1(_ENGINE.encode())
        h.update(str((img.shape, img.dtype.str, region)).encode())
        h.update(np.ascontiguousarray(img).data)
        key = h.hexdigest()
        if key in self._memory:
            return list(self._memory[key])
        path = self._dir / f"{key}.json"
        try:
            texts = [Text(*t) for t in json.loads(path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            if self._real is None:  # parallel workers (pytest -n) each get a share of the cores, or they fight over them
                workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
                self._real = Ocr(max(1, (os.cpu_count() or 1) // workers) if workers > 1 else -1)
            texts = self._real.read(img, region)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")  # parallel workers (pytest -n) never read half a file
            tmp.write_text(json.dumps([[t.text, t.x1, t.y1, t.x2, t.y2] for t in texts]), encoding="utf-8")
            os.replace(tmp, path)
        self._memory[key] = texts
        return list(texts)


@functools.cache
def _decoded(path: str) -> np.ndarray:
    return cv2.imread(path)


def fixture_image(path: Path) -> np.ndarray:
    """A fixture screenshot, decoded once per session (PNG decoding was a large part of the suite's
    time); every call gets its own copy, so a test that edits it can't affect another."""
    return _decoded(str(path)).copy()


@pytest.fixture(scope="session")
def ocr(request) -> Ocr:
    return CachedOcr(request.config.cache.mkdir("ocr"))
