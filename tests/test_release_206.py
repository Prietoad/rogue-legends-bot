"""2.0.6 statue/combat and abandoned-level regressions; no emulator required."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from roguebot import labels, navigation, play, screens, world2
from roguebot.build import PRESETS
from roguebot.navigation import Navigator
from roguebot.screens import LevelScreen, LevelState, classify_level_screen
from roguebot.vision import Text
from conftest import fixture_image

FIXTURES = Path(__file__).resolve().parents[1] / 'specs' / '2.0.6'
STATUES = [
    'watchdog_back_20261112_083747.png',
    'watchdog_stop_20261112_084117.png',
    'fail_20261112_084208.png',
    'fail_20261112_085956.png',
]


def t(text, x=720, y=500):
    return Text(text, x - 70, y - 20, x + 70, y + 20)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    labels.set_language('en')
    monkeypatch.setattr(play, '_level_abandoned', False)
    monkeypatch.setattr(world2, 'LAST', None)
    yield
    labels.set_language(None)


@pytest.fixture(params=STATUES)
def statue(request, ocr):
    if not (FIXTURES / request.param).exists():
        pytest.skip('Private account-run fixture is intentionally not distributed')
    img = fixture_image(FIXTURES / request.param)
    return img, ocr.read(img)


def test_statue_offers_enhanced_combo_instead_of_waiting_for_a_fight(statue, caplog):
    img, texts = statue
    assert world2.match_event(texts) == 'statue'
    assert not world2.is_battle(texts)
    assert world2.known_screen(texts) != 'battle'
    with caplog.at_level('INFO'):
        state = classify_level_screen(img, texts, build=PRESETS['poison'])
    assert state.kind is LevelScreen.EVENT
    decision = world2.LAST
    assert decision.event == 'statue' and decision.choice == 'offering'
    assert decision.inputs == {'skill': 'enhanced combo', 'core': False}
    assert world2.decide_statue('Enhanced Combo', PRESETS['poison']).choice == 'offering'
    offering = next(t for t in texts if t.norm == 'offering')  # title wraps as Make an / Offering
    pray = next(t for t in texts if t.norm == 'pray')
    assert state.tap == world2.choice_tap(offering, texts)
    assert state.tap != world2.choice_tap(pray, texts)
    assert 'W2 statue: choice offering' in caplog.text


@pytest.mark.parametrize('name', ['Enhanced Combo', 'Combo Mastery', 'Combo Rate Up', 'Combo Bolt',
                                 'Forget Enhanced Combo', 'Combo! Damage +20%'])
def test_combo_skill_names_are_not_combat_banners(name):
    assert not world2.is_battle([t(name)])


@pytest.mark.parametrize('banner', ['COMBO!', 'Combo', '¡COMBO!', 'Rourdombo!'])
def test_actual_combo_banners_still_wait_for_combat(banner):
    assert world2.is_battle([t(banner)])


def test_visible_statue_takes_precedence_over_generic_combat(monkeypatch, statue):
    img, texts = statue
    # Defensive precedence also covers a future battle-detector regression.
    monkeypatch.setattr(screens, 'is_battle', lambda _: True)
    assert classify_level_screen(img, texts, build=PRESETS['poison']).kind is LevelScreen.EVENT
    assert not world2.is_battle(texts + [t('Round 1/30'), t('COMBO!')])


def fake_device():
    actions = []
    return SimpleNamespace(tap=lambda *p: actions.append(p), back=lambda: actions.append('back')), actions


def test_watchdog_can_pray_and_stopped_statue_is_never_resumed(monkeypatch, statue, caplog):
    img, texts = statue
    device, actions = fake_device()
    p = play.Player.__new__(play.Player)
    p.device = device
    monkeypatch.setattr(p, '_watchdog_shot', lambda *_: None)
    monkeypatch.setattr(play, 'back_arrow', lambda _: None)
    monkeypatch.setattr(play, 'close_button', lambda _: None)
    pray = next(t for t in texts if t.norm == 'pray')
    safe = world2.choice_tap(pray, texts)
    assert world2.safe_exit_point(texts) == safe
    assert not p._watchdog(img, texts, 'back')
    assert not p._watchdog(img, texts, 'exit')
    assert actions == [safe, safe]
    assert 'no back arrow or safe exit' not in caplog.text

    nav = Navigator(device, None)
    nav._capture = lambda: (img, texts)
    nav.resume_level = lambda: pytest.fail('abandoned statue resumed')
    assert nav.level_in_progress()
    assert p._watchdog(img, texts, 'stop')
    assert play.level_abandoned()
    assert not nav.level_in_progress()  # make_runner's next attempt cannot play it out

    lobby = SimpleNamespace(level_title='2-1. Elysium I')
    frames = iter([(img, texts), (img, [])])
    nav._capture = lambda: next(frames)
    monkeypatch.setattr(navigation, 'tutorial_hand', lambda _: None)
    monkeypatch.setattr(navigation, 'parse_lobby', lambda ts: lobby if not ts else None)
    with caplog.at_level('WARNING'):
        assert nav.go_to_lobby() is lobby
    assert actions == [safe, safe, safe]
    assert 'Leaving a level the watchdog ended' in caplog.text
    assert not play.level_abandoned()  # only actual lobby recovery clears the guard


@pytest.mark.parametrize('with_player', [False, True])
def test_abandoned_fight_backs_out_without_replaying_it(monkeypatch, statue, with_player):
    img, _ = statue
    device, actions = fake_device()
    nav = Navigator(device, None)
    if with_player:
        nav.resume_level = lambda: pytest.fail('abandoned fight resumed')
    monkeypatch.setattr(play, '_level_abandoned', True)
    frames = iter([(img, [t('Round 1/30')]), (img, [])])
    nav._capture = lambda: next(frames)
    monkeypatch.setattr(navigation, 'tutorial_hand', lambda _: None)
    monkeypatch.setattr(navigation, 'parse_lobby', lambda ts: 'lobby' if not ts else None)
    monkeypatch.setattr(navigation, 'classify_level_screen', lambda *_: LevelState(LevelScreen.FIGHT))
    monkeypatch.setattr(navigation, 'back_arrow', lambda _: None)
    assert not nav.level_in_progress()
    assert nav.go_to_lobby() == 'lobby'
    assert actions == ['back']
    assert not play.level_abandoned()


@pytest.mark.parametrize('language,title,abandon,ok', [
    ('en', 'Continue Adventure?', 'Abandon', 'OK'),
    ('es', 'Continuar la aventura', 'Abandonar', 'Confirmar'),
])
def test_abandoned_adventure_prompt_never_resumes(monkeypatch, statue, language, title, abandon, ok):
    labels.set_language(language)
    img, _ = statue
    texts = [t(title, y=875), t(abandon, x=550, y=1417), t(ok, x=890, y=1417)]
    device, actions = fake_device()
    nav = Navigator(device, None)
    nav.resume_level = lambda: pytest.fail('abandoned adventure resumed')
    monkeypatch.setattr(play, '_level_abandoned', True)
    frames = iter([(img, texts), (img, [])])
    nav._capture = lambda: next(frames)
    monkeypatch.setattr(navigation, 'tutorial_hand', lambda _: None)
    monkeypatch.setattr(navigation, 'parse_lobby', lambda ts: 'lobby' if not ts else None)
    assert nav.go_to_lobby() == 'lobby'
    assert actions == [(550, 1417)]
    assert not play.level_abandoned()


def test_pray_is_only_a_safe_exit_on_a_recognized_statue():
    assert world2.safe_exit_point([t('Pray', y=1600)]) is None


def test_abandoned_level_result_still_uses_its_continue_button(monkeypatch, statue):
    img, _ = statue
    texts = [t('Victory!', y=900), t('Continue', y=2300)]
    device, actions = fake_device()
    nav = Navigator(device, None)
    monkeypatch.setattr(play, '_level_abandoned', True)
    frames = iter([(img, texts), (img, [])])
    nav._capture = lambda: next(frames)
    monkeypatch.setattr(navigation, 'tutorial_hand', lambda _: None)
    monkeypatch.setattr(navigation, 'parse_lobby', lambda ts: 'lobby' if not ts else None)
    monkeypatch.setattr(navigation, 'close_button', lambda _: None)
    assert nav.go_to_lobby() == 'lobby'
    assert actions == [(720, 2300)]
