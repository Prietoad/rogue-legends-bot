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
                             decide_vendor, decide_vista, find_blue_chest, is_battle, is_core_skill, is_path_fork,
                             is_skill_offer, looks_like_event, merge_board, next_miner_tap, ordinary_level_screen,
                             read_hud, read_miner_grid, reward_is_skill, safe_leave_label, safe_option,
                             score_vendor_card, tap_forbidden, unlock_requirement_met, vendor_bodies, vendor_needs_shot)


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
    assert decide_path("elysium", cards, 48, 5).choice == "B"  # rolls left <= 5 and a skill is affordable
    assert decide_path("elysium", cards, 10, 5).choice == "A"  # 10 is under the cheapest skill
    assert decide_path("elysium", cards, 25, 3).choice == "A"
    assert decide_path("elysium", cards, 80, 3, left_shop_tokens=80).choice == "A"
    assert decide_path("elysium", cards, 300, 2, left_shop_tokens=300).choice == "A"
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


def test_unknown_board_takes_the_shop_and_never_the_locked_chest():
    # Ancient Waterway as it was read live: chest text missing, shop on B, tokens 170.
    empty_and_shop = _cards(ca=frozenset(), cb=frozenset({"shop"}))
    assert decide_path(None, empty_and_shop, 170, 29).choice == "B"
    chest_and_shop = _cards(ca=frozenset({"chest"}), cb=frozenset({"shop"}))
    assert decide_path(None, chest_and_shop, 170, 20).choice == "B"
    assert decide_path("ancient waterway", chest_and_shop, 0, 20).choice == "B"
    # Shop on the left, locked chest on the right: still the shop.
    swapped = _cards(ca=frozenset({"shop"}), cb=frozenset({"chest"}))
    assert decide_path(None, swapped, 0, 20).choice == "A"
    assert decide_path(None, swapped, 0, 20).choice != "B"


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
    assert decide_locked_box(True, False).choice == "look_around"  # icon looks tappable; the cost is not met
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
    assert decide_springs(["Stay", "Get Out"], 0.7, 0.1).choice == "stay"  # 60% left after the hit
    assert decide_springs(["Stay", "Get Out"], 0.6, 0.6).choice == "get_out"  # the next stay would empty hp
    assert decide_springs(["Stay", "Get Out"], 0.55, 0.10).choice == "stay"  # 45% left, still at least 40%
    assert decide_springs(["Stay", "Get Out"], 0.50, 0.20).choice == "get_out"  # 30% left
    assert decide_springs(["Stay", "Get Out"], 0.39, 0.05).choice == "get_out"
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
    # The panel is the lower part of the frame. Tiles up by the speech bubble are not the grid.
    y0, x0, step, size = 300, 40, 40, 32
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


def test_cursed_vendor_v4_early_picks_the_right_card():
    """Early run, the user's pick was the right Sign.

    Left: debuff tiles become buffs, and lose 5% max HP after each battle.
    Right: elites start at 25% less HP, and a 50% chance to trip.
    The max-HP curse is heavy while more than 5 rolls remain, and cheap once they do not.
    """
    left = ("All debuff tiles are replaced with buff tiles for the rest of the run. "
            "Lose 5% Max HP after each battle")
    right = ("Elite enemies and bosses start combat with 25% less HP. "
             "50% chance to trip and take damage instead of Basic Attacking")
    early = decide_vendor(left, right, 20)
    assert early.choice == "right"
    assert early.inputs["left_parsed"] and early.inputs["right_parsed"]
    assert not vendor_needs_shot(early)
    late = decide_vendor(left, right, 5)
    assert late.choice == "left"  # the max-HP curse is cheap with 5 rolls left
    assert decide_vendor(left, right, None).choice == "right"  # rolls unreadable: treat the curse as heavy
    blank = decide_vendor("", "", None)
    assert not blank.inputs["left_parsed"] and vendor_needs_shot(blank)


def test_vendor_reads_the_lines_above_each_sign():
    texts = [
        Text("Cursed Vendor", 500, 900, 940, 980),
        Text("All debuff tiles are replaced with buff tiles for the rest of the run.", 280, 1400, 680, 1520),
        Text("Lose 5% Max HP after each battle", 280, 1600, 680, 1680),
        Text("Sign", 360, 1900, 560, 1980),
        Text("Elite enemies and bosses start combat with 25% less HP.", 860, 1400, 1280, 1520),
        Text("50% chance to trip and take damage instead of Basic Attacking", 860, 1600, 1280, 1680),
        Text("Sign", 960, 1900, 1160, 1980),
    ]
    left, right = vendor_bodies(texts)
    assert "debuff" in left.lower() and "max hp" in left.lower()
    assert "25%" in right and "trip" in right.lower()
    assert "Sign" not in left and "Sign" not in right
    assert decide_vendor(left, right, 20).choice == "right"


def test_locked_box_looks_around_when_a_key_or_gems_are_required():
    assert unlock_requirement_met("Needs a key to open", Hud()) is False
    assert unlock_requirement_met("Costs 50 gems", Hud(tokens=400)) is False
    assert unlock_requirement_met("Spend 80 tokens", Hud(tokens=80)) is True
    assert unlock_requirement_met("Spend 80 tokens", Hud(tokens=79)) is False
    assert unlock_requirement_met("Open the box", Hud()) is None
    assert decide_locked_box(True, unlock_requirement_met("You found a key", Hud())).choice == "look_around"


def test_battles_skill_picks_and_path_forks_are_not_unknown_events():
    battle = [Text("Round 1/30", 560, 80, 880, 130), Text("VIP", 40, 2240, 160, 2300),
              Text("x4", 70, 2320, 150, 2380)]
    assert is_battle(battle) and not looks_like_event(battle)
    skill = [Text("LEVEL UP!", 520, 700, 920, 780),
             Text("Select a Skill to learn!", 420, 820, 1020, 880),
             Text("Common", 140, 980, 280, 1030), Text("Round Bolt", 400, 980, 800, 1040),
             Text("Common", 140, 1280, 280, 1330), Text("Enraged Recovery", 400, 1280, 900, 1340),
             Text("Reroll (1)", 560, 1900, 880, 1980)]
    assert is_skill_offer(skill) and ordinary_level_screen(skill)
    assert not looks_like_event(skill)
    power = [Text("POWER UP!", 500, 700, 940, 780), Text("Select a Skill to learn!", 400, 820, 1040, 880),
             Text("Common", 160, 1000, 300, 1060), Text("Lightning Weapon", 400, 1000, 900, 1060)]
    assert is_skill_offer(power)
    fork = [Text("Path A", 360, 2200, 560, 2280), Text("000", 400, 1900, 520, 1960),
            Text("Path B", 900, 2200, 1100, 2280), Text("SHOP", 940, 1860, 1080, 1920)]
    assert is_path_fork(fork) and not looks_like_event(fork)
    # The speed button is not a leave option, and a blind fallback must not land on it.
    assert tap_forbidden((111, 2307))
    assert safe_leave_label(battle) is None
    assert safe_leave_label(skill) is None
    leave = safe_leave_label([Text("Walk Away", 400, 1800, 700, 1880),
                              Text("Pay 50 gems", 900, 1800, 1200, 1880)])
    assert leave is not None and leave.text == "Walk Away"
    from roguebot.screens import LevelScreen, classify_level_screen
    img = np.zeros((2560, 1440, 3), np.uint8)
    fight = classify_level_screen(img, battle)
    assert fight.kind is LevelScreen.FIGHT and fight.tap is None
    picked = classify_level_screen(img, skill)
    assert picked.kind is LevelScreen.SKILL_PICK
    # Round Bolt's center is not where a blind event tap used to land, and not the speed button.
    assert picked.tap is not None and picked.tap[0] > 400
    forked = classify_level_screen(img, fork)
    assert forked.kind is LevelScreen.EVENT and forked.tap == (1000, 2240)


def test_two_option_events_tap_the_button_under_the_title():
    """The name sits at y≈1790 and does nothing. The icon button is ~240 px lower."""
    from roguebot.screens import LevelScreen, classify_level_screen
    from roguebot.world2 import choice_tap, match_event, recovery_taps
    img = np.zeros((2560, 1440, 3), np.uint8)
    observe = Text("Observe", 430, 1763, 590, 1823)  # center (510, 1793), the live miss
    steal = Text("Steal", 840, 1764, 1010, 1824)
    texts = [Text("Two Fight, the Third Benefits", 360, 1480, 1080, 1560),
             Text("You witness a Goblin and a Skeleton fighting over a magical scroll.", 200, 1620, 1240, 1680),
             observe, steal,
             Text("Learn a Common Skill", 300, 2200, 720, 2280),
             Text("Learn a Legendary Skill", 780, 2140, 1120, 2200),
             Text("Lose -25% Max HP", 800, 2220, 1100, 2280)]
    assert match_event(texts) == "two_fight"
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.EVENT
    assert abs(state.tap[0] - 510) < 30
    assert state.tap[1] > 1950 and abs(state.tap[1] - 1793) > 80
    assert choice_tap(observe, texts)[1] == observe.center[1] + 238
    # The title tap did nothing: the next tries are the button, then the caption.
    alts = recovery_taps(texts, observe.center)
    assert alts and alts[0][1] > 1950
    assert any(abs(p[1] - 2240) < 40 for p in alts)


def test_another_deal_with_the_devil_leaves_on_the_button():
    from roguebot.screens import LevelScreen, classify_level_screen
    from roguebot.world2 import match_event
    img = np.zeros((2560, 1440, 3), np.uint8)
    leave = Text("Leave", 840, 1764, 1006, 1824)  # (923, 1794) was the live miss
    texts = [Text("Another Deal with the Devil", 340, 1460, 1100, 1540),
             Text('The mischievous dark imp appears before you once more: "Sign again, again!"',
                  160, 1600, 1280, 1680),
             Text("Sign", 400, 1760, 620, 1828), leave,
             Text("Learn 1 Legendary Skill", 280, 2140, 740, 2200),
             Text("Forget 2 Common Skills", 280, 2220, 740, 2280),
             Text("Walk Away", 800, 2220, 1050, 2300)]
    assert match_event(texts) == "devil"
    state = classify_level_screen(img, texts)  # skill list unreadable: leave
    assert state.kind is LevelScreen.EVENT
    assert abs(state.tap[0] - leave.center[0]) < 30
    assert state.tap[1] > 1950


def test_roll_tracker_remembers_the_map_and_a_dice_roll():
    from roguebot.world2 import RollTracker, read_hud
    rolls = RollTracker()
    assert rolls.cached() is None
    board = [Text("2/30", 40, 900, 90, 980), Text("18.5m/18.5m", 400, 40, 700, 80)]
    assert rolls.observe(board)
    assert rolls.cached() == (2, 30)
    event = [Text("Haunting Spirits", 500, 1360, 940, 1440)]
    assert not rolls.observe(event)
    assert read_hud(event).rolls_used is None
    assert rolls.cached() == (2, 30)  # the event hides the counter; the last map value stands
    rolls.note_roll()
    assert rolls.cached() == (3, 30)
    assert rolls.observe([Text("2/30", 40, 900, 90, 980)])  # the pre-roll frame is ignored once
    assert rolls.cached() == (3, 30)
    assert rolls.observe([Text("4/30", 40, 900, 90, 980)])
    assert rolls.cached() == (4, 30)
    rolls.reset()
    assert rolls.cached() is None


def test_stat_toast_elite_banner_and_chest_are_not_unknown_events():
    from roguebot.world2 import is_shop_screen, looks_like_event, transient_kind
    toast = [Text("Max HP -4%", 520, 900, 920, 980), Text("Tap To Stop", 560, 2100, 880, 2160),
             Text("Max HP +10%", 520, 980, 920, 1040)]
    assert transient_kind(toast) == "toast" and not looks_like_event(toast)
    minus = [Text("Max HP -10%", 500, 880, 940, 960)]
    assert transient_kind(minus) == "toast"
    banner = [Text("Elite Enemy", 520, 360, 920, 440), Text("Incoming", 560, 460, 880, 530)]
    assert transient_kind(banner) == "banner" and not looks_like_event(banner)
    chest = [Text("You found a Chest!", 480, 300, 960, 380), Text("Tap anywhere to open!", 480, 2080, 960, 2160)]
    assert transient_kind(chest) == "chest" and not looks_like_event(chest)
    assert not is_shop_screen(toast) and not is_shop_screen(chest)


def test_haunting_shop_and_chest_screenshots(ocr):
    from pathlib import Path
    from conftest import fixture_image
    from roguebot.screens import LevelScreen, classify_level_screen, parse_shop
    from roguebot.world2 import is_shop_screen, looks_like_event, match_event, transient_kind
    root = Path(__file__).parent / "fixtures"

    haunt = fixture_image(root / "w2_haunting_spirits.png")
    texts = ocr.read(haunt)
    assert match_event(texts) == "haunting"
    ignored = classify_level_screen(haunt, texts)  # no counter on this screen: ignore
    assert ignored.kind is LevelScreen.EVENT
    assert abs(ignored.tap[0] - 924) <= 40 and ignored.tap[1] > 1980
    embraced = classify_level_screen(haunt, texts, rolls=(8, 30))
    assert embraced.tap[0] < 700 and embraced.tap[1] > 1980
    late = classify_level_screen(haunt, texts, rolls=(12, 30))
    assert late.tap[0] > 800

    for name, money, prices in (
            ("w2_shop.png", 233, {48, 190, 95}),
            ("w2_shop_enraged.png", 505, {48, 95})):
        img = fixture_image(root / name)
        shop_texts = ocr.read(img)
        assert is_shop_screen(shop_texts) and not looks_like_event(shop_texts)
        state = classify_level_screen(img, shop_texts)
        assert state.kind is LevelScreen.SHOP and state.tap is not None and state.tap[1] > 2300
        shop = parse_shop(shop_texts)
        assert shop is not None and shop.money == money and shop.free_reroll is not None
        assert {c.cost for c in shop.cards} == prices
        assert shop.cards and all(c.name for c in shop.cards)

    chest_img = fixture_image(root / "w2_chest.png")
    chest_texts = ocr.read(chest_img)
    assert transient_kind(chest_texts) == "chest" and not looks_like_event(chest_texts)
    opened = classify_level_screen(chest_img, chest_texts)
    assert opened.kind is LevelScreen.CONTINUE and opened.tap[1] > 2000


def test_stuck_guard_tries_the_button_and_the_caption(monkeypatch):
    import numpy as np
    from roguebot import play
    from roguebot.screens import LevelScreen, LevelState
    clock = iter(range(0, 5000))
    monkeypatch.setattr(play.time, "monotonic", lambda: next(clock) * 0.05)
    monkeypatch.setattr(play.time, "sleep", lambda s: None)
    title = (924, 1800)
    states = iter([LevelState(LevelScreen.EVENT, title)] * 4 + [LevelState(LevelScreen.VICTORY, (720, 2200))])
    monkeypatch.setattr(play, "classify_level_screen", lambda *args, **kwargs: next(states))
    texts = [Text("Haunting Spirits", 500, 1360, 940, 1440),
             Text("Ignore", 844, 1770, 1004, 1830),
             Text("Walk Away", 800, 2230, 1050, 2310),
             Text("Embrace", 400, 1740, 620, 1800),
             Text("Darkness", 400, 1800, 620, 1840),
             Text("Lose -40% Max HP", 360, 2200, 680, 2280)]

    class Dev:
        taps = []

        def screenshot(self):
            return np.zeros((10, 10, 3), np.uint8)

        def tap(self, x, y, settle=0):
            Dev.taps.append((x, y))

    class Read:
        def read(self, img):
            return texts

    player = play.Player(Dev(), Read())
    monkeypatch.setattr(player, "_save_unknown", lambda *args, **kwargs: None)
    assert player.play_level() is LevelScreen.VICTORY
    ys = [y for _x, y in Dev.taps if _x > 800]
    assert title[1] in ys  # the title was tried
    assert any(y > 1980 for y in ys)  # then the button or the caption, not an endless wait
