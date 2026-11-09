package com.diego.roguebot_phone.bot

/** Port of roguebot/build.py: build preferences and the pure skill choice rules. */
val FARM_AVOID = listOf("glass cannon", "darkside", "dark side")

data class Build(
    val nature: String = Skills.PHYSICAL,
    val order: List<String> = Skills.DAMAGE_TYPES,
    val supportEvery: Int? = null,
    val avoid: List<String> = FARM_AVOID,
    val strict: Boolean = false,
)

/** Named presets. The order is a soft synergy bias. Shop stays wanted-only. */
val PRESETS = mapOf(
    "shuriken" to Build(Skills.PHYSICAL, listOf("shuriken", "bleed", "venom"),
        avoid = FARM_AVOID + listOf("deadly stars", "deadly star")),
    "fire" to Build(Skills.MAGIC, listOf("fire"), strict = true),
    "poison" to Build(Skills.PHYSICAL, listOf("venom", "bleed", "shuriken")),
    "ice" to Build(Skills.MAGIC, listOf("ice", "lightning", "fire")),
    "lightning" to Build(Skills.MAGIC, listOf("lightning", "fire", "ice")),
    "sustain" to Build(Skills.PHYSICAL, listOf("bleed", "venom", "shuriken"), supportEvery = 3),
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
    private fun avoided(s: Skill, b: Build): Boolean {
        val name = normalize(s.name)
        return b.avoid.any { it in name }
    }
    private fun upgraded(s: Skill, state: BuildState): Int {
        val key = Skills.skillKey(s.name)
        if (key.isEmpty()) return 1
        return if (state.taken.any { Skills.skillKey(it) == key }) 0 else 1
    }
    private fun damageOk(s: Skill, b: Build): Boolean {
        if (s.role != Skills.DAMAGE || s.nature != b.nature || avoided(s, b)) return false
        return !b.strict || s.damageType in b.order
    }

    /** Indices of the wanted skills, best first. Type order, then an upgrade of a skill already taken, then rarity. */
    fun ranked(skills: List<Skill>, build: Build, state: BuildState): List<Int> {
        val damage = skills.indices.filter { damageOk(skills[it], build) }
            .sortedWith(compareBy({ typeRank(skills[it], build) }, { upgraded(skills[it], state) }, { rarity(skills[it]) }, { it }))
        if (!state.wantsSupport(build)) return damage
        val support = skills.indices.filter { skills[it].role == Skills.SUPPORT && !avoided(skills[it], build) }
            .sortedWith(compareBy({ upgraded(skills[it], state) }, { rarity(skills[it]) }, { it }))
        return support + damage
    }

    /** Rarest first, then top to bottom. Avoided names are left out while anything else is offered. */
    fun fallback(skills: List<Skill>, build: Build? = null): List<Int> {
        val order = skills.indices.sortedWith(compareBy({ rarity(skills[it]) }, { it }))
        if (build == null) return order
        val kept = order.filter { !avoided(skills[it], build) }
        return kept.ifEmpty { order }
    }

    /** Wanted skills that name a damage type, or a support skill when one is due. Untyped damage is left out. */
    private fun preferred(skills: List<Skill>, build: Build, state: BuildState): List<Int> =
        ranked(skills, build, state).filter { skills[it].role == Skills.SUPPORT || skills[it].damageType != null }

    /** Fewer preferred skills than this step must take: reroll instead of filling with off-build cards. */
    fun offerIsUnfavorable(skills: List<Skill>, build: Build, state: BuildState, picks: Int = 1): Boolean =
        preferred(skills, build, state).size < maxOf(1, picks)

    /** Index of the card to take, or null to use the reroll. */
    fun choose(skills: List<Skill>, build: Build, state: BuildState, canReroll: Boolean): Int? {
        val pref = preferred(skills, build, state)
        if (pref.isNotEmpty()) return pref[0]
        if (canReroll) return null
        val wanted = ranked(skills, build, state)
        if (wanted.isNotEmpty()) return wanted[0]  // untyped damage of the right nature, no reroll left
        return fallback(skills, build)[0]
    }

    /** Buying order, or null to use the (free) reroll first. `fill` keeps off-build cards (dojo/raid). */
    fun shopOrder(skills: List<Skill>, build: Build, state: BuildState, canReroll: Boolean, fill: Boolean = true): List<Int>? {
        val wanted = ranked(skills, build, state)
        if (wanted.isEmpty() && canReroll) return null
        if (fill) return wanted + fallback(skills, build).filter { it !in wanted }
        val pref = preferred(skills, build, state)
        if (pref.isEmpty() && canReroll) return null
        return pref.ifEmpty { wanted }
    }
}
