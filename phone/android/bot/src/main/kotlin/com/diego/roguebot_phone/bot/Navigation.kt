package com.diego.roguebot_phone.bot

import kotlin.math.abs

/** Port of roguebot/navigation.py: from anywhere in the main UI to the start of the requested level. */

open class NavigationError(msg: String) : RuntimeException(msg)
open class LevelUnavailable(msg: String) : NavigationError(msg)
class StarsUnavailable(msg: String) : LevelUnavailable(msg)
class EliteUnavailable(msg: String) : LevelUnavailable(msg)

/** Errors shown to the user by key (translated in the app), like emulator.EmulatorError. */
class BotError(val key: String, val args: Map<String, Any> = emptyMap()) : RuntimeException(key)

const val MAX_SCROLLS = 15
const val MAX_LOBBY_ATTEMPTS = 16
const val MAX_ENERGY_CLAIMS = 15
const val FEATURE_READS = 3
const val VIDEO_COOLDOWN_REREADS = 3
const val MAX_ENERGY_REOPENS = 2
const val LEVEL_LOAD_TIMEOUT = 20.0
const val START_RETAP_AFTER = 4.0
const val START_RETAPS = 2
const val LANGUAGE_ATTEMPTS = 3

private fun samePlace(a: Text, b: Text) = abs(a.center.x - b.center.x) < 20 && abs(a.center.y - b.center.y) < 20

internal fun stillThere(button: Text, texts: List<Text>) = texts.any {
    it.norm == button.norm && abs(it.center.x - button.center.x) < 40 && abs(it.center.y - button.center.y) < 40
}

open class Navigator(
    val device: Device,
    val ocr: Ocr,
    val dryRun: Boolean = false,
    val ads: Boolean = false,
    val clock: Clock = SystemClock,
    val debug: DebugSink = DebugSink { _, name -> name },
) {
    var resumeLevel: (() -> Any)? = null  // plays an interrupted run to its end

    // --- public API ---

    fun startLatest(mode: Mode): Int? {
        val lobby = setMode(mode)
        Log.info("Starting latest ${mode.value} level: ${lobby.levelTitle}")
        pressStart(lobby.startButton, mode)
        return parseLevelNumber(lobby.levelTitle ?: "")
    }

    fun startLastBeaten(mode: Mode): Int {
        val lobby = setMode(mode)
        val latest = parseLevelNumber(lobby.levelTitle ?: "")
        if (latest == null || latest < 2) fail("No beaten ${mode.value} level (lobby level: ${lobby.levelTitle})", device.screenshot(), ::StarsUnavailable)
        startStarChallenge(mode, latest - 1)
        return latest - 1
    }

    open fun startStarChallenge(mode: Mode, level: Int) {
        openStarList(mode)
        val card = scrollTo(level)
        Log.info("Starting ${mode.value} star challenge: ${card.header.text}")
        pressStart(card.button!!, mode)
    }

    fun startPendingStars(mode: Mode): Int? {
        openStarList(mode)
        var prev: List<Int>? = null
        repeat(MAX_SCROLLS) {
            val (img, texts) = capture()
            val cards = Screens.parseStarList(img, texts, ocr)
            val pending = cards.filter { it.button != null && it.stars < 3 }
            if (pending.isNotEmpty()) {
                var card = pending.maxBy { it.number }
                card = scrollTo(card.number)
                Log.info("Starting ${mode.value} star challenge for missing stars: ${card.header.text} (${card.stars}/3)")
                pressStart(card.button!!, mode)
                return card.number
            }
            val numbers = cards.map { it.number }
            if (numbers.isEmpty() || numbers == prev || numbers[0] == 1) {
                Log.info("Every beaten ${mode.value} level has 3 stars")
                return null
            }
            prev = numbers
            dragList(-Config.MAX_DRAG)
        }
        Log.info("Every beaten ${mode.value} level has 3 stars")
        return null
    }

    private fun openStarList(mode: Mode) {
        var lobby = setMode(mode)
        if (lobby.starsButton == null) lobby = lobbyUntil { it.starsButton != null }
        if (lobby.starsButton == null) fail("Desafio de Estrellas is not unlocked on this account", device.screenshot(), ::StarsUnavailable)
        tapText(lobby.starsButton!!)
        val (img, texts) = captureChange { Screens.isStarList(it) }
        if (!Screens.isStarList(texts)) fail("Desafio de Estrellas list did not open", img)
    }

    /** Just after opening the game (splash, loading, login popups): retry until the lobby shows. */
    fun waitForLobby(timeout: Double): Lobby {
        val deadline = clock.now() + timeout
        while (true) {
            try {
                return goToLobby()
            } catch (e: NavigationError) {
                if (clock.now() > deadline) throw BotError("err_game_load", mapOf("seconds" to timeout.toInt()))
            }
        }
    }

    fun detectLanguage(): String {
        L.setLanguage(null)
        var lang: String? = null
        var img: Frame? = null
        for (i in 0 until LANGUAGE_ATTEMPTS) {
            goToLobby()
            val c = capture()
            img = c.first
            lang = L.detectLanguage(c.second)
            if (lang != null) break
        }
        if (lang == null) fail("Could not detect the game language in the lobby", img!!)
        L.setLanguage(lang)
        Log.info("Game language: $lang")
        return lang
    }

    /** Open the energy popup and take every free option (Daily Pack, videos). Never the gem button. */
    fun claimFreeEnergy(): Int {
        goToLobby()
        device.tap(Config.ENERGY_ICON)
        var reopened = 0
        var rereads = 0
        var img: Frame? = null
        repeat(MAX_ENERGY_CLAIMS) {
            val c = capture()
            img = c.first
            val texts = c.second
            // The claimed energy shows over the popup and hides its video button and counter: claim it first.
            val reward = if (Screens.popupClose(texts) == null) find(texts, L.TAP_TO_CLAIM) else null
            if (reward != null) {
                tapText(reward)
                return@repeat
            }
            val offers = Screens.parseEnergyPopup(c.first, texts)
            if (offers == null) {
                val close = Screens.popupClose(texts)
                if (close != null) {
                    Log.info("Closing popup")
                    tapText(close)
                    if (reopened < MAX_ENERGY_REOPENS && Screens.parseLobby(capture().second) != null) {
                        device.tap(Config.ENERGY_ICON)
                        reopened++
                    }
                } else {
                    clock.sleep(Config.UI_SETTLE)
                }
                return@repeat
            }
            when {
                offers.freePack != null -> {
                    Log.info("Claiming free Daily Pack energy")
                    tapText(offers.freePack)
                }
                offers.video != null && ads -> {
                    Log.info("Watching a video for energy")
                    device.tap(offers.video, settle = Config.VIDEO_SETTLE)
                }
                offers.videosLeft > 0 && ads && rereads < VIDEO_COOLDOWN_REREADS -> {
                    if (rereads == 0) save(c.first, "energy_cooldown")
                    Log.info("Videos left (${offers.videosLeft}) but no video button yet, waiting")
                    rereads++
                    clock.sleep(Config.VIDEO_SETTLE)
                }
                offers.videosLeft > 0 && !ads -> {
                    Log.info("No free energy left to claim (videos are off)")
                    device.tap(Config.ENERGY_POPUP_CLOSE)
                    return goToLobby().energy ?: 0
                }
                else -> {
                    Log.info("No free energy left to claim (screenshot: ${save(c.first, "energy_none")})")
                    device.tap(Config.ENERGY_POPUP_CLOSE)
                    return goToLobby().energy ?: 0
                }
            }
        }
        fail("Energy popup did not settle", img!!)
    }

    // --- steps ---

    open fun goToLobby(): Lobby {
        var handTaps = 0
        var img: Frame? = null
        repeat(MAX_LOBBY_ATTEMPTS + Config.TUTORIAL_MAX_STEPS) {
            val c = capture()
            img = c.first
            val texts = c.second
            val hand = if (handTaps < Config.TUTORIAL_MAX_STEPS) Screens.tutorialHand(c.first) else null
            if (hand != null) {
                Log.info("Following the tutorial hand")
                device.tap(hand)
                handTaps++
                return@repeat
            }
            if (Screens.updateRequired(texts)) throw BotError("err_game_update")
            val resume = Screens.resumePrompt(texts)
            if (resume != null) {
                val play = resumeLevel ?: fail("An interrupted level is waiting to be resumed", c.first)
                Log.info("Resuming the interrupted level")
                tapText(resume)
                play()
                return@repeat
            }
            Screens.parseLobby(texts)?.let { return it }
            val closeText = Screens.popupClose(texts)
            val closeX by lazy { Screens.closeButton(c.first) }  // template matching: only when needed
            val back by lazy { ModeScreens.backArrow(c.first) }
            val end by lazy { endButton(c.first, texts) }
            when {
                Screens.isLoading(texts) -> clock.sleep(Config.UI_SETTLE)
                closeText != null -> { Log.info("Closing popup"); tapText(closeText) }
                closeX != null -> { Log.info("Closing popup (✕)"); device.tap(closeX!!) }
                // A level or mode fight ended and nothing took its result (a part that failed in it).
                end != null -> { Log.info("Leaving a result screen"); device.tap(end!!) }
                Screens.isStarList(texts) -> { Log.info("In star challenge list, going back"); device.tap(Config.LIST_BACK) }
                back != null -> { Log.info("In a menu, going back"); device.tap(back!!) }
                Screens.footerVisible(c.first) -> { Log.info("Not in Aventura lobby, tapping footer tab"); device.tap(Config.AVENTURA_TAB) }
                !leaveOtherApp() -> clock.sleep(Config.UI_SETTLE)  // loading or a screen we don't know: wait
            }
        }
        fail("Could not reach the Aventura lobby", img!!)
    }

    /** The button of a level end (VICTORIA/DERROTA + Continuar/Confirmar) or mode fight result screen. */
    fun endButton(img: Frame, texts: List<Text>): P? {
        val state = Screens.classifyLevelScreen(img, texts)
        if (state.kind == LevelScreen.VICTORY || state.kind == LevelScreen.DEFEAT) return state.tap
        return ModeScreens.parseFightResult(texts)?.button?.center
    }

    /** Another app is in front of the game (an ad for another app, or the page it opened): Back, bring the
     * game to the front; an ad that only closes by tapping it is tapped and left the same way. */
    fun leaveOtherApp(): Boolean {
        val pkg = device.foregroundPackage()
        if (pkg == null || pkg == Config.PACKAGE) return false
        Log.info("Another app is in front ($pkg), going back to the game")
        for (tapAd in listOf(false, true)) {
            if (tapAd) {
                Log.info("Tapping the ad to close it")
                device.tap(Config.OTHER_APP_AD_TAP, settle = Config.VIDEO_SETTLE)
            }
            repeat(Config.BROWSER_BACK_MAX) {
                if (device.foregroundPackage() == Config.PACKAGE) return true
                device.back()
            }
            device.launch(Config.PACKAGE)
            if (device.foregroundPackage() == Config.PACKAGE) return true
        }
        return true
    }

    private fun setMode(mode: Mode): Lobby {
        var lobby = lobbyUntil { it.mode == mode || it.hasElite }
        if (lobby.mode != mode && !lobby.hasElite) fail("Elite mode is not unlocked on this account", device.screenshot(), ::EliteUnavailable)
        if (lobby.mode != mode) {
            Log.info("Switching mode ${lobby.mode.value} -> ${mode.value}")
            device.tap(Config.ELITE_TOGGLE)
            val deadline = clock.now() + Config.CHANGE_TIMEOUT
            while (goToLobby().also { lobby = it }.mode != mode) {
                if (clock.now() > deadline) fail("Mode toggle did not switch to ${mode.value}", device.screenshot())
                clock.sleep(Config.POLL_INTERVAL)
            }
        }
        return lobby
    }

    internal fun lobbyUntil(ok: (Lobby) -> Boolean): Lobby {
        var lobby = goToLobby()
        for (i in 1 until FEATURE_READS) {
            if (ok(lobby)) break
            lobby = goToLobby()
        }
        return lobby
    }

    fun scrollTo(level: Int): Card {
        var prevNumbers: List<Int>? = null
        var prevTarget: Card? = null
        var img: Frame? = null
        repeat(MAX_SCROLLS) {
            val c = capture()
            img = c.first
            val cards = Screens.parseStarList(c.first, c.second, ocr)
            val numbers = cards.map { it.number }
            if (cards.isEmpty()) fail("No level cards recognized in the list", c.first)
            val target = cards.firstOrNull { it.number == level }
            if (target?.button != null) {
                if (prevTarget != null && samePlace(prevTarget!!.button!!, target.button)) return target
                prevTarget = target  // the list may still be gliding: only tap a button seen twice in place
                clock.sleep(Config.SCROLL_SETTLE)
                return@repeat
            }
            if (target != null && target.header.center.y < Config.LIST_BOTTOM - Config.HEADER_ABOVE_BUTTON) {
                fail("Level $level is locked", c.first, ::LevelUnavailable)
            }
            if (numbers == prevNumbers) fail("Level $level not found (list ends at ${numbers.last()})", c.first, ::LevelUnavailable)
            prevNumbers = numbers
            dragList(scrollDelta(cards, level))
        }
        fail("Level $level not reached after $MAX_SCROLLS scrolls", img!!)
    }

    private fun dragList(delta: Int) {
        val startY = if (delta > 0) Config.LIST_BOTTOM - 100 else Config.LIST_TOP + 100
        device.swipe(P(Config.SCROLL_X, startY), P(Config.SCROLL_X, startY - delta), duration = Config.SCROLL_DURATION)
    }

    fun pressStart(button0: Text, mode: Mode) {
        var button = button0
        if (mode == Mode.ELITE) {
            tapText(button)  // opens the "Modo Élite" dialog; nothing is spent yet
            button = setEliteCost()
            if (dryRun) {
                Log.info("[dry-run] would tap '${button.text}' at ${button.center}")
                device.tap(Config.ELITE_DIALOG_CLOSE)
                return
            }
        } else if (dryRun) {
            Log.info("[dry-run] would tap '${button.text}' at ${button.center}")
            return
        }
        tapText(button)
        var deadline = clock.now() + LEVEL_LOAD_TIMEOUT
        var lastTap = clock.now()
        var retaps = 0
        var img: Frame? = null
        while (clock.now() < deadline) {
            val c = capture()
            img = c.first
            if (Screens.classifyLevelScreen(c.first, c.second).kind != LevelScreen.UNKNOWN) {
                Log.info("Level started")
                return
            }
            if (stillThere(button, c.second) && retaps < START_RETAPS && clock.now() - lastTap > START_RETAP_AFTER) {
                Log.info("Start tap did not register, tapping again")
                tapText(button)
                lastTap = clock.now(); retaps++
                deadline = maxOf(deadline, lastTap + LEVEL_LOAD_TIMEOUT)
            }
            clock.sleep(1.0)
        }
        fail("Level did not start (no in-level screen detected)", img ?: device.screenshot())
    }

    internal fun setEliteCost(): Text {
        var (img, texts) = capture()
        val energy = Screens.parseEnergy(texts) ?: fail("Could not read the energy counter", img)
        val affordable = Config.ELITE_COSTS.filter { it <= energy }
        if (affordable.isEmpty()) fail("Not enough energy for an elite run ($energy)", img)
        val target = affordable.max()
        repeat(2 * Config.ELITE_COSTS.size) {
            val dialog = Screens.parseEliteDialog(texts) ?: fail("Elite dialog not recognized", img)
            if (dialog.cost == target) {
                Log.info("Elite cost set to $target (energy $energy)")
                return dialog.startButton
            }
            device.tap(if (dialog.cost < target) Config.ELITE_COST_PLUS else Config.ELITE_COST_MINUS)
            val c = captureChange { t -> Screens.parseEliteDialog(t).let { d -> d == null || d.cost != dialog.cost } }
            img = c.first; texts = c.second
        }
        fail("Could not set elite cost to $target", img)
    }

    // --- helpers ---

    open fun capture(): Pair<Frame, List<Text>> {
        val img = device.screenshot()
        return img to ocr.read(img)
    }

    fun captureChange(changed: (List<Text>) -> Boolean): Pair<Frame, List<Text>> {
        val deadline = clock.now() + Config.CHANGE_TIMEOUT
        while (true) {
            val c = capture()
            if (changed(c.second) || clock.now() > deadline) return c
            clock.sleep(Config.POLL_INTERVAL)
        }
    }

    fun tapText(t: Text) = device.tap(t.center)

    fun save(img: Frame, name: String): String = debug.save(img, name)

    fun fail(msg: String, img: Frame, error: (String) -> NavigationError = ::NavigationError): Nothing {
        throw error("$msg (screenshot: ${save(img, "fail")})")
    }

    companion object {
        /** Pixels to scroll (positive = down) to bring the level's header to TARGET_HEADER_Y. */
        fun scrollDelta(cards: List<Card>, level: Int): Int {
            val ref = cards.minBy { abs(it.number - level) }
            val targetY = ref.header.center.y + (level - ref.number) * Config.CARD_PITCH
            var delta = targetY - Config.TARGET_HEADER_Y
            if (abs(delta) < Config.MIN_DRAG) delta = if (delta >= 0) Config.MIN_DRAG else -Config.MIN_DRAG
            return delta.coerceIn(-Config.MAX_DRAG, Config.MAX_DRAG)
        }
    }
}
