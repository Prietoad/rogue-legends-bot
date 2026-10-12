"""Full routine screens (modes, arena, tower, mines/pets, guild raid) on real screenshots."""

from pathlib import Path

import cv2
import pytest

from roguebot import labels
from roguebot.mode_screens import (back_arrow, in_guild, is_modes_list, mode_closed, mode_entry, parse_arena, parse_arena_opponents,
                                   parse_dungeon_popup, parse_fight_result, parse_raid, parse_skill_choice,
                                   parse_tower, pick_opponent)
from roguebot.screens import close_button
from roguebot.vision import Ocr, Text, find

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ocr():
    return Ocr()


@pytest.fixture(autouse=True)
def _reset_language():
    yield
    labels.set_language(None)


def load(ocr, name):
    labels.set_language("en" if name.startswith("en_") else "es")
    img = cv2.imread(str(FIXTURES / name))
    return img, ocr.read(img)


def test_modes_list(ocr):
    _, texts = load(ocr, "en_modes_list.png")
    assert is_modes_list(texts)
    for label in (labels.ARENA, labels.TOWER, labels.MINES, labels.PETS):
        assert mode_entry(texts, label) is not None, label


def test_modes_list_scrolled_down(ocr):
    _, texts = load(ocr, "en_modes_list_scrolled.png")
    assert is_modes_list(texts)
    assert mode_entry(texts, labels.ARENA) is None  # the routine scrolls back to the top
    assert mode_entry(texts, labels.PETS) is not None


@pytest.mark.parametrize("name", ["en_lobby_normal.png", "en_arena.png", "en_tower.png", "en_mines_ticket.png",
                                  "en_pets_ad.png"])
def test_not_modes_list(ocr, name):
    _, texts = load(ocr, name)
    assert not is_modes_list(texts)


@pytest.mark.parametrize("name, tickets", [("en_arena.png", 5), ("en_arena_4_tickets.png", 4)])
def test_arena_screen(ocr, name, tickets):
    img, texts = load(ocr, name)
    screen = parse_arena(img, texts, ocr)
    assert screen is not None and screen.tickets == tickets
    assert screen.challenge.center[1] > 2300


def test_arena_screen_absent_under_opponent_panel(ocr):
    img, texts = load(ocr, "en_arena_opponents.png")
    assert parse_arena(img, texts, ocr) is None


@pytest.mark.parametrize("name, powers, best", [
    ("en_arena_opponents.png", [201400, 129400, 287700, 70700, 250100], 287700),
    ("en_arena_opponents_2.png", [3400000, 316800, 252100, 201400, 339000], 339000),  # 3,4m is stronger: skipped
])
def test_arena_opponents(ocr, name, powers, best):
    _, texts = load(ocr, name)
    panel = parse_arena_opponents(texts)
    assert panel is not None
    assert panel.own_power == 534800
    assert [o.power for o in panel.opponents] == powers
    assert panel.free_refresh is not None
    choice = pick_opponent(panel.own_power, panel.opponents)
    assert choice.power == best
    assert abs(choice.challenge.center[0] - 1071) < 20  # the row's own Challenge button


def test_tower(ocr):
    _, texts = load(ocr, "en_tower.png")
    screen = parse_tower(texts)
    assert screen is not None and screen.tickets == 13
    assert parse_dungeon_popup(texts) is None and parse_raid(texts) is None


@pytest.mark.parametrize("name, difficulty, tickets, challenge, sweep, ad", [
    ("en_mines_no_tickets.png", 18, 0, False, False, True),
    ("en_mines_ticket.png", 18, 1, True, True, False),
    ("en_mines_done.png", 18, 0, True, True, False),  # buttons stay, tickets say 0: done
    ("en_pets.png", 17, 1, True, True, False),
    ("en_pets_ad.png", 17, 0, False, False, True),
])
def test_dungeon_popup(ocr, name, difficulty, tickets, challenge, sweep, ad):
    _, texts = load(ocr, name)
    popup = parse_dungeon_popup(texts)
    assert popup is not None
    assert (popup.difficulty, popup.tickets) == (difficulty, tickets)
    assert (popup.challenge is not None, popup.sweep is not None, popup.ad is not None) == (challenge, sweep, ad)


@pytest.mark.parametrize("name", ["en_mines_ad_reward.png", "en_mines_sweep_reward.png"])
def test_dungeon_reward_popup_is_claimed_not_parsed(ocr, name):
    _, texts = load(ocr, name)
    assert parse_dungeon_popup(texts) is None
    assert find(texts, labels.TAP_TO_CLAIM) is not None


@pytest.mark.parametrize("name, attempts", [("en_raid.png", 1), ("en_raid_done.png", 0)])
def test_raid(ocr, name, attempts):
    _, texts = load(ocr, name)
    screen = parse_raid(texts)
    assert screen is not None and screen.attempts == attempts


@pytest.mark.parametrize("name, chosen, needed, cards", [
    ("en_raid_skills.png", 0, 2, 4),
    ("en_raid_skills_1of2.png", 1, 2, 4),
    ("en_raid_skills_legendary.png", 0, 2, 4),
    ("en_raid_skills_mythic.png", 0, 1, 3),
    ("raid_skill_choice.png", 0, 2, 4),  # Spanish: the prompt also says "aprender"
])
def test_raid_skill_choice(ocr, name, chosen, needed, cards):
    _, texts = load(ocr, name)
    choice = parse_skill_choice(texts)
    assert choice is not None
    assert (choice.chosen, choice.needed, len(choice.cards)) == (chosen, needed, cards)
    assert choice.cards[0][1] < choice.cards[1][1]  # same rarity: top to bottom
    assert 820 < choice.cards[0][1] < 880  # first card body


@pytest.mark.parametrize("name, victory, button", [
    ("en_arena_victory.png", True, "OK"),
    ("en_tower_defeat.png", False, "Tap to Continue"),
    ("en_mines_defeat.png", False, "Tap to Continue"),
    ("en_raid_result.png", False, "OK"),
    ("tower_victory.png", True, "Confirmar"),
])
def test_fight_result(ocr, name, victory, button):
    _, texts = load(ocr, name)
    result = parse_fight_result(texts)
    assert result is not None and result.victory == victory and result.button.text == button


@pytest.mark.parametrize("name", ["en_arena_fight.png", "en_tower_fight.png", "en_raid_fight.png", "en_raid_skills.png"])
def test_fight_in_progress_has_no_result(ocr, name):
    _, texts = load(ocr, name)
    assert parse_fight_result(texts) is None


@pytest.mark.parametrize("name, at", [
    ("en_modes_list.png", (120, 2447)), ("en_arena.png", (120, 2447)), ("en_tower.png", (120, 2447)),
    ("en_raid.png", (120, 2447)), ("en_guild.png", (148, 2304)), ("stars_elite.png", (120, 2449)),
    ("en_lobby_normal.png", None), ("level_board_ready.png", None), ("en_level_fortune_teller.png", None),
    ("en_vip_offer.png", None), ("en_raid_skills.png", None), ("en_tower_defeat.png", None),
])
def test_back_arrow(name, at):
    img = cv2.imread(str(FIXTURES / name))
    found = back_arrow(img)
    assert (found is None) if at is None else (abs(found[0] - at[0]) < 5 and abs(found[1] - at[1]) < 5)


@pytest.mark.parametrize("name", ["en_arena_opponents.png", "en_mines_ticket.png", "en_pets_ad.png"])
def test_mode_popups_close_with_x(name):
    assert close_button(cv2.imread(str(FIXTURES / name))) is not None


@pytest.mark.parametrize("name, member", [
    ("en_lobby_normal.png", True), ("en_lobby_elite.png", True), ("lobby_normal.png", True), ("en_modes_list.png", False),
])
def test_in_guild(ocr, name, member):
    _, texts = load(ocr, name)
    assert in_guild(texts) == member


def test_vip_offer_closes_by_text(ocr):
    """Skip in a mode fight opens this paid offer; it must be closable without touching its price."""
    from roguebot.screens import popup_close
    _, texts = load(ocr, "en_vip_offer.png")
    assert popup_close(texts).text == "Tap anywhere to close"


def test_tower_spanish(ocr):
    """Spanish tower: "Torre de los Héroes", button "Desafío" (not "Desafiar"), tickets "4/10"."""
    _, texts = load(ocr, "tower_4_tickets.png")
    screen = parse_tower(texts)
    assert screen is not None and screen.tickets == 4
    assert screen.challenge.center[1] > 2300


@pytest.mark.parametrize("name", ["en_guild.png", "guild_map.png"])
def test_guild_map_raid_boss(ocr, name):
    """Spanish wraps the label over two lines ("Jefe de" / "Incursión")."""
    _, texts = load(ocr, name)
    boss = find(texts, labels.RAID_BOSS)
    assert boss is not None and 950 < boss.center[0] < 1060 and 1380 < boss.center[1] < 1460


def test_raid_spanish_done(ocr):
    """Spanish: "Asalto de Gremio", "Desafiar" + "Se actualiza en: 12h" once the attempts are used."""
    _, texts = load(ocr, "raid_done.png")
    screen = parse_raid(texts)
    assert screen is not None and screen.attempts == 0


def test_tower_cleared_screen(ocr):
    """After the 10th floor: "Congrats", tap the chest to claim (there is no back arrow on this screen)."""
    _, texts = load(ocr, "en_tower_cleared.png")
    assert find(texts, labels.TOWER_CLEARED) is not None
    assert parse_tower(texts) is None


def test_arena_closed_around_the_daily_reset(ocr):
    _, texts = load(ocr, "modes_list_arena_closed.png")  # "Arena / Abre en 4m"
    assert is_modes_list(texts)
    assert mode_closed(texts, mode_entry(texts, labels.ARENA))
    assert not mode_closed(texts, mode_entry(texts, labels.TOWER))  # "Piso 16-4" below it


def test_arena_open(ocr):
    _, texts = load(ocr, "en_modes_list.png")
    assert not mode_closed(texts, mode_entry(texts, labels.ARENA))


def test_vip_cards_icon_in_the_lobby(ocr):
    from roguebot.mode_screens import vip_cards_icon
    _, texts = load(ocr, "lobby_vip_icon.png")
    icon = vip_cards_icon(texts)
    assert icon and icon.center[0] < 200 and 600 < icon.center[1] < 800


def test_vip_cards_claim_all_never_a_price(ocr):
    from roguebot.mode_screens import vip_cards_icon, vip_claim_all
    _, texts = load(ocr, "vip_cards.png")  # also has "$34,99" / "$6,99" purchase buttons and card "Reclamar"
    button = vip_claim_all(texts)
    assert button and button.norm == "reclamar todo" and button.center[1] > 2300
    assert vip_cards_icon(texts) is None  # the "VIP" on the card is not the lobby icon (x > 250)
    _, lobby = load(ocr, "lobby_vip_icon.png")
    assert vip_claim_all(lobby) is None


def test_guild_hall_and_donation(ocr):
    from roguebot.mode_screens import free_donation, guild_hall_donate
    _, texts = load(ocr, "guild_map.png")
    assert find(texts, labels.GUILD_HALL)  # "Sala de / Gremio" castle
    _, texts = load(ocr, "en_guild.png")
    assert find(texts, labels.GUILD_HALL)  # "GuildHall"
    _, texts = load(ocr, "guild_hall.png")
    assert guild_hall_donate(texts).center[1] > 2100
    assert free_donation(texts) is None  # no popup yet
    _, texts = load(ocr, "guild_donation_free.png")
    button = free_donation(texts)
    assert button and button.norm == "gratis"
    _, texts = load(ocr, "guild_donation_paid.png")  # after the free one: a gem price ("25")
    assert find(texts, labels.DONATION_TITLE) and free_donation(texts) is None


def test_arena_opponents_spanish(ocr):
    _, texts = load(ocr, "arena_opponents.png")  # "Desafío de la Arena", "Desafiar", "Recarga Gratis"
    panel = parse_arena_opponents(texts)
    assert panel.own_power == 668800
    assert [o.power for o in panel.opponents] == [3500000, 717100, 107500, 440200, 248400]
    assert panel.free_refresh.norm == "recarga gratis"
    assert pick_opponent(panel.own_power, panel.opponents).power == 440200


@pytest.mark.parametrize("name", ["en_lobby_normal.png", "en_lobby_elite.png", "en_lobby_guild_popup.png"])
def test_vip_cards_icon_in_the_english_lobby(ocr, name):
    from roguebot.mode_screens import vip_cards_icon
    _, texts = load(ocr, name)  # "VIP / Cards", with "VIP" read as "VIPS"/"LVIP"
    icon = vip_cards_icon(texts)
    assert icon and icon.center[0] < 200 and 600 < icon.center[1] < 800


@pytest.mark.parametrize("name", ["patrol.png", "en_patrol.png"])
def test_patrol_popup(ocr, name):
    from roguebot.mode_screens import parse_patrol
    _, texts = load(ocr, name)
    popup = parse_patrol(texts)
    assert popup and popup.claim.center[0] > popup.quick.center[0]  # Claim (right), Quick Patrol (left)
    assert popup.claim.center[1] < 1900  # never the "VIP Monthly Card" offer below


@pytest.mark.parametrize("name", ["patrol_fast_used_up.png", "en_patrol_fast_used_up.png"])
def test_quick_patrol_used_up(ocr, name):
    from roguebot.mode_screens import parse_patrol, parse_quick_patrol
    img, texts = load(ocr, name)
    assert parse_patrol(texts) is None  # the quick patrol popup covers the patrol popup
    q = parse_quick_patrol(img, texts)
    assert q is not None and q.video is None and q.energy is None  # "Remaining: 0" under both


@pytest.mark.parametrize("name", ["patrol_fast_used_up.png", "en_patrol_fast_used_up.png"])
def test_quick_patrol_with_uses_left(ocr, name):
    from roguebot.mode_screens import parse_quick_patrol
    img, texts = load(ocr, name)
    texts = [Text(t.text.replace(": 0", ": 1"), t.x1, t.y1, t.x2, t.y2) for t in texts]
    q = parse_quick_patrol(img, texts)
    assert q.video.norm in ("gratis", "free") and q.energy.norm == "x10" and q.energy_cost == 10


def test_quick_patrol_energy_option_needs_the_lightning_icon(ocr):
    from roguebot.mode_screens import parse_quick_patrol
    img, texts = load(ocr, "patrol_fast_used_up.png")
    texts = [Text(t.text.replace(": 0", ": 1"), t.x1, t.y1, t.x2, t.y2) for t in texts]
    no_icon = img.copy()
    no_icon[1420:1530, 820:950] = (90, 200, 120)  # plain green button, e.g. a price without the lightning
    assert parse_quick_patrol(no_icon, texts).energy is None


def test_patrol_popups_absent_in_the_lobby(ocr):
    from roguebot.mode_screens import parse_patrol, parse_quick_patrol
    img, texts = load(ocr, "lobby_vip_icon.png")
    assert parse_patrol(texts) is None and parse_quick_patrol(img, texts) is None


@pytest.mark.parametrize("text, seconds", [
    ("tiempo de patrulla: 28:13", 28 * 60 + 13),
    ("patrol time: 01:28", 88),
    ("tiempo de patrulla: 7:50:00", 7 * 3600 + 50 * 60),
    ("patrol time: 08:00:00", 8 * 3600),
    ("tiempo de patrulla", None),
])
def test_patrol_seconds(text, seconds):
    from roguebot.mode_screens import patrol_seconds
    assert patrol_seconds(text) == seconds


@pytest.mark.parametrize("name, seconds", [("patrol.png", 28 * 60 + 13), ("en_patrol.png", 88)])
def test_patrol_popup_reads_the_counter(ocr, name, seconds):
    from roguebot.mode_screens import parse_patrol
    _, texts = load(ocr, name)
    assert parse_patrol(texts).elapsed == seconds


def test_arena_season_promotion_popup_closes_by_text(ocr):
    """A new arena season shows "Felicidades por tu ascenso!" over the arena screen."""
    from roguebot.screens import popup_close
    _, texts = load(ocr, "arena_promotion_popup.png")
    close = popup_close(texts)
    assert close and close.center[1] > 2400
