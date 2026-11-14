"""2.0.7: approved vendor weights, real-image Luxury Pass and ticket-only Dive.

The public fixture contains only static offer artwork, with no account details.
The actual-image tests always call the repository OCR fixture, never transcribed Text.
"""
import itertools
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from conftest import fixture_image
from roguebot import labels, luxury_pass, mode_screens, navigation, play, routine, screens, world2
from roguebot.luxury_pass import LuxuryPassBlocked
from roguebot.vision import Text

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
BENEFITS = [
    ('golden_road', 9000, 'Create a golden road of mega-buff tiles'),
    ('debuff_to_buff', 8000, 'Replace all debuff tiles with buff tiles'),
    ('remove_half', 7000, 'Remove half the enemy tiles'),
    ('inn', 6000, 'Every campfire becomes an inn'),
    ('elites_start', 5000, 'Elite enemies and bosses start with 25% less HP'),
    ('rerolls', 4000, 'Skill rerolls refresh on every skill selection'),
    ('black_market', 3000, 'All shops become black markets'),
    ('first_shop', 2000, 'First shop purchase is free'),
    ('tokens_500', 1000, 'Gain 500 Shop Tokens'),
]
CURSES = [
    ('shop_prices', 1000, 'Shop prices are doubled'),
    ('exp_halved', 2000, 'EXP gain is halved'),
    ('pets_disabled', 3000, 'Pets are disabled for the first three rounds'),
    ('mythic_trash', 4000, 'The next Mythic skill learned becomes Trash'),
    ('revives_disabled', 5000, 'Revives are disabled'),
    ('skills_disabled', 6000, 'Half the skills are disabled'),
    ('lose_max_hp', 7000, 'Lose 5% Max HP after each battle'),
    ('enemies_first', 8000, 'Enemies always act first'),
    ('campfires', 9000, 'All campfires are removed'),
    ('trip', 9500, 'Chance to trip instead of Basic Attacking'),
]


def text(value, x=720, y=500):
    return Text(value, x-60, y-20, x+60, y+20)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    labels.set_language('en')
    monkeypatch.setattr(play, 'DEBUG_DIR', tmp_path / 'player')
    monkeypatch.setattr(routine, 'DEBUG_DIR', tmp_path / 'routine')
    monkeypatch.setattr(navigation, 'DEBUG_DIR', tmp_path / 'navigation')
    monkeypatch.setattr(routine.config, 'POLL_INTERVAL', 0)
    monkeypatch.setattr(world2, 'LAST', None)
    yield
    labels.set_language(None)


@pytest.fixture(scope='session')
def luxury(ocr):
    # Generic full-screen offer artwork; no account HUD is present.
    img = fixture_image(FIXTURES / 'luxury_pass_season25.png')
    return img, ocr.read(img)


@pytest.mark.parametrize('benefit,curse', list(itertools.product(BENEFITS, CURSES)))
def test_every_approved_rank_pair_and_only_approved_interaction(benefit, curse):
    bid, rank, blessing = benefit
    cid, penalty, curse_text = curse
    bundle, unknown = world2.parse_vendor_bundle(blessing + '\n' + curse_text)
    assert not unknown and bundle is not None
    assert (bundle.benefit_id, bundle.curse_id) == (bid, cid)
    assert (bundle.benefit_rank, bundle.curse_penalty) == (rank, penalty)
    adjustment = -6000 if (bid, cid) == ('inn', 'campfires') else 0
    assert bundle.adjustment == adjustment
    assert bundle.score == rank - penalty + adjustment
    for rolls in (None, 0, 3, 5, 30):
        assert world2.score_vendor_card(blessing + '\n' + curse_text, rolls) == (bundle.score, [])


def test_vendor_variable_pairing_and_tie_breaks():
    golden_exp = BENEFITS[0][2] + '\n' + CURSES[1][2]
    debuff_prices = BENEFITS[1][2] + '\n' + CURSES[0][2]
    assert world2.decide_vendor(debuff_prices, golden_exp, None).choice == 'right'
    assert world2.decide_vendor(golden_exp, debuff_prices, None).choice == 'left'
    golden_trip = BENEFITS[0][2] + '\n' + CURSES[-1][2]
    assert world2.decide_vendor(golden_trip, debuff_prices, None).choice == 'right'
    assert world2.decide_vendor(golden_exp, golden_exp, None).choice == 'left'
    # The final ID ordering is explicit even though the approved ranks are unique.
    b = world2.VendorBundle
    assert b('a', 'z', 6000, 1000, 0).order < b('z', 'a', 5000, 1000, 1000).order
    assert b('z', 'z', 6000, 1000, 0).order < b('a', 'a', 6000, 2000, 1000).order
    assert b('a', 'z', 6000, 1000, 0).order < b('b', 'a', 6000, 1000, 0).order
    assert b('a', 'a', 6000, 1000, 0).order < b('a', 'b', 6000, 1000, 0).order


@pytest.mark.parametrize('unknown', ['', 'Gain 500 Shop Tokens', 'Shop prices are doubled',
    'Gain 500 Shop Tokens\nUnknown new curse',
    'Gain 500 Shop Tokens\nShop prices are doubled and lose all health',
    'Gain 500 Shop Tokens\nShop prices are doubled\nEXP gain is halved',
    'Gain 500 Shop Tokens\nShop prices',
    'Golden road\nShop prices are doubled'])
def test_vendor_incomplete_effects_are_unranked_deterministic_and_captured(unknown):
    assert world2.score_vendor_card(unknown, 20)[0] is None
    good = 'Every campfire becomes an inn\nShop prices are doubled'
    assert world2.decide_vendor(unknown, good, None).choice == 'right'
    d = world2.decide_vendor(unknown, unknown, None)
    assert d.choice == 'left' and not d.inputs['coin_flip']
    assert d.inputs['unknown'] and world2.vendor_needs_shot(d)


def test_vendor_unknown_saves_screenshot_and_ocr(luxury, tmp_path):
    img, texts = luxury
    p = play.Player(SimpleNamespace(), None)
    d = world2.decide_vendor('unknown benefit\nunknown curse', '', None)
    p._capture_vendor(img, texts, d)
    assert list((play.DEBUG_DIR / 'new_cursed_vendor').glob('*.png'))
    assert any('Luxury Pass' in f.read_text() for f in (play.DEBUG_DIR / 'new_cursed_vendor').glob('*.txt'))


def test_actual_luxury_image_ocr_recognized_before_generic_events(luxury, monkeypatch):
    img, texts = luxury
    assert {'luxury pass', 'new season', 'season 25', '$29.99'} <= {t.norm for t in texts}
    monkeypatch.setattr(screens, 'level_tap', lambda *a, **kw: pytest.fail('generic event consulted'))
    monkeypatch.setattr(screens, 'footer_visible', lambda _: pytest.fail('footer consulted'))
    state = screens.classify_level_screen(img, texts)
    assert state.kind is screens.LevelScreen.LUXURY_PASS
    assert state.tap == (720, 2453)
    assert state.tap[1] > max(t.y2 for t in texts) + 200


@pytest.mark.parametrize('change', ['price', 'season', 'anchor_missing', 'moved_anchor', 'extra_price',
                                  'blank_ocr', 'offer_shift', 'offer_changed', 'outside_blocked', 'wrong_size'])
def test_luxury_changed_or_unreadable_layout_fails_closed(luxury, change):
    original, original_texts = luxury
    img, texts = original.copy(), list(original_texts)
    if change in ('price', 'season'):
        old, new = ('$29.99', '$9.99') if change == 'price' else ('Season 25', 'Season 26')
        texts = [Text(new, t.x1, t.y1, t.x2, t.y2) if t.text == old else t for t in texts]
    elif change == 'anchor_missing':
        texts = [t for t in texts if t.norm != 'new season']
    elif change == 'moved_anchor':
        texts = [Text(t.text, t.x1, t.y1+70, t.x2, t.y2+70) if t.norm == '$29.99' else t for t in texts]
    elif change == 'extra_price':
        texts.append(text('$1', y=2400))
    elif change == 'blank_ocr':
        texts = []
    elif change == 'offer_shift':
        img = np.roll(img, 60, axis=0)
    elif change == 'offer_changed':
        img[1650:2200, 300:1100] = 0
    elif change == 'outside_blocked':
        img[2390:2520, 600:840] = (0, 255, 0)
    elif change == 'wrong_size':
        img = cv2.resize(img, (720, 1280))
    assert luxury_pass.is_luxury_pass(img, texts)
    assert luxury_pass.dismissal_tap(img, texts) is None
    assert screens.classify_level_screen(img, texts).tap is None


def test_luxury_timer_changes_do_not_weaken_price_or_outside_guards(luxury):
    img, texts = luxury
    changed = img.copy()
    changed[1130:1174, 671:829] = 0
    assert luxury_pass.dismissal_tap(changed, texts) == (720, 2453)


class Device:
    def __init__(self, frames=()):
        self.frames = iter(frames)
        self.actions = []

    def screenshot(self):
        img = next(self.frames)
        self.actions.append(('screenshot',))
        return img

    def tap(self, *point):
        self.actions.append(point)

    def back(self):
        self.actions.append(('back',))


def test_luxury_one_tap_then_immediate_fresh_classification_without_reset(luxury, monkeypatch):
    popup, popup_texts = luxury
    end = np.zeros_like(popup)
    end_texts = [text('VICTORY!'), text('Confirm', y=2100)]
    device = Device([popup, end])
    ocr = SimpleNamespace(read=lambda img, *a: popup_texts if img is popup else end_texts)
    p = play.Player(device, ocr)
    monkeypatch.setattr(p, '_watchdog', lambda *a: pytest.fail('watchdog used'))
    assert p.play_level() is screens.LevelScreen.VICTORY
    assert device.actions == [('screenshot',), (720, 2453), ('screenshot',), (720, 2100)]
    assert not play.level_abandoned()


def test_luxury_no_second_tap_even_across_play_level_retry(luxury):
    img, texts = luxury
    device = Device([img, img, img])
    p = play.Player(device, SimpleNamespace(read=lambda _: texts))
    with pytest.raises(LuxuryPassBlocked):
        p.play_level()
    with pytest.raises(LuxuryPassBlocked):
        p.play_level()
    assert device.actions.count((720, 2453)) == 1
    assert ('back',) not in device.actions
    assert list((play.DEBUG_DIR / 'unknown_events').glob('*.png'))
    assert list((play.DEBUG_DIR / 'unknown_events').glob('*.txt'))


def test_luxury_unreadable_never_taps_and_lobby_recovery_never_backs(luxury):
    img, texts = luxury
    device = Device([img, img])
    p = play.Player(device, SimpleNamespace(read=lambda _: []))
    with pytest.raises(LuxuryPassBlocked):
        p.play_level()
    nav = navigation.Navigator(device, SimpleNamespace(read=lambda _: texts))
    with pytest.raises(LuxuryPassBlocked):
        nav.go_to_lobby()
    assert device.actions == [('screenshot',), ('screenshot',)]


@pytest.fixture
def dive_frames(ocr):
    labels.set_language('es')
    frames = {}
    for name in ('dive.png', 'dive_no_tickets.png', 'dive_modifiers.png'):
        img = fixture_image(FIXTURES / name)
        frames[name] = (img, ocr.read(img))
    img, texts = frames['dive.png']
    two = [Text('2/2', t.x1, t.y1, t.x2, t.y2) if t.norm == '1/2' else t for t in texts]
    frames['two'] = (img, two)
    return frames


@pytest.mark.parametrize('name,tickets', [('dive.png', 1), ('dive_no_tickets.png', 0), ('two', 2)])
def test_dive_real_fixture_tickets_and_cost(dive_frames, name, tickets):
    img, texts = dive_frames[name]
    state = mode_screens.parse_dive(texts, img)
    assert state.tickets == tickets and state.cost == 1 and not state.reason


def make_routine(frames, monkeypatch):
    r = routine.Routine(Device(), None, SimpleNamespace())
    frames = iter(frames)
    r._capture = lambda: next(frames)
    monkeypatch.setattr(r, '_open_mode', lambda _: True)
    r.play_level = lambda: screens.LevelScreen.VICTORY
    return r


@pytest.mark.parametrize('tickets', [0, 1, 2])
def test_dive_runs_exactly_one_attempt_per_ticket_to_exhaustion(dive_frames, monkeypatch, tickets):
    ordered = [dive_frames['dive_no_tickets.png']]
    if tickets >= 1:
        ordered = [dive_frames['dive.png'], dive_frames['dive_modifiers.png']] + ordered
    if tickets == 2:
        ordered = [dive_frames['two'], dive_frames['dive_modifiers.png']] + ordered
    r = make_routine(ordered, monkeypatch)
    played = []
    r.play_level = lambda: played.append(True) or screens.LevelScreen.DEFEAT
    assert r.dive() == routine.DONE
    assert len(played) == tickets
    challenge = mode_screens.parse_dive(dive_frames['dive.png'][1]).challenge.center
    assert r.device.actions == [challenge] * tickets + [('back',)]


@pytest.mark.parametrize('change', ['missing', 'contradictory', '3/2', '1/3', 'bad_cost',
                                  'missing_cost', 'currency_icon', 'unknown_title', 'extra_charge', 'no_image'])
def test_dive_invalid_main_state_does_not_challenge(dive_frames, monkeypatch, change):
    original, ts = dive_frames['dive.png']
    img, texts = original.copy(), list(ts)
    if change == 'missing':
        texts = [t for t in texts if t.norm != '1/2']
    elif change == 'contradictory':
        texts.append(text('0/2', 850, 80))
    elif change in ('3/2', '1/3'):
        texts = [Text(change, t.x1, t.y1, t.x2, t.y2) if t.norm == '1/2' else t for t in texts]
    elif change == 'bad_cost':
        texts = [Text('2', t.x1, t.y1, t.x2, t.y2) if t.norm == '1' else t for t in texts]
    elif change == 'missing_cost':
        texts = [t for t in texts if t.norm != '1']
    elif change == 'currency_icon':
        img[2450:2515, 650:740] = 0
    elif change == 'unknown_title':
        texts = [t for t in texts if 'ruinas' not in t.norm]
    elif change == 'extra_charge':
        texts.append(text('$0.99', y=2300))
    elif change == 'no_image':
        img = None
    r = make_routine([(img, texts)], monkeypatch)
    r.play_level = lambda: pytest.fail('invalid entry played')
    assert r.dive() == routine.DONE
    assert r.device.actions == [('back',)]
    assert list(routine.DEBUG_DIR.glob('*.txt'))


@pytest.mark.parametrize('offer', ['Refill tickets', 'Watch Ad', 'Shop', 'Purchase', 'Subscribe',
                                 'Subscription', 'Buy 1 ticket', '10 gems', '10 gold', '10 diamonds',
                                 '$1.99', 'Free video', 'Cash', 'Unknown charge'])
def test_dive_spending_and_unknown_prompts_are_backed_out(dive_frames, monkeypatch, offer):
    img, _ = dive_frames['dive.png']
    prompt = (img, [text(offer), text('Confirm', y=1900), text('Cancel', y=1900, x=300)])
    r = make_routine([dive_frames['dive.png'], prompt], monkeypatch)
    r.play_level = lambda: pytest.fail('spending prompt handed to Player')
    assert r.dive() == routine.DONE
    assert r.device.actions == [(719, 2416), ('back',)]


def confirmation(body='Use exactly 1 Dungeon Dive ticket?'):
    return [text('Dungeon Dive'), text(body, y=1200), text('Confirm', x=900, y=1600),
            text('Cancel', x=400, y=1600)]


@pytest.mark.parametrize('body', ['Use exactly 1 Dungeon Dive ticket?', 'Spend 1 Dungeon Dive ticket?'])
def test_dive_accepts_only_explicit_one_ticket_confirmation(body):
    assert mode_screens.dive_confirmation(confirmation(body)).center == (900, 1600)


@pytest.mark.parametrize('body', ['Use 2 Dungeon Dive tickets?', 'Use 0 Dungeon Dive ticket?',
    'Use 1 ticket?', 'Use 1 Dungeon Dive ticket and 10 gems?', 'Use 1 Dungeon Dive ticket and watch ad?',
    'Use 1 Dungeon Dive ticket plus unknown charge?', 'Use 1 Dungeon Dive ticket for $0.99?'])
def test_dive_confirmation_rejects_other_or_unknown_charges(body):
    assert mode_screens.dive_confirmation(confirmation(body)) is None


def test_dive_confirmation_with_separate_extra_charge_is_rejected():
    assert mode_screens.dive_confirmation(confirmation() + [text('10 gems', y=1300)]) is None


def test_dive_confirm_once_then_play_fresh_attempt(dive_frames, monkeypatch):
    labels.set_language(None)
    img, _ = dive_frames['dive.png']
    r = make_routine([(img, confirmation()), dive_frames['dive_modifiers.png']], monkeypatch)
    assert r._dive_start()
    assert r.device.actions == [(900, 1600)]


def test_dive_repeated_confirmation_does_not_spend_twice(dive_frames, monkeypatch):
    labels.set_language('en')
    img, _ = dive_frames['dive.png']
    r = make_routine([(img, confirmation()), (img, confirmation())], monkeypatch)
    assert not r._dive_start()
    assert r.device.actions == [(900, 1600), ('back',)]


def test_dive_ticket_count_must_decrease_before_another_attempt(dive_frames, monkeypatch):
    r = make_routine([dive_frames['dive.png'], dive_frames['dive_modifiers.png'],
                      dive_frames['dive.png']], monkeypatch)
    assert r.dive() == routine.DONE
    assert r.device.actions == [(719, 2416), ('back',)]


def test_luxury_guard_is_terminal_in_runner(monkeypatch):
    from roguebot import __main__ as main
    from roguebot.request import RunRequest
    from test_main import FakeNav, FakeEmulator, FakeRoutine, run_with
    calls = []
    nav = FakeNav(energy=10)
    def blocked(*args):
        calls.append(True)
        raise LuxuryPassBlocked('no safe dismissal')
    nav.start_star_challenge = blocked
    monkeypatch.setattr(main, 'Emulator', FakeEmulator)
    monkeypatch.setattr(main, 'Routine', FakeRoutine)
    with pytest.raises(LuxuryPassBlocked):
        run_with(monkeypatch, nav, [], RunRequest(screens.Mode.NORMAL, 4))
    assert calls == [True]


def test_luxury_latch_survives_unknown_frames_and_resets_after_recognized_play(luxury):
    img, texts = luxury
    device = Device()
    p = play.Player(device, None)
    assert p._handle_luxury_pass(img, texts)
    blank = np.zeros_like(img)
    assert not p._handle_luxury_pass(blank, [])
    assert p._luxury_attempted
    state = p._state
    assert not p._handle_luxury_pass(blank, [text('VICTORY!'), text('Confirm', y=2000)])
    assert not p._luxury_attempted and p._state is state
    assert p._handle_luxury_pass(img, texts)
    assert device.actions == [(720, 2453)] * 2


def test_dive_waits_for_main_after_result_and_loading(dive_frames, monkeypatch):
    labels.set_language(None)
    img, _ = dive_frames['dive.png']
    result = (img, [text('VICTORY!'), text('Confirmar', y=2000)])
    loading = (img, [text('Cargando...')])
    r = make_routine([result, loading, dive_frames['dive_no_tickets.png']], monkeypatch)
    assert r.dive() == routine.DONE
    assert r.device.actions == [(720, 2000), ('back',)]


def test_dive_stale_main_times_out_without_another_challenge(dive_frames, monkeypatch):
    monkeypatch.setattr(routine, 'SCREEN_TIMEOUT', -1)
    r = make_routine([dive_frames['dive.png'], dive_frames['dive.png']], monkeypatch)
    assert r.dive() == routine.DONE
    assert r.device.actions == [(719, 2416), ('back',)]


def test_dive_confirmation_without_readable_image_is_not_tapped(monkeypatch):
    r = make_routine([(None, confirmation())], monkeypatch)
    assert not r._dive_start()
    assert r.device.actions == [('back',)]


def test_dive_legitimate_attempt_keeps_unfavorable_skill_reroll(dive_frames, monkeypatch, tmp_path):
    from roguebot.build import Build
    from test_skill_screens import PROMPT, REROLL, card, player
    p = player(tmp_path, Build('magic'))
    labels.set_language(None)
    shield = [PROMPT, *card('Common', 'Iron Shield', 'Gain a Shield.', 928), *REROLL]
    r = make_routine([dive_frames['dive.png'], dive_frames['dive_modifiers.png'],
                      dive_frames['dive_no_tickets.png']], monkeypatch)
    def attempt():
        assert p._pick_skill(shield) == (720, 2120)
        assert p._pick_skill(shield) == (720, 928 + play.config.SKILL_TAP_BELOW_RARITY)
        return screens.LevelScreen.DEFEAT
    r.play_level = attempt
    assert r.dive() == routine.DONE
    assert r.device.actions == [(719, 2416), ('back',)]


def test_luxury_unreadable_changed_body_is_still_blocked(luxury):
    img, _ = luxury
    changed = img.copy()
    changed[1300:2250, 150:1250] = 0
    assert luxury_pass.is_luxury_pass(changed, [])
    p = play.Player(Device([changed]), SimpleNamespace(read=lambda _: []))
    with pytest.raises(LuxuryPassBlocked):
        p.play_level()
    assert p.device.actions == [('screenshot',)]


def test_luxury_arriving_during_card_settle_never_reaches_generic_taps(luxury, monkeypatch):
    popup, texts = luxury
    first = np.zeros_like(popup)
    device = Device([first, popup])
    p = play.Player(device, SimpleNamespace(read=lambda im: texts if im is popup else [text('Cursed Vendor')]))
    monkeypatch.setattr(play, 'wait_until_settled', lambda *a: popup)
    monkeypatch.setattr(p, '_world2', lambda *a: pytest.fail('popup reached generic World 2 handler'))
    with pytest.raises(LuxuryPassBlocked):
        p.play_level()
    assert device.actions == [('screenshot',), (720, 2453), ('screenshot',)]
