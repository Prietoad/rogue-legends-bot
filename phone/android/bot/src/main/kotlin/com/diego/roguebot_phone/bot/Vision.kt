package com.diego.roguebot_phone.bot

import java.text.Normalizer
import kotlin.math.sqrt

/** Port of roguebot/vision.py: OCR text boxes, label matching, images and template matching. */

data class P(val x: Int, val y: Int)

data class Region(val x1: Int, val y1: Int, val x2: Int, val y2: Int)

data class Text(val text: String, val x1: Int, val y1: Int, val x2: Int, val y2: Int) {
    val center: P get() = P((x1 + x2) / 2, (y1 + y2) / 2)
    val norm: String by lazy { normalize(text) }  // matched against dozens of labels per frame
}

private val COMBINING = Regex("\\p{M}+")

/** Lowercase without accents, so "Desafío" == "desafio". */
fun normalize(s: String): String =
    COMBINING.replace(Normalizer.normalize(s, Normalizer.Form.NFKD), "").lowercase().trim()

private val LEVEL_RE = Regex("^\\s*(\\d+)\\s*\\.")

/** "12. Arenas Movedizas II" -> 12. */
fun parseLevelNumber(s: String): Int? = LEVEL_RE.find(s)?.groupValues?.get(1)?.toInt()

fun String.isDigits(): Boolean = isNotEmpty() && all { it in '0'..'9' }

/** True if the text matches any variant of the label (active language). */
fun matches(t: Text, label: Label, exact: Boolean = false): Boolean =
    label.variants.any { if (exact) t.norm == it else it in t.norm }

fun matches(t: Text, s: String, exact: Boolean = false): Boolean {
    val v = normalize(s)
    return if (exact) t.norm == v else v in t.norm
}

fun find(texts: List<Text>, label: Label, exact: Boolean = false): Text? = texts.firstOrNull { matches(it, label, exact) }

fun inRange(v: Int, r: IntRange): Boolean = v in r

/** An image in reference coordinates (1440x2560), ARGB pixels row by row. */
class Frame(val width: Int, val height: Int, val pixels: IntArray) {
    fun argb(x: Int, y: Int): Int = pixels[y * width + x]
    fun r(x: Int, y: Int): Int = (argb(x, y) shr 16) and 0xFF
    fun g(x: Int, y: Int): Int = (argb(x, y) shr 8) and 0xFF
    fun b(x: Int, y: Int): Int = argb(x, y) and 0xFF

    /** Fraction of pixels in [x1,x2) x [y1,y2) (clamped to the frame) for which test(r, g, b) holds. */
    fun fraction(x1: Int, y1: Int, x2: Int, y2: Int, test: (Int, Int, Int) -> Boolean): Double {
        val ax = x1.coerceIn(0, width); val bx = x2.coerceIn(0, width)
        val ay = y1.coerceIn(0, height); val by = y2.coerceIn(0, height)
        var n = 0; var hit = 0
        for (y in ay until by) for (x in ax until bx) {
            val c = pixels[y * width + x]
            n++
            if (test((c shr 16) and 0xFF, (c shr 8) and 0xFF, c and 0xFF)) hit++
        }
        return if (n == 0) 0.0 else hit.toDouble() / n
    }

    /** Mean (r, g, b) over [x1,x2) x [y1,y2). */
    fun mean(x1: Int, y1: Int, x2: Int, y2: Int): DoubleArray {
        val ax = x1.coerceIn(0, width); val bx = x2.coerceIn(0, width)
        val ay = y1.coerceIn(0, height); val by = y2.coerceIn(0, height)
        var r = 0.0; var g = 0.0; var b = 0.0; var n = 0
        for (y in ay until by) for (x in ax until bx) {
            val c = pixels[y * width + x]
            r += (c shr 16) and 0xFF; g += (c shr 8) and 0xFF; b += c and 0xFF; n++
        }
        return if (n == 0) doubleArrayOf(0.0, 0.0, 0.0) else doubleArrayOf(r / n, g / n, b / n)
    }

    fun crop(r: Region): Frame {
        val x1 = r.x1.coerceIn(0, width); val x2 = r.x2.coerceIn(x1, width)
        val y1 = r.y1.coerceIn(0, height); val y2 = r.y2.coerceIn(y1, height)
        val w = x2 - x1; val h = y2 - y1
        val out = IntArray(w * h)
        for (y in 0 until h) System.arraycopy(pixels, (y1 + y) * width + x1, out, y * w, w)
        return Frame(w, h, out)
    }

    /** Bilinear resize by [scale] (cv2.resize's default). */
    fun scaled(scale: Double): Frame {
        val w = Math.round(width * scale).toInt(); val h = Math.round(height * scale).toInt()
        val out = IntArray(w * h)
        for (y in 0 until h) {
            val fy = ((y + 0.5) / scale - 0.5).coerceIn(0.0, height - 1.0)
            val y0 = fy.toInt(); val y1 = minOf(y0 + 1, height - 1); val ty = fy - y0
            for (x in 0 until w) {
                val fx = ((x + 0.5) / scale - 0.5).coerceIn(0.0, width - 1.0)
                val x0 = fx.toInt(); val x1 = minOf(x0 + 1, width - 1); val tx = fx - x0
                var argb = 0xFF000000.toInt()
                for (shift in intArrayOf(16, 8, 0)) {
                    fun ch(px: Int, py: Int) = (pixels[py * width + px] shr shift) and 0xFF
                    val v = (ch(x0, y0) * (1 - tx) + ch(x1, y0) * tx) * (1 - ty) + (ch(x0, y1) * (1 - tx) + ch(x1, y1) * tx) * ty
                    argb = argb or (Math.round(v).toInt().coerceIn(0, 255) shl shift)
                }
                out[y * w + x] = argb
            }
        }
        return Frame(w, h, out)
    }

    companion object {
        fun blank(width: Int = Config.SCREEN_W, height: Int = Config.SCREEN_H) =
            Frame(width, height, IntArray(width * height) { 0xFF000000.toInt() })
    }
}

/** OpenCV's 8-bit HSV (H in [0,180), S and V in [0,255]), with its fixed-point tables, so values match exactly. */
private val SDIV = IntArray(256) { if (it == 0) 0 else Math.rint((255 shl 12) / it.toDouble()).toInt() }
private val HDIV = IntArray(256) { if (it == 0) 0 else Math.rint((180 shl 12) / (6.0 * it)).toInt() }

fun hsv(r: Int, g: Int, b: Int): IntArray {
    val v = maxOf(r, g, b)
    val diff = v - minOf(r, g, b)
    val vr = if (v == r) -1 else 0
    val vg = if (v == g) -1 else 0
    val s = (diff * SDIV[v] + (1 shl 11)) shr 12
    var h = (vr and (g - b)) + (vr.inv() and ((vg and (b - r + 2 * diff)) + (vg.inv() and (r - g + 4 * diff))))
    h = (h * HDIV[diff] + (1 shl 11)) shr 12
    if (h < 0) h += 180
    return intArrayOf(h, s, v)
}

interface Ocr {
    /** OCR the frame, or only the region. Coordinates are always full-frame. */
    fun read(img: Frame, region: Region? = null): List<Text>
}

/**
 * Template matching (OpenCV TM_CCOEFF_NORMED, as in the desktop bot), coarse to fine so it runs on a
 * phone: grey 1/8-scale search for candidates, then a colour 1/2-scale check around each. The score
 * gaps between "shown" and "not shown" are wide (e.g. 0.998 vs 0.61), so the reduced scale keeps them.
 */
class Template(val src: Frame) {
    val width = src.width
    val height = src.height
    internal val coarse = Plane.grey(src, COARSE)
    internal val fine = Planes.color(src, FINE)

    companion object {
        const val COARSE = 8
        const val FINE = 2
        const val CANDIDATES = 6
    }
}

internal class Plane(val w: Int, val h: Int, val v: DoubleArray) {
    companion object {
        fun grey(f: Frame, k: Int): Plane {
            val w = f.width / k; val h = f.height / k
            val v = DoubleArray(w * h)
            for (y in 0 until h) for (x in 0 until w) {
                var s = 0.0
                for (dy in 0 until k) for (dx in 0 until k) {
                    val c = f.pixels[(y * k + dy) * f.width + x * k + dx]
                    s += ((c shr 16) and 0xFF) + ((c shr 8) and 0xFF) + (c and 0xFF)
                }
                v[y * w + x] = s / (3 * k * k)
            }
            return Plane(w, h, v)
        }
    }
}

internal class Planes(val w: Int, val h: Int, val c: Array<DoubleArray>) {
    companion object {
        fun color(f: Frame, k: Int, region: Region? = null): Planes {
            val ox = region?.x1 ?: 0; val oy = region?.y1 ?: 0
            val fw = (region?.let { it.x2 - it.x1 } ?: f.width); val fh = (region?.let { it.y2 - it.y1 } ?: f.height)
            val w = fw / k; val h = fh / k
            val c = Array(3) { DoubleArray(w * h) }
            for (y in 0 until h) for (x in 0 until w) {
                var r = 0.0; var g = 0.0; var b = 0.0
                for (dy in 0 until k) for (dx in 0 until k) {
                    val px = f.pixels[(oy + y * k + dy) * f.width + ox + x * k + dx]
                    r += (px shr 16) and 0xFF; g += (px shr 8) and 0xFF; b += px and 0xFF
                }
                val n = (k * k).toDouble()
                c[0][y * w + x] = r / n; c[1][y * w + x] = g / n; c[2][y * w + x] = b / n
            }
            return Planes(w, h, c)
        }
    }
}

/** TM_CCOEFF_NORMED of template channels t over image channels img at (x, y) (means per channel). */
private fun ccoeff(img: Array<DoubleArray>, iw: Int, x: Int, y: Int, t: Array<DoubleArray>, tw: Int, th: Int): Double {
    val n = (tw * th).toDouble()
    var num = 0.0; var tt = 0.0; var ii = 0.0
    for (ch in t.indices) {
        val tc = t[ch]; val ic = img[ch]
        var tSum = 0.0; var iSum = 0.0; var ti = 0.0; var t2 = 0.0; var i2 = 0.0
        for (j in 0 until th) {
            val row = (y + j) * iw + x
            val trow = j * tw
            for (i in 0 until tw) {
                val a = tc[trow + i]; val b = ic[row + i]
                tSum += a; iSum += b; ti += a * b; t2 += a * a; i2 += b * b
            }
        }
        num += ti - tSum * iSum / n
        tt += t2 - tSum * tSum / n
        ii += i2 - iSum * iSum / n
    }
    val den = sqrt(maxOf(tt, 0.0) * maxOf(ii, 0.0))
    return if (den < 1e-9) 0.0 else num / den
}

/** Center of the best match of the template, or null if its score is below threshold. */
fun matchTemplate(img: Frame, t: Template, threshold: Double): P? = bestMatch(img, t)?.takeIf { it.second >= threshold }?.first

fun bestMatch(img: Frame, t: Template): Pair<P, Double>? {
    val c = Template.COARSE
    val plane = Plane.grey(img, c)
    val tp = t.coarse
    val cands = ArrayList<Triple<Int, Int, Double>>()
    for (y in 0..plane.h - tp.h) for (x in 0..plane.w - tp.w) {
        cands.add(Triple(x, y, ccoeff(arrayOf(plane.v), plane.w, x, y, arrayOf(tp.v), tp.w, tp.h)))
    }
    cands.sortByDescending { it.third }
    val picked = ArrayList<Triple<Int, Int, Double>>()
    for (cand in cands) {
        if (picked.size >= Template.CANDIDATES) break
        if (picked.none { kotlin.math.abs(it.first - cand.first) <= 2 && kotlin.math.abs(it.second - cand.second) <= 2 }) picked.add(cand)
    }
    val f = Template.FINE
    val tf = t.fine
    var best: Pair<P, Double>? = null
    for ((cx, cy, _) in picked) {
        // Search ±(c) full-res px around the coarse hit, at 1/2 scale.
        val x0 = (cx * c - c).coerceAtLeast(0); val y0 = (cy * c - c).coerceAtLeast(0)
        val x1 = (cx * c + c + t.width).coerceAtMost(img.width); val y1 = (cy * c + c + t.height).coerceAtMost(img.height)
        val win = Planes.color(img, f, Region(x0, y0, x1, y1))
        for (y in 0..win.h - tf.h) for (x in 0..win.w - tf.w) {
            val s = ccoeff(win.c, win.w, x, y, tf.c, tf.w, tf.h)
            if (best == null || s > best.second) best = P(x0 + x * f + t.width / 2, y0 + y * f + t.height / 2) to s
        }
    }
    return best
}
