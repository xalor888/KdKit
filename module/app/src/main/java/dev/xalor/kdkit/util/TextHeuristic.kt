package dev.xalor.kdkit.util

/**
 * "这段字节是不是文本"的判定（纯函数，JVM 可测）。
 *
 * 为什么值得单独写：旧实现在 `RC4Probe` 里用 `txt.any { it.code in 0x4E00..0x9FFF }` 判定 ——
 * **只认中文**。于是解出来的纯英文/数字明文（书名拼音、ID、URL、时间戳）被整类丢弃，
 * 而证据文件里看不出"是被过滤了"还是"本来就没有"，这正是 `UNEXPLAINED.md` 里悬着的那类问题。
 *
 * 现在的判据（三条都要满足，宁可保守）：
 *  1. 能按 UTF-8 严格解码（解不开就是二进制）；
 *  2. 可打印字符（含 CJK）比例 ≥ [minPrintable]；
 *  3. 不含 NUL / 控制字符（换行制表符除外）。
 */
object TextHeuristic {

    fun decode(bytes: ByteArray, minPrintable: Double = 0.9): String? {
        if (bytes.isEmpty()) return null
        val s = strictUtf8(bytes) ?: return null
        var printable = 0
        var control = 0
        for (ch in s) {
            when {
                ch == '\n' || ch == '\r' || ch == '\t' -> printable++
                ch.code < 0x20 -> control++
                Character.isISOControl(ch) -> control++
                else -> printable++
            }
        }
        if (control > 0) return null
        val ratio = printable.toDouble() / s.length
        if (ratio < minPrintable) return null
        return s
    }

    private fun strictUtf8(bytes: ByteArray): String? = try {
        val dec = Charsets.UTF_8.newDecoder()
            .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
            .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
        dec.decode(java.nio.ByteBuffer.wrap(bytes)).toString()
    } catch (_: Throwable) {
        null
    }
}
