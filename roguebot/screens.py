"""Screen recognition: turns OCR output into typed screen states. No input is sent from here."""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from roguebot import config, labels as L
from roguebot.skills import RARITY_NAMES
from roguebot.vision import Ocr, Text, find, match_template, matches, parse_level_number, parse_world_number


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
    map_button: Text | None = None  # "Mapa Mundial" compass (None: no worlds on this account)

    @property
    def world(self) -> int | None:
        """World of the shown level (1 = Everdale, 2 = Heliora: "2-1. Elysium I"); None if the title was not read."""
        return parse_world_number(self.level_title) if self.level_title else None


@dataclass(frozen=True)
class Card:
    """One level entry in the Desafio de Estrellas list."""
    number: int
    header: Text
    button: Text | None          # None when locked or the button is out of view
    stars: int = 3               # earned stars (gold icons in the header); each one gives rewards


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
    title = next((t.text for t in texts if parse_level_number(t.text) is not None), None)
    stars = find(texts, L.STARS_BUTTON)
    if stars and matches(stars, L.PATROL):  # OCR joined "Patrulla" and "de Estrellas": the button is its right half
        stars = Text(stars.text, (stars.x1 + stars.x2) // 2, stars.y1, stars.x2, stars.y2)
    return Lobby(mode, title, start, stars, parse_energy(texts), has_elite, find(texts, L.WORLD_MAP_BUTTON))


def parse_world_map(texts: list[Text]) -> dict[str, Text] | None:
    """The "Mapa Mundial" screen: each known world's name label (tapping it enters that world), or None
    on another screen. A world still locked or not in the game yet is simply not tapped by name."""
    if not find(texts, L.WORLD_MAP_TITLE) or find(texts, L.PATROL):
        return None
    return {w: t for w in config.WORLDS if (t := find(texts, w, exact=True))}


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
_PATH_SHOP = cv2.imread(str(Path(__file__).parent / "templates" / "path_shop.png"))


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
    EVENT = "event"              # tile event with options; we always pick "Salir" (leave)
    SHOP = "shop"                # shop tile; we buy nothing and press "Salir"
    LEAVE = "leave"              # screens we just exit: a lone "Salir"
    FORTUNE_TELLER = "fortune_teller"  # "Adivino": 100/70/40% balls paid with orbs; tap = its back arrow
    CONTINUE = "continue"        # screen whose only action is one button (see labels.CONTINUE_BUTTONS)
    DICE_DUEL = "dice_duel"      # "¡Batalla de Dados!" 21-style minigame
    PATH_CHOICE = "path_choice"  # board fork (Heliora): "Camino A" / "Camino B" cards showing where each path leads
    ANVIL = "anvil"              # "Yunque del Herrero": take the item or gamble on upgrading it (the Player decides)
    CONTRACT = "contract"        # "Vendedor Maldito": sign one of two contracts (the Player picks which)
    MINER = "miner"              # "Minero de Tesoros" minigame: dig tiles (the Player picks which)
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


_SPEED_RE = re.compile(r"x\s*([12])$")


def game_speed(texts: list[Text]) -> int | None:
    """Speed shown on the bottom-left "» x2" button (it shows the current speed), or None if absent."""
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
    roi = img[max(0, y - 120):y + 120, max(0, x - 120):x + 120]  # (a label at the screen edge: a lobby icon, not an option)
    return roi.size > 0 and cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)[..., 1].mean() > config.EVENT_DISABLED_MAX_SATURATION


def _event_option(img: np.ndarray, texts: list[Text]) -> tuple[int, int] | None:
    """Tile event (title band + option labels above icons): where to tap, or None if not an event.

    Takes "Salir" (leave) when offered, else the leftmost option that is not greyed out.
    """
    labels = event_options(img, texts)
    if not labels:
        return None
    return event_tap(next((t for t in labels if matches(t, L.LEAVE, exact=True)), labels[0]))


def event_tap(label: Text) -> tuple[int, int]:
    """An event option is taken by its icon, below its label."""
    return label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL


_PATH_RE = re.compile(r"^(.+) ([a-d])$")


@dataclass(frozen=True)
class PathOption:
    label: Text                  # "Camino A": tapping it takes the path
    shop: bool                   # the card's picture is a shop


def _shop_card(img: np.ndarray, label: Text) -> bool:
    """The shop wagon is drawn on the fork card above this label (the phone's OCR does not read its sign)."""
    x, y = label.center
    card = img[max(0, y - config.PATH_CARD_HEIGHT):y, max(0, x - config.PATH_CARD_HALF_WIDTH):x + config.PATH_CARD_HALF_WIDTH]
    return (card.shape[0] >= _PATH_SHOP.shape[0] and card.shape[1] >= _PATH_SHOP.shape[1]
            and match_template(card, _PATH_SHOP, config.PATH_SHOP_MIN_SCORE) is not None)


def parse_paths(texts: list[Text], img: np.ndarray | None = None) -> list[PathOption]:
    """A board fork: its cards ("Camino A", "Camino B") left to right, each showing where the path
    leads; empty when the board shows no fork. A shop card is known by its picture (given the frame) or
    by the sign on it ("SHOP", "BLACK / MARKET")."""
    labels = sorted((t for t in texts if (m := _PATH_RE.match(t.norm)) and m.group(1) in L.PATH_OPTION.variants
                     and t.center[1] > config.PATH_LABEL_MIN_Y), key=lambda t: t.center[0])
    if len(labels) < 2:
        return []
    return [PathOption(p, any(matches(t, L.PATH_SHOP, exact=True)
                              and abs(t.center[0] - p.center[0]) < config.PATH_CARD_HALF_WIDTH
                              and 0 < p.center[1] - t.center[1] < config.PATH_CARD_HEIGHT for t in texts)
                       or (img is not None and _shop_card(img, p)))
            for p in labels]


@dataclass(frozen=True)
class Contract:
    button: Text                 # its "Firmar"
    terms: str                   # its boon and curse, normalized, lines joined


def parse_contracts(texts: list[Text]) -> list[Contract]:
    """"Vendedor Maldito": the contracts on offer, left to right; empty on any other screen."""
    if not find(texts, L.CURSED_VENDOR):
        return []
    buttons = sorted((t for t in texts if matches(t, L.SIGN, exact=True)), key=lambda t: t.center[0])
    return [Contract(b, " ".join(t.norm for t in sorted(texts, key=lambda t: (t.center[1], t.center[0]))
                                 if _in_range(t.center[1], config.CONTRACT_TEXT_Y)
                                 and abs(t.center[0] - b.center[0]) < config.CONTRACT_HALF_WIDTH))
            for b in buttons] if len(buttons) > 1 else []


def parse_anvil(texts: list[Text]) -> tuple[Text, Text, int | None] | None:
    """"Yunque del Herrero": (take button, upgrade button, success chance in % or None); None elsewhere."""
    take, upgrade = find(texts, L.ANVIL_TAKE, exact=True), find(texts, L.ANVIL_UPGRADE, exact=True)
    if not (find(texts, L.ANVIL) and take and upgrade):
        return None
    chance = find(texts, L.ANVIL_CHANCE)
    m = re.search(r"(\d+)\s*%", chance.norm) if chance else None
    return take, upgrade, int(m.group(1)) if m else None


DIRT, EMPTY, TREASURE = "dirt", "empty", "treasure"


def miner_tile(row: int, col: int) -> tuple[int, int]:
    x, y = config.MINER_ORIGIN
    return x + col * config.MINER_PITCH, y + row * config.MINER_PITCH


def miner_tiles(img: np.ndarray) -> list[str]:
    """"Minero de Tesoros" grid, row by row: DIRT (not dug), EMPTY (dug, nothing) or TREASURE (a piece of
    one, or a whole dug-out one)."""
    tiles, h = [], config.MINER_TILE_HALF
    for i in range(config.MINER_SIZE ** 2):
        x, y = miner_tile(*divmod(i, config.MINER_SIZE))
        roi = img[y - h:y + h, x - h:x + h].reshape(-1, 3).astype(int)
        if (roi.max(1) < 60).mean() > config.MINER_EMPTY_DARK:
            tiles.append(EMPTY)
        elif np.abs(roi.mean(0) - config.MINER_DIRT).max() < config.MINER_DIRT_TOLERANCE:
            tiles.append(DIRT)
        else:
            tiles.append(TREASURE)
    return tiles


def treasures_left(texts: list[Text]) -> int | None:
    """N of "Tesoros Restantes: N" (OCR may split the number off)."""
    label = find(texts, L.TREASURES_LEFT)
    if not label:
        return None
    if m := re.search(r"(\d+)$", label.norm):
        return int(m.group(1))
    return next((int(t.norm) for t in texts if t.norm.isdigit() and abs(t.center[1] - label.center[1]) < 40
                 and 0 < t.x1 - label.x2 < 120), None)


def parse_hp(texts: list[Text]) -> float | None:
    """The hero's HP share in a level, from the top bar "7,2m / 10,1m" -> 0.71."""
    from roguebot.mode_screens import parse_power  # mode_screens imports nothing from here
    x1, y1, x2, y2 = config.HP_REGION
    for t in texts:
        if x1 <= t.center[0] <= x2 and y1 <= t.center[1] <= y2 and t.norm.count("/") == 1:
            now, top = (parse_power(v) for v in t.norm.split("/"))
            if now is not None and top:
                return min(1.0, now / top)
    return None


def event_options(img: np.ndarray, texts: list[Text]) -> list[Text]:
    """A tile event's option labels that can be taken (not greyed out), left to right; [] if not an event."""
    if not any(_in_range(t.center[1], config.EVENT_TITLE_Y)
               and abs(t.center[0] - config.SCREEN_SIZE[0] // 2) < config.EVENT_TITLE_CENTER_TOLERANCE for t in texts):
        return []
    labels = [t for t in texts if _in_range(t.center[1], config.EVENT_LABEL_Y)]
    return sorted([t for t in labels if _option_enabled(img, t)] or labels, key=lambda t: t.center[0])


def classify_level_screen(img: np.ndarray, texts: list[Text]) -> LevelState:
    if footer_visible(img):  # a main screen (lobby...), never a level: its texts can look like an event
        return LevelState(LevelScreen.UNKNOWN)
    proceed = find(texts, L.CONTINUE, exact=True)
    double = find(texts, L.DOUBLE_REWARD)
    if proceed and double:  # always double the reward with the (VIP-skipped) ad before continuing
        return LevelState(LevelScreen.DOUBLE_REWARD, double.center)
    end = proceed or find(texts, L.CONFIRM, exact=True)  # Dungeon Dive ends with "Confirmar"
    if end and find(texts, L.DEFEAT):
        return LevelState(LevelScreen.DEFEAT, end.center)
    if end and find(texts, L.VICTORY):
        return LevelState(LevelScreen.VICTORY, end.center)
    pick = find(texts, L.SKILL_PROMPT)
    if pick:
        # First card = topmost rarity tag ("Común", "Legendario"...) in the cards' top-left
        # corner. Anchoring on it skips the 1-5 pick counter of "SUBIDA DE PODER".
        tags = [t for t in texts if t.center[1] > pick.center[1]
                and _in_range(t.center[0], config.SKILL_RARITY_X)]
        if tags:
            first = min(tags, key=lambda t: t.center[1])
            return LevelState(LevelScreen.SKILL_PICK, (config.SCREEN_SIZE[0] // 2,
                                                       first.center[1] + config.SKILL_TAP_BELOW_RARITY))
    contracts = parse_contracts(texts)
    if contracts:
        return LevelState(LevelScreen.CONTRACT, contracts[0].button.center)
    paths = parse_paths(texts)
    if paths:
        return LevelState(LevelScreen.PATH_CHOICE, paths[0].label.center)
    if proceed and find(texts, L.LEVEL_MODIFIERS, exact=True):  # elite level intro: modifiers + Continue
        return LevelState(LevelScreen.CONTINUE, proceed.center)
    button = find(texts, L.EXACT_BUTTONS, exact=True)
    if button:
        return LevelState(LevelScreen.CONTINUE, button.center)
    for label in L.CONTINUE_BUTTONS:
        button = find(texts, label)
        if button:
            return LevelState(LevelScreen.CONTINUE, button.center)
    anvil = parse_anvil(texts)  # after the claim text: the reward banner shows over the anvil
    if anvil:
        return LevelState(LevelScreen.ANVIL, anvil[0].center)
    duel = _dice_duel(texts)
    if duel:
        return LevelState(LevelScreen.DICE_DUEL, duel)
    if find(texts, L.FLIP_CARDS_PROMPT):
        card = next((c for c in config.FLIP_CARDS if _face_down(img, c)), None)
        return LevelState(LevelScreen.FLIP_CARDS, card)
    if find(texts, L.FORTUNE_TELLER):
        return LevelState(LevelScreen.FORTUNE_TELLER, config.FORTUNE_TELLER_BACK)
    leave = find(texts, L.LEAVE, exact=True)
    if leave and find(texts, L.SHOP_REROLL):  # shop or black market (same screen, run coins, half price): "Salir" is the button itself
        return LevelState(LevelScreen.SHOP, leave.center)
    event_option = _event_option(img, texts)
    if event_option:
        return LevelState(LevelScreen.EVENT, event_option)
    if leave:  # e.g. "Meditación completa" -> "Salir"
        return LevelState(LevelScreen.LEAVE, leave.center)
    if find(texts, L.TREASURE_MINER) and find(texts, L.TREASURES_LEFT):  # out of pickaxes it shows "Salir" (above)
        return LevelState(LevelScreen.MINER)
    # Revive popup (over a fight). Checked late: skill/shop cards can mention "Revive" too.
    if find(texts, L.REVIVE_PROMPT):
        free = find(texts, L.REVIVE_FREE, exact=True)
        if free and _yellow_button(img, free.center):  # the video button is yellow; the gem one green
            return LevelState(LevelScreen.REVIVE, free.center)
        return LevelState(LevelScreen.UNKNOWN)  # no free revive left: let the countdown run out
    if _counter(texts, L.FIGHT_ROUND) is not None:
        return LevelState(LevelScreen.FIGHT)
    # Late, like the red dice: lucky wheels and offers can be green there too, but their texts match first.
    if dice_auto(img):
        return LevelState(LevelScreen.AUTO_PLAY)
    if dice_ready(img):
        return LevelState(LevelScreen.BOARD_READY, config.DICE_BUTTON)
    return LevelState(LevelScreen.UNKNOWN)


def card_stars(img: np.ndarray, header: Text) -> int:
    """Gold star icons (earned) right of a card header; missing ones are grey-blue."""
    y = header.center[1]
    earned = 0
    for x in config.STAR_ICONS_X:
        b, g, r = img[y - 12:y + 12, x - 12:x + 12].reshape(-1, 3).mean(0)
        earned += r > 180 and b < 150
    return earned


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
                cards[n] = Card(n, h, b, card_stars(img, h))
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


def parse_skill_cards(texts: list[Text]) -> list[SkillCard]:
    """Skill cards top to bottom: rarity tag, name (first line right of the icon), description (the
    rest), and in the shop the price and SOLD OUT state."""
    tags = sorted((t for t in texts if _in_range(t.center[0], config.SKILL_RARITY_X) and rarity_name(t)),
                  key=lambda t: t.center[1])
    cards = []
    for i, tag in enumerate(tags):
        top = tag.center[1] - 30
        bottom = tags[i + 1].center[1] - 30 if i + 1 < len(tags) else tag.center[1] + config.SKILL_CARD_HEIGHT
        band = [t for t in texts if top <= t.center[1] < bottom and t is not tag]
        words = sorted((t for t in band if t.x1 >= config.SKILL_TEXT_MIN_X and t.center[0] < config.SHOP_PRICE_MIN_X
                        and re.search(r"[a-z]{2}", t.norm)  # skip OCR junk glyphs
                        and t.norm != "exp"),  # "EXP" floats over a level-up pick after a fight
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


_USES_RE = re.compile(r"^\((\d+)\)$")


def skill_reroll(texts: list[Text]) -> Text | None:
    """The skill pick's reroll button, if it has uses left ("Reroll" with "(1)" below)."""
    button = find(texts, L.SKILL_REROLL)
    if not button:
        return None
    uses = next((int(m.group(1)) for t in _below(button, texts) if (m := _USES_RE.match(t.norm))), 0)
    return button if uses > 0 else None


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
    items: dict[str, Text] = field(default_factory=dict)  # stat items on sale: BOOST / HEAL -> price button


BOOST, HEAL = "boost", "heal"  # shop stat items: a stat up for the run ("ATQ ↑↑↑", "PS máx. ↑↑", 3 uses) / "Curar 30%"
_USES_LEFT_RE = re.compile(r"^(\d)\s*/\s*\d$")


def _shop_items(texts: list[Text]) -> dict[str, Text]:
    """The shop's stat items (above the skill cards): label, price below it; above it the uses left
    ("3/3") or "AGOTADO" once used up (then it is left out)."""
    items = {}
    for name in texts:
        if not _in_range(name.center[1], config.SHOP_ITEMS_Y):
            continue
        kind = HEAL if name.norm.startswith(L.SHOP_HEAL.variants) else BOOST  # OCR may drop the arrows ("ATQ")
        near = [t for t in texts if abs(t.center[0] - name.center[0]) < config.SHOP_ITEM_DX]
        above = [t for t in near if _in_range(name.center[1] - t.center[1], config.SHOP_ITEM_ABOVE)]
        price = next((t for t in near if t.norm.isdigit()
                      and _in_range(t.center[1] - name.center[1], config.SHOP_ITEM_PRICE_BELOW)), None)
        used_up = any(matches(t, L.SOLD_OUT) or ((m := _USES_LEFT_RE.match(t.norm)) and m.group(1) == "0") for t in above)
        if price and not used_up:
            items[kind] = price
    return items


def parse_shop(texts: list[Text]) -> Shop | None:
    leave = find(texts, L.LEAVE, exact=True)
    reroll = find(texts, L.SHOP_REROLL)
    if not (leave and reroll):
        return None
    free = reroll if reroll and any(matches(t, L.FREE, exact=True) for t in _below(reroll, texts)) else None
    return Shop(parse_money(texts), parse_skill_cards(texts), free, leave, _shop_items(texts))


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
