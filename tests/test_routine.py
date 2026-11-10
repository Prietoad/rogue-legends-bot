"""Full routine behaviour with fake screens (no device)."""

import itertools

import pytest

from roguebot import labels, routine
from roguebot.navigation import NavigationError
from roguebot.routine import Routine
from roguebot.vision import Text


class FakeDevice:
    def __init__(self):
        self.taps = []
        self.backs = 0
        self.apps = []  # foreground packages to report in order (then the game)

    def tap(self, x, y, settle=0):
        self.taps.append((x, y))

    def back(self, settle=0):
        self.backs += 1

    def foreground_package(self):
        return self.apps.pop(0) if self.apps else routine.config.PACKAGE

    def swipe(self, start, end, duration=0.6, settle=0):
        self.swipes = getattr(self, "swipes", [])
        self.swipes.append((start, end))

    def screenshot(self):
        return None


class FakeNav:
    def __init__(self):
        self.lobby_visits = 0

    def go_to_lobby(self):
        self.lobby_visits += 1

    def _fail(self, msg, img):
        raise NavigationError(msg)


@pytest.fixture(autouse=True)
def english(monkeypatch):
    monkeypatch.setattr(routine.config, "POLL_INTERVAL", 0)
    labels.set_language("en")
    yield
    labels.set_language(None)


def make(screens, ads=False):
    """Routine whose captures return the given OCR text lists in order."""
    r = Routine(FakeDevice(), None, FakeNav(), ads)
    frames = iter(screens)

    def capture():
        if r._pushed is not None:
            frame = r._pushed
            r._pushed = None
            return frame
        return None, next(frames)

    r._capture = capture
    return r


def test_failed_part_is_reported_and_the_next_one_runs(monkeypatch):
    r = make([MODES_TOP] * 5)  # after arena, dojo, tower, dive and mines: already back on the modes list
    ran = []

    def ok():
        ran.append("ok")
        return routine.DONE

    def stuck():
        raise NavigationError("stuck")
    monkeypatch.setattr(r, "arena", stuck)
    monkeypatch.setattr(r, "tower", ok)
    monkeypatch.setattr(r, "dungeon", lambda label: routine.DONE)
    monkeypatch.setattr(r, "raid", lambda: routine.SKIPPED)
    monkeypatch.setattr(r, "vip", lambda: routine.DONE)
    monkeypatch.setattr(r, "donate", lambda: routine.DONE)
    monkeypatch.setattr(r, "vault", lambda: routine.DONE)
    monkeypatch.setattr(r, "patrol", lambda: routine.DONE)
    monkeypatch.setattr(r, "_back_to_guild", lambda: False)
    for part in ("daily", "mail", "dojo", "dive"):
        monkeypatch.setattr(r, part, lambda: routine.DONE)
    results = r.run_parts()
    assert results == [("daily", "done"), ("vip", "done"), ("mail", "done"), ("patrol", "done"), ("arena", "failed"),
                       ("dojo", "done"), ("tower", "done"), ("dive", "done"), ("mines", "done"), ("pets", "done"),
                       ("raid", "skipped"), ("donate", "done"), ("vault", "done")]
    assert ran == ["ok"]
    # Stays in the modes tab. Lobby after daily, VIP, mail, patrol, the modes, raid, donation, vault.
    assert r.nav.lobby_visits == 8


def skill_screen(chosen, needed, rarities):
    tags = [Text(r, 280, 740 + 306 * i, 360, 770 + 306 * i) for i, r in enumerate(rarities)]
    return [Text("Select a Skill to learn!", 400, 560, 1040, 600), *tags,
            Text(f"Learn Skills ({chosen}/{needed})", 700, 2130, 1080, 2170)]


def test_fight_picks_best_skills_then_learns_then_waits_for_result():
    rarities = ["Common", "Legendary", "Common", "Mythic"]
    r = make([skill_screen(0, 2, rarities), skill_screen(1, 2, rarities), skill_screen(2, 2, rarities),
              [Text("Round: 1/10", 600, 170, 840, 210)],
              [Text("DEFEAT", 600, 880, 840, 940), Text("OK", 680, 2300, 760, 2350)]])
    result = r._fight()
    assert not result.victory
    mythic_y, legendary_y = 755 + 306 * 3 + 90, 755 + 306 + 90
    assert r.device.taps == [(800, mythic_y), (800, legendary_y), (890, 2150), (720, 2325)]


def test_fight_never_taps_skip():
    fight = [Text("VS", 700, 120, 740, 160), Text("Skip", 860, 2400, 980, 2450)]
    r = make([fight, fight, [Text("VICTORY!", 600, 1060, 840, 1110), Text("OK", 680, 2090, 760, 2140)]])
    assert r._fight().victory
    assert r.device.taps == [(720, 2115)]


def dungeon(tickets, ad=False, buttons=True):
    texts = [Text("Crystal Mines", 560, 450, 880, 500), Text("18", 680, 1110, 760, 1200),
             Text("Difficulty", 620, 1225, 800, 1270), Text(f"{tickets}/2", 700, 1695, 790, 1735)]
    if ad:
        texts.append(Text("Dungeon Tickets x1", 540, 1790, 900, 1835))
    if buttons:
        texts += [Text("Sweep previous", 340, 1800, 650, 1840), Text("Challenge", 820, 1825, 1066, 1870)]
    return texts


CLAIM = [Text("Tap anywhere to claim", 480, 2300, 960, 2345)]
LOADING = [Text("Loading...", 600, 1260, 840, 1300)]  # right after a Challenge tap registered
DEFEAT = [Text("DEFEAT", 600, 1000, 830, 1055), Text("Tap to Continue", 560, 2310, 875, 2350)]


def test_dungeon_challenges_then_sweeps_after_defeat_and_watches_ads(monkeypatch):
    r = make([dungeon(1), LOADING, DEFEAT,     # challenge, lose (ticket kept)
              dungeon(1), CLAIM,               # sweep, claim
              dungeon(0, ad=True, buttons=False), CLAIM,  # watch ad, claim
              dungeon(1), CLAIM,               # still lost: sweep again, claim
              dungeon(0)], ads=True)           # no tickets, no ad: done
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.dungeon(labels.MINES) == routine.DONE
    challenge, sweep, ad, cont, claim = (943, 1847), (495, 1820), (720, 1812), (717, 2330), (720, 2322)
    assert r.device.taps == [challenge, cont, sweep, claim, ad, claim, sweep, claim]


MODES_TOP = [Text("Arena", 1250, 240, 1360, 290), Text("Tower Challenge", 1000, 1020, 1300, 1070)]
MODES_SCROLLED = [Text("Tower Challenge", 1000, 410, 1300, 455), Text("Pet Kingdom", 1080, 1605, 1330, 1650)]


class SwipeDevice(FakeDevice):
    def __init__(self):
        super().__init__()
        self.swipes = []

    def swipe(self, start, end, duration=0.6, settle=0):
        self.swipes.append((start, end))


def test_open_mode_scrolls_the_modes_list_to_the_top():
    r = make([MODES_SCROLLED, MODES_SCROLLED, MODES_TOP, MODES_TOP])  # last: the list stopped moving
    r.device = SwipeDevice()
    r._open_mode(labels.ARENA)
    assert len(r.device.swipes) == 2
    assert all(end[1] > start[1] for start, end in r.device.swipes)  # finger drags down = list goes up
    assert r.device.taps[-1] == (1305, 265)  # Arena title


def test_open_mode_at_the_top_does_not_scroll():
    r = make([MODES_TOP])
    r.device = SwipeDevice()
    r._open_mode(labels.TOWER)
    assert r.device.swipes == [] and r.device.taps[-1] == (1150, 1045)


ARENA_SCREEN = [Text("Arena", 280, 60, 400, 120), Text("Challenge", 620, 2390, 820, 2440)]
MINES_POPUP = [Text("Crystal Mines", 560, 450, 880, 500), Text("Difficulty", 620, 1225, 800, 1270),
               Text("Arena", 1250, 240, 1360, 290), Text("Tower Challenge", 1000, 1020, 1300, 1070)]


def test_back_to_modes_uses_close_x_then_back_arrow(monkeypatch):
    r = make([MINES_POPUP, ARENA_SCREEN, MODES_TOP])
    monkeypatch.setattr(routine, "close_button", lambda img: (720, 2098) if r._frame is MINES_POPUP else None)
    monkeypatch.setattr(routine, "back_arrow", lambda img: (120, 2447))
    frames = iter([MINES_POPUP, ARENA_SCREEN, MODES_TOP])

    def capture():
        r._frame = next(frames)
        return None, r._frame
    r._capture = capture
    assert r._back_to_modes()
    assert r.device.taps == [(720, 2098), (120, 2447)]  # ✕ on the popup (not the arrow behind it), then ←


def test_back_to_modes_gives_up_and_the_routine_falls_back_to_the_lobby(monkeypatch):
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "close_button", lambda img: None)
    monkeypatch.setattr(routine, "back_arrow", lambda img: None)
    r = make([[Text("Loading.", 600, 1260, 760, 1310)]] * routine.MAX_BACK_STEPS)
    assert not r._back_to_modes()
    assert r.device.taps == []


def test_open_mode_from_the_modes_list_skips_the_lobby():
    r = make([MODES_TOP])
    r._open_mode(labels.TOWER)
    assert r.nav.lobby_visits == 0
    assert r.device.taps == [(1150, 1045)]


CONGRATS = [Text("Tower of Heroes 15", 560, 435, 880, 480), Text("Congratulations on clearing", 480, 685, 960, 720)]
TOWER = [Text("Tower of Heroes 16", 560, 245, 880, 290), Text("11/10", 800, 65, 905, 100),
         Text("Challenge", 620, 2395, 820, 2440)]


def test_tower_opens_the_cleared_tower_chest(monkeypatch):
    r = make([CONGRATS, CONGRATS + CLAIM, TOWER, LOADING, DEFEAT, TOWER])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    assert r.device.taps[:3] == [routine.config.TOWER_CHEST, (720, 2322), (720, 2417)]  # chest, claim, Challenge


def test_closed_arena_is_skipped_without_tapping():
    r = make([MODES_TOP + [Text("Opens in 4m", 980, 320, 1130, 360)]])
    assert r.arena() == routine.SKIPPED
    assert r.device.taps == []


ES_LOBBY = [Text("Patrulla", 650, 1900, 790, 1945), Text("APAGADO", 880, 2060, 990, 2095),
            Text("INICIO", 600, 2070, 716, 2115), Text("de Estrellas", 840, 1910, 960, 1945)]
VIP_LOBBY = ES_LOBBY + [Text("Tarjetas", 20, 640, 140, 680), Text("VIP", 50, 705, 110, 740)]
VIP_SCREEN = [Text("$6,99", 1130, 2080, 1280, 2130), Text("Reclamar todo", 560, 2420, 880, 2470)]


def test_vip_taps_only_claim_all_and_claims_the_reward():
    r = make([VIP_LOBBY, VIP_SCREEN, [Text("Toca en cualquier lugar para reclamar", 400, 2300, 1040, 2340)],
              VIP_SCREEN])
    labels.set_language("es")
    assert r.vip() == routine.DONE
    assert r.device.taps == [(80, 660), (720, 2445), (720, 2320)]  # icon label, claim all, reward popup


def test_vip_skipped_without_the_icon():
    labels.set_language("es")
    r = make([ES_LOBBY])
    assert r.vip() == routine.SKIPPED
    assert r.device.taps == []


GUILD_LOBBY = ES_LOBBY + [Text("Gremio", 40, 2160, 140, 2200)]
GUILD_MAP = [Text("Sala de", 680, 970, 800, 1020), Text("Gremio", 680, 1030, 800, 1075)]
GUILD_HALL = [Text("Registro", 260, 2225, 430, 2275), Text("Donar", 650, 2225, 790, 2270)]
DONATION_FREE = GUILD_HALL + [Text("Donación de Gremio", 520, 715, 920, 760), Text("Gratis", 650, 1585, 790, 1630)]
DONATION_PAID = GUILD_HALL + [Text("Donación de Gremio", 520, 715, 920, 760), Text("25", 740, 1590, 790, 1630)]
CLAIM_ES = [Text("Toca en cualquier lugar para reclamar", 400, 2300, 1040, 2340)]


def test_donate_only_the_free_donation():
    labels.set_language("es")
    r = make([GUILD_LOBBY, GUILD_MAP, GUILD_HALL, DONATION_FREE, DONATION_FREE, CLAIM_ES, CLAIM_ES, DONATION_PAID])
    assert r.donate() == routine.DONE
    assert r.device.taps == [routine.config.GUILD_BUTTON, (740, 995), (720, 2247), (720, 1607), (720, 2320)]
    # the gem price ("25") was never tapped


def test_donation_from_the_guild_map_does_not_leave_and_reenter():
    """After the raid the bot is already on the map: it must not go back to the lobby first."""
    labels.set_language("es")
    r = make([GUILD_MAP, GUILD_HALL, DONATION_FREE, DONATION_FREE, CLAIM_ES, DONATION_PAID])
    assert r.donate() == routine.DONE
    assert routine.config.GUILD_BUTTON not in r.device.taps
    assert (720, 1607) in r.device.taps  # the free donation


def test_vault_claims_the_free_personal_reward_and_not_a_price(monkeypatch):
    labels.set_language("en")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    guild_map = [Text("Guild Hall", 640, 980, 860, 1040), Text("Raid Boss", 1000, 1400, 1200, 1460),
                 Text("Vault", 160, 1480, 320, 1540)]
    inside = [Text("Personal Vault", 480, 400, 960, 460), Text("Daily", 560, 900, 760, 950),
              Text("Claim", 600, 1100, 840, 1160)]
    priced = [Text("Personal Vault", 480, 400, 960, 460), Text("Claim", 1000, 1100, 1200, 1160),
              Text("50", 1080, 1160, 1160, 1200)]
    lobby = [Text("Patrol", 650, 1900, 790, 1945), Text("OFF", 880, 2060, 990, 2095),
             Text("START", 600, 2070, 720, 2115)]
    r = make([guild_map, inside, priced, guild_map, lobby])
    assert r.vault() == routine.DONE
    assert r.device.taps[0] == (240, 1510)  # the vault building
    assert (720, 1130) in r.device.taps  # free Claim
    assert (1100, 1130) not in r.device.taps  # the gem-priced claim
    assert r.device.taps[-1] == routine.config.LIST_BACK  # guild map back to the main screen


def test_vault_with_nothing_to_claim_backs_out_to_the_lobby(monkeypatch):
    """No free claim: close the vault, then the map's bottom-left arrow. Never play the map as a level."""
    labels.set_language("en")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    guild_map = [Text("Guild Hall", 640, 980, 860, 1040), Text("Raid Boss", 1000, 1400, 1200, 1460),
                 Text("Coming soon", 500, 1750, 940, 1840), Text("Guild Camp", 520, 1900, 900, 1960),
                 Text("Vault", 160, 1480, 320, 1540)]
    inside = [Text("Personal Vault", 480, 400, 960, 460), Text("Daily", 560, 900, 760, 950)]
    lobby = [Text("Patrol", 650, 1900, 790, 1945), Text("OFF", 880, 2060, 990, 2095),
             Text("START", 600, 2070, 720, 2115)]
    r = make([guild_map, inside, inside, guild_map, lobby])
    assert r.vault() == routine.DONE
    assert r.device.taps == [(240, 1510), routine.config.LIST_BACK, routine.config.LIST_BACK]


def test_donate_skipped_outside_a_guild():
    labels.set_language("es")
    r = make([ES_LOBBY])
    assert r.donate() == routine.SKIPPED
    assert r.device.taps == []


PATROL_LOBBY = ES_LOBBY
PATROL = [Text("Tiempo de patrulla: 7:51:30", 560, 1025, 960, 1070), Text("Patrulla Rápida", 330, 1750, 660, 1800),
          Text("Reclamar", 860, 1750, 1030, 1800), Text("Tarjeta Mensual VIP", 300, 2240, 770, 2285)]


def quick(free_left, energy_left, energy="20/34"):
    return [Text(energy, 800, 65, 905, 100), Text("Reclama de inmediato las recompensas de 2 h:", 330, 920, 1110, 965),
            Text("Gratis", 470, 1450, 590, 1495), Text("x10", 950, 1450, 1010, 1500),
            Text(f"Cantidad restante: {free_left}", 340, 1575, 650, 1615),
            Text(f"Cantidad restante: {energy_left}", 790, 1575, 1100, 1615)]


def test_patrol_claims_then_uses_every_quick_patrol(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "VIDEO_SETTLE", 0)
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "parse_quick_patrol", _fake_quick)
    r = make([PATROL_LOBBY, PATROL, CLAIM_ES, PATROL, quick(1, 1), CLAIM_ES, quick(0, 1), quick(0, 0)], ads=True)
    assert r.patrol() == routine.DONE
    assert r.patrol_wait == routine.config.PATROL_CLAIM_AFTER  # claimed: the counter starts again
    assert r.device.taps == [(720, 1922), (945, 1775), (720, 2320), (495, 1775),  # patrol, claim, reward, quick
                             (530, 1472), (720, 2320), (980, 1475)]               # video, reward, energy


def test_quick_patrol_with_energy_needs_enough_energy(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "parse_quick_patrol", _fake_quick)
    r = make([PATROL_LOBBY, PATROL, PATROL, quick(0, 2, energy="7/34")])
    assert r.patrol() == routine.DONE
    assert (980, 1475) not in r.device.taps  # 7 energy < 10


def _fake_quick(img, texts):
    """parse_quick_patrol without the image check (fake screens have no pixels)."""
    from roguebot.mode_screens import QuickPatrol, _uses_left
    if not any("inmediato" in t.text for t in texts):
        return None
    video = next((t for t in texts if t.text == "Gratis" and _uses_left(t, texts) > 0), None)
    energy = next((t for t in texts if t.text == "x10" and _uses_left(t, texts) > 0), None)
    return QuickPatrol(video, energy, 10)


def test_lobby_parts_read_the_lobby_again_when_the_game_opens_a_screen(monkeypatch):
    """Live: right after the lobby showed, the game opened "Fondo del Álbum" by itself."""
    labels.set_language("es")
    album = [Text("Fondo del Álbum", 60, 260, 640, 310), Text("Reclamar todo", 1100, 2420, 1400, 2470)]
    r = make([album, VIP_LOBBY, VIP_SCREEN, VIP_SCREEN])
    assert r.vip() == routine.DONE
    assert r.nav.lobby_visits >= 2 and r.device.taps[0] == (80, 660)  # the VIP icon, not the album's button


def test_patrol_reward_is_only_claimed_after_2_hours(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "parse_quick_patrol", _fake_quick)
    assert routine.config.PATROL_CLAIM_AFTER == 2 * 3600
    early = [Text("Tiempo de patrulla: 1:59:59", 560, 1025, 960, 1070)] + PATROL[1:]
    r = make([PATROL_LOBBY, early, quick(0, 0)])
    assert r.patrol() == routine.DONE
    assert (945, 1775) not in r.device.taps  # "Reclamar" not pressed
    assert r.device.taps == [(720, 1922), (495, 1775)]  # patrol, then quick patrol only
    assert r.patrol_wait == 1  # due in 1 s: the next level opens it again


def test_a_stale_free_donation_frame_is_never_tapped_again(monkeypatch):
    """Right after the free donation the screen can still show "Gratis" for a moment while the game
    already put the 25-gem price on that button: the bot must wait to see it change."""
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "POLL_INTERVAL", 0)
    stale = DONATION_FREE
    r = make([GUILD_LOBBY, GUILD_MAP, GUILD_HALL, DONATION_FREE, DONATION_FREE, stale, stale, CLAIM_ES,
              CLAIM_ES, DONATION_PAID])
    assert r.donate() == routine.DONE
    assert r.device.taps.count((720, 1607)) == 1  # the free button, exactly once


def test_open_mode_waits_for_the_list_to_stop_after_scrolling():
    """Inertia: the first frame after the swipe can show Tower where it no longer is."""
    moving = [Text("Arena", 1250, 140, 1360, 190), Text("Tower Challenge", 1000, 920, 1300, 970)]
    r = make([MODES_SCROLLED, moving, MODES_TOP, MODES_TOP])
    r.device = SwipeDevice()
    r._open_mode(labels.TOWER)
    assert r.device.taps[-1] == (1150, 1045)  # the settled position, not (1150, 945)


def test_a_stuck_lobby_between_parts_does_not_abort_the_routine(monkeypatch):
    """Review: go_to_lobby raising between parts used to skip every remaining part."""
    r = make([])
    for part in ("vip", "daily", "mail", "arena", "dojo", "tower", "dive", "patrol", "raid", "donate", "vault"):
        monkeypatch.setattr(r, part, lambda: routine.DONE)
    monkeypatch.setattr(r, "dungeon", lambda label: routine.DONE)
    monkeypatch.setattr(r, "_back_to_modes", lambda: True)
    monkeypatch.setattr(r, "_back_to_guild", lambda: False)

    def stuck():
        raise NavigationError("Could not reach the Aventura lobby")
    r.nav.go_to_lobby = stuck
    results = r.run_parts()
    assert [p for p, _ in results] == list(routine.PARTS) and all(s == routine.DONE for _, s in results)


def test_arena_closes_a_popup_over_the_arena_screen(monkeypatch):
    labels.set_language("es")
    popup = [Text("Felicidades por tu ascenso!", 400, 920, 1040, 970),
             Text("Toca en cualquier lugar para cerrar", 440, 2440, 1000, 2480)]
    from roguebot.mode_screens import ArenaScreen
    monkeypatch.setattr(routine, "parse_arena", lambda img, texts, ocr: None if popup[0] in texts else
                        ArenaScreen(Text("Desafiar", 620, 2395, 820, 2440), 0))
    r = make([popup, []])
    monkeypatch.setattr(r, "_open_mode", lambda label: True)
    assert r.arena() == routine.DONE  # 0 tickets after the popup
    assert r.device.taps == [(720, 2460)]  # the popup's close text, not Challenge


def test_without_ads_dungeon_tickets_and_quick_patrol_videos_are_skipped(monkeypatch):
    r = make([dungeon(0, ad=True, buttons=False)])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.dungeon(labels.MINES) == routine.DONE and r.device.taps == []
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "parse_quick_patrol", _fake_quick)
    early = [Text("Tiempo de patrulla: 1:00:00", 560, 1025, 960, 1070)] + PATROL[1:]
    r = make([PATROL_LOBBY, early, quick(1, 0)])
    assert r.patrol() == routine.DONE
    assert r.device.taps == [(720, 1922), (495, 1775)]  # patrol, quick patrol; not its video


# --- Dojo Battle, Dungeon Dive, daily rewards, mail (2026-10-13) ---

def fake_dojo(img, texts, ocr):
    """parse_dojo without the ticket crop: fake screens say "tickets N"."""
    from roguebot.mode_screens import DojoScreen
    n = next((int(t.text.split()[1]) for t in texts if t.text.startswith("tickets")), None)
    if n is None:
        return None
    challenge = next((t for t in texts if t.text == "Desafío"), None)
    chest = next((t for t in texts if t.text == "RECLAMAR"), None)
    return DojoScreen(challenge, n, chest)


def dojo(tickets, chest=False):
    texts = [Text(f"tickets {tickets}", 1300, 60, 1400, 110)]
    texts.append(Text("RECLAMAR", 275, 2127, 502, 2170) if chest else
                 Text("Desafío", 620, 2390, 820, 2440) if tickets else Text("Se actualiza en:", 560, 2390, 880, 2440))
    return texts


def test_dojo_fights_while_there_are_tickets_and_claims_the_chest(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine, "parse_dojo", fake_dojo)
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    victory = [Text("VICTORIA", 600, 1000, 830, 1055), Text("Confirmar", 534, 2280, 905, 2367)]
    r = make([dojo(2), LOADING, victory, dojo(1), LOADING, victory, dojo(0, chest=True), CLAIM_ES, dojo(0)])
    monkeypatch.setattr(r, "_open_mode", lambda label: True)
    assert r.dojo() == routine.DONE
    challenge, confirm, chest = (720, 2415), (719, 2323), (388, 2148)
    assert r.device.taps == [challenge, confirm, challenge, confirm, chest, (720, 2320)]


def test_dojo_claims_the_chest_while_a_ticket_remains(monkeypatch):
    """The chest label is enough. A missing red dot on the modes button does not matter."""
    labels.set_language("es")
    monkeypatch.setattr(routine, "parse_dojo", fake_dojo)
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    victory = [Text("VICTORIA", 600, 1000, 830, 1055), Text("Confirmar", 534, 2280, 905, 2367)]
    r = make([dojo(1, chest=True), CLAIM_ES, dojo(1), LOADING, victory, dojo(0)])
    monkeypatch.setattr(r, "_open_mode", lambda label: True)
    assert r.dojo() == routine.DONE
    assert r.device.taps[0] == (388, 2148)  # chest before the remaining ticket is spent


def test_patrol_closes_quick_patrol_before_the_timed_claim(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "parse_quick_patrol", _fake_quick)
    sheet = [Text("Reclama de inmediato las recompensas de 2 h:", 330, 920, 1110, 965)]
    monkeypatch.setattr(routine, "quick_patrol_close",
                        lambda img, texts: (720, 1810) if any("inmediato" in t.text for t in texts) else None)
    r = make([PATROL_LOBBY, sheet, PATROL, CLAIM_ES, PATROL, quick(0, 0)])
    assert r.patrol() == routine.DONE
    assert r.device.taps[:3] == [(720, 1922), (720, 1810), (945, 1775)]  # open, close sheet, Reclamar


def test_skip_fights_taps_a_green_skip_once_and_stays_off_by_default(monkeypatch):
    labels.set_language("en")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    fight = [Text("Round: 1/10", 600, 170, 840, 210), Text("Skip", 800, 2380, 1000, 2460)]
    result = [Text("VICTORY!", 600, 1060, 840, 1110), Text("OK", 680, 2090, 760, 2140)]
    skip = fight[1]

    def green(img, texts):
        return skip if any(t.text == "Skip" for t in texts) else None

    monkeypatch.setattr(routine, "fight_skip", green)
    off = make([fight, result])
    assert off._fight().victory and off.device.taps == [(720, 2115)]  # default: the fight plays out
    on = make([fight, fight, result])
    on.skip_fights = True
    assert on._fight().victory
    assert on.device.taps == [(900, 2420), (720, 2115)]  # Skip once, then the result


def test_dojo_without_tickets_taps_nothing(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine, "parse_dojo", fake_dojo)
    r = make([dojo(0)])
    monkeypatch.setattr(r, "_open_mode", lambda label: True)
    assert r.dojo() == routine.DONE and r.device.taps == []


def dive(tickets):
    return [Text(f"{tickets}/2", 800, 65, 905, 100), Text("Recompensas", 600, 470, 830, 515),
            Text("Desafío", 620, 2390, 820, 2440)]


def test_dive_plays_a_level_per_ticket_win_or_lose(monkeypatch):
    labels.set_language("es")
    from roguebot.screens import LevelScreen
    results = iter([LevelScreen.DEFEAT, LevelScreen.VICTORY])
    r = make([dive(2), LOADING, dive(1), LOADING, dive(0)])
    r.play_level = lambda: next(results)
    monkeypatch.setattr(r, "_open_mode", lambda label: True)
    assert r.dive() == routine.DONE
    assert r.device.taps == [(720, 2415), (720, 2415)]  # 2 tickets, 2 runs; at 0 the button is not tapped


ES_MENU = ES_LOBBY + [Text("Correo", 336, 449, 461, 498), Text("Recompensas", 320, 1040, 480, 1070),
                      Text("Diarias", 349, 1068, 446, 1100)]
DAILY_POPUP = [Text("Recompensas Diarias", 420, 880, 1020, 935), Text("Reclamar", 551, 1138, 842, 1218),
               Text("Introducir Código", 470, 1360, 970, 1430)]
WEB_PAGE = [Text("roguelegend.io", 220, 130, 390, 170), Text("TIENDA", 780, 310, 890, 350),
            Text("Reclamar ahora!", 824, 1392, 1154, 1438)]
WEB_CLAIMED = [Text("roguelegend.io", 220, 130, 390, 170), Text("Día 1", 200, 1100, 320, 1150)]
WEB_WHEEL = [Text("roguelegend.io", 220, 130, 390, 170), Text("Giro gratis", 520, 1680, 920, 1760)]


def test_daily_rewards_claims_scrolls_for_the_free_spin_and_goes_back(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "VIDEO_SETTLE", 0)
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine.config, "SCROLL_SETTLE", 0)
    monkeypatch.setattr(routine.config, "WEB_POPUP_TIMEOUT", 0)
    monkeypatch.setattr(routine.config, "WHEEL_SPIN_TIMEOUT", 0)
    monkeypatch.setattr(routine.config, "WEB_CONTENT_TIMEOUT", 0)
    r = make(itertools.chain(
        [ES_LOBBY, ES_MENU, DAILY_POPUP, WEB_PAGE, WEB_CLAIMED, WEB_CLAIMED, WEB_CLAIMED, WEB_CLAIMED,
         WEB_CLAIMED, WEB_WHEEL],
        itertools.repeat(ES_LOBBY)))
    assert r.daily() == routine.DONE
    assert r.device.taps[:4] == [routine.config.MENU_BUTTON, (397, 1084), (696, 1178), (989, 1415)]
    assert (720, 1720) in r.device.taps  # Giro gratis, after the claim
    assert r.device.swipes  # scrolled down to find the spin
    assert r.device.backs == 0  # the lobby is on screen, so Back is not required


def test_daily_rewards_goes_back_to_the_game_even_without_the_web_claim(monkeypatch):
    """Another account may not be logged in on the web store: no "Reclamar ahora!". The lobby is left clean."""
    labels.set_language("es")
    monkeypatch.setattr(routine, "SCREEN_TIMEOUT", 0.05)
    monkeypatch.setattr(routine.config, "WEB_PAGE_TIMEOUT", 0.05)
    login = [Text("roguelegend.io", 220, 130, 390, 170), Text("Iniciar sesión", 500, 1200, 900, 1260)]
    r = make(itertools.chain([ES_LOBBY, ES_MENU, DAILY_POPUP], itertools.repeat(login)))
    r.device.apps = ["com.android.chromium"]
    assert r.daily() == routine.DONE
    assert r.device.backs >= 1 and (989, 1415) not in r.device.taps


def test_daily_rewards_closes_the_popup_when_the_browser_never_opens(monkeypatch):
    """The claim window used to stay up, so mail started on the wrong screen and the run restarted."""
    labels.set_language("es")
    monkeypatch.setattr(routine, "SCREEN_TIMEOUT", 0.05)
    monkeypatch.setattr(routine.config, "WEB_PAGE_TIMEOUT", 0.05)
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "close_button", lambda img: (720, 1500))
    r = make(itertools.chain([ES_LOBBY, ES_MENU, DAILY_POPUP], itertools.repeat(DAILY_POPUP)))
    assert r.daily() == routine.DONE
    assert r.device.taps.count((720, 1500)) >= 1
    assert (989, 1415) not in r.device.taps


EN_MENU = [Text("Patrol", 650, 1900, 790, 1945), Text("Mail", 336, 449, 461, 498),
           Text("Daily Rewards", 180, 1040, 520, 1100)]
EN_DAILY = [Text("Daily Rewards", 420, 880, 1020, 935), Text("Claim Rewards", 500, 1138, 940, 1218),
            Text("Enter Code", 470, 1360, 970, 1430)]
EN_WEB = [Text("roguelegend.io", 220, 130, 390, 170), Text("Claim Now", 824, 1392, 1154, 1438)]


def test_english_daily_rewards_taps_claim_rewards_not_enter_code(monkeypatch):
    labels.set_language("en")
    for name in ("VIDEO_SETTLE", "UI_SETTLE", "SCROLL_SETTLE", "WEB_POPUP_TIMEOUT",
                 "WHEEL_SPIN_TIMEOUT", "WEB_CONTENT_TIMEOUT"):
        monkeypatch.setattr(routine.config, name, 0)
    lobby = [Text("Patrol", 650, 1900, 790, 1945), Text("OFF", 900, 2060, 970, 2095),
             Text("START", 600, 2070, 716, 2115)]
    store = [Text("roguelegend.io", 220, 130, 390, 170)]
    page = store + [Text("Daily Rewards", 400, 700, 900, 760), Text("Collect", 560, 1480, 880, 1560)]
    collected = store + [Text("Collected", 500, 360, 940, 440), Text("Back to the shop", 480, 1760, 960, 1840)]
    shop = store + [Text("Points Store", 400, 900, 800, 960)]
    free = store + [Text("Daily Wheel", 480, 1200, 900, 1260), Text("FREE SPIN", 520, 1680, 920, 1760)]
    popup = store + [Text("Daily Wheel", 500, 280, 940, 360), Text("SPIN", 560, 1980, 880, 2060)]
    won = store + [Text("You won!", 520, 360, 920, 440), Text("Back to the shop", 480, 1760, 960, 1840)]
    landing = store + [Text("Daily Reward", 500, 900, 940, 980), Text("Claim Now!", 700, 1200, 1100, 1280)]
    r = make([lobby, EN_MENU, EN_DAILY, landing, page, page, collected, collected, shop, shop, free, popup,
              won, won, lobby, lobby, lobby])
    assert r.daily() == routine.DONE
    assert (720, 1178) in r.device.taps  # Claim Rewards
    assert (900, 1240) in r.device.taps  # Claim Now, which only opens the shop
    assert (720, 1395) not in r.device.taps  # Enter Code
    assert (720, 1520) in r.device.taps  # Collect
    assert (720, 1800) in r.device.taps  # Back to the shop, twice (collected, then you won)
    assert r.device.taps.count((720, 1800)) == 2
    assert (720, 1720) in r.device.taps  # FREE SPIN
    assert (720, 2020) in r.device.taps  # SPIN
    assert r.device.swipes
    assert r.device.backs == 0  # lobby text is the game; Back is not required


def test_daily_rewards_skips_a_missing_collect_and_a_missing_spin(monkeypatch):
    labels.set_language("en")
    for name in ("UI_SETTLE", "SCROLL_SETTLE", "WEB_POPUP_TIMEOUT", "WHEEL_SPIN_TIMEOUT", "WEB_CONTENT_TIMEOUT"):
        monkeypatch.setattr(routine.config, name, 0)
    monkeypatch.setattr(routine.config, "WEB_SCROLLS", 1)
    monkeypatch.setattr(routine, "close_button", lambda img: None)
    monkeypatch.setattr(routine, "close_button_any_size", lambda img: None)
    lobby = [Text("Patrol", 650, 1900, 790, 1945), Text("OFF", 900, 2060, 970, 2095),
             Text("START", 600, 2070, 716, 2115)]
    shop = [Text("roguelegend.io", 220, 130, 390, 170), Text("Daily Rewards", 400, 700, 900, 760),
            Text("Day 7", 200, 1100, 400, 1160)]
    r = make(itertools.chain([lobby, EN_MENU, EN_DAILY], itertools.repeat(shop)))
    r.device.apps = ["com.android.chromium"]
    assert r.daily() == routine.DONE
    assert (720, 1178) in r.device.taps  # the lobby still opens the page
    assert all(y < 1600 or y > 2100 for _, y in r.device.taps)  # no Collect, no SPIN
    assert r.device.backs >= 1  # the shop never leaves, so Back is used to get out


def test_collect_is_tapped_without_scrolling_when_it_is_already_visible():
    page = [Text("roguelegend.io", 220, 130, 390, 170), Text("Daily Rewards", 400, 700, 900, 760),
            Text("Collect", 560, 1480, 880, 1560)]
    r = make([page])
    button = r._find_collect()
    assert button is not None and button.center == (720, 1520)
    assert getattr(r.device, "swipes", []) == []


def test_collect_scrolls_back_up_after_passing_daily_rewards():
    store = [Text("roguelegend.io", 220, 130, 390, 170)]
    heading = store + [Text("Daily Rewards", 400, 200, 900, 260), Text("Day 3", 200, 400, 400, 460)]
    past = store + [Text("Daily Wheel", 400, 500, 900, 560), Text("Points Store", 400, 900, 800, 960)]
    back = store + [Text("Daily Rewards", 400, 700, 900, 760), Text("Collect", 560, 1480, 880, 1560)]
    r = make([heading, heading, heading, past, back])
    button = r._find_collect()
    assert button is not None and button.center == (720, 1520)
    assert r.device.swipes[0] == routine.config.WEB_SCROLL_DOWN_SMALL
    assert routine.config.WEB_SCROLL_UP_SMALL in r.device.swipes


def test_daily_rewards_without_a_claim_button_is_closed(monkeypatch):
    labels.set_language("en")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "close_button", lambda img: (720, 1600))
    no_claim = [Text("Daily Rewards", 420, 880, 1020, 935), Text("Enter Code", 470, 1360, 970, 1430)]
    lobby = [Text("Patrol", 650, 1900, 790, 1945), Text("OFF", 900, 2060, 970, 2095),
             Text("START", 600, 2070, 716, 2115)]
    r = make(itertools.chain([lobby, EN_MENU], itertools.repeat(no_claim)))
    assert r.daily() == routine.DONE
    assert (720, 1395) not in r.device.taps
    assert r.device.taps.count((720, 1600)) >= 1


def test_menu_entry_missing_skips_the_part(monkeypatch):
    labels.set_language("es")
    r = make([ES_LOBBY, ES_MENU[:-2]])  # menu without "Recompensas Diarias"
    assert r.daily() == routine.SKIPPED
    assert r.device.taps == [routine.config.MENU_BUTTON]


MAIL = [Text("Correo", 600, 470, 840, 525), Text("Recompensa diaria", 450, 670, 820, 710),
        Text("Eliminar todo", 300, 1815, 690, 1880), Text("Reclamar todo", 736, 1815, 1149, 1880)]


def test_mail_claims_all_and_never_deletes(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    r = make([ES_LOBBY, ES_MENU, MAIL, CLAIM_ES, MAIL])
    assert r.mail() == routine.DONE
    assert r.device.taps == [routine.config.MENU_BUTTON, (398, 473), (942, 1847), (720, 2320)]


def tower(tickets):
    return [Text("Tower of Heroes 16", 560, 245, 880, 290), Text(f"{tickets}/10", 800, 65, 905, 100),
            Text("Challenge", 620, 2395, 820, 2440)]


def tower_win(next_floor=True, label="Next Floor"):
    return [Text("VICTORY!", 600, 1000, 840, 1055), Text("Okay", 290, 1925, 640, 2005)] + (
        [Text(label, 760, 1925, 1190, 2005)] if next_floor else [])


def test_tower_goes_on_with_next_while_it_is_shown(monkeypatch):
    """Floors that show Next stay in the fight. The clear (no Next) taps Okay, then the tower screen."""
    r = make([tower(3), LOADING, tower_win(), LOADING, tower_win(label="Next"), LOADING,
              tower_win(next_floor=False), tower(0)])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    challenge, okay, nxt = (720, 2417), (465, 1965), (975, 1965)
    assert r.device.taps == [challenge, nxt, nxt, okay]


def test_tower_next_is_tapped_even_when_the_ticket_counter_says_one(monkeypatch):
    """A wrong ticket count used to tap Okay and bounce to the tower menu while Next was on screen."""
    r = make([tower(1), LOADING, tower_win(label="Next"), LOADING, tower_win(next_floor=False), tower(0)])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    assert r.device.taps[1] == (975, 1965)  # Next, not Okay at (465, 1965)


def test_tower_waits_through_loading_before_reading_the_result(monkeypatch):
    """A full-screen Loading... after a won fight is not a failure."""
    monkeypatch.setattr(routine.config, "MODE_FIGHT_TIMEOUT", 0)
    monkeypatch.setattr(routine.config, "FIGHT_LOADING_WAIT", 30)
    r = make([LOADING, LOADING, tower_win(label="Next"), LOADING])
    result = r._fight(next_floor=True)
    assert result.victory and result.next_floor is not None
    assert r.device.taps == [(975, 1965)]


def test_tower_next_floor_then_defeat_ends_the_tower(monkeypatch):
    r = make([tower(5), LOADING, tower_win(), LOADING, DEFEAT])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    assert r.device.taps == [(720, 2417), (975, 1965), (717, 2330)]


def test_tower_win_without_next_floor_reads_the_tower_screen_again(monkeypatch):
    r = make([tower(2), LOADING, tower_win(next_floor=False), tower(1), LOADING, DEFEAT])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    assert r.device.taps == [(720, 2417), (465, 1965), (720, 2417), (717, 2330)]


# The failure screenshot: Tower of Heroes 172, Floor 10, Round 1/30, Skip. Next has
# already started this fight. It is not a result and it has no back arrow.
TOWER_FLOOR_FIGHT = [Text("Tower of Heroes 172", 360, 70, 1080, 130),
                     Text("Floor 10", 520, 150, 920, 220),
                     Text("Round: 1/30", 430, 250, 1010, 310),
                     Text("Skip", 560, 2320, 880, 2400)]


def test_tower_waits_out_the_fight_next_floor_just_started(monkeypatch):
    """Budget 1 used to fail the instant Next was tapped, while Floor 10 Round 1 was already up."""
    monkeypatch.setattr(routine.config, "MAX_MODE_ACTIONS", 1)
    r = make([tower(5), LOADING, tower_win(), TOWER_FLOOR_FIGHT, TOWER_FLOOR_FIGHT, LOADING, DEFEAT])
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    assert r.device.taps == [(720, 2417), (975, 1965), (717, 2330)]


def test_tower_climbs_past_the_action_budget_until_a_defeat(monkeypatch):
    """Four towers are 40 floors. The old cap died on the next floor instead of climbing on."""
    monkeypatch.setattr(routine.config, "MAX_MODE_ACTIONS", 3)
    frames = [tower(9)]
    for _ in range(5):
        frames += [LOADING, tower_win()]
    frames += [LOADING, DEFEAT]
    r = make(frames)
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    assert r.tower() == routine.DONE
    assert r.device.taps[0] == (720, 2417)
    assert r.device.taps[1:-1] == [(975, 1965)] * 5
    assert r.device.taps[-1] == (717, 2330)


def test_tower_stops_when_next_never_leaves_the_victory_screen(monkeypatch):
    """A victory that stays up is not an endless climb. The safety budget still applies."""
    monkeypatch.setattr(routine.config, "MAX_MODE_ACTIONS", 2)
    monkeypatch.setattr(routine.config, "CHANGE_TIMEOUT", 0)
    r = make([tower(5)] + [tower_win()] * 6)
    monkeypatch.setattr(r, "_open_mode", lambda label: None)
    with pytest.raises(NavigationError, match="Tower did not finish"):
        r.tower()


def test_back_to_modes_finishes_a_tower_fight_then_leaves(monkeypatch):
    """Round 1 has no ←. Wait the fight out, dismiss the result, then the tower screen's ←."""
    menu = [Text("Tower of Heroes 172", 560, 245, 880, 290), Text("0/10", 800, 65, 905, 100),
            Text("Challenge", 620, 2395, 820, 2440)]
    r = make([TOWER_FLOOR_FIGHT, DEFEAT, menu, MODES_TOP])
    monkeypatch.setattr(routine, "close_button", lambda img: None)
    monkeypatch.setattr(routine, "back_arrow", lambda img: (120, 2447) if r.device.taps else None)
    assert r._back_to_modes()
    assert r.device.taps == [(717, 2330), (120, 2447)]


def test_press_taps_again_when_the_tap_did_not_register(monkeypatch):
    monkeypatch.setattr(routine, "PRESS_RETAP_AFTER", 0)
    r = make([tower(2), tower(2), LOADING])
    r._press(Text("Challenge", 620, 2395, 820, 2440))
    assert r.device.taps == [(720, 2417), (720, 2417), (720, 2417)]


def test_press_does_not_tap_again_once_the_next_screen_shows(monkeypatch):
    monkeypatch.setattr(routine, "PRESS_RETAP_AFTER", 0)
    panel = tower(2) + [Text("Arena Challenge", 500, 300, 900, 350)]  # the button stays visible under it
    r = make([panel])
    r._press(Text("Challenge", 620, 2395, 820, 2440), lambda texts: any(t.text == "Arena Challenge" for t in texts))
    assert r.device.taps == [(720, 2417)]


def named_skill_screen(chosen, needed, cards):
    """Skill pick with (rarity, name, description) cards."""
    texts = [Text("Select a Skill to learn!", 400, 560, 1040, 600)]
    for i, (rarity, name, desc) in enumerate(cards):
        y = 755 + 306 * i
        texts += [Text(rarity, 280, y - 15, 360, y + 15), Text(name, 465, y + 20, 900, y + 60),
                  Text(desc, 465, y + 90, 1000, y + 130)]
    return texts + [Text(f"Learn Skills ({chosen}/{needed})", 700, 2130, 1080, 2170)]


def test_dojo_and_raid_skill_picks_follow_the_build(tmp_path):
    from roguebot.build import Build
    from roguebot.skills import Catalog, MAGIC
    cards = [("Mythic", "Super Flash", "At the start of combat, Stun all enemies."),
             ("Common", "Fire Ball", "Every 2 rounds, cast a Fireball."),
             ("Legendary", "Glass Cannon", "ATK up, Max HP down."),
             ("Common", "Ice Shard", "Every 2 rounds, cast an Icicle.")]
    r = make([named_skill_screen(0, 2, cards), named_skill_screen(1, 2, cards), named_skill_screen(2, 2, cards),
              [Text("DEFEAT", 600, 880, 840, 940), Text("OK", 680, 2300, 760, 2350)]])
    r.build = Build(nature=MAGIC, order=("fire", "ice", "lightning", "shuriken", "venom", "bleed"))
    r.catalog = Catalog(tmp_path / "skills.json")
    r._fight()
    fire_y, ice_y = 755 + 306 + 90, 755 + 306 * 3 + 90
    assert r.device.taps[:2] == [(800, fire_y), (800, ice_y)]  # magic, fire first: not the rarest cards
    assert set(r.catalog.skills) >= {"fireball", "iceshard", "superflash", "glasscannon"}  # learned by the catalog


def test_raid_rerolls_when_one_wanted_skill_cannot_fill_the_pick(tmp_path):
    """Need two skills. One fire card is not enough for a fire-only build: reroll, do not take the venom."""
    from roguebot.build import Build
    from roguebot.skills import Catalog
    mixed = [("Common", "Fire Ball", "Every 2 rounds, cast a Fireball."),
             ("Common", "Venom Drip", "Every 2 rounds, cast Venom.")]
    both = [("Common", "Fire Ball", "Every 2 rounds, cast a Fireball."),
            ("Common", "Fire Wave", "Cast a wave of Fire.")]
    reroll = [Text("Reroll (1)", 280, 2100, 520, 2160)]
    r = make([named_skill_screen(0, 2, mixed) + reroll,
              named_skill_screen(0, 2, both),
              named_skill_screen(1, 2, both),
              named_skill_screen(2, 2, both),
              [Text("DEFEAT", 600, 880, 840, 940), Text("OK", 680, 2300, 760, 2350)]])
    r.build = Build(nature="magic", order=("fire",), strict=True)
    r.catalog = Catalog(tmp_path / "skills.json")
    r._fight()
    assert r.device.taps[0] == (400, 2130)
    assert r.device.taps[1][1] == 755 + 90  # the fire card, after the reroll


def test_raid_rerolls_once_when_nothing_fits_the_build(tmp_path):
    from roguebot.build import Build
    from roguebot.skills import Catalog
    unwanted = [("Common", "Venom Drip", "Every 2 rounds, cast Venom."),
                ("Rare", "Poison Cloud", "Venom damage each round.")]
    wanted = [("Common", "Fire Ball", "Every 2 rounds, cast a Fireball.")] + unwanted
    reroll = [Text("Reroll", 280, 2100, 520, 2160), Text("(1)", 360, 2168, 440, 2210)]
    r = make([named_skill_screen(0, 1, unwanted) + reroll,
              named_skill_screen(0, 1, wanted),
              named_skill_screen(1, 1, wanted),
              [Text("DEFEAT", 600, 880, 840, 940), Text("OK", 680, 2300, 760, 2350)]])
    r.build = Build(nature="magic", order=("fire",))
    r.catalog = Catalog(tmp_path / "skills.json")
    r._fight()
    assert r.device.taps[0] == (400, 2130)  # the reroll, not a venom card
    assert r.device.taps[1][1] == 755 + 90  # then the fire card


def test_run_parts_resumes_after_a_restart_at_the_part_that_broke(monkeypatch):
    r = make([MODES_TOP] * 20)
    monkeypatch.setattr(r, "_back_to_guild", lambda: False)
    calls = []

    def part(name, error=None):
        def run():
            calls.append(name)
            if error:
                raise error
            return routine.DONE
        return run
    for name in ("vip", "daily", "mail", "arena", "dojo", "dive", "patrol", "raid", "donate", "vault"):
        monkeypatch.setattr(r, name, part(name))
    monkeypatch.setattr(r, "tower", part("tower", RuntimeError("emulator froze")))
    monkeypatch.setattr(r, "dungeon", lambda label: routine.DONE)
    progress = {}
    with pytest.raises(RuntimeError):
        r.run_parts(progress)  # first attempt: the emulator froze in the tower
    assert progress["parts"][-1] == ("dojo", "done") and calls[-1] == "tower"
    calls.clear()
    monkeypatch.setattr(r, "tower", part("tower"))
    results = r.run_parts(progress)  # after the restart: from the tower on, nothing done twice
    assert calls == ["tower", "dive", "raid", "donate", "vault"]  # the patrol ran before the modes
    assert [p for p, _ in results] == list(routine.PARTS)


def test_a_part_that_keeps_breaking_the_run_is_marked_failed(monkeypatch):
    r = make([MODES_TOP] * 40)
    for name in ("vip", "daily", "mail", "arena", "dojo", "dive", "patrol", "raid", "donate", "vault", "tower"):
        monkeypatch.setattr(r, name, lambda: routine.DONE)
    monkeypatch.setattr(r, "dungeon", lambda label: (_ for _ in ()).throw(RuntimeError("frozen")))
    progress = {}
    for _ in range(routine.PART_RESTARTS + 1):
        with pytest.raises(RuntimeError):
            r.run_parts(progress)
    with pytest.raises(RuntimeError):  # mines skipped as failed; pets (same fake) breaks next
        r.run_parts(progress)
    assert ("mines", "failed") in progress["parts"]


def test_a_failed_part_left_stuck_restarts_and_resumes_at_the_next_part(monkeypatch):
    """A part that fails where the lobby can't be reached any more (a screen nothing recognizes) used to
    make every following part fail too; now the run restarts the emulator and goes on with the next part."""
    r = make([])
    for part in ("vip", "daily", "mail", "dojo", "tower", "dive", "patrol", "raid", "donate", "vault"):
        monkeypatch.setattr(r, part, lambda: routine.DONE)
    monkeypatch.setattr(r, "_back_to_guild", lambda: False)
    monkeypatch.setattr(r, "dungeon", lambda label: routine.DONE)
    monkeypatch.setattr(r, "arena", lambda: (_ for _ in ()).throw(NavigationError("Expected the arena screen")))
    monkeypatch.setattr(r, "_back_to_modes", lambda: False)

    def stuck():
        raise NavigationError("Could not reach the Aventura lobby")
    r.nav.go_to_lobby = stuck
    progress = {}
    with pytest.raises(routine.StuckError):
        r.run_parts(progress)
    assert progress["parts"][-1] == ("arena", "failed")
    r.nav.go_to_lobby = lambda: None  # after the restart
    results = r.run_parts(progress)
    assert [p for p, _ in results] == list(routine.PARTS)
