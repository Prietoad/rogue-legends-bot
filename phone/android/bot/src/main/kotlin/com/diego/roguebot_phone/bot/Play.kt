package com.diego.roguebot_phone.bot

import kotlin.math.abs

/** Port of roguebot/play.py: in-level loop (roll dice, fights, skills, events) until the level ends. */

class PlayError(msg: String) : RuntimeException(msg)

const val MAX_SHOP_STEPS = 8

/** Same screen kind and (nearly) the same point: OCR jitters text centers by a few pixels. */
fun sameTap(a: Pair<LevelScreen, P>, b: Pair<LevelScreen, P>?): Boolean =
    b != null && a.first == b.first && abs(a.second.x - b.second.x) <= Config.SAME_TAP_TOLERANCE &&
        abs(a.second.y - b.second.y) <= Config.SAME_TAP_TOLERANCE

class Player(
    val device: Device,
    val ocr: Ocr,
    val build: Build = Build(),
    val catalog: Catalog = Catalog(null),
    val ads: Boolean = false,
    val clock: Clock = SystemClock,
    val debug: DebugSink = DebugSink { _, name -> name },
    private val classify: (Frame, List<Text>) -> LevelState = Screens::classifyLevelScreen,
) {
    internal var state = BuildState()
    private var rerolled = false
    private var doubles = 0
    private var lastOffer: List<String>? = null
    private var speedTapped = false
    private var speedLocked = false
    private var autoHeld = false
    private var autoMissing = false

    /** Play until the level ends; returns VICTORY or DEFEAT. */
    fun playLevel(): LevelScreen {
        var lastKnown = clock.now()
        var lastTap: Pair<LevelScreen, P>? = null
        var repeats = 0
        var firstRepeat = clock.now()
        state = BuildState(); rerolled = false; doubles = 0; lastOffer = null
        while (true) {
            val img = device.screenshot()
            val texts = ocr.read(img)
            var s = classify(img, texts)

            if (s.kind == LevelScreen.SKILL_PICK) {
                s = LevelState(s.kind, pickSkill(texts) ?: s.tap)
            } else if (s.kind == LevelScreen.SHOP) {
                shop(texts)
            }

            if (s.kind == LevelScreen.DOUBLE_REWARD) {
                doubles++
                val proceed = find(texts, L.CONTINUE, exact = true)
                if ((!ads || doubles > Config.DOUBLE_REWARD_TRIES) && proceed != null) {
                    s = LevelState(LevelScreen.CONTINUE, proceed.center)
                } else if (!ads) {
                    s = LevelState(LevelScreen.UNKNOWN)  // Continue not read yet: never the ad button
                }
            } else if (s.kind == LevelScreen.REVIVE && !ads) {
                s = LevelState(LevelScreen.UNKNOWN)  // the free revive is a video: let the countdown run out
            }

            if ((s.kind == LevelScreen.BOARD_READY || s.kind == LevelScreen.AUTO_PLAY) && ensureDoubleSpeed(texts)) continue
            if (s.kind == LevelScreen.AUTO_PLAY && autoHeld) {
                Log.info("Auto-play on")
                autoHeld = false
            } else if (s.kind == LevelScreen.BOARD_READY && autoHeld) {
                Log.info("Holding the dice did not start auto-play; rolling by taps")
                autoHeld = false; autoMissing = true
            }

            if (s.kind == LevelScreen.VICTORY || s.kind == LevelScreen.DEFEAT) {
                Log.info("Level finished: ${s.kind.value}")
                device.tap(s.tap!!)
                return s.kind
            }

            if (s.kind == LevelScreen.UNKNOWN) {
                if (clock.now() - lastKnown > Config.UNKNOWN_SCREEN_TIMEOUT) fail("Stuck on an unknown screen", img)
            } else {
                lastKnown = clock.now()
            }

            val tap = s.tap
            if (tap != null) {
                val cur = s.kind to tap
                if (sameTap(cur, lastTap)) repeats++ else { repeats = 1; firstRepeat = clock.now() }
                lastTap = cur
                if (repeats > Config.MAX_REPEATED_TAPS && clock.now() - firstRepeat > Config.STUCK_TAP_SECONDS) {
                    fail("Tapping $tap on ${s.kind.value} has no effect", img)
                }
                if (s.kind == LevelScreen.BOARD_READY && !autoMissing) {
                    Log.info("board_ready -> hold $tap for auto-play")
                    device.hold(tap, Config.AUTO_PLAY_HOLD)
                    autoHeld = true
                } else {
                    Log.info("${s.kind.value} -> tap $tap")
                    device.tap(tap)
                }
            } else {
                lastTap = null; repeats = 0
                clock.sleep(Config.POLL_INTERVAL)
            }
        }
    }

    private fun skill(card: Screens.SkillCard): Skill = catalog.lookup(card.name, card.description, card.rarity, L.active)

    /** Tap point of the card the build wants, or of the reroll button. null if no card was read. */
    internal fun pickSkill(texts: List<Text>): P? {
        val cards = Screens.parseSkillCards(texts)
        if (cards.isEmpty()) return null
        val skills = cards.map(::skill)
        val reroll = Screens.skillReroll(texts)
        val i = Choice.choose(skills, build, state, canReroll = reroll != null && !rerolled)
        if (i == null) {
            Log.info("No wanted skill in ${skills.map { it.name }}: rerolling")
            rerolled = true
            return reroll!!.center
        }
        rerolled = false
        val offer = skills.map { it.name }
        if (offer != lastOffer) state.take(skills[i])  // the same offer again = the last tap did not land
        lastOffer = offer
        Log.info("Skill: ${skills[i].name} (${skills[i].rarity}, ${skills[i].damageType ?: "-"}, ${skills[i].role})")
        return P(Config.SCREEN_W / 2, cards[i].tag.center.y + Config.SKILL_TAP_BELOW_RARITY)
    }

    /** Free reroll if nothing is wanted, then buy in the build's order whatever the coins allow. */
    internal fun shop(texts0: List<Text>) {
        var texts = texts0
        var rerolledShop = false
        val tapped = HashSet<String>()
        repeat(MAX_SHOP_STEPS) {
            val shop = Screens.parseShop(texts) ?: return
            val money = shop.money ?: return
            val cards = shop.cards.filter { !it.sold && it.cost != null && it.name !in tapped }
            val skills = cards.map(::skill)
            val order = Choice.shopOrder(skills, build, state, canReroll = shop.freeReroll != null && !rerolledShop)
            if (order == null) {
                Log.info("Shop: no wanted skill in ${skills.map { it.name }}, free reroll")
                device.tap(shop.freeReroll!!.center)
                rerolledShop = true
            } else {
                val i = order.firstOrNull { cards[it].cost!! <= money } ?: return
                Log.info("Shop: buying ${skills[i].name} for ${cards[i].cost} (coins $money)")
                device.tap(cards[i].price!!.center)
                tapped.add(cards[i].name)
                state.take(skills[i])
            }
            texts = ocr.read(device.screenshot())
        }
    }

    /** Switch the game to x2 speed when it shows x1. Returns true if it tapped. */
    fun ensureDoubleSpeed(texts: List<Text>): Boolean {
        val speed = Screens.gameSpeed(texts)
        if (speed != 1 || speedLocked) {
            speedTapped = false
            return false
        }
        if (speedTapped) {
            Log.info("x2 speed is not unlocked on this account; playing at x1")
            speedLocked = true
            return false
        }
        Log.info("Enabling x2 speed")
        speedTapped = true
        device.tap(Config.SPEED_BUTTON)
        return true
    }

    private fun fail(msg: String, img: Frame): Nothing = throw PlayError("$msg (screenshot: ${debug.save(img, "play")})")
}
