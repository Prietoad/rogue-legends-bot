"""Full routine behaviour with fake screens (no device)."""

import pytest

from roguebot import labels, routine
from roguebot.navigation import NavigationError
from roguebot.routine import Routine
from roguebot.vision import Text


class FakeDevice:
    def __init__(self):
        self.taps = []

    def tap(self, x, y, settle=0):
        self.taps.append((x, y))

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


def make(screens):
    """Routine whose captures return the given OCR text lists in order."""
    r = Routine(FakeDevice(), None, FakeNav())
    frames = iter(screens)
    r._capture = lambda: (None, next(frames))
    return r


def test_failed_part_is_reported_and_the_next_one_runs(monkeypatch):
    r = make([MODES_TOP] * 3)  # after arena, tower and mines: already back on the modes list
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
    monkeypatch.setattr(r, "patrol", lambda: routine.DONE)
    results = r.run_parts()
    assert results == [("vip", "done"), ("arena", "failed"), ("tower", "done"), ("mines", "done"), ("pets", "done"), ("patrol", "done"), ("raid", "skipped"),
                       ("donate", "done")]
    assert ran == ["ok"]
    assert r.nav.lobby_visits == 5  # stays in the modes tab; lobby after VIP (first), modes, patrol, raid, donation


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
DEFEAT = [Text("DEFEAT", 600, 1000, 830, 1055), Text("Tap to Continue", 560, 2310, 875, 2350)]


def test_dungeon_challenges_then_sweeps_after_defeat_and_watches_ads(monkeypatch):
    r = make([dungeon(1), DEFEAT,              # challenge, lose (ticket kept)
              dungeon(1), CLAIM,               # sweep, claim
              dungeon(0, ad=True, buttons=False), CLAIM,  # watch ad, claim
              dungeon(1), CLAIM,               # still lost: sweep again, claim
              dungeon(0)])                     # no tickets, no ad: done
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
    r = make([CONGRATS, CONGRATS + CLAIM, TOWER, DEFEAT, TOWER])
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
    r = make([PATROL_LOBBY, PATROL, CLAIM_ES, PATROL, quick(1, 1), CLAIM_ES, quick(0, 1), quick(0, 0)])
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


def test_patrol_reward_is_only_claimed_near_the_8_hour_cap(monkeypatch):
    labels.set_language("es")
    monkeypatch.setattr(routine.config, "UI_SETTLE", 0)
    monkeypatch.setattr(routine, "parse_quick_patrol", _fake_quick)
    early = [Text("Tiempo de patrulla: 7:49:59", 560, 1025, 960, 1070)] + PATROL[1:]
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
    for part in ("vip", "arena", "tower", "patrol", "raid", "donate"):
        monkeypatch.setattr(r, part, lambda: routine.DONE)
    monkeypatch.setattr(r, "dungeon", lambda label: routine.DONE)
    monkeypatch.setattr(r, "_back_to_modes", lambda: True)

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
