package dev.xalor.kdkit

import dev.xalor.kdkit.util.CapturePolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CapturePolicyTest {

    @Test fun stampFormatIsThreeDigitMillis() {
        val s = CapturePolicy.stamp(0)
        assertTrue("第 30 行左右应有 .SSS 形式，实际=$s", Regex("^\\d{2}:\\d{2}:\\d{2}\\.\\d{3}$").matches(s))
    }

    @Test fun rotateOnlyWhenOverLimitAndFileNotEmpty() {
        assertFalse("空文件不轮转（否则每次启动都留一个空 prev）", CapturePolicy.shouldRotate(0, 10, 100))
        assertFalse(CapturePolicy.shouldRotate(90, 10, 100))
        assertTrue(CapturePolicy.shouldRotate(91, 10, 100))
    }

    @Test fun limitZeroDisablesRotation() {
        assertFalse("maxBytes<=0 表示不限制", CapturePolicy.shouldRotate(1_000_000, 100, 0))
    }

    @Test fun clampKeepsHeadAndMarksLength() {
        val long = "A".repeat(50)
        val out = CapturePolicy.clamp(long, 20)
        assertTrue(out.startsWith("A".repeat(20)))
        assertTrue("应标注原始长度，便于区分'被截断'与'本来如此'", out.endsWith("…(50)"))
    }

    @Test fun clampLeavesShortLinesAlone() {
        assertEquals("short", CapturePolicy.clamp("short", 20))
    }

    @Test fun formatKeepsParserContract() {
        val line = CapturePolicy.format("12:34:56.789", "SIGN result: abc", 100)
        assertEquals("12:34:56.789 SIGN result: abc\n", line)
        assertTrue("kit 的解析器按 'HH:mm:ss.SSS ' 前缀切分", line.matches(Regex("^\\d{2}:\\d{2}:\\d{2}\\.\\d{3} .*\\n$")))
    }

    @Test fun embeddedNewlinesAreFlattenedToOneRecordPerLine() {
        // 实测来源：`H5 n out:` 会带整段 PEM 证书，旧实现把换行原样写盘 ⇒
        // 一条记录变成 N 行，后续行没有前缀/时间戳，kit 只能计成 UNKNOWN。
        val pem = "-----BEGIN CERTIFICATE-----\nMIIFoTCC\r\nMRAwDgYD\n-----END CERTIFICATE-----"
        val one = CapturePolicy.format("12:34:56.789", "H5 n out: $pem", 10_000)
        assertEquals("压平后必须只有一行", 1, one.count { it == '\n' })
        assertTrue("内容不能丢（只换表示）", one.contains("-----BEGIN CERTIFICATE-----"))
        assertTrue(one.contains('⏎'))
        assertTrue(one.endsWith("\n"))
        assertTrue(one.matches(Regex("^\\d{2}:\\d{2}:\\d{2}\\.\\d{3} .*\\n$")))
    }

    @Test fun oneLineKeepsPlainTextUntouched() {
        assertEquals("SIGN URL: https://a/b?c=1", CapturePolicy.oneLine("SIGN URL: https://a/b?c=1"))
    }

    @Test fun flattenHappensBeforeTruncation() {
        // 先把 N 行压成一行、再截断：否则截断点会落在"第 2 行"，产出的仍是不完整记录。
        val body = "a\n".repeat(40)
        val line = CapturePolicy.format("12:34:56.789", "X " + body, 30)
        assertEquals(1, line.count { it == '\n' })
        val flattened = "X " + "a⏎".repeat(40)
        assertTrue("截断标注应是压平后的长度", line.contains("…(${flattened.length})"))
        assertTrue(line.startsWith("12:34:56.789 X a⏎a⏎"))
    }
}
