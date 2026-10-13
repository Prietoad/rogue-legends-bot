"""Screen recognition against real screenshots in tests/fixtures (no device needed)."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from roguebot.screens import (LevelScreen, Mode, classify_level_screen, close_button, footer_visible, game_speed, is_loading, is_star_list, parse_elite_dialog,
                              parse_energy, parse_energy_popup, parse_lobby, parse_star_list, popup_close)
from roguebot import labels
from roguebot.vision import Ocr, Text, normalize, parse_level_number

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ocr():
    return Ocr()


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    labels.set_language(None)


def fixture_language(name: str) -> str:
    return "en" if name.startswith("en_") else "es"


def load(ocr, name):
    """Screenshot + OCR, with only the fixture's own language active (en_* = English, else Spanish)."""
    labels.set_language(fixture_language(name))
    img = cv2.imread(str(FIXTURES / name))
    return img, ocr.read(img)


def test_parse_level_number():
    assert parse_level_number("12. Arenas Movedizas II") == 12
    assert parse_level_number("4.") == 4
    assert parse_level_number("Temporada 22") is None


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
    ("level_event_rest.png", LevelScreen.EVENT, (510, 2033)),    # no "Salir": leftmost option
    ("en_board_dice_unknown.png", LevelScreen.BOARD_READY, (720, 2150)),  # dark teal board: not a footer
    ("en_level_event_disabled_option.png", LevelScreen.EVENT, (922, 2033)),  # "Read" greyed after failing: "Walk Away"
    ("level_shop.png", LevelScreen.SHOP, (427, 2417)),
    ("level_shop_2.png", LevelScreen.SHOP, (427, 2417)),     # skill rows fall in the event bands
    ("level_lucky_wheel.png", LevelScreen.CONTINUE, (718, 2149)),
    ("level_monk_wheel.png", LevelScreen.CONTINUE, (721, 2281)),
    ("level_monk_done.png", LevelScreen.LEAVE, (720, 2279)),
    ("level_dice_duel.png", LevelScreen.DICE_DUEL, (1016, 2367)),  # score 0: roll
    ("level_reward_claim.png", LevelScreen.CONTINUE, (717, 2349)),
    ("level_defeat.png", LevelScreen.DEFEAT, (720, 2221)),
    ("level_victory.png", LevelScreen.VICTORY, (720, 2220)),
    ("level_event_result.png", LevelScreen.CONTINUE, (719, 2462)),
    ("level_flip_cards.png", LevelScreen.FLIP_CARDS, (299, 1280)),
    ("level_flip_cards_one_up.png", LevelScreen.FLIP_CARDS, (579, 1280)),  # skips the flipped card
    ("en_level_skill_levelup.png", LevelScreen.SKILL_PICK, (720, 1053)),
    ("en_level_modifiers.png", LevelScreen.CONTINUE, (719, 1930)),  # elite level intro
    ("level_fortune_teller.png", LevelScreen.LEAVE, (293, 2280)),  # "Adivino"
    ("en_level_fight.png", LevelScreen.FIGHT, None),  # "Round 4/30"
    ("level_dice_duel_won.png", LevelScreen.CONTINUE, (480, 2366)),  # RECLAMAR, not "Desafiar de Nuevo"
    ("level_revive.png", LevelScreen.REVIVE, (993, 1454)),
    ("en_level_skill_power_resurrection.png", LevelScreen.SKILL_PICK, (720, 1054)),  # "Revive after..." card  # "Gratis" video, never the 60-gem button
    ("level_revive_last_second.png", LevelScreen.REVIVE, (993, 1454)),
    ("en_level_shop.png", LevelScreen.SHOP, (428, 2417)),
    ("en_level_fortune_teller.png", LevelScreen.LEAVE, (293, 2280)),
    ("en_level_event_result.png", LevelScreen.CONTINUE, (720, 2461)),
    ("en_level_chest.png", LevelScreen.CONTINUE, (717, 2123)),
    ("en_level_monk_wheel.png", LevelScreen.CONTINUE, (720, 2281)),
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
