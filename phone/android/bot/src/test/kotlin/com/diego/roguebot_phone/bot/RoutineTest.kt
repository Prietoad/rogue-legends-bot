package com.diego.roguebot_phone.bot

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import kotlin.math.abs

/** Port of tests/test_routine.py: the full routine with scripted screens (no device). */
class RoutineTest {
    @Before
    fun setUp() {
        Fixtures.loadTemplates()
        L.setLanguage("en")
    }

    @After
    fun reset() = L.setLanguage(null)

    private val clock = FakeClock()
    private val device = FakeDevice()

    private fun nav(script: Script, ocr: Ocr = FakeOcr(), ads: Boolean = false) = ScriptNav(device, script, ocr, clock, ads)

    private fun make(vararg screens: List<Text>, ads: Boolean = false, ocr: Ocr = FakeOcr()): Routine =
        Routine(device, ocr, nav(Script.texts(*screens), ocr, ads), ads, clock = clock)

    private fun Routine.navigator() = nav as ScriptNav

    private fun assertNear(want: P, got: P) =
        assertTrue("want $want got $got", abs(want.x - got.x) <= 4 && abs(want.y - got.y) <= 4)

    private fun c(t: Text) = t.center

    @Test
    fun failedPartIsReportedAndTheNextOneRuns() {
        val ran = ArrayList<String>()
        val n = nav(Script.texts(MODES_TOP))
        val r = object : Routine(device, FakeOcr(), n, clock = clock) {
            override fun arena(): String = throw NavigationError("stuck")
            override fun tower(): String = Parts.DONE.also { ran.add("ok") }
            override fun dungeon(label: Label) = Parts.DONE
            override fun raid() = Parts.SKIPPED
            override fun vip() = Parts.DONE
            override fun donate() = Parts.DONE
            override fun patrol() = Parts.DONE
            override fun daily() = Parts.DONE
            override fun mail() = Parts.DONE
            override fun dojo() = Parts.DONE
            override fun dive() = Parts.DONE
        }
        val results = r.runParts()
        assertEquals(listOf("vip" to "done", "daily" to "done", "mail" to "done", "arena" to "failed", "dojo" to "done",
            "tower" to "done", "dive" to "done", "mines" to "done", "pets" to "done", "patrol" to "done", "raid" to "skipped",
            "donate" to "done"), results)
        assertEquals(listOf("ok"), ran)
        assertEquals(7, n.lobbyVisits)  // stays in the modes tab between modes
    }

    private fun skillScreen(chosen: Int, needed: Int, rarities: List<String>): List<Text> =
        listOf(t("Select a Skill to learn!", 400, 560, 1040, 600)) +
            rarities.mapIndexed { i, r -> t(r, 280, 740 + 306 * i, 360, 770 + 306 * i) } +
            t("Learn Skills ($chosen/$needed)", 700, 2130, 1080, 2170)

    @Test
    fun fightPicksBestSkillsThenLearnsThenWaitsForResult() {
        val rarities = listOf("Common", "Legendary", "Common", "Mythic")
        val r = make(skillScreen(0, 2, rarities), skillScreen(1, 2, rarities), skillScreen(2, 2, rarities),
            listOf(t("Round: 1/10", 600, 170, 840, 210)), listOf(t("DEFEAT", 600, 880, 840, 940), t("OK", 680, 2300, 760, 2350)))
        assertFalse(r.fight().victory)
        val mythicY = 755 + 306 * 3 + 90
        val legendaryY = 755 + 306 + 90
        assertEquals(listOf(P(800, mythicY), P(800, legendaryY), P(890, 2150), P(720, 2325)), device.taps)
    }

    @Test
    fun fightNeverTapsSkip() {
        val fight = listOf(t("VS", 700, 120, 740, 160), t("Skip", 860, 2400, 980, 2450))
        val r = make(fight, fight, listOf(t("VICTORY!", 600, 1060, 840, 1110), t("OK", 680, 2090, 760, 2140)))
        assertTrue(r.fight().victory)
        assertEquals(listOf(P(720, 2115)), device.taps)
    }

    private fun dungeon(tickets: Int, ad: Boolean = false, buttons: Boolean = true): List<Text> {
        val texts = mutableListOf(t("Crystal Mines", 560, 450, 880, 500), t("18", 680, 1110, 760, 1200),
            t("Difficulty", 620, 1225, 800, 1270), t("$tickets/2", 700, 1695, 790, 1735))
        if (ad) texts.add(t("Dungeon Tickets x1", 540, 1790, 900, 1835))
        if (buttons) texts += listOf(t("Sweep previous", 340, 1800, 650, 1840), t("Challenge", 820, 1825, 1066, 1870))
        return texts
    }

    private fun noOpenMode(r: Routine.() -> Unit = {}, script: Script, ads: Boolean = false, ocr: Ocr = FakeOcr(),
                           play: (() -> LevelScreen)? = null): Routine {
        val n = nav(script, ocr, ads)
        return object : Routine(device, ocr, n, ads, play, clock) {
            override fun openMode(label: Label) = true
        }.apply(r)
    }

    @Test
    fun dungeonChallengesThenSweepsAfterDefeatAndWatchesAds() {
        val r = noOpenMode(script = Script.texts(dungeon(1), LOADING, DEFEAT, dungeon(1), CLAIM, dungeon(0, ad = true, buttons = false), CLAIM,
            dungeon(1), CLAIM, dungeon(0)), ads = true)
        assertEquals(Parts.DONE, r.dungeon(L.MINES))
        val challenge = P(943, 1847); val sweep = P(495, 1820); val ad = P(720, 1812); val cont = P(717, 2330); val claim = P(720, 2322)
        assertEquals(listOf(challenge, cont, sweep, claim, ad, claim, sweep, claim), device.taps)
    }

    @Test
    fun withoutAdsDungeonTicketsAreSkipped() {
        val r = noOpenMode(script = Script.texts(dungeon(0, ad = true, buttons = false)))
        assertEquals(Parts.DONE, r.dungeon(L.MINES))
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun openModeScrollsTheModesListToTheTop() {
        val r = make(MODES_SCROLLED, MODES_SCROLLED, MODES_TOP, MODES_TOP)
        r.openMode(L.ARENA)
        assertEquals(2, device.swipes.size)
        assertTrue(device.swipes.all { it.second.y > it.first.y })  // finger drags down = list goes up
        assertEquals(P(1305, 265), device.taps.last())
    }

    @Test
    fun openModeAtTheTopDoesNotScrollNorVisitTheLobby() {
        val r = make(MODES_TOP)
        r.openMode(L.TOWER)
        assertEquals(0, device.swipes.size)
        assertEquals(listOf(P(1150, 1045)), device.taps)
        assertEquals(0, r.navigator().lobbyVisits)
    }

    @Test
    fun openModeWaitsForTheListToStopAfterScrolling() {
        val moving = listOf(t("Arena", 1250, 140, 1360, 190), t("Tower Challenge", 1000, 920, 1300, 970))
        val r = make(MODES_SCROLLED, moving, MODES_TOP, MODES_TOP)
        r.openMode(L.TOWER)
        assertEquals(P(1150, 1045), device.taps.last())
    }

    @Test
    fun backToModesUsesCloseXThenBackArrow() {
        val popup = Canvas().paste(template("close_x.png"), 720, 2098).paste(template("back_arrow.png"), 120, 2447).frame
        val arena = Canvas().paste(template("back_arrow.png"), 120, 2447).frame
        val r = Routine(device, FakeOcr(), nav(Script(listOf(popup to MINES_POPUP, arena to ARENA_SCREEN, Script.BLANK to MODES_TOP))), clock = clock)
        assertTrue(r.backToModes())
        assertEquals(2, device.taps.size)
        assertNear(P(720, 2098), device.taps[0])  // the popup's ✕, not the arrow behind it
        assertNear(P(120, 2447), device.taps[1])
    }

    @Test
    fun backToModesGivesUp() {
        val r = make(listOf(t("Loading.", 600, 1260, 760, 1310)))
        assertFalse(r.backToModes())
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun towerOpensTheClearedTowerChest() {
        val tower = listOf(t("Tower of Heroes 16", 560, 245, 880, 290), t("11/10", 800, 65, 905, 100), t("Challenge", 620, 2395, 820, 2440))
        val congrats = listOf(t("Tower of Heroes 15", 560, 435, 880, 480), t("Congratulations on clearing", 480, 685, 960, 720))
        val r = noOpenMode(script = Script.texts(congrats, congrats + CLAIM, tower, LOADING, DEFEAT, tower))
        assertEquals(Parts.DONE, r.tower())
        assertEquals(listOf(Config.TOWER_CHEST, P(720, 2322), P(720, 2417)), device.taps.take(3))
    }

    @Test
    fun closedArenaIsSkippedWithoutTapping() {
        val r = make(MODES_TOP + t("Opens in 4m", 980, 320, 1130, 360))
        assertEquals(Parts.SKIPPED, r.arena())
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun arenaClosesAPopupOverTheArenaScreen() {
        L.setLanguage("es")
        val popup = listOf(t("Felicidades por tu ascenso!", 400, 920, 1040, 970), t("Toca en cualquier lugar para cerrar", 440, 2440, 1000, 2480))
        val arena = listOf(t("Arena", 280, 60, 400, 120), t("Desafiar", 620, 2395, 820, 2440))
        val ocr = FakeOcr { _, region -> if (region == Config.ARENA_TICKETS_REGION) listOf(t("0", 850, 60, 900, 110)) else emptyList() }
        val r = noOpenMode(script = Script.texts(popup, arena), ocr = ocr)
        assertEquals(Parts.DONE, r.arena())
        assertEquals(listOf(P(720, 2460)), device.taps)  // the popup's close text, not Challenge
    }

    @Test
    fun vipTapsOnlyClaimAllAndClaimsTheReward() {
        L.setLanguage("es")
        val r = make(VIP_LOBBY, VIP_SCREEN, CLAIM_ES, VIP_SCREEN)
        assertEquals(Parts.DONE, r.vip())
        assertEquals(listOf(P(80, 660), P(720, 2445), P(720, 2320)), device.taps)
    }

    @Test
    fun vipSkippedWithoutTheIcon() {
        L.setLanguage("es")
        val r = make(ES_LOBBY)
        assertEquals(Parts.SKIPPED, r.vip())
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun lobbyPartsReadTheLobbyAgainWhenTheGameOpensAScreen() {
        L.setLanguage("es")
        val album = listOf(t("Fondo del Álbum", 60, 260, 640, 310), t("Reclamar todo", 1100, 2420, 1400, 2470))
        val r = make(album, VIP_LOBBY, VIP_SCREEN, VIP_SCREEN)
        assertEquals(Parts.DONE, r.vip())
        assertTrue(r.navigator().lobbyVisits >= 2)
        assertEquals(P(80, 660), device.taps[0])
    }

    @Test
    fun donateOnlyTheFreeDonation() {
        L.setLanguage("es")
        val r = make(GUILD_LOBBY, GUILD_MAP, GUILD_HALL, DONATION_FREE, DONATION_FREE, CLAIM_ES, CLAIM_ES, DONATION_PAID)
        assertEquals(Parts.DONE, r.donate())
        assertEquals(listOf(Config.GUILD_BUTTON, P(740, 995), P(720, 2247), P(720, 1607), P(720, 2320)), device.taps)
    }

    @Test
    fun aStaleFreeDonationFrameIsNeverTappedAgain() {
        L.setLanguage("es")
        val r = make(GUILD_LOBBY, GUILD_MAP, GUILD_HALL, DONATION_FREE, DONATION_FREE, DONATION_FREE, DONATION_FREE, CLAIM_ES,
            CLAIM_ES, DONATION_PAID)
        assertEquals(Parts.DONE, r.donate())
        assertEquals(1, device.taps.count { it == P(720, 1607) })
    }

    @Test
    fun donateSkippedOutsideAGuild() {
        L.setLanguage("es")
        val r = make(ES_LOBBY)
        assertEquals(Parts.SKIPPED, r.donate())
        assertEquals(emptyList<P>(), device.taps)
    }

    private fun quick(freeLeft: Int, energyLeft: Int, energy: String = "20/34"): Pair<Frame, List<Text>> =
        Canvas().lightning(980, 1475).frame to listOf(t(energy, 800, 65, 905, 100),
            t("Reclama de inmediato las recompensas de 2 h:", 330, 920, 1110, 965),
            t("Gratis", 470, 1450, 590, 1495), t("x10", 950, 1450, 1010, 1500),
            t("Cantidad restante: $freeLeft", 340, 1575, 650, 1615), t("Cantidad restante: $energyLeft", 790, 1575, 1100, 1615))

    private fun s(texts: List<Text>) = Script.BLANK to texts

    @Test
    fun patrolClaimsThenUsesEveryQuickPatrol() {
        L.setLanguage("es")
        val r = Routine(device, FakeOcr(), nav(Script(listOf(s(ES_LOBBY), s(PATROL), s(CLAIM_ES), s(PATROL), quick(1, 1), s(CLAIM_ES),
            quick(0, 1), quick(0, 0))), ads = true), ads = true, clock = clock)
        assertEquals(Parts.DONE, r.patrol())
        assertEquals(Config.PATROL_CLAIM_AFTER.toDouble(), r.patrolWait!!, 0.0)
        assertEquals(listOf(P(720, 1922), P(945, 1775), P(720, 2320), P(495, 1775), P(530, 1472), P(720, 2320), P(980, 1475)), device.taps)
    }

    @Test
    fun quickPatrolWithEnergyNeedsEnoughEnergy() {
        L.setLanguage("es")
        val r = Routine(device, FakeOcr(), nav(Script(listOf(s(ES_LOBBY), s(PATROL), s(PATROL), quick(0, 2, energy = "7/34")))), clock = clock)
        assertEquals(Parts.DONE, r.patrol())
        assertFalse(P(980, 1475) in device.taps)
    }

    @Test
    fun patrolRewardIsOnlyClaimedNearThe8HourCap() {
        L.setLanguage("es")
        val early = listOf(t("Tiempo de patrulla: 7:49:59", 560, 1025, 960, 1070)) + PATROL.drop(1)
        val r = Routine(device, FakeOcr(), nav(Script(listOf(s(ES_LOBBY), s(early), quick(0, 0)))), clock = clock)
        assertEquals(Parts.DONE, r.patrol())
        assertEquals(listOf(P(720, 1922), P(495, 1775)), device.taps)
        assertEquals(1.0, r.patrolWait!!, 0.0)
    }

    @Test
    fun withoutAdsQuickPatrolVideosAreSkipped() {
        L.setLanguage("es")
        val early = listOf(t("Tiempo de patrulla: 1:00:00", 560, 1025, 960, 1070)) + PATROL.drop(1)
        val r = Routine(device, FakeOcr(), nav(Script(listOf(s(ES_LOBBY), s(early), quick(1, 0)))), clock = clock)
        assertEquals(Parts.DONE, r.patrol())
        assertEquals(listOf(P(720, 1922), P(495, 1775)), device.taps)
    }

    @Test
    fun aStuckLobbyBetweenPartsDoesNotAbortTheRoutine() {
        val n = nav(Script.texts()).apply { lobbyError = NavigationError("Could not reach the Aventura lobby") }
        val r = object : Routine(device, FakeOcr(), n, clock = clock) {
            override fun arena() = Parts.DONE
            override fun tower() = Parts.DONE
            override fun dungeon(label: Label) = Parts.DONE
            override fun raid() = Parts.DONE
            override fun vip() = Parts.DONE
            override fun donate() = Parts.DONE
            override fun patrol() = Parts.DONE
            override fun daily() = Parts.DONE
            override fun mail() = Parts.DONE
            override fun dojo() = Parts.DONE
            override fun dive() = Parts.DONE
            override fun backToModes() = true
        }
        val results = r.runParts()
        assertEquals(Parts.ALL, results.map { it.first })
        assertTrue(results.all { it.second == Parts.DONE })
    }

    // --- tower "Próximo piso", re-tapped challenges, build skill picks, resume after a recovery ---

    private fun tower(tickets: Int) = listOf(t("Tower of Heroes 16", 560, 245, 880, 290), t("$tickets/10", 800, 65, 905, 100),
        t("Challenge", 620, 2395, 820, 2440))

    private fun towerWin(nextFloor: Boolean = true) = listOf(t("VICTORY!", 600, 1000, 840, 1055), t("Confirm", 290, 1925, 640, 2005)) +
        if (nextFloor) listOf(t("Next Floor", 760, 1925, 1190, 2005)) else emptyList()

    @Test
    fun towerGoesOnWithNextFloorWhileAnotherTicketIsLeft() {
        val r = noOpenMode(script = Script.texts(tower(3), LOADING, towerWin(), LOADING, towerWin(), LOADING, towerWin(), tower(0)))
        assertEquals(Parts.DONE, r.tower())
        val challenge = P(720, 2417); val confirm = P(465, 1965); val next = P(975, 1965)
        assertEquals(listOf(challenge, next, next, confirm), device.taps)  // the last ticket's win is confirmed
    }

    @Test
    fun towerNextFloorThenDefeatEndsTheTower() {
        val r = noOpenMode(script = Script.texts(tower(5), LOADING, towerWin(), LOADING, DEFEAT))
        assertEquals(Parts.DONE, r.tower())
        assertEquals(listOf(P(720, 2417), P(975, 1965), P(717, 2330)), device.taps)
    }

    @Test
    fun towerWinWithoutNextFloorReadsTheTowerScreenAgain() {
        val r = noOpenMode(script = Script.texts(tower(2), LOADING, towerWin(nextFloor = false), tower(1), LOADING, DEFEAT))
        assertEquals(Parts.DONE, r.tower())
        assertEquals(listOf(P(720, 2417), P(465, 1965), P(720, 2417), P(717, 2330)), device.taps)
    }

    @Test
    fun pressTapsAgainWhenTheTapDidNotRegister() {
        val r = make(*(List(40) { tower(2) } + listOf(LOADING)).toTypedArray())  // still there for 2 rounds, then gone
        r.press(t("Challenge", 620, 2395, 820, 2440))
        assertEquals(List(3) { P(720, 2417) }, device.taps)
    }

    @Test
    fun pressDoesNotTapAgainOnceTheNextScreenShows() {
        val panel = tower(2) + t("Arena Challenge", 500, 300, 900, 350)  // the button stays visible under it
        val r = make(panel)
        r.press(t("Challenge", 620, 2395, 820, 2440)) { texts -> texts.any { it.text == "Arena Challenge" } }
        assertEquals(listOf(P(720, 2417)), device.taps)
    }

    private fun namedSkillScreen(chosen: Int, needed: Int, cards: List<Triple<String, String, String>>): List<Text> {
        val texts = mutableListOf(t("Select a Skill to learn!", 400, 560, 1040, 600))
        cards.forEachIndexed { i, (rarity, name, desc) ->
            val y = 755 + 306 * i
            texts += listOf(t(rarity, 280, y - 15, 360, y + 15), t(name, 465, y + 20, 900, y + 60), t(desc, 465, y + 90, 1000, y + 130))
        }
        return texts + t("Learn Skills ($chosen/$needed)", 700, 2130, 1080, 2170)
    }

    @Test
    fun dojoAndRaidSkillPicksFollowTheBuild() {
        val cards = listOf(Triple("Mythic", "Super Flash", "At the start of combat, Stun all enemies."),
            Triple("Common", "Fire Ball", "Every 2 rounds, cast a Fireball."),
            Triple("Legendary", "Glass Cannon", "ATK up, Max HP down."),
            Triple("Common", "Ice Shard", "Every 2 rounds, cast an Icicle."))
        val n = nav(Script.texts(namedSkillScreen(0, 2, cards), namedSkillScreen(1, 2, cards), namedSkillScreen(2, 2, cards),
            listOf(t("DEFEAT", 600, 880, 840, 940), t("OK", 680, 2300, 760, 2350))))
        val catalog = Catalog(null)
        val r = Routine(device, FakeOcr(), n, clock = clock, build = Build(Skills.MAGIC, listOf("fire", "ice", "lightning", "shuriken", "venom", "bleed")),
            catalog = catalog)
        r.fight()
        assertEquals(listOf(P(800, 755 + 306 + 90), P(800, 755 + 306 * 3 + 90)), device.taps.take(2))  // magic, fire first
        assertTrue(catalog.lookup("Fire Ball", "", "common", "en").damageType == "fire")
    }

    private open inner class AllDone(n: Navigator) : Routine(device, FakeOcr(), n, clock = clock) {
        val calls = ArrayList<String>()
        private fun done(part: String) = Parts.DONE.also { calls.add(part) }
        override fun arena() = done("arena")
        override fun tower() = done("tower")
        override fun dungeon(label: Label) = done(if (label == L.MINES) "mines" else "pets")
        override fun raid() = done("raid")
        override fun vip() = done("vip")
        override fun donate() = done("donate")
        override fun patrol() = done("patrol")
        override fun daily() = done("daily")
        override fun mail() = done("mail")
        override fun dojo() = done("dojo")
        override fun dive() = done("dive")
        override fun backToModes() = true
    }

    @Test
    fun runPartsResumesAfterARecoveryAtThePartThatBroke() {
        var broken = true
        val r = object : AllDone(nav(Script.texts(MODES_TOP))) {
            override fun tower(): String = if (broken) throw IllegalStateException("frozen") else super.tower()
        }
        val progress = RoutineProgress()
        assertThrows(IllegalStateException::class.java) { r.runParts(progress) }
        assertEquals("dojo" to "done", progress.parts.last())
        broken = false
        r.calls.clear()
        val results = r.runParts(progress)
        assertEquals(listOf("tower", "dive", "mines", "pets", "patrol", "raid", "donate"), r.calls)
        assertEquals(Parts.ALL, results.map { it.first })
    }

    @Test
    fun aPartThatKeepsBreakingTheRunIsMarkedFailed() {
        val r = object : AllDone(nav(Script.texts(MODES_TOP))) {
            override fun tower(): String = throw IllegalStateException("frozen")
        }
        val progress = RoutineProgress()
        repeat(PART_RESTARTS + 1) { assertThrows(IllegalStateException::class.java) { r.runParts(progress) } }
        r.runParts(progress)
        assertTrue("tower" to "failed" in progress.parts)
        assertEquals(Parts.ALL, progress.parts.map { it.first })
    }

    @Test
    fun aFailedPartLeftStuckRaisesAndTheRoutineResumesAtTheNextPart() {
        val n = nav(Script.texts()).apply { lobbyError = NavigationError("Could not reach the Aventura lobby") }
        val r = object : AllDone(n) {
            override fun arena(): String = throw NavigationError("Expected the arena screen")
            override fun backToModes() = false
        }
        val progress = RoutineProgress()
        assertThrows(StuckError::class.java) { r.runParts(progress) }
        assertEquals("arena" to "failed", progress.parts.last())
        n.lobbyError = null
        assertEquals(Parts.ALL, r.runParts(progress).map { it.first })
    }

    // --- Dojo Battle, Dungeon Dive, daily rewards, mail ---

    private fun dojo(tickets: Int, chest: Boolean = false): List<Text> = listOf(
        t("Batalla de Dojo", 500, 150, 940, 200), t("tickets", 1300, 60, 1400, 110),
        when {
            chest -> t("RECLAMAR", 275, 2127, 502, 2170)
            tickets > 0 -> t("Desafío", 620, 2390, 820, 2440)
            else -> t("Se actualiza en:", 560, 2390, 880, 2440)
        })

    @Test
    fun dojoFightsWhileThereAreTicketsAndClaimsTheChest() {
        L.setLanguage("es")
        val victory = listOf(t("VICTORIA", 600, 1000, 830, 1055), t("Confirmar", 534, 2280, 905, 2367))
        val counts = listOf(2, 1, 0, 0)
        val frames = counts.map { Frame(1, 1, IntArray(1)) }  // distinct frames: each one has its own ticket count
        val ocr = FakeOcr { img, _ -> listOf(t(counts[frames.indexOf(img)].toString(), 1300, 60, 1340, 110)) }
        val script = Script(listOf(frames[0] to dojo(2), s(LOADING), s(victory), frames[1] to dojo(1), s(LOADING), s(victory),
            frames[2] to dojo(0, chest = true), s(CLAIM_ES), frames[3] to dojo(0)))
        val r = noOpenMode(script = script, ocr = ocr)
        assertEquals(Parts.DONE, r.dojo())
        val challenge = P(720, 2415); val confirm = P(719, 2323); val chest = P(388, 2148)
        assertEquals(listOf(challenge, confirm, challenge, confirm, chest, P(720, 2320)), device.taps)
    }

    @Test
    fun dojoWithoutTicketsTapsNothing() {
        L.setLanguage("es")
        val ocr = FakeOcr { _, _ -> listOf(t("0", 1300, 60, 1340, 110)) }
        val r = noOpenMode(script = Script.texts(dojo(0)), ocr = ocr)
        assertEquals(Parts.DONE, r.dojo())
        assertEquals(emptyList<P>(), device.taps)
    }

    private fun dive(tickets: Int) = listOf(t("$tickets/2", 800, 65, 905, 100), t("Recompensas", 600, 470, 830, 515),
        t("Desafío", 620, 2390, 820, 2440))

    @Test
    fun divePlaysALevelPerTicketWinOrLose() {
        L.setLanguage("es")
        val results = ArrayDeque(listOf(LevelScreen.DEFEAT, LevelScreen.VICTORY))
        val r = noOpenMode(script = Script.texts(dive(2), LOADING, dive(1), LOADING, dive(0)), play = { results.removeFirst() })
        assertEquals(Parts.DONE, r.dive())
        assertEquals(listOf(P(720, 2415), P(720, 2415)), device.taps)
    }

    @Test
    fun dailyRewardsClaimsOnTheWebPageAndGoesBackToTheGame() {
        L.setLanguage("es")
        val r = make(ES_LOBBY, ES_MENU, DAILY_POPUP, WEB_PAGE)
        device.apps.addAll(listOf("com.android.chrome", "com.android.chrome"))
        assertEquals(Parts.DONE, r.daily())
        assertEquals(listOf(Config.MENU_BUTTON, P(397, 1084), P(696, 1178), P(989, 1415)), device.taps)
        assertEquals(listOf("back", "back"), device.actions)
    }

    @Test
    fun dailyRewardsGoesBackToTheGameEvenWithoutTheWebClaim() {
        L.setLanguage("es")
        val login = listOf(t("roguelegend.io", 220, 130, 390, 170), t("Iniciar sesión", 500, 1200, 900, 1260))
        val r = make(ES_LOBBY, ES_MENU, DAILY_POPUP, login)
        device.apps.add("com.android.chrome")
        assertThrows(NavigationError::class.java) { r.daily() }
        assertEquals(listOf("back"), device.actions)
        assertFalse(P(989, 1415) in device.taps)
    }

    @Test
    fun dailyRewardsLaunchesTheGameWhenBackDoesNotReturnToIt() {
        L.setLanguage("es")
        val r = make(ES_LOBBY, ES_MENU, DAILY_POPUP, WEB_PAGE)
        device.apps.addAll(List(Config.BROWSER_BACK_MAX) { "com.android.chrome" })
        assertEquals(Parts.DONE, r.daily())
        assertEquals(List(Config.BROWSER_BACK_MAX) { "back" } + "launch", device.actions)
    }

    @Test
    fun menuEntryMissingSkipsThePart() {
        L.setLanguage("es")
        val r = make(ES_LOBBY, ES_MENU.dropLast(2))
        assertEquals(Parts.SKIPPED, r.daily())
        assertEquals(listOf(Config.MENU_BUTTON), device.taps)
    }

    @Test
    fun mailClaimsAllAndNeverDeletes() {
        L.setLanguage("es")
        val r = make(ES_LOBBY, ES_MENU, MAIL, CLAIM_ES, MAIL)
        assertEquals(Parts.DONE, r.mail())
        assertEquals(listOf(Config.MENU_BUTTON, P(398, 473), P(942, 1847), P(720, 2320)), device.taps)
    }

    companion object {
        val CLAIM = listOf(t("Tap anywhere to claim", 480, 2300, 960, 2345))
        val LOADING = listOf(t("Loading...", 600, 1260, 840, 1300))  // right after a Challenge tap registered
        val DEFEAT = listOf(t("DEFEAT", 600, 1000, 830, 1055), t("Tap to Continue", 560, 2310, 875, 2350))
        val MODES_TOP = listOf(t("Arena", 1250, 240, 1360, 290), t("Tower Challenge", 1000, 1020, 1300, 1070))
        val MODES_SCROLLED = listOf(t("Tower Challenge", 1000, 410, 1300, 455), t("Pet Kingdom", 1080, 1605, 1330, 1650))
        val ARENA_SCREEN = listOf(t("Arena", 280, 60, 400, 120), t("Challenge", 620, 2390, 820, 2440))
        val MINES_POPUP = listOf(t("Crystal Mines", 560, 450, 880, 500), t("Difficulty", 620, 1225, 800, 1270),
            t("Arena", 1250, 240, 1360, 290), t("Tower Challenge", 1000, 1020, 1300, 1070))
        val ES_LOBBY = listOf(t("Patrulla", 650, 1900, 790, 1945), t("APAGADO", 880, 2060, 990, 2095),
            t("INICIO", 600, 2070, 716, 2115), t("de Estrellas", 840, 1910, 960, 1945))
        val VIP_LOBBY = ES_LOBBY + listOf(t("Tarjetas", 20, 640, 140, 680), t("VIP", 50, 705, 110, 740))
        val VIP_SCREEN = listOf(t("$6,99", 1130, 2080, 1280, 2130), t("Reclamar todo", 560, 2420, 880, 2470))
        val CLAIM_ES = listOf(t("Toca en cualquier lugar para reclamar", 400, 2300, 1040, 2340))
        val GUILD_LOBBY = ES_LOBBY + t("Gremio", 40, 2160, 140, 2200)
        val GUILD_MAP = listOf(t("Sala de", 680, 970, 800, 1020), t("Gremio", 680, 1030, 800, 1075))
        val GUILD_HALL = listOf(t("Registro", 260, 2225, 430, 2275), t("Donar", 650, 2225, 790, 2270))
        val DONATION_FREE = GUILD_HALL + listOf(t("Donación de Gremio", 520, 715, 920, 760), t("Gratis", 650, 1585, 790, 1630))
        val DONATION_PAID = GUILD_HALL + listOf(t("Donación de Gremio", 520, 715, 920, 760), t("25", 740, 1590, 790, 1630))
        val PATROL = listOf(t("Tiempo de patrulla: 7:51:30", 560, 1025, 960, 1070), t("Patrulla Rápida", 330, 1750, 660, 1800),
            t("Reclamar", 860, 1750, 1030, 1800), t("Tarjeta Mensual VIP", 300, 2240, 770, 2285))
        val ES_MENU = ES_LOBBY + listOf(t("Correo", 336, 449, 461, 498), t("Recompensas", 320, 1040, 480, 1070),
            t("Diarias", 349, 1068, 446, 1100))
        val DAILY_POPUP = listOf(t("Recompensas Diarias", 420, 880, 1020, 935), t("Reclamar", 551, 1138, 842, 1218),
            t("Introducir Código", 470, 1360, 970, 1430))
        val WEB_PAGE = listOf(t("roguelegend.io", 220, 130, 390, 170), t("TIENDA", 780, 310, 890, 350),
            t("Reclamar ahora!", 824, 1392, 1154, 1438))
        val MAIL = listOf(t("Correo", 600, 470, 840, 525), t("Recompensa diaria", 450, 670, 820, 710),
            t("Eliminar todo", 300, 1815, 690, 1880), t("Reclamar todo", 736, 1815, 1149, 1880))
    }
}
