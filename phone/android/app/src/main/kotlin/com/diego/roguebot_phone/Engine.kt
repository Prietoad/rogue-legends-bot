package com.diego.roguebot_phone

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import com.diego.roguebot_phone.bot.BotError
import com.diego.roguebot_phone.bot.Catalog
import com.diego.roguebot_phone.bot.DebugSink
import com.diego.roguebot_phone.bot.Frame
import com.diego.roguebot_phone.bot.Log
import com.diego.roguebot_phone.bot.PaddleOcr
import com.diego.roguebot_phone.bot.Report
import com.diego.roguebot_phone.bot.RunRequest
import com.diego.roguebot_phone.bot.Runner
import com.diego.roguebot_phone.bot.Stopped
import com.diego.roguebot_phone.bot.Template
import com.diego.roguebot_phone.bot.Templates
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Runs the bot on a background thread and reports its log and status to the UI (MainActivity). */
object Engine {
    private val main = Handler(Looper.getMainLooper())
    private val time = SimpleDateFormat("HH:mm:ss", Locale.ROOT)
    private val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.ROOT)
    private const val LOG_LINES = 500
    const val ACTION_STOP = "com.diego.roguebot_phone.STOP"

    private val lines = ArrayDeque<String>()
    var listener: ((Map<String, Any?>) -> Unit)? = null  // set by MainActivity (main thread)
    @Volatile var stopRequested = false
        private set
    @Volatile private var thread: Thread? = null
    @Volatile var lastStatus: Map<String, Any?> = mapOf("type" to "status", "state" to "idle")
        private set
    private var ocr: PaddleOcr? = null

    /** The desktop bot's OCR (rapidocr's models, see PaddleOcr), loaded once: it takes a few seconds. */
    private fun ocr(context: Context): PaddleOcr = ocr ?: synchronized(this) {
        ocr ?: run {
            fun bytes(name: String) = context.assets.open("ocr/$name").use { it.readBytes() }
            val chars = org.json.JSONArray(String(bytes(PaddleOcr.REC_CHARACTERS), Charsets.UTF_8))
            PaddleOcr(bytes(PaddleOcr.DET_MODEL), bytes(PaddleOcr.REC_MODEL), (0 until chars.length()).map { chars.getString(it) })
        }.also { ocr = it }
    }

    val running: Boolean get() = thread?.isAlive == true

    fun history(): List<String> = synchronized(lines) { lines.toList() }

    private fun emit(event: Map<String, Any?>) {
        if (event["type"] == "status") lastStatus = event
        main.post { listener?.invoke(event) }
    }

    private fun log(context: Context, level: String, msg: String) {
        val line = "${time.format(Date())} ${level.padEnd(5)} $msg"
        synchronized(lines) {
            lines.addLast(line)
            while (lines.size > LOG_LINES) lines.removeFirst()
        }
        try {
            File(context.getExternalFilesDir(null), "bot.log").appendText(line + "\n")
        } catch (_: Exception) {
        }
        emit(mapOf("type" to "log", "line" to line))
    }

    private fun frame(bitmap: Bitmap): Frame {
        val px = IntArray(bitmap.width * bitmap.height)
        bitmap.getPixels(px, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        return Frame(bitmap.width, bitmap.height, px)
    }

    fun loadTemplates(context: Context) {
        fun load(name: String) = Template(frame(context.assets.open("templates/$name").use { BitmapFactory.decodeStream(it) }))
        Templates.closeX = load("close_x.png")
        Templates.backArrow = load("back_arrow.png")
        Templates.tutorialHand = load("tutorial_hand.png")
    }

    /** The phone's copy of the skill database, seeded from the desktop bot's data/skills.json. */
    private fun catalog(context: Context): Catalog {
        val file = File(context.filesDir, "skills.json")
        if (!file.exists()) context.assets.open("skills.json").use { input -> file.outputStream().use { input.copyTo(it) } }
        return Catalog(file)
    }

    private fun debugSink(context: Context) = DebugSink { img, name ->
        val dir = File(context.getExternalFilesDir(null), "debug").apply { mkdirs() }
        val file = File(dir, "${name}_${stamp.format(Date())}.png")
        val bitmap = Bitmap.createBitmap(img.pixels, img.width, img.height, Bitmap.Config.ARGB_8888)
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        file.absolutePath
    }

    fun dump(context: Context, service: BotService) {
        Engine.loadTemplates(context)
        val dir0 = File(context.getExternalFilesDir(null), "dumps").apply { mkdirs() }
        service.rawScreenshot().let { raw ->  // the phone's own screen, before mapping it to the reference size
            File(dir0, "raw_${stamp.format(Date())}.png").outputStream().use { raw.compress(Bitmap.CompressFormat.PNG, 100, it) }
            raw.recycle()
        }
        val img = service.screenshot()
        val texts = ocr(context).read(img)
        val dir = File(context.getExternalFilesDir(null), "dumps").apply { mkdirs() }
        val name = "dump_${stamp.format(Date())}"
        val bitmap = Bitmap.createBitmap(img.pixels, img.width, img.height, Bitmap.Config.ARGB_8888)
        File(dir, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        bitmap.recycle()
        val raw = service.map
        val json = org.json.JSONObject()
            .put("screen", raw?.let { "${it.width}x${it.height}" })
            .put("foreground", service.foregroundPackage())
            .put("texts", org.json.JSONArray(texts.map { org.json.JSONArray(listOf(it.text, it.x1, it.y1, it.x2, it.y2)) }))
            .put("language", com.diego.roguebot_phone.bot.L.detectLanguage(texts))
            .put("level_screen", com.diego.roguebot_phone.bot.Screens.classifyLevelScreen(img, texts).kind.value)
            .put("lobby", com.diego.roguebot_phone.bot.Screens.parseLobby(texts)?.toString())
        File(dir, "$name.json").writeText(json.toString(1))
    }

    fun ocrFixtures(context: Context) {
        val files = context.getExternalFilesDir(null)!!
        val out = org.json.JSONObject()
        for (file in File(files, "fixtures").listFiles { f -> f.name.endsWith(".png") }!!.sortedBy { it.name }) {
            val texts = ocr(context).read(Fixtures.load(file))
            out.put(file.name, org.json.JSONObject().put("texts",
                org.json.JSONArray(texts.map { org.json.JSONArray(listOf(it.text, it.x1, it.y1, it.x2, it.y2)) })))
        }
        File(files, "device_ocr_raw.json").writeText(out.toString())
    }

    fun emitError(key: String) = emit(mapOf("type" to "status", "state" to "error", "key" to key))

    /** Returns an error key if it cannot start. */
    fun start(context: Context, request: RunRequest): String? {
        val service = BotService.instance ?: return "err_service"
        if (running) return null
        val app = context.applicationContext
        stopRequested = false
        Log.sink = { level, msg -> log(app, level, msg) }
        main.post { service.setKeepAwake(true) }
        emit(mapOf("type" to "status", "state" to "running"))
        thread = Thread {
            var status: Map<String, Any?>
            try {
                loadTemplates(app)
                Log.info("Loading the text recognition")
                val report = Runner(service, ocr(app), catalog(app), debug = debugSink(app)).run(request)
                status = mapOf("type" to "status", "state" to "done", "report" to report.toMap())
            } catch (e: Stopped) {
                status = mapOf("type" to "status", "state" to "stopped")
            } catch (e: BotError) {
                Log.error("Error: ${e.key}")
                status = mapOf("type" to "status", "state" to "error", "key" to e.key, "args" to e.args.mapValues { it.value.toString() })
            } catch (e: Throwable) {
                if (stopRequested) {
                    status = mapOf("type" to "status", "state" to "stopped")
                } else {
                    val msg = e.message ?: (e.cause ?: e).toString()
                    Log.error("Error: $msg")
                    android.util.Log.e("roguebot", "Run failed", e)
                    status = mapOf("type" to "status", "state" to "error", "message" to msg)
                }
            }
            main.post { BotService.instance?.setKeepAwake(false) }
            CaptureService.stop(app)
            thread = null
            emit(status)
        }.apply { name = "roguebot"; start() }
        return null
    }

    fun stop() {
        stopRequested = true
        thread?.interrupt()
    }

    private fun Report.toMap(): Map<String, Any?> = mapOf(
        "results" to results.map { it.value },
        "repeat" to repeat,
        "dryRun" to dryRun,
        "parts" to parts.map { listOf(it.first, it.second) },
    )
}

class StopReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Engine.ACTION_STOP) Engine.stop()
    }
}

/**
 * Diagnostics (from a PC: adb shell am broadcast -a com.diego.roguebot_phone.DUMP): saves what the bot sees,
 * the screen mapped to the reference size (PNG) and its OCR (JSON), to the app's files/dumps folder. Read
 * only: it never taps. Used to calibrate a new phone and to compare the phone's OCR with the desktop's.
 */
class DumpReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val service = BotService.instance ?: return
        val app = context.applicationContext
        val pending = goAsync()
        Thread {
            try {
                Engine.dump(app, service)
            } finally {
                pending.finish()
            }
        }.start()
    }
}

/**
 * OCR check (from a PC, phone/tools/device_ocr.py): reads every PNG in files/fixtures with the app's OCR into
 * files/device_ocr_raw.json, so DeviceOcrTest can check the device reads like the PC.
 */
class OcrFixturesReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        Thread { Engine.ocrFixtures(app) }.start()  // minutes: longer than a broadcast may last
    }
}

private object Fixtures {
    fun load(file: File): Frame {
        val bitmap = BitmapFactory.decodeFile(file.absolutePath)
        val px = IntArray(bitmap.width * bitmap.height)
        bitmap.getPixels(px, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        bitmap.recycle()
        return Frame(bitmap.width, bitmap.height, px)
    }
}
