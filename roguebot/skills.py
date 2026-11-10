"""Skill database (data/skills.json): every skill seen in a level, with its tags.

New skills are added automatically when they show up (skill pick or shop), with tags inferred from
the name and description. The inference is a best guess: edit the JSON to fix a tag and set
"auto" to false (entries with auto=false are never re-inferred).
"""

import difflib
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from roguebot.settings import DATA_DIR
from roguebot.vision import normalize

log = logging.getLogger(__name__)

CATALOG_PATH = DATA_DIR / "skills.json"

DAMAGE_TYPES = ("ice", "lightning", "fire", "shuriken", "venom", "bleed")
MAGIC_TYPES = ("ice", "lightning", "fire")
PHYSICAL, MAGIC = "physical", "magic"
DAMAGE, SUPPORT = "damage", "support"
RARITY_NAMES = ("mythic", "legendary", "epic", "rare", "common", "useless")  # same order as labels.RARITIES

# Keyword stems on normalized text (lowercase, no accents), Spanish and English. A stem matches at
# the start of a word, so "ice" does not match "twice" or "price".
_TYPE_WORDS = {
    "ice": ("ice", "icicle", "chill", "frost", "freez", "frozen", "snow", "hielo", "carambano", "escalofrio",
            "frio", "escarcha", "congel", "nieve"),
    "lightning": ("lightning", "bolt", "thunder", "shock", "electr", "spark", "rayo", "relampago", "trueno",
                  "descarga", "chispa"),
    "fire": ("fire", "burn", "flame", "blaze", "ignit", "inferno", "fuego", "quema", "llama", "ardiente",
             "incendi", "ascua"),
    "shuriken": ("shuriken",),
    "venom": ("poison", "venom", "toxic", "veneno", "venen", "toxic"),
    "bleed": ("bleed", "sangr", "wound", "herida"),  # the game's bleed effect is called "Wound"
}
_DAMAGE_WORDS = ("atk", "atq", "damage", "dmg", "dano", "attack", "ataque", "crit", "execut", "ejecut", "counter",
                 "contraataque", "strike", "golpe")
_SUPPORT_WORDS = ("shield", "escudo", "dodge", "evasion", "evade", "heal", "cura", "recover", "recupera", "restor",
                  "restaura", "regenera", "def$", "max hp", "hp max", "lifesteal", "robo de vida", "revive", "revivir")


def _regex(stems) -> re.Pattern:
    """Stems match at a word start; a trailing "$" makes it a whole word ("def$": DEF, not "Definitiva")."""
    return re.compile(r"\b(" + "|".join(re.escape(s[:-1]) + r"\b" if s.endswith("$") else re.escape(s)
                                       for s in stems) + ")")


_TYPE_RE = {t: _regex(words) for t, words in _TYPE_WORDS.items()}
_NATURE_RE = {MAGIC: _regex(("magic", "magia")), PHYSICAL: _regex(("physical", "fisic"))}
_DAMAGE_RE = _regex(_DAMAGE_WORDS)
_SUPPORT_RE = _regex(_SUPPORT_WORDS)


def name_is_support(name: str) -> bool:
    """The skill name itself is a support (Heal, Shield, Dodge). A damage word in the same name does not win."""
    return _SUPPORT_RE.search(normalize(name)) is not None


def skill_key(name: str) -> str:
    """Letters only, so OCR variants ("Ultimate-Bolt", "Ultimate Bolt", "CounterMastery") share a key."""
    return re.sub(r"[^a-z]", "", normalize(name))


# OCR fragments from half-faded cards. Dropped on load and never auto-added.
# Endless Fury, Last Stand and Feral Lethality are not here: a clean read should still be saved.
JUNK_KEYS = {
    "endlescfury", "weap", "thality", "lastst", "erallethality", "iltimat", "iltimnte",
    "fuma", "riken", "exp", "expexd", "expexp", "expxext", "exf", "exo", "ha", "hh",
    "rit", "ritic", "ritie", "mitie", "wear", "wemr", "woun", "outbre", "outbro",
    "uthreak", "vampi", "xp", "shop", "ken",
}


def _desc_words(description: str) -> list[str]:
    return re.findall(r"[a-z]{2,}", normalize(description or ""))


def skill_name_rejected(name: str, description: str = "") -> str | None:
    """Why this must not be written into the catalog, or None when it may be saved.

    Short names, all-caps fragments, and "Lv"/"SALE" glued onto a name are OCR leftovers.
    A description under four words is the same kind of partial read. A faded card is
    rejected so a later clean frame can still be captured.
    """
    raw = (name or "").strip()
    letters = re.sub(r"[^A-Za-z]", "", raw)
    if len(letters) < 4:
        return "short"
    key = skill_key(raw)
    if key in JUNK_KEYS:
        return "junk"
    if re.search(r"lv\.?\s*\d|\bsale\b", raw, re.I):
        return "level-or-sale"
    if raw.isupper() and " " not in raw and len(letters) <= 8:
        return "caps"
    if description and len(_desc_words(description)) < 4:
        return "short-description"
    return None


def junk_on_load(name: str) -> bool:
    """A saved entry to drop. Description length is not used: reviewed skills can be short."""
    reason = skill_name_rejected(name, "")
    return reason in ("short", "junk", "level-or-sale", "caps")


def infer_tags(name: str, description: str) -> tuple[str | None, str, str]:
    """(damage_type, nature, role) guessed from the text.

    damage_type: the type whose keyword appears first (name first), or None.
    nature: magic for ice/lightning/fire; untyped skills follow whichever of "magical"/"physical" they
    mention first ("Wizard: Magical DMG ↑, Physical DMG ↓↓" is magic); physical otherwise.
    role: damage if it has a damage type; else support if its name has a support word ("Lifesteal",
    "Enraged Dodge"); else whichever of a damage/support word comes first; else damage.
    """
    text = normalize(f"{name} . {description}")
    found = [(m.start(), t) for t, rx in _TYPE_RE.items() if (m := rx.search(text))]
    damage_type = min(found)[1] if found else None
    nature = MAGIC if damage_type in MAGIC_TYPES else PHYSICAL
    if damage_type is None:
        mentions = [(m.start(), n) for n, rx in _NATURE_RE.items() if (m := rx.search(text))]
        nature = min(mentions)[1] if mentions else PHYSICAL
    if damage_type:
        role = DAMAGE
    elif _SUPPORT_RE.search(normalize(name)):
        role = SUPPORT
    else:  # both kinds of words: the first one wins (the boosted stat is listed first: "HP Máx. ↑↑↑↑, ATQ ↓↓↓")
        found = [(m.start(), r) for r, rx in ((DAMAGE, _DAMAGE_RE), (SUPPORT, _SUPPORT_RE)) if (m := rx.search(text))]
        role = min(found)[1] if found else DAMAGE
    return damage_type, nature, role


@dataclass
class Skill:
    name: str
    lang: str | None
    rarity: str                  # see RARITY_NAMES
    damage_type: str | None      # see DAMAGE_TYPES
    nature: str                  # PHYSICAL / MAGIC
    role: str                    # DAMAGE / SUPPORT
    description: str = ""
    auto: bool = True            # tags inferred by the bot (set false after reviewing them)


class Catalog:
    def __init__(self, path: Path = CATALOG_PATH):
        self.path = path
        self.skills: dict[str, Skill] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.skills = {k: Skill(**v) for k, v in data.items() if not junk_on_load(v.get("name", k))}

    def contains(self, name: str) -> bool:
        """True when this name is already in the database, allowing for a small OCR slip."""
        key = skill_key(name)
        if not key:
            return False
        if key in self.skills:
            return True
        return bool(difflib.get_close_matches(key, list(self.skills), n=1, cutoff=0.8))

    def lookup(self, name: str, description: str, rarity: str, lang: str | None) -> Skill:
        """The known skill with this name (tolerating small OCR differences), or a new one, saved.

        A close name (>= 0.8) is the same skill. A fragment is returned for this decision
        and not written, so a faded card does not pollute the file or block a later capture.
        """
        key = skill_key(name)
        if not key:
            damage_type, nature, role = infer_tags(name, description)
            return Skill(name, lang, rarity, damage_type, nature, role, description)
        if key not in self.skills:
            close = difflib.get_close_matches(key, list(self.skills), n=1, cutoff=0.8)
            if close:
                return self.skills[close[0]]
            damage_type, nature, role = infer_tags(name, description)
            skill = Skill(name, lang, rarity, damage_type, nature, role, description)
            if skill_name_rejected(name, description):
                return skill
            self.skills[key] = skill
            log.info("New skill: %s (%s, %s, %s, %s)", name, rarity, damage_type or "-", nature, role)
            self.save()
        return self.skills[key]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in sorted(self.skills.items())}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
