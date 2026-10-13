package com.diego.roguebot_phone.bot

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import kotlin.math.abs

/** Port of the navigation and level-play tests of tests/test_logic.py and tests/test_skill_screens.py. */
class NavigationTest {
    @Before
    fun setUp() = Fixtures.loadTemplates()

    @After
    fun reset() = L.setLanguage(null)

    private val clock = FakeClock()

    /** A real Navigator (its own go_to_lobby) whose captures follow the script. */
    private fun nav(device: Device, script: Script, ads: Boolean = false) = ScriptNav(device, script, FakeOcr(), clock, ads, real = true)

    private fun near(want: P, got: P) = assertTrue("want $want got $got", abs(want.x - got.x) <= 4 && abs(want.y - got.y) <= 4)

    @Test
    fun scrollDelta() {
        fun card(n: Int, y: Int) = Card(n, t("$n. Level", 40, y - 25, 600, y + 25), null)
        assertEquals(-1100, Navigator.scrollDelta(listOf(card(11, 700), card(12, 1267)), 2))
        assertEquals(150, Navigator.scrollDelta(listOf(card(7, 750)), 7))
        assertEquals(567, Navigator.scrollDelta(listOf(card(5, 700)), 6))
    }

    /** Every reading of the time is 5 s later: the start button has been there "long enough" at once. */
    private val fast = object : Clock {
        var t = 0.0
        override fun now(): Double { t += 5; return t }
        override fun sleep(seconds: Double) {}
    }

    @Test
    fun startTapIsRepeatedWhenItDidNotRegister() {
        L.setLanguage("es")
        val device = FakeDevice()
        ScriptNav(device, Script.texts(LOBBY, LOADING, IN_LEVEL), clock = fast, real = true).pressStart(START, Mode.NORMAL)
        assertEquals(listOf(START.center, START.center), device.taps)  // first tap + one retap; loading = registered
    }

    @Test
    fun startTapIsRetriedAtMostTwice() {
        L.setLanguage("es")
        val device = FakeDevice()
        ScriptNav(device, Script.texts(LOBBY, LOBBY, LOBBY, LOBBY, IN_LEVEL), clock = fast, real = true).pressStart(START, Mode.NORMAL)
        assertEquals(1 + START_RETAPS, device.taps.size)
    }

    @Test
    fun goToLobbyPrefersTheBackArrowOverTheFooter() {
        val towerFrame = Canvas().footer().paste(template("back_arrow.png"), 120, 2447).frame
        val tower = listOf(t("Tower of Heroes 16", 560, 245, 880, 290), t("Challenge", 620, 2395, 820, 2440))
        val device = FakeDevice()
        nav(device, Script(listOf(towerFrame to tower, Script.BLANK to ES_LOBBY))).goToLobby()
        assertEquals(1, device.taps.size)
        near(P(120, 2447), device.taps[0])
    }

    @Test
    fun goToLobbyTapsTheFooterOnAMainScreen() {
        val device = FakeDevice()
        nav(device, Script(listOf(Canvas().footer().frame to listOf(t("Héroes", 600, 300, 800, 350)), Script.BLANK to ES_LOBBY))).goToLobby()
        assertEquals(listOf(Config.AVENTURA_TAB), device.taps)
    }

    @Test
    fun detectLanguageRetriesWhenTheGameLeavesTheLobby() {
        val arrow = Canvas().paste(template("back_arrow.png"), 120, 2447).frame
        val event = listOf(t("Evento de Pesca", 60, 60, 370, 100), t("Viaje de Pesca", 540, 1660, 900, 1710))
        val device = FakeDevice()
        val n = nav(device, Script(listOf(Script.BLANK to ES_LOBBY, arrow to event, arrow to event, Script.BLANK to ES_LOBBY, Script.BLANK to ES_LOBBY)))
        assertEquals("es", n.detectLanguage())
        assertEquals(1, device.taps.size)
        near(P(120, 2447), device.taps[0])
    }

    @Test
    fun goToLobbyClosesALongPopupChain() {
        val popup = ES_LOBBY + t("Toca en cualquier lugar para cerrar", 440, 2340, 1000, 2380)
        val device = FakeDevice()
        nav(device, Script.texts(*Array(10) { popup }, ES_LOBBY)).goToLobby()
        assertEquals(10, device.taps.size)
    }

    @Test
    fun goToLobbyFollowsTheTutorialHand() {
        val hand = Canvas().paste(template("tutorial_hand.png"), 700 - Config.TUTORIAL_TAP_OFFSET.x, 1200 - Config.TUTORIAL_TAP_OFFSET.y).frame
        val arrow = Canvas().paste(template("back_arrow.png"), 120, 2447).frame
        val album = listOf(t("Completa todos los conjuntos para elegir:", 400, 530, 1040, 575))
        val device = FakeDevice()
        nav(device, Script(listOf(hand to ES_LOBBY, arrow to album, Script.BLANK to ES_LOBBY))).goToLobby()
        assertEquals(2, device.taps.size)
        near(P(700, 1200), device.taps[0])   // the hand's button
        near(P(120, 2447), device.taps[1])   // then back out of the album
    }

    @Test
    fun goToLobbyResumesAnInterruptedLevel() {
        L.setLanguage("en")
        val device = FakeDevice()
        val played = ArrayList<String>()
        val n = nav(device, Script.texts(RESUME, EN_LOBBY))
        n.resumeLevel = { played.add("level") }
        n.goToLobby()
        assertEquals(listOf(P(890, 1417)), device.taps)
        assertEquals(listOf("level"), played)
    }

    @Test
    fun goToLobbyWithoutAPlayerStopsAtTheResumePrompt() {
        L.setLanguage("en")
        val device = FakeDevice()
        assertThrows(NavigationError::class.java) { nav(device, Script.texts(RESUME)).goToLobby() }
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun goToLobbyStopsWhenTheGameNeedsAnUpdate() {
        val device = FakeDevice()
        val e = assertThrows(BotError::class.java) {
            nav(device, Script.texts(listOf(t("Nueva Actualización", 520, 900, 920, 950), t("ACTUALIZAR", 600, 1360, 840, 1410)))).goToLobby()
        }
        assertEquals("err_game_update", e.key)
        assertEquals(emptyList<P>(), device.taps)
    }

    /** The game is in front again after `backs` Back presses, `launches` launches or a tap on the ad. */
    private class OtherAppDevice(val backs: Int? = null, val launches: Int? = null, val adTap: Boolean = false) : FakeDevice() {
        private fun game() = actions.count { it == "back" } == backs || actions.count { it == "launch" } == launches || (adTap && taps.isNotEmpty())
        override fun foregroundPackage() = if (game()) Config.PACKAGE else "com.other.ad"
    }

    private val ad = listOf(t("Install now", 600, 1500, 840, 1550))

    @Test
    fun goToLobbyLeavesAnotherAppWithBack() {
        val device = OtherAppDevice(backs = 1)
        nav(device, Script.texts(ad, ES_LOBBY)).goToLobby()
        assertEquals(listOf("back"), device.actions)
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun goToLobbyBringsTheGameBackWhenBackDoesNothing() {
        val device = OtherAppDevice(launches = 1)
        nav(device, Script.texts(ad, ES_LOBBY)).goToLobby()
        assertEquals(List(Config.BROWSER_BACK_MAX) { "back" } + "launch", device.actions)
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun goToLobbyTapsAnAdThatOnlyClosesByTappingIt() {
        val device = OtherAppDevice(adTap = true)
        nav(device, Script.texts(ad, ES_LOBBY)).goToLobby()
        assertEquals(listOf(Config.OTHER_APP_AD_TAP), device.taps)
        assertEquals(List(Config.BROWSER_BACK_MAX) { "back" } + "launch", device.actions)
    }

    @Test
    fun goToLobbyWaitsOnAnUnknownGameScreen() {
        val device = FakeDevice()
        nav(device, Script.texts(ad, ES_LOBBY)).goToLobby()
        assertEquals(emptyList<String>(), device.actions)
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun energyClaimClosesALatePromoAndReopensTheEnergyPopup() {
        L.setLanguage("es")
        val promo = listOf(t("Oferta limitada!", 600, 850, 840, 890), t("Toca en cualquier lugar para cerrar", 440, 2440, 1000, 2480))
        val lobby = ES_LOBBY + t("3/32", 820, 70, 890, 100)
        val popup = listOf(t("Comprar", 660, 745, 780, 785), t("Intentos Restantes Hoy:", 330, 1255, 650, 1290), t("0", 480, 1295, 500, 1330))
        val device = FakeDevice()
        assertEquals(3, nav(device, Script.texts(lobby, promo, lobby, popup, lobby)).claimFreeEnergy())
        assertEquals(listOf(Config.ENERGY_ICON, P(720, 2460), Config.ENERGY_ICON, Config.ENERGY_POPUP_CLOSE), device.taps)
    }

    @Test
    fun energyVideosAreWatchedOnlyWithAds() {
        L.setLanguage("es")
        val lobby = ES_LOBBY + t("20/32", 820, 70, 890, 100)
        // The yellow video button under "Intentos Restantes Hoy: 2".
        val popup = Canvas().fill(370, 1340, 610, 1410, 250, 200, 30).frame to listOf(t("Comprar", 660, 745, 780, 785),
            t("Intentos Restantes Hoy: 2", 330, 1255, 650, 1290))
        val noVideos = Script.BLANK to listOf(t("Comprar", 660, 745, 780, 785), t("Intentos Restantes Hoy: 0", 330, 1255, 650, 1290))
        val withAds = FakeDevice()
        assertEquals(20, nav(withAds, Script(listOf(Script.BLANK to lobby, popup, noVideos, Script.BLANK to lobby)), ads = true).claimFreeEnergy())
        assertEquals(listOf(Config.ENERGY_ICON, P(490, 1375), Config.ENERGY_POPUP_CLOSE), withAds.taps)
        val noAds = FakeDevice()
        assertEquals(20, nav(noAds, Script(listOf(Script.BLANK to lobby, popup, Script.BLANK to lobby))).claimFreeEnergy())
        assertEquals(listOf(Config.ENERGY_ICON, Config.ENERGY_POPUP_CLOSE), noAds.taps)  // the video left alone
    }

    @Test
    fun eliteCostWaitsForTheNewCostBeforePressingAgain() {
        L.setLanguage("es")
        fun dialog(cost: Int) = listOf(t("Modo Élite", 560, 600, 880, 650), t("INICIO", 600, 1880, 840, 1930),
            t("x$cost", 690, 1960, 750, 2000), t("12/32", 820, 70, 890, 100))
        val device = FakeDevice()
        nav(device, Script.texts(dialog(5), dialog(5), dialog(10))).setEliteCost()
        assertEquals(listOf(Config.ELITE_COST_PLUS), device.taps)
    }

    @Test
    fun lobbyWithoutEliteOrStarChallengeIsStillTheLobby() {
        L.setLanguage("es")
        val lobby = Screens.parseLobby(BARE_LOBBY)!!
        assertEquals(Mode.NORMAL, lobby.mode)
        assertTrue(!lobby.hasElite && lobby.starsButton == null && lobby.energy == 20)
    }

    @Test
    fun missingEliteOrStarChallengeRaiseTheirOwnErrors() {
        L.setLanguage("es")
        val device = FakeDevice()
        val n = nav(device, Script.texts(BARE_LOBBY))
        assertThrows(EliteUnavailable::class.java) { n.startLatest(Mode.ELITE) }
        assertThrows(StarsUnavailable::class.java) { n.startStarChallenge(Mode.NORMAL, 3) }
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun lastBeatenIsTheLevelBeforeTheLobbyLevel() {
        L.setLanguage("es")
        val started = ArrayList<Int>()
        val n = object : Navigator(FakeDevice(), FakeOcr(), clock = clock) {
            override fun capture() = Script.BLANK to (ES_LOBBY + t("13. Bosque Embrujado II", 480, 560, 960, 600))
            override fun startStarChallenge(mode: Mode, level: Int) { started.add(level) }
        }
        assertEquals(12, n.startLastBeaten(Mode.NORMAL))
        assertEquals(listOf(12), started)
        val first = object : Navigator(FakeDevice(), FakeOcr(), clock = clock) {
            override fun capture() = Script.BLANK to (ES_LOBBY + t("1. Bosque", 480, 560, 960, 600))
        }
        assertThrows(LevelUnavailable::class.java) { first.startLastBeaten(Mode.NORMAL) }
    }

    // --- level play ---

    private fun play(kinds: List<LevelState>, texts: List<Text> = emptyList(), ads: Boolean = false): List<Pair<String, P>> {
        val states = ArrayDeque(kinds)
        val actions = ArrayList<Pair<String, P>>()
        val device = object : FakeDevice() {
            override fun tap(p: P, settle: Double) { actions.add("tap" to p) }
            override fun hold(p: P, seconds: Double, settle: Double) { actions.add("hold" to p) }
        }
        val ocr = object : Ocr { override fun read(img: Frame, region: Region?) = texts }
        Player(device, ocr, ads = ads, clock = clock, classify = { _, _ -> states.removeFirst() }).playLevel()
        return actions
    }

    private fun s(kind: LevelScreen, tap: P? = null) = LevelState(kind, tap)
    private val dice = Config.DICE_BUTTON

    @Test
    fun redDiceIsHeldForAutoPlayThenLeftAlone() {
        val actions = play(listOf(s(LevelScreen.BOARD_READY, dice), s(LevelScreen.AUTO_PLAY), s(LevelScreen.AUTO_PLAY),
            s(LevelScreen.SKILL_PICK, P(720, 1052)), s(LevelScreen.AUTO_PLAY), s(LevelScreen.VICTORY, P(720, 2220))))
        assertEquals(listOf("hold" to dice, "tap" to P(720, 1052), "tap" to P(720, 2220)), actions)
    }

    @Test
    fun autoPlayStoppingMidLevelIsTurnedOnAgain() {
        val actions = play(listOf(s(LevelScreen.BOARD_READY, dice), s(LevelScreen.AUTO_PLAY), s(LevelScreen.BOARD_READY, dice),
            s(LevelScreen.AUTO_PLAY), s(LevelScreen.VICTORY, P(720, 2220))))
        assertEquals(listOf("hold" to dice, "hold" to dice, "tap" to P(720, 2220)), actions)
    }

    @Test
    fun withoutAutoPlayTheDiceIsTapped() {
        val actions = play(listOf(s(LevelScreen.BOARD_READY, dice), s(LevelScreen.BOARD_READY, dice), s(LevelScreen.FIGHT),
            s(LevelScreen.BOARD_READY, dice), s(LevelScreen.VICTORY, P(720, 2220))))
        assertEquals(listOf("hold" to dice, "tap" to dice, "tap" to dice, "tap" to P(720, 2220)), actions)
    }

    @Test
    fun withoutAdsX2RewardsIsSkippedAndReviveWaits() {
        val actions = play(listOf(s(LevelScreen.REVIVE, P(990, 1455)), s(LevelScreen.REVIVE, P(990, 1455)),
            s(LevelScreen.DOUBLE_REWARD, P(1150, 2220)), s(LevelScreen.VICTORY, P(720, 2220))))
        assertEquals(listOf("tap" to P(720, 2220)), actions)
    }

    @Test
    fun withoutAdsTheLevelEndContinuesInsteadOfDoubling() {
        L.setLanguage("es")
        val actions = play(listOf(s(LevelScreen.DOUBLE_REWARD, P(1150, 2220)), s(LevelScreen.VICTORY, P(720, 2220))),
            listOf(t("Continuar", 600, 2360, 840, 2400), t("x2 Recompensas", 1000, 2200, 1300, 2240)))
        assertEquals(listOf("tap" to P(720, 2380), "tap" to P(720, 2220)), actions)
    }

    @Test
    fun x2RewardsButtonThatStaysIsGivenUpForContinue() {
        L.setLanguage("es")
        val actions = play(List(3) { s(LevelScreen.DOUBLE_REWARD, P(1150, 2220)) } + s(LevelScreen.VICTORY, P(720, 2380)),
            listOf(t("Continuar", 600, 2360, 840, 2400), t("x2 Recompensas", 1000, 2200, 1300, 2240)), ads = true)
        assertEquals(listOf(P(1150, 2220), P(1150, 2220), P(720, 2380), P(720, 2380)), actions.map { it.second })
    }

    @Test
    fun repeatedTapsNeedTimeTooBeforeGivingUp() {
        val actions = play(List(9) { s(LevelScreen.CONTINUE, P(720, 2380)) } + s(LevelScreen.VICTORY, P(720, 2300)))
        assertEquals(10, actions.size)  // 9 quick repeats (< 10 s): not stuck
    }

    @Test
    fun aRevivePopupThatStaysWithoutAdsTimesOut() {
        val e = assertThrows(PlayError::class.java) { play(List(200) { s(LevelScreen.REVIVE, P(990, 1455)) }) }
        assertTrue(e.message!!.contains("unknown screen"))
    }

    @Test
    fun jitteringTapsCountAsRepeats() {
        val ev = LevelScreen.EVENT
        assertTrue(sameTap(ev to P(76, 1991), ev to P(78, 1990)))
        assertTrue(!sameTap(ev to P(76, 1991), ev to P(500, 1991)))
        assertTrue(!sameTap(ev to P(76, 1991), LevelScreen.SHOP to P(76, 1991)))
        assertTrue(!sameTap(ev to P(76, 1991), null))
    }

    @Test
    fun speedX1IsSwitchedOnceAndLockedIsNotRetried() {
        val device = FakeDevice()
        val player = Player(device, FakeOcr(), clock = clock)
        fun speed(n: Int) = listOf(t("» x$n", 80, 2410, 230, 2460))
        assertTrue(player.ensureDoubleSpeed(speed(1)))
        assertTrue(!player.ensureDoubleSpeed(speed(1)))  // still x1 after tapping: locked
        assertTrue(!player.ensureDoubleSpeed(speed(1)))
        assertTrue(!player.ensureDoubleSpeed(emptyList()))
        assertEquals(listOf(Config.SPEED_BUTTON), device.taps)
    }

    // --- skill picks and shops ---

    private fun card(rarity: String, name: String, description: String, y: Int, price: Int? = null): List<Text> =
        listOfNotNull(t(rarity, 280, y - 15, 360, y + 15), t(name, 450, y + 20, 800, y + 60), t(description, 450, y + 100, 1000, y + 140),
            price?.let { t(it.toString(), 1130, y + 180, 1200, y + 220) })

    private val prompt = t("Select a Skill to learn!", 400, 830, 1040, 870)
    private val reroll = listOf(t("Reroll", 650, 2100, 790, 2140), t("(1)", 690, 2170, 750, 2210))

    private fun player(build: Build, frames: List<List<Text>> = emptyList()): Pair<Player, FakeDevice> {
        L.setLanguage("en")
        val device = FakeDevice()
        val queue = ArrayDeque(frames)
        val ocr = object : Ocr { override fun read(img: Frame, region: Region?) = queue.removeFirst() }
        return Player(device, ocr, build, Catalog(java.io.File.createTempFile("skills", ".json").apply { delete() }), clock = clock) to device
    }

    @Test
    fun playerPicksTheBuildSkillAndRecordsIt() {
        val (p, _) = player(Build(Skills.MAGIC))
        val screen = listOf(prompt) + card("Common", "Sneaky Poison", "When you dodge, apply Poison.", 928) +
            card("Common", "Fire Weapon", "Attacks deal additional fire damage.", 1236) + reroll
        assertEquals(P(720, 1236 + Config.SKILL_TAP_BELOW_RARITY), p.pickSkill(screen))
        assertEquals(listOf("Fire Weapon"), p.state.taken)
        assertEquals(setOf("sneakypoison", "fireweapon"), p.catalog.skills.keys)
    }

    @Test
    fun playerRerollsOnceWhenNothingFits() {
        val (p, _) = player(Build(Skills.MAGIC))
        val shieldOnly = listOf(prompt) + card("Common", "Iron Shield", "Gain a Shield.", 928) + reroll
        assertEquals(P(720, 2120), p.pickSkill(shieldOnly))
        assertEquals(P(720, 928 + Config.SKILL_TAP_BELOW_RARITY), p.pickSkill(shieldOnly))
    }

    private data class ShopCard(val rarity: String, val name: String, val description: String, val price: Int, val sold: Boolean = false)

    private fun shop(money: Int, cards: List<ShopCard>, free: Boolean = true): List<Text> {
        val texts = mutableListOf(t("SHOP", 640, 340, 800, 390), t("$money", 140, 155, 200, 190), t("Reroll", 780, 2365, 930, 2405),
            t("Exit", 380, 2395, 470, 2440), t(if (free) "FREE" else "10", 840, 2435, 930, 2475))
        cards.forEachIndexed { i, c ->
            val y = 1086 + 334 * i
            texts += card(c.rarity, c.name, c.description, y, c.price)
            if (c.sold) texts.add(t("SOLD OUT", 500, y + 110, 900, y + 140))
        }
        return texts
    }

    private fun priceAt(i: Int) = P(1165, 1086 + 334 * i + 200)
    private val recovery = ShopCard("Common", "Recovery", "Restore 5% HP.", 48)
    private val fireWave = ShopCard("Common", "Fire Wave", "Cast Fire Wave.", 95)
    private val executioner = ShopCard("Legendary", "Executioner", "Execute the enemy.", 190)

    @Test
    fun shopBuysWantedFirstThenWhatCoinsAllow() {
        val (p, device) = player(Build(Skills.MAGIC), listOf(
            shop(155, listOf(recovery, fireWave.copy(sold = true), executioner), free = false),
            shop(107, listOf(recovery.copy(sold = true), fireWave.copy(sold = true), executioner), free = false)))
        p.shop(shop(250, listOf(recovery, fireWave, executioner)))
        assertEquals(listOf(priceAt(1), priceAt(0)), device.taps)
        assertEquals(listOf("Fire Wave", "Recovery"), p.state.taken)
    }

    @Test
    fun shopUsesTheFreeRerollWhenNothingFits() {
        val (p, device) = player(Build(Skills.MAGIC), listOf(shop(100, listOf(fireWave), free = false),
            shop(5, listOf(fireWave.copy(sold = true)), free = false)))
        p.shop(shop(100, listOf(recovery)))
        assertEquals(listOf(P(855, 2385), priceAt(0)), device.taps)
    }

    @Test
    fun shopWithoutCoinsBuysNothing() {
        val (p, device) = player(Build(Skills.MAGIC))
        p.shop(shop(20, listOf(fireWave), free = false))
        assertEquals(emptyList<P>(), device.taps)
    }

    @Test
    fun cardWithoutAReadableNameIsSkipped() {
        L.setLanguage("en")
        val texts = listOf(prompt, t("Mythic", 280, 913, 360, 943), t("after your first death.", 450, 1040, 900, 1080)) +
            card("Common", "Fire Wave", "Every turn cast Fire Wave.", 1236)
        assertEquals(listOf("Fire Wave"), Screens.parseSkillCards(texts).map { it.name })
    }

    @Test
    fun raidSkillChoicePrefersHighestRarity() {
        L.setLanguage("en")
        val texts = listOf(t("Select a Skill to learn!", 400, 560, 1040, 600), t("Common", 280, 740, 360, 770), t("Epic", 280, 1050, 360, 1080),
            t("Mythic", 280, 1360, 360, 1390), t("Epic", 280, 1660, 360, 1690), t("Learn Skills (0/2)", 700, 2130, 1080, 2170))
        val choice = ModeScreens.parseSkillChoice(texts)!!
        assertEquals(listOf(1465, 1155, 1765, 845), choice.cards.map { it.y })
        assertEquals(0 to 2, choice.chosen to choice.needed)
    }

    @Test
    fun diceDuelPolicy() {
        for ((score, label) in listOf(0 to "TIRAR", 14 to "TIRAR", 15 to "RESISTIR", 20 to "RESISTIR")) {
            val texts = listOf(t("Yo $score / 21", 600, 1960, 800, 2010), t("RESISTIR", 450, 2340, 620, 2390), t("TIRAR", 940, 2340, 1090, 2390))
            val state = Screens.classifyLevelScreen(Script.BLANK, texts)
            assertEquals(LevelScreen.DICE_DUEL, state.kind)
            assertEquals(texts.first { it.text == label }.center, state.tap)
        }
    }

    @Test
    fun aLevelLeftRunningIsRecognizedAtStart() {
        for ((name, running) in listOf("level_board_ready.png" to true, "level_fight.png" to true, "level_skill_levelup.png" to true,
            "lobby_normal.png" to false, "lobby_promo_popup.png" to false, "level_event_result.png" to false)) {
            val (img, texts) = Fixtures.case(name)
            L.setLanguage(null)
            assertEquals(name, running, levelInProgress(img, texts))
        }
    }

    @Test
    fun templatesAreFoundOnRealScreens() {
        // A popup with ✕ and a menu with ←, from the screenshots; none on the plain lobby.
        assertNotNull(Screens.closeButton(Fixtures.fixture("elite_dialog_x5.png")))
        assertNotNull(ModeScreens.backArrow(Fixtures.fixture("dojo.png")))
        assertNotNull(Screens.tutorialHand(Fixtures.fixture("lobby_tutorial_hand.png")))
        assertNull(Screens.closeButton(Fixtures.fixture("lobby_normal.png")))
        assertNull(ModeScreens.backArrow(Fixtures.fixture("lobby_normal.png")))
    }

    companion object {
        val START = t("INICIO", 600, 2060, 716, 2120)
        val LOBBY = listOf(START, t("Patrulla", 650, 1900, 790, 1945))
        val LOADING = listOf(t("Cargando...", 600, 1260, 840, 1320))
        val IN_LEVEL = listOf(t("Toca para continuar", 500, 2320, 940, 2370))
        val ES_LOBBY = RoutineTest.ES_LOBBY
        val BARE_LOBBY = listOf(t("Patrulla", 650, 1900, 790, 1945), t("INICIO", 600, 2070, 716, 2115), t("20/32", 820, 70, 890, 100))
        val RESUME = listOf(t("Continue Adventure?", 520, 875, 920, 920), t("You have an ongoing", 520, 1140, 920, 1190),
            t("Abandon", 470, 1395, 630, 1440), t("OK", 860, 1395, 920, 1440))
        val EN_LOBBY = listOf(t("Patrol", 650, 1900, 790, 1945), t("OFF", 900, 2060, 970, 2095), t("START", 600, 2070, 716, 2115),
            t("Challenge", 840, 1910, 960, 1945))
    }
}
