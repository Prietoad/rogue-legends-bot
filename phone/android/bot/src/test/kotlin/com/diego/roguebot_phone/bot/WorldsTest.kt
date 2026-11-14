package com.diego.roguebot_phone.bot

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Port of tests/test_worlds.py: worlds (the "Mapa Mundial") and what Heliora's levels added. */
class WorldsTest {
    @Before
    fun setUp() = Fixtures.loadTemplates()

    @After
    fun reset() = L.setLanguage(null)

    private val clock = FakeClock()
    private val mapButton = t("Mundial", 374, 1904, 522, 1943)
    private val map = listOf(t("Mapa Mundial", 504, 99, 932, 185), t("Heliora", 460, 1523, 605, 1567),
        t("Everdale", 690, 2220, 866, 2272), t("Portal del Caos", 1116, 1344, 1343, 1379))

    private fun lobby(title: String, compass: Boolean = true) = listOfNotNull(t("Patrulla", 739, 1904, 884, 1943),
        t("APAGADO", 880, 2064, 987, 2090), t("INICIO", 532, 2047, 785, 2136), t(title, 415, 540, 1020, 615),
        t("16/38", 794, 64, 916, 105), if (compass) mapButton else null)

    private fun nav(world: String?, vararg screens: List<Text>): Pair<ScriptNav, FakeDevice> {
        L.setLanguage("es")
        val device = FakeDevice()
        return ScriptNav(device, Script.texts(*screens), FakeOcr(), clock, real = true, world = world) to device
    }

    @Test
    fun levelTitlesOfOtherWorlds() {
        assertEquals(1, parseLevelNumber("2-1. Elysium I")); assertEquals(2, parseWorldNumber("2-1. Elysium I"))
        assertEquals(14, parseLevelNumber("2-14. Elysium (Élite) II"))
        assertEquals(81, parseLevelNumber("81. Picos Helados XII")); assertEquals(1, parseWorldNumber("81. Picos Helados XII"))
        assertNull(parseWorldNumber("Temporada 25"))
    }

    @Test
    fun switchingWorldGoesThroughTheMap() {
        val (n, device) = nav("heliora", lobby("81. Picos Helados XII"), map, map, lobby("2-1. Elysium I"))
        assertEquals(2, n.setMode(Mode.NORMAL).world)
        assertEquals(listOf(mapButton.center, map[1].center), device.taps)  // the compass, then the island's name
        assertEquals("heliora", n.world)
    }

    @Test
    fun theWantedWorldAlreadyShowingNeedsNoTap() {
        val (n, device) = nav("heliora", lobby("2-1. Elysium I"))
        assertEquals(2, n.setMode(Mode.NORMAL).world)
        val (m, device2) = nav("everdale", lobby("81. Picos Helados XII"))
        assertEquals(1, m.setMode(Mode.NORMAL).world)
        val (none, device3) = nav(null, lobby("81. Picos Helados XII"))
        assertEquals(1, none.setMode(Mode.NORMAL).world)
        assertEquals(emptyList<P>(), device.taps + device2.taps + device3.taps)
    }

    @Test
    fun accountWithoutWorldsPlaysWhereItIs() {
        val (n, device) = nav("heliora", lobby("13. Bosque Embrujado II", compass = false))
        assertEquals(1, n.setMode(Mode.NORMAL).world)
        assertNull(n.world)  // given up for the session
        assertEquals(emptyList<P>(), device.taps)
        val (first, _) = nav("everdale", lobby("13. Bosque Embrujado II", compass = false))
        assertEquals(1, first.setMode(Mode.NORMAL).world)
        assertEquals("everdale", first.world)  // the first world: nothing to switch
    }

    @Test
    fun worldMissingFromTheMapOrLockedIsGivenUp() {
        val everdale = lobby("81. Picos Helados XII")
        val noHeliora = listOf(map[0], map[2])
        val (n, device) = nav("heliora", everdale, noHeliora, noHeliora, everdale)
        assertEquals(1, n.setWorld(Screens.parseLobby(everdale)!!).world)
        assertNull(n.world)
        assertEquals(mapButton.center, device.taps[0])
        assertTrue(map[1].center !in device.taps)
        val back = Canvas().paste(template("back_arrow.png"), 120, 2447).frame  // the map's ← button
        val (locked, device2) = nav("heliora")
        var shown = 0
        val frames = listOf(Script.BLANK to everdale) + List(30) { back to map } + listOf(Script.BLANK to everdale)
        val script = Script(frames)
        val real = object : Navigator(device2, FakeOcr(), clock = clock, world = "heliora") {
            override fun capture() = script.next().also { shown++ }
        }
        assertEquals(1, real.setWorld(Screens.parseLobby(everdale)!!).world)  // the map stayed open: left by its back arrow
        assertNull(real.world)
        assertTrue(shown > 3 && locked.world == "heliora")
    }

    @Test
    fun worldOptionInTheRequest() {
        assertEquals("heliora", buildRequest("normal", "latest", "", world = "heliora").world)
        assertNull(buildRequest("normal", "latest", "").world)
        assertNull(buildRequest("normal", "stars", "3", world = "atlantis").world)
    }

    // --- strategy ---

    @Test
    fun forkTakesTheShopOnlyWithCoinsForIt() {
        assertEquals(1, Strategy.choosePath(listOf(false, true), 166))
        assertEquals(0, Strategy.choosePath(listOf(true, false), Config.PATH_SHOP_COINS))
        assertEquals(0, Strategy.choosePath(listOf(false, true), Config.PATH_SHOP_COINS - 1))
        assertEquals(0, Strategy.choosePath(listOf(false, true), null))
        assertEquals(0, Strategy.choosePath(listOf(true, true), 0))
        assertEquals(0, Strategy.choosePath(listOf(false, false), 500))
    }

    @Test
    fun eventRules() {
        L.setLanguage("es")
        assertEquals(0, Strategy.chooseEvent(listOf("no,gracias", "toma el taxi"), 1.0))
        assertEquals(1, Strategy.chooseEvent(listOf("indulgencia", "rechazar"), 0.2))
        assertEquals(0, Strategy.chooseEvent(listOf("espiar", "mete el brazo"), 1.0))
        assertEquals(0, Strategy.chooseEvent(listOf("observar", "robado"), 1.0))
        assertEquals(0, Strategy.chooseEvent(listOf("rezar", "ofrenda", "hacer una"), 1.0))
        assertEquals(0, Strategy.chooseEvent(listOf("descansar", "entrenar"), null))
        assertEquals(0, Strategy.chooseEvent(listOf("descansar", "entrenar"), 0.49))
        assertEquals(1, Strategy.chooseEvent(listOf("descansar", "entrenar"), 1.0))
        assertNull(Strategy.chooseEvent(listOf("firmar", "salir"), 1.0))
        assertNull(Strategy.chooseEvent(emptyList(), 1.0))
    }

    @Test
    fun shopItemRule() {
        val both = mapOf("boost" to 57, "heal" to 95)
        assertEquals("boost", Strategy.shopItem(both, 200, 1.0))
        assertEquals("heal", Strategy.shopItem(both, 200, 0.3))
        assertEquals("boost", Strategy.shopItem(both, 60, 0.3))
        assertEquals("boost", Strategy.shopItem(both, 200, null))
        assertNull(Strategy.shopItem(mapOf("heal" to 95), 200, 0.9))
        assertNull(Strategy.shopItem(mapOf("boost" to 57), 56, 1.0))
    }

    @Test
    fun cursedVendorContract() {
        L.setLanguage("es")
        val inn = "cada fogata se convierte en una posada (cura completa + mejora 2 habilidades). los precios de la tienda se duplican."
        val rerolls = "las nuevas tiradas de habilidad se renuevan en cada seleccion de habilidad. los enemigos siempre actuan primero"
        assertEquals(1, Strategy.chooseContract(listOf(rerolls, inn)))   // +3 -2 beats +1 -1
        assertEquals(0, Strategy.chooseContract(listOf(inn, rerolls)))
        assertEquals(0, Strategy.chooseContract(listOf("algo nuevo", "otra cosa")))  // unknown terms: the first
        assertEquals(1, Strategy.chooseContract(listOf("los precios de la tienda se duplican.", "algo nuevo")))
        val vendor = listOf(t("Vendedor Maldito", 392, 181, 1045, 274), t("Firmar", 298, 2310, 560, 2405), t("Firmar", 879, 2313, 1140, 2403),
            t("habilidad se renuevan", 182, 1490, 676, 1544), t("siempre actúan", 180, 2042, 558, 2099), t("primero", 180, 2100, 383, 2158),
            t("posada (cura completa", 758, 1540, 1234, 1598), t("tienda se duplican.", 759, 2067, 1217, 2130))
        assertEquals(LevelScreen.CONTRACT, Screens.classifyLevelScreen(Script.BLANK, vendor).kind)
        assertEquals(P(1009, 2358), player().first.contract(vendor))
        assertEquals(emptyList<Screens.Contract>(), Screens.parseContracts(vendor.drop(1)))  // "Firmar" alone (the devil's deal) is no vendor
    }

    @Test
    fun autoPlayThatNeverEndsStopsTheLevel() {
        val states = ArrayDeque(List(Config.WAIT_SCREEN_FRAMES + 5) { LevelState(LevelScreen.AUTO_PLAY) })
        val stuck = Player(FakeDevice(), FakeOcr(), clock = clock, classify = { _, _ -> states.removeFirst() })
        assertTrue(org.junit.Assert.assertThrows(PlayError::class.java) { stuck.playLevel() }.message!!.contains("Waiting on auto_play"))
        val turns = ArrayDeque(List(200) { LevelState(if (it % 2 == 0) LevelScreen.AUTO_PLAY else LevelScreen.FIGHT) } +
            List(300) { LevelState(LevelScreen.FIGHT) } + LevelState(LevelScreen.VICTORY, P(720, 2220)))
        assertEquals(LevelScreen.VICTORY, Player(FakeDevice(), FakeOcr(), clock = clock, classify = { _, _ -> turns.removeFirst() }).playLevel())
    }

    private fun grid(treasure: List<Int> = emptyList(), empty: List<Int> = emptyList()) =
        MutableList(49) { if (it in treasure) Screens.TREASURE else if (it in empty) Screens.EMPTY else Screens.DIRT }

    @Test
    fun minerSearchAndFollow() {
        assertEquals(24, Strategy.minerDig(grid(), emptySet()))
        val g = grid()
        repeat(9) {
            val i = Strategy.minerDig(g, emptySet())!!
            assertEquals(0, (i / 7 + i % 7) % 3)  // diagonals 3 apart
            g[i] = Screens.EMPTY
        }
        assertEquals(11, Strategy.minerDig(grid(treasure = listOf(10)), emptySet()))
        assertEquals(9, Strategy.minerDig(grid(treasure = listOf(10), empty = listOf(11)), emptySet()))
        assertTrue(Strategy.minerDig(grid(treasure = listOf(10, 17)), emptySet()) in listOf(3, 24))
        assertEquals(24, Strategy.minerDig(grid(treasure = listOf(10, 17), empty = listOf(3, 9, 11, 16, 18)), emptySet()))
        assertEquals(24, Strategy.minerDig(grid(treasure = listOf(0)), setOf(0)))
        assertNull(Strategy.minerDig(List(49) { Screens.EMPTY }, emptySet()))
    }

    // --- player ---

    private fun card(rarity: String, name: String, y: Int, price: Int? = null): List<Text> =
        listOfNotNull(t(rarity, 280, y - 15, 360, y + 15), t(name, 450, y + 20, 800, y + 60), t("Deals fire damage.", 450, y + 100, 1000, y + 140),
            price?.let { t(it.toString(), 1130, y + 180, 1200, y + 220) })

    private fun shop(money: Int, sold: Boolean, uses: String?, hp: String = "10m/10m"): List<Text> =
        listOfNotNull(t("SHOP", 640, 340, 800, 390), t("$money", 140, 155, 200, 190), t("Reroll", 780, 2365, 930, 2405),
            t("Exit", 380, 2395, 470, 2440), t("10", 840, 2435, 930, 2475), t(hp, 408, 54, 725, 109),
            uses?.let { t(it, 807, 707, 902, 765) }, t("ATQ↑↑↑", 691, 850, 903, 912), t("Curar 30%", 1017, 856, 1234, 909),
            t("57", 792, 947, 874, 1010), t("95", 1121, 947, 1202, 1010)) +
            card("Common", "Fire Wave", 1086, 95) + if (sold) listOf(t("SOLD OUT", 500, 1196, 900, 1226)) else emptyList()

    private fun player(frames: List<List<Text>> = emptyList()): Pair<Player, FakeDevice> {
        val device = FakeDevice()
        val queue = ArrayDeque(frames)
        val ocr = object : Ocr { override fun read(img: Frame, region: Region?) = queue.removeFirst() }
        return Player(device, ocr, Build(Skills.MAGIC), Catalog(java.io.File.createTempFile("skills", ".json").apply { delete() }), clock = clock) to device
    }

    private val boostPrice = P(833, 978)
    private val healPrice = P(1161, 978)

    @Test
    fun shopBuysTheStatBoostBeforeSkills() {
        val (p, device) = player(listOf(shop(193, false, "2/3"), shop(136, false, "1/3"), shop(79, false, "AGOTADO"), shop(79, true, "AGOTADO")))
        p.shop(shop(250, false, "3/3"))
        assertEquals(listOf(boostPrice, boostPrice, boostPrice), device.taps)  // Fire Wave costs 95: no coins left for it
        assertEquals(emptyList<String>(), p.state.taken)
    }

    @Test
    fun shopHealsFirstWhenHurtAndStopsWhenTheCoinsDoNotDrop() {
        val (p, device) = player(listOf(shop(105, false, "3/3", hp = "6m/10m"), shop(48, false, "2/3")))
        p.shop(shop(200, false, "3/3", hp = "3m/10m"))
        assertEquals(listOf(healPrice, boostPrice), device.taps)
        val stuck = shop(200, false, null)
        val (q, device2) = player(listOf(stuck, shop(105, true, null)))
        q.shop(stuck)
        assertEquals(listOf(boostPrice, P(1165, 1286)), device2.taps)  // one try, then on to the skills
    }

    @Test
    fun skillPickWaitsForEveryCard() {
        L.setLanguage("en")
        val (p, _) = player()
        val prompt = t("Select a Skill to learn!", 400, 830, 1040, 870)
        val one = listOf(prompt) + card("Common", "Iron Shield", 928)
        val three = one + card("Common", "Fire Weapon", 1236) + card("Common", "Ice Weapon", 1544)
        assertEquals(listOf(false, false, true), listOf(one, three, three).map(p::offerSettled))
        assertTrue(p.offerSettled(listOf(prompt)))  // no card read: the old fallback right away
        assertEquals(listOf(false, true), listOf(three, three).map(p::offerSettled))
        assertTrue(List(6) { if (it % 2 == 0) one else three }.map(p::offerSettled)[Config.SKILL_PICK_SETTLE_FRAMES])
    }

    @Test
    fun playerStopsFollowingATreasureOnceItIsDugOut() {
        L.setLanguage("es")
        val (p, _) = player()
        fun frame(tiles: List<String>, left: Int): Pair<Frame, List<Text>> {
            val canvas = Canvas()
            for ((i, kind) in tiles.withIndex()) {
                val c = Screens.minerTile(i / 7, i % 7)
                val (r, g, b) = when (kind) { Screens.DIRT -> Triple(171, 122, 80); Screens.EMPTY -> Triple(24, 16, 8); else -> Triple(249, 148, 26) }
                canvas.fill(c.x - 60, c.y - 60, c.x + 60, c.y + 60, r, g, b)
            }
            return canvas.frame to listOf(t("Tesoros Restantes: $left", 468, 2087, 972, 2139))
        }
        fun dig(tiles: List<String>, left: Int) = frame(tiles, left).let { p.miner(it.first, it.second) }
        assertEquals(Screens.minerTile(3, 3), dig(grid(), 5))
        assertEquals(Screens.minerTile(5, 2), dig(grid(treasure = listOf(36), empty = listOf(24)), 5))  // follow the piece
        assertTrue(dig(grid(treasure = listOf(36, 37), empty = listOf(24)), 5) in listOf(Screens.minerTile(5, 0), Screens.minerTile(5, 3)))
        val done = grid(treasure = listOf(35, 36, 37), empty = listOf(24))
        val next = dig(done, 4)  // the count dropped: dug out whole
        assertEquals(setOf(35, 36, 37), p.minerDone)
        assertTrue(next !in listOf(28, 29, 30, 34, 38, 42, 43, 44).map { Screens.minerTile(it / 7, it % 7) })
    }

    @Test
    fun playerTapsTheChosenForkCardAndEventOption() {
        L.setLanguage("es")
        val (p, _) = player()
        val fork = listOf(t("Camino A", 362, 2251, 638, 2313), t("Camino B", 803, 2251, 1079, 2313), t("SHOP", 880, 1930, 990, 1990),
            t("SHOP", 1290, 1820, 1400, 1870))  // the second sign is a building on the board, outside the cards
        assertEquals(P(941, 2282), p.path(Script.BLANK, fork + t("166", 120, 145, 223, 203)))
        assertEquals(P(500, 2282), p.path(Script.BLANK, fork + t("12", 120, 145, 223, 203)))
        // The phone's OCR does not read the sign: the shop wagon drawn on the card is matched instead.
        val img = Fixtures.fixture("level_path_choice.png")
        val unsigned = fork.take(2)
        assertEquals(listOf(false, false), Screens.parsePaths(unsigned).map { it.shop })
        assertEquals(listOf(false, true), Screens.parsePaths(unsigned, img).map { it.shop })
        assertEquals(listOf(false, false), Screens.parsePaths(unsigned, Script.BLANK).map { it.shop })
        val rest = listOf(t("Un Momento de Descanso", 217, 1353, 1220, 1447), t("Descansar", 352, 1765, 671, 1824),
            t("Entrenar", 790, 1762, 1058, 1825))
        assertEquals(P(924, 1793 + Config.EVENT_ICON_BELOW_LABEL), p.event(Script.BLANK, rest + t("10m/10m", 408, 54, 725, 109)))
        assertEquals(P(511, 1794 + Config.EVENT_ICON_BELOW_LABEL), p.event(Script.BLANK, rest + t("4m/10m", 408, 54, 725, 109)))
        assertNull(p.event(Script.BLANK, listOf(rest[0], t("Firmar", 420, 1765, 600, 1824), t("Salir", 850, 1765, 1000, 1824))))
    }

    @Test
    fun blacksmithAnvil() {
        L.setLanguage("es")
        assertTrue(Strategy.anvilUpgrade(70) && Strategy.anvilUpgrade(40))
        assertFalse(Strategy.anvilUpgrade(10) || Strategy.anvilUpgrade(null))  // unreadable chance: take
        fun anvil(chance: String) = listOf(t("Yunque del Herrero", 362, 156, 1074, 258), t(chance, 713, 2077, 1157, 2169),
            t("Recibes", 353, 2219, 659, 2312), t("Reforzar", 765, 2219, 1100, 2312))
        assertEquals(LevelScreen.ANVIL, Screens.classifyLevelScreen(Script.BLANK, anvil("Éxito del 70%!")).kind)
        assertEquals(70, Screens.parseAnvil(anvil("Éxito del 70%!"))!!.chance)
        assertEquals(P(932, 2265), player().first.anvil(anvil("Éxito del 70%!")))   // upgrade
        assertEquals(P(506, 2265), player().first.anvil(anvil("Éxito del 10%!")))   // take
        assertEquals(P(506, 2265), player().first.anvil(anvil("???")))
        assertNull(Screens.parseAnvil(anvil("Éxito del 70%!").drop(1)))             // no anvil title
        val claim = anvil("Éxito del 10%!") + t("Toca en cualquier lugar", 401, 2309, 1036, 2389)
        assertEquals(LevelScreen.CONTINUE, Screens.classifyLevelScreen(Script.BLANK, claim).kind)  // reward banner over the anvil
        assertTrue(LevelScreen.ANVIL in ON_BOARD)
    }
}
