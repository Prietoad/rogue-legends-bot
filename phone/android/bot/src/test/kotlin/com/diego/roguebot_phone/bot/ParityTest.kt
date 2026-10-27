package com.diego.roguebot_phone.bot

import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Kotlin parsers against the desktop bot's, on every real screenshot in tests/fixtures: same image,
 * same OCR boxes (recorded by phone/tools/export_parity.py), same results. Template matches (✕, ←,
 * tutorial hand) may differ by a few pixels: the phone matches at a reduced scale.
 */
class ParityTest {
    @After
    fun reset() = L.setLanguage(null)

    private fun text(t: Text?): Any = t?.let { JSONArray(listOf(it.text, it.x1, it.y1, it.x2, it.y2)) } ?: JSONObject.NULL
    private fun p(v: P?): Any = v?.let { JSONArray(listOf(it.x, it.y)) } ?: JSONObject.NULL
    private fun obj(vararg kv: Pair<String, Any?>): JSONObject = JSONObject().apply { kv.forEach { put(it.first, it.second ?: JSONObject.NULL) } }
    private fun <T> nul(v: T?, f: (T) -> Any): Any = v?.let(f) ?: JSONObject.NULL

    private fun card(c: Screens.SkillCard) = obj("rarity" to c.rarity, "name" to c.name, "description" to c.description,
        "tag" to text(c.tag), "price" to text(c.price), "sold" to c.sold)

    internal fun outputs(img: Frame, texts: List<Text>, ocr: Ocr): Map<String, Any> {
        val out = linkedMapOf<String, Any>(
            "parse_lobby" to nul(Screens.parseLobby(texts)) {
                obj("mode" to it.mode.value, "level_title" to it.levelTitle, "start_button" to text(it.startButton),
                    "stars_button" to text(it.starsButton), "energy" to it.energy, "has_elite" to it.hasElite)
            },
            "is_star_list" to Screens.isStarList(texts),
            "parse_energy" to (Screens.parseEnergy(texts) ?: JSONObject.NULL),
            "parse_elite_dialog" to nul(Screens.parseEliteDialog(texts)) { obj("start_button" to text(it.startButton), "cost" to it.cost) },
            "parse_energy_popup" to nul(Screens.parseEnergyPopup(img, texts)) {
                obj("free_pack" to text(it.freePack), "video" to p(it.video), "videos_left" to it.videosLeft)
            },
            "update_required" to Screens.updateRequired(texts),
            "resume_prompt" to text(Screens.resumePrompt(texts)),
            "on_board" to onBoard(img, texts),
            "is_loading" to Screens.isLoading(texts),
            "close_button" to p(Screens.closeButton(img)),
            "tutorial_hand" to p(Screens.tutorialHand(img)),
            "footer_visible" to Screens.footerVisible(img),
            "popup_close" to text(Screens.popupClose(texts)),
            "lobby_behind" to Screens.lobbyBehind(texts),
            "outside_tap_clear" to (if (Screens.lobbyBehind(texts)) Screens.outsideTapClear(texts) else JSONObject.NULL),  // only used then
            "classify_level_screen" to Screens.classifyLevelScreen(img, texts).let { obj("kind" to it.kind.value, "tap" to p(it.tap)) },
            "game_speed" to (Screens.gameSpeed(texts) ?: JSONObject.NULL),
            "dice_ready" to Screens.diceReady(img),
            "dice_auto" to Screens.diceAuto(img),
            "parse_star_list" to (if (Screens.isStarList(texts)) JSONArray(Screens.parseStarList(img, texts, ocr).map {
                obj("number" to it.number, "header" to text(it.header), "button" to text(it.button), "stars" to it.stars)
            }) else JSONObject.NULL),
            "parse_skill_cards" to JSONArray(Screens.parseSkillCards(texts).map(::card)),
            "skill_reroll" to text(Screens.skillReroll(texts)),
            "parse_money" to (Screens.parseMoney(texts) ?: JSONObject.NULL),
            "parse_shop" to nul(Screens.parseShop(texts)) {
                obj("money" to it.money, "cards" to JSONArray(it.cards.map(::card)), "free_reroll" to text(it.freeReroll), "exit" to text(it.exit))
            },
            "parse_fortune_teller" to nul(Screens.parseFortuneTeller(texts)) {
                obj("orbs" to it.orbs, "balls" to JSONObject().apply { it.balls.forEach { (k, v) -> put(k.toString(), p(v)) } })
            },
            "back_arrow" to p(ModeScreens.backArrow(img)),
            "in_guild" to ModeScreens.inGuild(texts),
            "vip_cards_icon" to text(ModeScreens.vipCardsIcon(texts)),
            "vip_claim_all" to text(ModeScreens.vipClaimAll(texts)),
            "guild_hall" to text(ModeScreens.guildHall(texts)),
            "guild_hall_donate" to text(ModeScreens.guildHallDonate(texts)),
            "free_donation" to text(ModeScreens.freeDonation(texts)),
            "parse_patrol" to nul(ModeScreens.parsePatrol(texts)) { obj("claim" to text(it.claim), "quick" to text(it.quick), "elapsed" to it.elapsed) },
            "parse_quick_patrol" to nul(ModeScreens.parseQuickPatrol(img, texts)) {
                obj("video" to text(it.video), "energy" to text(it.energy), "energy_cost" to it.energyCost)
            },
            "is_modes_list" to ModeScreens.isModesList(texts),
            "parse_arena" to nul(ModeScreens.parseArena(img, texts, ocr)) { obj("challenge" to text(it.challenge), "tickets" to it.tickets) },
            "parse_arena_opponents" to nul(ModeScreens.parseArenaOpponents(texts, img, ocr)) {
                obj("own_power" to it.ownPower, "opponents" to JSONArray(it.opponents.map { o -> obj("power" to o.power, "challenge" to text(o.challenge)) }),
                    "free_refresh" to text(it.freeRefresh))
            },
            "parse_tower" to nul(ModeScreens.parseTower(texts)) { obj("challenge" to text(it.challenge), "tickets" to it.tickets) },
            "parse_dojo" to nul(ModeScreens.parseDojo(img, texts, ocr)) {
                obj("challenge" to text(it.challenge), "tickets" to it.tickets, "chest" to text(it.chest))
            },
            "parse_dive" to nul(ModeScreens.parseDive(texts)) { obj("challenge" to text(it.challenge), "tickets" to it.tickets) },
            "menu_daily" to text(ModeScreens.menuEntry(texts, L.MENU_DAILY)),
            "menu_mail" to text(ModeScreens.menuEntry(texts, L.MENU_MAIL)),
            "daily_claim" to text(ModeScreens.dailyClaim(texts)),
            "mail_claim_all" to text(ModeScreens.mailClaimAll(texts)),
            "parse_dungeon_popup" to nul(ModeScreens.parseDungeonPopup(texts)) {
                obj("difficulty" to it.difficulty, "tickets" to it.tickets, "challenge" to text(it.challenge), "sweep" to text(it.sweep), "ad" to text(it.ad))
            },
            "parse_raid" to nul(ModeScreens.parseRaid(texts)) { obj("challenge" to text(it.challenge), "attempts" to it.attempts) },
            "parse_skill_choice" to nul(ModeScreens.parseSkillChoice(texts)) {
                obj("cards" to JSONArray(it.cards.map(::p)), "chosen" to it.chosen, "needed" to it.needed, "learn" to text(it.learn))
            },
            "parse_fight_result" to nul(ModeScreens.parseFightResult(texts)) { obj("victory" to it.victory, "button" to text(it.button), "next_floor" to text(it.nextFloor)) },
        )
        for ((name, label) in listOf("ARENA" to L.ARENA, "DOJO" to L.DOJO, "TOWER" to L.TOWER, "DIVE" to L.DIVE, "MINES" to L.MINES, "PETS" to L.PETS)) {
            val entry = ModeScreens.modeEntry(texts, label)
            out["mode_entry_$name"] = text(entry)
            out["mode_closed_$name"] = entry?.let { ModeScreens.modeClosed(texts, it) } ?: JSONObject.NULL
        }
        return out
    }

    private fun same(a: Any?, b: Any?): Boolean = when {
        (a == null || a == JSONObject.NULL) -> b == null || b == JSONObject.NULL
        a is Number && b is Number -> a.toLong() == b.toLong() && a.toDouble() == b.toDouble()
        a is JSONArray && b is JSONArray -> a.length() == b.length() && (0 until a.length()).all { same(a.get(it), b.get(it)) }
        a is JSONObject && b is JSONObject -> a.keySet() == b.keySet() && a.keySet().all { same(a.get(it), b.get(it)) }
        else -> a == b
    }

    private fun near(a: Any?, b: Any?): Boolean {
        if (a == JSONObject.NULL || b == JSONObject.NULL) return a == b
        val x = a as JSONArray; val y = b as JSONArray
        return kotlin.math.abs(x.getInt(0) - y.getInt(0)) <= TEMPLATE_PX && kotlin.math.abs(x.getInt(1) - y.getInt(1)) <= TEMPLATE_PX
    }

    @Test
    fun everyParserMatchesTheDesktopBot() {
        Fixtures.loadTemplates()
        val cases = Fixtures.parity()
        val failures = ArrayList<String>()
        for (name in cases.keySet().sorted()) {
            val case = cases.getJSONObject(name)
            val (img, texts, ocr) = Fixtures.case(name, case)
            L.setLanguage(null)
            val detected = L.detectLanguage(texts)
            L.setLanguage(case.getString("lang"))
            val got = outputs(img, texts, ocr) + ("detect_language" to (detected ?: JSONObject.NULL))
            val want = case.getJSONObject("out")
            for (key in want.keySet()) {
                val ok = if (key in TEMPLATE_KEYS) near(want.get(key), got[key]) else same(want.get(key), got[key])
                if (!ok) failures.add("$name $key: python=${want.get(key)} kotlin=${got[key]}")
            }
        }
        assertTrue("${failures.size} differences:\n" + failures.joinToString("\n"), failures.isEmpty())
    }

    companion object {
        val TEMPLATE_KEYS = setOf("close_button", "tutorial_hand", "back_arrow")
        const val TEMPLATE_PX = 4
    }
}
