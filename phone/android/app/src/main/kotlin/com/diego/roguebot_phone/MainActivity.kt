package com.diego.roguebot_phone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import com.diego.roguebot_phone.bot.Build as BotBuild
import android.media.projection.MediaProjectionManager
import com.diego.roguebot_phone.bot.Config
import com.diego.roguebot_phone.bot.RunRequest
import com.diego.roguebot_phone.bot.buildRequest
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/** Bridges the Flutter UI and the bot engine: Start/Stop, status, log and the accessibility setting. */
class MainActivity : FlutterActivity() {
    companion object {
        const val CAPTURE_REQUEST = 7
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        MethodChannel(messenger, "roguebot/engine").setMethodCallHandler { call, result ->
            when (call.method) {
                "state" -> result.success(mapOf(
                    "serviceEnabled" to (BotService.instance != null),
                    "gameInstalled" to gameInstalled(),
                    "running" to Engine.running,
                    "status" to Engine.lastStatus,
                    "log" to Engine.history(),
                ))
                "openAccessibility" -> {
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    result.success(null)
                }
                "start" -> {
                    askNotifications()
                    try {
                        @Suppress("UNCHECKED_CAST")
                        val build = BotBuild(call.argument<String>("nature")!!, call.argument<List<String>>("order")!!,
                            call.argument<Int>("supportEvery"))
                        val request = buildRequest(call.argument("mode")!!, call.argument("source")!!, call.argument("level")!!,
                            call.argument("full")!!, build, call.argument("loop")!!, call.argument("ads")!!)
                        when {
                            BotService.instance == null -> result.success("err_service")
                            Engine.running -> result.success(null)
                            else -> {
                                pending = request
                                val mpm = getSystemService(MediaProjectionManager::class.java)
                                @Suppress("DEPRECATION")
                                startActivityForResult(mpm.createScreenCaptureIntent(), CAPTURE_REQUEST)
                                result.success(null)
                            }
                        }
                    } catch (e: IllegalArgumentException) {
                        result.success(e.message)
                    }
                }
                "stop" -> {
                    Engine.stop()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
        EventChannel(messenger, "roguebot/events").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                Engine.listener = { events.success(it) }
            }

            override fun onCancel(arguments: Any?) {
                Engine.listener = null
            }
        })
    }

    private var pending: RunRequest? = null

    /** The user's answer to "start capturing the screen?": start the capture, then the bot. */
    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != CAPTURE_REQUEST) return
        val request = pending ?: return
        pending = null
        if (resultCode != RESULT_OK || data == null) {
            Engine.emitError("err_capture")
            return
        }
        val app = applicationContext
        CaptureService.start(app, data) { Engine.start(app, request)?.let { Engine.emitError(it) } }
    }

    private fun gameInstalled(): Boolean = try {
        packageManager.getPackageInfo(Config.PACKAGE, 0)
        true
    } catch (e: PackageManager.NameNotFoundException) {
        false
    }

    private fun askNotifications() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }
}
