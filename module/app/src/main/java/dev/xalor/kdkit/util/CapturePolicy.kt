package dev.xalor.kdkit.util

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 抓取文件的**纯决策逻辑**（不引用任何 android 类，因此可在 JVM 单测里直接跑）。
 *
 * 与 [Capture] 的分工：这里决定"这一行长什么样、要不要轮转、超长怎么截"，
 * [Capture] 只负责"投递到后台线程 + 真正写盘"。
 *
 * 行格式必须保持稳定 —— `kit/python/` 下 6 个解析器（`capture_transcript.py` /
 * `bridge_inventory.py` / `guard_report.py` / `rc4_plaintexts.py` / `session_report.py` /
 * `decrypt_capture.py`）都按 `HH:mm:ss.SSS <line>` 这一种前缀切分，改格式等于让它们全部静默失败。
 */
object CapturePolicy {

    /** 单文件上限；超过就轮转成 `.prev.txt`（不删除，避免"刚轮转"被误读成"没数据"）。 */
    const val DEFAULT_MAX_BYTES: Long = 4L * 1024 * 1024

    /** 单行上限：一条超长的 JSON 桥载荷不该把磁盘吃掉。 */
    const val DEFAULT_MAX_LINE: Int = 4_000

    private val threads = ThreadLocal.withInitial { SimpleDateFormat("HH:mm:ss.SSS", Locale.US) }

    fun stamp(now: Long): String = threads.get()!!.format(Date(now))

    /**
     * 需要轮转吗？（当前已写 [currentBytes]，本次追加 [incoming] 字节）
     *
     * [maxBytes] <= 0 表示**不限制** —— 这是配置通道 `capture_max_mb=0` 的语义
     * （长时间取证时宁可写满磁盘也不丢证据）。空文件永不轮转，否则每次启动都会留下一个空 prev。
     */
    fun shouldRotate(currentBytes: Long, incoming: Int, maxBytes: Long = DEFAULT_MAX_BYTES): Boolean {
        if (maxBytes <= 0) return false
        if (currentBytes <= 0) return false
        return currentBytes + incoming > maxBytes
    }

    /**
     * 截断单行。保留**行首**（tag 与主体语义都在前面），并在尾部标注原始长度，
     * 这样"被截断"与"原本就这么短"在证据里可区分。
     */
    fun clamp(line: String, max: Int = DEFAULT_MAX_LINE): String =
        if (line.length <= max) line else line.substring(0, max) + " …(${line.length})"

    /**
     * 把内嵌换行压成 `⏎`，**一条记录永远只占一行**。
     *
     * 为什么必须在写入侧做：抓取文件的格式契约是 `HH:mm:ss.SSS <prefix> <body>`，
     * 而 kit 的解析器逐行读、按前缀切分。可有些 body 天然带换行 ——
     * `H5 n out:` 会带整段 PEM 证书（实测 `work/dpsdk/acceptance_capture.txt` 里
     * 148 行"未知行"全部来自一个证书的续行），桥 JSON、堆栈、SQL 也一样。
     * 旧实现直接把换行写进文件，于是**一条记录被读成 N 行**，后续行没有前缀、没有时间戳，
     * 只会被计成 UNKNOWN。把它压成 `⏎` 后，一条记录仍是可定位的一行，内容不丢。
     */
    fun oneLine(line: String): String =
        line.replace("\r\n", "⏎").replace('\n', '⏎').replace('\r', '⏎')

    /** 最终写入磁盘的一行（含时间戳与换行）：先压平内嵌换行，再按长度截断。 */
    fun format(stamp: String, line: String, max: Int = DEFAULT_MAX_LINE): String =
        stamp + " " + clamp(oneLine(line), max) + "\n"
}
