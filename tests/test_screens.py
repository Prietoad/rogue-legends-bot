"""Screen recognition against real screenshots in tests/fixtures (no device needed)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

import logging

from roguebot import config, labels
from roguebot.screens import (LevelScreen, Mode, classify_level_screen, close_button, footer_visible, game_speed, is_loading, is_star_list, parse_elite_dialog,
                              parse_energy, parse_energy_popup, parse_hp_ratio, parse_lobby, parse_star_list, popup_close,
                              star_challenge_button)
from roguebot.vision import Text, normalize, parse_level_number
from conftest import fixture_image

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    labels.set_language(None)


def fixture_language(name: str) -> str:
    return "en" if name.startswith("en_") else "es"


def load(ocr, name):
    """Screenshot + OCR, with only the fixture's own language active (en_* = English, else Spanish)."""
    labels.set_language(fixture_language(name))
    img = fixture_image(FIXTURES / name)
    return img, ocr.read(img)


def test_parse_level_number():
    assert parse_level_number("12. Arenas Movedizas II") == 12
    assert parse_level_number("4.") == 4
    assert parse_level_number("Temporada 22") is None
    # World 2 lobby "2-N. Name" and the star list's chapter-local "N. Name" are the same id.
    assert parse_level_number("2-1. Elysium I") == 1
    assert parse_level_number("2-3. Molten Core I") == 3
    assert parse_level_number("1. Elysium I") == 1
    assert parse_level_number("Unlock by completing the chapter.") is None


def test_normalize():
    assert normalize("Desafío de Estrellas") == "desafio de estrellas"


@pytest.mark.parametrize("name, mode, title", [
    ("lobby_normal.png", Mode.NORMAL, "13. Bosque Embrujado II"),
    ("lobby_elite.png", Mode.ELITE, "2. Las Tierras Altas (Élite) I"),
])
def test_lobby(ocr, name, mode, title):
    _, texts = load(ocr, name)
    lobby = parse_lobby(texts)
    assert lobby is not None
    assert lobby.mode == mode
    assert lobby.level_title == title
    assert not is_star_list(texts)


@pytest.mark.parametrize("name, playable, locked", [
    ("stars_normal_top.png", [1, 2, 3], []),
    ("stars_normal_end.png", [11, 12], [13]),
    ("stars_elite.png", [1], [2]),
])
def test_star_list(ocr, name, playable, locked):
    img, texts = load(ocr, name)
    assert is_star_list(texts)
    assert parse_lobby(texts) is None
    cards = parse_star_list(img, texts, ocr)
    assert [c.number for c in cards if c.button] == playable
    for n in locked:
        assert any(c.number == n and c.button is None for c in cards)


@pytest.mark.parametrize("name, kind, tap", [
    ("level_skill_levelup.png", LevelScreen.SKILL_PICK, (720, 1052)),
    ("level_skill_power.png", LevelScreen.SKILL_PICK, (720, 1103)),
    ("level_fight.png", LevelScreen.FIGHT, None),
    ("level_board_ready.png", LevelScreen.BOARD_READY, (720, 2150)),
    ("board.png", LevelScreen.BOARD_READY, (720, 2150)),
    ("level_board_rolling.png", LevelScreen.UNKNOWN, None),
    ("level_board_auto.png", LevelScreen.AUTO_PLAY, None),          # green dice "Toca para Detener" right after the hold
    ("level_board_auto_rolling.png", LevelScreen.AUTO_PLAY, None),  # auto-play mid-level: never tap (it would stop it)
    ("level_event_cart.png", LevelScreen.EVENT, (923, 2030)),    # "Salir" option
    ("level_event_rest.png", LevelScreen.EVENT, (924, 2032)),    # HP 107.2/152.5k >= 40%: "Entrenar", not "Descansar"
    ("en_board_dice_unknown.png", LevelScreen.BOARD_READY, (720, 2150)),  # dark teal board: not a footer
    ("en_level_event_disabled_option.png", LevelScreen.EVENT, (922, 2033)),  # "Read" greyed after failing: "Walk Away"
    ("level_shop.png", LevelScreen.SHOP, (427, 2417)),
    ("level_shop_2.png", LevelScreen.SHOP, (427, 2417)),     # skill rows fall in the event bands
    ("level_lucky_wheel.png", LevelScreen.CONTINUE, (718, 2149)),
    ("level_monk_wheel.png", LevelScreen.MONK, (721, 2281)),
    ("level_monk_done.png", LevelScreen.MONK, (720, 2279)),
    ("level_dice_duel.png", LevelScreen.DICE_DUEL, (1016, 2367)),  # score 0: roll
    ("level_reward_claim.png", LevelScreen.CONTINUE, (717, 2349)),
    ("level_defeat.png", LevelScreen.DEFEAT, (720, 2221)),
    ("level_victory.png", LevelScreen.VICTORY, (720, 2220)),
    ("dive_defeat.png", LevelScreen.DEFEAT, (720, 2144)),  # Dungeon Dive: "DERROTA" + "Confirmar"
    ("level_event_result.png", LevelScreen.CONTINUE, (719, 2462)),
    ("level_flip_cards.png", LevelScreen.FLIP_CARDS, (299, 1280)),
    ("level_flip_cards_one_up.png", LevelScreen.FLIP_CARDS, (579, 1280)),  # skips the flipped card
    ("en_level_skill_levelup.png", LevelScreen.SKILL_PICK, (720, 1053)),
    ("en_level_modifiers.png", LevelScreen.CONTINUE, (719, 1930)),  # elite level intro
    ("level_fortune_teller.png", LevelScreen.FORTUNE_TELLER, (293, 2280)),  # "Adivino"; Player picks the ball
    ("level_fortune_teller_won.png", LevelScreen.CONTINUE, (717, 2349)),  # "Recibiste" + skill: tap to claim
    ("en_level_fight.png", LevelScreen.FIGHT, None),  # "Round 4/30"
    ("level_dice_duel_won.png", LevelScreen.CONTINUE, (480, 2366)),  # RECLAMAR, not "Desafiar de Nuevo"
    ("level_revive.png", LevelScreen.REVIVE, (993, 1454)),
    ("en_level_skill_power_resurrection.png", LevelScreen.SKILL_PICK, (720, 1054)),  # "Revive after..." card  # "Gratis" video, never the 60-gem button
    ("level_revive_last_second.png", LevelScreen.REVIVE, (993, 1454)),
    ("en_level_shop.png", LevelScreen.SHOP, (428, 2417)),
    ("en_level_fortune_teller.png", LevelScreen.FORTUNE_TELLER, (293, 2280)),
    ("en_level_event_result.png", LevelScreen.CONTINUE, (720, 2461)),
    ("en_level_chest.png", LevelScreen.CONTINUE, (717, 2123)),
    ("en_level_monk_wheel.png", LevelScreen.MONK, (720, 2281)),
    ("en_level_victory_x2.png", LevelScreen.DOUBLE_REWARD, (1018, 2222)),
    ("en_level_flip_cards.png", LevelScreen.FLIP_CARDS, (299, 1280)),
    ("en_level_dice_duel.png", LevelScreen.DICE_DUEL, (1014, 2368)),
    ("en_level_dice_duel_lost.png", LevelScreen.LEAVE, (718, 2378)),
    ("en_level_lucky_wheel.png", LevelScreen.CONTINUE, (719, 2148)),
    ("en_level_dice_duel_won.png", LevelScreen.CONTINUE, (479, 2366)),
])
def test_level_screens(ocr, name, kind, tap):
    img, texts = load(ocr, name)
    state = classify_level_screen(img, texts)
    assert state.kind == kind
    if tap is None:
        assert state.tap is None
    else:
        assert abs(state.tap[0] - tap[0]) <= 15 and abs(state.tap[1] - tap[1]) <= 15


def _replace_hp(texts, hp: str | None):
    """Swap the top-bar heart line. None drops it. The heal option's "39% de HP" stays."""
    out = []
    for t in texts:
        top = t.center[1] <= config.TOP_BAR_MAX_Y and "/" in t.norm and "k" in t.norm
        if not top:
            out.append(t)
        elif hp is not None:
            out.append(Text(hp, t.x1, t.y1, t.x2, t.y2))
    return out


def test_hp_ratio_reads_the_heart_line_not_the_heal_amount():
    assert parse_hp_ratio([Text("39% de HP", 369, 2303, 653, 2363)]) is None
    ratio = parse_hp_ratio([Text("107,2k/152,5k", 420, 58, 663, 100), Text("39% de HP", 369, 2303, 653, 2363)])
    assert ratio == pytest.approx(107.2 / 152.5)
    assert parse_hp_ratio([Text("12/32", 820, 70, 890, 100)]) is None  # energy, no k/m/b


def test_campfire_restores_hp_only_under_40_percent(ocr):
    img, texts = load(ocr, "level_event_rest.png")
    low = classify_level_screen(img, _replace_hp(texts, "50k/152,5k"))  # 32.8%
    assert low.kind is LevelScreen.EVENT
    assert abs(low.tap[0] - 510) <= 15 and abs(low.tap[1] - 2033) <= 15  # Descansar
    exact = classify_level_screen(img, _replace_hp(texts, "61k/152,5k"))  # 40.0%: not under
    assert abs(exact.tap[0] - 924) <= 15  # Entrenar


def test_campfire_upgrades_when_hp_is_unreadable(ocr, caplog):
    """The "39% de HP" under Descansar is the heal amount. Missing heart line → upgrade, and say so."""
    img, texts = load(ocr, "level_event_rest.png")
    with caplog.at_level(logging.INFO, logger="roguebot.screens"):
        state = classify_level_screen(img, _replace_hp(texts, None))
    assert abs(state.tap[0] - 924) <= 15 and abs(state.tap[1] - 2032) <= 15
    assert "HP unreadable" in caplog.text


def test_campfire_at_full_hp_does_not_heal_when_the_upgrade_is_missing(caplog):
    """The frame after a skill pick can show only Descansar. That is not a heal at 100% HP."""
    img = np.zeros((2560, 1440, 3), np.uint8)
    heal = Text("Descansar", 400, 1760, 620, 1820)
    texts = [Text("Un momento de descanso", 500, 1360, 940, 1440),
             Text("150k/200k", 420, 58, 663, 100), heal,
             Text("Restaura", 400, 2240, 620, 2300), Text("30% de HP", 400, 2300, 620, 2360)]
    with caplog.at_level(logging.INFO, logger="roguebot.screens"):
        state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.EVENT and state.tap is None
    assert "not healing" in caplog.text
    low = [Text("40k/200k", 420, 58, 663, 100) if t.text.startswith("150k") else t for t in texts]
    healed = classify_level_screen(img, low)  # 20%: the heart is the right tap
    assert healed.tap[0] == heal.center[0]


def test_campfire_fallback_is_the_other_column_not_the_heart():
    from roguebot.screens import campfire_non_heal_tap
    heal = Text("Descansar", 400, 1760, 620, 1820)
    texts = [Text("Un momento de descanso", 500, 1360, 940, 1440), heal]
    tap = campfire_non_heal_tap(np.zeros((2560, 1440, 3), np.uint8), texts)
    assert tap[0] == config.SCREEN_SIZE[0] - heal.center[0]
    assert tap[0] != heal.center[0]


def test_campfire_english_bodies_pick_the_upgrade_without_rest_or_train_labels():
    """No English fixture: match restore/heal HP and upgrade/improve skill, not guessed button words."""
    img = np.zeros((2560, 1440, 3), np.uint8)
    heal = Text("Recover", 349, 1762, 671, 1828)
    upgrade = Text("Study", 790, 1762, 1058, 1827)
    texts = [Text("A short rest", 400, 1360, 1040, 1440), Text("150k/200k", 420, 58, 663, 100),
             heal, upgrade, Text("Restore", 385, 2240, 640, 2299), Text("30% HP", 369, 2303, 653, 2363),
             Text("Upgrade 1", 801, 2237, 1051, 2308), Text("existing skill", 793, 2304, 1056, 2361)]
    high = classify_level_screen(img, texts)
    assert high.tap == (upgrade.center[0], upgrade.center[1] + config.EVENT_ICON_BELOW_LABEL)
    low = [Text("40k/200k", 420, 58, 663, 100) if t.text.startswith("150k") else t for t in texts]
    healed = classify_level_screen(img, low)  # 20%
    assert healed.tap[0] == heal.center[0]


@pytest.mark.parametrize("name", ["lobby_promo_popup.png", "lobby_roulette_popup.png", "en_lobby_spin_popup.png",
                                  "lobby_limited_offer_popup.png"])
def test_lobby_popups(ocr, name):
    _, texts = load(ocr, name)
    close = popup_close(texts)
    assert close is not None
    assert close.center[1] > 2300  # bottom "Toca ... para cerrar", never a purchase button
    assert parse_lobby(texts) is None


@pytest.mark.parametrize("name", ["lobby_normal.png", "lobby_elite.png"])
def test_lobby_has_no_popup(ocr, name):
    _, texts = load(ocr, name)
    assert popup_close(texts) is None


@pytest.mark.parametrize("name, cost", [("elite_dialog_x5.png", 5), ("elite_dialog_x15.png", 15)])
def test_elite_dialog(ocr, name, cost):
    _, texts = load(ocr, name)
    dialog = parse_elite_dialog(texts)
    assert dialog is not None
    assert dialog.cost == cost
    assert parse_energy(texts) == 12


def test_elite_dialog_absent_in_lobby(ocr):
    _, texts = load(ocr, "lobby_elite.png")
    assert parse_elite_dialog(texts) is None
    assert parse_energy(texts) == 13


def test_loading(ocr):
    _, texts = load(ocr, "loading.png")
    assert is_loading(texts)
    assert parse_lobby(texts) is None
    _, texts = load(ocr, "lobby_normal.png")
    assert not is_loading(texts)


@pytest.mark.parametrize("name, speed", [
    ("level_speed_x1.png", 1),
    ("level_board_ready.png", 2),
    ("level_fight.png", 2),
    ("lobby_normal.png", None),
])
def test_game_speed(ocr, name, speed):
    _, texts = load(ocr, name)
    assert game_speed(texts) == speed


def test_world2_fight_skill_and_path_screenshots(ocr):
    """Live 1440x2560 frames. A fight waits, a skill offer is a skill pick, the fork takes the shop."""
    from roguebot import world2
    img, texts = load(ocr, "w2_round_1_30.png")
    labels.set_language("en")
    assert world2.is_battle(texts)
    assert classify_level_screen(img, texts).kind is LevelScreen.FIGHT
    assert classify_level_screen(img, texts).tap is None
    assert game_speed(texts) == 4
    img, texts = load(ocr, "w2_skill_power_up.png")
    labels.set_language("en")
    assert world2.is_skill_offer(texts)
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.SKILL_PICK
    assert state.tap is None or state.tap[0] > 400
    img, texts = load(ocr, "w2_path_fork.png")
    labels.set_language("en")
    assert world2.is_path_fork(texts)
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.EVENT
    assert state.tap is not None and state.tap[0] > 700  # Path B, the shop, not the locked chest


@pytest.mark.parametrize("name", ["lobby_normal.png", "level_skill_levelup.png", "level_board_ready.png"])
def test_recognition_from_1080x1920(ocr, name):
    """A 1080x1920 device: Device.screenshot() upscales its frames to the reference size."""
    img = cv2.imread(str(FIXTURES / name))
    small = cv2.resize(img, (1080, 1920), interpolation=cv2.INTER_AREA)
    restored = cv2.resize(small, (1440, 2560), interpolation=cv2.INTER_CUBIC)
    expected = classify_level_screen(img, ocr.read(img))
    got = classify_level_screen(restored, ocr.read(restored))
    assert got.kind == expected.kind
    assert (parse_lobby(ocr.read(restored)) is None) == (parse_lobby(ocr.read(img)) is None)


@pytest.mark.parametrize("score, label", [(0, "tirar"), (14, "tirar"), (15, "resistir"), (20, "resistir")])
def test_dice_duel_policy(score, label):
    from roguebot.vision import Text
    texts = [Text(f"Yo {score} / 21", 600, 1960, 800, 2010),
             Text("RESISTIR", 450, 2340, 620, 2390), Text("TIRAR", 940, 2340, 1090, 2390)]
    state = classify_level_screen(np.zeros((2560, 1440, 3), np.uint8), texts)
    assert state.kind == LevelScreen.DICE_DUEL
    assert state.tap == next(t.center for t in texts if t.norm == label)


# --- English UI -------------------------------------------------------------------------

@pytest.mark.parametrize("name, mode, level", [
    ("en_lobby_normal.png", Mode.NORMAL, 13),
    ("en_lobby_elite.png", Mode.ELITE, 2),
])
def test_lobby_english(ocr, name, mode, level):
    _, texts = load(ocr, name)
    lobby = parse_lobby(texts)
    assert lobby is not None
    assert lobby.mode == mode
    assert parse_level_number(lobby.level_title) == level
    assert not is_star_list(texts)
    # "Star Challenge" OCRs as "Star"/"i-Star" plus "Challenge", in the row above Start.
    assert lobby.stars_button is not None and lobby.stars_button.norm == "challenge"
    assert 150 < lobby.start_button.center[1] - lobby.stars_button.center[1] < 220


def test_star_challenge_ignores_boss_rush_and_other_event_tiles(ocr):
    """A featured Boss Rush / Wish Challenge tile also says "Challenge" or "Rush", higher on the
    lobby than Star Challenge. The control to open is the one just above Start."""
    _, texts = load(ocr, "en_lobby_normal.png")
    events = [
        Text("Boss Rush", 1100, 980, 1380, 1060),
        Text("Challenge", 560, 1180, 860, 1240),          # the event banner's button
        Text("Wish Challenge", 1180, 1400, 1420, 1460),
        Text("Chest Rush", 1280, 1560, 1420, 1620),
        Text("Egg Rush", 1280, 1580, 1420, 1640),
    ]
    lobby = parse_lobby(texts + events)
    assert lobby.stars_button.norm == "challenge"
    assert lobby.stars_button.center[1] > 1900            # the row above Start, not the banner
    # The banner button alone, with no "Star" line, is not Star Challenge.
    start = next(t for t in texts if t.norm == "start")
    assert star_challenge_button(events + [start, Text("Patrol", 659, 1903, 775, 1943)], start) is None


@pytest.mark.parametrize("name", ["lobby_normal.png", "lobby_elite.png"])
def test_spanish_star_challenge_is_de_estrellas_above_start(ocr, name):
    _, texts = load(ocr, name)
    lobby = parse_lobby(texts)
    assert lobby.stars_button.norm == "de estrellas"
    assert lobby.stars_button.center[1] < lobby.start_button.center[1]


@pytest.mark.parametrize("name", ["elite_dialog_x5.png", "en_elite_dialog_x5.png"])
def test_elite_dialog_does_not_take_the_dimmed_star_label_behind_it(ocr, name):
    """The dialog's own Start is not the lobby Start, so the label showing through is not the button."""
    _, texts = load(ocr, name)
    assert parse_lobby(texts).stars_button is None


@pytest.mark.parametrize("name, playable, locked", [
    ("en_stars_normal_end.png", [11, 12], [13]),
    ("en_stars_elite.png", [1], [2]),
])
def test_star_list_english(ocr, name, playable, locked):
    img, texts = load(ocr, name)
    assert is_star_list(texts)
    assert parse_lobby(texts) is None
    cards = parse_star_list(img, texts, ocr)
    assert [c.number for c in cards if c.button] == playable
    for n in locked:
        assert any(c.number == n and c.button is None for c in cards)


def test_elite_dialog_english(ocr):
    _, texts = load(ocr, "en_elite_dialog_x5.png")
    dialog = parse_elite_dialog(texts)
    assert dialog is not None and dialog.cost == 5
    assert parse_energy(texts) == 24


def test_energy_popup_free_options(ocr):
    img, texts = load(ocr, "en_energy_popup.png")
    offers = parse_energy_popup(img, texts)
    assert offers is not None
    assert offers.free_pack is not None and offers.free_pack.norm == "free"
    x, y = offers.video
    assert abs(x - 490) < 20 and abs(y - 1392) < 20   # yellow video button, left column
    assert x < 720                                      # never the gem-priced button (right column)
    assert offers.videos_left == 3


def test_energy_popup_no_video_when_chances_used(ocr):
    img, texts = load(ocr, "en_energy_popup.png")
    texts = [Text(t.text.replace("3", "0"), t.x1, t.y1, t.x2, t.y2) if "Chances" in t.text else t
             for t in texts]
    assert parse_energy_popup(img, texts).video is None


def test_energy_popup_ignores_non_yellow_button(ocr):
    img, texts = load(ocr, "en_energy_popup.png")
    grey = img.copy()
    grey[1300:1480, 300:680] = 120  # video button area no longer yellow
    offers = parse_energy_popup(grey, texts)
    assert offers.video is None
    assert offers.videos_left == 3  # e.g. a cooldown after a video: chances still left (the bot re-reads)


def test_energy_reward_over_the_popup_is_found(ocr):
    """The Daily Pack reward banner covers the video button: it is claimed before reading the popup."""
    from roguebot import labels as L
    from roguebot.vision import find
    _, texts = load(ocr, "energy_popup_pack_reward.png")
    assert find(texts, L.TAP_TO_CLAIM).center[1] > 2250


def test_energy_popup_absent_in_lobby(ocr):
    img, texts = load(ocr, "en_lobby_normal.png")
    assert parse_energy_popup(img, texts) is None
    assert parse_lobby(texts).energy == 24


def test_victory_without_double_button_continues(ocr):
    img, texts = load(ocr, "en_level_victory_x2.png")
    texts = [t for t in texts if "rewards" not in t.norm]  # same screen once the ad was watched
    state = classify_level_screen(img, texts)
    assert state.kind == LevelScreen.VICTORY
    assert abs(state.tap[0] - 473) < 15 and abs(state.tap[1] - 2220) < 15  # "Continue"


@pytest.mark.parametrize("name, x_at", [
    ("en_lobby_daily_login.png", (720, 2072)),
    ("en_energy_popup.png", (720, 1947)),
    ("en_elite_dialog_x5.png", (720, 2025)),
    ("elite_dialog_x5.png", (720, 2025)),
    ("lobby_normal.png", None),
    ("en_lobby_elite.png", None),
    ("stars_normal_end.png", None),
    ("level_board_ready.png", None),
    ("lobby_roulette_popup.png", None),   # closed by its "para cerrar" text instead
])
def test_close_button(name, x_at):
    img = cv2.imread(str(FIXTURES / name))
    found = close_button(img)
    if x_at is None:
        assert found is None
    else:
        assert abs(found[0] - x_at[0]) <= 3 and abs(found[1] - x_at[1]) <= 3


@pytest.mark.parametrize("name, visible", [
    ("lobby_normal.png", True), ("lobby_elite.png", True), ("en_lobby_normal.png", True),
    ("en_lobby_elite.png", True),
    ("pets_tab.png", True),  # Mascotas tab selected: its own tab color changes, the other four stay
    ("en_board_dice_unknown.png", False),  # dark teal level board
    ("en_lobby_daily_login.png", False), ("en_energy_popup.png", False), ("lobby_promo_popup.png", False),
    ("lobby_roulette_popup.png", False), ("elite_dialog_x5.png", False),
    ("stars_normal_end.png", False), ("level_board_ready.png", False), ("level_victory.png", False),
])
def test_footer_visible(name, visible):
    assert footer_visible(cv2.imread(str(FIXTURES / name))) is visible


def test_energy_popup_daily_pack_already_claimed(ocr):
    img, texts = load(ocr, "en_energy_popup_pack_claimed.png")
    offers = parse_energy_popup(img, texts)
    assert offers.free_pack is None     # "Refresh in: ..." timer: already taken today
    assert offers.video is not None     # videos still available (3 chances, OCR reads "Todav")



@pytest.mark.parametrize("name, lang", [
    ("lobby_normal.png", "es"), ("lobby_elite.png", "es"),
    ("en_lobby_normal.png", "en"), ("en_lobby_elite.png", "en"),
    ("level_board_ready.png", None),  # not a lobby: unknown
])
def test_detect_language(ocr, name, lang):
    _, texts = load(ocr, name)
    labels.set_language(None)
    assert labels.detect_language(texts) == lang


@pytest.mark.parametrize("name, wrong", [("lobby_normal.png", "en"), ("en_lobby_normal.png", "es")])
def test_other_language_labels_are_not_used(ocr, name, wrong):
    _, texts = load(ocr, name)
    labels.set_language(wrong)
    assert parse_lobby(texts) is None


@pytest.mark.parametrize("name", ["elite_dialog_x5.png", "en_elite_dialog_x5.png"])
def test_elite_dialog_modifiers_are_not_the_level_intro(ocr, name):
    """The elite start dialog also lists "Level Modifiers", but its button is INICIO/START (spends energy)."""
    img, texts = load(ocr, name)
    assert classify_level_screen(img, texts).kind is not LevelScreen.CONTINUE


def test_revive_never_taps_a_non_yellow_button(ocr):
    """If "Gratis" is not on the yellow video button (e.g. a changed layout), wait instead of tapping."""
    img, texts = load(ocr, "level_revive.png")
    img = img.copy()
    img[1380:1530, 750:1120] = (60, 200, 150)  # repaint the video button green, like the gem one
    assert classify_level_screen(img, texts).kind is LevelScreen.UNKNOWN


def test_energy_popup_spanish(ocr):
    """Spanish puts the count under "Intentos Restantes Hoy:"; the Daily Pack shows "Se actualiza en" once taken."""
    img, texts = load(ocr, "energy_popup_pack_claimed.png")
    offers = parse_energy_popup(img, texts)
    assert offers is not None
    assert offers.free_pack is None
    assert offers.video is not None and abs(offers.video[0] - 488) < 10  # yellow video button, not the gem one


@pytest.mark.parametrize("name", ["lobby_normal.png", "lobby_elite.png", "en_lobby_normal.png", "en_lobby_elite.png"])
def test_lobby_is_never_a_level_screen(ocr, name):
    """Lobby texts can fall in the event bands; with the footer visible it is never a level screen."""
    img, texts = load(ocr, name)
    assert classify_level_screen(img, texts).kind is LevelScreen.UNKNOWN


def test_energy_popup_spanish_no_videos_left(ocr):
    """All video chances used ("Intentos Restantes Hoy: 0"); the gem button still has 1 but is never offered."""
    img, texts = load(ocr, "energy_popup_no_videos.png")
    offers = parse_energy_popup(img, texts)
    assert offers is not None and offers.free_pack is None and offers.video is None


def test_lobby_under_the_album_popup_is_not_the_lobby(ocr):
    """New chapter unlocked: "Colección del Álbum" popup over the lobby, closed via its text."""
    _, texts = load(ocr, "lobby_album_popup.png")
    assert parse_lobby(texts) is None
    assert popup_close(texts)


def test_tutorial_hand_points_at_the_new_album_button(ocr):
    from roguebot.screens import tutorial_hand
    img, texts = load(ocr, "lobby_tutorial_hand.png")  # the game ignores every other tap meanwhile
    x, y = tutorial_hand(img)
    album = next(t for t in texts if "lbum" in t.text and t.center[0] > 1200)
    assert abs(x - album.center[0]) < 60 and abs(y - album.center[1]) < 110


@pytest.mark.parametrize("name", ["lobby_album_popup.png", "lobby_vip_icon.png", "level_revive.png", "level_defeat.png",
                                  "en_modes_list.png", "vip_cards.png", "guild_map.png"])
def test_no_tutorial_hand(name):
    from roguebot.screens import tutorial_hand
    assert tutorial_hand(cv2.imread(str(FIXTURES / name))) is None


@pytest.mark.parametrize("name, target", [
    ("en_equip_tutorial_hand.png", (1093, 1213)),   # the Heroes tab under the fingertip ring (tapped live)
    ("en_heroes_tutorial_hand.png", (867, 1021)),   # the Companions "+" slot
])
def test_tutorial_hand_on_other_screens(name, target):
    from roguebot.screens import tutorial_hand
    x, y = tutorial_hand(cv2.imread(str(FIXTURES / name)))
    assert abs(x - target[0]) < 40 and abs(y - target[1]) < 40


def test_resume_adventure_prompt(ocr):
    from roguebot.screens import resume_prompt
    _, texts = load(ocr, "en_lobby_resume_adventure.png")  # over the lobby, after the game was closed mid-level
    ok = resume_prompt(texts)
    assert ok and ok.norm == "ok" and ok.center[0] > 720  # OK, never "Abandon" (left)
    _, lobby = load(ocr, "en_lobby_normal.png")
    assert resume_prompt(lobby) is None


def test_resume_adventure_prompt_spanish(ocr):
    """"¿Continuar la aventura?" + Abandonar / Confirmar (the game was killed mid-level, seen 2026-10-16)."""
    from roguebot.screens import resume_prompt
    _, texts = load(ocr, "lobby_resume_adventure.png")
    ok = resume_prompt(texts)
    assert ok and ok.norm == "confirmar" and ok.center[0] > 720  # never "Abandonar" (left)
    assert parse_lobby(texts) is None  # the lobby under the dialog is not usable


def test_greyed_event_option_is_skipped_even_without_a_leave_option(ocr):
    """Forbidden Knowledge: after a failed "Read" the option is greyed and taps do nothing."""
    img, texts = load(ocr, "en_level_event_disabled_option.png")
    texts = [t for t in texts if t.text != "Walk Away"] + [Text("Run", 880, 1770, 960, 1815)]  # not a leave label
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.EVENT and abs(state.tap[0] - 920) < 10  # the enabled one, not "Read"


def test_game_update_required(ocr):
    from roguebot.screens import update_required
    _, texts = load(ocr, "game_update_required.png")  # "Nueva Actualización" + ACTUALIZAR at game start
    assert update_required(texts)
    _, lobby = load(ocr, "lobby_vip_icon.png")
    assert not update_required(lobby)


def test_black_market_is_left_without_buying(ocr):
    """Review: the black market label is a guess and its prices may be gems: never treat it as a shop."""
    from roguebot.screens import parse_shop
    img, texts = load(ocr, "level_shop.png")
    texts = texts + [Text("Mercado Negro", 520, 300, 920, 350)]
    assert parse_shop(texts) is None
    state = classify_level_screen(img, texts)
    assert state.kind is LevelScreen.LEAVE


def test_labels_are_normalized_once():
    from roguebot import labels as L
    assert L._l("Desafío", ("Élite", "x")).es == ("desafio",)
    assert L._l("Desafío", ("Élite", "x")).en == ("elite", "x")


def test_star_list_cards_know_their_stars(ocr):
    """Level 12 misses ">65% HP" (2 gold stars), 13 has all 3, 14 is locked."""
    img, texts = load(ocr, "stars_pending.png")
    cards = {c.number: c for c in parse_star_list(img, texts, ocr)}
    assert cards[12].stars == 2 and cards[12].button
    assert cards[13].stars == 3
    assert cards[14].button is None


def test_header_below_the_icons_is_not_read_as_zero_stars(ocr):
    """The cream body under the title bar matches the empty-star colour. It is not 0/3."""
    from roguebot.screens import header_stars
    from roguebot.vision import Text
    img, texts = load(ocr, "stars_pending.png")
    card = next(c for c in parse_star_list(img, texts, ocr) if c.number == 13)
    h = card.header
    shifted = Text(h.text, h.x1, h.y1 + 36, h.x2, h.y2 + 36)
    stars, known = header_stars(img, shifted)
    assert not (known and stars == 0)
    assert stars == 3
    far = Text(h.text, h.x1, h.y1 + 220, h.x2, h.y2 + 220)
    stars, known = header_stars(img, far)
    assert not (known and stars == 0)
    # A false 0/3 is corrected by the objective rows on the real list.
    from roguebot.screens import _with_objectives
    card12 = next(c for c in parse_star_list(img, texts, ocr) if c.number == 12)
    fixed, known = _with_objectives(img, texts, card.header, card.button.center[1], 0, True)
    assert known and fixed == 3
    fixed, known = _with_objectives(img, texts, card12.header, card12.button.center[1], 0, True)
    assert known and fixed == 2


def _mount_star_crop(name: str, card_top: int, card_bottom: int):
    """Place one card from a ground-truth crop onto the 1440x2560 star layout.

    The crop is a phone-sized picture of the cards. Scale it so the title-bar stars
    land on STAR_ICONS_X, which is where the bot samples a full screenshot.
    """
    crop = cv2.imread(str(FIXTURES / name))
    card = crop[card_top:card_bottom]
    b, g, r = [card.astype(int)[..., i] for i in range(3)]
    purple = (b > 160) & (r > 120) & (g < 140) & (b > g + 40)
    band = purple[:70]
    cols = np.where(band.any(0))[0]
    cols = cols[cols > card.shape[1] * 0.7]
    groups, start, prev = [], int(cols[0]), int(cols[0])
    for x in cols[1:]:
        if x > prev + 6:
            groups.append((start, prev))
            start = int(x)
        prev = int(x)
    groups.append((start, int(prev)))
    centers = [(a + c) // 2 for a, c in groups]
    scale = (config.STAR_ICONS_X[1] - config.STAR_ICONS_X[0]) / (centers[1] - centers[0])
    resized = cv2.resize(card, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    canvas = np.zeros((2560, 1440, 3), np.uint8)
    header_y = 700
    star_y = int(np.where(band.any(1))[0].mean() * scale)
    y0 = header_y - star_y
    x0 = config.STAR_ICONS_X[0] - int(centers[0] * scale)
    canvas[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
    return canvas, header_y


def _check_rows(img, top, bottom):
    from roguebot.screens import _green_check
    found, y = [], top
    while y < bottom:
        if _green_check(img, y):
            found.append(y)
            y += 36
        else:
            y += 3
    return found


def test_purple_title_stars_and_green_checks_tell_3_of_3_from_2_of_3():
    """Levels 68-70 are 3/3. Level 47 is 2/3: two purple stars, one pale, and no check on the last row."""
    from roguebot.screens import _with_objectives, header_stars
    from roguebot.vision import Text
    full, y = _mount_star_crop("stars_elite_68_70.png", 0, 290)
    header = Text("68. Shifting Sands", 80, y - 20, 700, y + 20)
    stars, known = header_stars(full, header)
    assert known and stars == 3
    checks = _check_rows(full, y + 20, y + 520)
    assert len(checks) == 3  # one green check on every objective
    rows = [Text("objective", 360, cy - 16, 900, cy + 16) for cy in checks]
    stars, known = _with_objectives(full, rows, header, checks[-1] + 80, 0, True)
    assert known and stars == 3  # three checks override a false 0/3
    miss, y = _mount_star_crop("stars_elite_47.png", 0, 287)
    header = Text("47. Shifting Sands", 80, y - 20, 700, y + 20)
    stars, known = header_stars(miss, header)
    assert known and stars == 2  # two purple stars and one pale star in the title bar
    checks = _check_rows(miss, y + 20, y + 500)
    assert len(checks) == 2  # the last objective has a pale star and no green check


@pytest.mark.parametrize("name, number", [
    ("en_stars_normal_end.png", 10),
    ("stars_normal_end.png", 10),
    ("stars_pending.png", 11),
])
def test_clipped_card_above_the_list_still_misses_a_star(ocr, name, number):
    """The list opens on the last beaten level. The card above it is cut off: its header
    (and the header stars) are off screen, but a grey condition star and Start are visible."""
    from roguebot.screens import clipped_star_card
    img, texts = load(ocr, name)
    cards = parse_star_list(img, texts, ocr)
    clip = clipped_star_card(img, texts, cards)
    assert clip is not None and clip.number == number and clip.stars < 3 and clip.button
    assert clip.number == min(c.number for c in cards) - 1


def test_the_top_of_the_star_list_has_no_clipped_card(ocr):
    from roguebot.screens import clipped_star_card
    img, texts = load(ocr, "stars_normal_top.png")
    cards = parse_star_list(img, texts, ocr)
    assert clipped_star_card(img, texts, cards) is None


def test_dive_victory_okay_and_tap_to_continue_are_dismissed():
    import numpy as np
    from roguebot.screens import LevelScreen, classify_level_screen
    img = np.zeros((2560, 1440, 3), np.uint8)
    okay = classify_level_screen(img, [Text("VICTORY!", 560, 900, 880, 980), Text("Okay", 600, 2100, 840, 2160)])
    assert okay.kind is LevelScreen.VICTORY and okay.tap == (720, 2130)
    cont = classify_level_screen(img, [Text("VICTORY", 560, 900, 880, 980),
                                       Text("Tap to Continue", 520, 2280, 920, 2340)])
    assert cont.kind is LevelScreen.VICTORY and cont.tap == (720, 2310)


@pytest.mark.parametrize("name, in_level", [
    ("level_board_ready.png", True), ("en_level_fight.png", True), ("en_level_skill_levelup.png", True),
    ("en_lobby_normal.png", False), ("en_tower.png", False), ("en_level_event_result.png", False),
])
def test_level_in_progress(ocr, name, in_level):
    from roguebot.navigation import Navigator
    img, texts = load(ocr, name)
    nav = Navigator(None, ocr)
    nav._capture = lambda: (img, texts)
    assert nav.level_in_progress() is in_level


def test_guild_map_is_not_a_level_even_when_its_labels_sit_in_the_event_bands():
    """Guild Hall / Coming soon land on the event title and option rows. That is the guild map."""
    import numpy as np
    from roguebot.navigation import Navigator
    img = np.zeros((2560, 1440, 3), np.uint8)
    texts = [Text("Guild Hall", 560, 980, 880, 1040),
             Text("Raid Boss", 900, 1360, 1200, 1440),
             Text("Coming soon", 560, 1750, 940, 1840),
             Text("Guild Camp", 520, 1900, 900, 1960),
             Text("Shop", 200, 1400, 360, 1460),
             Text("Vault", 160, 1500, 320, 1560)]
    assert classify_level_screen(img, texts).kind is LevelScreen.UNKNOWN
    assert classify_level_screen(img, texts).tap is None
    assert Navigator._on_board(img, texts) is False
    vault = [Text("Personal Vault", 400, 1360, 1040, 1440), Text("Claim", 400, 1750, 700, 1840)]
    assert classify_level_screen(img, vault).kind is LevelScreen.UNKNOWN
    assert Navigator._on_board(img, vault) is False


@pytest.mark.parametrize("name, on_board", [
    ("level_board_ready.png", True), ("level_board_auto.png", True), ("level_skill_levelup.png", True),
    ("en_level_skill_levelup.png", True),
    ("dojo_skills.png", False), ("en_raid_skills.png", False), ("raid_skill_choice.png", False),  # mode fights
    ("level_fight.png", False), ("en_raid_fight.png", False), ("lobby_normal.png", False),
])
def test_go_to_lobby_plays_out_only_level_boards(ocr, name, on_board):
    """go_to_lobby can't leave a running level: it plays it out, but never a dojo/raid fight."""
    from roguebot.navigation import Navigator
    img, texts = load(ocr, name)
    assert Navigator._on_board(img, texts) is on_board


@pytest.mark.parametrize("name, orbs", [
    ("level_fortune_teller.png", 5),
    ("en_level_fortune_teller.png", 5),
    ("level_fortune_teller_missed.png", 3),  # after the 40% ball failed ("Las estrellas guardaron silencio")
    ("level_fortune_teller_no_orbs.png", 0),
])
def test_fortune_teller(ocr, name, orbs):
    from roguebot.screens import parse_fortune_teller
    _, texts = load(ocr, name)
    teller = parse_fortune_teller(texts)
    assert teller.orbs == orbs
    assert sorted(teller.balls) == [40, 70, 100]
    for chance, button in ((100, (368, 1626)), (70, (719, 1626)), (40, (1073, 1626))):  # the "x1"/"x2" buttons
        assert abs(teller.balls[chance][0] - button[0]) <= 15 and abs(teller.balls[chance][1] - button[1]) <= 15


def test_fortune_teller_absent_on_other_screens(ocr):
    from roguebot.screens import parse_fortune_teller
    _, texts = load(ocr, "level_shop.png")
    assert parse_fortune_teller(texts) is None


LEVEL_FIXTURES = ["board.png", "level_board_ready.png", "level_board_auto.png", "level_event_cart.png", "level_event_rest.png",
                  "en_level_event_disabled_option.png", "level_shop.png", "en_level_shop.png", "level_dice_duel.png",
                  "level_flip_cards.png", "level_revive.png", "level_fortune_teller.png", "level_skill_levelup.png",
                  "en_level_fight.png", "level_victory.png", "level_defeat.png", "en_level_victory_x2.png"]
LOBBY_POPUP_FIXTURES = ["lobby_autumn_event_popup.png", "lobby_album_popup.png", "lobby_roulette_popup.png",
                        "lobby_limited_offer_popup.png", "en_lobby_spin_popup.png", "en_lobby_guild_popup.png",
                        "en_vip_offer.png", "en_lobby_daily_login.png", "lobby_normal.png", "en_lobby_elite.png"]


@pytest.mark.parametrize("name", LEVEL_FIXTURES)
def test_level_screens_have_no_lobby_behind(ocr, name):
    from roguebot.screens import lobby_behind
    _, texts = load(ocr, name)
    assert not lobby_behind(texts)


@pytest.mark.parametrize("name", LOBBY_POPUP_FIXTURES)
def test_lobby_popups_are_never_played_as_a_level(ocr, name):
    """Seen 2026-10-23..27: a seasonal popup over the lobby looked like a level event, go_to_lobby handed it to
    the player, which tapped "options" in the lobby (once into the Equip tab) and stopped on an unknown screen."""
    from roguebot.navigation import Navigator
    from roguebot.screens import lobby_behind
    img, texts = load(ocr, name)
    assert lobby_behind(texts)
    assert not Navigator._on_board(img, texts)
    nav = Navigator(None, ocr)
    nav._capture = lambda: (img, texts)
    assert not nav.level_in_progress()


def test_autumn_event_popup_closes_by_its_x(ocr):
    """"¡Sendero de Ascuas!" (autumn 2026): a big ✕ at the bottom center, over the dimmed footer."""
    from roguebot.screens import outside_tap_clear
    img, texts = load(ocr, "lobby_autumn_event_popup.png")
    assert close_button(img) == (720, 2453)
    assert outside_tap_clear(texts)


def test_close_button_any_size_finds_a_bigger_x(ocr):
    import cv2
    from roguebot.screens import _CLOSE_X, close_button_any_size
    img, _ = load(ocr, "lobby_normal.png")
    img = img.copy()
    big = cv2.resize(_CLOSE_X, None, fx=1.5, fy=1.5)
    img[1000:1000 + big.shape[0], 600:600 + big.shape[1]] = big
    assert close_button(img) is None
    x, y = close_button_any_size(img)
    assert abs(x - (600 + big.shape[1] // 2)) <= 3 and abs(y - (1000 + big.shape[0] // 2)) <= 3


def test_close_button_any_size_absent_on_plain_screens(ocr):
    from roguebot.screens import close_button_any_size
    for name in ("lobby_normal.png", "lobby_limited_offer_popup.png", "level_board_ready.png"):
        img, _ = load(ocr, name)
        assert close_button_any_size(img) is None, name


def test_outside_tap_never_lands_on_popup_text():
    from roguebot.screens import outside_tap_clear
    from roguebot.vision import Text
    assert outside_tap_clear([Text("Aventura", 640, 2450, 799, 2492)])
    assert outside_tap_clear([Text("Toca en cualquier lugar para cerrar", 358, 2434, 1078, 2491)])
    assert not outside_tap_clear([Text("$4,99", 660, 2420, 780, 2480)])


def test_a_level_left_at_the_fortune_teller_is_played_out(ocr):
    """Seen 2026-10-21: the game sat at the Fortune Teller and go_to_lobby failed instead of playing the level out."""
    from roguebot.navigation import IN_LEVEL, Navigator
    img, texts = load(ocr, "level_fortune_teller_no_orbs.png")
    assert Navigator._on_board(img, texts)
    assert classify_level_screen(img, texts).kind in IN_LEVEL
