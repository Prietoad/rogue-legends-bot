"""Build preferences (set in the UI) and the skill choice rules. Pure: no device, no OCR.

Rules (from the user):
- Wanted skills are damage skills of the preferred nature (physical/magic), best damage type first
  (the user's order; untyped skills after the listed types), then rarer, then the top card.
  A named type (shuriken, venom, ...) beats a higher rarity and the top card.
- With "support every N": after N damage skills, a support skill is wanted instead. If none is
  offered, take the damage skill and take the next support skill that shows up.
- A level-up with no listed damage type (only untyped or off-nature cards): use the reroll if there
  is one. Still nothing: untyped damage of the right nature, else the rarest card, top first.
- Shop: buy only the wanted skills, in that order, while the coins allow. Do not spend coins on
  off-build cards. A free reroll is used when no listed damage type is offered (not when a weaker
  same-nature card is merely cheaper). Dojo and raid still fill remaining picks from the other cards.
"""

from dataclasses import dataclass, field

from roguebot.skills import DAMAGE, DAMAGE_TYPES, MAGIC, PHYSICAL, RARITY_NAMES, SUPPORT, Skill, skill_key
from roguebot.vision import normalize

# Farm builds never prefer these. Deadly Stars is only refused on the shuriken preset.
FARM_AVOID = ("glass cannon", "darkside", "dark side")


@dataclass(frozen=True)
class Build:
    nature: str = PHYSICAL                          # PHYSICAL / MAGIC
    order: tuple[str, ...] = DAMAGE_TYPES           # damage types, most wanted first
    support_every: int | None = None                # take a support skill after this many damage skills
    avoid: tuple[str, ...] = FARM_AVOID             # normalized name fragments never preferred
    strict: bool = False                            # only the damage types listed in order (fire-only)


# Named presets. The order is a soft synergy bias (no gear OCR). Shop stays wanted-only.
PRESETS: dict[str, Build] = {
    "shuriken": Build(PHYSICAL, ("shuriken", "bleed", "venom"),
                      avoid=FARM_AVOID + ("deadly stars", "deadly star")),
    "fire": Build(MAGIC, ("fire",), strict=True),
    "poison": Build(PHYSICAL, ("venom", "bleed", "shuriken")),
    "ice": Build(MAGIC, ("ice", "lightning", "fire")),
    "lightning": Build(MAGIC, ("lightning", "fire", "ice")),
    "sustain": Build(PHYSICAL, ("bleed", "venom", "shuriken"), support_every=3),
}


@dataclass
class BuildState:
    """What the current level run has taken so far."""
    damage_since_support: int = 0
    taken: list[str] = field(default_factory=list)

    def take(self, skill: Skill) -> None:
        self.taken.append(skill.name)
        self.damage_since_support = 0 if skill.role == SUPPORT else self.damage_since_support + 1

    def wants_support(self, build: Build) -> bool:
        return build.support_every is not None and self.damage_since_support >= build.support_every


def _rarity(skill: Skill) -> int:
    """0 = best (mythic)."""
    return RARITY_NAMES.index(skill.rarity) if skill.rarity in RARITY_NAMES else len(RARITY_NAMES)


def _type_rank(skill: Skill, build: Build) -> int:
    return build.order.index(skill.damage_type) if skill.damage_type in build.order else len(build.order)


def _avoided(skill: Skill, build: Build) -> bool:
    name = normalize(skill.name)
    return any(piece in name for piece in build.avoid)


def _upgraded(skill: Skill, state: BuildState) -> int:
    """0 when this run already took the skill (an upgrade beats a new card of the same type)."""
    key = skill_key(skill.name)
    if not key:
        return 1
    return 0 if any(skill_key(taken) == key for taken in state.taken) else 1


def _damage_ok(skill: Skill, build: Build) -> bool:
    if skill.role != DAMAGE or skill.nature != build.nature or _avoided(skill, build):
        return False
    # A strict preset (fire only) does not want other types, including untyped cards.
    return not build.strict or skill.damage_type in build.order


def ranked(skills: list[Skill], build: Build, state: BuildState) -> list[int]:
    """Indices of the wanted skills, best first (empty if none is wanted).

    Type order first, then a skill this run already took (upgrade it), then rarity.
    """
    damage = sorted((i for i, s in enumerate(skills) if _damage_ok(s, build)),
                    key=lambda i: (_type_rank(skills[i], build), _upgraded(skills[i], state), _rarity(skills[i]), i))
    if not state.wants_support(build):
        return damage
    support = sorted((i for i, s in enumerate(skills) if s.role == SUPPORT and not _avoided(s, build)),
                     key=lambda i: (_upgraded(skills[i], state), _rarity(skills[i]), i))
    return support + damage  # no support offered: the damage skill, and keep wanting support


def fallback(skills: list[Skill], build: Build | None = None) -> list[int]:
    """Rarest first, then top to bottom. Avoided names are left out while anything else is offered."""
    order = sorted(range(len(skills)), key=lambda i: (_rarity(skills[i]), i))
    if build is None:
        return order
    kept = [i for i in order if not _avoided(skills[i], build)]
    return kept or order


def _preferred(skills: list[Skill], build: Build, state: BuildState) -> list[int]:
    """Wanted skills that name a damage type, or a support skill when one is due.

    Untyped damage is left out: it is the top-of-screen physical fallback, not the build.
    """
    return [i for i in ranked(skills, build, state) if skills[i].role == SUPPORT or skills[i].damage_type]


def offer_is_unfavorable(skills: list[Skill], build: Build, state: BuildState, picks: int = 1) -> bool:
    """True when the offer has fewer preferred skills than this step must take.

    Preferred means a named damage type the build wants, or a support skill when one is due.
    Untyped and off-build cards do not count, so a Dojo / raid / dive pick rerolls instead of
    filling the rest of the offer with them. `picks` is how many cards this step still has to take.
    """
    return len(_preferred(skills, build, state)) < max(1, picks)


def choose(skills: list[Skill], build: Build, state: BuildState, can_reroll: bool) -> int | None:
    """Index of the card to take, or None to use the reroll."""
    preferred = _preferred(skills, build, state)
    if preferred:
        return preferred[0]
    if can_reroll:
        return None
    wanted = ranked(skills, build, state)
    if wanted:  # untyped damage of the right nature, and no reroll left
        return wanted[0]
    return fallback(skills, build)[0]


def shop_order(skills: list[Skill], build: Build, state: BuildState, can_reroll: bool,
               fill: bool = True) -> list[int] | None:
    """Buying order for the shop's skills, or None to use the (free) reroll first.

    `fill` (dojo and raid, which must pick several) keeps the other cards after the wanted ones.
    The level shop leaves them out, so leftover coins are not spent off-build.
    """
    wanted = ranked(skills, build, state)
    if not wanted and can_reroll:
        return None
    if fill:
        return wanted + [i for i in fallback(skills, build) if i not in wanted]
    preferred = _preferred(skills, build, state)
    if not preferred and can_reroll:
        return None
    return preferred or wanted
