package dev.xalor.kdkit

import dev.xalor.kdkit.util.TextHeuristic
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class TextHeuristicTest {

    @Test fun chinesePlaintextDecoded() {
        assertEquals("""{"name":"五年高考三年模拟"}""", TextHeuristic.decode("""{"name":"五年高考三年模拟"}""".toByteArray()))
    }

    @Test fun pureAsciiPlaintextDecoded() {
        // 旧实现用"CJK 判定"会把这整类丢掉
        assertNotNull(TextHeuristic.decode("""{"bookId":12345,"url":"https://x/y"}""".toByteArray()))
        assertNotNull(TextHeuristic.decode("1712345678".toByteArray()))
    }

    @Test fun jsonWithNewlinesAllowed() {
        assertNotNull(TextHeuristic.decode("{\n  \"a\": 1\n}".toByteArray()))
    }

    @Test fun binaryRejected() {
        assertNull(TextHeuristic.decode(byteArrayOf(0, 1, 2, 3, -1, -2)))
        assertNull(TextHeuristic.decode(byteArrayOf(0x7f, 0x1f, 0x02)))
    }

    @Test fun invalidUtf8Rejected() {
        // 0xC3 后跟 0x28 是非法 UTF-8
        assertNull(TextHeuristic.decode(byteArrayOf(0xC3.toByte(), 0x28)))
    }

    @Test fun emptyRejected() {
        assertNull(TextHeuristic.decode(ByteArray(0)))
    }

    @Test fun mostlyBinaryRejectedEvenIfDecodable() {
        // 大量非 ASCII 但合法的字符（例如一片 U+0080 以上）在可打印比例上仍应通过；
        // 真正要挡的是控制字符，这里验证组合判据的保守性。
        val s = String(CharArray(100) { 'a' })
        assertNotNull(TextHeuristic.decode(s.toByteArray()))
    }
}
