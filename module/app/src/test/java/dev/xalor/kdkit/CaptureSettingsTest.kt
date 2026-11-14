package dev.xalor.kdkit

import dev.xalor.kdkit.config.CaptureSettings
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 这两个键此前只有"字段、没人填"：`capture_max_mb` 只在 `Capture.maxBytes` 的 KDoc 里出现过，
 * `log_level` 完全没有接线。这里直接测 [CaptureSettings] 的**真实**换算函数
 * （不是在测试里抄一遍公式 —— 那样测的是测试自己）。
 */
class CaptureSettingsTest {

    @Test fun megabytesConvertToBytes() {
        assertEquals(4L * 1024 * 1024, CaptureSettings.mbToBytes("4"))
        assertEquals(16L * 1024 * 1024, CaptureSettings.mbToBytes("16"))
    }

    @Test fun zeroAndNegativeMeanUnlimited() {
        assertEquals("0 = 不限制（长取证场景）", 0L, CaptureSettings.mbToBytes("0"))
        assertEquals("负数同样按不限制处理", 0L, CaptureSettings.mbToBytes("-3"))
    }

    @Test fun blankOrGarbageFallsBackToDefault() {
        val dflt = CaptureSettings.DEFAULT_MAX_MB * 1024L * 1024L
        assertEquals("空串回落默认 4MB", dflt, CaptureSettings.mbToBytes(""))
        assertEquals("null 回落默认", dflt, CaptureSettings.mbToBytes(null))
        assertEquals("非数字回落默认", dflt, CaptureSettings.mbToBytes("abc"))
        assertEquals("前后空格容忍", 8L * 1024 * 1024, CaptureSettings.mbToBytes(" 8 "))
    }

    @Test fun lineKilobytesConvertToChars() {
        assertEquals(4096, CaptureSettings.kbToChars("4"))
        assertEquals(Int.MAX_VALUE, CaptureSettings.kbToChars("0"))
        assertEquals(CaptureSettings.DEFAULT_MAX_LINE_KB * 1024, CaptureSettings.kbToChars(null))
    }

    @Test fun logLevelIsClamped() {
        assertEquals(0, CaptureSettings.parseLevel("-5"))
        assertEquals(2, CaptureSettings.parseLevel("9"))
        assertEquals(1, CaptureSettings.parseLevel("1"))
        assertEquals(CaptureSettings.DEFAULT_LOG_LEVEL, CaptureSettings.parseLevel("x"))
    }
}
