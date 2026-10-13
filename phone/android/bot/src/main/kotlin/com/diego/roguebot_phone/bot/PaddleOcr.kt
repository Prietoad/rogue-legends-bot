package com.diego.roguebot_phone.bot

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * The desktop bot's OCR on the phone: rapidocr's pipeline (PaddleOCR PP-OCRv6 det + rec models, the same
 * ONNX files) re-implemented with ONNX Runtime, so the phone reads the game exactly like the desktop and
 * every label and fixture applies as is. Settings are rapidocr's defaults (its config.yaml). Simplification:
 * game text is horizontal, so boxes are axis-aligned rectangles (OpenCV's minAreaRect in rapidocr) and the
 * 180° classifier is skipped. Model files and the character list: phone/tools/ocr_models.py.
 */
class PaddleOcr(detModel: ByteArray, recModel: ByteArray, characterList: List<String>) : Ocr {
    private val env = OrtEnvironment.getEnvironment()
    private val det: OrtSession = env.createSession(detModel, OrtSession.SessionOptions())
    private val rec: OrtSession = env.createSession(recModel, OrtSession.SessionOptions())
    private val characters: List<String> = listOf("blank") + characterList + " "  // CTC blank first, space last

    /** BGR planes in [0, 255], the image the pipeline works on. */
    private class Img(val w: Int, val h: Int, val c: Array<FloatArray>) {
        fun crop(x0: Int, y0: Int, cw: Int, ch: Int): Img {
            val out = Array(3) { FloatArray(cw * ch) }
            for (k in 0 until 3) for (y in 0 until ch) for (x in 0 until cw) {
                val sx = (x0 + x).coerceIn(0, w - 1); val sy = (y0 + y).coerceIn(0, h - 1)
                out[k][y * cw + x] = c[k][sy * w + sx]
            }
            return Img(cw, ch, out)
        }

        /** OpenCV INTER_LINEAR (half-pixel centers). */
        fun resize(nw: Int, nh: Int): Img {
            val out = Array(3) { FloatArray(nw * nh) }
            val sx = w.toDouble() / nw; val sy = h.toDouble() / nh
            for (y in 0 until nh) {
                val fy = ((y + 0.5) * sy - 0.5).coerceAtLeast(0.0)
                val y0 = min(floor(fy).toInt(), h - 1); val y1 = min(y0 + 1, h - 1); val ty = (fy - y0).toFloat()
                for (x in 0 until nw) {
                    val fx = ((x + 0.5) * sx - 0.5).coerceAtLeast(0.0)
                    val x0 = min(floor(fx).toInt(), w - 1); val x1 = min(x0 + 1, w - 1); val tx = (fx - x0).toFloat()
                    for (k in 0 until 3) {
                        val p = c[k]
                        val top = p[y0 * w + x0] * (1 - tx) + p[y0 * w + x1] * tx
                        val bottom = p[y1 * w + x0] * (1 - tx) + p[y1 * w + x1] * tx
                        out[k][y * nw + x] = top * (1 - ty) + bottom * ty
                    }
                }
            }
            return Img(nw, nh, out)
        }

        /** np.rot90: 90° counter-clockwise. */
        fun rot90(): Img {
            val out = Array(3) { FloatArray(w * h) }
            for (k in 0 until 3) for (y in 0 until h) for (x in 0 until w) out[k][(w - 1 - x) * h + y] = c[k][y * w + x]
            return Img(h, w, out)
        }

        /** Padded with black rows at the top and bottom (rapidocr's vertical padding). */
        fun padVertical(p: Int): Img {
            val nh = h + 2 * p
            val out = Array(3) { FloatArray(w * nh) }
            for (k in 0 until 3) System.arraycopy(c[k], 0, out[k], p * w, w * h)
            return Img(w, nh, out)
        }
    }

    private fun toImg(f: Frame, region: Region?): Pair<Img, P> {
        val x0 = region?.x1?.coerceIn(0, f.width) ?: 0; val y0 = region?.y1?.coerceIn(0, f.height) ?: 0
        val x1 = region?.x2?.coerceIn(x0, f.width) ?: f.width; val y1 = region?.y2?.coerceIn(y0, f.height) ?: f.height
        val w = x1 - x0; val h = y1 - y0
        val c = Array(3) { FloatArray(w * h) }
        for (y in 0 until h) for (x in 0 until w) {
            val px = f.pixels[(y0 + y) * f.width + x0 + x]
            val i = y * w + x
            c[0][i] = (px and 0xFF).toFloat(); c[1][i] = ((px shr 8) and 0xFF).toFloat(); c[2][i] = ((px shr 16) and 0xFF).toFloat()
        }
        return Img(w, h, c) to P(x0, y0)
    }

    @Synchronized
    override fun read(img: Frame, region: Region?): List<Text> {
        val (src, origin) = toImg(img, region)
        if (src.w < 2 || src.h < 2) return emptyList()
        // Global preprocessing: max side 2000, min side 30, sizes multiple of 32.
        var work = src
        var ratioW = 1.0; var ratioH = 1.0
        if (max(src.h, src.w) > MAX_SIDE) {
            val r = MAX_SIDE.toDouble() / max(src.h, src.w)
            work = resized32(src, r).also { ratioH = src.h.toDouble() / it.h; ratioW = src.w.toDouble() / it.w }
        }
        if (min(work.h, work.w) < MIN_SIDE) {
            val base = work
            val r = MIN_SIDE.toDouble() / min(base.h, base.w)
            work = resized32(base, r).also { ratioH = base.h.toDouble() / it.h; ratioW = base.w.toDouble() / it.w }
        }
        // Vertical padding for very flat or tiny images.
        var padTop = 0
        if (work.h <= MIN_HEIGHT || work.w.toDouble() / work.h > WIDTH_HEIGHT_RATIO) {
            val newH = max((work.w / WIDTH_HEIGHT_RATIO).toInt(), MIN_HEIGHT) * 2
            padTop = kotlin.math.abs(newH - work.h) / 2
            work = work.padVertical(padTop)
        }
        val boxes = detect(work)
        if (boxes.isEmpty()) return emptyList()
        val crops = boxes.map { b ->
            val c = work.crop(b[0], b[1], b[2] - b[0], b[3] - b[1])
            if (c.h.toDouble() / c.w >= 1.5) c.rot90() else c
        }
        val texts = recognize(crops)
        val out = ArrayList<Text>()
        for ((i, b) in boxes.withIndex()) {
            val (txt, score) = texts[i]
            if (txt.isBlank() || score < TEXT_SCORE) continue
            fun mx(v: Int) = (v * ratioW).coerceIn(0.0, src.w.toDouble()).toInt() + origin.x
            fun my(v: Int) = ((v - padTop) * ratioH).coerceIn(0.0, src.h.toDouble()).toInt() + origin.y
            out.add(Text(txt, mx(b[0]), my(b[1]), mx(b[2]), my(b[3])))
        }
        return out
    }

    private fun resized32(img: Img, ratio: Double): Img {
        val h = round32((img.h * ratio).toInt()); val w = round32((img.w * ratio).toInt())
        return img.resize(max(w, 32), max(h, 32))
    }

    /** Python's round() (halves to even) of v / 32, times 32. */
    private fun round32(v: Int): Int = (Math.rint(v / 32.0) * 32).toInt()

    // --- detection (DB) ---

    /** Text boxes [x0, y0, x1, y1] in `img` coordinates, in reading order. */
    private fun detect(img: Img): List<IntArray> {
        var ratio = 1.0
        if (min(img.h, img.w) < DET_LIMIT_SIDE) ratio = DET_LIMIT_SIDE.toDouble() / min(img.h, img.w)
        val rh = round32((img.h * ratio).toInt()); val rw = round32((img.w * ratio).toInt())
        if (rh <= 0 || rw <= 0) return emptyList()
        val input = if (rh == img.h && rw == img.w) img else img.resize(rw, rh)
        val buf = floats(3 * rw * rh)
        for (k in 0 until 3) for (v in input.c[k]) buf.put((v / 255f - 0.5f) / 0.5f)
        buf.rewind()
        val pred = OnnxTensor.createTensor(env, buf, longArrayOf(1, 3, rh.toLong(), rw.toLong())).use { t ->
            det.run(mapOf(det.inputNames.first() to t)).use { r -> (r[0] as OnnxTensor).floatBuffer.let { fb -> FloatArray(fb.remaining()).also { fb.get(it) } } }
        }
        // Binary map, dilated with a 2x2 kernel (anchor at its bottom-right cell).
        val bin = BooleanArray(rw * rh)
        for (y in 0 until rh) for (x in 0 until rw) {
            bin[y * rw + x] = pred[y * rw + x] > DET_THRESH || (x > 0 && pred[y * rw + x - 1] > DET_THRESH) ||
                (y > 0 && pred[(y - 1) * rw + x] > DET_THRESH) || (x > 0 && y > 0 && pred[(y - 1) * rw + x - 1] > DET_THRESH)
        }
        val seen = BooleanArray(rw * rh)
        val boxes = ArrayList<DoubleArray>()
        val stack = IntArray(rw * rh)
        for (start in 0 until rw * rh) {
            if (!bin[start] || seen[start]) continue
            var xmin = rw; var xmax = -1; var ymin = rh; var ymax = -1
            var sp = 0
            stack[sp++] = start; seen[start] = true
            while (sp > 0) {
                val i = stack[--sp]
                val x = i % rw; val y = i / rw
                if (x < xmin) xmin = x; if (x > xmax) xmax = x; if (y < ymin) ymin = y; if (y > ymax) ymax = y
                for (dy in -1..1) for (dx in -1..1) {  // 8-connected, like OpenCV contours
                    val nx = x + dx; val ny = y + dy
                    if (nx < 0 || ny < 0 || nx >= rw || ny >= rh) continue
                    val j = ny * rw + nx
                    if (bin[j] && !seen[j]) { seen[j] = true; stack[sp++] = j }
                }
            }
            val bw = (xmax - xmin).toDouble(); val bh = (ymax - ymin).toDouble()
            if (min(bw, bh) < MIN_SIZE) continue
            var sum = 0.0
            for (y in ymin..ymax) for (x in xmin..xmax) sum += pred[y * rw + x]
            if (sum / ((xmax - xmin + 1) * (ymax - ymin + 1)) < BOX_THRESH) continue
            val d = bw * bh * UNCLIP_RATIO / (2 * (bw + bh))
            if (min(bw, bh) + 2 * d < MIN_SIZE + 2) continue
            boxes.add(doubleArrayOf(xmin - d, ymin - d, xmax + d, ymax + d))
        }
        // Back to `img` coordinates, clipped, small ones dropped.
        val out = boxes.mapNotNull { b ->
            fun sx(v: Double) = Math.rint(v / rw * img.w).coerceIn(0.0, img.w.toDouble()).toInt().coerceAtMost(img.w - 1)
            fun sy(v: Double) = Math.rint(v / rh * img.h).coerceIn(0.0, img.h.toDouble()).toInt().coerceAtMost(img.h - 1)
            val r = intArrayOf(sx(b[0]), sy(b[1]), sx(b[2]), sy(b[3]))
            if (r[2] - r[0] <= 3 || r[3] - r[1] <= 3) null else r
        }
        // Reading order: by top edge; boxes less than 10 px apart in y form one line, sorted by x.
        val byY = out.sortedBy { it[1] }
        val line = IntArray(byY.size)
        for (i in 1 until byY.size) line[i] = line[i - 1] + if (byY[i][1] - byY[i - 1][1] >= SORT_Y_THRESHOLD) 1 else 0
        return byY.indices.sortedWith(compareBy({ line[it] }, { byY[it][0] })).map { byY[it] }
    }

    // --- recognition (CTC) ---

    private fun recognize(crops: List<Img>): List<Pair<String, Double>> {
        val ratios = crops.map { it.w.toDouble() / it.h }
        val order = crops.indices.sortedBy { ratios[it] }
        val res = Array(crops.size) { "" to 0.0 }
        for (begin in order.indices step REC_BATCH) {
            val batch = order.subList(begin, min(order.size, begin + REC_BATCH))
            val maxRatio = max(REC_W.toDouble() / REC_H, batch.maxOf { ratios[it] })
            val imgW = (REC_H * maxRatio).toInt()
            val buf = floats(batch.size * 3 * REC_H * imgW)
            for (idx in batch) {
                val c = crops[idx]
                val rw = if (ceil(REC_H * ratios[idx]) > imgW) imgW else ceil(REC_H * ratios[idx]).toInt()
                val r = c.resize(max(rw, 1), REC_H)
                for (k in 0 until 3) for (y in 0 until REC_H) for (x in 0 until imgW) {
                    buf.put(if (x < r.w) (r.c[k][y * r.w + x] / 255f - 0.5f) / 0.5f else 0f)
                }
            }
            buf.rewind()
            OnnxTensor.createTensor(env, buf, longArrayOf(batch.size.toLong(), 3, REC_H.toLong(), imgW.toLong())).use { t ->
                rec.run(mapOf(rec.inputNames.first() to t)).use { r ->
                    val o = r[0] as OnnxTensor
                    decode(o.info.shape, o.floatBuffer, batch, res)  // read in place: N x T x 18710 floats is large
                }
            }
        }
        return res.toList()
    }

    /** CTC greedy decoding: best class per step, repeats and blanks dropped; score = mean of their probabilities. */
    private fun decode(shape: LongArray, probs: FloatBuffer, batch: List<Int>, res: Array<Pair<String, Double>>) {
        val steps = shape[1].toInt(); val classes = shape[2].toInt()
        for ((n, idx) in batch.withIndex()) {
            val sb = StringBuilder()
            val confs = ArrayList<Double>()
            var prev = -1
            for (s in 0 until steps) {
                val base = (n * steps + s) * classes
                var best = 0; var bestP = probs.get(base)
                for (k in 1 until classes) { val v = probs.get(base + k); if (v > bestP) { best = k; bestP = v } }
                if (best != prev && best != 0) {
                    sb.append(characters[best])
                    confs.add(Math.round(bestP * 1e5) / 1e5)
                }
                prev = best
            }
            res[idx] = sb.toString() to (if (confs.isEmpty()) 0.0 else confs.average())
        }
    }

    /** A float buffer outside the Java heap (the model inputs are tens of MB). */
    private fun floats(n: Int): FloatBuffer = ByteBuffer.allocateDirect(n * 4).order(ByteOrder.nativeOrder()).asFloatBuffer()

    companion object {
        const val MAX_SIDE = 2000
        const val MIN_SIDE = 30
        const val MIN_HEIGHT = 30
        const val WIDTH_HEIGHT_RATIO = 8.0
        const val TEXT_SCORE = 0.5
        const val DET_LIMIT_SIDE = 736
        const val DET_THRESH = 0.3f
        const val BOX_THRESH = 0.5
        const val UNCLIP_RATIO = 1.6
        const val MIN_SIZE = 3
        const val SORT_Y_THRESHOLD = 10
        const val REC_BATCH = 6
        const val REC_H = 48
        const val REC_W = 320
        const val DET_MODEL = "PP-OCRv6_det_small.onnx"
        const val REC_MODEL = "PP-OCRv6_rec_small.onnx"
        const val REC_CHARACTERS = "rec_characters.json"  // phone/tools/ocr_models.py: as rapidocr splits it
    }
}
