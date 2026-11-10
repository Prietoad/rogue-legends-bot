"""Screen recognition: turns OCR output into typed screen states. No input is sent from here."""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from roguebot import config, labels as L
from roguebot.mode_screens import guild_screen
from roguebot.skills import RARITY_NAMES
from roguebot.vision import Ocr, Text, find, match_template, matches, parse_level_number
from roguebot.world2 import is_battle, is_shop_screen, level_tap

log = logging.getLogger(__name__)


class Mode(Enum):
    NORMAL = "normal"
    ELITE = "elite"


START_LABEL = {Mode.NORMAL: L.START_NORMAL, Mode.ELITE: L.START_ELITE}


@dataclass(frozen=True)
class Lobby:
    """Aventura tab main screen."""
    mode: Mode
    level_title: str | None      # e.g. "13. Bosque Embrujado II"
    start_button: Text           # INICIO (normal) / LISTO (elite)
    stars_button: Text | None    # "Desafio de Estrellas" (None: not unlocked on this account)
    energy: int | None           # top bar "12/32" -> 12
    has_elite: bool = True       # the elite skull toggle shows (not unlocked on new accounts)


@dataclass(frozen=True)
class Card:
    """One level entry in the Desafio de Estrellas list."""
    number: int
    header: Text
    button: Text | None          # None when locked or the button is out of view
    stars: int = 3               # earned stars (gold icons in the header); each one gives rewards
    stars_known: bool = False    # False: the icons were not read. That is not "missing stars".


def parse_lobby(texts: list[Text]) -> Lobby | None:
    if not find(texts, L.PATROL) or popup_close(texts):  # some promos are see-through: lobby texts show under them
        return None
    if find(texts, L.RESUME_ADVENTURE):  # the lobby shows under the resume dialog, which takes every tap
        return None
    # Other accounts may not have elite mode or Desafío de Estrellas yet: both are optional.
    has_elite = True
    if find(texts, L.ELITE_ON, exact=True):
        mode = Mode.ELITE
    elif find(texts, L.ELITE_OFF, exact=True):
        mode = Mode.NORMAL
    else:
        mode, has_elite = Mode.NORMAL, False
    start = find(texts, START_LABEL[mode], exact=True)
    if not start:
        return None
    return Lobby(mode, lobby_level_title(texts, start), start, star_challenge_button(texts, start), parse_energy(texts), has_elite)


def lobby_level_title(texts: list[Text], start: Text) -> str | None:
    """The centered "N. Name" above Start.

    The first text that looks like a level used to win. A side label ("38. ...") then got
    pinned after a win while the real last-unlocked title was ~76. Side columns are ignored.
    With nothing centered, the old first-match is kept so a odd layout still has a title.
    """
    mid = config.SCREEN_SIZE[0] // 2
    above_lo, above_hi = config.LOBBY_TITLE_ABOVE
    candidates = []
    for t in texts:
        if parse_level_number(t.text) is None:
            continue
        x, y = t.center
        if abs(x - mid) > config.LOBBY_TITLE_DX:
            continue
        if not (above_lo <= start.center[1] - y <= above_hi):
            continue
        candidates.append(t)
    if candidates:
        return min(candidates, key=lambda t: (abs(t.center[0] - mid), t.center[1])).text
    return next((t.text for t in texts if parse_level_number(t.text) is not None), None)


# Event tiles that share a word with Star Challenge. Never the lobby control above Start.
_EVENT_TILES = ("boss rush", "boss challenge", "wish challenge", "chest rush", "egg rush")


def _event_tile(t: Text) -> bool:
    return any(name in t.norm for name in _EVENT_TILES)


def star_challenge_button(texts: list[Text], start: Text) -> Text | None:
    """The lobby's Star Challenge / Desafío de Estrellas control, in the row just above Start.

    Not Boss Rush and not another event (Wish Challenge, Chest Rush, Egg Rush). English OCR
    splits the label into "Star" (sometimes "i-Star") and "Challenge", so a bare "Challenge"
    only counts there, with "Star" on the line above it. "Start" contains "star" but sits
    below this row, and "Starter Pack" is the left-column icon."""
    sx, sy = start.center
    above_lo, above_hi = config.STAR_CHALLENGE_ABOVE

    def in_row(t: Text) -> bool:
        x, y = t.center
        return above_lo <= sy - y <= above_hi and abs(x - sx) <= config.STAR_CHALLENGE_DX and not _event_tile(t)

    phrase = [t for t in texts if matches(t, L.STARS_BUTTON) and in_row(t)]
    if phrase:
        return min(phrase, key=lambda t: abs(t.center[0] - sx))
    for t in texts:
        if t.norm != "challenge" or not in_row(t):
            continue
        if any(_star_line(o, t) for o in texts):
            return t
    return None


def _star_line(label: Text, challenge: Text) -> bool:
    """The "Star" half of a split "Star Challenge" label: just above the "Challenge" line."""
    if "star" not in label.norm or "starter" in label.norm or _event_tile(label):
        return False
    return (abs(label.center[0] - challenge.center[0]) <= config.STAR_WORD_DX
            and 0 <= challenge.center[1] - label.center[1] <= config.STAR_WORD_ABOVE)


def is_star_list(texts: list[Text]) -> bool:
    return bool(find(texts, L.STAR_LIST_TITLE) and find(texts, L.LIST_REWARDS)
                and not find(texts, L.PATROL))


@dataclass(frozen=True)
class EliteDialog:
    """"Modo Élite" popup shown after LISTO: INICIO with an energy cost of 5, 10 or 15."""
    start_button: Text
    cost: int


_COST_RE = re.compile(r"^x\s*(\d+)$")
_ENERGY_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")


def parse_energy(texts: list[Text]) -> int | None:
    """Current energy from the top bar counter, e.g. "12/32" -> 12."""
    for t in texts:
        m = _ENERGY_RE.match(t.norm)
        if m and t.center[1] < config.TOP_BAR_MAX_Y and _in_range(t.center[0], config.ENERGY_X):
            return int(m.group(1))
    return None


def parse_elite_dialog(texts: list[Text]) -> EliteDialog | None:
    start = find(texts, L.START_NORMAL, exact=True)
    if not (find(texts, L.ELITE_DIALOG_TITLE) and start):
        return None
    for t in texts:
        m = _COST_RE.match(t.norm)
        if m and 0 < t.center[1] - start.center[1] < config.COST_BELOW_START_MAX:
            return EliteDialog(start, int(m.group(1)))
    return None


@dataclass(frozen=True)
class EnergyOffers:
    """Free ways to get energy in the energy popup. The gem-priced button is never included."""
    free_pack: Text | None             # Daily Pack "Free" button
    video: tuple[int, int] | None      # yellow "watch a video" button that still has chances left
    videos_left: int = 0               # "Chances Left Today: N" of the video button (shown even during a cooldown)


def _yellow_button(img: np.ndarray, center: tuple[int, int]) -> bool:
    """The video button is yellow; the gem-priced one next to it is green."""
    x, y = center
    roi = img[y - 35:y + 35, x - 120:x + 120].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    return float(((r > 200) & (g > 160) & (b < 80)).mean()) > config.VIDEO_YELLOW_MIN_FRACTION


def _chances_left(label: Text, texts: list[Text]) -> int | None:
    """N of "Chances Left Today: N". Spanish puts N on the line below ("Intentos Restantes Hoy:" / "2")."""
    m = re.search(r"(\d+)$", label.norm)
    if m:
        return int(m.group(1))
    below = [t for t in texts if t.norm.isdigit() and 0 < t.center[1] - label.center[1] <= config.CHANCES_NUMBER_BELOW
             and abs(t.center[0] - label.center[0]) < config.CHANCES_NUMBER_DX]
    return int(min(below, key=lambda t: abs(t.center[0] - label.center[0])).norm) if below else None


def parse_energy_popup(img: np.ndarray, texts: list[Text]) -> EnergyOffers | None:
    if not find(texts, L.ENERGY_POPUP_TITLE):
        return None
    video, videos_left = None, 0
    for t in texts:
        left = _chances_left(t, texts) if matches(t, L.ENERGY_CHANCES) else None
        if left:
            button = (t.center[0], t.center[1] + config.VIDEO_BELOW_CHANCES)
            if _yellow_button(img, button):
                video, videos_left = button, left
                break
            if t.center[0] < config.SCREEN_SIZE[0] // 2:  # the video button is the left one (gems: right)
                videos_left = left
    free_pack = None if find(texts, L.DAILY_PACK_CLAIMED) else find(texts, L.ENERGY_FREE, exact=True)
    return EnergyOffers(free_pack, video, videos_left)


def update_required(texts: list[Text]) -> bool:
    """The game refuses to start until it is updated from Google Play ("Nueva Actualización")."""
    return find(texts, L.UPDATE_REQUIRED) is not None


def resume_prompt(texts: list[Text]) -> Text | None:
    """The "Continue Adventure? You have an ongoing adventure. Resume?" dialog (a run was interrupted,
    e.g. the game was closed mid-level): its OK button. Its energy is already spent, so resume it."""
    title = find(texts, L.RESUME_ADVENTURE)
    if not title:
        return None
    return next((t for t in texts if matches(t, L.OK, exact=True) and t.center[1] > title.center[1]), None)


def is_loading(texts: list[Text]) -> bool:
    return find(texts, L.LOADING) is not None


_CLOSE_X = cv2.imread(str(Path(__file__).parent / "templates" / "close_x.png"))
_TUTORIAL_HAND = cv2.imread(str(Path(__file__).parent / "templates" / "tutorial_hand.png"))


def close_button(img: np.ndarray) -> tuple[int, int] | None:
    """The round ✕ that closes popups (energy, elite dialog, daily login...). Found by image, so it
    works in any language; it only ever closes, so it is always safe to tap."""
    return match_template(img, _CLOSE_X, config.CLOSE_X_MIN_SCORE)


def close_button_any_size(img: np.ndarray) -> tuple[int, int] | None:
    """The same ✕ drawn at another size (unknown popups, e.g. new seasonal events). Slower than
    close_button: only for popups nothing else recognized."""
    for scale in config.CLOSE_X_SCALES:
        found = match_template(img, cv2.resize(_CLOSE_X, None, fx=scale, fy=scale), config.CLOSE_X_MIN_SCORE)
        if found:
            return found
    return None


def outside_tap_clear(texts: list[Text]) -> bool:
    """No text but the footer tab label or a "para cerrar" hint near POPUP_OUTSIDE_TAP: tapping it can't
    hit a popup's button (a price, a purchase)."""
    x, y = config.POPUP_OUTSIDE_TAP
    m = config.OUTSIDE_TAP_CLEARANCE
    return not any(t.x1 - m < x < t.x2 + m and t.y1 - m < y < t.y2 + m
                   and not matches(t, L.LOBBY_TAB, exact=True) and not matches(t, L.POPUP_CLOSE) for t in texts)


def tutorial_hand(img: np.ndarray) -> tuple[int, int] | None:
    """Where a forced tutorial's pointing hand points (e.g. at a newly unlocked lobby button).
    While it shows, the game ignores every other tap."""
    center = match_template(img, _TUTORIAL_HAND, config.TUTORIAL_HAND_MIN_SCORE)
    if center is None:
        return None
    dx, dy = config.TUTORIAL_TAP_OFFSET
    return center[0] + dx, center[1] + dy


def footer_visible(img: np.ndarray) -> bool:
    """Main screens show the bottom tab bar at full brightness; popups darken it. Every tab but the
    selected one must show its color (one sample alone matched a dark teal level board, and the bot took
    it for a main screen; checking only the first and last tab missed the footer on the Mascotas tab)."""
    matching = 0
    for (x1, x2), color in config.FOOTER_SAMPLES:
        mean = img[config.FOOTER_Y[0]:config.FOOTER_Y[1], x1:x2].reshape(-1, 3).mean(0)
        matching += bool(np.abs(mean - color).max() < config.FOOTER_COLOR_TOLERANCE)
    return matching >= config.FOOTER_MIN_TABS


def lobby_behind(texts: list[Text]) -> bool:
    """Lobby labels (footer "Aventura", "Patrulla", "Gremio", "Modos") show, dimmed, under lobby popups
    and never on a level board: such a screen is a popup, never a level to play (a seasonal event
    popup once looked like a level event and the bot tapped it as one)."""
    return bool(find(texts, L.PATROL) or find(texts, L.GUILD_BUTTON, exact=True) or find(texts, L.MODES_BUTTON, exact=True)
                or any(matches(t, L.LOBBY_TAB, exact=True) and t.center[1] > config.FOOTER_Y[0] for t in texts))


def popup_close(texts: list[Text]) -> Text | None:
    """Lobby promo popups ("Toca para cerrar", "Toca en cualquier lugar para cerrar").

    Only this text is ever tapped on a popup: they contain purchase buttons.
    """
    return find(texts, L.POPUP_CLOSE)


class LevelScreen(Enum):
    VICTORY = "victory"          # "¡VICTORIA!" + Continuar
    DEFEAT = "defeat"            # "DERROTA" + Continuar
    DOUBLE_REWARD = "double_reward"  # end screen "x2 Rewards" ad button; tapped before Continuar
    REVIVE = "revive"            # "¡Revivir ahora!" on death: free video revive (never the gem button)
    SKILL_PICK = "skill_pick"    # "¡SUBISTE DE NIVEL!" / "¡SUBIDA DE PODER!"
    BOARD_READY = "board_ready"  # red dice button active
    AUTO_PLAY = "auto_play"      # green dice "Toca para Detener": the game rolls by itself; never tap it (stops it)
    FIGHT = "fight"              # "Ronda N/30", plays by itself
    EVENT = "event"              # tile event; leave, or campfire: upgrade unless HP is under 40%
    SHOP = "shop"                # shop tile; we buy nothing and press "Salir"
    LEAVE = "leave"              # screens we just exit: a lone "Salir"
    FORTUNE_TELLER = "fortune_teller"  # "Adivino": 100/70/40% balls paid with orbs; tap = its back arrow
    MONK = "monk"                # "Monje Sabio" / "Wise Monk": spin twice, then leave. HP is ignored.
    CONTINUE = "continue"        # screen whose only action is one button (see labels.CONTINUE_BUTTONS)
    DICE_DUEL = "dice_duel"      # "¡Batalla de Dados!" 21-style minigame
    FLIP_CARDS = "flip_cards"    # "Excavar en Busca de Tesoro" memory minigame; flip face-down cards in order
    UNKNOWN = "unknown"          # transitions/animations, or a screen not handled yet


@dataclass(frozen=True)
class LevelState:
    kind: LevelScreen
    tap: tuple[int, int] | None = None  # where to tap to advance, None = just wait


_COUNTER_RE = re.compile(r"^(\D+?)\s*(\d+)\s*/\s*(\d+)$")  # "ronda 3/30", "yo 12 / 21"


def _counter(texts: list[Text], prefix: L.Label) -> int | None:
    """Value N of a "<prefix> N / M" text, e.g. the fight round or the dice duel score."""
    for t in texts:
        m = _COUNTER_RE.match(t.norm)
        if m and m.group(1).strip() in prefix.variants:
            return int(m.group(2))
    return None


def dice_ready(img: np.ndarray) -> bool:
    """The roll button is bright red when it can be pressed and grey while the dice rolls."""
    x1, y1, x2, y2 = config.DICE_REGION
    roi = img[y1:y2, x1:x2].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    return float(((r > 170) & (g < 90) & (b < 90)).mean()) > config.DICE_RED_MIN_FRACTION


def dice_auto(img: np.ndarray) -> bool:
    """Auto-play (turned on by holding the dice) shows the dice button lime green."""
    x1, y1, x2, y2 = config.DICE_REGION
    roi = img[y1:y2, x1:x2].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    return float(((g > 150) & (r > 120) & (b < 90) & (g > r)).mean()) > config.DICE_GREEN_MIN_FRACTION


_SPEED_RE = re.compile(r"x\s*([124])$")


def _skill_banner(texts: list[Text]) -> bool:
    """The short "POWER UP!" / "LEVEL UP!" ribbon, not those words inside a card description."""
    for t in texts:
        n = t.norm.strip("!¡ ")
        if len(n) > 28:
            continue
        if n in ("power up", "level up", "subiste de nivel", "subida de poder"):
            return True
    return False


def game_speed(texts: list[Text]) -> int | None:
    """Speed shown on the bottom-left button (x1, x2 or VIP x4), or None if that label is absent.

    The button shows the speed that is selected. "VIP Active" is only drawn while x4 is selected,
    so it is not how VIP is detected.
    """
    for t in texts:
        m = _SPEED_RE.search(t.norm)
        if m and _in_range(t.center[0], config.SPEED_LABEL_X) and _in_range(t.center[1], config.SPEED_LABEL_Y):
            return int(m.group(1))
    return None


def _dice_duel(texts: list[Text]) -> tuple[int, int] | None:
    """"¡Batalla de Dados!" (reach 21 without going over): roll below DUEL_STAND_AT, else stand."""
    roll, stand = find(texts, L.DUEL_ROLL, exact=True), find(texts, L.DUEL_STAND, exact=True)
    score = _counter(texts, L.DUEL_SCORE_PREFIX)
    if not (roll and stand and score is not None):
        return None
    return (roll if score < config.DUEL_STAND_AT else stand).center


def _face_down(img: np.ndarray, center: tuple[int, int]) -> bool:
    """Card-flip minigame: a face-down card shows a big light-blue "?" in its center."""
    x, y = center
    roi = img[y - 60:y + 60, x - 50:x + 50].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    return float(((b > 200) & (g > 150) & (r < 150)).mean()) > config.FLIP_FACE_DOWN_MIN_FRACTION


def _in_range(v: int, r: tuple[int, int]) -> bool:
    return r[0] <= v <= r[1]


def _option_enabled(img: np.ndarray, label: Text) -> bool:
    """A used-up option ("Read" after failing it) turns its icon grey."""
    x, y = label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL
    roi = cv2.cvtColor(img[y - 120:y + 120, x - 120:x + 120], cv2.COLOR_BGR2HSV)
    return roi[..., 1].mean() > config.EVENT_DISABLED_MAX_SATURATION


# "107,2k/152,5k" (comma or dot decimals). A k/m/b suffix is required so the energy "12/32" never matches.
_HP_LINE = re.compile(r"^(\d+(?:[.,]\d+)?)([kmb])?/(\d+(?:[.,]\d+)?)([kmb])?$")
_HEAL_BODY = re.compile(r"(restaura\w*|restaur\w*|heal|restore|curar\w*).{0,30}hp|hp.{0,20}(restaura|heal|restore|curar)")
_UPGRADE_BODY = re.compile(
    r"(mejora\w*|upgrade|improve|level up).{0,40}(habilidad|skill)"
    r"|(habilidad|skill).{0,30}(existente|existing)")
_HP_SCALE = {None: 1.0, "k": 1e3, "m": 1e6, "b": 1e9}


def _scaled_hp(num: str, suffix: str | None) -> float | None:
    try:
        value = float(num.replace(",", "."))
    except ValueError:
        return None
    return value * _HP_SCALE[suffix]


def parse_hp_ratio(texts: list[Text]) -> float | None:
    """Current/max HP from the top-bar heart line, e.g. "107,2k/152,5k" -> 0.703.

    None when that line is missing or unreadable. The campfire heal option's "39% de HP" is how much
    the rest restores, never the current HP, and it sits far below the top bar.
    """
    for t in texts:
        if t.center[1] > config.TOP_BAR_MAX_Y or not _in_range(t.center[0], config.HP_X):
            continue
        m = _HP_LINE.match(t.norm.replace(" ", ""))
        if not m or not (m.group(2) or m.group(4)):
            continue
        current, maximum = _scaled_hp(m.group(1), m.group(2)), _scaled_hp(m.group(3), m.group(4))
        if current is None or maximum is None or maximum <= 0:
            continue
        return current / maximum
    return None


def _column_blob(label: Text, texts: list[Text]) -> str:
    """The option label plus the body text in its column (below the icon)."""
    parts = [label.norm]
    for t in texts:
        if t.center[1] <= label.center[1]:
            continue
        if abs(t.center[0] - label.center[0]) <= config.EVENT_COLUMN_X:
            parts.append(t.norm)
    return " ".join(parts)


def _is_heal_option(label: Text, blob: str) -> bool:
    """Campfire heart. Spanish label seen: "Descansar". English is matched from the body ("restore/heal … HP")."""
    return matches(label, L.CAMPFIRE_REST, exact=True) or _HEAL_BODY.search(blob) is not None


def _is_upgrade_option(label: Text, blob: str) -> bool:
    """Campfire book. Spanish label seen: "Entrenar". English is matched from the body ("upgrade/improve … skill")."""
    return matches(label, L.CAMPFIRE_TRAIN, exact=True) or _UPGRADE_BODY.search(blob) is not None


class _CampfireWait:
    """This frame is the campfire, but the upgrade label is not readable and HP is not under 40%.

    The caller waits and reads again. It must not fall through to the heal button.
    """


_CAMPFIRE_WAIT = _CampfireWait()


def _campfire_label(labels: list[Text], texts: list[Text]) -> Text | _CampfireWait | None:
    """Which campfire option to tap, or None if this event is not the rest/campfire.

    Default is the skill upgrade. Restore HP only when the top-bar heart line is under 40%.
    If that line cannot be read, upgrade: do not invent an HP from the heal amount.
    If the upgrade label is missing on this frame and HP is not under 40%, wait. Healing at
    full HP because the book had not rendered yet (the frame right after a skill pick) is the bug.
    """
    heal = upgrade = None
    for label in labels:
        blob = _column_blob(label, texts)
        if upgrade is None and _is_upgrade_option(label, blob):
            upgrade = label
        elif heal is None and _is_heal_option(label, blob):
            heal = label
    if heal is None and upgrade is None:
        return None
    ratio = parse_hp_ratio(texts)
    if ratio is not None and ratio < config.CAMPFIRE_HEAL_BELOW and heal is not None:
        log.info("Campfire: HP %.1f%% < 40%%, restoring HP", ratio * 100)
        return heal
    if upgrade is not None:
        if ratio is None:
            log.info("Campfire: HP unreadable, upgrading skill")
        else:
            log.info("Campfire: HP %.1f%%, upgrading skill", ratio * 100)
        return upgrade
    if ratio is None:
        log.info("Campfire: HP unreadable and the skill upgrade is not readable; waiting")
    else:
        log.info("Campfire: HP %.1f%%, skill upgrade not readable; not healing", ratio * 100)
    return _CAMPFIRE_WAIT


def campfire_non_heal_tap(img: np.ndarray, texts: list[Text]) -> tuple[int, int] | None:
    """A campfire tap that is not the heal, after the upgrade label never showed.

    Prefers a label that reads as the upgrade, else the right-hand option (the book sits on
    the right). If the only label is the heal, mirror it across the screen: the two icons
    are opposite each other, and that point is the upgrade icon, not the heart.
    """
    labels = [t for t in texts if _in_range(t.center[1], config.EVENT_LABEL_Y)]
    if not labels:
        return None
    heal = None
    for label in labels:
        blob = _column_blob(label, texts)
        if _is_upgrade_option(label, blob):
            return label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL
        if heal is None and _is_heal_option(label, blob):
            heal = label
    others = [t for t in labels if t is not heal]
    if others:
        label = max(others, key=lambda t: t.center[0])
        return label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL
    if heal is None:
        return None
    return config.SCREEN_SIZE[0] - heal.center[0], heal.center[1] + config.EVENT_ICON_BELOW_LABEL


def _event_option(img: np.ndarray, texts: list[Text]) -> tuple[int, int] | None:
    """Tile event (title band + option labels above icons): where to tap, or None if not an event.

    Campfire ("Un Momento de Descanso"): upgrade the skill, unless the top-bar HP is under 40%.
    Other events: "Salir" (leave) when offered, else the leftmost option that is not greyed out.
    """
    has_title = any(_in_range(t.center[1], config.EVENT_TITLE_Y)
                    and abs(t.center[0] - config.SCREEN_SIZE[0] // 2) < config.EVENT_TITLE_CENTER_TOLERANCE
                    for t in texts)
    labels = [t for t in texts if _in_range(t.center[1], config.EVENT_LABEL_Y)]
    if not (has_title and labels):
        return None
    labels = [t for t in labels if _option_enabled(img, t)] or labels
    label = _campfire_label(labels, texts)
    if label is _CAMPFIRE_WAIT:
        return _CAMPFIRE_WAIT
    if label is None:
        label = next((t for t in labels if matches(t, L.LEAVE, exact=True)), min(labels, key=lambda t: t.center[0]))
    return label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL


def monk_spin_button(texts: list[Text]) -> Text | None:
    """The GIRAR/SPIN button, not a higher misread of the same word.

    The button center sits near y=2280. OCR sometimes also returns an exact "SPIN"/"GIRAR"
    near y=2080, in the gap under the subtitle; tapping that misses and the button stays.
    Speech and the subtitle are higher still (~1850) and already excluded by MONK_SPIN_MIN_Y.
    Several hits: the lowest one is the button.
    """
    hits = [t for t in texts if matches(t, L.MONK_SPIN, exact=True) and t.center[1] > config.MONK_SPIN_MIN_Y]
    return max(hits, key=lambda t: t.center[1]) if hits else None


def classify_level_screen(img: np.ndarray, texts: list[Text], build=None, board: str | None = None,
                          skills=None, min_skill_price: int | None = None,
                          rolls: tuple[int, int] | None = None,
                          left_shop_tokens: int | None = None) -> LevelState:
    if guild_screen(texts):  # guild map / personal vault: labels look like an event, they are not a level
        return LevelState(LevelScreen.UNKNOWN)
    if footer_visible(img):  # a main screen (lobby...), never a level: its texts can look like an event
        return LevelState(LevelScreen.UNKNOWN)
    proceed = find(texts, L.CONTINUE, exact=True)
    double = find(texts, L.DOUBLE_REWARD)
    if proceed and double:  # always double the reward with the (VIP-skipped) ad before continuing
        return LevelState(LevelScreen.DOUBLE_REWARD, double.center)
    # Dive / tower ends: Continue, Confirm, Okay, or "Tap to Continue".
    end = (proceed or find(texts, L.CONFIRM, exact=True) or find(texts, L.OK, exact=True)
           or find(texts, L.TAP_TO_CONTINUE))
    if end and find(texts, L.DEFEAT):
        return LevelState(LevelScreen.DEFEAT, end.center)
    if end and find(texts, L.VICTORY):
        return LevelState(LevelScreen.VICTORY, end.center)
    pick = find(texts, L.SKILL_PROMPT)
    banner = _skill_banner(texts)
    if pick or banner:
        # Horizontal rows: rarity tag on the left, name to its right. World 2 cards sit
        # further left than the original column, so the band is wider than the shop's.
        # "Select a Skill to learn!" is this screen even when a tag was not read: the
        # player picks, and it must not fall through to the unknown-event catcher.
        floor = (pick.center[1] - 30) if pick else 400
        tags = [t for t in texts if t.center[1] > floor and rarity_name(t)
                and _in_range(t.center[0], config.SKILL_PICK_RARITY_X)]
        if tags:
            first = min(tags, key=lambda t: t.center[1])
            return LevelState(LevelScreen.SKILL_PICK, (config.SCREEN_SIZE[0] // 2,
                                                       first.center[1] + config.SKILL_TAP_BELOW_RARITY))
        if pick:
            return LevelState(LevelScreen.SKILL_PICK, None)
    if proceed and find(texts, L.LEVEL_MODIFIERS, exact=True):  # elite level intro: modifiers + Continue
        return LevelState(LevelScreen.CONTINUE, proceed.center)
    if find(texts, L.MONK):  # before GIRAR/SPIN is taken as a generic continue: the player spins twice
        spin = monk_spin_button(texts)
        if spin:
            return LevelState(LevelScreen.MONK, spin.center)
        leave = find(texts, L.LEAVE, exact=True)
        return LevelState(LevelScreen.MONK, leave.center if leave else None)
    button = find(texts, L.EXACT_BUTTONS, exact=True)
    if button:
        return LevelState(LevelScreen.CONTINUE, button.center)
    for label in L.CONTINUE_BUTTONS:
        button = find(texts, label)
        if button:
            return LevelState(LevelScreen.CONTINUE, button.center)
    duel = _dice_duel(texts)
    if duel:
        return LevelState(LevelScreen.DICE_DUEL, duel)
    if find(texts, L.FLIP_CARDS_PROMPT):
        card = next((c for c in config.FLIP_CARDS if _face_down(img, c)), None)
        return LevelState(LevelScreen.FLIP_CARDS, card)
    if find(texts, L.FORTUNE_TELLER):
        return LevelState(LevelScreen.FORTUNE_TELLER, config.FORTUNE_TELLER_BACK)
    leave = find(texts, L.LEAVE, exact=True)
    if leave and find(texts, L.BLACK_MARKET):  # never seen: its prices may be gems, so just leave
        return LevelState(LevelScreen.LEAVE, leave.center)
    if is_shop_screen(texts):  # SHOP header and/or Reroll + Exit. The greeting is not the title.
        reroll = find(texts, L.SHOP_REROLL)
        shop_tap = leave.center if leave else (reroll.center if reroll else None)
        return LevelState(LevelScreen.SHOP, shop_tap)
    # World 2 path forks and events. None on World 1 screens, so campfire and "leave" stay as they were.
    w2 = level_tap(img, texts, build=build, board=board, skills=skills, min_skill_price=min_skill_price,
                   rolls=rolls, left_shop_tokens=left_shop_tokens)
    if w2:
        return LevelState(LevelScreen.EVENT, w2)
    event_option = _event_option(img, texts)
    if event_option is _CAMPFIRE_WAIT:
        return LevelState(LevelScreen.EVENT, None)  # reread; do not tap the heart
    if event_option:
        return LevelState(LevelScreen.EVENT, event_option)
    if leave:  # e.g. "Meditación completa" -> "Salir"
        return LevelState(LevelScreen.LEAVE, leave.center)
    # Revive popup (over a fight). Checked late: skill/shop cards can mention "Revive" too.
    if find(texts, L.REVIVE_PROMPT):
        free = find(texts, L.REVIVE_FREE, exact=True)
        if free and _yellow_button(img, free.center):  # the video button is yellow; the gem one green
            return LevelState(LevelScreen.REVIVE, free.center)
        return LevelState(LevelScreen.UNKNOWN)  # no free revive left: let the countdown run out
    # "Round 10/30 Wave 3/3" is one line. The counter regex requires the whole line to be
    # "round N/M", so the wave suffix used to miss and the fight was tapped through.
    if _counter(texts, L.FIGHT_ROUND) is not None or is_battle(texts):
        return LevelState(LevelScreen.FIGHT)
    # Late, like the red dice: lucky wheels and offers can be green there too, but their texts match first.
    if dice_auto(img):
        return LevelState(LevelScreen.AUTO_PLAY)
    if dice_ready(img):
        return LevelState(LevelScreen.BOARD_READY, config.DICE_BUTTON)
    return LevelState(LevelScreen.UNKNOWN)


def card_stars(img: np.ndarray, header: Text) -> int:
    """Gold star icons (earned) right of a card header; missing ones are grey-blue.

    The count is only meaningful when `header_stars` says the read is known. A short count
    from a sample that missed the icons is not a level with missing stars.
    """
    count, _known = header_stars(img, header)
    return count


def _star_samples(img: np.ndarray, y: int) -> list[str | None]:
    kinds = []
    for x in config.STAR_ICONS_X:
        if y < 12 or x < 12 or y + 12 >= img.shape[0] or x + 12 >= img.shape[1]:
            kinds.append(None)
            continue
        b, g, r = img[y - 10:y + 10, x - 10:x + 10].reshape(-1, 3).mean(0)
        kinds.append(_star_kind(float(b), float(g), float(r)))
    return kinds


def _star_gaps_dark(img: np.ndarray, y: int) -> bool:
    """True when the gaps between the three star slots are the dark title bar.

    A real row of stars (filled or empty) has dark bar between the icons (~80).
    The cream card body is pale in the gaps too (~230), and so is a pale border,
    so those rows are not three empty stars.
    """
    xs = config.STAR_ICONS_X
    if y < 6 or y + 6 >= img.shape[0]:
        return False
    for x in ((xs[0] + xs[1]) // 2, (xs[1] + xs[2]) // 2):
        if x < 6 or x + 6 >= img.shape[1]:
            return False
        if float(img[y - 4:y + 4, x - 4:x + 4].mean()) >= config.STAR_GAP_MAX_MEAN:
            return False
    return True


def header_stars(img: np.ndarray, header: Text) -> tuple[int, bool]:
    """(filled stars, known). Known only when all three icons were read.

    Filled stars are gold (older art) or purple (current art). An empty star is pale.
    The header text box is not always on the icon row, so a few rows around it are tried.
    A row of filled stars wins over a later all-pale row: the cream card body sits just
    below the title bar and used to be accepted as 0/3 before the icons were looked at.
    An all-pale row counts only when it is actually on the dark title bar.
    Unknown (the second value False) must not be treated as "fewer than 3".
    """
    y0 = int(header.center[1])
    filled = None
    empty = None
    for dy in range(0, config.STAR_HEADER_SEARCH + 1, 8):
        for sign in (1, -1) if dy else (1,):
            yy = y0 + sign * dy
            kinds = _star_samples(img, yy)
            if not all(k in ("gold", "grey") for k in kinds):
                continue
            earned = sum(k == "gold" for k in kinds)
            if earned:
                filled = earned if filled is None else max(filled, earned)
            elif empty is None and _star_gaps_dark(img, yy):
                empty = 0
    if filled is not None:
        return filled, True
    if empty is not None:
        return 0, True
    return 3, False


def _star_kind(b: float, g: float, r: float) -> str | None:
    """'gold' earned star (gold or purple), 'grey' missing star, or None (background and text).

    A 20 px window mixes the icon with the dark title bar, so a purple star's average is
    dimmer than the icon itself and a pale star is not pure white. Those diluted samples
    still have to be told apart: purple keeps a low green, the empty star does not.
    """
    if r > 180 and b < 160 and r - b > 80:
        return "gold"
    if b > 180 and g > 160 and abs(r - b) < 50:
        return "grey"
    # Purple filled star, including one averaged with the navy bar.
    if b > 100 and g < 90 and b > g + 45 and b > r * 0.9 and r > 50:
        return "gold"
    # Pale empty star averaged with the same bar: the channels stay close and green stays up.
    if b > 110 and g > 90 and r > 80 and abs(r - b) < 50 and abs(g - b) < 45:
        return "grey"
    return None


def _green_check(img: np.ndarray, y: int) -> bool:
    """A green check at the right of an objective row. The green condition text is further left."""
    x0, x1 = config.OBJECTIVE_CHECK_X
    y = int(y)
    if y < 10 or y + 10 >= img.shape[0] or x0 < 0 or x1 > img.shape[1]:
        return False
    roi = img[y - 10:y + 10, x0:x1].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    green = (g > 160) & (r < 190) & (b < 140) & (g > r + 25) & (g > b + 40)
    return float(green.mean()) >= config.OBJECTIVE_CHECK_MIN_FRACTION


def objective_tally(img: np.ndarray, texts: list[Text], y0: float, y1: float) -> tuple[int, int, int]:
    """(completed, missed, rows) for objective lines between two y positions.

    A row is complete when it has a green check or a filled (gold/purple) star. A pale star
    with no check is a miss. Rows within 40 px are the same line read twice.
    """
    x0, x1 = config.OBJECTIVE_TEXT_X
    lines: list[Text] = []
    for t in texts:
        if not (y0 < t.center[1] < y1 and x0 <= t.x1 <= x1):
            continue
        if any(abs(t.center[1] - kept.center[1]) < 40 for kept in lines):
            continue
        lines.append(t)
    done = missed = 0
    for t in lines:
        sx, sy = int(t.x1 - config.OBJECTIVE_STAR_DX), int(t.center[1])
        star = None
        if 8 <= sy < img.shape[0] - 8 and 8 <= sx < img.shape[1] - 8:
            b, g, r = img[sy - 8:sy + 8, sx - 8:sx + 8].reshape(-1, 3).mean(0)
            star = _star_kind(float(b), float(g), float(r))
        if _green_check(img, t.center[1]) or star == "gold":
            done += 1
        elif star == "grey":
            missed += 1
    return done, missed, len(lines)


def _with_objectives(img: np.ndarray, texts: list[Text], header: Text, button_y: float,
                     stars: int, known: bool) -> tuple[int, bool]:
    """Header icons, corrected by the objective rows when those were actually read.

    Three green checks (or three filled row stars) is 3/3 even if the title-bar icons were
    clipped or sampled on the cream body. A pale row star with no check is a real miss.
    A header that already shows three filled stars is not downgraded by a stray sample.
    """
    done, missed, seen = objective_tally(img, texts, header.center[1] + 30, button_y - 30)
    if seen == 0:
        return stars, known
    if done >= 3 and missed == 0:
        return 3, True
    if missed and not (known and stars == 3):
        return min(done, 3 - min(missed, 3)), True
    if not known and done >= 3:
        return 3, True
    return stars, known


def _objective_stars(img: np.ndarray, texts: list[Text], y0: float, y1: float) -> tuple[int, int]:
    """(gold, grey) objective-row stars between two y positions. The icon sits just left of the text."""
    x0, x1 = config.OBJECTIVE_TEXT_X
    gold = grey = 0
    for t in texts:
        if not (y0 < t.center[1] < y1 and x0 <= t.x1 <= x1):
            continue
        x, y = int(t.x1 - config.OBJECTIVE_STAR_DX), int(t.center[1])
        if y < 8 or x < 8 or y + 8 >= img.shape[0] or x + 8 >= img.shape[1]:
            continue
        b, g, r = img[y - 8:y + 8, x - 8:x + 8].reshape(-1, 3).mean(0)
        kind = _star_kind(b, g, r)
        gold += kind == "gold"
        grey += kind == "grey"
    return gold, grey


def clipped_star_card(img: np.ndarray | None, texts: list[Text], cards: list[Card]) -> Card | None:
    """The card cut off at the top of the star list.

    The list opens on the last beaten level. The card above it (often the one that still
    misses a star) has its header — and the header's star icons — above the screen, while
    its Start button and condition rows are visible. `card_stars` never sees it, so a scan
    that only reads headers plays the last beaten level instead.

    Its number is the one just below the first full card. A grey condition star means it
    is still incomplete. None when the top card is fully on screen or its stars can't be read.
    """
    if img is None or not cards:
        return None
    first = min(cards, key=lambda c: c.header.center[1])

    def linked(t: Text) -> bool:
        return any(c.button and abs(c.button.center[1] - t.center[1]) < 25 for c in cards)

    orphans = [t for t in texts if any(matches(t, lbl, exact=True) for lbl in START_LABEL.values())
               and config.LIST_TOP < t.center[1] < first.header.center[1] and not linked(t)]
    if not orphans:
        return None
    button = min(orphans, key=lambda t: first.header.center[1] - t.center[1])
    if not (0 < first.header.center[1] - button.center[1] < config.CARD_PITCH):
        return None
    if first.number < 2:
        return None
    done, missed, seen = objective_tally(img, texts, config.LIST_TOP, button.center[1] - 40)
    if seen and done >= 3 and missed == 0:
        stars, known = 3, True  # every visible objective is checked: the clipped header is not 0/3
    elif seen and missed:
        stars, known = min(done, 3 - min(missed, 3)), True
    else:
        gold, grey = _objective_stars(img, texts, config.LIST_TOP, button.center[1] - 40)
        if grey:
            stars, known = min(gold, 2), True
        elif gold >= 3:
            stars, known = 3, True
        else:
            return None  # the missing row may still be off screen: the hunt scrolls the header into view
    return Card(first.number - 1, first.header, button, stars, known)


def parse_star_list(img: np.ndarray, texts: list[Text], ocr: Ocr) -> list[Card]:
    """Cards visible in the star challenge list, sorted by number.

    Headers are read from a crop above each INICIO/LISTO button, because full-frame OCR
    misses some of them. Headers without a button (locked or partially visible cards)
    come from the full-frame pass.
    """
    cards: dict[int, Card] = {}
    buttons = [t for t in texts if any(matches(t, lbl, exact=True) for lbl in START_LABEL.values())
               and config.LIST_TOP < t.center[1] < config.LIST_BOTTOM]
    for b in buttons:
        cy = b.center[1] - config.HEADER_ABOVE_BUTTON
        if cy - config.HEADER_HALF_HEIGHT < config.LIST_TOP:
            continue
        region = (config.HEADER_X_RANGE[0], cy - config.HEADER_HALF_HEIGHT,
                  config.HEADER_X_RANGE[1], cy + config.HEADER_HALF_HEIGHT)
        for h in ocr.read(img, region):
            n = parse_level_number(h.text)
            if n is not None:
                stars, known = header_stars(img, h)
                # Objective checks correct a title-bar read. Three checks is 3/3 even when the
                # icons were sampled on the cream body (that used to come back as 0/3). A pale
                # objective star with no check is a real miss. Three filled header stars are
                # not downgraded by a stray sample.
                stars, known = _with_objectives(img, texts, h, b.center[1], stars, known)
                cards[n] = Card(n, h, b, stars, known)
                break
    for t in texts:
        n = parse_level_number(t.text)
        if n is not None and n not in cards and config.LIST_TOP < t.center[1] < config.LIST_BOTTOM:
            cards[n] = Card(n, t, None)
    return sorted(cards.values(), key=lambda c: c.number)


# --- skill cards (skill pick and shop) ---------------------------------------------------------

@dataclass(frozen=True)
class SkillCard:
    rarity: str                  # one of RARITY_NAMES
    name: str
    description: str
    tag: Text                    # the rarity tag, top-left of the card
    price: Text | None = None    # shop: the current price button (the lowest number on the card's right)
    sold: bool = False           # shop: already bought

    @property
    def cost(self) -> int | None:
        return int(self.price.norm) if self.price else None


def rarity_name(t: Text) -> str | None:
    return next((RARITY_NAMES[i] for i, r in enumerate(L.RARITIES) if matches(t, r, exact=True)), None)


def parse_skill_cards(texts: list[Text], rarity_x: tuple[int, int] | None = None) -> list[SkillCard]:
    """Skill cards top to bottom: rarity tag, name (first line right of the icon), description (the
    rest), and in the shop the price and SOLD OUT state.

    `rarity_x` widens the tag column for the horizontal World 2 rows. The shop keeps the narrow one.
    """
    band = config.SKILL_RARITY_X if rarity_x is None else rarity_x
    tags = sorted((t for t in texts if _in_range(t.center[0], band) and rarity_name(t)),
                  key=lambda t: t.center[1])
    cards = []
    for i, tag in enumerate(tags):
        top = tag.center[1] - 30
        bottom = tags[i + 1].center[1] - 30 if i + 1 < len(tags) else tag.center[1] + config.SKILL_CARD_HEIGHT
        band = [t for t in texts if top <= t.center[1] < bottom and t is not tag]
        words = sorted((t for t in band if t.x1 >= config.SKILL_TEXT_MIN_X and t.center[0] < config.SHOP_PRICE_MIN_X
                        and re.search(r"[a-z]{2}", t.norm)),  # skip OCR junk glyphs
                       key=lambda t: (t.center[1], t.center[0]))
        lo, hi = config.SKILL_NAME_BELOW_TAG
        if not words or not lo <= words[0].center[1] - tag.center[1] <= hi:
            continue  # name not read: skip the card rather than store a description line as its name
        prices = [t for t in band if t.center[0] >= config.SHOP_PRICE_MIN_X and t.norm.isdigit()]
        cards.append(SkillCard(rarity_name(tag), words[0].text, " ".join(t.text for t in words[1:]), tag,
                               max(prices, key=lambda t: t.center[1]) if prices else None,
                               any(matches(t, L.SOLD_OUT) for t in band)))
    return cards


def _below(button: Text, texts: list[Text]) -> list[Text]:
    return [t for t in texts if 0 < t.center[1] - button.center[1] <= config.REROLL_COUNT_BELOW
            and abs(t.center[0] - button.center[0]) < 120]


_USES_RE = re.compile(r"\((\d+)\)")


def _reroll_uses(text: str) -> int:
    """Free uses written as "(1)". A bare number is a gem or coin price and is not a use."""
    m = _USES_RE.search(text)
    return int(m.group(1)) if m else 0


def skill_reroll(texts: list[Text]) -> Text | None:
    """The skill pick's free reroll, while it still has uses.

    The count is "(1)" under the button or on the same line ("Reroll (1)", "Volver a tirar (1)").
    A price with no parentheses is premium currency and is never returned.
    """
    button = find(texts, L.SKILL_REROLL)
    if not button:
        return None
    if _reroll_uses(button.norm) > 0:
        return button
    if any(_reroll_uses(t.norm) > 0 for t in _below(button, texts)):
        return button
    return None


def parse_money(texts: list[Text]) -> int | None:
    """Run coins, top-left counter under the HP bar."""
    x1, y1, x2, y2 = config.MONEY_REGION
    return next((int(t.norm) for t in texts if t.norm.isdigit()
                 and x1 <= t.center[0] <= x2 and y1 <= t.center[1] <= y2), None)


@dataclass(frozen=True)
class Shop:
    money: int | None
    cards: list[SkillCard]
    free_reroll: Text | None     # the reroll button while it says FREE (afterwards it costs coins)
    exit: Text
    reroll_cost: int | None = None  # coin price under the button once it is no longer free
    reroll: Text | None = None       # the reroll button, free or paid


def _reroll_cost(reroll: Text, texts: list[Text]) -> int | None:
    return next((int(t.norm) for t in _below(reroll, texts) if t.norm.isdigit()), None)


def parse_shop(texts: list[Text]) -> Shop | None:
    leave = find(texts, L.LEAVE, exact=True)
    reroll = find(texts, L.SHOP_REROLL)
    if not (leave and reroll) or find(texts, L.BLACK_MARKET):
        return None
    free = reroll if any(matches(t, L.FREE, exact=True) for t in _below(reroll, texts)) else None
    return Shop(parse_money(texts), parse_skill_cards(texts), free, leave,
                None if free else _reroll_cost(reroll, texts), reroll)


@dataclass(frozen=True)
class FortuneTeller:
    orbs: int | None                     # run orbs left (bottom counter)
    balls: dict[int, tuple[int, int]]    # chance (100, 70, 40) -> its buy button


_CHANCE_RE = re.compile(r"^(\d+)\s*%$")


def parse_fortune_teller(texts: list[Text]) -> FortuneTeller | None:
    """"Adivino": each ball gives a skill with its chance ("100%" tag above it), paid with run orbs."""
    if not find(texts, L.FORTUNE_TELLER):
        return None
    x1, y1, x2, y2 = config.FORTUNE_ORBS_REGION
    orbs = next((int(t.norm) for t in texts if t.norm.isdigit()
                 and x1 <= t.center[0] <= x2 and y1 <= t.center[1] <= y2), None)
    balls = {int(m.group(1)): (t.center[0], t.center[1] + config.FORTUNE_BUTTON_BELOW_TAG)
             for t in texts if (m := _CHANCE_RE.match(t.norm))}
    return FortuneTeller(orbs, balls)
