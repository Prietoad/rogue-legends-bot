package com.diego.roguebot_phone.bot

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import javax.imageio.ImageIO

/** Test data shared with the desktop bot: tests/fixtures screenshots, roguebot/templates, parity.json. */
object Fixtures {
    val ROOT: File = File("../../..").canonicalFile  // tests run from phone/android/bot

    fun image(file: File): Frame {
        val bi = ImageIO.read(file)
        val px = IntArray(bi.width * bi.height)
        bi.getRGB(0, 0, bi.width, bi.height, px, 0, bi.width)
        return Frame(bi.width, bi.height, px)
    }

    fun fixture(name: String): Frame = image(File(ROOT, "tests/fixtures/$name"))

    fun loadTemplates() {
        val dir = File(ROOT, "roguebot/templates")
        Templates.closeX = Template(image(File(dir, "close_x.png")))
        Templates.backArrow = Template(image(File(dir, "back_arrow.png")))
        Templates.tutorialHand = Template(image(File(dir, "tutorial_hand.png")))
    }

    /** The desktop bot's OCR models (from the rapidocr Python package, by phone/tools/ocr_models.py). */
    val modelsDir: File by lazy {
        val dir = File("build/ocr").absoluteFile
        val p = ProcessBuilder("python", File(ROOT, "phone/tools/ocr_models.py").path, dir.path).inheritIO().start()
        check(p.waitFor() == 0) { "phone/tools/ocr_models.py failed" }
        dir
    }

    private val ocr by lazy {
        val chars = JSONArray(File(modelsDir, PaddleOcr.REC_CHARACTERS).readText())
        PaddleOcr(File(modelsDir, PaddleOcr.DET_MODEL).readBytes(), File(modelsDir, PaddleOcr.REC_MODEL).readBytes(),
            (0 until chars.length()).map { chars.getString(it) })
    }

    fun paddleOcr(): PaddleOcr = ocr

    private val parityJson by lazy { JSONObject(javaClass.classLoader!!.getResource("parity.json")!!.readText()) }

    fun parity(): JSONObject = parityJson

    fun texts(a: JSONArray): List<Text> = (0 until a.length()).map {
        val t = a.getJSONArray(it)
        Text(t.getString(0), t.getInt(1), t.getInt(2), t.getInt(3), t.getInt(4))
    }

    /** OCR that replays what the desktop OCR read on this fixture (full frame and region crops). */
    class RecordedOcr(private val full: List<Text>, private val regions: Map<String, List<Text>>) : Ocr {
        override fun read(img: Frame, region: Region?): List<Text> =
            if (region == null) full else regions["${region.x1},${region.y1},${region.x2},${region.y2}"] ?: emptyList()
    }

    data class Case(val img: Frame, val texts: List<Text>, val ocr: Ocr)

    fun case(name: String, case: JSONObject = parity().getJSONObject(name)): Case {
        val texts = texts(case.getJSONArray("texts"))
        val regions = case.getJSONObject("regions").let { r -> r.keySet().associateWith { texts(r.getJSONArray(it)) } }
        return Case(fixture(name), texts, RecordedOcr(texts, regions))
    }
}
