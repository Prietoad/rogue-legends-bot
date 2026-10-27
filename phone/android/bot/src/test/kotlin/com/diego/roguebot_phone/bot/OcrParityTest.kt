package com.diego.roguebot_phone.bot

import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import kotlin.math.abs

/**
 * The phone's OCR (PaddleOcr: rapidocr's models and pipeline in Kotlin) against the desktop OCR, on every
 * fixture: run the phone OCR on the screenshot, feed what it reads to the parsers, and compare their results
 * with the desktop bot's. Texts may sit a few pixels apart (rapidocr's rotated boxes vs our rectangles).
 */
class OcrParityTest {
    @After
    fun reset() = L.setLanguage(null)

    private fun key(s: String) = normalize(s).filter { it.isLetterOrDigit() }

    private fun same(a: Any?, b: Any?): Boolean {
        val na = a == null || a == JSONObject.NULL
        val nb = b == null || b == JSONObject.NULL
        if (na || nb) return na == nb
        return when {
            a is JSONArray && b is JSONArray && isText(a) && isText(b) -> near(center(a), center(b)) && key(a.getString(0)) == key(b.getString(0))
            a is JSONArray && b is JSONArray && a.length() == 2 && a.opt(0) is Number && b.opt(0) is Number ->
                near(a.getInt(0) to a.getInt(1), b.getInt(0) to b.getInt(1))
            a is JSONArray && b is JSONArray -> a.length() == b.length() && (0 until a.length()).all { same(a.get(it), b.get(it)) }
            a is JSONObject && b is JSONObject -> a.keySet() == b.keySet() && a.keySet().all { k -> k in FREE_TEXT || same(a.get(k), b.get(k)) }
            a is Number && b is Number -> a.toLong() == b.toLong()
            else -> a == b
        }
    }

    private fun isText(a: JSONArray) = a.length() == 5 && a.opt(0) is String
    private fun center(a: JSONArray) = (a.getInt(1) + a.getInt(3)) / 2 to (a.getInt(2) + a.getInt(4)) / 2
    private fun near(a: Pair<Int, Int>, b: Pair<Int, Int>) = abs(a.first - b.first) <= TOLERANCE && abs(a.second - b.second) <= TOLERANCE

    @Test
    fun phoneOcrLeadsToTheSameDecisions() {
        Fixtures.loadTemplates()
        val ocr = Fixtures.paddleOcr()
        val cases = Fixtures.parity()
        val reads = Fixtures.phoneReads(cases.keySet())
        val failures = ArrayList<String>()
        var textMisses = 0
        var textTotal = 0
        for (name in cases.keySet().sorted()) {
            val case = cases.getJSONObject(name)
            val img = Fixtures.fixture(name)
            val texts = reads.getValue(name)
            val desktop = Fixtures.texts(case.getJSONArray("texts"))
            textTotal += desktop.size
            textMisses += desktop.count { d -> texts.none { it.norm == d.norm && abs(it.center.x - d.center.x) <= TOLERANCE && abs(it.center.y - d.center.y) <= TOLERANCE } }
            L.setLanguage(null)
            val detected = L.detectLanguage(texts)
            L.setLanguage(case.getString("lang"))
            val got = ParityTest().outputs(img, texts, ocr) + ("detect_language" to (detected ?: JSONObject.NULL))
            val want = case.getJSONObject("out")
            for (key in want.keySet()) {
                if ("$name $key" in KNOWN) continue
                if (!same(want.get(key), got[key])) failures.add("$name $key: desktop=${want.get(key)} phone=${got[key]}")
            }
        }
        val report = "texts read differently: $textMisses of $textTotal\n${failures.size} differences:\n" + failures.joinToString("\n")
        File("build/ocr_parity.txt").writeText(report)
        assertTrue(report, failures.isEmpty())
    }

    companion object {
        const val TOLERANCE = 12
        val FREE_TEXT = setOf("level_title", "name", "description")  // read with small differences ("II"/"Il", "Critical-Mastery"); skills are keyed by letters
        /** Known differences, each harmless. */
        val KNOWN = setOf(
            "dojo_chest_claim.png parse_dojo",               // a reward popup over the dojo: tapped away before the dojo screen is used
            "en_patrol.png vip_cards_icon",                  // "ViP" instead of "Cards": the other line of the same icon
            "lobby_limited_offer_popup.png classify_level_screen",  // reads "cualquier lugar" right (desktop: "cualquierlugar"); a lobby popup, closed by its text
            "lobby_limited_offer_popup.png popup_close",
            "level_shop_2.png parse_skill_cards",             // sale price: the phone reads the right "48", the desktop "87"
            "level_shop_2.png parse_shop",
            "guild_map_garbled.png guild_hall",              // the phone reads "Sala de" right (desktop: "Sa Slde", so its line "Gremio"): the same castle label
        )
    }
}
