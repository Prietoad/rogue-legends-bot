package com.diego.roguebot_phone.bot

/** The user pressed Stop: raised by the next screenshot, tap or wait. */
class Stopped : RuntimeException("Stopped by the user")

/** Port of roguebot/device.py's interface. On the phone: the accessibility service (BotService). */
interface Device {
    /** Full frame, mapped to the reference resolution. */
    fun screenshot(): Frame
    fun tap(p: P, settle: Double = Config.UI_SETTLE)
    fun back(settle: Double = Config.UI_SETTLE)
    fun hold(p: P, seconds: Double, settle: Double = Config.UI_SETTLE)
    fun swipe(start: P, end: P, duration: Double = 0.6, settle: Double = Config.SCROLL_SETTLE)
    fun foregroundPackage(): String?
    /** Bring an app to the front (starts it if it is not running). */
    fun launch(pkg: String, settle: Double = Config.VIDEO_SETTLE)
    /** Sleep, raising Stopped as soon as Stop is pressed. */
    fun waitFor(seconds: Double)
}

/** time.monotonic / time.sleep, replaceable in tests. */
interface Clock {
    fun now(): Double
    fun sleep(seconds: Double)
}

object SystemClock : Clock {
    override fun now(): Double = System.nanoTime() / 1e9
    override fun sleep(seconds: Double) {
        try {
            Thread.sleep((seconds * 1000).toLong())
        } catch (e: InterruptedException) {
            throw Stopped()
        }
    }
}

/** Log lines go to the app's log view and file. */
object Log {
    @Volatile
    var sink: (String, String) -> Unit = { level, msg -> println("$level $msg") }

    fun info(msg: String) = sink("INFO", msg)
    fun warn(msg: String) = sink("WARN", msg)
    fun error(msg: String) = sink("ERROR", msg)
}

/** Saves failure screenshots (the app's debug folder); returns where. */
fun interface DebugSink {
    fun save(img: Frame, name: String): String
}
