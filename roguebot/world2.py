"""World 2 choices. Pure: HUD values and OCR text in, a choice out. No taps.

The player logs each decision and taps the button the text was read from. A title that
matches nothing is not decided here; the unknown-event catcher records it and picks a
safe option. Campfire, Wise Monk and World 1 events stay in screens.py / play.py.
"""

import logging
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from roguebot import config, labels as L
from roguebot.build import PRESETS, Build
from roguebot.skills import DAMAGE_TYPES, MAGIC, PHYSICAL, infer_tags, name_is_support
from roguebot.vision import Text, find, normalize

log = logging.getLogger(__name__)

LATE_ROLLS = 5          # Elysium "shop if almost out of rolls", and when removing campfires barely matters
LAST_SHOP_ROLLS = 5     # Atlantis: this few rolls left and the shop will not come around again
HAUNT_EMBRACE_UNTIL = 10  # rolls used
VISTA_GAZE_UNTIL = 5
SPRINGS_STAY_HP = 0.60
GOBLIN_RAID_HP = 0.50
MINER_SIZE = 7
MINER_PICKAXES = 9
UNK, DUG, GEM = 0, 1, 2

# Blessing scores are positive. Curse scores are the penalty subtracted from the blessing.
# Tuned to the two picks from playtesting:
#   early: black-market / EXP-halved beats elites -25% / campfires-removed
#   3 rolls left: remove-half-enemies / campfires-removed beats rerolls / enemies-act-first
# Campfires-removed is heavy, and nearly free once few rolls are left (no campfire would be reached).
VENDOR_LINES = (
    {"id": "rerolls", "kind": "blessing", "score": 80,
     "phrases": ("skill rerolls refresh on every skill selection", "skill rerolls refresh")},
    {"id": "remove_half", "kind": "blessing", "score": 90,
     "phrases": ("remove half of the enemy tiles", "remove half of the enemy")},
    {"id": "tokens_500", "kind": "blessing", "score": 70,
     "phrases": ("gain 500 shop tokens", "500 shop tokens")},
    {"id": "black_market", "kind": "blessing", "score": 40,
     "phrases": ("all shops become black markets", "shops become black markets", "black markets")},
    {"id": "elites", "kind": "blessing", "score": 75,
     "phrases": ("elites/bosses -25% hp", "elites -25% hp", "bosses -25% hp")},
    {"id": "first_shop", "kind": "blessing", "score": 35,
     "phrases": ("first shop free", "first shop is free")},
    {"id": "enemies_first", "kind": "curse", "score": 15,
     "phrases": ("enemies will always act first", "always act first")},
    {"id": "campfires", "kind": "curse", "score": 100, "late_score": 10,
     "phrases": ("all campfires are removed", "campfires are removed", "campfires removed")},
    {"id": "exp_halved", "kind": "curse", "score": 30,
     "phrases": ("exp halved", "experience halved", "exp is halved")},
    {"id": "skills_disabled", "kind": "curse", "score": 90,
     "phrases": ("half of skills disabled", "skills disabled for")},
    {"id": "debuff_to_buff", "kind": "blessing", "score": 80,
     "phrases": ("all debuff tiles are replaced with buff tiles", "debuff tiles are replaced with buff")},
    {"id": "elites_start", "kind": "blessing", "score": 75,
     "phrases": ("elite enemies and bosses start combat with 25% less hp",
                 "start combat with 25% less hp", "bosses start combat with 25% less hp")},
    # Same shape as campfires-removed: almost free once few rolls are left, otherwise never taken.
    {"id": "lose_max_hp", "kind": "curse", "score": 100, "late_score": 10,
     "phrases": ("lose 5% max hp after each battle", "max hp after each battle", "5% max hp after each")},
    {"id": "trip", "kind": "curse", "score": 40,
     "phrases": ("chance to trip and take damage instead of basic attacking",
                 "trip and take damage instead of basic attacking", "instead of basic attacking")},
)

# Titles the generic World 1 handler already owns. An unknown title is anything else.
KNOWN_OTHER_TITLES = (
    "un momento de descanso", "a short rest", "short rest",
    "carro de botin", "abandoned loot", "forbidden knowledge", "conocimiento prohibido",
    "wise monk", "monje sabio",
)

SAFE_WORDS = (
    "walk away", "leave", "salir", "exit", "refuse", "no thanks", "no thank",
    "ignore", "get out", "look around",
)

_HP_LINE = re.compile(r"^(\d+(?:[.,]\d+)?)([kmb])?/(\d+(?:[.,]\d+)?)([kmb])?$")
_ROLLS = re.compile(r"^(\d+)/(\d+)$")
_SCALED = re.compile(r"^(\d+(?:[.,]\d+)?)([kmb])?$")
_HP_SCALE = {None: 1.0, "": 1.0, "k": 1e3, "m": 1e6, "b": 1e9}
_PATH_LABEL = re.compile(r"^path\s*([ab])$")
_STAT_WORDS = {"atk", "def", "hp", "max", "attack", "defense"}


@dataclass(frozen=True)
class Hud:
    hp: float | None = None
    max_hp: float | None = None
    tokens: int | None = None
    rolls_used: int | None = None
    rolls_total: int | None = None

    @property
    def hp_ratio(self) -> float | None:
        if self.hp is None or not self.max_hp:
            return None
        return self.hp / self.max_hp

    @property
    def rolls_left(self) -> int | None:
        if self.rolls_used is None or self.rolls_total is None:
            return None
        return max(0, self.rolls_total - self.rolls_used)


@dataclass(frozen=True)
class Decision:
    event: str
    choice: str | None
    reason: str
    inputs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class KnownSkill:
    name: str
    rarity: str


@dataclass(frozen=True)
class PathCard:
    key: str                 # "A" / "B" when the label says so
    content: frozenset
    blob: str
    tap: tuple[int, int]


LAST: Decision | None = None


def active_build(fallback: Build, saved: dict | None) -> Build:
    """The preset saved by the window, or the build this run was started with.

    Core-skill checks use this. A named preset supplies its damage order. Custom
    uses damage_order from settings. Poison is not special-cased.
    """
    if not saved:
        return fallback
    preset = saved.get("preset")
    if isinstance(preset, str) and preset in PRESETS:
        return PRESETS[preset]
    order = saved.get("damage_order")
    if isinstance(order, list) and sorted(order) == sorted(DAMAGE_TYPES):
        nature = saved.get("nature")
        if nature not in (PHYSICAL, MAGIC):
            nature = fallback.nature
        return Build(nature, tuple(order), fallback.support_every)
    return fallback


def is_core_skill(name: str | None, build: Build) -> bool | None:
    """True when the skill is a damage skill of the active preset's types.

    None when the name cannot be read (the caller treats that as "might be core").
    A support name (Heal Shuriken) is not core even if it also names a damage type.
    """
    if not name or not normalize(name).strip():
        return None
    cleaned = re.sub(r"\b(?:lv|lvl|level)\.?\s*\d+\b", " ", normalize(name))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if name_is_support(cleaned):
        return False
    damage_type, _, _role = infer_tags(cleaned, "")
    if damage_type and damage_type in build.order:
        return True
    return False


def board_from_title(title: str | None) -> str | None:
    """'2-1. Elysium I' -> 'elysium'. None when the name is not one of the four boards."""
    if not title:
        return None
    n = normalize(title)
    for board, phrases in (
        ("ancient waterway", ("ancient waterway", "waterway")),
        ("molten core", ("molten core",)),
        ("elysium", ("elysium",)),
        ("atlantis", ("atlantis",)),
    ):
        if any(p in n for p in phrases):
            return board
    return None


def _scaled(num: str, suffix: str | None) -> float | None:
    try:
        return float(num.replace(",", ".")) * _HP_SCALE[suffix]
    except (ValueError, KeyError):
        return None


def read_hud(texts: list[Text]) -> Hud:
    """HP, shop tokens and the roll counter. Missing pieces stay None (the unreadable fallback)."""
    hp = max_hp = None
    for t in texts:
        if t.center[1] > config.TOP_BAR_MAX_Y or not (config.HP_X[0] <= t.center[0] <= config.HP_X[1]):
            continue
        m = _HP_LINE.match(t.norm.replace(" ", ""))
        if not m or not (m.group(2) or m.group(4)):
            continue
        cur, mx = _scaled(m.group(1), m.group(2)), _scaled(m.group(3), m.group(4))
        if cur is None or not mx:
            continue
        hp, max_hp = cur, mx
        break
    tokens = _tokens(texts)
    rolls = _rolls(texts)
    return Hud(hp, max_hp, tokens, rolls[0] if rolls else None, rolls[1] if rolls else None)


def _tokens(texts: list[Text]) -> int | None:
    """The coin under the level badge (top-left). Not the heart line and not the sword/shield stats."""
    x1, y1, x2, y2 = config.MONEY_REGION
    best = None
    for t in texts:
        if not (x1 <= t.center[0] <= x2 and y1 <= t.center[1] <= y2 + 80):
            continue
        m = _SCALED.match(t.norm.replace(" ", ""))
        if not m:
            continue
        value = _scaled(m.group(1), m.group(2))
        if value is None:
            continue
        best = int(value)
        break
    return best


def _rolls(texts: list[Text]) -> tuple[int, int] | None:
    """'2/30' on the left of the board. The top-bar energy '12/32' is not this."""
    hits = []
    for t in texts:
        if t.center[1] <= config.TOP_BAR_MAX_Y:
            continue
        m = _ROLLS.match(t.norm.replace(" ", ""))
        if not m:
            continue
        used, total = int(m.group(1)), int(m.group(2))
        if total < used or total > 99 or total < 5:
            continue
        hits.append((t.center[0], used, total))
    if not hits:
        return None
    _, used, total = min(hits)  # the board counter sits on the left edge
    return used, total


def _line_has(blob: str, phrase: str) -> bool:
    n, p = normalize(blob), normalize(phrase)
    if not p:
        return False
    if p in n:
        return True
    if len(n) <= len(p) + 12 and len(p) >= 8:
        # One-character OCR slips on a short line ("herh" / "herb").
        import difflib
        return difflib.SequenceMatcher(None, n, p).ratio() >= 0.84
    return False


def _best_rule(blob: str, kind: str) -> dict | None:
    found = []
    for rule in VENDOR_LINES:
        if rule["kind"] != kind:
            continue
        hit = max((len(p) for p in rule["phrases"] if _line_has(blob, p)), default=0)
        if hit:
            found.append((hit, rule))
    return max(found)[1] if found else None


def score_vendor_card(text: str, rolls_left: int | None) -> tuple[int, list[str]]:
    """Blessing minus curse. Unknown clauses score 0 and are returned for the debug log.

    Campfires-removed uses its small late penalty when rolls_left <= LATE_ROLLS.
    """
    blessing = _best_rule(text, "blessing")
    curse = _best_rule(text, "curse")
    penalty = 0
    if curse:
        late = curse.get("late_score")
        if late is not None and rolls_left is not None and rolls_left <= LATE_ROLLS:
            penalty = late
        else:
            penalty = curse["score"]
    score = (blessing["score"] if blessing else 0) - penalty
    unknown = []
    for clause in re.split(r"[\n.|]+", text):
        c = clause.strip()
        if len(normalize(c)) < 8:
            continue
        if _best_rule(c, "blessing") or _best_rule(c, "curse"):
            continue
        unknown.append(c)
    return score, unknown


def _side_parsed(text: str) -> bool:
    return _best_rule(text, "blessing") is not None or _best_rule(text, "curse") is not None


def decide_vendor(left: str, right: str, rolls_left: int | None) -> Decision:
    ls, lu = score_vendor_card(left, rolls_left)
    rs, ru = score_vendor_card(right, rolls_left)
    choice = "left" if ls >= rs else "right"
    return Decision("cursed_vendor", choice,
                    f"left {ls} vs right {rs}",
                    {"left": ls, "right": rs, "rolls_left": rolls_left, "unknown": lu + ru,
                     "left_parsed": _side_parsed(left), "right_parsed": _side_parsed(right),
                     "left_text": left, "right_text": right})


def vendor_needs_shot(decision: Decision | None) -> bool:
    """A side with no recognized line, or a clause that matches no rule, should be saved."""
    if decision is None or decision.event != "cursed_vendor":
        return False
    if decision.inputs.get("unknown"):
        return True
    return not decision.inputs.get("left_parsed") or not decision.inputs.get("right_parsed")


def decide_statue(skill_name: str | None, build: Build) -> Decision:
    core = is_core_skill(skill_name, build) if skill_name else None
    if core is False:
        return Decision("statue", "offering", "named skill is not a core preset skill",
                        {"skill": skill_name, "core": False})
    why = "skill unreadable" if core is None else "named skill is a core preset skill"
    return Decision("statue", "pray", why, {"skill": skill_name, "core": core})


def decide_herb() -> Decision:
    return Decision("mysterious_herb", "make_tea", "always make tea", {})


def decide_slime(tokens: int | None) -> Decision:
    if tokens is not None and tokens >= 75:
        return Decision("slime", "indulge", "tokens >= 75", {"tokens": tokens})
    why = "tokens unreadable" if tokens is None else "tokens < 75"
    return Decision("slime", "refuse", why, {"tokens": tokens})


def decide_minigame_taxi(tokens: int | None) -> Decision:
    if tokens is not None and tokens >= 75:
        return Decision("minigame_taxi", "taxi", "tokens >= 75", {"tokens": tokens})
    why = "tokens unreadable" if tokens is None else "tokens < 75"
    return Decision("minigame_taxi", "no_thanks", why, {"tokens": tokens})


def decide_shop_taxi(tokens: int | None) -> Decision:
    if tokens is not None and tokens >= 300:
        return Decision("shop_taxi", "travel", "tokens >= 300", {"tokens": tokens})
    why = "tokens unreadable" if tokens is None else "tokens < 300"
    return Decision("shop_taxi", "no_thanks", why, {"tokens": tokens})


def unlock_requirement_met(blob: str, hud: Hud) -> bool | None:
    """True when the unlock text's cost is one the player can pay. None when it states no cost.

    A key, or any gem price, is not met: the bot does not spend gems, and it cannot see a key count.
    Colour alone is not enough — a bright icon with "needs a key" still does not unlock.
    """
    n = normalize(blob)
    if re.search(r"\bgems?\b|\bdiamonds?\b|\bgold\b", n):
        return False
    ratio = re.search(r"(\d+)\s*/\s*(\d+)\s*keys?", n)
    if ratio:
        return int(ratio.group(1)) >= int(ratio.group(2))
    if re.search(r"\bkeys?\b|\bllave", n):
        return False
    cost = re.search(r"(\d+)\s*tokens?", n)
    if cost:
        if hud.tokens is None:
            return None
        return hud.tokens >= int(cost.group(1))
    return None


def decide_locked_box(unlock_enabled: bool | None, requirement_met: bool | None = None) -> Decision:
    if requirement_met is False:
        return Decision("locked_box", "look_around", "unlock requirement is not met", {})
    if unlock_enabled:
        return Decision("locked_box", "unlock", "unlock is tappable", {})
    why = "unlock greyed" if unlock_enabled is False else "unlock unreadable"
    return Decision("locked_box", "look_around", why, {})


def decide_kidnapped(pay_enabled: bool | None) -> Decision:
    if pay_enabled is False:
        return Decision("kidnapped", "escape", "pay is greyed", {})
    why = "pay them" if pay_enabled else "pay not found; escape"
    choice = "pay" if pay_enabled else "escape"
    return Decision("kidnapped", choice, why, {})


def decide_devil(skills: list[KnownSkill] | None, build: Build) -> Decision:
    if skills is None:
        return Decision("devil", "leave", "skill list unreadable", {})
    commons = [s for s in skills if normalize(s.rarity) == "common"]
    if len(commons) != 2:
        return Decision("devil", "leave", f"{len(commons)} common skills", {"commons": len(commons)})
    cores = [is_core_skill(s.name, build) for s in commons]
    if any(c is None for c in cores) or all(cores):
        why = "a common skill is unreadable" if any(c is None for c in cores) else "both commons are core"
        return Decision("devil", "leave", why, {"cores": cores})
    return Decision("devil", "sign", "exactly 2 commons and they are not both core", {"cores": cores})


def decide_chaos() -> Decision:
    return Decision("chaos_magician", "refuse", "never accept", {})


def decide_two_fight() -> Decision:
    return Decision("two_fight", "observe", "observe, then the normal skill pick", {})


def decide_anvil() -> Decision:
    return Decision("anvil", "take", "always take, never enhance", {})


def decide_haunting(rolls_used: int | None) -> Decision:
    if rolls_used is not None and rolls_used <= HAUNT_EMBRACE_UNTIL:
        return Decision("haunting", "embrace", "rolls used <= 10", {"rolls_used": rolls_used})
    why = "rolls unreadable" if rolls_used is None else "rolls used > 10"
    return Decision("haunting", "ignore", why, {"rolls_used": rolls_used})


def decide_cart() -> Decision:
    return Decision("abandoned_cart", "some", "always grab some coins", {})


def decide_goblin(hp_ratio: float | None) -> Decision:
    if hp_ratio is not None and hp_ratio > GOBLIN_RAID_HP:
        return Decision("goblin", "raid", "hp > 50%", {"hp": hp_ratio})
    why = "hp unreadable" if hp_ratio is None else "hp <= 50%"
    return Decision("goblin", "sneak", why, {"hp": hp_ratio})


def decide_springs(buttons: list[str], hp_ratio: float | None, cost_ratio: float | None) -> Decision:
    names = [normalize(b) for b in buttons]
    if not any("stay" in n for n in names):
        return Decision("boiling_springs", "enter", "enter the hot spring", {})
    inputs = {"hp": hp_ratio, "cost": cost_ratio}
    if hp_ratio is None or hp_ratio < SPRINGS_STAY_HP:
        why = "hp unreadable" if hp_ratio is None else "hp < 60%"
        return Decision("boiling_springs", "get_out", why, inputs)
    if cost_ratio is None or hp_ratio <= cost_ratio:
        why = "stay cost unreadable" if cost_ratio is None else "next stay would drop hp to 0"
        return Decision("boiling_springs", "get_out", why, inputs)
    return Decision("boiling_springs", "stay", "hp >= 60% and the next stay will not kill", inputs)


def decide_vista(rolls_used: int | None, skills_known: int | None) -> Decision:
    inputs = {"rolls_used": rolls_used, "skills_known": skills_known}
    if rolls_used is None or skills_known is None:
        return Decision("vista", "resist", "rolls or skill count unreadable", inputs)
    if rolls_used <= VISTA_GAZE_UNTIL and skills_known <= 2:
        return Decision("vista", "gaze", "rolls used <= 5 and at most 2 skills", inputs)
    return Decision("vista", "resist", "default resist", inputs)


def reward_is_skill(blob: str | None) -> bool:
    """The Read column names a skill (Enraged Strength), not a stat line (+5% ATK/DEF/HP)."""
    if not blob:
        return False
    n = normalize(blob)
    n = re.sub(r"\bread\b", " ", n)
    words = [w for w in re.findall(r"[a-z]{4,}", n) if w not in _STAT_WORDS | {"instead", "work", "skill", "learn", "gain"}]
    return bool(words)


def decide_book(read_blob: str | None) -> Decision:
    if reward_is_skill(read_blob):
        return Decision("magical_book", "read", "read reward is a skill", {"reward": read_blob})
    why = "reward unreadable" if not read_blob else "read reward is not a skill"
    return Decision("magical_book", "work_out", why, {"reward": read_blob})


def _content_of(blob: str) -> frozenset:
    n = normalize(blob)
    found = set()
    table = {
        "statue": ("prayer", "statue", "shrine"),
        "shop": ("shop", "tienda"),
        "chest": ("chest", "locked", "coffer", "padlock"),
        "anvil": ("anvil", "blacksmith", "hammer", "forge"),
        "campfire": ("campfire", "bonfire", "camp fire"),
    }
    for kind, words in table.items():
        if any(w in n for w in words):
            found.add(kind)
    # Ancient Waterway's locked chest often has no word, only the "000" on the lock.
    if "000" in n.replace(" ", ""):
        found.add("chest")
    return frozenset(found)


def path_cards(texts: list[Text]) -> list[PathCard]:
    """Path A / Path B cards. Content comes from the text on that card, not from the letter."""
    labels = []
    for t in texts:
        m = _PATH_LABEL.match(t.norm)
        if m and len(t.norm) <= 8:
            labels.append((m.group(1).upper(), t))
    if len(labels) < 2:
        return []
    cards = []
    for key, label in labels:
        others = [o.center[0] for k, o in labels if o is not label]
        parts = [label.text]
        for t in texts:
            if t is label or t.center[1] > label.center[1] + 60:
                continue
            if t.center[1] < label.center[1] - 520:
                continue
            if abs(t.center[0] - label.center[0]) > 220:
                continue
            if others and min(abs(t.center[0] - x) for x in others) < abs(t.center[0] - label.center[0]):
                continue
            parts.append(t.text)
        blob = " ".join(parts)
        cards.append(PathCard(key, _content_of(blob), blob, label.center))
    return cards


def _card(cards: list[PathCard], kind: str, letter: str) -> PathCard | None:
    found = [c for c in cards if kind in c.content]
    if len(found) == 1:
        return found[0]
    return next((c for c in cards if c.key == letter), None)


def decide_path(board: str | None, cards: list[PathCard], tokens: int | None, rolls_left: int | None,
                min_skill_price: int = config.SHOP_SKILL_FLOOR) -> Decision:
    """Which path card to take. None when the board and the card contents are both unknown.

    Letters are only the names from the table for a known board. An unknown board is
    decided from what is drawn on the cards (statue, shop, chest, anvil, campfire).
    """
    kinds = set()
    for c in cards:
        kinds |= set(c.content)
    resolved = board
    if resolved is None:
        if "statue" in kinds and "shop" in kinds:
            resolved = "elysium"
        elif "chest" in kinds and ("anvil" in kinds or "shop" in kinds) and "statue" not in kinds and "campfire" not in kinds:
            resolved = "ancient waterway"
        elif "campfire" in kinds and "shop" in kinds:
            resolved = "atlantis"
    inputs = {"board": resolved, "tokens": tokens, "rolls_left": rolls_left,
              "cards": [{"key": c.key, "content": sorted(c.content)} for c in cards]}

    def take(card: PathCard | None, reason: str) -> Decision:
        if card is None:
            return Decision("path", None, reason + "; card not found", inputs)
        return Decision("path", card.key, reason, {**inputs, "content": sorted(card.content)})

    if resolved == "molten core":
        return Decision("path", None, "molten core has no path choice", inputs)
    if resolved is None:
        # The board name was not read. A shop (or anvil) beats a locked chest and an empty card.
        # Never the leftmost card: on Ancient Waterway that is the locked chest.
        shops = [c for c in cards if "shop" in c.content or "anvil" in c.content]
        if shops and "statue" not in kinds and "campfire" not in kinds:
            return take(shops[0], "board unknown; taking the shop, not a locked chest")
        return Decision("path", None, "board and path contents unreadable", inputs)

    if resolved == "ancient waterway":
        # The anvil and the shop. Content wins over the letter, so a shop drawn on A is
        # still the shop. The letter B is only the fallback when the pictures were not read,
        # and it is never a card we can see is a locked chest.
        wanted = [c for c in cards if "anvil" in c.content or "shop" in c.content]
        if len(wanted) == 1:
            return take(wanted[0], "ancient waterway always takes anvil + shop")
        card = next((c for c in wanted if c.key == "B"), None)
        if card is None:
            card = _card(cards, "anvil", "B") or _card(cards, "shop", "B")
        if card and "chest" in card.content and "shop" not in card.content and "anvil" not in card.content:
            card = None
        return take(card, "ancient waterway always takes anvil + shop")
    if resolved == "elysium":
        shop, statue = _card(cards, "shop", "B"), _card(cards, "statue", "A")
        if tokens is None:
            return take(statue, "tokens unreadable")
        if tokens >= 300:
            return take(shop, "tokens >= 300")
        if rolls_left is not None and rolls_left <= LATE_ROLLS and tokens > 0:
            return take(shop, "rolls left <= 5 and tokens remain")
        return take(statue, "else the prayer statue")
    # atlantis
    shop, camp = _card(cards, "shop", "A"), _card(cards, "campfire", "B")
    if tokens is not None and tokens >= 300:
        return take(shop, "tokens >= 300")
    if (rolls_left is not None and rolls_left <= LAST_SHOP_ROLLS and tokens is not None
            and tokens >= min_skill_price):
        return take(shop, "shop will not come around again and a skill is affordable")
    return take(camp, "default campfire")


# event id, title phrases, choice id -> button phrases
_EVENTS = (
    ("statue", ("statue of the gods",), {"pray": ("pray",), "offering": ("make an offering", "offering")}),
    ("cursed_vendor", ("cursed vendor",), {"sign": ("sign",)}),
    ("mysterious_herb", ("the mysterious herb", "mysterious herb"),
     {"make_tea": ("make tea",), "eat": ("eat it",)}),
    ("slime", ("slime culinarian",), {"indulge": ("indulge",), "refuse": ("refuse",)}),
    ("minigame_taxi", ("magical minigame taxi", "minigame taxi"),
     {"taxi": ("take the taxi",), "no_thanks": ("no thanks",)}),
    ("shop_taxi", ("magical shop taxi", "the magical shop taxi"),
     {"travel": ("travel to shop", "travel"), "no_thanks": ("no thanks",)}),
    ("locked_box", ("the locked box", "locked box"),
     {"look_around": ("look around",), "unlock": ("unlock box", "unlock")}),
    ("kidnapped", ("kidnapped",), {"escape": ("escape",), "pay": ("pay them",)}),
    ("devil", ("another deal with the devil", "deal with the devil"),
     {"sign": ("sign",), "leave": ("leave",)}),
    ("chaos_magician", ("chaos magician",), {"refuse": ("refuse",), "accept": ("accept",)}),
    ("two_fight", ("two fight, the third benefits", "two fight the third benefits", "the third benefits"),
     {"observe": ("observe",)}),
    ("anvil", ("blacksmith's anvil", "blacksmiths anvil", "blacksmith anvil"),
     {"take": ("take",), "enhance": ("enhance",)}),
    ("haunting", ("haunting spirits",), {"embrace": ("embrace",), "ignore": ("ignore",)}),
    ("abandoned_cart", ("another abandoned cart", "abandoned cart"),
     {"some": ("grab some", "some coins"), "many": ("grab many", "many coins")}),
    ("goblin", ("goblin encampment",), {"raid": ("raid camp", "raid"), "sneak": ("sneak in", "sneak")}),
    ("boiling_springs", ("the boiling springs", "boiling springs"),
     {"enter": ("enter hot spring", "hot spring", "enter"), "stay": ("stay",), "get_out": ("get out",)}),
    ("vista", ("a disorienting vista", "disorienting vista"), {"resist": ("resist",), "gaze": ("gaze",)}),
    ("magical_book", ("the magical book", "magical book"),
     {"read": ("read",), "work_out": ("work out",)}),
    ("treasure_miner", ("treasure miner",), {}),
)


def _title_line(text: str, phrase: str) -> bool:
    return _line_has(text, phrase) and len(normalize(text)) <= len(normalize(phrase)) + 12


def match_event(texts: list[Text]) -> str | None:
    """The known World 2 event whose title line is on screen, most specific phrase first."""
    hits = []
    for event, titles, _choices in _EVENTS:
        for t in texts:
            for phrase in titles:
                if _title_line(t.text, phrase):
                    hits.append((len(normalize(phrase)), event))
    if not hits:
        return None
    return max(hits)[1]


def is_known_title(title: str) -> bool:
    """World 2 titles and the World 1 events the generic handler already owns."""
    n = normalize(title)
    if any(normalize(p) in n for _e, titles, _c in _EVENTS for p in titles):
        return True
    return any(p in n for p in KNOWN_OTHER_TITLES)


def is_miner(texts: list[Text]) -> bool:
    return match_event(texts) == "treasure_miner"


def choice_labels(texts: list[Text]) -> list[Text]:
    """Button names in the bottom half. The title banner sits above them."""
    cutoff = config.SCREEN_SIZE[1] // 2
    return [t for t in texts if t.center[1] >= cutoff and re.search(r"[a-z]{2}", t.norm)]


def _column_blob(label: Text, texts: list[Text]) -> str:
    parts = [label.text]
    for t in texts:
        if t is label:
            continue
        if abs(t.center[0] - label.center[0]) <= config.EVENT_COLUMN_X and t.center[1] > label.center[1]:
            parts.append(t.text)
    return " ".join(parts)


def choice_tap(label: Text, texts: list[Text]) -> tuple[int, int]:
    """Where to tap. The icon sits between the choice name and the description under it.

    A button whose text is the button (Take, Path A, Leave) has nothing below it: tap the text.
    """
    below = [t for t in texts if 40 < t.center[1] - label.center[1] < 460
             and abs(t.center[0] - label.center[0]) <= config.EVENT_COLUMN_X and t is not label]
    if not below:
        return label.center
    nxt = min(below, key=lambda t: t.center[1])
    return label.center[0], (label.center[1] + nxt.center[1]) // 2


def _option_enabled(img: np.ndarray | None, label: Text) -> bool:
    if img is None:
        return True
    x, y = label.center[0], label.center[1] + config.EVENT_ICON_BELOW_LABEL
    h, w = img.shape[:2]
    y1, y2 = max(0, y - 80), min(h, y + 80)
    x1, x2 = max(0, x - 80), min(w, x + 80)
    if y2 <= y1 or x2 <= x1:
        return True
    roi = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    return float(roi[..., 1].mean()) > config.EVENT_DISABLED_MAX_SATURATION


def _buttons(texts: list[Text], phrases: dict[str, tuple[str, ...]]) -> dict[str, Text]:
    found = {}
    for t in choice_labels(texts):
        for key, options in phrases.items():
            if key in found:
                continue
            if any(_line_has(t.text, p) and len(t.norm) <= len(normalize(p)) + 10 for p in options):
                found[key] = t
    return found


def _offering_skill(blob: str) -> str | None:
    m = re.search(r"forget\s+(.+)", normalize(blob))
    if not m:
        return None
    name = re.sub(r"\b(?:major|minor|boon|simple|receive|a|an)\b", " ", m.group(1))
    name = re.sub(r"\b(?:lv|lvl|level)\.?\s*\d+\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .:-")
    return name or None


def _stay_cost(blob: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", normalize(blob))
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) / 100.0


def _enabled_flags(img, buttons: dict[str, Text]) -> dict[str, bool]:
    flags = {key: _option_enabled(img, label) for key, label in buttons.items()}
    if flags and not any(flags.values()):
        return {key: True for key in flags}  # a blank frame cannot mark every icon grey
    return flags


def _decide(event: str, texts: list[Text], buttons: dict[str, Text], hud: Hud, build: Build,
            skills: list[KnownSkill] | None, enabled: dict[str, bool]) -> Decision:
    blob = {key: _column_blob(label, texts) for key, label in buttons.items()}
    if event == "statue":
        return decide_statue(_offering_skill(blob.get("offering", "")), build)
    if event == "cursed_vendor":
        bodies = vendor_bodies(texts)
        if bodies:
            return decide_vendor(bodies[0], bodies[1], hud.rolls_left)
        return Decision("cursed_vendor", None, "the two sign cards were not both read", {})
    if event == "mysterious_herb":
        return decide_herb()
    if event == "slime":
        return decide_slime(hud.tokens)
    if event == "minigame_taxi":
        return decide_minigame_taxi(hud.tokens)
    if event == "shop_taxi":
        return decide_shop_taxi(hud.tokens)
    if event == "locked_box":
        unlock = buttons.get("unlock")
        blob = ""
        if unlock is not None:
            blob = _column_blob(unlock, texts) + " " + _body_above(unlock, buttons.get("look_around"), texts)
        met = unlock_requirement_met(blob, hud)
        return decide_locked_box(enabled.get("unlock") if unlock is not None else None, met)
    if event == "kidnapped":
        return decide_kidnapped(enabled.get("pay") if "pay" in buttons else None)
    if event == "devil":
        return decide_devil(skills, build)
    if event == "chaos_magician":
        return decide_chaos()
    if event == "two_fight":
        return decide_two_fight()
    if event == "anvil":
        return decide_anvil()
    if event == "haunting":
        return decide_haunting(hud.rolls_used)
    if event == "abandoned_cart":
        return decide_cart()
    if event == "goblin":
        return decide_goblin(hud.hp_ratio)
    if event == "boiling_springs":
        return decide_springs(list(buttons), hud.hp_ratio, _stay_cost(blob.get("stay", "")))
    if event == "vista":
        return decide_vista(hud.rolls_used, len(skills) if skills is not None else None)
    if event == "magical_book":
        return decide_book(blob.get("read"))
    return Decision(event, None, "no rule", {})


def level_tap(img, texts: list[Text], build: Build | None = None, board: str | None = None,
              skills: list[KnownSkill] | None = None, min_skill_price: int | None = None) -> tuple[int, int] | None:
    """Tap for a World 2 path fork or a known World 2 event. None if this frame is neither.

    Sets LAST to the decision (including a path that could not be read). Campfire and
    World 1 events return None so the existing handler keeps them.
    """
    global LAST
    build = build or Build()
    hud = read_hud(texts)
    price = config.SHOP_SKILL_FLOOR if min_skill_price is None else min_skill_price
    cards = path_cards(texts)
    if len(cards) >= 2:
        known = {"elysium", "ancient waterway", "molten core", "atlantis"}
        resolved = board if board in known else board_from_title(board)
        decision = decide_path(resolved, cards, hud.tokens, hud.rolls_left, price)
        LAST = decision
        _log(decision, hud)
        chosen = next((c for c in cards if c.key == decision.choice), None)
        return None if chosen is None else choice_tap(
            Text(chosen.key, chosen.tap[0] - 20, chosen.tap[1] - 16, chosen.tap[0] + 20, chosen.tap[1] + 16), texts)
    event = match_event(texts)
    if event is None or event == "treasure_miner":
        LAST = None
        return None
    phrases = next(c for e, _t, c in _EVENTS if e == event)
    buttons = _buttons(texts, phrases)
    enabled = _enabled_flags(img, buttons)
    decision = _decide(event, texts, buttons, hud, build, skills, enabled)
    LAST = decision
    _log(decision, hud)
    label = buttons.get(decision.choice or "")
    if label is None:
        return None
    return choice_tap(label, texts)


def _log(decision: Decision, hud: Hud) -> None:
    log.info("W2 %s: choice %s (%s) tokens=%s hp=%s/%s rolls=%s/%s inputs=%s",
             decision.event, decision.choice, decision.reason, hud.tokens, hud.hp, hud.max_hp,
             hud.rolls_used, hud.rolls_total, decision.inputs)
    for line in decision.inputs.get("unknown") or []:
        log.info("W2 cursed vendor unknown line: %s", line)


_BATTLE_RE = re.compile(r"(?:round|ronda)\s*:?\s*\d+\s*/\s*\d+")


def is_battle(texts: list[Text]) -> bool:
    """A fight HUD ("Round 1/30"). Not a skill named Round Bolt."""
    return any(_BATTLE_RE.search(t.norm) for t in texts)


def is_skill_offer(texts: list[Text]) -> bool:
    """POWER UP! / LEVEL UP! with "Select a Skill to learn!" — the normal skill picker owns this.

    The banner match is the short ribbon only, so a description that mentions a level-up does not count.
    """
    if find(texts, L.SKILL_PROMPT):
        return True
    banner = False
    for t in texts:
        n = t.norm.strip("!¡ ")
        if len(n) <= 28 and n in ("power up", "level up", "subiste de nivel", "subida de poder"):
            banner = True
            break
    if not banner:
        return False
    return any(find(texts, rarity, exact=True) for rarity in L.RARITIES)


def is_path_fork(texts: list[Text]) -> bool:
    return len(path_cards(texts)) >= 2


def ordinary_level_screen(texts: list[Text]) -> bool:
    """A fight, a skill pick, or a path fork. Never an unknown event."""
    return is_battle(texts) or is_skill_offer(texts) or is_path_fork(texts)


def looks_like_event(texts: list[Text]) -> bool:
    """A title-like line plus two choices in the bottom half. Not a fight, skill pick, path, shop or the board."""
    if ordinary_level_screen(texts):
        return False
    labels = choice_labels(texts)
    if len(labels) < 2:
        return False
    short = [t for t in texts if 8 <= len(t.norm) <= 40 and t.center[1] < config.SCREEN_SIZE[1] * 0.72]
    return bool(short)


def event_title(texts: list[Text]) -> str | None:
    """The banner above the choice buttons, for the unknown-event filename.

    Body lines under the buttons ("Restaura", "30% de HP") are not the title.
    """
    labels = choice_labels(texts)
    if len(labels) < 2:
        return None
    top = min(t.center[1] for t in labels)
    mid = config.SCREEN_SIZE[0] // 2
    lines = [t for t in texts if t.center[1] < top - 30 and abs(t.center[0] - mid) < 420
             and 10 <= len(t.norm) <= 48 and t.center[1] > config.TOP_BAR_MAX_Y]
    if not lines:
        return None
    return min(lines, key=lambda t: abs(t.center[0] - mid)).text


def costly(text: str) -> bool:
    n = normalize(text)
    if any(w in n for w in ("token", "gem", "diamond", "forget", "% hp", "max hp")):
        return True
    if "lose" in n and re.search(r"\d", n):
        return True
    return False


def safe_option(options: list[tuple[str, str]]) -> int:
    """Index of the safe choice. options are (label, column blob).

    Walk-away / leave / refuse / no-thanks first. Otherwise the option that costs nothing.
    If every option costs something, the smallest stated number, then the first option.
    """
    for i, (label, _blob) in enumerate(options):
        n = normalize(label)
        if any(w in n for w in SAFE_WORDS):
            return i
    free = [i for i, (_label, blob) in enumerate(options) if not costly(blob)]
    if free:
        return free[0]

    def amount(i: int) -> int:
        m = re.search(r"(\d+)", options[i][1])
        return int(m.group(1)) if m else 10**9

    return min(range(len(options)), key=lambda i: (amount(i), i)) if options else 0


def tap_forbidden(point: tuple[int, int]) -> bool:
    """The bottom-left speed / VIP badge. A fallback tap here turns x4 off."""
    x, y = point
    return x < 420 and y > 2050


def safe_leave_label(texts: list[Text]) -> Text | None:
    """A recognized no-cost leave / walk-away label. Nothing else, and never the speed button."""
    if ordinary_level_screen(texts):
        return None
    for t in choice_labels(texts):
        if not any(w in t.norm for w in SAFE_WORDS):
            continue
        blob = _column_blob(t, texts)
        if costly(t.text) or costly(blob):
            continue
        point = choice_tap(t, texts)
        if tap_forbidden(point) or tap_forbidden(t.center):
            continue
        return t
    return None


def _body_above(label: Text, other: Text | None, texts: list[Text]) -> str:
    """Card text above a button. Sign's blessing and curse sit above the button, not under it."""
    parts = []
    for t in texts:
        if t is label or t is other:
            continue
        dy = label.center[1] - t.center[1]
        if dy < 24 or dy > 760:
            continue
        if other is not None and abs(t.center[0] - other.center[0]) + 40 < abs(t.center[0] - label.center[0]):
            continue
        if abs(t.center[0] - label.center[0]) > 360:
            continue
        parts.append(t)
    parts.sort(key=lambda t: (t.center[1], t.center[0]))
    return " ".join(t.text for t in parts)


def vendor_bodies(texts: list[Text]) -> tuple[str, str] | None:
    """Blessing and curse text of the left and right Sign cards.

    The lines are above each Sign button. Text under the button is the page footer, not the offer.
    """
    signs = sorted((t for t in choice_labels(texts) if t.norm == "sign" or t.norm.startswith("sign ")),
                   key=lambda t: t.center[0])
    if len(signs) < 2:
        return None
    return _body_above(signs[0], signs[1], texts), _body_above(signs[1], signs[0], texts)


def fallback_path_tap(texts: list[Text]) -> tuple[int, int] | None:
    """A shop card when the fork could not be named. Never the locked chest, never a blind left tap."""
    cards = path_cards(texts)
    shops = [c for c in cards if "shop" in c.content or "anvil" in c.content]
    if len(shops) != 1:
        return None
    if tap_forbidden(shops[0].tap):
        return None
    return shops[0].tap


# --- Treasure Miner -----------------------------------------------------------------

_SHAPES = (
    frozenset((0, c) for c in range(4)),                          # 1x4
    frozenset((r, 0) for r in range(4)),                          # 4x1
    frozenset((r, c) for r in range(2) for c in range(3)),        # 2x3
    frozenset((r, c) for r in range(3) for c in range(2)),        # 3x2
)


def _placements(shape: frozenset, size: int = MINER_SIZE):
    rows = max(r for r, _c in shape) + 1
    cols = max(c for _r, c in shape) + 1
    for r in range(size - rows + 1):
        for c in range(size - cols + 1):
            yield frozenset((r + dr, c + dc) for dr, dc in shape)


def _gems(board) -> set[tuple[int, int]]:
    return {(r, c) for r in range(len(board)) for c in range(len(board[0])) if board[r][c] == GEM}


def _components(board) -> list[frozenset]:
    gems = _gems(board)
    seen = set()
    comps = []
    for start in sorted(gems):
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            cur = stack.pop()
            if cur in comp:
                continue
            comp.add(cur)
            r, c = cur
            for nxt in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if nxt in gems and nxt not in comp:
                    stack.append(nxt)
        seen |= comp
        comps.append(frozenset(comp))
    return comps


def _complete(comp: frozenset) -> bool:
    if len(comp) not in (4, 6):
        return False
    return any(comp == place for shape in _SHAPES if len(shape) == len(comp) for place in _placements(shape))


def _neighbors(comp: frozenset, size: int = MINER_SIZE):
    out = set()
    for r, c in comp:
        for nxt in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            nr, nc = nxt
            if 0 <= nr < size and 0 <= nc < size and nxt not in comp:
                out.add(nxt)
    return out


def _covers(comp: frozenset, board) -> list[frozenset]:
    size = len(board)
    out = []
    for shape in _SHAPES:
        if len(shape) < len(comp):
            continue
        for place in _placements(shape, size):
            if not comp <= place:
                continue
            if any(board[r][c] == DUG for r, c in place):
                continue
            if any(board[r][c] == GEM and (r, c) not in comp for r, c in place):
                continue
            out.append(place)
    return out


def _hunt(board) -> tuple[int, int] | None:
    undug = [(r, c) for r in range(len(board)) for c in range(len(board[0])) if board[r][c] == UNK]
    if not undug:
        return None

    def rank(cell):
        r, c = cell
        # Stride-2 lattice first (spread out), then the rest of the checkerboard, then the gaps.
        if r % 2 == 0 and c % 2 == 0:
            group = 0
        elif (r + c) % 2 == 0:
            group = 1
        else:
            group = 2
        return group, r, c

    return min(undug, key=rank)


def next_miner_tap(board, pickaxes: int) -> tuple[int, int] | None:
    """Next undug cell, or None when there are no pickaxes or no undug cells.

    A partial gem (a hit that is not yet a 1x4 or a 2x3, either orientation) is finished
    first: dig a cell that every possible completion still needs, else the neighbor that
    fits the most completions. Otherwise hunt on a stride / checkerboard of undug cells.
    Dug cells are never returned.
    """
    if pickaxes <= 0:
        return None
    partials = [c for c in _components(board) if not _complete(c)]
    if partials:
        comp = max(partials, key=lambda c: (len(c), sorted(c)))
        places = _covers(comp, board)
        neigh = {cell for cell in _neighbors(comp) if board[cell[0]][cell[1]] == UNK}
        if places:
            forced = set(places[0])
            for place in places[1:]:
                forced &= place
            forced = {cell for cell in forced if board[cell[0]][cell[1]] == UNK}
            prefer = forced & neigh or forced
            if prefer:
                return min(prefer)
            counts: dict[tuple[int, int], int] = {}
            for place in places:
                for cell in place:
                    if cell in neigh:
                        counts[cell] = counts.get(cell, 0) + 1
            if counts:
                return max(counts, key=lambda cell: (counts[cell], -cell[0], -cell[1]))
        if neigh:
            return min(neigh)
    return _hunt(board)


def merge_board(old, new):
    """A revealed cell stays revealed. A later frame cannot bury a gem or an empty hole."""
    if old is None:
        return new
    out = []
    for r in range(MINER_SIZE):
        row = []
        for c in range(MINER_SIZE):
            a, b = old[r][c], new[r][c]
            if a == GEM or b == GEM:
                row.append(GEM)
            elif a == DUG or b == DUG:
                row.append(DUG)
            else:
                row.append(UNK)
        out.append(row)
    return out


def _classify_cell(b: float, g: float, r: float) -> int:
    mx, mn = max(b, g, r), min(b, g, r)
    if mx < 75:
        return DUG
    if mx > 0 and (mx - mn) / mx > 0.35 and mx > 90:
        return GEM
    return UNK


def read_miner_grid(img: np.ndarray):
    """7x7 cell classes and centers, from the tile squares themselves.

    None when a regular 7 by 7 of similar squares is not in the middle of the frame.
    Colors: a saturated tile is a gem, a near-black tile is dug and empty, the rest is undug.
    Real gem art may not match these cutoffs; a miss is logged and the visit can still Leave.
    """
    if img is None or img.size == 0 or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    y0, y1 = int(h * 0.16), int(h * 0.78)
    x0, x1 = int(w * 0.05), int(w * 0.95)
    roi = img[y0:y1, x0:x1]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    contours, _hier = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = roi.shape[0] * roi.shape[1]
    boxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 8 or bh < 8:
            continue
        if not 0.72 <= bw / bh <= 1.38:
            continue
        if not area / 140 <= bw * bh <= area / 20:
            continue
        boxes.append((x + bw / 2, y + bh / 2, bw, bh))
    if len(boxes) < MINER_SIZE * 4:
        return None
    xs = _cluster([b[0] for b in boxes], MINER_SIZE)
    ys = _cluster([b[1] for b in boxes], MINER_SIZE)
    if xs is None or ys is None:
        return None
    board = [[UNK for _ in range(MINER_SIZE)] for _ in range(MINER_SIZE)]
    centers = [[None for _ in range(MINER_SIZE)] for _ in range(MINER_SIZE)]
    for cx, cy, _bw, _bh in boxes:
        col = min(range(MINER_SIZE), key=lambda i: abs(xs[i] - cx))
        row = min(range(MINER_SIZE), key=lambda i: abs(ys[i] - cy))
        px, py = int(x0 + cx), int(y0 + cy)
        px = min(w - 1, max(0, px))
        py = min(h - 1, max(0, py))
        b, g, r = (float(v) for v in img[py, px])
        board[row][col] = _classify_cell(b, g, r)
        centers[row][col] = (px, py)
    for row in range(MINER_SIZE):
        for col in range(MINER_SIZE):
            if centers[row][col] is not None:
                continue
            px = min(w - 1, max(0, int(x0 + xs[col])))
            py = min(h - 1, max(0, int(y0 + ys[row])))
            b, g, r = (float(v) for v in img[py, px])
            board[row][col] = _classify_cell(b, g, r)
            centers[row][col] = (px, py)
    return board, centers


def _cluster(values: list[float], k: int) -> list[float] | None:
    vals = sorted(values)
    if len(vals) < k:
        return None
    gaps = sorted(((vals[i + 1] - vals[i], i) for i in range(len(vals) - 1)), reverse=True)[:k - 1]
    cuts = sorted(i for _gap, i in gaps)
    groups, start = [], 0
    for i in cuts:
        groups.append(vals[start:i + 1])
        start = i + 1
    groups.append(vals[start:])
    if len(groups) != k or any(not g for g in groups):
        return None
    return [sum(g) / len(g) for g in groups]


def miner_out(texts: list[Text]) -> bool:
    return any("we're out" in t.norm or "were out" in t.norm or "out of pick" in t.norm for t in texts)


def find_blue_chest(img: np.ndarray) -> tuple[int, int] | None:
    """Centroid of the largest blue blob in the middle of the frame (the raid chest).

    Only called after a goblin raid, and only when the frame has no other button to tap.
    """
    if img is None or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    y0, y1 = int(h * 0.25), int(h * 0.75)
    x0, x1 = int(w * 0.2), int(w * 0.8)
    roi = img[y0:y1, x0:x1].astype(int)
    b, g, r = roi[..., 0], roi[..., 1], roi[..., 2]
    mask = (b > 140) & (b > r + 40) & (b > g + 15)
    if int(mask.sum()) < 400:
        return None
    ys, xs = np.nonzero(mask)
    return int(xs.mean()) + x0, int(ys.mean()) + y0


def slug(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", normalize(title)).strip("_")
    return (cleaned or "untitled")[:40]
