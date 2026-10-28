"""OCR engine settings and template matching (coarse to fine)."""

from pathlib import Path

import cv2
import pytest
from omegaconf import OmegaConf
from rapidocr.inference_engine.onnxruntime.main import OrtInferSession

from roguebot import config, mode_screens, screens
from roguebot.vision import find, match_template
from conftest import fixture_image

FIXTURES = Path(__file__).parent / "fixtures"


def _full_search(img, template, threshold):
    """The plain full-size search match_template replaced (~0.3 s per frame)."""
    _, best, _, (x, y) = cv2.minMaxLoc(cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED))
    return (x + template.shape[1] // 2, y + template.shape[0] // 2) if best >= threshold else None


TEMPLATES = [(screens._CLOSE_X, config.CLOSE_X_MIN_SCORE), (screens._TUTORIAL_HAND, config.TUTORIAL_HAND_MIN_SCORE),
             (mode_screens._BACK_ARROW, config.BACK_ARROW_MIN_SCORE),
             (cv2.resize(screens._CLOSE_X, None, fx=0.6, fy=0.6), config.CLOSE_X_MIN_SCORE)]


# patrol_fast_used_up shows two ✕ (the coarse search alone once picked the other one)
@pytest.mark.parametrize("name", ["patrol_fast_used_up.png", "en_patrol_fast_used_up.png", "lobby_tutorial_hand.png",
                                  "en_arena.png", "energy_popup_no_videos.png", "level_board_ready.png"])
def test_coarse_to_fine_matching_finds_what_the_full_search_finds(name):
    img = fixture_image(FIXTURES / name)
    for template, threshold in TEMPLATES:
        assert match_template(img, template, threshold) == _full_search(img, template, threshold)


def test_ocr_sessions_do_not_spin():
    options = OrtInferSession._init_sess_opts(OmegaConf.create({"enable_cpu_mem_arena": False}))
    assert options.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    assert options.get_session_config_entry("session.inter_op.allow_spinning") == "0"


# The angle classifier (off now) turned these short texts upside down: "Modos" -> "sodo", "x1" -> "LX"
@pytest.mark.parametrize("name, text", [("lobby_normal.png", "Modos"), ("level_fortune_teller.png", "x1"),
                                        ("arena_opponents_millions.png", "3,3m"), ("guild_map_garbled.png", "Sala de")])
def test_ocr_reads_short_texts_the_right_way_up(ocr, name, text):
    assert find(ocr.read(fixture_image(FIXTURES / name)), text, exact=True)


def test_numpy_blas_uses_one_thread():
    """Set before numpy loads (roguebot/__init__.py): OpenBLAS reserved ~490 MB with 16 cores."""
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c", "import os; os.environ.pop('OPENBLAS_NUM_THREADS', None); import roguebot, "
                          "numpy; print(os.environ['OPENBLAS_NUM_THREADS'])"], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1"
