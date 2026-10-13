package com.diego.roguebot_phone

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Rect
import android.view.Display
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import com.diego.roguebot_phone.bot.Config
import com.diego.roguebot_phone.bot.Device
import com.diego.roguebot_phone.bot.Frame
import com.diego.roguebot_phone.bot.P
import com.diego.roguebot_phone.bot.ScreenMap
import com.diego.roguebot_phone.bot.Stopped
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * The phone side of roguebot/device.py: screenshots (AccessibilityService.takeScreenshot, Android 11+),
 * taps and swipes (dispatchGesture), Back, the app in front, and opening the game. No game knowledge.
 * The user enables it once in Settings > Accessibility.
 */
class BotService : AccessibilityService(), Device {
    private val executor = Executors.newSingleThreadExecutor()
    private var keepAwake: View? = null
    @Volatile
    var map: ScreenMap? = null
        private set

    override fun onServiceConnected() {
        instance = this
    }

    override fun onDestroy() {
        instance = null
        Engine.stop()
        executor.shutdown()
        super.onDestroy()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        instance = null
        Engine.stop()
        return super.onUnbind(intent)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    private fun checkStop() {
        if (Engine.stopRequested || Thread.currentThread().isInterrupted) throw Stopped()
    }

    private fun sleep(seconds: Double) {
        try {
            Thread.sleep((seconds * 1000).toLong())
        } catch (e: InterruptedException) {
            throw Stopped()
        }
    }

    /** Raw screenshot: the screen capture (CaptureService) while it runs, else the accessibility one. */
    fun rawScreenshot(): Bitmap {
        val capture = CaptureService.instance ?: return accessibilityScreenshot()
        repeat(CAPTURE_WAITS) {  // the first mirrored frame takes a moment
            checkStop()
            capture.capture()?.let { return it }
            sleep(0.1)
        }
        throw IllegalStateException("No frame from the screen capture")
    }

    /** Accessibility screenshot (Android 11+), retried while Android rate-limits it (one every ~1/3 s). */
    private fun accessibilityScreenshot(): Bitmap {
        repeat(SCREENSHOT_TRIES) {
            checkStop()
            val latch = CountDownLatch(1)
            var bitmap: Bitmap? = null
            var error = 0
            takeScreenshot(Display.DEFAULT_DISPLAY, executor, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    val hw = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                    bitmap = hw?.copy(Bitmap.Config.ARGB_8888, false)
                    result.hardwareBuffer.close()
                    latch.countDown()
                }

                override fun onFailure(errorCode: Int) {
                    error = errorCode
                    latch.countDown()
                }
            })
            if (!latch.await(10, TimeUnit.SECONDS)) throw IllegalStateException("Screenshot timed out")
            bitmap?.let { return it }
            if (error != ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT) throw IllegalStateException("Screenshot failed ($error)")
            sleep(0.35)
        }
        throw IllegalStateException("Screenshot failed (rate limited)")
    }

    override fun screenshot(): Frame {
        val raw = rawScreenshot()
        if (raw.width > raw.height) throw IllegalStateException("The phone is in landscape: the game must be in portrait")
        val m = ScreenMap(raw.width, raw.height).also { map = it }
        val out = Bitmap.createBitmap(Config.SCREEN_W, Config.SCREEN_H, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(out)
        val paint = Paint(Paint.FILTER_BITMAP_FLAG)
        val bands = listOf(0, ScreenMap.TOP_BAND, ScreenMap.BOTTOM_BAND, Config.SCREEN_H)
        for (i in 0 until 3) {
            val y0 = bands[i]; val y1 = bands[i + 1]
            val src = Rect(0, m.sourceRow(y0), raw.width, if (y1 == Config.SCREEN_H) raw.height else m.sourceRow(y1))
            canvas.drawBitmap(raw, src, Rect(0, y0, Config.SCREEN_W, y1), paint)
        }
        raw.recycle()
        val pixels = IntArray(Config.SCREEN_W * Config.SCREEN_H)
        out.getPixels(pixels, 0, Config.SCREEN_W, 0, 0, Config.SCREEN_W, Config.SCREEN_H)
        out.recycle()
        return Frame(Config.SCREEN_W, Config.SCREEN_H, pixels)
    }

    private fun mapOrMeasure(): ScreenMap = map ?: run {
        val raw = rawScreenshot()
        ScreenMap(raw.width, raw.height).also { map = it; raw.recycle() }
    }

    private fun gesture(points: List<P>, durationMs: Long) {
        checkStop()
        val m = mapOrMeasure()
        val path = Path()
        points.forEachIndexed { i, p ->
            val (x, y) = m.toDevice(p)
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        val latch = CountDownLatch(1)
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceAtLeast(1))
        val ok = dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) = latch.countDown()
            override fun onCancelled(gestureDescription: GestureDescription?) = latch.countDown()
        }, null)
        if (!ok) throw IllegalStateException("The gesture was not accepted")
        latch.await(durationMs + 5000, TimeUnit.MILLISECONDS)
    }

    override fun tap(p: P, settle: Double) {
        gesture(listOf(p), TAP_MS)
        sleep(settle)
    }

    override fun back(settle: Double) {
        checkStop()
        performGlobalAction(GLOBAL_ACTION_BACK)
        sleep(settle)
    }

    override fun hold(p: P, seconds: Double, settle: Double) {
        gesture(listOf(p), (seconds * 1000).toLong())
        sleep(settle)
    }

    override fun swipe(start: P, end: P, duration: Double, settle: Double) {
        gesture(listOf(start, end), (duration * 1000).toLong())
        sleep(settle)
    }

    override fun foregroundPackage(): String? = rootInActiveWindow?.packageName?.toString()

    override fun launch(pkg: String, settle: Double) {
        checkStop()
        val intent = packageManager.getLaunchIntentForPackage(pkg) ?: return
        startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED))
        sleep(settle)
    }

    override fun waitFor(seconds: Double) {
        checkStop()
        sleep(seconds)
        checkStop()
    }

    /** While the bot runs: an invisible overlay keeps the screen on (the game pauses when it turns off). */
    fun setKeepAwake(on: Boolean) {
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        if (on && keepAwake == null) {
            val view = View(this)
            val params = WindowManager.LayoutParams(1, 1, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON, PixelFormat.TRANSLUCENT)
            wm.addView(view, params)
            keepAwake = view
        } else if (!on) {
            keepAwake?.let { wm.removeView(it) }
            keepAwake = null
        }
    }

    companion object {
        const val TAP_MS = 60L
        const val SCREENSHOT_TRIES = 10
        const val CAPTURE_WAITS = 50

        @Volatile
        var instance: BotService? = null
    }
}
