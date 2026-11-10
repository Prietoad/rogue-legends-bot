"""2.0.3: cursed vendor lines, miner grid, known screens, boons, captures, coin flip, Elysium."""

import random
from pathlib import Path

import cv2
import numpy as np

from roguebot.build import PRESETS
from roguebot.config import SHOP_SKILL_FLOOR
from roguebot.play import capture_once, load_seen
from roguebot.screens import LevelScreen, classify_level_screen
from roguebot.vision import Text
from roguebot.world2 import (DUG, GEM, UNK, blank_miner, boon_sort_key, choose_boon, clean_card_name,
                             clean_vendor_text, coin_flip_applies, coin_flip_labels, coin_flip_temporary,
                             count_pickaxes, decide_path, decide_vendor, fallback_miner_centers, known_screen,
                             next_unopened, read_miner_grid, score_vendor_card, tile_changed, vendor_needs_shot)

FIXTURES = Path(__file__).parent / "fixtures"
LINES = FIXTURES / "w2_203"


def _lines(name: str) -> list[Text]:
    raw = (LINES / name).read_text(encoding="utf-8").splitlines()
    return [Text(s, 200, 80 + i * 36, 900, 110 + i * 36) for i, s in enumerate(raw) if s.strip()]


def test_vendor_new_lines_score_and_the_header_is_not_unknown():
    left = "Cursed Vendor Gain 500 Shop Tokens. Lose 5% Max HP after each battle"
    right = ("Cursed Vendor CURSES FOR A PRICE Create a golden road of mega buff tiles. "
             "Shop prices are doubled.")
    decision = decide_vendor(left, right, 29)
    assert decision.choice == "right"
    assert decision.inputs["left"] < decision.inputs["right"]
    assert not decision.inputs["unknown"]
    assert not vendor_needs_shot(decision)
    assert "cursed vendor" not in decision.inputs["right_text"]
    assert "golden road" in decision.inputs["right_text"]
    # The mild curse still wins when the blessing on that card was not read.
    late = decide_vendor("0 Lose 5% Max HP after each battle", "0 0 Shop prices are doubled.", 29)
    assert late.choice == "right"
    assert not late.inputs["unknown"]
    assert clean_vendor_text("0 Shop prices are doubled") == "shop prices are doubled"
    _score, unknown = score_vendor_card("Shop prices are doubled", None)
    assert not unknown


def test_vendor_unknown_tie_is_a_logged_coin_flip(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="roguebot.world2"):
        decision = decide_vendor("A curse nobody has written down today",
                                 "Another curse nobody has written down", None,
                                 rng=random.Random(0))
    assert decision.choice in ("left", "right")
    assert decision.inputs["coin_flip"]
    assert "COIN FLIP (temporary): options" in caplog.text
    assert "-> picked" in caplog.text


def test_vendor_choice_taps_the_matching_sign_even_with_junk():
    """Unknown-looking OCR used to score a side and then not tap, because 'right' is not a button name."""
    img = np.zeros((2560, 1440, 3), np.uint8)
    left_sign = Text("Sign", 300, 1900, 520, 1980)
    right_sign = Text("Sign", 900, 1900, 1120, 1980)
    texts = [
        Text("Cursed Vendor", 500, 900, 940, 980),
        Text("CURSES FOR A PRICE", 700, 1040, 1100, 1100),
        Text("Gain 500 Shop Tokens.", 240, 1400, 680, 1480),
        Text("Lose 5% Max HP after each battle", 240, 1560, 680, 1640),
        Text("Create a golden road of mega buff tiles.", 820, 1360, 1280, 1500),
        Text("0 Shop prices are doubled.", 820, 1580, 1280, 1660),
        left_sign, Text("OR", 680, 1900, 760, 1980), right_sign,
    ]
    state = classify_level_screen(img, texts, rolls=(1, 30))
    assert state.kind is LevelScreen.EVENT
    assert abs(state.tap[0] - right_sign.center[0]) < 40
    assert state.tap[0] != left_sign.center[0]


def test_miner_grid_on_the_half_capture_is_the_board_not_the_speech_bubble():
    img = cv2.imread(str(FIXTURES / "w2_treasure_miner_half.jpg"))
    assert img is not None and img.shape[0] == 1280
    viewed = read_miner_grid(img)
    assert viewed is not None
    board, centers = viewed
    # Half of the measured 1440x2560 centers. The old reader tapped the bubble near y=266.
    expect_x = [round(v / 2) for v in (285, 434, 583, 732, 881, 1030, 1179)]
    expect_y = [round(v / 2) for v in (1107, 1252, 1397, 1542, 1687, 1832, 1979)]
    for c, x in enumerate(expect_x):
        assert abs(centers[0][c][0] - x) <= 30
    for r, y in enumerate(expect_y):
        assert abs(centers[r][0][1] - y) <= 30
        assert centers[r][0][1] > 480
    gems = [(r, c) for r in range(7) for c in range(7) if board[r][c] == GEM]
    dug = [(r, c) for r in range(7) for c in range(7) if board[r][c] == DUG]
    assert gems and dug and len(gems) < 15
    icons = count_pickaxes(img, centers)
    assert icons == 9


def test_miner_fallback_and_a_miss_tries_a_different_tile():
    centers = fallback_miner_centers()
    assert centers[0][0] == (285, 1107)
    assert centers[0][1] == (434, 1107)
    assert centers[6][6] == (1179, 1979)
    assert centers[1][0][1] - centers[0][0][1] == 145
    board = blank_miner()
    assert next_unopened(board, set()) == (0, 0)
    skipped = next_unopened(board, {(0, 0)})
    assert skipped != (0, 0)
    assert skipped is not None
    # Nothing unopened: there is still no Leave to invent.
    full = [[DUG for _ in range(7)] for _ in range(7)]
    assert next_unopened(full, set()) is None
    assert tile_changed((80, 120, 170), (80, 120, 170)) is False
    assert tile_changed((80, 120, 170), (10, 10, 10)) is True
    assert read_miner_grid(np.zeros((2560, 1440, 3), np.uint8)) is None


def test_miner_screen_is_not_a_coin_flip():
    texts = _lines("20261109_213443_treasure_miner.txt")
    assert not coin_flip_applies(texts)
    from roguebot.world2 import is_miner
    assert is_miner(texts)


def test_known_screens_from_the_2_0_2_captures():
    claim = (
        "20261109_205934_you_received.txt",
        "20261109_212402_you_received.txt",
        "20261109_212411_you_forgot.txt",
        "20261109_210636_ucky_treasure.txt",
        "20261109_211347_you_received.txt",
    )
    for name in claim:
        assert known_screen(_lines(name)) == "claim", name
    victory = (
        "20261109_210738_you_survived.txt",
        "20261109_210740_chapter_10.txt",
        "20261109_212006_you_survived.txt",
        "20261109_212008_longest_journey.txt",
        "20261109_213729_you_survived.txt",
    )
    for name in victory:
        assert known_screen(_lines(name)) == "victory", name
    assert known_screen(_lines("20261109_205913_after_event.txt")) == "battle"
    for name in ("20261109_211611_current_reward.txt", "20261109_211624_after_event.txt",
                 "20261109_211630_dice_battle.txt"):
        kind = known_screen(_lines(name))
        assert kind in ("dice", "claim"), name
    assert not coin_flip_applies(_lines("20261109_211611_current_reward.txt"))
    assert not coin_flip_applies(_lines("20261109_210740_chapter_10.txt"))


def test_battle_line_with_a_wave_is_a_fight():
    img = np.zeros((2560, 1440, 3), np.uint8)
    texts = [Text("Round 10/30 Wave 3/3", 400, 80, 1100, 140), Text("VIP", 40, 2240, 160, 2300)]
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.FIGHT
    assert state.tap is None


def test_boon_rank_prefers_poison_then_attack_and_cleans_the_name():
    poison = "Feral poison. Damage over time is doubled."
    attack = "Gain 20% ATK and crit."
    shield = "Max HP up and a shield."
    gold = "Gain gold and a reroll."
    assert boon_sort_key("A", poison) < boon_sort_key("B", attack)
    assert boon_sort_key("B", attack) < boon_sort_key("C", shield)
    assert boon_sort_key("C", shield) < boon_sort_key("D", gold)
    offers = [("Shield", shield), ("Gold", gold), ("Poison", poison)]
    assert choose_boon(offers, PRESETS["poison"]) == 2
    # Same tier, the line that says damage wins over a bare attack word that does not.
    assert choose_boon([("Flat", "ATK up"), ("Hit", "damage and crit")], PRESETS["poison"]) == 1
    tied = choose_boon([("Alpha", "a mystery boon of no stat"), ("Beta", "another mystery boon")],
                       PRESETS["poison"], rng=random.Random(1))
    assert tied in (0, 1)
    assert clean_card_name("0 Feral Adaptibility") == "Feral Adaptibility"
    assert clean_card_name("eraLLethality") == "eraLLethality"


def test_coin_flip_drops_prices_and_the_vip_badge(caplog):
    import logging
    texts = [
        Text("Strange Crossroads", 500, 900, 1000, 980),
        Text("Buy 50 gems", 300, 1800, 560, 1880),
        Text("Purchase", 800, 1800, 1100, 1880),
        Text("Give Up", 300, 2100, 560, 2180),
        Text("Ponder", 800, 2000, 1100, 2080),
        Text("60", 200, 2260, 320, 2340),  # gem price sitting on the VIP badge
    ]
    labels = coin_flip_labels(texts)
    assert [name for name, _point in labels] == ["Ponder"]
    assert coin_flip_applies(texts)
    with caplog.at_level(logging.INFO, logger="roguebot.world2"):
        assert coin_flip_temporary(["Ponder", "Wait"], rng=random.Random(2)) in ("Ponder", "Wait")
    assert "COIN FLIP (temporary): options ['Ponder', 'Wait'] -> picked" in caplog.text
    # Dismiss popups are not a purchase.
    center = __import__("roguebot.world2", fromlist=["dismiss_point"]).dismiss_point(
        [Text("Tap anywhere to claim", 400, 2200, 1000, 2280)])
    assert center == (720, 1280)


def test_capture_is_once_per_key_across_a_fresh_seen_file(tmp_path):
    img = np.zeros((20, 20, 3), np.uint8)
    seen = load_seen(tmp_path)
    assert capture_once(tmp_path, "feraladaptibility", img, "name: Feral\nrarity: legendary\n", seen, sync=True)
    assert not capture_once(tmp_path, "feraladaptibility", img, "again", seen, sync=True)
    again = load_seen(tmp_path)
    assert "feraladaptibility" in again
    assert not capture_once(tmp_path, "feraladaptibility", img, "third", again, sync=True)
    written = list(tmp_path.glob("*.txt"))
    assert len(written) == 2  # seen.txt plus the one capture
    body = next(p for p in written if p.name != "seen.txt").read_text(encoding="utf-8")
    assert "Feral" in body and "legendary" in body


def test_elysium_late_shop_needs_a_skill_price():
    from roguebot.world2 import PathCard
    cards = [PathCard("A", frozenset({"statue"}), "A", (400, 2200)),
             PathCard("B", frozenset({"shop"}), "B", (1000, 2200))]
    assert SHOP_SKILL_FLOOR == 48
    assert decide_path("elysium", cards, 47, 3).choice == "A"
    assert decide_path("elysium", cards, 48, 3).choice == "B"
    assert decide_path("atlantis", cards, 48, 5).choice == "B"  # unchanged last-shop rule
    assert decide_path("ancient waterway", cards, 0, 20).choice == "B"
