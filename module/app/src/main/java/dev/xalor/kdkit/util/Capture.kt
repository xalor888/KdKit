package dev.xalor.kdkit.util

import android.content.Context
import java.io.File
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.atomic.AtomicLong

/**
 * 模块所有观测功能的**唯一**落盘通道。
 *
 * 一个文件（宿主私有目录 `files/kdkit_capture.txt`）装下全部观测行，`kit/python/` 的六个
 * 解析器读的都是它 —— 一次 pull 就能汇总一轮会话。
 *
 * ### 2026-10-25 重构（为什么不再直接 `appendText`）
 *
 * 旧实现每次 `append` 都在**调用线程**上做 open/write/close。调用线程是宿主的业务线程
 * （签名、网络、UI），所以观测本身会变成掉帧源；同时 `SignObserver` / `NativeProbe` /
 * `ReqHeaders` 各自又写了一遍自己的文件逻辑（三份重复实现，三份 bug 面）。
 *
 * 现在：
 *  * **单写者线程 + 有界队列**：投递是内存操作，队列满就丢弃并计入 [stats]（宁可丢观测，
 *    不可拖慢宿主）；
 *  * **轮转而非删除**：写满 [maxBytes] 时把当前文件改名为 `kdkit_capture.prev.txt`，
 *    保证"刚轮转"不会被误读成"没数据"（2026-10-11 遇到过，代价是一轮假红）；
 *  * **一处实现**：其它功能只调 [append] / [record]，不再自己拼时间戳与 cap；
 *  * **可诊断**：[stats] 给出 written / dropped / rotated / bytes，`module_report.py` 能读。
 */
object Capture {

    private const val FILE_NAME = "kdkit_capture.txt"
    private const val ROTATE_NAME = "kdkit_capture.prev.txt"
    private const val QUEUE_CAPACITY = 4_096

    /** 上限可被配置通道覆盖（`capture_max_mb`），0 或负数表示不限制。 */
    @Volatile
    var maxBytes: Long = CapturePolicy.DEFAULT_MAX_BYTES

    @Volatile
    var maxLine: Int = CapturePolicy.DEFAULT_MAX_LINE

    private val written = AtomicLong()
    private val dropped = AtomicLong()
    private val rotated = AtomicLong()

    @Volatile
    private var file: File? = null

    @Volatile
    private var started = false

    private val queue = ArrayBlockingQueue<String>(QUEUE_CAPACITY)

    /**
     * 每 1 秒丢弃超过这么多行就暂停 5 秒（见 [DropCircuit]）。
     * 取值远高于正常写入速率：正常会话每秒几十行，只有"写爆"才会触发。
     */
    private val circuit = DropCircuit(tripPerSecond = 5_000, pauseMs = 5_000)

    /**
     * 投递一行（不阻塞、不抛异常）。
     *
     * **不再有"累计丢满就永久闭嘴"**：旧实现是 `if (dropped.get() > 1_000_000) return`，
     * `dropped` 是进程内累计值 ⇒ 一次突发之后这个进程**此后再也不写一行抓取**，
     * 而且不报错、文件还在、看着一切正常 —— 后面所有证据静默消失（2026-11-02 代码审查 D1）。
     * 现在改成本地熔断：写爆就暂停 5 秒，然后**自动恢复**。
     */
    fun append(line: String) {
        val now = System.currentTimeMillis()
        if (!circuit.allow(now)) return                 // 暂停期：直接丢，但会计数
        if (!queue.offer(line)) {
            dropped.incrementAndGet()
            circuit.onDrop(now)
        }
        ensureWriter()
    }

    /** 与 [append] 等价，只是读起来像"记一条证据"。[tag] 用来对齐 `grep`。 */
    fun record(tag: String, line: String) = append("$tag $line")

    /**
     * 记一条**只该出现一次**的会话标记（启动/注入/关键配置），
     * 便于在抓取里分段："这个进程从这一行开始"。
     */
    fun mark(line: String) = append("=== $line")

    fun stats(): Map<String, Long> = mapOf(
        "written" to written.get(),
        "dropped" to dropped.get(),
        "rotated" to rotated.get(),
        "bytes" to (file?.takeIf { it.exists() }?.length() ?: 0L),
        // 熔断次数：>0 说明这一轮**确实被写爆过**（以前这个信息完全不可见）
        "trips" to circuit.trips,
        "paused" to if (circuit.allow(System.currentTimeMillis())) 0L else 1L,
    )

    /** 测试 / 诊断用：把已投递的行立刻刷出去。 */
    fun flush() {
        val f = resolve() ?: return
        drainPending(f)
        while (true) {
            val line = queue.poll() ?: break
            writeLine(f, line)
        }
    }

    fun resetForTest() {
        queue.clear()
        written.set(0)
        dropped.set(0)
        rotated.set(0)
        file = null
    }

    // ── writer ────────────────────────────────────────────────────────────────

    /**
     * 路径还解析不出来时先挂在这里，等 `resolve()` 成功后按原顺序补写。
     *
     * 为什么必须有它：`HookCore.start` 跑在 `handleLoadPackage` 里，那一刻
     * `ActivityThread.currentApplication()` 往往还是 null（Application 尚未创建）。
     * 旧实现在 writer 里 `resolve() ?: continue` —— **直接丢行**，于是启动阶段那些
     * "只写一次"的结论行（`NEXIT` 自证、`=== HookCore start`）永久消失，
     * 而报告读起来像"这个功能没跑"。2026-11-02 实测：日志里
     * `NativeExitGuard: ... selfTest=1` 明明在，抓取里一行 `NEXIT` 都没有。
     */
    private val pending = java.util.concurrent.ConcurrentLinkedQueue<String>()

    /** 挂起上限。超了才真的丢（并计入 `dropped`），避免无读者时无限涨。 */
    private const val PENDING_MAX = 4_000

    private fun ensureWriter() {
        if (started) return
        started = true
        Thread({
            while (true) {
                val line = try {
                    queue.take()
                } catch (_: InterruptedException) {
                    return@Thread
                }
                val f = resolve()
                if (f == null) {
                    if (pending.size < PENDING_MAX) pending.add(line) else dropped.incrementAndGet()
                    try {
                        Thread.sleep(200)      // 路径还没好：别空转
                    } catch (_: InterruptedException) {
                        return@Thread
                    }
                    continue
                }
                drainPending(f)
                writeLine(f, line)
            }
        }, "KdKit-capture").apply { isDaemon = true; priority = Thread.MIN_PRIORITY }.start()
    }

    /** 把早期待写的行按原顺序补出去（只有 writer 线程会调用）。 */
    private fun drainPending(f: File) {
        while (true) {
            val p = pending.poll() ?: return
            writeLine(f, p)
        }
    }

    private fun writeLine(f: File, raw: String) {
        try {
            val line = CapturePolicy.format(CapturePolicy.stamp(System.currentTimeMillis()), raw, maxLine)
            val bytes = line.toByteArray(Charsets.UTF_8).size
            if (maxBytes > 0 && CapturePolicy.shouldRotate(f.length(), bytes, maxBytes)) {
                val prev = File(f.parentFile, ROTATE_NAME)
                runCatching { if (prev.exists()) prev.delete() }
                runCatching { f.renameTo(prev) }
                rotated.incrementAndGet()
                // 轮转是"证据换文件"的时刻，也是**丢掉多少**最该被看见的时刻。
                // 以前这些数字只在 stats() 里，而没有任何工具读它 ⇒ 等于没有（D1 的另一半）。
                KdLog.i(
                    "Capture rotated #${rotated.get()} " +
                        "written=${written.get()} dropped=${dropped.get()} trips=${circuit.trips}",
                )
            }
            f.appendText(line)
            written.incrementAndGet()
        } catch (_: Throwable) {
            dropped.incrementAndGet()
        }
    }

    private fun resolve(): File? {
        file?.let { return it }
        return try {
            // ActivityThread 是隐藏 API：反射拿，避免在宿主进程里踩 ClassLoader 问题。
            val app = Class.forName("android.app.ActivityThread")
                .getMethod("currentApplication").invoke(null) as? Context
            app?.filesDir?.let { File(it, FILE_NAME).also { f -> file = f } }
        } catch (_: Throwable) {
            null
        }
    }
}
