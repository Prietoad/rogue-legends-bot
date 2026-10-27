package com.diego.roguebot_phone.bot

import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import kotlin.math.abs

/**
 * The OCR on a real device (ONNX Runtime for Android, recorded by phone/tools/device_ocr.py into
 * device_ocr.json) reads the fixtures like the same code on the PC. Skipped without a recording.
 */
class DeviceOcrTest {
    @Test
    fun deviceReadsLikeThePc() {
        val url = javaClass.classLoader!!.getResource("device_ocr.json")
        assumeTrue("no device recording", url != null)
        val device = JSONObject(url!!.readText())
        val reads = Fixtures.phoneReads(device.keySet())
        val failures = ArrayList<String>()
        for (name in device.keySet().sorted()) {
            val phone = Fixtures.texts(device.getJSONObject(name).getJSONArray("texts"))
            val pc = reads.getValue(name)
            val missing = pc.filter { p -> phone.none { it.text == p.text && abs(it.center.x - p.center.x) <= 3 && abs(it.center.y - p.center.y) <= 3 } }
            if (missing.isNotEmpty()) failures.add("$name: ${missing.map { it.text }} vs ${phone.map { it.text }}")
        }
        assertTrue(failures.joinToString(System.lineSeparator()), failures.isEmpty())
    }
}
