package com.diego.roguebot_phone.bot

import kotlin.math.roundToInt

/**
 * Maps a phone screen to the 1440x2560 (9:16) reference the bot works in.
 *
 * A 9:16 screen is just scaled. Taller phones (e.g. 20:9) show the same UI with extra height: the game
 * (Unity, scaled to the width) keeps its top bar at the top, its footer at the bottom and its popups
 * centered. So the reference frame is built from three bands: the top band from the top of the screen,
 * the bottom band from the bottom, and the middle band from the screen's center. Taps go back through
 * the same bands. Wider-than-9:16 screens are not supported.
 */
class ScreenMap(val width: Int, val height: Int) {
    val scale: Double = width.toDouble() / Config.SCREEN_W           // reference -> device px
    private val extra: Double = height / scale - Config.SCREEN_H        // reference px the phone has in addition

    init {
        require(extra >= -Config.SCREEN_H * 0.01) { "Screen ${width}x$height is wider than 9:16" }
    }

    /** Device y of a reference y. */
    fun deviceY(y: Int): Int = (when {
        y < TOP_BAND -> y.toDouble()
        y >= BOTTOM_BAND -> y + maxOf(extra, 0.0)
        else -> y + maxOf(extra, 0.0) / 2
    } * scale).roundToInt().coerceIn(0, height - 1)

    fun toDevice(p: P): Pair<Float, Float> =
        ((p.x * scale).roundToInt().coerceIn(0, width - 1)).toFloat() to deviceY(p.y).toFloat()

    /** Reference row -> device row, for building the reference frame. */
    fun sourceRow(y: Int): Int = deviceY(y)

    companion object {
        const val TOP_BAND = 853     // reference rows [0, 853) are anchored to the top
        const val BOTTOM_BAND = 1707 // rows [1707, 2560) to the bottom; the rest to the center
    }
}
