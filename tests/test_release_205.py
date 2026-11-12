"""2.0.5 regression coverage using release captures and fake devices; no emulator."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from roguebot import config, labels, world2
from roguebot.build import (PRESETS, POISON_RANK, BuildState, choose, core_index,
                            offer_is_unfavorable, ranked, shop_order)
from roguebot.mode_screens import dojo_unavailable, parse_fight_result
from roguebot.play import Player
from roguebot.screens import (LevelScreen, LevelState, classify_level_screen,
                              close_button_any_size, parse_skill_cards, vault_cinematic)
from roguebot.skills import Catalog, Skill, skill_key
from roguebot.vision import Text
from conftest import fixture_image

FIXTURES = Path(__file__).resolve().parents[1] / 'specs' / '2.0.5'
POISON = PRESETS['poison']


@pytest.fixture(autouse=True)
def english():
    labels.set_language('en')
    yield
    labels.set_language(None)


def t(text, x=720, y=500):
    return Text(text, x - 70, y - 20, x + 70, y + 20)


def skill(name, damage_type=None, rarity='common'):
    return Skill(name, 'en', rarity, damage_type, 'physical', 'damage')


def player():
    p = Player.__new__(Player)
    p.device = SimpleNamespace(back=lambda: None)
    p._miner = p._miner_centers = p._miner_pending = None
    p._miner_used, p._miner_skips = 0, set()
    p._miner_wait_since = p._clearing_since = None
    p._open_chest = False
    return p


@pytest.mark.parametrize('icons', [2, 9])
def test_miner_confirmed_digs_override_stuck_icons(monkeypatch, icons):
    p = player()
    img = np.full((2560, 1440, 3), 120, np.uint8)
    monkeypatch.setattr(world2, 'read_miner_grid', lambda *_: (world2.blank_miner(), world2.fallback_miner_centers()))
    monkeypatch.setattr(world2, 'count_pickaxes', lambda *_: icons)
    monkeypatch.setattr(world2, 'tile_changed', lambda *_: True)
    # Every confirmed change consumes one tool. No tenth dig, regardless of icon reading.
    for _ in range(9):
        assert p._miner_tap(img, []) is not None
    assert p._miner_tap(img, []) is None
    assert p._miner_used == 9
    assert p._miner_pending is None


def test_miner_grid_rejects_shifted_edges_even_with_valid_average_step():
    assert not world2.miner_step_ok([337 + 161*i for i in range(7)], 149, 1440, 0)
    assert world2.miner_step_ok(list(world2.FALLBACK_MINER_COLS), 149, 1440, 0)
    assert not world2.miner_step_ok([y + 50 for y in world2.FALLBACK_MINER_ROWS], 145, 2560, 1)
    assert world2.miner_step_ok([x / 2 for x in world2.FALLBACK_MINER_COLS], 149, 720, 0)


@pytest.mark.parametrize('name', ['Corrosion', 'Special Experiment', 'Poison Strike', 'Deep Venom', 'Combo Mastery Lv. 2'])
def test_statue_protects_poison_core(name):
    assert world2.is_core_skill(name, POISON)
    assert world2.decide_statue(name, POISON).choice == 'pray'


@pytest.mark.parametrize('name', ['Ninja Dodge', 'Heal Shuriken'])
def test_support_names_stay_not_core(name):
    assert world2.is_core_skill(name, POISON) is False


def test_statue_reads_catalog_role_and_pet_context(tmp_path, monkeypatch):
    c = Catalog(tmp_path / 'skills.json')
    c.skills['arbitrary'] = skill('Arbitrary', 'venom')
    monkeypatch.setattr(world2, 'Catalog', lambda: c)
    assert world2.is_core_skill('Arbitrary', POISON)
    c.skills['arbitrary'].role = 'support'
    assert world2.is_core_skill('Arbitrary', POISON) is False
    assert world2.is_core_skill('Special Experiment', replace(POISON, pets_equipped=False)) is False


def test_poison_order_applies_to_picks_shop_and_rerolls():
    cards = [skill(name) for name in reversed(list(POISON_RANK))]
    expected = sorted(range(len(cards)), key=lambda i: POISON_RANK[skill_key(cards[i].name)])
    assert ranked(cards, POISON, BuildState()) == expected
    assert shop_order(cards, POISON, BuildState(), True, fill=False) == expected
    assert choose(cards, POISON, BuildState(), True) == expected[0]
    assert skill_key(cards[expected[0]].name) == 'poisonstrike'
    for card in cards:
        assert not offer_is_unfavorable([card], POISON, BuildState(), picks=4)
    bolt = Skill('Combo Bolt', 'en', 'mythic', 'lightning', 'magic', 'damage')
    counter = skill('Counter Mastery')
    assert choose([bolt, counter, skill('Enhanced Combo')], POISON, BuildState(), False) == 2
    assert choose([bolt, counter], POISON, BuildState(), False) == 1
    assert shop_order([bolt], POISON, BuildState(), False, fill=False) == []


def test_four_card_offer_keeps_one_preferred_and_fills_rest():
    cards = [skill('Poison Strike', 'venom'), skill('Warrior'), skill('Fire Weapon', 'fire'), skill('Deadly Fireball', 'fire')]
    assert not offer_is_unfavorable(cards, POISON, BuildState(), picks=4)
    assert shop_order(cards, POISON, BuildState(), False)[0] == 0
    assert core_index([skill('Combo Mastery Lv. 2')], POISON) == 0


MAPS = ['20261110_154206_after_event.png', '20261110_160257_after_event.png',
        '20261110_161702_after_event.png', '20261110_165755_after_event.png', '20261110_171138_after_event.png']
INFO = ['play_20261110_201409.png', 'fail_20261110_201455.png', 'fail_20261110_201541.png',
        'fail_20261110_201628.png', 'fail_20261110_201713.png', '20261110_204000_skill_info.png',
        '20261110_204015_after_event.png', 'play_20261110_225625.png', 'play_20261111_060908.png']
BATTLES = ['20261111_004206_12_1m_8_7m.png', '20261111_004457_23_6m_9_4m.png', '20261111_010904_round_1730.png']
MINERS = ['watchdog_back_20261111_205121.png', 'watchdog_stop_20261111_205450.png', 'fail_20261111_205702.png']


@pytest.mark.parametrize('name', MAPS)
def test_zoomed_maps_are_not_unknown_events(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    assert world2.is_quiet_map(texts)
    assert world2.skip_unknown_save(texts)
    assert not world2.coin_flip_applies(texts)
    p = player()
    p._save_unknown = lambda *_: pytest.fail('saved the map')
    p._world2(img, texts, LevelState(LevelScreen.UNKNOWN))


@pytest.mark.parametrize('name', INFO)
def test_skill_info_closes_before_claim_or_event_waiter(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    assert world2.is_skill_info(texts)
    close = close_button_any_size(img)
    assert close is not None and abs(close[0]-720) < 25 and abs(close[1]-2259) < 25
    assert world2.skip_unknown_save(texts)
    assert not world2.coin_flip_applies(texts)
    p = player()
    p._save_unknown = lambda *_: pytest.fail('saved Skill Info')
    state = p._world2(img, texts, LevelState(LevelScreen.UNKNOWN))
    assert state.tap == close
    assert classify_level_screen(img, texts).tap == close


def test_watchdog_ignores_overlay_ocr_jitter_and_action_attempts():
    a = [t('Skill Info'), t('HP 120', y=900)]
    b = [t('Skill Info', x=721), t('HP 121', y=905), t('garbled description', y=1100)]
    sig = world2.progress_signature(a)
    assert sig == world2.progress_signature(b)
    w = world2.StuckWatch()
    assert w.see(sig, 0) == 'ok'
    assert w.see(world2.progress_signature(b), 90) == 'back'
    assert w.see(sig, 300) == 'stop'


@pytest.mark.parametrize('name', ['20261110_180908.png', '20261110_195310.png', '20261110_200330.png',
                                  '20261111_020306.png', '20261111_161923.png'])
def test_poison_reroll_fixtures_keep_combo_cards(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    cards = parse_skill_cards(texts, (80, 720))
    c = Catalog()
    # Recognition decisions must not write the real catalog during tests.
    skills = [c.skills.get(skill_key(card.name)) or skill(card.name) for card in cards]
    i = choose(skills, POISON, BuildState(), True)
    assert i is not None
    assert skill_key(skills[i].name) in {'combomastery', 'followupstrike', 'weaponmastery'}


@pytest.mark.parametrize('name', ['20261110_193431_level_modifiers.png', '20261110_193814_level_modifiers.png',
                                  '20261111_193352_level_modifiers.png'])
def test_modifiers_continue_is_not_overwritten(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    state = classify_level_screen(img, texts)
    assert state.kind == LevelScreen.CONTINUE
    assert player()._world2(img, texts, state) == state
    assert not any(label.lower() in {'level', 'modifiers'} for label, _ in world2.coin_flip_labels(texts))
    assert world2.tap_forbidden((1200, 2050))


@pytest.mark.parametrize('name', ['20261110_194207_x10x55_5kx1.png', '20261111_025355_eliteenemy.png', '20261111_041002_maxhp_11.png'])
def test_spinner_taps_stop_not_reward_prices_or_hud(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    state = classify_level_screen(img, texts)
    assert state.kind == LevelScreen.CONTINUE
    assert any(x.norm == 'tap to stop' and x.center == state.tap for x in texts)
    assert world2.event_title(texts) is None
    assert not world2.coin_flip_applies(texts)


@pytest.mark.parametrize('name', MINERS)
def test_miner_with_tools_and_closed_tiles_keeps_digging(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    assert world2.is_miner(texts)
    p = player()
    p._miner_used = 7
    p._miner = [[world2.DUG]*7 for _ in range(7)]  # stale merged board caused the original hang
    point = p._miner_tap(img, texts)
    assert point is not None
    assert 250 <= point[0] <= 1200 and 1060 <= point[1] <= 2020
    assert p._miner_pending is not None


def test_tower_victory_fixture_advances(ocr):
    texts = ocr.read(fixture_image(FIXTURES / 'fail_20261111_193325.png'))
    result = parse_fight_result(texts)
    assert result and result.victory and result.next_floor


def test_dojo_modes_zero_tickets_is_unavailable(ocr):
    img = fixture_image(FIXTURES / 'fail_20261111_190704.png'); texts = ocr.read(img)
    assert dojo_unavailable(img, texts, ocr)
    from roguebot.routine import Routine
    r = Routine.__new__(Routine); r.ocr = ocr
    result = r._dojo_screen(img, texts)
    assert result.tickets == 0 and result.challenge is None


def test_vault_cinematic_recognition_and_no_price_popup_false_positive(ocr):
    img = fixture_image(FIXTURES / 'fail_20261111_194801.png'); texts = ocr.read(img)
    assert vault_cinematic(img, texts)
    assert not vault_cinematic(img, [t('Claim 100 gems')])
    assert not vault_cinematic(np.zeros_like(img), [])


@pytest.mark.parametrize('name', BATTLES)
def test_fight_frames_never_coin_flip_or_save(name, ocr):
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    assert world2.is_battle(texts)
    assert classify_level_screen(img, texts).kind == LevelScreen.FIGHT
    assert world2.skip_unknown_save(texts)
    assert world2.event_title(texts) is None
    assert world2.coin_flip_labels(texts) == []
    assert not world2.coin_flip_applies(texts)


def test_catalog_new_skills_and_clean_level_suffix(tmp_path):
    c = Catalog()
    for name, rarity in [('Serpent Stance', 'mythic'), ('Outbreak', 'legendary')]:
        s = c.skills[skill_key(name)]
        assert (s.rarity, s.damage_type, s.nature, s.role, s.auto) == (rarity, 'venom', 'physical', 'damage', False)
    c = Catalog(tmp_path / 'skills.json')
    s = c.lookup('Outbreak-Lv-2+', 'At round 3, apply Poison 15 times on all enemies.', 'legendary', 'en')
    assert s.name == 'Outbreak' and list(c.skills) == ['outbreak']


def test_tower_many_skipped_floors_with_no_observed_round(monkeypatch):
    from roguebot.routine import Routine, DONE
    from roguebot.mode_screens import FightResult
    r = Routine.__new__(Routine)
    r._open_mode = lambda _: True
    r._wait_for = lambda *_: SimpleNamespace(tickets=19, challenge=t('Challenge'))
    r._press = lambda *_: None
    floors = iter(range(1, 207))
    r._capture = lambda: (None, [t(f'Tower of Heroes {next(floors)}')])
    r._push = lambda *_: None
    wins = iter([FightResult(True, t('OK'), t('Next'), False)]*205 + [FightResult(False, t('OK'))])
    r._fight = lambda **_: next(wins)
    assert r.tower() == DONE


@pytest.mark.parametrize('name,action', [('play_20261110_201409.png', 'close'),
                                         ('fail_20261111_205702.png', 'back'),
                                         ('fail_20261111_194801.png', 'center')])
def test_lobby_recovery_dismisses_blocking_release_screens(name, action, ocr, monkeypatch):
    from roguebot import navigation
    img = fixture_image(FIXTURES / name); texts = ocr.read(img)
    sentinel = [t('test lobby')]
    frames = iter([(img, texts), (img, sentinel)])
    taps, backs = [], []
    nav = navigation.Navigator(SimpleNamespace(tap=lambda x,y,**_: taps.append((x,y)), back=lambda: backs.append(True)), ocr)
    nav._capture = lambda: next(frames)
    monkeypatch.setattr(navigation, 'parse_lobby', lambda ts: 'lobby' if ts == sentinel else None)
    monkeypatch.setattr(navigation, 'tutorial_hand', lambda _: None)
    monkeypatch.setattr(navigation.time, 'sleep', lambda _: None)
    assert nav.go_to_lobby() == 'lobby'
    if action == 'close':
        assert taps == [close_button_any_size(img)]
    elif action == 'center':
        assert taps == [(720, 1280)]
    else:
        assert backs or taps  # a visible close is also safe


def test_miner_spent_wait_is_bounded_without_an_extra_dig(monkeypatch):
    from roguebot import play
    p = player(); backs=[]; p.device.back=lambda: backs.append(True)
    ticks=iter([0., 9.]); monkeypatch.setattr(play.time, 'monotonic', lambda: next(ticks))
    assert p._miner_wait_for_leave() is None
    assert p._miner_wait_for_leave() is None
    assert backs == [True]


def test_vault_exit_waits_through_cinematic(ocr, monkeypatch):
    from roguebot import routine
    img = fixture_image(FIXTURES / 'fail_20261111_194801.png'); texts = ocr.read(img)
    r = routine.Routine.__new__(routine.Routine)
    taps=[]; r.device=SimpleNamespace(tap=lambda x,y: taps.append((x,y)))
    frames=iter([(img,texts),(None,[])])
    r._capture=lambda: next(frames)
    monkeypatch.setattr(routine.time,'sleep',lambda _: None)
    r._leave_guild()
    assert taps == [(720,1280)]


@pytest.mark.parametrize('name', MINERS)
def test_miner_icon_reader_counts_lit_tools_not_dim_silhouettes(name):
    img = fixture_image(FIXTURES / name)
    assert world2.count_pickaxes(img, world2.fallback_miner_centers()) == 2


def test_poison_strike_precedes_combos_before_and_after_ownership():
    cards = [skill('Combo Mastery', rarity='legendary'), skill('Poison Strike', 'venom')]
    state = BuildState()
    assert choose(cards, POISON, state, True) == 1
    state.take(cards[1])
    assert choose(cards, POISON, state, True) == 1
    from roguebot.build import protected_core
    assert not protected_core('Combo Mastery', POISON, BuildState())
    state.take(cards[0])
    assert protected_core('Combo Mastery', POISON, state)


def test_hud_only_zoomed_map_does_not_require_hp_or_building_ocr():
    texts = [t('EXP', y=100), t('Lv', y=150), t('Skills', x=1200, y=2450)]
    assert world2.is_quiet_map(texts)
    assert world2.skip_unknown_save(texts)


def test_combo_bolt_is_excluded_even_from_fill_and_fallback():
    bolt = Skill('Combo Bolt', 'en', 'mythic', 'lightning', 'magic', 'damage')
    assert choose([bolt], POISON, BuildState(), False) is None
    assert shop_order([bolt, skill('Counter Mastery')], POISON, BuildState(), False) == [1]


def test_no_free_revive_is_not_overwritten_by_the_battle_behind_it():
    texts = [t('Round 1/30'), t('Revive?', y=1000)]
    # Use the active label, avoiding reliance on a guessed prompt translation.
    texts[-1] = t(labels.REVIVE_PROMPT.variants[0], y=1000)
    state = LevelState(LevelScreen.UNKNOWN)
    assert player()._world2(None, texts, state) == state
