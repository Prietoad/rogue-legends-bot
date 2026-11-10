"""2.0.4: hangs, settle, vendor reads, miner grid, shop caps, and the overnight fixtures."""

import random
from pathlib import Path

import pytest

import cv2
import numpy as np

from roguebot import config
from roguebot.build import PRESETS, Build, BuildState, shop_order
from roguebot.labels import set_language, star_challenge_name
from roguebot.screens import LevelScreen, classify_level_screen, parse_skill_cards
from roguebot.skills import Catalog, skill_name_rejected
from roguebot.vision import Text
from roguebot.world2 import (DUG, GEM, FALLBACK_MINER_COLS, StuckWatch, _stay_cost, bandits_done,
                             coin_flip_labels, decide_springs, decide_vendor, hp_plausible, is_bandits,
                             is_battle, is_quiet_map, is_skills_overlay, miner_step_ok, name_unreadable,
                             powerup_next, read_miner_grid, score_vendor_card, skip_unknown_save,
                             vendor_bodies)

FIXTURES = Path(__file__).parent / "fixtures" / "w2_204"


def _t(text, x, y, w=180, h=40):
    return Text(text, x - w // 2, y - h // 2, x + w // 2, y + h // 2)


def test_springs_reads_the_red_damage_not_the_green_gain():
    blob = "Stay Gain +5% Max HP Take -20% HP Damage"
    assert _stay_cost(blob) == 0.20
    # 18.6 / 22.9 is about 81%. 81% - 20% is still above 40%, so Stay.
    decision = decide_springs(["Stay", "Get Out"], 18.6 / 22.9, _stay_cost(blob))
    assert decision.choice == "stay"
    assert "40%" in decision.reason
    # The same hit at 50% HP would leave 30%. Get Out.
    assert decide_springs(["Stay", "Get Out"], 0.50, 0.20).choice == "get_out"
    assert _stay_cost("Gain +5% Max HP") is None


def test_springs_fixture_lines_are_the_damage_cost():
    img = cv2.imread(str(FIXTURES / "boiling_stuck2_half.jpg"))
    assert img is not None and img.shape[:2] == (1280, 720)
    # Coordinates from the half frame, scaled to the 1440x2560 reference.
    stay = _t("Stay", 508, 1798)
    out = _t("Get Out", 926, 1792)
    texts = [
        _t("The Boiling Springs", 718, 1404, 500),
        stay, out,
        _t("Gain +5% Max", 514, 2258),
        _t("HP", 512, 2310, 80),
        _t("Take -20% HP", 512, 2366),
        _t("Damage", 512, 2424, 120),
        _t("Walk Away", 924, 2270),
        _t("18.6m/22.9m", 564, 80, 220),
    ]
    from roguebot.world2 import level_tap
    point = level_tap(img, texts)
    assert point is not None
    # The icon under Stay, not the damage sentence under it.
    assert abs(point[0] - 508) < 40
    assert 1980 < point[1] < 2150
    assert point[1] < 2200


def test_watchdog_escalates_and_does_not_wait_forever():
    watch = StuckWatch()
    sig = (3, 30, 18_600_000, 260, ("the boiling springs", "stay"))
    assert watch.see(sig, 0) == "ok"
    assert watch.see(sig, 89) == "ok"
    assert watch.see(sig, 90) == "back"
    assert watch.see(sig, 97) == "ok"
    assert watch.see(sig, 98) == "exit"
    assert watch.see(sig, 299) == "ok"
    assert watch.see(sig, 300) == "stop"
    # Any change, including the HP line, starts the timer over.
    moved = (3, 30, 18_000_000, 260, ("the boiling springs", "stay"))
    assert watch.see(moved, 301) == "ok"
    assert watch.see(moved, 390) == "ok"


def test_coin_flip_ignores_descriptions_skills_and_attempts_left():
    texts = [
        _t("POWER UP!", 720, 1074),
        _t("Deal +1% +2% increased damage", 824, 1304, 500),
        _t("to enemies for each stack of Poison", 834, 1354, 500),
        _t("on them", 556, 1406),
        _t("NEXT", 720, 2154, 200),
        _t("Skills", 1198, 2455, 120),
        _t("2 attempts left", 718, 1882, 280),
        _t("VIP", 110, 2284, 80),
    ]
    labels = [name for name, _point in coin_flip_labels(texts)]
    assert labels == ["NEXT"]
    point = coin_flip_labels(texts)[0][1]
    assert abs(point[0] - 720) < 40
    assert abs(point[1] - 1198) > 100  # not the Skills book


def test_powerup_next_skills_overlay_and_trash_card():
    upgrade = [
        _t("POWERUP!", 720, 1074),
        _t("Common", 322, 1194, 120),
        _t("Corrosion+", 618, 1230),
        _t("Deal +1% +2% increased damage", 824, 1304, 500),
        _t("NEXT", 720, 2154, 160),
        _t("Skills", 1196, 2454, 120),
    ]
    nxt = powerup_next(upgrade)
    assert nxt is not None and abs(nxt.center[1] - 2154) < 5
    overlay = [_t("Skills", 718, 436, 200), _t("POWER UP!", 720, 1074), _t("NEXT", 718, 2154),
               _t("Skills", 1198, 2456, 120)]
    assert is_skills_overlay(overlay)
    assert powerup_next(overlay) is not None  # the result is still under the book
    trash = [
        _t("POWER UP!", 720, 724),
        _t("Select a Skill to learn!", 720, 850, 500),
        _t("Useless", 324, 930, 140),
        _t("Trash", 546, 964),
        _t("What was once an impressive ability has now been reduced to sludge", 700, 1090, 600),
    ]
    assert powerup_next(trash) is None  # a pick, not an upgrade result
    cards = parse_skill_cards(trash, (80, 720))
    assert len(cards) == 1 and cards[0].rarity == "useless" and cards[0].name == "Trash"


def test_bandits_taps_the_dice_until_escaped_and_not_the_attempts_line():
    rolling = [_t("Captured by Bandits!", 722, 298, 400),
               _t("Roll higher than 8, or lose your shop tokens!", 720, 1140, 600)]
    assert is_bandits(rolling) and not bandits_done(rolling)
    done = rolling + [_t("Escaped!", 720, 1778), _t("2 attempts left", 718, 1882, 280)]
    assert bandits_done(done)
    labels = [name for name, _p in coin_flip_labels(done)]
    assert "2 attempts left" not in labels
    assert all("attempt" not in name.lower() for name in labels)


def test_vendor_reads_the_blessing_half_and_keeps_unknown_lines_a_coin_flip():
    left_sign = _t("Sign", 428, 2364, 160)
    right_sign = _t("Sign", 1008, 2362, 160)
    texts = [
        _t("This will", 500, 1100, 200),  # speech bubble, above the cards
        _t("CURSES FOR A PRICE", 900, 1200, 300),
        _t("Remove half of the enemy tiles on the board and gain EXP and Shop Tokens.", 400, 1550, 500, 200),
        _t("Shop prices are doubled.", 360, 2070, 400),
        _t("Every campfire becomes an inn (full heal + upgrade 2 skills).", 940, 1520, 500, 180),
        _t("EXP gain is halved.", 990, 2070, 360),
        left_sign, _t("OR", 722, 2364, 80), right_sign,
    ]
    bodies = vendor_bodies(texts)
    assert bodies is not None
    assert "remove half" in bodies[0].lower()
    assert "shop prices are doubled" in bodies[0].lower()
    assert "becomes an inn" in bodies[1].lower()
    assert "exp gain is halved" in bodies[1].lower()
    assert "this will" not in bodies[0].lower() and "this will" not in bodies[1].lower()
    decision = decide_vendor(bodies[0], bodies[1], 20, rng=random.Random(0))
    # Inn is recognized and still unweighted, so it does not add a score. EXP halved does.
    assert decision.inputs["right"] == -30
    assert decision.inputs["left"] > decision.inputs["right"]
    assert any("inn" in line or "campfire" in line for line in decision.inputs["unknown"])
    # Two fully unknown lines still coin-flip. Weights were not added for them.
    unknown = decide_vendor("Your pets are disabled for the first 3 rounds in every battle.",
                            "The next Mythic skill you learn becomes Trash.", None, rng=random.Random(1))
    assert unknown.inputs["coin_flip"]
    score, _lines = score_vendor_card("EXP gain is halved.", 20)
    assert score == -30
    score, _lines = score_vendor_card("Your first shop purchase is free.", 20)
    assert score == 35
    score, _lines = score_vendor_card(
        "For the next 5 battle encounters, half of your skills are disabled.", 20)
    assert score == -90


def test_vendor_fixture_ocr_includes_the_blessing(ocr):
    img = cv2.imread(str(FIXTURES / "cv_inn_vs_removehalf_half.jpg"))
    assert img is not None
    texts = ocr.read(img)
    sy, sx = 2560 / img.shape[0], 1440 / img.shape[1]
    scaled = [Text(t.text, int(t.x1 * sx), int(t.y1 * sy), int(t.x2 * sx), int(t.y2 * sy)) for t in texts]
    bodies = vendor_bodies(scaled)
    assert bodies is not None
    blob = " ".join(bodies).lower()
    assert "campfire" in blob and "inn" in blob
    assert "exp gain is halved" in blob or "halved" in blob
    assert "remove half" in blob
    assert "this will" not in blob


def test_miner_fixture_sees_the_purple_and_orange_gems_on_the_measured_grid():
    img = cv2.imread(str(FIXTURES / "miner_gems_skipped_half.jpg"))
    assert img is not None
    viewed = read_miner_grid(img)
    assert viewed is not None
    board, centers = viewed
    scale = img.shape[1] / 1440
    step = (centers[0][-1][0] - centers[0][0][0]) / 6
    assert abs(step - config.MINER_COL_STEP * scale) / (config.MINER_COL_STEP * scale) <= config.MINER_STEP_TOLERANCE
    for c, x in enumerate(FALLBACK_MINER_COLS):
        assert abs(centers[0][c][0] - x * scale) <= 40
    assert board[2][4] == GEM  # purple, tall
    assert board[6][2] == GEM  # orange, wide
    assert any(board[r][c] == DUG for r in range(7) for c in range(7))
    # The live miss: columns at x=151 and x=1303 are not the board.
    assert not miner_step_ok([151, 343, 535, 727, 919, 1111, 1303], config.MINER_COL_STEP, 1440, 0)
    assert miner_step_ok(list(FALLBACK_MINER_COLS), config.MINER_COL_STEP, 1440, 0)


def test_battle_board_and_chest_are_not_unknown_events():
    battle = [_t("Round 3/30", 574, 172, 200), _t("25.1m(2.5m)(5.4m)", 890, 668, 300),
              _t("150.9m", 1176, 670, 140), _t("158.2m", 1176, 1154, 140)]
    combo = [_t("Rourdombo!", 772, 190, 200), _t("15.3m(2.5m)(7.7m)", 892, 668, 300),
             _t("61.7m", 1178, 670, 120)]
    assert is_battle(battle) and is_battle(combo)
    assert skip_unknown_save(battle) and skip_unknown_save(combo)
    chest = [_t("You found a Chest!", 718, 336, 400), _t("21.7m/21.7m", 562, 80, 220)]
    assert skip_unknown_save(chest)
    board = [_t("20.4m/20.9m", 562, 78, 240), _t("» x4", 154, 2432, 80), _t("BLACK", 730, 1020, 80)]
    assert is_quiet_map(board) and skip_unknown_save(board)
    img = np.zeros((2560, 1440, 3), np.uint8)
    state = classify_level_screen(img, battle)
    assert state.kind is LevelScreen.FIGHT


def test_hud_rejects_a_max_of_one_and_a_max_below_current():
    assert hp_plausible(9_900_000, 1) is False
    assert hp_plausible(18_600_000, 22_900_000) is True
    assert hp_plausible(100, 50) is False
    from roguebot.screens import parse_hp_ratio
    assert parse_hp_ratio([Text("9.9m/1", 420, 58, 663, 100)]) is None
    assert parse_hp_ratio([Text("18.6m/22.9m", 420, 58, 663, 100)]) == pytest.approx(18.6 / 22.9)


def test_shop_refresh_stops_at_50_and_skips_off_build_commons():
    from roguebot.play import refresh_leaves_a_buy
    from roguebot.skills import Skill
    build = PRESETS["poison"]
    cleave = Skill("Ultimate Cleave", "en", "common", None, "physical", "damage", "A wide swing.")
    venom = Skill("Corrosion", "en", "common", "venom", "physical", "damage",
                  "Deal extra damage for each stack of Poison on them.")
    spark = Skill("Spark", "en", "common", "lightning", "magic", "damage",
                  "Lightning damage on each hit this combat.")
    # Poison is physical venom/bleed/shuriken. Lightning is magic: it conflicts.
    assert shop_order([cleave], build, BuildState(), can_reroll=False, fill=False) == []
    assert shop_order([venom], build, BuildState(), can_reroll=False, fill=False) == [0]
    assert shop_order([spark], build, BuildState(), can_reroll=False, fill=False) == []
    # Fire's neighbor is lightning, same nature, so that common is the exception.
    fire = PRESETS["fire"]
    bolt = Skill("Spark", "en", "common", "lightning", "magic", "damage",
                 "Lightning damage on each hit this combat.")
    assert shop_order([bolt], fire, BuildState(), can_reroll=False, fill=False) == [0]
    assert refresh_leaves_a_buy(200, 50, []) is True
    assert refresh_leaves_a_buy(200, 70, []) is True  # the coin-floor check is separate from the cap
    assert config.SHOP_REFRESH_MAX == 50


def test_faded_names_are_not_saved_and_clean_skills_are_in_the_catalog(tmp_path):
    assert skill_name_rejected("thality", "partial") == "junk"
    assert skill_name_rejected("Weap", "Your basic attacks deal more damage now") == "junk"
    assert skill_name_rejected("Endlesc Fury", "Everytime you use a Weapon Attack gain something faded") == "junk"
    assert name_unreadable("EXP") and name_unreadable("Lv.2") and name_unreadable("HA")
    assert not name_unreadable("Corrosion")
    catalog = Catalog()
    assert catalog.contains("Relentless Flurry")
    assert catalog.contains("Divine Intervention")
    assert catalog.contains("Divine Judgement")
    assert catalog.contains("Eye for an Eye")
    assert catalog.contains("Feral Adaptibility")
    assert catalog.contains("Corrosion")
    assert catalog.contains("Weapon Mastery")
    assert catalog.contains("Trash")
    assert not catalog.contains("Endless Fury")
    assert not catalog.contains("Last Stand")
    assert not catalog.contains("Feral Lethality")
    assert not catalog.contains("Endlesc Fury")
    assert "exp" not in catalog.skills
    fresh = Catalog(tmp_path / "skills.json")
    fresh.lookup("Endlesc Fury", "a faded line", "legendary", "en")
    assert "endlescfury" not in fresh.skills
    fresh.lookup("Corrosion", "Deal +1% increased damage to enemies for each stack of Poison on them.",
                 "common", "en")
    assert "corrosion" in fresh.skills


def test_a_core_skill_and_an_unreadable_name_are_not_rerolled(tmp_path):
    from roguebot.play import Player
    from roguebot.screens import SkillCard

    class Dev:
        def tap(self, *a, **k):
            pass

        def screenshot(self):
            return None

    class NoOcr:
        def read(self, img, region=None):
            return []

    player = Player(Dev(), NoOcr(), PRESETS["poison"], Catalog(tmp_path / "skills.json"))
    set_language("en")
    try:
        tag = _t("Common", 300, 1000, 140)
        core = SkillCard("common", "Corrosion", "Deal extra damage for each stack of Poison.", tag)
        # parse path: the offer is only EXP, which is not a card name, so nothing is rerolled
        exp_only = [_t("Select a Skill to learn!", 720, 800, 500),
                    _t("Common", 300, 1000, 140), _t("EXP", 560, 1040, 80),
                    _t("Reroll", 720, 2155, 160), _t("(1)", 720, 2200, 80)]
        assert player._pick_skill(exp_only) is None
        cards = [
            _t("Select a Skill to learn!", 720, 800, 500),
            _t("Common", 300, 1000, 140),
            _t("Corrosion", 620, 1040, 240),
            _t("Deal extra damage for each stack of Poison on the enemy.", 700, 1120, 500),
            _t("Reroll", 720, 2155, 160), _t("(1)", 720, 2200, 80),
        ]
        point = player._pick_skill(cards)
        assert point is not None and point[1] < 2000  # the card, not the reroll button
        assert core.name == "Corrosion"
    finally:
        set_language(None)


def test_shop_refresh_above_50_is_refused(tmp_path):
    from roguebot.play import Player
    from roguebot.screens import Shop
    from roguebot.vision import Text as T

    class Dev:
        taps = []

        def tap(self, x, y, settle=0):
            self.taps.append((x, y))

    dev = Dev()
    player = Player(dev, None, PRESETS["poison"], Catalog(tmp_path / "skills.json"))
    reroll = T("Reroll", 780, 2365, 930, 2405)
    shop = Shop(200, [], None, T("Exit", 380, 2395, 470, 2440), 70, reroll)
    assert player._refresh_shop(shop, [], False) is False
    assert dev.taps == []
    shop = Shop(200, [], None, shop.exit, 50, reroll)
    assert player._refresh_shop(shop, [], True) is True
    assert dev.taps == [reroll.center]


def test_exp_toast_is_not_a_card_name():
    tag = _t("Legendary", 300, 1000, 140)
    toast = _t("EXP", 500, 1040, 80)
    name = _t("Weapon Mastery", 700, 1040, 280)
    desc = _t("Your Basic Attacks, Combo Attacks and Counter Attacks deal more DMG", 800, 1120, 600)
    cards = parse_skill_cards([tag, toast, name, desc], (80, 720))
    assert len(cards) == 1
    assert cards[0].name == "Weapon Mastery"


def test_star_list_error_uses_the_active_language():
    set_language("en")
    try:
        assert star_challenge_name() == "Star Challenge"
        set_language("es")
        assert star_challenge_name() == "Desafío de Estrellas"
    finally:
        set_language(None)


def test_frames_match_waits_out_a_slide_in():
    from roguebot.play import frames_match
    base = np.zeros((800, 450, 3), np.uint8)
    base[:] = (40, 40, 40)
    same = base.copy()
    same[100:110, 100:110] = (42, 42, 42)  # sparkle
    assert frames_match(base, same)
    slid = base.copy()
    slid[200:500, 80:400] = (180, 160, 90)
    assert not frames_match(base, slid)
    assert not frames_match(None, base)
    assert not frames_match(np.zeros((10, 10, 3), np.uint8), np.zeros((10, 10, 3), np.uint8))
