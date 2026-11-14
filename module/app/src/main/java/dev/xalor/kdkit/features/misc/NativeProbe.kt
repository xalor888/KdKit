package dev.xalor.kdkit.features.misc

import android.util.Base64
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 签名公式探针 —— 把 `work/native_reversal.md` §5 里唯一没拿到的两个运行时字符串读出来，
 * 并且**在进程内当场验证公式**。
 *
 * `libbaseutil.so nativeGetSign(param)` 的写法（静态反汇编）：
 *
 *     x22 = &G           // G = libbaseutil 基址 + 0xa238
 *     x0  = [x22], x22 += 0x10        // 取 G+0x10 处那个对象当字符串去 md5
 *     B2  = md5_hex(x0)
 *     out = asprintf("%s[%s]@%s", x22 /*G+0x20*/, B2, param)
 *     return md5_hex(out)
 *
 * 这两个字符串是 init（`0x3014`）时创建的堆/内联对象（签名证书派生值 + token 派生值），
 * 脱离进程读不到（harness 里 `Unsafe`/`/proc/self/mem` 都失败）。本功能跑在**目标进程内部**，
 * 于是可以：读 `/proc/self/maps` 拿到 .so 基址 → 读 `/proc/self/mem` 把 G 附近整块 dump 出来 →
 * 提取候选字符串 → 用实测的 `(param, sign)` 反推哪一对能算出同一个 md5。
 *
 * 命中即等于把签名公式钉死，并且验证过程本身留在模块日志里（不用离线另算）。
 */
object NativeProbe : SwitchFeature(
    id = "native_probe",
    title = "签名公式探针",
    summary = "读取 libbaseutil.so 运行时字符串并当场验证签名公式（nativeGetSign 的 md5 组合）",
    category = Category.MISC,
    defaultOn = false,
    hot = true,
) {
    private const val LIB = "libbaseutil.so"
    /** G 结构体在 .bss 的地址（paddr == vaddr，见 native_reversal.md §2） */
    private const val G_OFF = 0xa238L
    private const val DUMP = 0x180
    private val done = AtomicBoolean(false)

    /** (param, sign) pairs written to the capture file — capped, this is per-request data. */
    private val captured = java.util.concurrent.atomic.AtomicInteger(0)
    private const val DEFAULT_MAX_CAPTURE = 20

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "native_probe_capture",
            title = "记录 (param, sign) 条数",
            summary = "用于离线复算签名公式的样本数，默认 20",
            kind = KdOption.Kind.STRING,
            default = "20",
        ),
    )

    override fun install() {
        var n = 0
        // 必须走 hookAllAfter 的 `gate`：`hookAll` 没有 gate 形参，回调里也不判配置，
        // 于是这个功能**默认关着也在读参数、写 SIGNPARAM、起线程扫 /proc/self/mem**。
        n += Xp.hookAllAfter(
            "com.zuoyebang.baseutil.NativeHelper", "nativeGetSign",
            Xp.classLoader, gate = id,
        ) { param ->
            val arg = param.args.firstOrNull()?.toString() ?: return@hookAllAfter
            val sign = param.result?.toString() ?: return@hookAllAfter
            KdLog.i("NativeProbe: nativeGetSign param=${peek(arg)} -> $sign")
            val cap = KdConfig.getString("native_probe_capture", DEFAULT_MAX_CAPTURE.toString())
                .toIntOrNull() ?: DEFAULT_MAX_CAPTURE
            if (captured.getAndIncrement() < cap) capture("SIGNPARAM param=$arg sign=$sign")
            if (done.compareAndSet(false, true)) {
                // run off the hook thread: a blocking /proc/self/mem read must not
                // stall the caller (the app's network thread)
                Thread({ probe(arg, sign) }, "KdKit-probe").start()
            }
        }
        KdLog.i("NativeProbe installed ($n hooks)")
    }

    // ── the actual probe ──────────────────────────────────────────────────────

    private fun probe(param: String, sign: String) {
        try {
            probeInner(param, sign)
        } catch (t: Throwable) {
            KdLog.w("NativeProbe failed: $t")
        }
    }

    private fun probeInner(param: String, sign: String) {
        KdLog.i("NativeProbe: probe thread start")
        val base = libBase() ?: return KdLog.w("NativeProbe: $LIB not mapped")
        val g = base + G_OFF
        KdLog.i("NativeProbe: $LIB base=0x${base.toString(16)} G=0x${g.toString(16)}")

        KdLog.i("NativeProbe: reading G ...")
        val dump = readMem(g, DUMP) ?: return KdLog.w("NativeProbe: cannot read G")
        KdLog.i("NativeProbe: read ${dump.size} bytes from G")
        KdLog.i("NativeProbe: G dump = ${hex(dump.copyOf(minOf(dump.size, 0x40)))}")

        val candidates = mutableListOf<String>()
        // 1) 内联字符串（%s 直接指向对象本体的情况）
        candidates += inlineStrings(dump)
        // 2) 8 字节指针解引用后的 C 字符串
        var i = 0
        while (i + 8 <= dump.size) {
            val p = le64(dump, i)
            if (p > 0x1000 && p < 0x8000000000L) {
                readCString(p, 128)?.let { if (it.isNotEmpty()) candidates += it }
            }
            i += 8
        }
        val uniq = candidates.distinct().filter { it.isNotEmpty() && it.length <= 200 }
        KdLog.i("NativeProbe: ${uniq.size} candidate string(s): " +
                uniq.joinToString(" | ") { peek(it) })

        // 3) 暴力配对：sign == md5(A + "[" + md5hex(X) + "]@" + param)
        var hits = 0
        for (a in uniq) {
            for (x in uniq) {
                val out = a + "[" + md5hex(x.toByteArray()) + "]@" + param
                if (md5hex(out.toByteArray()) == sign) {
                    hits++
                    KdLog.w("NativeProbe: *** FORMULA MATCH *** A=${peek(a)} X=${peek(x)}")
                    capture("FORMULA A=$a X=$x param=$param sign=$sign")
                }
            }
        }
        KdLog.i("NativeProbe: done, matches=$hits")
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    /** 统一走共享通道（原来自己开文件 + 自己的 4MB 判断，三份重复实现之一）。 */
    private fun capture(line: String) = dev.xalor.kdkit.util.Capture.append("NativeProbe $line")

    /** Lowest mapping of the library = its base address. */
    private fun libBase(): Long? = try {
        File("/proc/self/maps").readLines()
            .firstOrNull { it.endsWith("/$LIB") }
            ?.substringBefore('-')
            ?.toLong(16)
    } catch (t: Throwable) {
        null
    }

    private fun readMem(addr: Long, len: Int): ByteArray? = try {
        RandomAccessFile("/proc/self/mem", "r").use { f ->
            f.seek(addr)
            val buf = ByteArray(len)
            val n = f.read(buf)
            if (n <= 0) null else buf.copyOf(n)
        }
    } catch (t: Throwable) {
        null
    }

    private fun readCString(addr: Long, max: Int): String? {
        val b = readMem(addr, max) ?: return null
        val end = b.indexOf(0.toByte())
        if (end <= 0) return null
        val s = String(b, 0, end, Charsets.UTF_8)
        return if (s.all { it.code in 0x20..0x7e || it.code > 0x7f }) s else null
    }

    /** Printable runs inside the dumped region (for the inline `%s` case). */
    private fun inlineStrings(d: ByteArray): List<String> {
        val out = mutableListOf<String>()
        val sb = StringBuilder()
        for (b in d) {
            val c = b.toInt() and 0xff
            if (c in 0x20..0x7e) {
                sb.append(c.toChar())
            } else {
                if (sb.length >= 4) out += sb.toString()
                sb.setLength(0)
            }
        }
        if (sb.length >= 4) out += sb.toString()
        return out
    }

    private fun le64(b: ByteArray, off: Int): Long {
        var v = 0L
        for (i in 7 downTo 0) v = (v shl 8) or (b[off + i].toLong() and 0xff)
        return v
    }

    private fun md5hex(b: ByteArray): String =
        MessageDigest.getInstance("MD5").digest(b).joinToString("") { "%02x".format(it) }

    private fun hex(b: ByteArray): String = b.joinToString("") { "%02x".format(it) }

    private fun peek(s: String): String = if (s.length > 120) s.substring(0, 120) + "…" else s
}
