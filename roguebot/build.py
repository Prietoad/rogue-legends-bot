"""Build preferences (set in the UI) and the skill choice rules. Pure: no device, no OCR.

Rules (from the user):
- Wanted skills are damage skills of the preferred nature (physical/magic), best damage type first
  (the user's order; untyped physical skills after the listed types), then rarer, then the top card.
- With "support every N": after N damage skills, a support skill is wanted instead. If none is
  offered, take the damage skill and take the next support skill that shows up.
- Nothing wanted on offer: use the reroll if there is one. Still nothing: the rarest card, top first.
- Shop: the same ranking (reroll only while free), then buy in that order whatever the coins allow.
"""

from dataclasses import dataclass, field

from roguebot.skills import DAMAGE, DAMAGE_TYPES, PHYSICAL, RARITY_NAMES, SUPPORT, Skill


@dataclass(frozen=True)
class Build:
    nature: str = PHYSICAL                          # PHYSICAL / MAGIC
    order: tuple[str, ...] = DAMAGE_TYPES           # damage types, most wanted first
    support_every: int | None = None                # take a support skill after this many damage skills


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


def ranked(skills: list[Skill], build: Build, state: BuildState) -> list[int]:
    """Indices of the wanted skills, best first (empty if none is wanted)."""
    damage = sorted((i for i, s in enumerate(skills) if s.role == DAMAGE and s.nature == build.nature),
                    key=lambda i: (_type_rank(skills[i], build), _rarity(skills[i]), i))
    if not state.wants_support(build):
        return damage
    support = sorted((i for i, s in enumerate(skills) if s.role == SUPPORT), key=lambda i: (_rarity(skills[i]), i))
    return support + damage  # no support offered: the damage skill, and keep wanting support


def fallback(skills: list[Skill]) -> list[int]:
    """Rarest first, then top to bottom."""
    return sorted(range(len(skills)), key=lambda i: (_rarity(skills[i]), i))


def choose(skills: list[Skill], build: Build, state: BuildState, can_reroll: bool) -> int | None:
    """Index of the card to take, or None to use the reroll."""
    wanted = ranked(skills, build, state)
    if wanted:
        return wanted[0]
    if can_reroll:
        return None
    return fallback(skills)[0]


def shop_order(skills: list[Skill], build: Build, state: BuildState, can_reroll: bool) -> list[int] | None:
    """Buying order for the shop's skills, or None to use the (free) reroll first."""
    wanted = ranked(skills, build, state)
    if not wanted and can_reroll:
        return None
    return wanted + [i for i in fallback(skills) if i not in wanted]
