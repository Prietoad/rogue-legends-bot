"""Screen recognition: turns OCR output into typed screen states. No input is sent from here."""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from roguebot import config, labels as L
from roguebot.skills import RARITY_NAMES
from roguebot.vision import Ocr, Text, find, match_template, matches, parse_level_number


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
    stars_button: Text           # "Desafio de Estrellas"
    energy: int | None           # top bar "12/32" -> 12


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
    stars = find(texts, L.STARS_BUTTON)
    if find(texts, L.ELITE_ON, exact=True):
        mode = Mode.ELITE
    elif find(texts, L.ELITE_OFF, exact=True):
        mode = Mode.NORMAL
    else:
        return None
    start = find(texts, START_LABEL[mode], exact=True)
    if not (stars and start):
        return None
    title = next((t.text for t in texts if parse_level_number(t.text) is not None), None)
    return Lobby(mode, title, start, stars, parse_energy(texts))


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


def tutorial_hand(img: np.ndarray) -> tuple[int, int] | None:
    """Where a forced tutorial's pointing hand points (e.g. at a newly unlocked lobby button).
    While it shows, the game ignores every other tap."""
    center = match_template(img, _TUTORIAL_HAND, config.TUTORIAL_HAND_MIN_SCORE)
    if center is None:
        return None
    dx, dy = config.TUTORIAL_TAP_OFFSET
    return center[0] + dx, center[1] + dy


def footer_visible(img: np.ndarray) -> bool:
    """Main screens show the bottom tab bar at full brightness; popups darken it. Both tab samples
    must match: one alone matched a dark teal level board (and the bot took it for a main screen)."""
    for (x1, x2), color in config.FOOTER_SAMPLES:
        mean = img[config.FOOTER_Y[0]:config.FOOTER_Y[1], x1:x2].reshape(-1, 3).mean(0)
        if np.abs(mean - color).max() >= config.FOOTER_COLOR_TOLERANCE:
            return False
    return True


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
    LEAVE = "leave"              # screens we just exit: a lone "Salir", the Fortune Teller back arrow
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
    roi = cv2.cvtColor(img[y - 120:y + 120, x - 120:x + 120], cv2.COLOR_BGR2HSV)
    return roi[..., 1].mean() > config.EVENT_DISABLED_MAX_SATURATION


def _event_option(img: np.ndarray, texts: list[Text]) -> tuple[int, int] | None:
    """Tile event (title band + option labels above icons): where to tap, or None if not an event.

    Takes "Salir" (leave) when offered, else the leftmost option that is not greyed out.
    """
    has_title = any(_in_range(t.center[1], config.EVENT_TITLE_Y)
                    and abs(t.center[0] - config.SCREEN_SIZE[0] // 2) < config.EVENT_TITLE_CENTER_TOLERANCE
                    for t in texts)
    labels = [t for t in texts if _in_range(t.center[1], config.EVENT_LABEL_Y)]
    if not (has_title and labels):
        return None
    labels = [t for t in labels if _option_enabled(img, t)] or labels
    label = next((t for t in labels if matches(t, L.LEAVE, exact=True)), min(labels, key=lambda t: t.center[0]))
    return label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL


def classify_level_screen(img: np.ndarray, texts: list[Text]) -> LevelState:
    if footer_visible(img):  # a main screen (lobby...), never a level: its texts can look like an event
        return LevelState(LevelScreen.UNKNOWN)
    proceed = find(texts, L.CONTINUE, exact=True)
    double = find(texts, L.DOUBLE_REWARD)
    if proceed and double:  # always double the reward with the (VIP-skipped) ad before continuing
        return LevelState(LevelScreen.DOUBLE_REWARD, double.center)
    if proceed and find(texts, L.DEFEAT):
        return LevelState(LevelScreen.DEFEAT, proceed.center)
    if proceed and find(texts, L.VICTORY):
        return LevelState(LevelScreen.VICTORY, proceed.center)
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
    if proceed and find(texts, L.LEVEL_MODIFIERS, exact=True):  # elite level intro: modifiers + Continue
        return LevelState(LevelScreen.CONTINUE, proceed.center)
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
        return LevelState(LevelScreen.LEAVE, config.FORTUNE_TELLER_BACK)
    leave = find(texts, L.LEAVE, exact=True)
    if leave and find(texts, L.BLACK_MARKET):  # never seen: its prices may be gems, so just leave
        return LevelState(LevelScreen.LEAVE, leave.center)
    if leave and find(texts, L.SHOP_REROLL):  # shop: "Salir" is the button itself
        return LevelState(LevelScreen.SHOP, leave.center)
    event_option = _event_option(img, texts)
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


def _rarity_name(t: Text) -> str | None:
    return next((RARITY_NAMES[i] for i, r in enumerate(L.RARITIES) if matches(t, r, exact=True)), None)


def parse_skill_cards(texts: list[Text]) -> list[SkillCard]:
    """Skill cards top to bottom: rarity tag, name (first line right of the icon), description (the
    rest), and in the shop the price and SOLD OUT state."""
    tags = sorted((t for t in texts if _in_range(t.center[0], config.SKILL_RARITY_X) and _rarity_name(t)),
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
        cards.append(SkillCard(_rarity_name(tag), words[0].text, " ".join(t.text for t in words[1:]), tag,
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


def parse_shop(texts: list[Text]) -> Shop | None:
    leave = find(texts, L.LEAVE, exact=True)
    reroll = find(texts, L.SHOP_REROLL)
    if not (leave and reroll) or find(texts, L.BLACK_MARKET):
        return None
    free = reroll if reroll and any(matches(t, L.FREE, exact=True) for t in _below(reroll, texts)) else None
    return Shop(parse_money(texts), parse_skill_cards(texts), free, leave)
