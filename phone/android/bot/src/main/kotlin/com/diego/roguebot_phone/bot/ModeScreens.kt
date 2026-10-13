package com.diego.roguebot_phone.bot

import kotlin.math.abs

/** Port of roguebot/mode_screens.py: recognition for the full routine screens. Pure: no input. */
object ModeScreens {
    private val POWER_RE = Regex("^(\\d+(?:[.,]\\d+)?)\\s*([kmb]?)$")
    private val RATIO_RE = Regex("^(\\d+)\\s*/\\s*(\\d+)$")
    private val LEARN_RE = Regex("\\((\\d+)\\s*/\\s*(\\d+)\\)")
    private val TRAILING_NUMBER_RE = Regex("(\\d+)\\s*$")
    private val SCALE = mapOf("" to 1L, "k" to 1_000L, "m" to 1_000_000L, "b" to 1_000_000_000L)

    fun backArrow(img: Frame): P? = matchTemplate(img, Templates.backArrow, Config.BACK_ARROW_MIN_SCORE)

    /** "534,8k" -> 534800, "3,4m", "339k", "1045". */
    fun parsePower(s: String): Long? {
        val m = POWER_RE.find(s.trim().lowercase()) ?: return null
        val v = m.groupValues[1].replace(",", ".").toDouble() * SCALE.getValue(m.groupValues[2])
        return Math.rint(v).toLong()  // Python's round(): halves to even
    }

    fun inGuild(texts: List<Text>): Boolean = find(texts, L.GUILD_BUTTON, exact = true) != null

    fun vipCardsIcon(texts: List<Text>): Text? =
        texts.firstOrNull { matches(it, L.VIP_CARDS, exact = true) && it.center.x < Config.LOBBY_LEFT_ICONS_MAX_X }

    fun vipClaimAll(texts: List<Text>): Text? = texts.firstOrNull { matches(it, L.CLAIM_ALL, exact = true) && it.center.y > 2300 }

    fun guildHallDonate(texts: List<Text>): Text? = texts.firstOrNull { matches(it, L.DONATE, exact = true) && it.center.y > 2100 }

    fun freeDonation(texts: List<Text>): Text? {
        val title = find(texts, L.DONATION_TITLE) ?: return null
        return texts.firstOrNull { matches(it, L.FREE, exact = true) && it.center.y > title.center.y }
    }

    data class PatrolPopup(val claim: Text, val quick: Text, val elapsed: Int?)

    private val PATROL_TIME_RE = Regex("(\\d+):(\\d{2})(?::(\\d{2}))?\\s*$")

    fun patrolSeconds(text: String): Int? {
        val m = PATROL_TIME_RE.find(text) ?: return null
        val a = m.groupValues[1].toInt(); val b = m.groupValues[2].toInt(); val c = m.groupValues[3]
        return if (c.isNotEmpty()) a * 3600 + b * 60 + c.toInt() else a * 60 + b
    }

    fun parsePatrol(texts: List<Text>): PatrolPopup? {
        val timer = find(texts, L.PATROL_TIME)
        if (timer == null || find(texts, L.QUICK_PATROL_TEXT) != null) return null
        val row = texts.filter { it.center.y in Config.PATROL_BUTTONS_Y }
        val claim = row.firstOrNull { matches(it, L.PATROL_CLAIM, exact = true) }
        val quick = row.firstOrNull { matches(it, L.QUICK_PATROL) }
        return if (claim != null && quick != null) PatrolPopup(claim, quick, patrolSeconds(timer.norm)) else null
    }

    data class QuickPatrol(val video: Text?, val energy: Text?, val energyCost: Int = 0)

    private val ENERGY_COST_RE = Regex("^x\\s*(\\d+)$")

    private fun usesLeft(button: Text, texts: List<Text>): Int {
        val (lo, hi) = Config.REMAINING_BELOW_BUTTON
        for (t in texts) {
            val dy = t.center.y - button.center.y
            if (matches(t, L.REMAINING) && dy > lo && dy < hi && abs(t.center.x - button.center.x) < 150) {
                return TRAILING_NUMBER_RE.find(t.norm)?.groupValues?.get(1)?.toInt() ?: 0
            }
        }
        return 0
    }

    /** The energy option shows a cyan lightning left of its "x10"; a gem price would be purple. */
    private fun lightningIcon(img: Frame, label: Text): Boolean {
        val x = label.center.x; val y = label.center.y
        val x0 = maxOf(0, x - 150); val x1 = x - 35
        return img.fraction(x0, y - 45, x1, y + 45) { r, g, b ->
            val h = hsv(r, g, b)
            h[0] in 80..105 && h[1] > 90 && h[2] > 150
        } > Config.QUICK_PATROL_CYAN_MIN
    }

    fun parseQuickPatrol(img: Frame, texts: List<Text>): QuickPatrol? {
        if (find(texts, L.QUICK_PATROL_TEXT) == null) return null
        val video = texts.firstOrNull { matches(it, L.FREE, exact = true) && usesLeft(it, texts) > 0 }
        for (t in texts) {
            val m = ENERGY_COST_RE.find(t.norm)
            if (m != null && usesLeft(t, texts) > 0 && lightningIcon(img, t)) return QuickPatrol(video, t, m.groupValues[1].toInt())
        }
        return QuickPatrol(video, null, 0)
    }

    fun isModesList(texts: List<Text>): Boolean {
        val titles = listOf(L.ARENA, L.TOWER, L.MINES, L.PETS).map { find(texts, it, exact = it === L.ARENA) }
        return titles.count { it != null } >= 2 && find(texts, L.DIFFICULTY) == null
    }

    fun modeEntry(texts: List<Text>, label: Label): Text? = find(texts, label, exact = label === L.ARENA)

    fun modeClosed(texts: List<Text>, entry: Text): Boolean = texts.any {
        matches(it, L.ARENA_CLOSED) && it.center.y - entry.center.y in 1 until Config.MODE_SUBTITLE_BELOW
    }

    private fun bottomChallenge(texts: List<Text>): Text? = texts.firstOrNull { matches(it, L.CHALLENGE, exact = true) && it.center.y > 2300 }

    data class ArenaScreen(val challenge: Text, val tickets: Int)

    fun parseArena(img: Frame, texts: List<Text>, ocr: Ocr): ArenaScreen? {
        val title = find(texts, L.ARENA, exact = true)
        val button = bottomChallenge(texts)
        if (title == null || button == null || title.center.y >= Config.TOP_BAR_MAX_Y || find(texts, L.ARENA_PANEL) != null) return null
        val digits = ocr.read(img, Config.ARENA_TICKETS_REGION).filter { it.norm.isDigits() }
        if (digits.isEmpty()) return null
        return ArenaScreen(button, digits[0].norm.toInt())
    }

    data class Opponent(val power: Long, val challenge: Text?)
    data class ArenaOpponents(val ownPower: Long, val opponents: List<Opponent>, val freeRefresh: Text?)

    fun parseArenaOpponents(texts: List<Text>): ArenaOpponents? {
        if (find(texts, L.ARENA_PANEL) == null) return null
        val own = texts.firstNotNullOfOrNull { t ->
            if (t.center.y > Config.ARENA_POWER_Y.first && t.center.y < Config.ARENA_POWER_Y.second && t.center.x < Config.ARENA_ROW_POWER_X.second)
                parsePower(t.norm) else null
        } ?: return null
        val opponents = ArrayList<Opponent>()
        for (b in texts) {
            if (!(matches(b, L.CHALLENGE, exact = true) && b.center.y > Config.ARENA_ROWS_Y.first && b.center.y < Config.ARENA_ROWS_Y.second)) continue
            val (lo, hi) = Config.ARENA_ROW_POWER_BELOW
            val power = texts.firstNotNullOfOrNull { t ->
                val dy = t.center.y - b.center.y
                if (t.center.x > Config.ARENA_ROW_POWER_X.first && t.center.x < Config.ARENA_ROW_POWER_X.second && dy > lo && dy < hi) parsePower(t.norm) else null
            }
            if (power != null) opponents.add(Opponent(power, b))
        }
        return ArenaOpponents(own, opponents, find(texts, L.FREE_REFRESH))
    }

    /** The strongest opponent that is not stronger than us, or null if all are stronger. */
    fun pickOpponent(ownPower: Long, opponents: List<Opponent>): Opponent? = opponents.filter { it.power <= ownPower }.maxByOrNull { it.power }

    data class TowerScreen(val challenge: Text, val tickets: Int)

    fun parseTower(texts: List<Text>): TowerScreen? {
        val button = bottomChallenge(texts)
        if (find(texts, L.TOWER_TITLE) == null || button == null) return null
        return texts.firstNotNullOfOrNull { t ->
            val m = RATIO_RE.find(t.norm)
            if (m != null && t.center.y < Config.TOP_BAR_MAX_Y) TowerScreen(button, m.groupValues[1].toInt()) else null
        }
    }

    data class DojoScreen(val challenge: Text?, val tickets: Int, val chest: Text?)

    fun parseDojo(img: Frame, texts: List<Text>, ocr: Ocr): DojoScreen? {
        val title = find(texts, L.DOJO)
        if (title == null || title.center.y >= Config.DOJO_TITLE_MAX_Y) return null
        val digits = ocr.read(img, Config.DOJO_TICKETS_REGION).filter { it.norm.isDigits() }
        if (digits.isEmpty()) return null
        val chest = texts.firstOrNull { matches(it, L.DOJO_CHEST, exact = true) && it.center.y > Config.DOJO_CHEST_Y.first && it.center.y < Config.DOJO_CHEST_Y.second }
        return DojoScreen(bottomChallenge(texts), digits[0].norm.toInt(), chest)
    }

    data class DiveScreen(val challenge: Text, val tickets: Int)

    fun parseDive(texts: List<Text>): DiveScreen? {
        val button = bottomChallenge(texts)
        if (button == null || find(texts, L.DIVE_REWARDS, exact = true) == null || find(texts, L.TOWER_TITLE) != null) return null
        return texts.firstNotNullOfOrNull { t ->
            val m = RATIO_RE.find(t.norm)
            if (m != null && t.center.y < Config.TOP_BAR_MAX_Y) DiveScreen(button, m.groupValues[1].toInt()) else null
        }
    }

    fun menuEntry(texts: List<Text>, label: Label): Text? = texts.firstOrNull { matches(it, label, exact = true) && it.center.x < Config.MENU_MAX_X }

    fun dailyClaim(texts: List<Text>): Text? {
        val title = find(texts, L.DAILY_TITLE) ?: return null
        return texts.firstOrNull { matches(it, L.DAILY_CLAIM, exact = true) && it.center.y > title.center.y }
    }

    fun mailClaimAll(texts: List<Text>): Text? {
        if (find(texts, L.MAIL_TITLE, exact = true) == null) return null
        return find(texts, L.CLAIM_ALL, exact = true)
    }

    data class DungeonPopup(val difficulty: Int?, val tickets: Int, val challenge: Text?, val sweep: Text?, val ad: Text?)

    fun parseDungeonPopup(texts: List<Text>): DungeonPopup? {
        val diff = find(texts, L.DIFFICULTY)
        if (diff == null || (find(texts, L.MINES) == null && find(texts, L.PETS) == null)) return null
        val tickets = texts.firstNotNullOfOrNull { t ->
            val m = RATIO_RE.find(t.norm)
            if (m != null && t.center.y > Config.DUNGEON_TICKETS_Y.first && t.center.y < Config.DUNGEON_TICKETS_Y.second) m.groupValues[1].toInt() else null
        } ?: return null
        val level = texts.firstOrNull {
            it.norm.isDigits() && diff.center.y - it.center.y in 1 until 150 && abs(it.center.x - diff.center.x) < 100
        }?.norm?.toInt()
        return DungeonPopup(level, tickets, find(texts, L.CHALLENGE, exact = true), find(texts, L.SWEEP), find(texts, L.AD_TICKETS))
    }

    data class RaidScreen(val challenge: Text, val attempts: Int)

    fun parseRaid(texts: List<Text>): RaidScreen? {
        val button = bottomChallenge(texts)
        if (find(texts, L.RAID_TITLE) == null || button == null) return null
        val attempts = find(texts, L.RAID_ATTEMPTS)
        val m = attempts?.let { TRAILING_NUMBER_RE.find(it.norm) }
        return RaidScreen(button, m?.groupValues?.get(1)?.toInt() ?: 0)
    }

    data class SkillChoice(val cards: List<P>, val chosen: Int, val needed: Int, val learn: Text)

    private fun rarityRank(t: Text): Int? = L.RARITIES.indexOfFirst { matches(t, it, exact = true) }.takeIf { it >= 0 }

    fun parseSkillChoice(texts: List<Text>): SkillChoice? {
        val prompt = find(texts, L.SKILL_PROMPT)
        val learn = find(texts, L.LEARN_SKILLS)
        val m = learn?.let { LEARN_RE.find(it.norm) }
        if (prompt == null || m == null) return null
        val tags = texts.filter { it.center.y > prompt.center.y && rarityRank(it) != null && it.center.x in Config.SKILL_RARITY_X }
            .sortedWith(compareBy({ rarityRank(it) }, { it.center.y }))
        val cards = tags.map { P(Config.SKILL_CARD_TAP_X, it.center.y + Config.SKILL_CARD_TAP_BELOW_RARITY) }
        return SkillChoice(cards, m.groupValues[1].toInt(), m.groupValues[2].toInt(), learn)
    }

    data class FightResult(val victory: Boolean, val button: Text)

    fun parseFightResult(texts: List<Text>): FightResult? {
        val button = find(texts, L.OK, exact = true) ?: find(texts, L.TAP_TO_CONTINUE) ?: return null
        if (find(texts, L.VICTORY) != null) return FightResult(true, button)
        if (find(texts, L.DEFEAT) != null) return FightResult(false, button)
        return null
    }
}
