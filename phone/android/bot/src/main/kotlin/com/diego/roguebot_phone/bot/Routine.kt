package com.diego.roguebot_phone.bot

import kotlin.math.abs

/**
 * Port of roguebot/routine.py: full routine (VIP cards, daily rewards, mail, the six modes, patrol,
 * guild raid and donation). A part that gets stuck is reported as failed and the next one runs.
 */
object Parts {
    val ALL = listOf("vip", "daily", "mail", "arena", "dojo", "tower", "dive", "mines", "pets", "patrol", "raid", "donate")
    val MODES = listOf("arena", "dojo", "tower", "dive", "mines", "pets")
    const val DONE = "done"
    const val SKIPPED = "skipped"
    const val FAILED = "failed"
}

const val MAX_BACK_STEPS = 8
const val LOBBY_RETRIES = 3
const val SCREEN_TIMEOUT = 20.0

open class Routine(
    val device: Device,
    val ocr: Ocr,
    val nav: Navigator,
    val ads: Boolean = false,
    val playLevel: (() -> LevelScreen)? = null,
    val clock: Clock = SystemClock,
) {
    var patrolWait: Double? = null  // set by patrol(): seconds until it is worth opening again

    fun runParts(): List<Pair<String, String>> {
        val steps = mapOf<String, () -> String>(
            "arena" to ::arena, "dojo" to ::dojo, "dive" to ::dive, "daily" to ::daily, "mail" to ::mail, "tower" to ::tower,
            "mines" to { dungeon(L.MINES) }, "pets" to { dungeon(L.PETS) }, "raid" to ::raid, "vip" to ::vip,
            "patrol" to ::patrol, "donate" to ::donate,
        )
        val results = ArrayList<Pair<String, String>>()
        for ((i, part) in Parts.ALL.withIndex()) {
            val following = Parts.ALL.getOrNull(i + 1)
            Log.info("Routine: $part")
            val status = try {
                steps.getValue(part)()
            } catch (e: NavigationError) {
                Log.error("Routine: $part failed: ${e.message}"); Parts.FAILED
            } catch (e: PlayError) {
                Log.error("Routine: $part failed: ${e.message}"); Parts.FAILED
            }
            results.add(part to status)
            if (!(part in Parts.MODES && following in Parts.MODES && backToModes())) {
                try {
                    nav.goToLobby()
                } catch (e: NavigationError) {
                    Log.error("Routine: could not get back to the lobby after $part: ${e.message}")
                }
            }
        }
        return results
    }

    // --- parts ---

    open fun arena(): String {
        if (!openMode(L.ARENA)) {
            Log.info("Arena: closed for now")
            return Parts.SKIPPED
        }
        repeat(Config.MAX_MODE_ACTIONS) {
            val screen = waitFor("arena screen") { img, texts -> claimOr(texts) { ModeScreens.parseArena(img, it, ocr) } }
            if (screen.tickets < 1) {
                Log.info("Arena: no tickets left")
                return Parts.DONE
            }
            tap(screen.challenge)
            var panel = waitFor("arena opponent list") { _, texts -> claimOr(texts, ModeScreens::parseArenaOpponents) }
            var choice = ModeScreens.pickOpponent(panel.ownPower, panel.opponents)
            if (choice == null && panel.freeRefresh != null) {
                Log.info("Arena: every opponent is stronger, using the free refresh")
                tap(panel.freeRefresh!!)
                clock.sleep(Config.UI_SETTLE)
                panel = waitFor("arena opponent list") { _, texts -> claimOr(texts, ModeScreens::parseArenaOpponents) }
                choice = ModeScreens.pickOpponent(panel.ownPower, panel.opponents)
            }
            if (choice == null) {
                if (panel.opponents.isEmpty()) fail("No arena opponents recognized")
                choice = panel.opponents.minBy { it.power }
            }
            Log.info("Arena: power ${panel.ownPower} vs ${choice.power} (${screen.tickets} tickets)")
            tap(choice.challenge!!)
            fight()
        }
        fail("Arena did not run out of tickets")
    }

    open fun tower(): String {
        openMode(L.TOWER)
        repeat(Config.MAX_MODE_ACTIONS) {
            val screen = waitFor("tower screen") { _, texts -> claimOr(texts, ::towerOrChest) }
            if (screen.tickets < 1) {
                Log.info("Tower: no tickets left")
                return Parts.DONE
            }
            tap(screen.challenge)
            if (!fight().victory) return Parts.DONE
        }
        fail("Tower did not finish")
    }

    open fun dungeon(label: Label): String {
        openMode(label)
        val name = label.variants[0]
        var lost = false
        repeat(Config.MAX_MODE_ACTIONS) {
            val popup = waitFor("dungeon popup") { _, texts -> claimOr(texts, ModeScreens::parseDungeonPopup) }
            when {
                popup.tickets < 1 -> {
                    if (popup.ad == null || !ads) {
                        Log.info("$name: no tickets left")
                        return Parts.DONE
                    }
                    Log.info("$name: watching an ad for a ticket")
                    device.tap(popup.ad.center, settle = Config.VIDEO_SETTLE)
                }
                lost -> {
                    val sweep = popup.sweep ?: fail("Sweep button not found")
                    Log.info("$name: sweeping the previous stage (${popup.tickets} tickets)")
                    tap(sweep)
                }
                else -> {
                    val challenge = popup.challenge ?: fail("Challenge button not found")
                    Log.info("$name: challenging difficulty ${popup.difficulty}")
                    tap(challenge)
                    lost = !fight().victory
                }
            }
        }
        fail("Dungeon did not run out of tickets")
    }

    open fun dojo(): String {
        if (!openMode(L.DOJO)) {
            Log.info("Dojo: closed for now")
            return Parts.SKIPPED
        }
        repeat(Config.MAX_MODE_ACTIONS) {
            val screen = waitFor("dojo screen") { img, texts -> claimOr(texts) { ModeScreens.parseDojo(img, it, ocr) } }
            when {
                screen.chest != null -> {
                    Log.info("Dojo: claiming the progress chest")
                    tap(screen.chest)
                    clock.sleep(Config.UI_SETTLE)
                }
                screen.tickets < 1 || screen.challenge == null -> {
                    Log.info("Dojo: no tickets left")
                    return Parts.DONE
                }
                else -> {
                    Log.info("Dojo: challenge (${screen.tickets} tickets)")
                    tap(screen.challenge)
                    fight()
                }
            }
        }
        fail("Dojo did not run out of tickets")
    }

    open fun dive(): String {
        if (!openMode(L.DIVE)) {
            Log.info("Dungeon Dive: closed for now")
            return Parts.SKIPPED
        }
        repeat(Config.MAX_MODE_ACTIONS) {
            val screen = waitFor("dungeon dive screen") { _, texts -> claimOr(texts, ModeScreens::parseDive) }
            if (screen.tickets < 1) {
                Log.info("Dungeon Dive: no tickets left")
                return Parts.DONE
            }
            Log.info("Dungeon Dive: challenge (${screen.tickets} tickets)")
            tap(screen.challenge)
            Log.info("Dungeon Dive finished: ${playLevel!!().value}")
        }
        fail("Dungeon Dive did not run out of tickets")
    }

    open fun daily(): String {
        if (!openMenu(L.MENU_DAILY)) return Parts.SKIPPED
        tap(waitFor("daily rewards popup") { _, texts -> ModeScreens.dailyClaim(texts) })
        try {
            val claim = waitFor("daily reward web page") { _, texts -> find(texts, L.DAILY_WEB_CLAIM) }
            Log.info("Daily rewards: claiming on the web page")
            tap(claim)
            clock.sleep(Config.VIDEO_SETTLE)
        } finally {
            backToGame()
        }
        return Parts.DONE
    }

    open fun mail(): String {
        if (!openMenu(L.MENU_MAIL)) return Parts.SKIPPED
        tap(waitFor("mail popup") { _, texts -> ModeScreens.mailClaimAll(texts) })
        Log.info("Mail: claim all")
        clock.sleep(Config.UI_SETTLE)
        waitFor("mail popup") { _, texts -> claimOr(texts, ModeScreens::mailClaimAll) }
        return Parts.DONE
    }

    open fun raid(): String {
        val texts = lobbyTexts()
        if (!ModeScreens.inGuild(texts)) {
            Log.info("Not in a guild, skipping the raid")
            return Parts.SKIPPED
        }
        device.tap(Config.GUILD_BUTTON)
        tap(waitFor("guild map") { _, t -> find(t, L.RAID_BOSS) })
        repeat(Config.MAX_MODE_ACTIONS) {
            val screen = waitFor("raid screen") { _, t -> ModeScreens.parseRaid(t) }
            if (screen.attempts < 1) {
                Log.info("Raid: no attempts left")
                return Parts.DONE
            }
            Log.info("Raid: ${screen.attempts} attempts left")
            tap(screen.challenge)
            fight()
        }
        fail("Raid did not run out of attempts")
    }

    open fun patrol(): String {
        val texts = lobbyTexts()
        val button = find(texts, L.PATROL) ?: fail("Patrol button not found in the lobby")
        tap(button)
        var popup = waitFor("patrol popup") { _, t -> claimOr(t, ModeScreens::parsePatrol) }
        patrolWait = popup.elapsed?.let { maxOf(0, Config.PATROL_CLAIM_AFTER - it).toDouble() }
        val elapsed = popup.elapsed
        if (elapsed != null && elapsed >= Config.PATROL_CLAIM_AFTER) {
            Log.info("Patrol: claiming the reward (${elapsed / 3600}:${"%02d".format(elapsed % 3600 / 60)})")
            tap(popup.claim)
            patrolWait = Config.PATROL_CLAIM_AFTER.toDouble()
            clock.sleep(Config.UI_SETTLE)
            popup = waitFor("patrol popup") { _, t -> claimOr(t, ModeScreens::parsePatrol) }
        } else {
            Log.info("Patrol: not claiming yet (counter ${elapsed?.let { "${it / 3600}:${"%02d".format(it % 3600 / 60)}" } ?: "unreadable"})")
        }
        tap(popup.quick)
        repeat(Config.MAX_MODE_ACTIONS) {
            val (quick, energy) = waitFor("quick patrol popup") { img, t ->
                claimOr(t) { tt -> ModeScreens.parseQuickPatrol(img, tt)?.let { it to (Screens.parseEnergy(tt) ?: 0) } }
            }
            when {
                quick.video != null && ads -> {
                    Log.info("Patrol: quick patrol with a free video")
                    tap(quick.video)
                    clock.sleep(Config.VIDEO_SETTLE)
                }
                quick.energy != null && energy >= quick.energyCost -> {
                    Log.info("Patrol: quick patrol for ${quick.energyCost} energy ($energy)")
                    tap(quick.energy)
                    clock.sleep(Config.UI_SETTLE)
                }
                else -> {
                    Log.info("Patrol: no free quick patrol left")
                    return Parts.DONE
                }
            }
        }
        fail("Quick patrol did not run out")
    }

    open fun donate(): String {
        val texts = lobbyTexts()
        if (!ModeScreens.inGuild(texts)) {
            Log.info("Not in a guild, skipping the donation")
            return Parts.SKIPPED
        }
        device.tap(Config.GUILD_BUTTON)
        tap(waitFor("guild map") { _, t -> find(t, L.GUILD_HALL) })
        tap(waitFor("guild hall") { _, t -> ModeScreens.guildHallDonate(t) })
        waitFor("donation popup") { _, t -> find(t, L.DONATION_TITLE) }
        repeat(Config.DONATE_FREE_MAX) {
            val t = waitFor("donation popup") { _, tt -> claimOr(tt) { x -> if (find(x, L.DONATION_TITLE) != null) x else null } }
            val free = ModeScreens.freeDonation(t)
            if (free == null) {
                Log.info("Guild donation: no free donation left")
                return Parts.DONE
            }
            Log.info("Guild donation: free donation")
            tap(free)
            waitChange { x -> ModeScreens.freeDonation(x) == null }  // never decide on a stale "Gratis" frame
        }
        return Parts.DONE
    }

    open fun vip(): String {
        val texts = lobbyTexts()
        val icon = ModeScreens.vipCardsIcon(texts)
        if (icon == null) {
            Log.info("No VIP cards icon in the lobby, skipping")
            return Parts.SKIPPED
        }
        tap(icon)
        tap(waitFor("VIP cards screen") { _, t -> ModeScreens.vipClaimAll(t) })
        Log.info("VIP cards: claim all")
        clock.sleep(Config.UI_SETTLE)
        waitFor("VIP cards screen") { _, t -> claimOr(t, ModeScreens::vipClaimAll) }
        return Parts.DONE
    }

    // --- steps ---

    internal open fun openMode(label: Label): Boolean {
        var texts = capture().second
        if (!ModeScreens.isModesList(texts)) {
            nav.goToLobby()
            device.tap(Config.MODES_BUTTON)
            texts = waitFor("modes list") { _, t -> if (ModeScreens.isModesList(t)) t else null }
        }
        var scrolled = false
        for (i in 0 until Config.MODES_MAX_SCROLLS) {
            if (find(texts, L.ARENA, exact = true) != null) break
            Log.info("Modes list scrolled down, scrolling to the top")
            device.swipe(Config.MODES_SCROLL_UP.first, Config.MODES_SCROLL_UP.second, duration = Config.SCROLL_DURATION)
            texts = capture().second
            scrolled = true
        }
        var entry = ModeScreens.modeEntry(texts, label)
        while (scrolled && entry != null) {  // inertia: only tap a card seen twice in the same place
            texts = capture().second
            val again = ModeScreens.modeEntry(texts, label)
            scrolled = !(again != null && abs(again.center.y - entry.center.y) < 20)
            entry = again
        }
        if (entry == null) fail("${label.variants[0]} not found in the modes list")
        if (ModeScreens.modeClosed(texts, entry)) return false
        tap(entry)
        return true
    }

    private fun openMenu(label: Label): Boolean {
        lobbyTexts()
        device.tap(Config.MENU_BUTTON)
        val deadline = clock.now() + SCREEN_TIMEOUT
        while (clock.now() < deadline) {
            val texts = capture().second
            if (ModeScreens.menuEntry(texts, L.MENU_MAIL) != null) {
                val entry = ModeScreens.menuEntry(texts, label)
                if (entry != null) {
                    tap(entry)
                    return true
                }
                break
            }
            clock.sleep(Config.POLL_INTERVAL)
        }
        Log.info("No ${label.variants[0]} in the lobby menu, skipping")
        return false
    }

    private fun backToGame() {
        repeat(Config.BROWSER_BACK_MAX) {
            if (device.foregroundPackage() == Config.PACKAGE) return
            device.back()
        }
        // The phone may not go back to the game from the browser: bring it to the front.
        device.launch(Config.PACKAGE)
        if (device.foregroundPackage() != Config.PACKAGE) fail("Could not get back to the game from the browser")
    }

    internal open fun backToModes(): Boolean {
        repeat(MAX_BACK_STEPS) {
            val (img, texts) = capture()
            if (ModeScreens.isModesList(texts)) return true
            val closeText = Screens.popupClose(texts)
            when {
                closeText != null -> tap(closeText)
                else -> {
                    val closeX = Screens.closeButton(img)
                    val back = if (closeX == null) ModeScreens.backArrow(img) else null
                    when {
                        closeX != null -> device.tap(closeX)
                        back != null -> device.tap(back)
                        else -> clock.sleep(Config.UI_SETTLE)
                    }
                }
            }
        }
        Log.info("Could not get back to the modes list")
        return false
    }

    /** Wait out a mode/raid fight, picking skills (highest rarity). Never taps "Skip" (paid VIP offer). */
    internal fun fight(): ModeScreens.FightResult {
        val deadline = clock.now() + Config.MODE_FIGHT_TIMEOUT
        var img: Frame? = null
        while (clock.now() < deadline) {
            val c = capture()
            img = c.first
            val result = ModeScreens.parseFightResult(c.second)
            if (result != null) {
                Log.info("Fight finished: ${if (result.victory) "victory" else "defeat"}")
                tap(result.button)
                return result
            }
            val choice = ModeScreens.parseSkillChoice(c.second)
            when {
                choice != null && choice.chosen < choice.needed -> {
                    if (choice.chosen >= choice.cards.size) fail("Skill cards not recognized", c.first)
                    device.tap(choice.cards[choice.chosen])
                }
                choice != null -> tap(choice.learn)
                else -> clock.sleep(Config.POLL_INTERVAL)
            }
        }
        fail("Fight did not finish", img)
    }

    private fun towerOrChest(texts: List<Text>): ModeScreens.TowerScreen? {
        if (find(texts, L.TOWER_CLEARED) != null) {
            Log.info("Tower cleared: opening the reward chest")
            device.tap(Config.TOWER_CHEST)
            return null
        }
        return ModeScreens.parseTower(texts)
    }

    /** Tap away reward popups and popups that close by text; otherwise parse the screen. */
    private fun <T> claimOr(texts: List<Text>, parse: (List<Text>) -> T?): T? {
        val away = find(texts, L.TAP_TO_CLAIM) ?: Screens.popupClose(texts)
        if (away != null) {
            tap(away)
            return null
        }
        return parse(texts)
    }

    private fun lobbyTexts(): List<Text> {
        var texts: List<Text> = emptyList()
        repeat(LOBBY_RETRIES) {
            nav.goToLobby()
            texts = capture().second
            if (Screens.parseLobby(texts) != null) return texts
        }
        return texts
    }

    private fun waitChange(changed: (List<Text>) -> Boolean) {
        val deadline = clock.now() + Config.CHANGE_TIMEOUT
        while (!changed(capture().second) && clock.now() < deadline) clock.sleep(Config.POLL_INTERVAL)
    }

    private fun <T> waitFor(what: String, parse: (Frame, List<Text>) -> T?): T {
        val deadline = clock.now() + SCREEN_TIMEOUT
        var img: Frame? = null
        while (clock.now() < deadline) {
            val c = capture()
            img = c.first
            parse(c.first, c.second)?.let { return it }
            clock.sleep(Config.POLL_INTERVAL)
        }
        fail("Expected the $what", img)
    }

    private fun capture(): Pair<Frame, List<Text>> = nav.capture()

    private fun tap(t: Text) = device.tap(t.center)

    private fun fail(msg: String, img: Frame? = null): Nothing = nav.fail(msg, img ?: device.screenshot())
}
