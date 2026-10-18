package com.diego.roguebot_phone.bot

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.ZoneId

/** Port of tests/test_build.py and the pure parts of tests/test_logic.py, plus the phone's screen mapping. */
class LogicTest {
    @Test
    fun inferTags() {
        val cases = listOf(
            Triple("Fire Weapon", "Your Weapon Attacks deal additional fire damage and have a chance to cast Fireball.", Skills.Tags("fire", "magic", "damage")),
            Triple("Carámbano de Contraataque", "Cada vez que haces un Contraataque, lanza Carámbano.", Skills.Tags("ice", "magic", "damage")),
            Triple("Descarga Definitiva", "Lanza 2 Descargas después de usar tu Definitiva.", Skills.Tags("lightning", "magic", "damage")),
            Triple("Shuriken-Curativo", "Cada 2 rondas, lanza 1 Shuriken. Todos los Shurikens tienen probabilidad de curarte.", Skills.Tags("shuriken", "physical", "damage")),
            Triple("Sneaky Poison", "When you dodge, apply Poison to a random enemy 2 times.", Skills.Tags("venom", "physical", "damage")),
            Triple("Golpe Venenoso", "Los Ataques del arma aplicarán 1 acumulación de Veneno.", Skills.Tags("venom", "physical", "damage")),
            Triple("Glass Cannon", "ATK ↑↑↑↑, Max HP ↓↓↓", Skills.Tags(null, "physical", "damage")),
            Triple("Executioner", "When the enemy has less than 50% HP, immediately execute them.", Skills.Tags(null, "physical", "damage")),
            Triple("Escudo enfurecido", "La primera vez que tu HP <40%, obtienes un Escudo igual al 25% de HP.", Skills.Tags(null, "physical", "support")),
            Triple("Recovery", "Chance to restore 5% HP every turn.", Skills.Tags(null, "physical", "support")),
            Triple("Lifesteal", "Weapon Attacks have a chance to Lifesteal", Skills.Tags(null, "physical", "support")),
            Triple("Evasión-Enfurecida", "Cuando el HP <40%, Tasa de evasión", Skills.Tags(null, "physical", "support")),
            Triple("Twice the Price", "Cast twice.", Skills.Tags(null, "physical", "damage")),
            Triple("Wizard", "Magical DMG ↑, Physical DMG ↓↓", Skills.Tags(null, "magic", "damage")),
            Triple("Lanzamiento Doble", "Después de usar tu Definitiva, encadena otra Definitiva.", Skills.Tags(null, "physical", "damage")),
            Triple("Defensa Creciente", "Cada ronda, DEF ↑", Skills.Tags(null, "physical", "support")),
            Triple("Macizo", "HP Máx. ↑↑↑↑, ATQ ↓↓↓", Skills.Tags(null, "physical", "support")),
            Triple("Fuerza-Enfurecida", "Cuando el HP <40%, ATQ y DEF", Skills.Tags(null, "physical", "damage")),
            Triple("Warrior", "Physical DMG ↑, Magical DMG ↓", Skills.Tags(null, "physical", "damage")),
            Triple("Mago", "Daño Mágico ↑, Daño Físico ↓↓", Skills.Tags(null, "magic", "damage")),
            Triple("Wound Strike", "Weapon Attacks will apply 1 stack of Wound.", Skills.Tags("bleed", "physical", "damage")),
        )
        for ((name, description, tags) in cases) assertEquals(name, tags, Skills.inferTags(name, description))
    }

    @Test
    fun inferTagsMatchesTheDesktopOnTheWholeSkillDatabase() {
        // Every skill the desktop bot inferred (auto = true) must get the same tags here.
        val data = JSONObject(File(Fixtures.ROOT, "data/skills.json").readText())
        var checked = 0
        for (key in data.keySet()) {
            val s = data.getJSONObject(key)
            if (!s.getBoolean("auto")) continue
            val tags = Skills.inferTags(s.getString("name"), s.getString("description"))
            val want = Skills.Tags(if (s.isNull("damage_type")) null else s.getString("damage_type"), s.getString("nature"), s.getString("role"))
            assertEquals(s.getString("name"), want, tags)
            checked++
        }
        assertTrue(checked > 20)
    }

    @Test
    fun skillKeyIgnoresOcrSpacing() {
        assertEquals("ultimatebolt", Skills.skillKey("Ultimate-Bolt"))
        assertEquals("ultimatebolt", Skills.skillKey("Ultimate Bolt"))
        assertEquals("carambano", Skills.skillKey("Carámbano"))
    }

    @Test
    fun catalogAddsNewSkillsSavesAndToleratesTypos() {
        val file = File.createTempFile("skills", ".json").apply { delete() }
        val catalog = Catalog(file)
        val skill = catalog.lookup("Fire Wave", "Every turn cast Fire Wave.", "common", "en")
        assertEquals(Triple("fire", "magic", "damage"), Triple(skill.damageType, skill.nature, skill.role))
        assertEquals("common", JSONObject(file.readText()).getJSONObject("firewave").getString("rarity"))
        assertEquals("Fire Wave", Catalog(file).skills.getValue("firewave").name)
        assertEquals("Fire Wave", catalog.lookup("Fire Wavc", "", "common", "en").name)  // OCR typo -> same skill
        assertEquals(1, catalog.skills.size)
    }

    @Test
    fun ratioMatchesDifflib() {
        assertEquals(2.0 * 8 / 18, Catalog.ratio("lifesteal", "lifesteai"), 1e-9)  // difflib: 0.888...
        assertEquals(1.0, Catalog.ratio("abc", "abc"), 1e-9)
        assertEquals(0.0, Catalog.ratio("abc", "xyz"), 1e-9)
    }

    private fun sk(name: String, type: String? = null, role: String = "damage", rarity: String = "common") =
        Skill(name, "en", rarity, type, if (type in Skills.MAGIC_TYPES) "magic" else "physical", role)

    private val fire = sk("fire", "fire")
    private val ice = sk("ice", "ice")
    private val venom = sk("venom", "venom")
    private val shield = sk("shield", role = "support")
    private val atk = sk("atk")

    @Test
    fun buildChoiceRules() {
        val magic = Build("magic", listOf("ice", "fire", "lightning", "shuriken", "venom", "bleed"))
        assertEquals(2, Choice.choose(listOf(fire, venom, ice), magic, BuildState(), true))
        val physical = Build("physical", listOf("venom", "bleed", "shuriken", "ice", "fire", "lightning"))
        assertEquals(2, Choice.choose(listOf(atk, fire, venom), physical, BuildState(), false))
        assertEquals(0, Choice.choose(listOf(atk, fire, shield), physical, BuildState(), false))
        val fireFirst = Build("magic", listOf("fire", "ice", "lightning", "shuriken", "venom", "bleed"))
        assertEquals(1, Choice.choose(listOf(sk("big ice", "ice", rarity = "legendary"), fire), fireFirst, BuildState(), false))
        assertEquals(1, Choice.choose(listOf(fire, sk("big fire", "fire", rarity = "legendary")), fireFirst, BuildState(), false))
        val offer = listOf(venom, sk("rare venom", "venom", rarity = "legendary"), shield)
        assertNull(Choice.choose(offer, Build("magic"), BuildState(), true))
        assertEquals(1, Choice.choose(offer, Build("magic"), BuildState(), false))
        assertEquals(0, Choice.choose(listOf(venom, atk), Build("magic"), BuildState(), false))
    }

    @Test
    fun supportAfterNDamageSkills() {
        val build = Build("magic", supportEvery = 2)
        val state = BuildState()
        assertEquals(1, Choice.choose(listOf(shield, fire), build, state, false))
        state.take(fire)
        assertEquals(1, Choice.choose(listOf(shield, fire), build, state, false))
        state.take(fire)
        assertEquals(1, Choice.choose(listOf(fire, shield), build, state, false))
        assertEquals(1, Choice.choose(listOf(fire, ice), build, state, true))
        state.take(fire)
        assertTrue(state.wantsSupport(build))
        state.take(shield)
        assertTrue(!state.wantsSupport(build) && state.damageSinceSupport == 0)
        val never = BuildState().apply { damageSinceSupport = 10 }
        assertEquals(1, Choice.choose(listOf(shield, fire), Build("magic"), never, false))
    }

    @Test
    fun shopOrder() {
        val build = Build("magic")
        assertNull(Choice.shopOrder(listOf(venom, shield), build, BuildState(), true))
        assertEquals(2, Choice.shopOrder(listOf(venom, shield, fire), build, BuildState(), true)!![0])
        assertEquals(listOf(2, 1, 0), Choice.shopOrder(listOf(venom, sk("l", "venom", rarity = "legendary"), fire), build, BuildState(), false))
    }

    @Test
    fun parsePowerAndPickOpponent() {
        val cases = mapOf("534,8k" to 534800L, "3,4m" to 3400000L, "339k" to 339000L, "1045" to 1045L, "62,9b" to 62900000000L,
            "70.7K" to 70700L, "Win:" to null, "x1" to null)
        for ((s, v) in cases) assertEquals(s, v, ModeScreens.parsePower(s))
        val opponents = listOf(600L, 100L, 499L, 500L, 501L).map { ModeScreens.Opponent(it, null) }
        assertEquals(500L, ModeScreens.pickOpponent(500, opponents)!!.power)
        assertNull(ModeScreens.pickOpponent(50, opponents))
    }

    @Test
    fun buildRequest() {
        assertEquals(RunRequest(Mode.ELITE, null, repeat = true), buildRequest("elite", LATEST, ""))
        assertEquals(RunRequest(Mode.NORMAL, 7, repeat = true), buildRequest("normal", STARS, " 7 "))
        for (bad in listOf("", "abc", "0", "-3")) assertThrows(IllegalArgumentException::class.java) { buildRequest("normal", STARS, bad) }
        val loop = buildRequest("normal", LATEST, "", loop = true)
        assertTrue(loop.loop && !loop.full && loop.repeat)  // keep running levels only
        val full = buildRequest("normal", LATEST, "", full = true)
        assertTrue(full.full && full.repeat && !full.loop)
        assertEquals(RunRequest(Mode.ELITE, null, repeat = true, lastBeaten = true), buildRequest("elite", BEATEN, ""))
        val pending = buildRequest("normal", PENDING, "")
        assertTrue(pending.pendingStars && pending.lastBeaten && pending.level == null)
        assertTrue(!buildRequest("normal", LATEST, "1").ads && buildRequest("normal", LATEST, "1", ads = true).ads)
    }

    @Test
    fun errorKeyIgnoresNumbersAndScreenshots() {
        assertEquals(errorKey(NavigationError("Level 12 is locked (screenshot: /a/fail_1.png)")),
            errorKey(NavigationError("Level 13 is locked (screenshot: /b/fail_2.png)")))
    }

    @Test
    fun patrolNextIsDueTimeOrMidnight() {
        val zone = ZoneId.of("Europe/Madrid")
        val noon = java.time.ZonedDateTime.of(2026, 10, 13, 12, 0, 0, 0, zone).toEpochSecond().toDouble()
        assertEquals(noon + 3600, patrolNext(3600.0, noon, zone), 0.0)
        assertEquals(noon + 12 * 3600, patrolNext(20 * 3600.0, noon, zone), 0.0)  // midnight first
        assertEquals(noon, patrolNext(null, noon, zone), 0.0)
    }

    @Test
    fun screenMapScalesA916Screen() {
        val m = ScreenMap(1080, 1920)
        assertEquals(1079f to 1613f, m.toDevice(P(1440, 2150)))  // clamped to the last pixel
        assertEquals(540f to 960f, m.toDevice(P(720, 1280)))
    }

    @Test
    fun screenMapAnchorsBandsOnATallScreen() {
        val m = ScreenMap(1080, 2400)  // 20:9: 2400 / 0.75 = 3200 reference rows, 640 extra
        assertEquals(60f, m.toDevice(P(0, 80)).second)                      // top bar: from the top
        assertEquals(1200f, m.toDevice(P(720, 1280)).second)                // popups: centered
        assertEquals(2288f, m.toDevice(P(720, 2410)).second)                // footer: 150 ref px (112.5) above the bottom
    }

    @Test
    fun screenMapRejectsLandscape() {
        assertThrows(IllegalArgumentException::class.java) { ScreenMap(2400, 1080) }
    }

    @Test
    fun normalizeAndLevelNumbers() {
        assertEquals("desafio de estrellas", normalize("Desafío de Estrellas"))
        assertEquals(12, parseLevelNumber("12. Arenas Movedizas II"))
        assertEquals(4, parseLevelNumber("4."))
        assertNull(parseLevelNumber("Temporada 22"))
    }

    @Test
    fun hsvMatchesOpenCv() {
        assertEquals(listOf(0, 255, 255), hsv(255, 0, 0).toList())
        assertEquals(listOf(60, 255, 255), hsv(0, 255, 0).toList())
        assertEquals(listOf(96, 255, 255), hsv(0, 200, 255).toList())  // the quick patrol's cyan lightning
        assertEquals(listOf(0, 0, 128), hsv(128, 128, 128).toList())
        assertEquals(listOf(66, 242, 200), hsv(10, 200, 50).toList())
        assertEquals(listOf(165, 127, 200), hsv(200, 100, 150).toList())
    }
}
