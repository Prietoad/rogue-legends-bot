package com.diego.roguebot_phone.bot

/** Port of roguebot/build.py: build preferences and the pure skill choice rules. */
data class Build(
    val nature: String = Skills.PHYSICAL,
    val order: List<String> = Skills.DAMAGE_TYPES,
    val supportEvery: Int? = null,
)

class BuildState {
    var damageSinceSupport = 0
    val taken = ArrayList<String>()

    fun take(skill: Skill) {
        taken.add(skill.name)
        damageSinceSupport = if (skill.role == Skills.SUPPORT) 0 else damageSinceSupport + 1
    }

    fun wantsSupport(build: Build): Boolean = build.supportEvery != null && damageSinceSupport >= build.supportEvery
}

object Choice {
    private fun rarity(s: Skill): Int = Skills.RARITY_NAMES.indexOf(s.rarity).let { if (it < 0) Skills.RARITY_NAMES.size else it }
    private fun typeRank(s: Skill, b: Build): Int = b.order.indexOf(s.damageType).let { if (it < 0 || s.damageType == null) b.order.size else it }

    /** Indices of the wanted skills, best first (empty if none is wanted). */
    fun ranked(skills: List<Skill>, build: Build, state: BuildState): List<Int> {
        val damage = skills.indices.filter { skills[it].role == Skills.DAMAGE && skills[it].nature == build.nature }
            .sortedWith(compareBy({ typeRank(skills[it], build) }, { rarity(skills[it]) }, { it }))
        if (!state.wantsSupport(build)) return damage
        val support = skills.indices.filter { skills[it].role == Skills.SUPPORT }.sortedWith(compareBy({ rarity(skills[it]) }, { it }))
        return support + damage
    }

    /** Rarest first, then top to bottom. */
    fun fallback(skills: List<Skill>): List<Int> = skills.indices.sortedWith(compareBy({ rarity(skills[it]) }, { it }))

    /** Index of the card to take, or null to use the reroll. */
    fun choose(skills: List<Skill>, build: Build, state: BuildState, canReroll: Boolean): Int? {
        val wanted = ranked(skills, build, state)
        if (wanted.isNotEmpty()) return wanted[0]
        if (canReroll) return null
        return fallback(skills)[0]
    }

    /** Buying order for the shop's skills, or null to use the (free) reroll first. */
    fun shopOrder(skills: List<Skill>, build: Build, state: BuildState, canReroll: Boolean): List<Int>? {
        val wanted = ranked(skills, build, state)
        if (wanted.isEmpty() && canReroll) return null
        return wanted + fallback(skills).filter { it !in wanted }
    }
}
