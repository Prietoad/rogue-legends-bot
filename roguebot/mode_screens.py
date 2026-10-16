"""Recognition for the full routine screens: Modes list, Arena, Tower, Crystal Mines / Pet Kingdom
and the guild raid. Pure: OCR output -> typed states. No input is sent from here."""

import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from roguebot import config, labels as L
from roguebot.vision import Ocr, Text, find, match_template, matches

_BACK_ARROW = cv2.imread(str(Path(__file__).parent / "templates" / "back_arrow.png"))
_POWER_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*([kmb]?)$")
_RATIO_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")
_LEARN_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)")
_TRAILING_NUMBER_RE = re.compile(r"(\d+)\s*$")
_SCALE = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def back_arrow(img: np.ndarray) -> tuple[int, int] | None:
    """The square ← button of menus (modes list, arena, tower, guild...). Found by image."""
    return match_template(img, _BACK_ARROW, config.BACK_ARROW_MIN_SCORE)


def parse_power(s: str) -> int | None:
    """Power values as shown in the game: "534,8k" -> 534800, "3,4m", "339k", "1045"."""
    m = _POWER_RE.match(s.strip().lower())
    if not m:
        return None
    return round(float(m.group(1).replace(",", ".")) * _SCALE[m.group(2)])


def in_guild(texts: list[Text]) -> bool:
    """The lobby shows the "Gremio"/"Guild" book button only to guild members."""
    return find(texts, L.GUILD_BUTTON, exact=True) is not None


def vip_cards_icon(texts: list[Text]) -> Text | None:
    """The lobby's "Tarjetas VIP"/"VIP Cards" icon label (left column)."""
    return next((t for t in texts if matches(t, L.VIP_CARDS, exact=True)
                 and t.center[0] < config.LOBBY_LEFT_ICONS_MAX_X), None)


def vip_claim_all(texts: list[Text]) -> Text | None:
    """The VIP cards screen's "Reclamar todo"/"Claim All" button. The screen also has purchase
    buttons ($ prices): only this exact text is ever tapped."""
    return next((t for t in texts if matches(t, L.CLAIM_ALL, exact=True) and t.center[1] > 2300), None)


def guild_hall(texts: list[Text]) -> Text | None:
    """The guild map's castle label ("Sala de / Gremio", "GuildHall"). The castle's flag over "Sala de"
    can garble it ("Sa Slde"), so its second line "Gremio" counts too, only in the castle's band
    (the lobby's own "Gremio" button is far lower)."""
    return find(texts, L.GUILD_HALL) or next(
        (t for t in texts if matches(t, L.GUILD_HALL_LOWER, exact=True)
         and config.GUILD_HALL_LABEL_Y[0] < t.center[1] < config.GUILD_HALL_LABEL_Y[1]), None)


def guild_hall_donate(texts: list[Text]) -> Text | None:
    """The guild hall's bottom "Donar"/"Donate" button (with Registro and Gestionar)."""
    return next((t for t in texts if matches(t, L.DONATE, exact=True) and t.center[1] > 2100), None)


def free_donation(texts: list[Text]) -> Text | None:
    """The donation popup's button, only while it says "Gratis"/"Free". After the free one it
    shows a gem price ("25"), which is never returned."""
    title = find(texts, L.DONATION_TITLE)
    if not title:
        return None
    return next((t for t in texts if matches(t, L.FREE, exact=True) and t.center[1] > title.center[1]), None)


@dataclass(frozen=True)
class PatrolPopup:
    claim: Text            # "Reclamar": the reward collected so far
    quick: Text            # "Patrulla Rápida": opens the quick patrol popup
    elapsed: int | None    # seconds on the "Tiempo de patrulla" counter (it stops at 8 h), None if unreadable


_PATROL_TIME_RE = re.compile(r"(\d+):(\d{2})(?::(\d{2}))?\s*$")


def patrol_seconds(text: str) -> int | None:
    """ "Tiempo de patrulla: 28:13" (mm:ss) or "7:50:00" (h:mm:ss) -> seconds."""
    m = _PATROL_TIME_RE.search(text)
    if not m:
        return None
    a, b, c = (int(g) if g else None for g in m.groups())
    return a * 3600 + b * 60 + c if c is not None else a * 60 + b


def parse_patrol(texts: list[Text]) -> PatrolPopup | None:
    """The Patrulla popup (lobby). Below it there is a "Tarjeta Mensual VIP" offer: never tapped."""
    if not find(texts, L.PATROL_TIME) or find(texts, L.QUICK_PATROL_TEXT):
        return None
    row = [t for t in texts if config.PATROL_BUTTONS_Y[0] <= t.center[1] <= config.PATROL_BUTTONS_Y[1]]
    claim = next((t for t in row if matches(t, L.PATROL_CLAIM, exact=True)), None)
    quick = next((t for t in row if matches(t, L.QUICK_PATROL)), None)
    timer = find(texts, L.PATROL_TIME)
    return PatrolPopup(claim, quick, patrol_seconds(timer.norm)) if claim and quick else None


@dataclass(frozen=True)
class QuickPatrol:
    video: Text | None        # "Gratis"/"Free" (watch a video), only while it has uses left
    energy: Text | None       # "x10" with the lightning icon, only while it has uses left
    energy_cost: int = 0


_ENERGY_COST_RE = re.compile(r"^x\s*(\d+)$")


def _uses_left(button: Text, texts: list[Text]) -> int:
    lo, hi = config.REMAINING_BELOW_BUTTON
    for t in texts:
        if matches(t, L.REMAINING) and lo < t.center[1] - button.center[1] < hi and abs(t.center[0] - button.center[0]) < 150:
            m = _TRAILING_NUMBER_RE.search(t.norm)
            return int(m.group(1)) if m else 0
    return 0


def _lightning_icon(img: np.ndarray, label: Text) -> bool:
    """The energy option shows a cyan lightning left of its "x10"; a gem price would be purple."""
    x, y = label.center
    hsv = cv2.cvtColor(img[y - 45:y + 45, max(0, x - 150):x - 35], cv2.COLOR_BGR2HSV)
    cyan = (hsv[..., 0] >= 80) & (hsv[..., 0] <= 105) & (hsv[..., 1] > 90) & (hsv[..., 2] > 150)
    return cyan.mean() > config.QUICK_PATROL_CYAN_MIN


def parse_quick_patrol(img: np.ndarray, texts: list[Text]) -> QuickPatrol | None:
    """Quick patrol popup: a free video and an energy option, each with "Remaining: N"."""
    if not find(texts, L.QUICK_PATROL_TEXT):
        return None
    video = next((t for t in texts if matches(t, L.FREE, exact=True) and _uses_left(t, texts) > 0), None)
    energy, cost = None, 0
    for t in texts:
        m = _ENERGY_COST_RE.match(t.norm)
        if m and _uses_left(t, texts) > 0 and _lightning_icon(img, t):
            energy, cost = t, int(m.group(1))
            break
    return QuickPatrol(video, energy, cost)


def is_modes_list(texts: list[Text]) -> bool:
    """The modes list, at any scroll position: at least two mode card titles, no mines/pets popup."""
    titles = [find(texts, label, exact=label is L.ARENA) for label in (L.ARENA, L.TOWER, L.MINES, L.PETS)]
    return sum(t is not None for t in titles) >= 2 and not find(texts, L.DIFFICULTY)


def mode_entry(texts: list[Text], label: L.Label) -> Text | None:
    """A mode's card title in the modes list."""
    return find(texts, label, exact=label is L.ARENA)


def mode_closed(texts: list[Text], entry: Text) -> bool:
    """The mode's card says it opens later ("Abre en 4m" under Arena around the daily reset)."""
    return any(matches(t, L.ARENA_CLOSED) and 0 < t.center[1] - entry.center[1] < config.MODE_SUBTITLE_BELOW
               for t in texts)


def _bottom_challenge(texts: list[Text]) -> Text | None:
    """The big "Challenge" button at the bottom of arena / tower / raid screens."""
    return next((t for t in texts if matches(t, L.CHALLENGE, exact=True) and t.center[1] > 2300), None)


@dataclass(frozen=True)
class ArenaScreen:
    challenge: Text
    tickets: int


def parse_arena(img: np.ndarray, texts: list[Text], ocr: Ocr) -> ArenaScreen | None:
    """Arena main screen. The ticket count is re-read from a crop (full-frame OCR misses it)."""
    title = find(texts, L.ARENA, exact=True)
    button = _bottom_challenge(texts)
    if not (title and button and title.center[1] < config.TOP_BAR_MAX_Y) or find(texts, L.ARENA_PANEL):
        return None
    digits = [t for t in ocr.read(img, config.ARENA_TICKETS_REGION) if t.norm.isdigit()]
    if not digits:
        return None
    return ArenaScreen(button, int(digits[0].norm))


@dataclass(frozen=True)
class Opponent:
    power: int
    challenge: Text


@dataclass(frozen=True)
class ArenaOpponents:
    own_power: int
    opponents: list[Opponent]
    free_refresh: Text | None


def parse_arena_opponents(texts: list[Text]) -> ArenaOpponents | None:
    if not find(texts, L.ARENA_PANEL):
        return None
    own = next((p for t in texts if config.ARENA_POWER_Y[0] < t.center[1] < config.ARENA_POWER_Y[1]
                and (p := parse_power(t.norm)) is not None and t.center[0] < config.ARENA_ROW_POWER_X[1]), None)
    if own is None:
        return None
    opponents = []
    for b in texts:
        if not (matches(b, L.CHALLENGE, exact=True) and config.ARENA_ROWS_Y[0] < b.center[1] < config.ARENA_ROWS_Y[1]):
            continue
        dy = config.ARENA_ROW_POWER_BELOW
        power = next((p for t in texts if config.ARENA_ROW_POWER_X[0] < t.center[0] < config.ARENA_ROW_POWER_X[1]
                      and dy[0] < t.center[1] - b.center[1] < dy[1] and (p := parse_power(t.norm)) is not None), None)
        if power is not None:
            opponents.append(Opponent(power, b))
    return ArenaOpponents(own, opponents, find(texts, L.FREE_REFRESH))


def pick_opponent(own_power: int, opponents: list[Opponent]) -> Opponent | None:
    """The strongest opponent that is not stronger than us, or None if all are stronger."""
    weaker = [o for o in opponents if o.power <= own_power]
    return max(weaker, key=lambda o: o.power) if weaker else None


@dataclass(frozen=True)
class TowerScreen:
    challenge: Text
    tickets: int


def parse_tower(texts: list[Text]) -> TowerScreen | None:
    """Tower main screen: tickets are the top-bar counter "13/10" (it can exceed the max)."""
    button = _bottom_challenge(texts)
    if not (find(texts, L.TOWER_TITLE) and button):
        return None
    for t in texts:
        m = _RATIO_RE.match(t.norm)
        if m and t.center[1] < config.TOP_BAR_MAX_Y:
            return TowerScreen(button, int(m.group(1)))
    return None


@dataclass(frozen=True)
class DojoScreen:
    challenge: Text | None       # gone at 0 tickets: the button shows "Se actualiza en" instead
    tickets: int
    chest: Text | None           # progress chest "RECLAMAR" (free reward), when ready


def parse_dojo(img: np.ndarray, texts: list[Text], ocr: Ocr) -> DojoScreen | None:
    """Dojo Battle main screen. Tickets are re-read from a crop (full-frame OCR misses them)."""
    title = find(texts, L.DOJO)
    if not (title and title.center[1] < config.DOJO_TITLE_MAX_Y):
        return None
    digits = [t for t in ocr.read(img, config.DOJO_TICKETS_REGION) if t.norm.isdigit()]
    if not digits:
        return None
    chest = next((t for t in texts if matches(t, L.DOJO_CHEST, exact=True)
                  and config.DOJO_CHEST_Y[0] < t.center[1] < config.DOJO_CHEST_Y[1]), None)
    return DojoScreen(_bottom_challenge(texts), int(digits[0].norm), chest)


@dataclass(frozen=True)
class DiveScreen:
    challenge: Text
    tickets: int                 # top bar "1/2"; at 0 the Challenge button stays but does nothing


def parse_dive(texts: list[Text]) -> DiveScreen | None:
    """Dungeon Dive main screen ("Ruinas Olvidadas 12": the title changes with the stage)."""
    button = _bottom_challenge(texts)
    if not (button and find(texts, L.DIVE_REWARDS, exact=True)) or find(texts, L.TOWER_TITLE):
        return None
    for t in texts:
        m = _RATIO_RE.match(t.norm)
        if m and t.center[1] < config.TOP_BAR_MAX_Y:
            return DiveScreen(button, int(m.group(1)))
    return None


def menu_entry(texts: list[Text], label: L.Label) -> Text | None:
    """An entry of the lobby's top-left ≡ menu (Correo, Recompensas Diarias...)."""
    return next((t for t in texts if matches(t, label, exact=True) and t.center[0] < config.MENU_MAX_X), None)


def daily_claim(texts: list[Text]) -> Text | None:
    """The "Recompensas Diarias" popup's "Reclamar" (it opens the game's web store in a browser)."""
    title = find(texts, L.DAILY_TITLE)
    if not title:
        return None
    return next((t for t in texts if matches(t, L.DAILY_CLAIM, exact=True) and t.center[1] > title.center[1]), None)


def mail_claim_all(texts: list[Text]) -> Text | None:
    """The mail popup's "Reclamar todo" (never "Eliminar todo" next to it)."""
    if not find(texts, L.MAIL_TITLE, exact=True):
        return None
    return find(texts, L.CLAIM_ALL, exact=True)


@dataclass(frozen=True)
class DungeonPopup:
    """Crystal Mines / Pet Kingdom popup."""
    difficulty: int | None
    tickets: int
    challenge: Text | None
    sweep: Text | None
    ad: Text | None              # "Dungeon Tickets x1" watch-ad button (only shown at 0 tickets)


def parse_dungeon_popup(texts: list[Text]) -> DungeonPopup | None:
    diff = find(texts, L.DIFFICULTY)
    if not (diff and (find(texts, L.MINES) or find(texts, L.PETS))):
        return None
    tickets = next((int(m.group(1)) for t in texts if (m := _RATIO_RE.match(t.norm))
                    and config.DUNGEON_TICKETS_Y[0] < t.center[1] < config.DUNGEON_TICKETS_Y[1]), None)
    if tickets is None:
        return None
    level = next((int(t.norm) for t in texts if t.norm.isdigit()
                  and 0 < diff.center[1] - t.center[1] < 150 and abs(t.center[0] - diff.center[0]) < 100), None)
    return DungeonPopup(level, tickets, find(texts, L.CHALLENGE, exact=True), find(texts, L.SWEEP),
                        find(texts, L.AD_TICKETS))


@dataclass(frozen=True)
class RaidScreen:
    challenge: Text
    attempts: int                # 0 once the button shows "Refreshes In"


def parse_raid(texts: list[Text]) -> RaidScreen | None:
    button = _bottom_challenge(texts)
    if not (find(texts, L.RAID_TITLE) and button):
        return None
    attempts = find(texts, L.RAID_ATTEMPTS)
    m = _TRAILING_NUMBER_RE.search(attempts.norm) if attempts else None
    return RaidScreen(button, int(m.group(1)) if m else 0)


@dataclass(frozen=True)
class SkillChoice:
    """Raid skill step: pick `needed` cards, then press Learn Skills."""
    cards: list[tuple[int, int]]  # tap points, best rarity first (ties keep top-to-bottom order)
    chosen: int
    needed: int
    learn: Text


def _rarity_rank(t: Text) -> int | None:
    return next((i for i, r in enumerate(L.RARITIES) if matches(t, r, exact=True)), None)


def parse_skill_choice(texts: list[Text]) -> SkillChoice | None:
    prompt, learn = find(texts, L.SKILL_PROMPT), find(texts, L.LEARN_SKILLS)
    m = _LEARN_RE.search(learn.norm) if learn else None
    if not (prompt and m):
        return None
    tags = sorted((t for t in texts if t.center[1] > prompt.center[1] and _rarity_rank(t) is not None
                   and config.SKILL_RARITY_X[0] <= t.center[0] <= config.SKILL_RARITY_X[1]),
                  key=lambda t: (_rarity_rank(t), t.center[1]))
    cards = [(config.SKILL_CARD_TAP_X, t.center[1] + config.SKILL_CARD_TAP_BELOW_RARITY) for t in tags]
    return SkillChoice(cards, int(m.group(1)), int(m.group(2)), learn)


@dataclass(frozen=True)
class FightResult:
    victory: bool
    button: Text                 # OK / Tap to Continue
    next_floor: Text | None = None  # tower victory: "Próximo piso" (the next fight right away, one more ticket)


def parse_fight_result(texts: list[Text]) -> FightResult | None:
    """End of an arena / tower / mines / pets / raid fight."""
    button = find(texts, L.OK, exact=True) or find(texts, L.TAP_TO_CONTINUE)
    if not button:
        return None
    if find(texts, L.VICTORY):
        return FightResult(True, button, find(texts, L.TOWER_NEXT_FLOOR))
    if find(texts, L.DEFEAT):
        return FightResult(False, button)
    return None
