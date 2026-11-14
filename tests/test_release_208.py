"""Public startup regressions using an existing public lobby and account-free popup."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from conftest import fixture_image
from roguebot import labels, luxury_pass, navigation, screens
from roguebot.vision import Text

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def lobby(ocr):
    # Reuse an already-public lobby fixture. The exact account capture stays private.
    img = fixture_image(ROOT / 'tests/fixtures/en_lobby_normal.png')
    return img, ocr.read(img)


@pytest.fixture(scope='module')
def popup(ocr):
    img = fixture_image(ROOT / 'tests/fixtures/luxury_pass_season25.png')
    return img, ocr.read(img)


@pytest.fixture(autouse=True)
def language():
    labels.set_language(None)
    yield
    labels.set_language(None)


def test_actual_lobby_ocr_is_not_a_luxury_pass(lobby):
    img, texts = lobby
    assert not luxury_pass.is_luxury_pass(img, texts)
    assert luxury_pass.dismissal_tap(img, texts) is None
    assert screens.parse_lobby(texts) is not None
    # The template fallback must also reject this lobby with unreadable OCR.
    assert not luxury_pass.is_luxury_pass(img, [])


@pytest.mark.parametrize('entry', ['go_to_lobby', 'detect_language'])
def test_startup_uses_real_lobby_recognition_without_input(lobby, entry, monkeypatch, tmp_path):
    img, texts = lobby
    actions = []

    def capture():
        actions.append('screenshot')
        return img.copy()

    def forbidden(*args):
        pytest.fail(f'startup issued speculative input: {args}')

    device = SimpleNamespace(screenshot=capture, tap=forbidden, back=forbidden)
    # Replay only OCR derived from these exact pixels; recognition is real.
    nav = navigation.Navigator(device, SimpleNamespace(read=lambda frame: list(texts)))
    monkeypatch.setattr(navigation, 'DEBUG_DIR', tmp_path / 'debug')
    result = getattr(nav, entry)()
    if entry == 'detect_language':
        assert result == 'en'
        assert actions == ['screenshot', 'screenshot']
    else:
        assert result == screens.parse_lobby(texts)
        assert actions == ['screenshot']
    assert not (tmp_path / 'debug').exists()


@pytest.mark.parametrize('values', [
    ['Season 25'], ['Season 26'], ['Season 100'], ['NEW SEASON'],
    ['New seasonal rewards'], ['$29.99'], ['Luxury rewards'],
    ['NEW SEASON', 'Season 25', '$29.99'],
])
def test_shared_banner_and_price_text_never_establish_presence(lobby, values):
    img, _ = lobby
    texts = [Text(value, 500, 160 + i*100, 950, 240 + i*100)
             for i, value in enumerate(values)]
    assert not luxury_pass.is_luxury_pass(img, texts)
    assert luxury_pass.dismissal_tap(img, texts) is None


def test_genuine_popup_keeps_priority_and_exact_dismissal(popup, monkeypatch):
    img, texts = popup
    assert luxury_pass.is_luxury_pass(img, texts)
    assert luxury_pass.dismissal_tap(img, texts) == luxury_pass.OUTSIDE_TAP
    monkeypatch.setattr(screens, 'level_tap', lambda *a: pytest.fail('generic event consulted'))
    state = screens.classify_level_screen(img, texts)
    assert state.kind is screens.LevelScreen.LUXURY_PASS
    assert state.tap == luxury_pass.OUTSIDE_TAP


def test_unreadable_popup_title_artwork_blocks_changed_body(popup):
    img, _ = popup
    changed = img.copy()
    changed[1300:2250, 150:1250] = 0
    assert luxury_pass.is_luxury_pass(changed, [])
    assert luxury_pass.dismissal_tap(changed, []) is None


def test_shared_popup_season_artwork_is_not_modal_evidence(lobby, popup):
    img, _ = lobby
    offer, _ = popup
    banner_only = img.copy()
    banner_only[1220:1320, 500:940] = offer[1220:1320, 500:940]
    assert not luxury_pass.is_luxury_pass(banner_only, [])
    assert luxury_pass.dismissal_tap(banner_only, []) is None


def test_changed_popup_title_still_blocks_without_dismissal():
    img = np.zeros((2560, 1440, 3), dtype=np.uint8)
    texts = [Text('Luxury Pass - Season 26', 400, 100, 1000, 240)]
    assert luxury_pass.is_luxury_pass(img, texts)
    assert luxury_pass.dismissal_tap(img, texts) is None
