"""World 2 choices. Pure: HUD values and OCR text in, a choice out. No taps.

The player logs each decision and taps the button the text was read from. A title that
matches nothing is not decided here; the unknown-event catcher records it and picks a
safe option. Campfire, Wise Monk and World 1 events stay in screens.py / play.py.
"""

import logging
import random
import re
from dataclasses import dataclass, field, replace

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
    # 2.0.3 playtest. The golden road is a strong blessing. Doubled shop prices is the
    # mildest curse: take that card over any heavier curse.
    {"id": "golden_road", "kind": "blessing", "score": 95,
     "phrases": ("create a golden road of mega buff tiles", "golden road of mega buff", "mega buff tiles")},
    {"id": "shop_prices", "kind": "curse", "score": 5,
     "phrases": ("shop prices are doubled", "prices are doubled")},
)

# TODO: remove coin flip after full data. Unknown curses, boons, and events are not
# ranked yet, so a choice the weights cannot separate used to wait forever.
COIN_FLIP_TEMPORARY = True

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


class RollTracker:
    """Last N/30 read on the map, and a dice roll that the map has not confirmed yet.

    Event screens hide the counter, so a rule that needs the roll count would otherwise
    see "unreadable". `observe` stores the counter whenever it is on screen. `note_roll`
    bumps that count when this bot rolls the dice, until a later map frame confirms it.
    `reset` at the start of each level: the counter is per level, not per session.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.used: int | None = None
        self.total: int | None = None
        self.pending = False
        self._stale = 0

    def observe(self, texts: list[Text]) -> bool:
        """True when this frame showed N/30. A lower number right after a roll is the old frame."""
        seen = _rolls(texts)
        if not seen:
            return False
        used, total = seen
        if self.pending and self.used is not None and used < self.used:
            self._stale += 1
            if self._stale < 3:
                return True
        self._stale = 0
        self.used, self.total = used, total
        self.pending = False
        return True

    def note_roll(self) -> None:
        """The dice was just rolled. The map still paints the previous N for a frame or two."""
        if self.used is None or self.pending:
            return
        self.used += 1
        if self.total is not None:
            self.used = min(self.used, self.total)
        self.pending = True
        self._stale = 0

    def cached(self) -> tuple[int, int] | None:
        if self.used is None:
            return None
        return self.used, self.total if self.total is not None else 30


def with_cached_rolls(hud: Hud, rolls: tuple[int, int] | None) -> Hud:
    """Fill a HUD whose counter is hidden from the last known N/30. A visible counter wins."""
    if hud.rolls_used is not None or not rolls:
        return hud
    return replace(hud, rolls_used=rolls[0], rolls_total=rolls[1])


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


_VENDOR_HEADER = re.compile(r"\b(?:cursed vendor|curses for a price)\b")


def clean_vendor_text(text: str) -> str:
    """Drop the banner and a leading '0' OCR reads on the sign cards.

    '0 Shop prices are doubled' and 'Cursed Vendor CURSES FOR A PRICE ...' are the
    same lines the table already knows once that junk is gone. Line breaks stay, so
    a real unknown curse on its own line is still reported.
    """
    lines = []
    for line in text.splitlines() or [""]:
        n = normalize(line)
        n = re.sub(r"\b0\b", " ", n)
        n = _VENDOR_HEADER.sub(" ", n)
        n = re.sub(r"[ \t]+", " ", n).strip(" .")
        if n:
            lines.append(n)
    return "\n".join(lines)


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
    An unknown clause does not block the tap: it adds nothing, and the known side still wins.
    """
    text = clean_vendor_text(text)
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
    text = clean_vendor_text(text)
    return _best_rule(text, "blessing") is not None or _best_rule(text, "curse") is not None


def coin_flip_temporary(options: list[str], rng=None, pick: str | None = None) -> str | None:
    """Random pick among options the weights cannot separate.

    TODO: remove coin flip after full data. Every call logs
    'COIN FLIP (temporary): options [...] -> picked X' so it can be found and deleted.
    `pick` retries a later option after the previous tap did nothing; it is still logged.
    """
    if not options or not COIN_FLIP_TEMPORARY:
        return None
    if pick is None:
        pick = (rng or random).choice(list(options))
    elif pick not in options:
        return None
    log.info("COIN FLIP (temporary): options %s -> picked %s", list(options), pick)
    return pick


def decide_vendor(left: str, right: str, rolls_left: int | None, rng=None) -> Decision:
    ls, lu = score_vendor_card(left, rolls_left)
    rs, ru = score_vendor_card(right, rolls_left)
    unknown = lu + ru
    parsed = (_side_parsed(left), _side_parsed(right))
    # Known weights tied, and at least one line is not in the table: flip so the screen
    # cannot sit there. A tie of two fully known cards stays on the left, as before.
    if ls == rs and (unknown or not all(parsed)):
        choice = coin_flip_temporary(["left", "right"], rng)
        reason = "COIN FLIP (temporary); known weights tied on unknown lines"
    else:
        choice = "left" if ls >= rs else "right"
        reason = f"left {ls} vs right {rs}"
    return Decision("cursed_vendor", choice, reason,
                    {"left": ls, "right": rs, "rolls_left": rolls_left, "unknown": unknown,
                     "left_parsed": parsed[0], "right_parsed": parsed[1],
                     "left_text": clean_vendor_text(left), "right_text": clean_vendor_text(right),
                     "coin_flip": choice is not None and ls == rs and bool(unknown or not all(parsed))})


def vendor_needs_shot(decision: Decision | None) -> bool:
    """A side with no recognized line, or a clause that matches no rule, should be saved."""
    if decision is None or decision.event != "cursed_vendor":
        return False
    if decision.inputs.get("unknown"):
        return True
    return not decision.inputs.get("left_parsed") or not decision.inputs.get("right_parsed")


def clean_card_name(name: str) -> str:
    """Strip a leading '0' and other OCR junk glued onto a boon or skill name."""
    text = (name or "").strip()
    text = re.sub(r"^(?:0[\s.:-]*)+", "", text)
    text = re.sub(r"^[^A-Za-z]+", "", text).strip()
    return text or (name or "").strip()


# Interim major-boon order for the poison farm (Plague Blade + Venom Loop).
# (1) poison / DoT / status damage, (2) flat ATK / damage / crit,
# (3) Max HP / damage reduction / shield, (4) utility. Attack outranks defense.
_BOON_TIERS = (
    ("poison", "venom", "toxic", "bleed", "wound", "damage over time"),
    ("atk", "attack", "damage", "dmg", "crit"),
    ("max hp", "damage reduction", "shield", "armor", "defense", "defence"),
    ("gold", "reroll", "token"),
)


def _boon_has(text: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def boon_sort_key(name: str, description: str) -> tuple:
    """Lower is better. A tie prefers a line that says damage or poison."""
    text = normalize(f"{name} {description}")
    tier = next((i for i, words in enumerate(_BOON_TIERS) if any(_boon_has(text, w) or w in text and " " in w
                                                                  for w in words)), 9)
    prefer = 0 if any(_boon_has(text, w) for w in ("damage", "poison", "venom", "dmg")) else 1
    return tier, prefer


def choose_boon(offers: list[tuple[str, str]], build: Build | None = None, rng=None) -> int:
    """Index of the major boon to take. A pure tie of unknown lines is a coin flip.

    A name that is one of the active preset's core skills outranks the interim list.
    """
    if not offers:
        return 0
    build = build or Build()

    def key(i: int) -> tuple:
        name, desc = offers[i]
        core = is_core_skill(clean_card_name(name), build)
        return (0 if core else 1, *boon_sort_key(name, desc), i)

    best = min(range(len(offers)), key=key)
    top = key(best)[:3]
    tied = [i for i in range(len(offers)) if key(i)[:3] == top]
    if len(tied) == 1:
        return tied[0]
    labels = [offers[i][0] for i in tied]
    pick = coin_flip_temporary(labels, rng)
    if pick is None:
        return tied[0]
    return tied[labels.index(pick)]


def is_boon_screen(texts: list[Text]) -> bool:
    """Major Boon card pick. A long description that happens to say 'boon' is not the banner."""
    return any("boon" in t.norm and len(t.norm) <= 32 for t in texts)


def card_blob(texts: list[Text], tag: Text, nxt: Text | None) -> str:
    """Every OCR line on a skill/boon card, name and description together."""
    top = tag.center[1] - 30
    bot = (nxt.center[1] - 20) if nxt is not None else tag.center[1] + 420
    rows = [t for t in texts if top <= t.center[1] < bot and t is not tag and re.search(r"[a-z]{2}", t.norm)]
    rows.sort(key=lambda t: (t.center[1], t.center[0]))
    return " ".join(t.text for t in rows)


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
                min_skill_price: int = config.SHOP_SKILL_FLOOR,
                left_shop_tokens: int | None = None) -> Decision:
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
        # The fork right after a shop still shows the same token count. Going back in
        # buys nothing the visit just refused.
        if left_shop_tokens is not None and tokens == left_shop_tokens:
            return take(statue, "just left a shop with the same token count")
        if tokens >= 300:
            return take(shop, "tokens >= 300")
        # Same "at least one skill is affordable" bar as Atlantis (cheapest skill is 48).
        if rolls_left is not None and rolls_left <= LATE_ROLLS and tokens >= min_skill_price:
            return take(shop, "rolls left <= 5 and a skill is affordable")
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
    """Treasure Miner, including a frame whose title OCR missed.

    The coin-flip fallback must never run here: there is no safe button until Leave,
    and Leave itself is not drawn until every pickaxe has been used.
    """
    if match_event(texts) == "treasure_miner":
        return True
    blob = " ".join(t.norm for t in texts)
    return ("remaining treasure" in blob or "dig up hidden" in blob or "treasure miner" in blob)


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


def _near(a: tuple[int, int], b: tuple[int, int], tol: int = 25) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _in_title_band(label: Text) -> bool:
    """Option titles sit above the icon. Lower text is the button itself (Path A, Take, Sign)."""
    y = label.center[1]
    lo, hi = config.EVENT_LABEL_Y
    return lo - 40 <= y <= hi + 40


def _title_anchor(label: Text, texts: list[Text]) -> Text:
    """Bottom line of a wrapped title ("Embrace" / "Darkness"). The icon hangs under that line."""
    anchor = label
    for t in texts:
        if t is label:
            continue
        if abs(t.center[0] - label.center[0]) > config.EVENT_COLUMN_X:
            continue
        dy = t.center[1] - anchor.center[1]
        if 0 < dy <= 90 and t.center[1] <= config.EVENT_LABEL_Y[1] + 30:
            anchor = t
    return anchor


def _caption_below(anchor: Text, texts: list[Text]) -> Text | None:
    """The line under the icon ("Walk Away", "Learn a Common Skill"), not the wrapped title."""
    floor = config.EVENT_LABEL_Y[1] + 40
    hits = [t for t in texts if t is not anchor and t.center[1] >= floor
            and 40 < t.center[1] - anchor.center[1] < 800
            and abs(t.center[0] - anchor.center[0]) <= config.EVENT_COLUMN_X]
    if not hits:
        return None
    return min(hits, key=lambda t: t.center[1])


def tap_candidates(label: Text, texts: list[Text]) -> list[tuple[int, int]]:
    """Places a choice can be tapped, best first.

    A two-option event draws the name, then the icon button, then a caption. Tapping the
    name does nothing. The button center is first and the caption is the backup. A control
    whose own words are the button (Path A, Take, Sign) is tapped on that text.
    """
    anchor = _title_anchor(label, texts)
    points: list[tuple[int, int]] = []
    if _in_title_band(label):
        points.append((anchor.center[0], anchor.center[1] + config.EVENT_ICON_BELOW_LABEL))
        caption = _caption_below(anchor, texts)
        if caption is not None:
            points.append(caption.center)
    else:
        below = [t for t in texts if 40 < t.center[1] - label.center[1] < 460
                 and abs(t.center[0] - label.center[0]) <= config.EVENT_COLUMN_X and t is not label]
        if below:
            nxt = min(below, key=lambda t: t.center[1])
            points.append((label.center[0], (label.center[1] + nxt.center[1]) // 2))
        points.append(label.center)
    out = []
    for p in points:
        if any(_near(p, q) for q in out) or tap_forbidden(p):
            continue
        out.append(p)
    return out


def choice_tap(label: Text, texts: list[Text]) -> tuple[int, int]:
    """The point that should be tapped for this choice. Never the title text of a two-option event."""
    found = tap_candidates(label, texts)
    return found[0] if found else label.center


def recovery_taps(texts: list[Text], failed: tuple[int, int]) -> list[tuple[int, int]]:
    """Other points in the same column after `failed` did nothing: the button, then its caption.

    The other option is not included. Switching choices is not a retry.
    """
    labels = [t for t in choice_labels(texts)
              if abs(t.center[0] - failed[0]) <= config.EVENT_COLUMN_X + 40]
    points: list[tuple[int, int]] = []
    for label in labels:
        for p in tap_candidates(label, texts):
            if _near(p, failed) or any(_near(p, q) for q in points) or tap_forbidden(p):
                continue
            points.append(p)
    return points


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
              skills: list[KnownSkill] | None = None, min_skill_price: int | None = None,
              rolls: tuple[int, int] | None = None,
              left_shop_tokens: int | None = None) -> tuple[int, int] | None:
    """Tap for a World 2 path fork or a known World 2 event. None if this frame is neither.

    Sets LAST to the decision (including a path that could not be read). Campfire and
    World 1 events return None so the existing handler keeps them. `rolls` is the last
    N/30 from the map when this frame hides the counter.
    """
    global LAST
    build = build or Build()
    hud = with_cached_rolls(read_hud(texts), rolls)
    price = config.SHOP_SKILL_FLOOR if min_skill_price is None else min_skill_price
    cards = path_cards(texts)
    if len(cards) >= 2:
        known = {"elysium", "ancient waterway", "molten core", "atlantis"}
        resolved = board if board in known else board_from_title(board)
        decision = decide_path(resolved, cards, hud.tokens, hud.rolls_left, price, left_shop_tokens)
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
    if event == "cursed_vendor":
        # The choice is "left" / "right". The buttons are both named Sign, so a lookup
        # by the choice name used to return nothing and the screen sat there.
        signs = _vendor_signs(texts)
        idx = {"left": 0, "right": 1}.get(decision.choice or "")
        if idx is None or idx >= len(signs):
            return None
        return choice_tap(signs[idx], texts)
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


def shop_header(texts: list[Text]) -> Text | None:
    """The wooden SHOP sign. A path card's "SHOP" icon is much lower and is not this."""
    mid = config.SCREEN_SIZE[0] // 2
    hits = [t for t in texts if t.norm.strip("!¡ ") in ("shop", "tienda")
            and t.center[1] < 520 and abs(t.center[0] - mid) < 320]
    return hits[0] if hits else None


def is_shop_screen(texts: list[Text]) -> bool:
    """World 2 shop: the SHOP header and/or the Reroll + Exit buttons.

    The greeting changes ("The hero befor…", "I have exactly what…") and an item line
    ("When HP <40%, ATK") can sit where an event title would. Neither of those is the shop.
    The black market is not this: its prices may be gems, and it is left without buying.
    """
    if find(texts, L.BLACK_MARKET):
        return False
    leave = find(texts, L.LEAVE, exact=True)
    reroll = find(texts, L.SHOP_REROLL)
    header = shop_header(texts)
    if leave and reroll:
        return True
    return bool(header and (leave or reroll))


_STAT_TOAST = re.compile(r"^max hp\s*[+\-]\s*\d+\s*%$")


def known_screen(texts: list[Text]) -> str | None:
    """A screen the 2.0.2 run saved as an unknown event. None when it really is unknown.

    "claim" is tapped through (You Received / You Forgot / Lucky Treasure).
    "victory" is the existing end screen (Continue / x2 Rewards), not a new choice.
    "battle" waits. "dice" is the dice duel, including its win popup's siblings
    that the duel handler already plays.
    """
    lines = [t.norm.strip("!¡.: ") for t in texts]

    def short(phrases: tuple[str, ...], limit: int = 48) -> bool:
        return any(any(p in n for p in phrases) for n in lines if len(n) <= limit)

    if any(re.search(r"(?:round|ronda)\s*:?\s*\d+\s*/\s*\d+", n) or re.search(r"\bwave\s*\d+\s*/\s*\d+", n)
           for n in lines if len(n) <= 40):
        return "battle"
    # A dice win popup also says "You Received" / "Tap anywhere to claim": that tap wins.
    if short(("you received", "you forgot", "lucky treasure", "ucky treasure", "tap anywhere to claim")):
        return "claim"
    if short(("dice battle", "current reward", "winning streak", "gambler")):
        return "dice"
    if short(("victory", "victoria", "you survived", "longest journey")):
        return "victory"
    if short(("tap anywhere to continue", "tap to continue", "tap to claim")):
        return "claim"
    return None


def transient_kind(texts: list[Text]) -> str | None:
    """A map toast, elite banner, or chest popup. Not an event and not worth saving.

    "chest" is tapped through ("Tap anywhere to open"). "toast" and "banner" just wait.
    """
    for t in texts:
        n = t.norm.strip("!¡. ")
        if _STAT_TOAST.match(n):
            return "toast"
        if "you found a chest" in n or "encontraste un cofre" in n:
            return "chest"
        if n in ("elite enemy", "incoming"):
            return "banner"
    return None


def looks_like_event(texts: list[Text]) -> bool:
    """A title-like line plus two choices in the bottom half. Not a fight, skill pick, path, shop or the board."""
    if ordinary_level_screen(texts) or is_shop_screen(texts) or transient_kind(texts):
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


_COIN_BLOCK = (
    "gem", "diamond", "gold", "buy", "purchase", "spend",
    "give up", "quit", "abandon", "forfeit", "surrender",
    "settings", "home", "exit run", "end run",
)
# The paid x4 speed badge. A fallback tap here toggles VIP speed.
_VIP_X4 = (111, 2307)


def _near_vip(point: tuple[int, int]) -> bool:
    return abs(point[0] - _VIP_X4[0]) <= 90 and abs(point[1] - _VIP_X4[1]) <= 90


def blocked_choice(text: str, point: tuple[int, int]) -> bool:
    """Gems, gold, diamonds, purchases, quitting the run, and the VIP x4 badge.

    Word boundaries, so a blessing that says "golden" is not treated as a gold price.
    """
    n = normalize(text)
    if n.isdigit():  # a bare "60" is the gem price, not a choice
        return True
    if any(re.search(r"\b" + re.escape(w) + r"\b", n) for w in _COIN_BLOCK):
        return True
    return tap_forbidden(point) or _near_vip(point)


def dismiss_point(texts: list[Text]) -> tuple[int, int] | None:
    """'Tap anywhere to claim/continue' closes the popup. The center is not a price."""
    phrases = ("tap anywhere to claim", "tap anywhere to continue", "tap to continue", "tap to claim",
               "tap anywhere")
    if any(any(p in t.norm for p in phrases) for t in texts):
        return config.SCREEN_SIZE[0] // 2, config.SCREEN_SIZE[1] // 2
    return None


def coin_flip_applies(texts: list[Text]) -> bool:
    """An unknown choice screen. Never a fight, a shop, the miner, or a known popup."""
    if is_miner(texts) or is_shop_screen(texts) or ordinary_level_screen(texts):
        return False
    if known_screen(texts) or transient_kind(texts):
        return False
    title = event_title(texts)
    if title and is_known_title(title):
        return False
    return looks_like_event(texts)


def coin_flip_labels(texts: list[Text]) -> list[tuple[str, tuple[int, int]]]:
    """Safe buttons on an unknown choice screen, in reading order. Blocklisted ones are gone."""
    found = []
    for t in choice_labels(texts):
        point = choice_tap(t, texts)
        blob = t.text + " " + _column_blob(t, texts)
        if blocked_choice(blob, point) or blocked_choice(blob, t.center):
            continue
        if any(_near(point, p) for _label, p in found):
            continue
        found.append((t.text, point))
    return found


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


def _vendor_signs(texts: list[Text]) -> list[Text]:
    return sorted((t for t in choice_labels(texts) if t.norm == "sign" or t.norm.startswith("sign ")),
                  key=lambda t: t.center[0])[:2]


def vendor_bodies(texts: list[Text]) -> tuple[str, str] | None:
    """Blessing and curse text of the left and right Sign cards.

    The lines are above each Sign button. Text under the button is the page footer, not the offer.
    """
    signs = _vendor_signs(texts)
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


# Measured on a 1440x2560 Treasure Miner screen. Used only when the tiles themselves
# cannot be found. Column step ~149, row step ~145.
FALLBACK_MINER_COLS = (285, 434, 583, 732, 881, 1030, 1179)
FALLBACK_MINER_ROWS = (1107, 1252, 1397, 1542, 1687, 1832, 1979)


def fallback_miner_centers() -> list[list[tuple[int, int]]]:
    """Tile centers in reference coordinates, one unopened cell at a time until Leave."""
    return [[(FALLBACK_MINER_COLS[c], FALLBACK_MINER_ROWS[r]) for c in range(MINER_SIZE)]
            for r in range(MINER_SIZE)]


def blank_miner():
    return [[UNK for _ in range(MINER_SIZE)] for _ in range(MINER_SIZE)]


def _classify_cell(b: float, g: float, r: float) -> int:
    """Single-pixel fallback. Dirt tiles are saturated, so this is only a hint."""
    mx, mn = max(b, g, r), min(b, g, r)
    if mx < 75:
        return DUG
    if mx > 0 and (mx - mn) / mx > 0.35 and mx > 90:
        return GEM
    return UNK


def _patch_mean(img: np.ndarray, point: tuple[int, int]) -> tuple[float, float, float]:
    x, y = point
    h, w = img.shape[:2]
    x0, x1 = max(0, x - 6), min(w, x + 6)
    y0, y1 = max(0, y - 6), min(h, y + 6)
    patch = img[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0, 0.0, 0.0
    mean = patch.astype(float).mean(axis=(0, 1))
    return float(mean[0]), float(mean[1]), float(mean[2])


def _classify_against_median(sample: tuple[float, float, float],
                             median: tuple[float, float, float]) -> int:
    """Undug dirt matches the median tile. A dark hole is dug. Anything else vivid is a gem.

    The old cutoff called every brown tile a gem, because the dirt is saturated. That
    made the bot refuse to tap the real grid.
    """
    b, g, r = sample
    mb, mg, mr = median
    mx = max(b, g, r)
    dist = abs(b - mb) + abs(g - mg) + abs(r - mr)
    dirt = r > g > b and (r - b) > 40
    if mx < 75:
        return DUG
    if dirt and dist < 180:
        return UNK
    if dist > 90 and not dirt:
        return GEM
    return UNK


def cell_signature(img: np.ndarray, point: tuple[int, int]) -> tuple[int, int, int]:
    b, g, r = _patch_mean(img, point)
    return int(b), int(g), int(r)


def tile_changed(before: tuple[int, int, int], after: tuple[int, int, int], tol: int = 45) -> bool:
    """A real dig shifts the patch. Sparkle and the idle character do not."""
    return sum(abs(a - b) for a, b in zip(before, after)) > tol


def _remaining_anchor(texts: list[Text] | None) -> int | None:
    if not texts:
        return None
    hits = [t.center[1] for t in texts if "remaining treasure" in t.norm]
    return min(hits) if hits else None


def read_miner_grid(img: np.ndarray, texts: list[Text] | None = None):
    """7x7 cell classes and centers, from the tile squares in the panel.

    The search stays below the miner and the speech bubble. Those used to win the
    contour cluster, so a dig was tapped at y≈530 (the bubble) and the pickaxe was
    counted anyway. None when a regular 7 by 7 is not in the panel; the caller then
    uses the measured fallback grid and keeps digging.
    """
    if img is None or img.size == 0 or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    anchor = _remaining_anchor(texts)
    if anchor is not None:
        top = max(0, int(anchor - 0.46 * h))
        bot = min(h, int(anchor - 0.012 * h))
    else:
        # Panel on a 1440x2560 frame is about y 1000-2050. The character is above that.
        top, bot = int(h * 0.40), int(h * 0.84)
    left, right = int(w * 0.08), int(w * 0.94)
    if bot - top < 40 or right - left < 40:
        return None
    roi = img[top:bot, left:right]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    contours, _hier = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    side = 0.085 * w
    lo, hi = (0.45 * side) ** 2, (1.35 * side) ** 2
    boxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 8 or bh < 8:
            continue
        if not 0.75 <= bw / max(bh, 1) <= 1.35:
            continue
        if not lo <= bw * bh <= hi:
            continue
        boxes.append((x + bw / 2, y + bh / 2, bw, bh))
    if len(boxes) < MINER_SIZE * 4:
        return None
    xs = _cluster([b[0] for b in boxes], MINER_SIZE)
    ys = _cluster([b[1] for b in boxes], MINER_SIZE)
    if xs is None or ys is None:
        return None
    if (ys[-1] - ys[0]) < 0.20 * h:
        return None  # a flat cluster is the speech bubble, not the grid
    centers = []
    samples = []
    for row in range(MINER_SIZE):
        crow = []
        for col in range(MINER_SIZE):
            px = min(w - 1, max(0, int(left + xs[col])))
            py = min(h - 1, max(0, int(top + ys[row])))
            crow.append((px, py))
            samples.append(_patch_mean(img, (px, py)))
        centers.append(crow)
    median = tuple(float(v) for v in np.median(np.array(samples), axis=0))
    board = []
    for row in range(MINER_SIZE):
        board.append([_classify_against_median(samples[row * MINER_SIZE + col], median)
                      for col in range(MINER_SIZE)])
    return board, centers


def count_pickaxes(img: np.ndarray, centers) -> int | None:
    """How many pickaxe icons sit in the row just above the grid. None when the row is unreadable.

    A head is a light, low-saturation blob. The handle beside it is thinner and is not counted.
    """
    if img is None or not centers or img.ndim != 3:
        return None
    h, w = img.shape[:2]
    first_y = centers[0][0][1]
    y = int(first_y - 0.065 * h)
    if y < 12 or y >= h - 12:
        return None
    x0 = max(0, centers[0][0][0] - int(0.04 * w))
    x1 = min(w, centers[0][-1][0] + int(0.04 * w))
    y0, y1 = max(0, y - 14), min(h, y + 14)
    if x1 - x0 < 20:
        return None
    roi = img[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 90) & (hsv[:, :, 2] > 85) & (hsv[:, :, 2] < 220)).astype(np.uint8)
    _n, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    heads = 0
    min_w, max_w = 0.02 * w, 0.07 * w
    min_area = 0.00015 * w * h
    for i in range(1, len(stats)):
        _x, _y, bw, bh, area = stats[i]
        if min_w <= bw <= max_w and bh >= 0.005 * h and area >= min_area:
            heads += 1
    if 1 <= heads <= MINER_PICKAXES:
        return heads
    if heads == 0 and float(roi.mean()) < 110:
        return 0
    return None


def next_unopened(board, skips: set[tuple[int, int]] | None = None) -> tuple[int, int] | None:
    """Next tile to dig. Cells that just failed to change are skipped, not given up on.

    When every unopened cell was a miss, the hunt starts over. Leaving the screen is
    not an option until Leave is actually drawn.
    """
    skips = skips or set()
    masked = [row[:] for row in board]
    for r, c in skips:
        if 0 <= r < len(masked) and 0 <= c < len(masked[0]) and masked[r][c] == UNK:
            masked[r][c] = DUG
    nxt = next_miner_tap(masked, 1)
    if nxt is None:
        return next_miner_tap(board, 1)
    return nxt


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
