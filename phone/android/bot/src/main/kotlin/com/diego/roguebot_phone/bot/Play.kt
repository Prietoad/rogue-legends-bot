package com.diego.roguebot_phone.bot

import kotlin.math.abs

/** Port of roguebot/play.py: in-level loop (roll dice, fights, skills, events) until the level ends. */

class PlayError(msg: String) : RuntimeException(msg)

const val MAX_SHOP_STEPS = 16

/** True when paying `cost` still leaves a wanted skill buyable. A free refresh always passes. */
fun refreshLeavesABuy(money: Int, cost: Int, wantedCosts: List<Int>, floor: Int = Config.SHOP_SKILL_FLOOR): Boolean {
    if (cost <= 0) return money >= 0
    if (money < cost) return false
    val after = money - cost
    val affordable = wantedCosts.filter { it <= money }
    if (affordable.isNotEmpty()) return after >= affordable.min()
    return after >= floor
}

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
    private var autoSeen = false  // auto-play worked in this level: a hold that brings the red dice back was missed
    private var autoMisses = 0    // such missed holds in a row
    private var fortuneBought = ArrayList<Int>()  // Fortune Teller balls bought this visit (chances)
    private var fortuneTap: Triple<Int, Int, Double>? = null  // (chance, orbs before, time) of the last ball tap
    private var monkSpins = 0  // spins whose reward was claimed this visit
    private var monkArmed: Double? = null  // when the current spin was tapped; cleared when its reward is claimed
    private var monkLeaveSince: Double? = null  // Salir showed while a spin was still owed
    private var monkSince: Double? = null  // start of the current unresolved Monk wait
    private var monkRetapped = false  // the in-flight spin was tapped a second time
    private var monkYielded = false  // timed out: the generic level loop owns this screen
    private var campfireWaits = 0

    /** Play until the level ends; returns VICTORY or DEFEAT. */
    fun playLevel(): LevelScreen {
        var lastKnown = clock.now()
        var lastTap: Pair<LevelScreen, P>? = null
        var repeats = 0
        var firstRepeat = clock.now()
        state = BuildState(); rerolled = false; doubles = 0; lastOffer = null
        fortuneBought = ArrayList(); fortuneTap = null
        resetMonk()
        campfireWaits = 0
        while (true) {
            val img = device.screenshot()
            val texts = ocr.read(img)
            var s = classify(img, texts)
            val rawKind = s.kind

            if (rawKind == LevelScreen.SKILL_PICK) {
                s = LevelState(s.kind, pickSkill(texts) ?: s.tap)
            } else if (rawKind == LevelScreen.SHOP) {
                shop(texts)
            } else if (rawKind == LevelScreen.FORTUNE_TELLER) {
                s = LevelState(s.kind, fortune(texts))
            } else if (rawKind == LevelScreen.MONK && !monkYielded) {
                val tap = monkTap(texts, img)
                s = if (monkYielded && tap == null && s.tap == null) {
                    LevelState(LevelScreen.UNKNOWN)  // nothing to tap: the unknown-screen guard applies
                } else if (!(monkYielded && tap == null)) {
                    LevelState(LevelScreen.MONK, tap)
                } else {
                    s  // classifier found SPIN/Leave: that tap is the recovery
                }
            } else if (rawKind == LevelScreen.MONK && s.tap == null) {
                s = LevelState(LevelScreen.UNKNOWN)
            } else if (rawKind == LevelScreen.BOARD_READY || rawKind == LevelScreen.AUTO_PLAY) {
                fortuneBought.clear()  // back on the board: a later Fortune Teller is a new visit
                resetMonk()
            }
            if (rawKind != LevelScreen.MONK) monkYielded = false

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
                autoHeld = false; autoSeen = true; autoMisses = 0
            } else if (s.kind == LevelScreen.BOARD_READY && autoHeld) {
                autoHeld = false; autoMisses++
                if (autoSeen && autoMisses < Config.AUTO_PLAY_RETRIES) {
                    Log.info("Holding the dice did not start auto-play this time; holding again")
                } else {
                    Log.info("Holding the dice did not start auto-play; rolling by taps")
                    autoMissing = true
                }
            }

            if (s.kind == LevelScreen.EVENT && s.tap == null) {
                campfireWaits += 1
                if (campfireWaits <= Config.CAMPFIRE_REREADS) {
                    Log.info("Campfire: skill upgrade not readable, rereading ($campfireWaits)")
                    clock.sleep(Config.POLL_INTERVAL)
                    continue
                }
                val fallback = Screens.campfireNonHealTap(texts)
                campfireWaits = 0
                if (fallback == null) {
                    Log.info("Campfire: no non-heal option; not restoring HP")
                    clock.sleep(Config.POLL_INTERVAL)
                    continue
                }
                Log.info("Campfire: upgrade still unreadable; choosing the non-heal option")
                s = LevelState(LevelScreen.EVENT, fallback)
            } else {
                campfireWaits = 0
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

    private fun skill(card: Screens.SkillCard): Skill {
        val known = catalog.lookup(card.name, card.description, card.rarity, L.active)
        if (!known.auto) return known
        val fresh = Skills.inferTags(card.name, card.description)
        if (fresh.damageType != null && fresh.damageType != known.damageType) {
            Log.info("Skill ${card.name} read as ${fresh.damageType} from its card (saved tag ${known.damageType ?: "-"})")
            return known.copy(damageType = fresh.damageType, nature = fresh.nature, role = fresh.role)
        }
        return known
    }

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

    /** Fortune Teller: buy the balls in FORTUNE_BUYS order while the orbs allow, then the back arrow.
     *  A buy counts once the orb counter drops (a missed tap is tapped again); null = wait for it. */
    internal fun fortune(texts: List<Text>): P? {
        val teller = Screens.parseFortuneTeller(texts) ?: return Config.FORTUNE_TELLER_BACK
        fortuneTap?.let { (chance, orbs, tapped) ->
            if (teller.orbs != null && teller.orbs < orbs) fortuneBought.add(chance)
            else if (clock.now() - tapped < Config.FORTUNE_RETAP_AFTER) return null
            fortuneTap = null
        }
        if (teller.orbs != null) {
            for ((chance, times) in Config.FORTUNE_BUYS) {
                val button = teller.balls[chance] ?: continue
                if (fortuneBought.count { it == chance } < times && teller.orbs >= Config.FORTUNE_COST.getValue(chance)) {
                    Log.info("Fortune Teller: $chance% ball (orbs ${teller.orbs})")
                    fortuneTap = Triple(chance, teller.orbs, clock.now())
                    return button
                }
            }
        }
        return Config.FORTUNE_TELLER_BACK
    }

    private fun resetMonk() {
        monkSpins = 0
        monkArmed = null
        monkLeaveSince = null
        monkSince = null
        monkRetapped = false
        monkYielded = false
    }

    /** The reward overlay after a spin ("Tap anywhere to claim" / "You Received"). */
    private fun monkClaim(texts: List<Text>): P? {
        find(texts, L.TAP_TO_CLAIM)?.let { return it.center }
        if (find(texts, L.MONK_REWARD) != null) return P(Config.SCREEN_W / 2, Config.SCREEN_H / 2)
        return null
    }

    /** One frame of a Monk wait. Past MONK_WAIT_TIMEOUT, recover instead of returning null forever. */
    private fun monkWait(img: Frame, texts: List<Text>, message: String): P? {
        val now = clock.now()
        if (monkSince == null) monkSince = now
        if (now - monkSince!! >= Config.MONK_WAIT_TIMEOUT) return monkGiveUp(img, texts)
        Log.info(message)
        return null
    }

    /** The wait never ended. Warn, keep a screenshot, tap a reward or Leave if one is readable. */
    private fun monkGiveUp(img: Frame, texts: List<Text>): P? {
        val waited = monkSince?.let { clock.now() - it } ?: 0.0
        Log.warn("Wise Monk: timed out after ${waited.toInt()}s with $monkSpins/${Config.MONK_SPINS} spins claimed; recovering")
        Log.warn("Wise Monk: saved ${debug.save(img, "monk")}")
        monkYielded = true
        monkArmed = null
        monkSince = null
        monkLeaveSince = null
        monkRetapped = false
        monkClaim(texts)?.let {
            Log.info("Wise Monk: recovery tap on the reward")
            return it
        }
        val cont = find(texts, L.TAP_TO_CONTINUE) ?: find(texts, L.CONTINUE, exact = true)
        if (cont != null) {
            Log.info("Wise Monk: recovery tap to continue")
            return cont.center
        }
        find(texts, L.LEAVE, exact = true)?.let {
            Log.info("Wise Monk: recovery tap on Leave")
            return it.center
        }
        Log.info("Wise Monk: no reward or Leave to tap; back to screen detection")
        return null
    }

    /** Wise Monk: spin twice, claim each reward, then leave. HP is never a reason to stop early.
     *  A spin counts only when its reward overlay is tapped. The button still showing after
     *  MONK_SPIN_SETTLE is a missed tap: tried once more, still not counted. */
    private fun monkTap(texts: List<Text>, img: Frame): P? {
        monkClaim(texts)?.let { claim ->
            if (monkArmed != null) {
                monkSpins += 1
                monkArmed = null
                Log.info("Wise Monk: spin $monkSpins/${Config.MONK_SPINS} done")
            }
            monkLeaveSince = null
            monkSince = null
            monkRetapped = false
            Log.info("Wise Monk: claiming the reward")
            return claim
        }
        val spin = Screens.monkSpinButton(texts)
        val leave = find(texts, L.LEAVE, exact = true)
        if (spin != null && monkSpins < Config.MONK_SPINS) {
            monkLeaveSince = null
            val now = clock.now()
            if (monkArmed == null) {
                monkArmed = now
                monkSince = now
                monkRetapped = false
                Log.info("Wise Monk: spin ${monkSpins + 1}/${Config.MONK_SPINS}")
                return spin.center
            }
            if (!monkRetapped && now - monkArmed!! >= Config.MONK_SPIN_SETTLE) {
                monkRetapped = true
                monkArmed = now
                Log.info("Wise Monk: spin ${monkSpins + 1}/${Config.MONK_SPINS} was not claimed; tapping SPIN again")
                return spin.center
            }
            return monkWait(img, texts, "Wise Monk: waiting for the reward of spin ${monkSpins + 1}/${Config.MONK_SPINS}")
        }
        if (leave != null && monkArmed == null && monkSpins >= Config.MONK_SPINS) {
            monkSince = null
            return leave.center
        }
        if (leave != null && spin == null) {
            if (monkLeaveSince == null) monkLeaveSince = clock.now()
            if (clock.now() - monkLeaveSince!! >= Config.MONK_LEAVE_WAIT) {
                Log.info("Wise Monk: spin button did not return ($monkSpins/${Config.MONK_SPINS} claimed); leaving")
                monkArmed = null
                monkSince = null
                monkRetapped = false
                return leave.center
            }
            return monkWait(img, texts, "Wise Monk: waiting to spin again ($monkSpins/${Config.MONK_SPINS})")
        }
        if (monkArmed != null) {
            return monkWait(img, texts, "Wise Monk: waiting for the reward of spin ${monkSpins + 1}/${Config.MONK_SPINS}")
        }
        if (monkSpins >= Config.MONK_SPINS) return monkWait(img, texts, "Wise Monk: waiting to leave")
        return monkWait(img, texts, "Wise Monk: waiting to spin again ($monkSpins/${Config.MONK_SPINS})")
    }

    /** Buy wanted skills the coins can pay, refreshing while a refresh still leaves a wanted buy. */
    internal fun shop(texts0: List<Text>) {
        var texts = texts0
        var freeUsed = false
        val tapped = HashSet<String>()
        repeat(MAX_SHOP_STEPS) {
            val shop = Screens.parseShop(texts) ?: return
            val money = shop.money ?: return
            val cards = shop.cards.filter { !it.sold && it.cost != null && it.name !in tapped }
            val skills = cards.map(::skill)
            val preferred = Choice.shopOrder(skills, build, state, canReroll = true, fill = false)
            if (preferred != null && preferred.isNotEmpty()) {
                val affordable = preferred.filter { cards[it].cost!! <= money }
                if (affordable.isNotEmpty()) buy(shop, cards, skills, affordable[0], tapped)
                else if (!refreshShop(shop, preferred.map { cards[it].cost!! }, freeUsed)) return
                else freeUsed = freeUsed || shop.freeReroll != null
            } else if (refreshShop(shop, emptyList(), freeUsed)) {
                freeUsed = freeUsed || shop.freeReroll != null
            } else {
                val fallback = Choice.shopOrder(skills, build, state, canReroll = false, fill = false) ?: emptyList()
                val affordable = fallback.filter { cards[it].cost!! <= money }
                if (affordable.isEmpty()) return
                buy(shop, cards, skills, affordable[0], tapped)
            }
            texts = ocr.read(device.screenshot())
        }
    }

    private fun buy(shop: Screens.Shop, cards: List<Screens.SkillCard>, skills: List<Skill>, i: Int, tapped: MutableSet<String>) {
        Log.info("Shop: buying ${skills[i].name} for ${cards[i].cost} (coins ${shop.money})")
        device.tap(cards[i].price!!.center)
        tapped.add(cards[i].name)
        state.take(skills[i])
    }

    private fun refreshShop(shop: Screens.Shop, wantedCosts: List<Int>, freeUsed: Boolean): Boolean {
        val free = shop.freeReroll
        if (free != null && !freeUsed) {
            Log.info("Shop: no affordable wanted skill, free refresh")
            device.tap(free.center)
            return true
        }
        val cost = shop.rerollCost
        val money = shop.money
        val button = shop.reroll
        if (button == null || cost == null || money == null) return false
        if (!refreshLeavesABuy(money, cost, wantedCosts)) {
            Log.info("Shop: refresh ($cost) would leave too few coins (have $money)")
            return false
        }
        Log.info("Shop: refresh for $cost (coins $money)")
        device.tap(button.center)
        return true
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
