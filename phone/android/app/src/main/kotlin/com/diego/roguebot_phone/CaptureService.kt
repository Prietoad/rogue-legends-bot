package com.diego.roguebot_phone

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.util.DisplayMetrics
import android.view.WindowManager

/**
 * Screen capture with MediaProjection (the user allows it on each Start): a virtual display mirrors the
 * screen into an ImageReader, and screenshots read its latest image. Runs as a foreground service (Android
 * requires it for capturing), whose notification has the Stop button. Accessibility screenshots are only a
 * fallback: on some devices (e.g. MuMu Player) they come back black.
 */
class CaptureService : Service() {
    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private val thread = HandlerThread("capture").apply { start() }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val data = intent?.let { if (Build.VERSION.SDK_INT >= 33) it.getParcelableExtra(EXTRA_DATA, Intent::class.java) else @Suppress("DEPRECATION") it.getParcelableExtra(EXTRA_DATA) }
        if (data == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        val type = if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, notification(this), type) else startForeground(NOTIFICATION, notification(this))
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val p = mpm.getMediaProjection(Activity.RESULT_OK, data) ?: run {
            stopSelf()
            return START_NOT_STICKY
        }
        p.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                release()
                Engine.stop()  // the user revoked the capture (e.g. from the status bar)
            }
        }, Handler(thread.looper))
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(metrics)
        val r = ImageReader.newInstance(metrics.widthPixels, metrics.heightPixels, PixelFormat.RGBA_8888, 2)
        display = p.createVirtualDisplay("roguebot", metrics.widthPixels, metrics.heightPixels, metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, Handler(thread.looper))
        projection = p
        reader = r
        instance = this
        onReady?.invoke()
        onReady = null
        return START_NOT_STICKY
    }

    private var last: Bitmap? = null

    /** A copy of the latest mirrored frame (a still screen sends no new images: the last one is kept), or
     * null if none arrived yet. */
    @Synchronized
    fun capture(): Bitmap? {
        reader?.acquireLatestImage()?.use {
            val plane = it.planes[0]
            val rowPixels = plane.rowStride / plane.pixelStride
            val padded = Bitmap.createBitmap(rowPixels, it.height, Bitmap.Config.ARGB_8888)
            padded.copyPixelsFromBuffer(plane.buffer)
            val frame = if (rowPixels == it.width) padded else Bitmap.createBitmap(padded, 0, 0, it.width, it.height).also { padded.recycle() }
            last?.recycle()
            last = frame
        }
        return last?.copy(Bitmap.Config.ARGB_8888, false)
    }

    @Synchronized
    private fun release() {
        display?.release()
        reader?.close()
        last?.recycle()
        last = null
        display = null
        reader = null
        projection = null
        if (instance === this) instance = null
    }

    override fun onDestroy() {
        projection?.stop()
        release()
        thread.quitSafely()
        super.onDestroy()
    }

    companion object {
        private const val EXTRA_DATA = "data"
        private const val CHANNEL = "bot"
        private const val NOTIFICATION = 1

        @Volatile
        var instance: CaptureService? = null
        private var onReady: (() -> Unit)? = null

        /** Start capturing with the user's consent (the result of createScreenCaptureIntent), then run ready. */
        fun start(context: Context, consent: Intent, ready: () -> Unit) {
            onReady = ready
            context.startForegroundService(Intent(context, CaptureService::class.java).putExtra(EXTRA_DATA, consent))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, CaptureService::class.java))
        }

        /** "Running" with a Stop button: the game is in front while the bot plays, not this app. */
        private fun notification(context: Context): Notification {
            val nm = context.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Bot", NotificationManager.IMPORTANCE_LOW))
            val stop = PendingIntent.getBroadcast(context, 0, Intent(Engine.ACTION_STOP).setPackage(context.packageName),
                PendingIntent.FLAG_IMMUTABLE)
            val open = PendingIntent.getActivity(context, 0, Intent(context, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            return Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle("Rogue Legend bot")
                .setContentText("Running")
                .setOngoing(true)
                .setContentIntent(open)
                .addAction(Notification.Action.Builder(null, "Stop", stop).build())
                .build()
        }
    }
}
