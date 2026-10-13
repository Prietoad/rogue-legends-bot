package com.diego.roguebot_phone.bot

/** Test doubles: a device that records input, a clock that only moves when slept, scripted screens. */

class FakeClock(var t: Double = 0.0) : Clock {
    override fun now() = t
    override fun sleep(seconds: Double) {
        t += maxOf(seconds, 0.01)
    }
}

open class FakeDevice : Device {
    val taps = ArrayList<P>()
    val holds = ArrayList<P>()
    val swipes = ArrayList<Pair<P, P>>()
    val actions = ArrayList<String>()  // "back" / "launch"
    val apps = ArrayDeque<String>()    // foreground packages to report in order (then the game)
    var screen: () -> Frame = { Frame.blank() }

    override fun screenshot() = screen()
    override fun tap(p: P, settle: Double) { taps.add(p) }
    override fun back(settle: Double) { actions.add("back") }
    override fun hold(p: P, seconds: Double, settle: Double) { holds.add(p) }
    override fun swipe(start: P, end: P, duration: Double, settle: Double) { swipes.add(start to end) }
    override fun foregroundPackage(): String? = apps.removeFirstOrNull() ?: Config.PACKAGE
    override fun launch(pkg: String, settle: Double) { actions.add("launch") }
    override fun waitFor(seconds: Double) {}
}

/** Screens shown in order; the last one stays (like a screen that does not change any more). */
class Script(frames: List<Pair<Frame, List<Text>>>) {
    private val queue = ArrayDeque(frames)
    var last: Pair<Frame, List<Text>> = frames.lastOrNull() ?: (Frame.blank() to emptyList())
    fun next(): Pair<Frame, List<Text>> = (queue.removeFirstOrNull() ?: last).also { last = it }

    companion object {
        val BLANK = Frame.blank()  // shared by text-only screens (never written)
        fun texts(vararg screens: List<Text>) = Script(screens.map { BLANK to it })
    }
}

/** OCR whose region reads come from a function of the frame (e.g. the dojo ticket crop). */
class FakeOcr(private val regions: (Frame, Region) -> List<Text> = { _, _ -> emptyList() }) : Ocr {
    override fun read(img: Frame, region: Region?): List<Text> = if (region == null) emptyList() else regions(img, region)
}

/** A Navigator whose captures follow a script; go_to_lobby only counts (unless real = true). */
class ScriptNav(device: Device, val script: Script, ocr: Ocr = FakeOcr(), clock: Clock = FakeClock(), ads: Boolean = false,
                private val real: Boolean = false) : Navigator(device, ocr, ads = ads, clock = clock) {
    var lobbyVisits = 0
    var lobbyError: NavigationError? = null

    override fun capture() = script.next()

    override fun goToLobby(): Lobby {
        lobbyVisits++
        lobbyError?.let { throw it }
        return if (real) super.goToLobby() else Lobby(Mode.NORMAL, null, Text("INICIO", 0, 0, 1, 1), null, null)
    }
}

fun t(text: String, x1: Int, y1: Int, x2: Int, y2: Int) = Text(text, x1, y1, x2, y2)

/** A blank frame with things drawn on it. */
class Canvas(val frame: Frame = Frame.blank()) {
    fun fill(x1: Int, y1: Int, x2: Int, y2: Int, r: Int, g: Int, b: Int) = apply {
        val c = (0xFF shl 24) or (r shl 16) or (g shl 8) or b
        for (y in y1 until y2) for (x in x1 until x2) frame.pixels[y * frame.width + x] = c
    }

    /** Paste an image (e.g. a template) centered at (cx, cy). */
    fun paste(img: Frame, cx: Int, cy: Int) = apply {
        val x0 = cx - img.width / 2; val y0 = cy - img.height / 2
        for (y in 0 until img.height) for (x in 0 until img.width) frame.pixels[(y0 + y) * frame.width + x0 + x] = img.pixels[y * img.width + x]
    }

    /** The bottom tab bar of main screens, at full brightness. */
    fun footer() = fill(60, 2380, 300, 2440, 123, 55, 80).fill(1140, 2380, 1380, 2440, 91, 86, 95)

    /** The quick patrol's cyan lightning left of an "x10" label centered at (x, y). */
    fun lightning(x: Int, y: Int) = fill(x - 150, y - 45, x - 35, y + 45, 0, 200, 255)
}

fun template(name: String): Frame = Fixtures.image(java.io.File(Fixtures.ROOT, "roguebot/templates/$name"))
