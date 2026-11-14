package com.diego.roguebot_phone.bot

import kotlin.math.abs

/** Port of roguebot/play.py: in-level loop (roll dice, fights, skills, events) until the level ends. */

class PlayError(msg: String) : RuntimeException(msg)

const val MAX_SHOP_STEPS = 12

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
    private var seenOffer: Int? = null  // cards read on the last skill pick frame (they fly in: decide on a settled frame)
    private var offerFrames = 0         // frames in a row whose card count differed from the frame before
    internal var minerDone: Set<Int> = emptySet()  // treasure miner: tiles of treasures already dug out whole
    private var minerLeft: Int? = null             // its "Tesoros Restantes" on the last frame
    private var speedTapped = false
    private var speedLocked = false
    private var autoHeld = false
    private var autoMissing = false
    private var autoSeen = false  // auto-play worked in this level: a hold that brings the red dice back was missed
    private var autoMisses = 0    // such missed holds in a row
    private var fortuneBought = ArrayList<Int>()  // Fortune Teller balls bought this visit (chances)
    private var fortuneTap: Triple<Int, Int, Double>? = null  // (chance, orbs before, time) of the last ball tap

    /** Play until the level ends; returns VICTORY or DEFEAT. */
    fun playLevel(): LevelScreen {
        var lastKnown = clock.now()
        var lastTap: Pair<LevelScreen, P>? = null
        var repeats = 0
        var firstRepeat = clock.now()
        var waiting: LevelScreen? = null  // the screen kind being waited on, and for how many frames
        var waitingFrames = 0
        state = BuildState(); rerolled = false; doubles = 0; lastOffer = null
        fortuneBought = ArrayList(); fortuneTap = null
        while (true) {
            val img = device.screenshot()
            val texts = ocr.read(img)
            var s = classify(img, texts)

            if (s.kind == LevelScreen.SKILL_PICK) {
                s = LevelState(s.kind, if (offerSettled(texts)) pickSkill(texts) ?: s.tap else null)
            } else if (s.kind == LevelScreen.PATH_CHOICE) {
                s = LevelState(s.kind, path(img, texts))
            } else if (s.kind == LevelScreen.EVENT) {
                s = LevelState(s.kind, event(img, texts) ?: s.tap)
            } else if (s.kind == LevelScreen.MINER) {
                s = LevelState(s.kind, miner(img, texts))
            } else if (s.kind == LevelScreen.CONTRACT) {
                s = LevelState(s.kind, contract(texts))
            } else if (s.kind == LevelScreen.SHOP) {
                shop(texts)
            } else if (s.kind == LevelScreen.FORTUNE_TELLER) {
                s = LevelState(s.kind, fortune(texts))
            } else if (s.kind == LevelScreen.BOARD_READY || s.kind == LevelScreen.AUTO_PLAY) {
                fortuneBought.clear()  // back on the board: a later Fortune Teller is a new visit
                minerDone = emptySet(); minerLeft = null
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

            if (s.kind == LevelScreen.VICTORY || s.kind == LevelScreen.DEFEAT) {
                Log.info("Level finished: ${s.kind.value}")
                device.tap(s.tap!!)
                return s.kind
            }

            waitingFrames = if (s.kind == waiting) waitingFrames + 1 else 0
            waiting = s.kind
            if (s.tap == null && s.kind != LevelScreen.UNKNOWN && s.kind != LevelScreen.FIGHT && waitingFrames > Config.WAIT_SCREEN_FRAMES) {
                fail("Waiting on ${s.kind.value} for too long", img)  // auto-play never lasts this long without a fight or an event
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

    /** The skill cards fly in one by one: a frame taken meanwhile once showed a single card and the reroll
     *  was wasted on it. True once two frames in a row show the same number of cards (or after
     *  SKILL_PICK_SETTLE_FRAMES changing frames). */
    internal fun offerSettled(texts: List<Text>): Boolean {
        val cards = Screens.parseSkillCards(texts).size
        if (cards > 0 && cards != seenOffer && offerFrames < Config.SKILL_PICK_SETTLE_FRAMES) {
            seenOffer = cards; offerFrames++
            return false
        }
        seenOffer = null; offerFrames = 0
        return true
    }

    /** Board fork: the path the strategy wants (the shop while the coins are worth it). */
    internal fun path(img: Frame, texts: List<Text>): P {
        val paths = Screens.parsePaths(texts, img)
        val coins = Screens.parseMoney(texts)
        val i = Strategy.choosePath(paths.map { it.shop }, coins)
        Log.info("Fork: ${paths.joinToString(" / ") { it.label.text + if (it.shop) " = shop" else "" }} (coins $coins) -> ${paths[i].label.text}")
        return paths[i].label.center
    }

    /** Tile event: the option the strategy wants, or null when it has no rule for this event. */
    internal fun event(img: Frame, texts: List<Text>): P? {
        val options = Screens.eventOptions(img, texts)
        val hp = Screens.parseHp(texts)
        val i = Strategy.chooseEvent(options.map { it.norm }, hp) ?: return null
        Log.info("Event: ${options.joinToString(" / ") { it.text }} (HP ${hp?.let { "${Math.round(it * 100)}%" } ?: "?"}) -> ${options[i].text}")
        return Screens.eventTap(options[i])
    }

    /** Cursed vendor: sign the contract the strategy rates best. */
    internal fun contract(texts: List<Text>): P {
        val contracts = Screens.parseContracts(texts)
        val i = Strategy.chooseContract(contracts.map { it.terms })
        Log.info("Cursed vendor: ${contracts.joinToString(" | ") { it.terms }} -> signing ${i + 1}")
        return contracts[i].button.center
    }

    /** Treasure miner: the tile to dig. A drop of "Tesoros Restantes" means the treasure pieces on screen
     *  are dug out whole: they are not followed any more. */
    internal fun miner(img: Frame, texts: List<Text>): P? {
        val tiles = Screens.minerTiles(img)
        val left = Screens.treasuresLeft(texts)
        val before = minerLeft
        if (left != null && before != null && left < before) minerDone = tiles.indices.filter { tiles[it] == Screens.TREASURE }.toSet()
        minerLeft = left ?: minerLeft
        val i = Strategy.minerDig(tiles, minerDone) ?: return null
        return Screens.minerTile(i / Config.MINER_SIZE, i % Config.MINER_SIZE)
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

    /** Stat items first (heal when hurt, then the cheap stat boost), a free reroll if no skill is wanted,
     *  then skills in the build's order whatever the coins allow. */
    internal fun shop(texts0: List<Text>) {
        var texts = texts0
        var rerolledShop = false
        val tapped = HashSet<String>()
        var itemBuy: Int? = null  // coins before the stat item just tapped
        var itemsDone = false
        repeat(MAX_SHOP_STEPS) {
            val shop = Screens.parseShop(texts) ?: return
            val money = shop.money ?: return
            if (itemBuy != null && money >= itemBuy!!) itemsDone = true  // the coins did not drop: sold out or a missed tap
            val item = if (itemsDone) null else Strategy.shopItem(shop.items.mapValues { it.value.norm.toInt() }, money, Screens.parseHp(texts))
            if (item != null) {
                Log.info("Shop: buying $item for ${shop.items.getValue(item).norm} (coins $money)")
                device.tap(shop.items.getValue(item).center)
                itemBuy = money
                texts = ocr.read(device.screenshot())
                return@repeat
            }
            itemBuy = null
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
