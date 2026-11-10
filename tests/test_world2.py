"""World 2 decision rules. Pure: HUD numbers and OCR text in, a choice out."""

import numpy as np

from roguebot.build import PRESETS, Build
from roguebot.config import SHOP_SKILL_FLOOR
from roguebot.skills import DAMAGE_TYPES
from roguebot.vision import Text
from roguebot.world2 import (DUG, GEM, UNK, Hud, KnownSkill, PathCard, active_build, board_from_title,
                             decide_anvil, decide_book, decide_cart, decide_chaos, decide_devil, decide_goblin,
                             decide_haunting, decide_herb, decide_kidnapped, decide_locked_box, decide_minigame_taxi,
                             decide_path, decide_shop_taxi, decide_slime, decide_springs, decide_statue, decide_two_fight,
                             decide_vendor, decide_vista, find_blue_chest, is_core_skill, merge_board, next_miner_tap,
                             read_hud, read_miner_grid, reward_is_skill, safe_option, score_vendor_card)


MINER = 7


def _blank(n=MINER):
    return [[UNK for _ in range(n)] for _ in range(n)]


def test_world_ids_and_board_names():
    assert board_from_title("2-1. Elysium I") == "elysium"
    assert board_from_title("2-2. Ancient Waterway I") == "ancient waterway"
    assert board_from_title("2-3. Molten Core I") == "molten core"
    assert board_from_title("1. Atlantis I") == "atlantis"
    assert board_from_title("13. Bosque Embrujado II") is None


def test_hud_reads_hp_tokens_and_rolls_and_ignores_energy():
    texts = [Text("20,8m / 20.8m", 400, 40, 700, 80), Text("275", 40, 160, 120, 200),
             Text("12/32", 760, 40, 900, 80), Text("2/30", 40, 900, 90, 980)]
    hud = read_hud(texts)
    assert hud.hp == 20.8e6 and hud.max_hp == 20.8e6
    assert hud.tokens == 275 and hud.rolls_used == 2 and hud.rolls_left == 28
    assert read_hud([Text("107,2k/152,5k", 420, 58, 663, 100)]).hp_ratio == 107.2 / 152.5


def test_core_skill_uses_the_active_preset_not_a_hardcoded_poison():
    poison, fire = PRESETS["poison"], PRESETS["fire"]
    assert is_core_skill("Poison Strike Lv.2", poison) is True
    assert is_core_skill("Poison Strike Lv.2", fire) is False
    assert is_core_skill("Heal Shuriken", poison) is False
    assert is_core_skill("", poison) is None
    assert is_core_skill(None, poison) is None
    custom = active_build(Build(), {"preset": "custom", "damage_order": list(DAMAGE_TYPES), "nature": "physical"})
    assert is_core_skill("Poison Strike", custom) is True
    assert active_build(fire, {"preset": "poison"}).order == poison.order
    assert active_build(fire, {}) is fire


def _cards(a="A", b="B", ca=frozenset(), cb=frozenset()):
    return [PathCard(a, ca, a, (400, 2200)), PathCard(b, cb, b, (1000, 2200))]


def test_elysium_path():
    cards = _cards(ca=frozenset({"statue"}), cb=frozenset({"shop"}))
    assert decide_path("elysium", cards, 300, 20).choice == "B"
    assert decide_path("elysium", cards, 10, 5).choice == "B"  # rolls left <= 5 and tokens remain
    assert decide_path("elysium", cards, 0, 5).choice == "A"
    assert decide_path("elysium", cards, 100, 20).choice == "A"
    assert decide_path("elysium", cards, None, None).choice == "A"  # unreadable
    assert decide_path("elysium", cards, 10, None).choice == "A"


def test_waterway_is_always_the_anvil_shop_and_molten_has_no_choice():
    cards = _cards(ca=frozenset({"chest"}), cb=frozenset({"anvil", "shop"}))
    assert decide_path("ancient waterway", cards, 0, 20).choice == "B"
    assert decide_path("molten core", cards, 999, 1).choice is None


def test_atlantis_path_and_content_fallback_ignores_the_letter():
    # Letters swapped on purpose: content, not the letter, decides an unknown board.
    cards = _cards("A", "B", frozenset({"campfire"}), frozenset({"shop"}))
    assert decide_path("atlantis", cards, 300, 20).choice == "B"  # the shop, wherever it sits
    assert decide_path("atlantis", cards, 100, 20).choice == "A"  # campfire is the default
    assert decide_path("atlantis", cards, SHOP_SKILL_FLOOR, 5).choice == "B"  # last chance, a skill is affordable
    assert decide_path("atlantis", cards, SHOP_SKILL_FLOOR - 1, 3).choice == "A"
    assert decide_path("atlantis", cards, None, 2).choice == "A"  # tokens unreadable: default campfire
    assert decide_path(None, cards, 300, 20).choice == "B"  # board unknown: still the shop
    assert decide_path(None, _cards(), None, None).choice is None


def test_statue_prays_on_a_core_skill_and_offers_a_weak_one():
    poison = PRESETS["poison"]
    assert decide_statue("Poison Strike Lv.2", poison).choice == "pray"
    assert decide_statue("Heal Shuriken", poison).choice == "offering"
    assert decide_statue("Lacerate", poison).choice == "offering"
    assert decide_statue(None, poison).choice == "pray"
    assert decide_statue("Poison Strike", PRESETS["fire"]).choice == "offering"


def test_cursed_vendor_matches_the_two_playtest_picks():
    early_left, _ = score_vendor_card("All shops become black markets\nEXP halved", 20)
    early_right, _ = score_vendor_card("Elites/bosses -25% HP\nAll campfires are removed", 20)
    assert early_left > early_right
    assert decide_vendor("All shops become black markets. EXP halved",
                         "Elites/bosses -25% HP. All campfires are removed", 20).choice == "left"
    late_left, _ = score_vendor_card("Remove half of the enemy tiles on the board\nAll campfires are removed", 3)
    late_right, _ = score_vendor_card("Skill rerolls refresh on every skill selection\nEnemies will always act first", 3)
    assert late_left > late_right
    assert decide_vendor("Remove half of the enemy tiles\nAll campfires are removed",
                         "Skill rerolls refresh on every skill selection\nEnemies will always act first",
                         3).choice == "left"
    _score, unknown = score_vendor_card("Gain 500 Shop Tokens\nA curse nobody has written down", None)
    assert unknown and "nobody" in unknown[0].lower()


def test_simple_event_rules_and_their_unreadable_fallbacks():
    assert decide_herb().choice == "make_tea"
    assert decide_slime(75).choice == "indulge" and decide_slime(74).choice == "refuse"
    assert decide_slime(None).choice == "refuse"
    assert decide_minigame_taxi(75).choice == "taxi" and decide_minigame_taxi(74).choice == "no_thanks"
    assert decide_minigame_taxi(None).choice == "no_thanks"
    assert decide_shop_taxi(300).choice == "travel" and decide_shop_taxi(299).choice == "no_thanks"
    assert decide_shop_taxi(None).choice == "no_thanks"
    assert decide_locked_box(False).choice == "look_around" and decide_locked_box(None).choice == "look_around"
    assert decide_locked_box(True).choice == "unlock"
    assert decide_kidnapped(True).choice == "pay" and decide_kidnapped(False).choice == "escape"
    assert decide_kidnapped(None).choice == "escape"
    assert decide_chaos().choice == "refuse" and decide_two_fight().choice == "observe"
    assert decide_anvil().choice == "take" and decide_cart().choice == "some"
    assert decide_haunting(10).choice == "embrace" and decide_haunting(11).choice == "ignore"
    assert decide_haunting(None).choice == "ignore"
    assert decide_goblin(0.51).choice == "raid" and decide_goblin(0.50).choice == "sneak"
    assert decide_goblin(None).choice == "sneak"


def test_devil_signs_only_for_two_commons_that_are_not_both_core():
    poison = PRESETS["poison"]
    weak = [KnownSkill("Heal Shuriken", "common"), KnownSkill("Lacerate", "common")]
    both = [KnownSkill("Poison Strike", "common"), KnownSkill("Bleed Dart", "common")]
    assert decide_devil(weak, poison).choice == "sign"
    assert decide_devil(both, poison).choice == "leave"
    assert decide_devil(weak + [KnownSkill("Extra", "common")], poison).choice == "leave"
    assert decide_devil(None, poison).choice == "leave"


def test_springs_vista_and_book():
    assert decide_springs(["Enter Hot Spring"], 0.9, None).choice == "enter"
    assert decide_springs(["Stay", "Get Out"], 0.7, 0.1).choice == "stay"
    assert decide_springs(["Stay", "Get Out"], 0.6, 0.6).choice == "get_out"  # the next stay would empty hp
    assert decide_springs(["Stay", "Get Out"], 0.59, 0.05).choice == "get_out"
    assert decide_springs(["Stay", "Get Out"], None, 0.1).choice == "get_out"
    assert decide_springs(["Stay", "Get Out"], 0.8, None).choice == "get_out"
    assert decide_vista(5, 2).choice == "gaze"
    assert decide_vista(6, 2).choice == "resist" and decide_vista(5, 3).choice == "resist"
    assert decide_vista(None, 1).choice == "resist" and decide_vista(1, None).choice == "resist"
    assert reward_is_skill("Enraged Strength") and not reward_is_skill("+5% ATK/DEF/Max HP")
    assert decide_book("Enraged Strength").choice == "read"
    assert decide_book("+5% ATK").choice == "work_out" and decide_book(None).choice == "work_out"


def test_safe_option_prefers_leave_then_a_free_choice():
    assert safe_option([("Eat It", "lose 10% hp"), ("Walk Away", "")]) == 1
    assert safe_option([("Pay 75 tokens", "75 tokens"), ("Look Around", "+1 key")]) == 1
    assert safe_option([("Pay 100", "100 tokens"), ("Pay 40", "40 tokens")]) == 1


def test_treasure_miner_finishes_a_partial_gem_then_hunts_and_skips_dug_tiles():
    board = _blank()
    assert next_miner_tap(board, 9) == (0, 0)  # stride, spread out
    assert next_miner_tap(board, 0) is None
    board[3][3] = GEM
    assert next_miner_tap(board, 9) in {(2, 3), (4, 3), (3, 2), (3, 4)}
    line = _blank()
    for c in range(4):
        line[0][c] = GEM
    assert next_miner_tap(line, 9) != (0, 1)  # the finished 1x4 is not dug again
    assert next_miner_tap(line, 9)[0] != 0 or next_miner_tap(line, 9)[1] not in range(4)
    vertical = _blank()
    for r in range(4):
        vertical[r][6] = GEM
    hunt = next_miner_tap(vertical, 9)
    assert (hunt[0], hunt[1]) not in {(r, 6) for r in range(4)}
    rect = _blank()
    for r in range(2):
        for c in range(3):
            rect[r][c] = GEM
    assert all(next_miner_tap(rect, 9) != (r, c) for r in range(2) for c in range(3))
    forced = _blank()
    forced[0][0] = forced[0][1] = forced[0][2] = GEM
    for cell in ((1, 0), (1, 1), (1, 2), (0, 4)):
        r, c = cell
        # block every completion except extending the line to (0, 3)
    for r in range(1, 7):
        forced[r][0] = forced[r][1] = forced[r][2] = DUG
    forced[1][3] = DUG
    assert next_miner_tap(forced, 9) == (0, 3)
    later = merge_board(forced, _blank())
    assert later[0][0] == GEM and later[1][0] == DUG


def test_miner_grid_reader_on_a_drawn_board_and_the_blue_chest():
    img = np.zeros((700, 520, 3), np.uint8)
    img[:] = (30, 30, 30)
    # The reader looks at the middle of the frame. Keep every tile inside that band.
    y0, x0, step, size = 140, 50, 56, 46
    for r in range(7):
        for c in range(7):
            x, y = x0 + c * step, y0 + r * step
            color = (150, 150, 155)
            if r == 0 and c < 4:
                color = (40, 180, 40)
            elif r == 6 and c == 6:
                color = (20, 20, 20)
            cv2_rect(img, x, y, size, color)
    viewed = read_miner_grid(img)
    assert viewed is not None
    board, centers = viewed
    assert board[0][0] == GEM and board[6][6] == DUG and board[3][3] == UNK
    assert centers[0][0] != centers[6][6]
    chest = np.zeros((400, 400, 3), np.uint8)
    chest[150:230, 160:250] = (220, 40, 30)
    found = find_blue_chest(chest)
    assert found is not None and 160 < found[0] < 250 and 150 < found[1] < 230


def cv2_rect(img, x, y, size, color):
    """A tile with a light rim so a dark interior still has an edge the grid reader can see."""
    img[y:y + size, x:x + size] = (230, 230, 230)
    img[y + 4:y + size - 4, x + 4:x + size - 4] = color


def test_classify_makes_tea_and_leaves_the_campfire_alone():
    from roguebot.screens import LevelScreen, classify_level_screen
    img = np.zeros((2560, 1440, 3), np.uint8)
    tea = Text("Make Tea", 250, 1760, 520, 1820)
    eat = Text("Eat It", 860, 1760, 1100, 1820)
    texts = [Text("The Mysterious Herb", 420, 1360, 1020, 1440), tea, eat,
             Text("Upgrade a Random Skill", 200, 2100, 560, 2160),
             Text("Replace a random skill", 800, 2100, 1200, 2160)]
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.EVENT
    assert state.tap[0] == tea.center[0]
    assert state.tap[0] != eat.center[0]
    # Campfire still upgrades at full HP. The herb rule must not steal it.
    heal = Text("Descansar", 300, 1760, 560, 1820)
    train = Text("Entrenar", 860, 1760, 1100, 1820)
    camp = [Text("Un momento de descanso", 400, 1360, 1040, 1440),
            Text("150k/200k", 420, 40, 700, 80), heal, train,
            Text("Restaura 30% de HP", 250, 2140, 600, 2200),
            Text("Mejora 1 habilidad existente", 800, 2140, 1200, 2200)]
    camped = classify_level_screen(img, camp)
    assert camped.tap[0] == train.center[0]
