package com.diego.roguebot_phone.bot

/** Port of roguebot/screens.py: OCR output -> typed screen states. No input is sent from here. */

enum class Mode(val value: String) { NORMAL("normal"), ELITE("elite") }

/** Image templates (the PNGs in roguebot/templates), loaded by the platform (assets on the phone). */
object Templates {
    lateinit var closeX: Template
    lateinit var backArrow: Template
    lateinit var tutorialHand: Template
    lateinit var pathShop: Template
}

fun startLabel(mode: Mode): Label = if (mode == Mode.NORMAL) L.START_NORMAL else L.START_ELITE

data class Lobby(
    val mode: Mode,
    val levelTitle: String?,
    val startButton: Text,
    val starsButton: Text?,
    val energy: Int?,
    val hasElite: Boolean = true,
    val mapButton: Text? = null,  // "Mapa Mundial" compass (null: no worlds on this account)
) {
    /** World of the shown level (1 = Everdale, 2 = Heliora: "2-1. Elysium I"); null if the title was not read. */
    val world: Int? get() = levelTitle?.let(::parseWorldNumber)
}

data class Card(val number: Int, val header: Text, val button: Text?, val stars: Int = 3)

object Screens {
    fun parseLobby(texts: List<Text>): Lobby? {
        if (find(texts, L.PATROL) == null || popupClose(texts) != null) return null
        if (find(texts, L.RESUME_ADVENTURE) != null) return null  // the lobby shows under the resume dialog, which takes every tap
        var hasElite = true
        val mode = when {
            find(texts, L.ELITE_ON, exact = true) != null -> Mode.ELITE
            find(texts, L.ELITE_OFF, exact = true) != null -> Mode.NORMAL
            else -> { hasElite = false; Mode.NORMAL }
        }
        val start = find(texts, startLabel(mode), exact = true) ?: return null
        val title = texts.firstOrNull { parseLevelNumber(it.text) != null }?.text
        var stars = find(texts, L.STARS_BUTTON)
        if (stars != null && matches(stars, L.PATROL)) {  // OCR joined "Patrulla" and "de Estrellas": the button is its right half
            stars = Text(stars.text, (stars.x1 + stars.x2) / 2, stars.y1, stars.x2, stars.y2)
        }
        return Lobby(mode, title, start, stars, parseEnergy(texts), hasElite, find(texts, L.WORLD_MAP_BUTTON))
    }

    /** The "Mapa Mundial" screen: each known world's name label (tapping it enters that world), or null. */
    fun parseWorldMap(texts: List<Text>): Map<String, Text>? {
        if (find(texts, L.WORLD_MAP_TITLE) == null || find(texts, L.PATROL) != null) return null
        val worlds = LinkedHashMap<String, Text>()
        for (w in Config.WORLDS) texts.firstOrNull { matches(it, w, exact = true) }?.let { worlds[w] = it }
        return worlds
    }

    fun isStarList(texts: List<Text>): Boolean =
        find(texts, L.STAR_LIST_TITLE) != null && find(texts, L.LIST_REWARDS) != null && find(texts, L.PATROL) == null

    private val COST_RE = Regex("^x\\s*(\\d+)$")
    private val ENERGY_RE = Regex("^(\\d+)\\s*/\\s*(\\d+)$")

    fun parseEnergy(texts: List<Text>): Int? = texts.firstNotNullOfOrNull { t ->
        val m = ENERGY_RE.find(t.norm)
        if (m != null && t.center.y < Config.TOP_BAR_MAX_Y && t.center.x in Config.ENERGY_X) m.groupValues[1].toInt() else null
    }

    data class EliteDialog(val startButton: Text, val cost: Int)

    fun parseEliteDialog(texts: List<Text>): EliteDialog? {
        val start = find(texts, L.START_NORMAL, exact = true)
        if (find(texts, L.ELITE_DIALOG_TITLE) == null || start == null) return null
        for (t in texts) {
            val m = COST_RE.find(t.norm)
            if (m != null && t.center.y - start.center.y in 1 until Config.COST_BELOW_START_MAX) return EliteDialog(start, m.groupValues[1].toInt())
        }
        return null
    }

    data class EnergyOffers(val freePack: Text?, val video: P?, val videosLeft: Int = 0)

    /** The video button is yellow; the gem-priced one next to it is green. */
    fun yellowButton(img: Frame, c: P): Boolean =
        img.fraction(c.x - 120, c.y - 35, c.x + 120, c.y + 35) { r, g, b -> r > 200 && g > 160 && b < 80 } > Config.VIDEO_YELLOW_MIN_FRACTION

    private val TRAILING_DIGITS = Regex("(\\d+)$")

    private fun chancesLeft(label: Text, texts: List<Text>): Int? {
        TRAILING_DIGITS.find(label.norm)?.let { return it.groupValues[1].toInt() }
        val below = texts.filter {
            it.norm.isDigits() && it.center.y - label.center.y in 1..Config.CHANCES_NUMBER_BELOW &&
                kotlin.math.abs(it.center.x - label.center.x) < Config.CHANCES_NUMBER_DX
        }
        return below.minByOrNull { kotlin.math.abs(it.center.x - label.center.x) }?.norm?.toInt()
    }

    fun parseEnergyPopup(img: Frame, texts: List<Text>): EnergyOffers? {
        if (find(texts, L.ENERGY_POPUP_TITLE) == null) return null
        var video: P? = null
        var videosLeft = 0
        for (t in texts) {
            val left = if (matches(t, L.ENERGY_CHANCES)) chancesLeft(t, texts) else null
            if (left != null && left != 0) {
                val button = P(t.center.x, t.center.y + Config.VIDEO_BELOW_CHANCES)
                if (yellowButton(img, button)) { video = button; videosLeft = left; break }
                if (t.center.x < Config.SCREEN_W / 2) videosLeft = left
            }
        }
        val freePack = if (find(texts, L.DAILY_PACK_CLAIMED) != null) null else find(texts, L.ENERGY_FREE, exact = true)
        return EnergyOffers(freePack, video, videosLeft)
    }

    fun updateRequired(texts: List<Text>): Boolean = find(texts, L.UPDATE_REQUIRED) != null

    fun resumePrompt(texts: List<Text>): Text? {
        val title = find(texts, L.RESUME_ADVENTURE) ?: return null
        return texts.firstOrNull { matches(it, L.OK, exact = true) && it.center.y > title.center.y }
    }

    fun isLoading(texts: List<Text>): Boolean = find(texts, L.LOADING) != null

    fun closeButton(img: Frame): P? = matchTemplate(img, Templates.closeX, Config.CLOSE_X_MIN_SCORE)

    private val closeXScaled by lazy { Config.CLOSE_X_SCALES.map { Template(Templates.closeX.src.scaled(it)) } }

    /** The same ✕ drawn at another size (unknown popups, e.g. new seasonal events). Slower than
     *  closeButton: only for popups nothing else recognized. */
    fun closeButtonAnySize(img: Frame): P? = closeXScaled.firstNotNullOfOrNull { matchTemplate(img, it, Config.CLOSE_X_MIN_SCORE) }

    /** Lobby labels (footer "Aventura", "Patrulla", "Gremio", "Modos") show, dimmed, under lobby popups and
     *  never on a level board: such a screen is a popup, never a level to play (a seasonal event popup once
     *  looked like a level event and the bot tapped it as one). */
    fun lobbyBehind(texts: List<Text>): Boolean =
        find(texts, L.PATROL) != null || find(texts, L.GUILD_BUTTON, exact = true) != null || find(texts, L.MODES_BUTTON, exact = true) != null ||
            texts.any { matches(it, L.LOBBY_TAB, exact = true) && it.center.y > Config.FOOTER_Y.first }

    /** No text but the footer tab label or a "para cerrar" hint near POPUP_OUTSIDE_TAP: tapping it can't
     *  hit a popup's button (a price, a purchase). */
    fun outsideTapClear(texts: List<Text>): Boolean {
        val (x, y) = Config.POPUP_OUTSIDE_TAP
        val m = Config.OUTSIDE_TAP_CLEARANCE
        return texts.none { t -> t.x1 - m < x && x < t.x2 + m && t.y1 - m < y && y < t.y2 + m &&
            !matches(t, L.LOBBY_TAB, exact = true) && !matches(t, L.POPUP_CLOSE) }
    }

    fun tutorialHand(img: Frame): P? {
        val c = matchTemplate(img, Templates.tutorialHand, Config.TUTORIAL_HAND_MIN_SCORE) ?: return null
        return P(c.x + Config.TUTORIAL_TAP_OFFSET.x, c.y + Config.TUTORIAL_TAP_OFFSET.y)
    }

    /** Main screens show the bottom tab bar at full brightness; popups darken it. Every tab but the selected
     * one must show its color. */
    fun footerVisible(img: Frame): Boolean = Config.FOOTER_SAMPLES.count { (xs, bgr) ->
        val m = img.mean(xs.first, Config.FOOTER_Y.first, xs.last + 1, Config.FOOTER_Y.last + 1)
        maxOf(kotlin.math.abs(m[2] - bgr[0]), kotlin.math.abs(m[1] - bgr[1]), kotlin.math.abs(m[0] - bgr[2])) < Config.FOOTER_COLOR_TOLERANCE
    } >= Config.FOOTER_MIN_TABS

    /** Lobby promo popups ("Toca para cerrar"). Only this text is ever tapped on a popup. */
    fun popupClose(texts: List<Text>): Text? = find(texts, L.POPUP_CLOSE)

    private val COUNTER_RE = Regex("^(\\D+?)\\s*(\\d+)\\s*/\\s*(\\d+)$")

    fun counter(texts: List<Text>, prefix: Label): Int? = texts.firstNotNullOfOrNull { t ->
        val m = COUNTER_RE.find(t.norm)
        if (m != null && m.groupValues[1].trim() in prefix.variants) m.groupValues[2].toInt() else null
    }

    fun diceReady(img: Frame): Boolean {
        val r = Config.DICE_REGION
        return img.fraction(r.x1, r.y1, r.x2, r.y2) { R, G, B -> R > 170 && G < 90 && B < 90 } > Config.DICE_RED_MIN_FRACTION
    }

    fun diceAuto(img: Frame): Boolean {
        val r = Config.DICE_REGION
        return img.fraction(r.x1, r.y1, r.x2, r.y2) { R, G, B -> G > 150 && R > 120 && B < 90 && G > R } > Config.DICE_GREEN_MIN_FRACTION
    }

    private val SPEED_RE = Regex("x\\s*([12])$")

    fun gameSpeed(texts: List<Text>): Int? = texts.firstNotNullOfOrNull { t ->
        val m = SPEED_RE.find(t.norm)
        if (m != null && t.center.x in Config.SPEED_LABEL_X && t.center.y in Config.SPEED_LABEL_Y) m.groupValues[1].toInt() else null
    }

    private fun diceDuel(texts: List<Text>): P? {
        val roll = find(texts, L.DUEL_ROLL, exact = true)
        val stand = find(texts, L.DUEL_STAND, exact = true)
        val score = counter(texts, L.DUEL_SCORE_PREFIX)
        if (roll == null || stand == null || score == null) return null
        return (if (score < Config.DUEL_STAND_AT) roll else stand).center
    }

    private fun faceDown(img: Frame, c: P): Boolean =
        img.fraction(c.x - 50, c.y - 60, c.x + 50, c.y + 60) { r, g, b -> b > 200 && g > 150 && r < 150 } > Config.FLIP_FACE_DOWN_MIN_FRACTION

    /** A used-up option turns its icon grey: mean HSV saturation of the icon. */
    private fun optionEnabled(img: Frame, label: Text): Boolean {
        val x = label.center.x
        val y = label.center.y + Config.EVENT_ICON_BELOW_LABEL
        var sum = 0.0; var n = 0
        for (yy in (y - 120).coerceAtLeast(0) until (y + 120).coerceAtMost(img.height))
            for (xx in (x - 120).coerceAtLeast(0) until (x + 120).coerceAtMost(img.width)) {
                sum += hsv(img.r(xx, yy), img.g(xx, yy), img.b(xx, yy))[1]; n++
            }
        return n > 0 && sum / n > Config.EVENT_DISABLED_MAX_SATURATION
    }

    /** A tile event's option labels that can be taken (not greyed out), left to right; empty if not an event. */
    fun eventOptions(img: Frame, texts: List<Text>): List<Text> {
        val hasTitle = texts.any {
            it.center.y in Config.EVENT_TITLE_Y && kotlin.math.abs(it.center.x - Config.SCREEN_W / 2) < Config.EVENT_TITLE_CENTER_TOLERANCE
        }
        if (!hasTitle) return emptyList()
        val labels = texts.filter { it.center.y in Config.EVENT_LABEL_Y }
        return labels.filter { optionEnabled(img, it) }.ifEmpty { labels }.sortedBy { it.center.x }
    }

    /** An event option is taken by its icon, below its label. */
    fun eventTap(label: Text) = P(label.center.x, label.center.y + Config.EVENT_ICON_BELOW_LABEL)

    private fun eventOption(img: Frame, texts: List<Text>): P? {
        val labels = eventOptions(img, texts)
        if (labels.isEmpty()) return null
        return eventTap(labels.firstOrNull { matches(it, L.LEAVE, exact = true) } ?: labels[0])
    }

    data class PathOption(val label: Text, val shop: Boolean)

    private val PATH_RE = Regex("^(.+) ([a-d])$")

    /** The shop wagon is drawn on the fork card above this label (the phone's OCR does not read its sign). */
    private fun shopCard(img: Frame, label: Text): Boolean {
        val c = label.center
        val card = img.crop(Region(c.x - Config.PATH_CARD_HALF_WIDTH, c.y - Config.PATH_CARD_HEIGHT, c.x + Config.PATH_CARD_HALF_WIDTH, c.y))
        val t = Templates.pathShop
        return card.width >= t.width && card.height >= t.height && matchTemplate(card, t, Config.PATH_SHOP_MIN_SCORE) != null
    }

    /** A board fork: its cards ("Camino A", "Camino B") left to right, each showing where the path leads;
     *  empty when the board shows no fork. A shop card is known by its picture (given the frame) or by the
     *  sign on it ("SHOP", "BLACK / MARKET"). */
    fun parsePaths(texts: List<Text>, img: Frame? = null): List<PathOption> {
        val labels = texts.filter { t ->
            val m = PATH_RE.find(t.norm)
            m != null && m.groupValues[1] in L.PATH_OPTION.variants && t.center.y > Config.PATH_LABEL_MIN_Y
        }.sortedBy { it.center.x }
        if (labels.size < 2) return emptyList()
        return labels.map { p ->
            PathOption(p, texts.any { matches(it, L.PATH_SHOP, exact = true) &&
                kotlin.math.abs(it.center.x - p.center.x) < Config.PATH_CARD_HALF_WIDTH &&
                p.center.y - it.center.y in 1 until Config.PATH_CARD_HEIGHT } || (img != null && shopCard(img, p)))
        }
    }

    data class Contract(val button: Text, val terms: String)

    /** "Vendedor Maldito": the contracts on offer, left to right; empty on any other screen. */
    fun parseContracts(texts: List<Text>): List<Contract> {
        if (find(texts, L.CURSED_VENDOR) == null) return emptyList()
        val buttons = texts.filter { matches(it, L.SIGN, exact = true) }.sortedBy { it.center.x }
        if (buttons.size < 2) return emptyList()
        val ordered = texts.sortedWith(compareBy({ it.center.y }, { it.center.x }))
        return buttons.map { b ->
            Contract(b, ordered.filter { it.center.y in Config.CONTRACT_TEXT_Y && kotlin.math.abs(it.center.x - b.center.x) < Config.CONTRACT_HALF_WIDTH }
                .joinToString(" ") { it.norm })
        }
    }

    const val DIRT = "dirt"
    const val EMPTY = "empty"
    const val TREASURE = "treasure"

    fun minerTile(row: Int, col: Int) = P(Config.MINER_ORIGIN.x + col * Config.MINER_PITCH, Config.MINER_ORIGIN.y + row * Config.MINER_PITCH)

    /** "Minero de Tesoros" grid, row by row: DIRT (not dug), EMPTY (dug, nothing) or TREASURE. */
    fun minerTiles(img: Frame): List<String> {
        val h = Config.MINER_TILE_HALF
        return (0 until Config.MINER_SIZE * Config.MINER_SIZE).map { i ->
            val c = minerTile(i / Config.MINER_SIZE, i % Config.MINER_SIZE)
            val dark = img.fraction(c.x - h, c.y - h, c.x + h, c.y + h) { r, g, b -> maxOf(r, g, b) < 60 }
            val m = img.mean(c.x - h, c.y - h, c.x + h, c.y + h)
            val d = Config.MINER_DIRT
            when {
                dark > Config.MINER_EMPTY_DARK -> EMPTY
                maxOf(kotlin.math.abs(m[2] - d[0]), kotlin.math.abs(m[1] - d[1]), kotlin.math.abs(m[0] - d[2])) < Config.MINER_DIRT_TOLERANCE -> DIRT
                else -> TREASURE
            }
        }
    }

    /** N of "Tesoros Restantes: N" (OCR may split the number off). */
    fun treasuresLeft(texts: List<Text>): Int? {
        val label = find(texts, L.TREASURES_LEFT) ?: return null
        TRAILING_DIGITS.find(label.norm)?.let { return it.groupValues[1].toInt() }
        return texts.firstOrNull { it.norm.isDigits() && kotlin.math.abs(it.center.y - label.center.y) < 40 && it.x1 - label.x2 in 1 until 120 }?.norm?.toInt()
    }

    /** The hero's HP share in a level, from the top bar "7,2m / 10,1m" -> 0.71. */
    fun parseHp(texts: List<Text>): Double? {
        val r = Config.HP_REGION
        for (t in texts) {
            if (t.center.x !in r.x1..r.x2 || t.center.y !in r.y1..r.y2 || t.norm.count { it == '/' } != 1) continue
            val (now, top) = t.norm.split("/").map(ModeScreens::parsePower)
            if (now != null && top != null && top != 0L) return minOf(1.0, now.toDouble() / top.toDouble())
        }
        return null
    }

    fun classifyLevelScreen(img: Frame, texts: List<Text>): LevelState {
        if (footerVisible(img)) return LevelState(LevelScreen.UNKNOWN)
        val proceed = find(texts, L.CONTINUE, exact = true)
        val double = find(texts, L.DOUBLE_REWARD)
        if (proceed != null && double != null) return LevelState(LevelScreen.DOUBLE_REWARD, double.center)
        val end = proceed ?: find(texts, L.CONFIRM, exact = true)  // Dungeon Dive ends with "Confirmar"
        if (end != null && find(texts, L.DEFEAT) != null) return LevelState(LevelScreen.DEFEAT, end.center)
        if (end != null && find(texts, L.VICTORY) != null) return LevelState(LevelScreen.VICTORY, end.center)
        val pick = find(texts, L.SKILL_PROMPT)
        if (pick != null) {
            val tags = texts.filter { it.center.y > pick.center.y && it.center.x in Config.SKILL_RARITY_X }
            if (tags.isNotEmpty()) {
                val first = tags.minBy { it.center.y }
                return LevelState(LevelScreen.SKILL_PICK, P(Config.SCREEN_W / 2, first.center.y + Config.SKILL_TAP_BELOW_RARITY))
            }
        }
        parseContracts(texts).firstOrNull()?.let { return LevelState(LevelScreen.CONTRACT, it.button.center) }
        parsePaths(texts).firstOrNull()?.let { return LevelState(LevelScreen.PATH_CHOICE, it.label.center) }
        if (proceed != null && find(texts, L.LEVEL_MODIFIERS, exact = true) != null) return LevelState(LevelScreen.CONTINUE, proceed.center)
        find(texts, L.EXACT_BUTTONS, exact = true)?.let { return LevelState(LevelScreen.CONTINUE, it.center) }
        for (label in L.CONTINUE_BUTTONS) find(texts, label)?.let { return LevelState(LevelScreen.CONTINUE, it.center) }
        diceDuel(texts)?.let { return LevelState(LevelScreen.DICE_DUEL, it) }
        if (find(texts, L.FLIP_CARDS_PROMPT) != null) {
            return LevelState(LevelScreen.FLIP_CARDS, Config.FLIP_CARDS.firstOrNull { faceDown(img, it) })
        }
        if (find(texts, L.FORTUNE_TELLER) != null) return LevelState(LevelScreen.FORTUNE_TELLER, Config.FORTUNE_TELLER_BACK)
        val leave = find(texts, L.LEAVE, exact = true)
        if (leave != null && find(texts, L.SHOP_REROLL) != null) return LevelState(LevelScreen.SHOP, leave.center)
        eventOption(img, texts)?.let { return LevelState(LevelScreen.EVENT, it) }
        if (leave != null) return LevelState(LevelScreen.LEAVE, leave.center)
        if (find(texts, L.TREASURE_MINER) != null && find(texts, L.TREASURES_LEFT) != null) return LevelState(LevelScreen.MINER)  // out of pickaxes it shows "Salir" (above)
        if (find(texts, L.REVIVE_PROMPT) != null) {
            val free = find(texts, L.REVIVE_FREE, exact = true)
            if (free != null && yellowButton(img, free.center)) return LevelState(LevelScreen.REVIVE, free.center)
            return LevelState(LevelScreen.UNKNOWN)
        }
        if (counter(texts, L.FIGHT_ROUND) != null) return LevelState(LevelScreen.FIGHT)
        if (diceAuto(img)) return LevelState(LevelScreen.AUTO_PLAY)
        if (diceReady(img)) return LevelState(LevelScreen.BOARD_READY, Config.DICE_BUTTON)
        return LevelState(LevelScreen.UNKNOWN)
    }

    /** Gold star icons (earned) right of a card header. */
    fun cardStars(img: Frame, header: Text): Int {
        val y = header.center.y
        return Config.STAR_ICONS_X.count { x ->
            val m = img.mean(x - 12, y - 12, x + 12, y + 12)
            m[0] > 180 && m[2] < 150
        }
    }

    fun parseStarList(img: Frame, texts: List<Text>, ocr: Ocr): List<Card> {
        val cards = LinkedHashMap<Int, Card>()
        val buttons = texts.filter { t -> Mode.values().any { matches(t, startLabel(it), exact = true) } && t.center.y > Config.LIST_TOP && t.center.y < Config.LIST_BOTTOM }
        for (b in buttons) {
            val cy = b.center.y - Config.HEADER_ABOVE_BUTTON
            if (cy - Config.HEADER_HALF_HEIGHT < Config.LIST_TOP) continue
            val region = Region(Config.HEADER_X_RANGE.first, cy - Config.HEADER_HALF_HEIGHT, Config.HEADER_X_RANGE.second, cy + Config.HEADER_HALF_HEIGHT)
            for (h in ocr.read(img, region)) {
                val n = parseLevelNumber(h.text)
                if (n != null) { cards[n] = Card(n, h, b, cardStars(img, h)); break }
            }
        }
        for (t in texts) {
            val n = parseLevelNumber(t.text)
            if (n != null && n !in cards && t.center.y > Config.LIST_TOP && t.center.y < Config.LIST_BOTTOM) cards[n] = Card(n, t, null)
        }
        return cards.values.sortedBy { it.number }
    }

    // --- skill cards (skill pick and shop) ---

    data class SkillCard(val rarity: String, val name: String, val description: String, val tag: Text,
                         val price: Text? = null, val sold: Boolean = false) {
        val cost: Int? get() = price?.norm?.toInt()
    }

    fun rarityName(t: Text): String? = L.RARITIES.indexOfFirst { matches(t, it, exact = true) }.let { if (it < 0) null else Skills.RARITY_NAMES[it] }

    private val TWO_LETTERS = Regex("[a-z]{2}")

    fun parseSkillCards(texts: List<Text>): List<SkillCard> {
        val tags = texts.filter { it.center.x in Config.SKILL_RARITY_X && rarityName(it) != null }.sortedBy { it.center.y }
        val cards = ArrayList<SkillCard>()
        for ((i, tag) in tags.withIndex()) {
            val top = tag.center.y - 30
            val bottom = if (i + 1 < tags.size) tags[i + 1].center.y - 30 else tag.center.y + Config.SKILL_CARD_HEIGHT
            val band = texts.filter { it.center.y >= top && it.center.y < bottom && it !== tag }
            val words = band.filter { it.x1 >= Config.SKILL_TEXT_MIN_X && it.center.x < Config.SHOP_PRICE_MIN_X && TWO_LETTERS.containsMatchIn(it.norm) &&
                it.norm != "exp" }  // "EXP" floats over a level-up pick after a fight
                .sortedWith(compareBy({ it.center.y }, { it.center.x }))
            if (words.isEmpty() || words[0].center.y - tag.center.y !in Config.SKILL_NAME_BELOW_TAG) continue
            val prices = band.filter { it.center.x >= Config.SHOP_PRICE_MIN_X && it.norm.isDigits() }
            cards.add(SkillCard(rarityName(tag)!!, words[0].text, words.drop(1).joinToString(" ") { it.text }, tag,
                prices.maxByOrNull { it.center.y }, band.any { matches(it, L.SOLD_OUT) }))
        }
        return cards
    }

    private fun below(button: Text, texts: List<Text>): List<Text> = texts.filter {
        it.center.y - button.center.y in 1..Config.REROLL_COUNT_BELOW && kotlin.math.abs(it.center.x - button.center.x) < 120
    }

    private val USES_RE = Regex("^\\((\\d+)\\)$")

    fun skillReroll(texts: List<Text>): Text? {
        val button = find(texts, L.SKILL_REROLL) ?: return null
        val uses = below(button, texts).firstNotNullOfOrNull { USES_RE.find(it.norm)?.groupValues?.get(1)?.toInt() } ?: 0
        return if (uses > 0) button else null
    }

    fun parseMoney(texts: List<Text>): Int? {
        val r = Config.MONEY_REGION
        return texts.firstOrNull { it.norm.isDigits() && it.center.x in r.x1..r.x2 && it.center.y in r.y1..r.y2 }?.norm?.toInt()
    }

    /** items = stat items on sale: BOOST / HEAL -> price button. */
    data class Shop(val money: Int?, val cards: List<SkillCard>, val freeReroll: Text?, val exit: Text,
                    val items: Map<String, Text> = emptyMap())

    const val BOOST = "boost"  // a stat up for the run ("ATQ ↑↑↑", "PS máx. ↑↑", 3 uses)
    const val HEAL = "heal"    // "Curar 30%"
    private val USES_LEFT_RE = Regex("^(\\d)\\s*/\\s*\\d$")

    /** The shop's stat items (above the skill cards): label, price below it; above it the uses left
     *  ("3/3") or "AGOTADO" once used up (then it is left out). */
    private fun shopItems(texts: List<Text>): Map<String, Text> {
        val items = LinkedHashMap<String, Text>()
        for (name in texts) {
            if (name.center.y !in Config.SHOP_ITEMS_Y) continue
            val kind = if (L.SHOP_HEAL.variants.any { name.norm.startsWith(it) }) HEAL else BOOST  // OCR may drop the arrows ("ATQ")
            val near = texts.filter { kotlin.math.abs(it.center.x - name.center.x) < Config.SHOP_ITEM_DX }
            val above = near.filter { name.center.y - it.center.y in Config.SHOP_ITEM_ABOVE }
            val price = near.firstOrNull { it.norm.isDigits() && it.center.y - name.center.y in Config.SHOP_ITEM_PRICE_BELOW }
            val usedUp = above.any { matches(it, L.SOLD_OUT) || USES_LEFT_RE.find(it.norm)?.groupValues?.get(1) == "0" }
            if (price != null && !usedUp) items[kind] = price
        }
        return items
    }

    /** The shop or the black market (same screen, run coins, half price). */
    fun parseShop(texts: List<Text>): Shop? {
        val leave = find(texts, L.LEAVE, exact = true)
        val reroll = find(texts, L.SHOP_REROLL)
        if (leave == null || reroll == null) return null
        val free = if (below(reroll, texts).any { matches(it, L.FREE, exact = true) }) reroll else null
        return Shop(parseMoney(texts), parseSkillCards(texts), free, leave, shopItems(texts))
    }

    /** "Adivino": orbs left and each ball's buy button by its chance (100, 70, 40). */
    data class FortuneTeller(val orbs: Int?, val balls: Map<Int, P>)

    private val CHANCE_RE = Regex("^(\\d+)\\s*%$")

    fun parseFortuneTeller(texts: List<Text>): FortuneTeller? {
        if (find(texts, L.FORTUNE_TELLER) == null) return null
        val r = Config.FORTUNE_ORBS_REGION
        val orbs = texts.firstOrNull { it.norm.isDigits() && it.center.x in r.x1..r.x2 && it.center.y in r.y1..r.y2 }?.norm?.toInt()
        val balls = texts.mapNotNull { t ->
            CHANCE_RE.find(t.norm)?.let { it.groupValues[1].toInt() to P(t.center.x, t.center.y + Config.FORTUNE_BUTTON_BELOW_TAG) }
        }.toMap()
        return FortuneTeller(orbs, balls)
    }
}

enum class LevelScreen(val value: String) {
    VICTORY("victory"), DEFEAT("defeat"), DOUBLE_REWARD("double_reward"), REVIVE("revive"), SKILL_PICK("skill_pick"),
    BOARD_READY("board_ready"), AUTO_PLAY("auto_play"), FIGHT("fight"), EVENT("event"), SHOP("shop"), LEAVE("leave"),
    FORTUNE_TELLER("fortune_teller"), PATH_CHOICE("path_choice"), MINER("miner"), CONTRACT("contract"),
    CONTINUE("continue"), DICE_DUEL("dice_duel"), FLIP_CARDS("flip_cards"), UNKNOWN("unknown")
}

data class LevelState(val kind: LevelScreen, val tap: P? = null)
