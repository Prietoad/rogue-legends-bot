package com.diego.roguebot_phone.bot

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
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

    fun fixture(name: String): Frame = image(File(ROOT, "tests/fixtures/$name"))  // not kept: 15 MB each decoded

    private val phoneReads = ConcurrentHashMap<String, List<Text>>()
    // Reads at once (measured best on 16 cores: ONNX Runtime already uses threads per read, and the 2 GB test
    // heap thrashes with more; a decoded screenshot and its float planes are ~150 MB).
    private val OCR_THREADS = maxOf(2, Runtime.getRuntime().availableProcessors() / 4)

    /** The phone OCR's full-frame read of each fixture: read once, in parallel (it was most of the suite's time,
     *  and OcrParityTest and DeviceOcrTest read the same fixtures). Reads are also kept in build/ocr_cache,
     *  keyed by the screenshot, the models and PaddleOcr.kt, so later runs skip OCR; `gradlew clean` empties it. */
    fun phoneReads(names: Collection<String>): Map<String, List<Text>> {
        val pool = Executors.newFixedThreadPool(OCR_THREADS)
        try {
            names.filter { !phoneReads.containsKey(it) }.map { n -> pool.submit { phoneReads[n] = cachedRead(n) } }.forEach { it.get() }
        } finally {
            pool.shutdown()
        }
        return names.associateWith { phoneReads.getValue(it) }
    }

    private val cacheDir = File("build/ocr_cache").apply { mkdirs() }
    private val engineKey by lazy {
        sha1(listOf(File(modelsDir, PaddleOcr.DET_MODEL), File(modelsDir, PaddleOcr.REC_MODEL), File(modelsDir, PaddleOcr.REC_CHARACTERS),
            File("src/main/kotlin/com/diego/roguebot_phone/bot/PaddleOcr.kt")).map { it.readBytes() })
    }

    private fun cachedRead(name: String): List<Text> {
        val file = File(ROOT, "tests/fixtures/$name")
        val cached = File(cacheDir, sha1(listOf(engineKey.toByteArray(), file.readBytes())) + ".json")
        if (cached.exists()) runCatching { return texts(JSONArray(cached.readText())) }
        val read = paddleOcr().read(image(file))
        val tmp = File(cacheDir, "${cached.name}.${Thread.currentThread().id}.tmp")
        tmp.writeText(JSONArray(read.map { JSONArray(listOf(it.text, it.x1, it.y1, it.x2, it.y2)) }).toString())
        tmp.renameTo(cached) || tmp.delete()  // another thread wrote it first: same content
        return read
    }

    private fun sha1(parts: List<ByteArray>): String {
        val md = MessageDigest.getInstance("SHA-1")
        parts.forEach { md.update(it); md.update(0) }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

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
