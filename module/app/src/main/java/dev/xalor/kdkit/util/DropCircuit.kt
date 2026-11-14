package dev.xalor.kdkit.util

/**
 * 观测落盘的**熔断器** —— 把"丢线"从"永久停写"改成"短暂让路"。
 *
 * ### 原来的实现和它的问题
 *
 * `Capture.append` 开头是：
 *
 * ```kotlin
 * if (dropped.get() > 1_000_000L) return     // 长期无读者时彻底闭嘴
 * ```
 *
 * `dropped` 是**进程生命周期内的累计值**。于是一次突发（写者比落盘线程快，队列 4096 填满）
 * 累积到 100 万次丢弃之后，**这个进程此后再也不会写一行抓取**，而且：
 *
 * * 没有任何日志说"我关了"；
 * * `stats()` 里 `dropped` 只是个数字，没人盯；
 * * 抓取文件还在、还在轮转，**看起来一切正常** —— 后面所有证据全部消失。
 *
 * 这是最坏的失败形态：静默、永久、且证据本身被它吃掉。
 *
 * 而那道上限本来想防的是"没人读时无限涨内存"，可队列**本来就有界**（4096），
 * 满了就是丢、不会涨。所以真正需要防的是**磁盘 I/O 被写爆**，
 * 而那用"限速 + 短暂暂停"就够，不需要判死刑。
 *
 * ### 现在的语义
 *
 * * 每秒丢弃次数没超阈值 ⇒ 不停；
 * * 超了 ⇒ **暂停 [pauseMs] 毫秒**（默认 5 秒），期间直接丢弃、不排队；
 * * 暂停结束**自动恢复**，不需要人工干预；
 * * 每次进入/退出暂停都计数，`Capture.stats()` 里能看见。
 *
 * 纯对象 + 注入时钟 ⇒ 可单测（不用 `Thread.sleep`）。
 */
class DropCircuit(
    /** 1 秒内丢弃超过这个数就熔断。 */
    private val tripPerSecond: Int = 5_000,
    /** 熔断后暂停多久（毫秒）。 */
    private val pauseMs: Long = 5_000,
) {

    /**
     * 用**显式标志**而不是 `windowStartMs == 0L` 表示"还没开始计数"。
     *
     * 用 0 当哨兵值会与"时钟真的给了 0"撞车（单测里就是这样）：
     * 于是每次 `onDrop` 都以为窗口没开过，`windowDrops` 永远停在 1，熔断永不触发。
     * 生产环境 `currentTimeMillis()` 不会是 0，但依赖"某个值永远不会等于哨兵值"
     * 是隐患，不是设计。
     */
    @Volatile private var started = false
    @Volatile private var windowStartMs: Long = 0
    @Volatile private var windowDrops: Int = 0
    @Volatile private var pausedUntilMs: Long = 0

    /** 累计进入暂停的次数（诊断用：>0 说明这一轮确实被写爆过）。 */
    @Volatile var trips: Long = 0
        private set

    /** @return true = 现在可以投递；false = 处于静默暂停期，直接丢弃。 */
    fun allow(nowMs: Long): Boolean = nowMs >= pausedUntilMs

    /** 记一次"队列满、没能投递"。 */
    fun onDrop(nowMs: Long) {
        if (!started) {
            started = true
            windowStartMs = nowMs
            windowDrops = 1
            return
        }
        if (nowMs - windowStartMs >= 1_000L) {
            // 窗口过期：重新开始统计。这一秒没爆就什么都不做。
            windowStartMs = nowMs
            windowDrops = 1
            return
        }
        windowDrops++
        if (windowDrops > tripPerSecond && nowMs >= pausedUntilMs) {
            pausedUntilMs = nowMs + pauseMs
            trips++
            windowDrops = 0
            windowStartMs = nowMs
        }
    }

    /** 距离恢复还有多久（毫秒，<=0 表示没在暂停）。 */
    fun remainingPauseMs(nowMs: Long): Long = (pausedUntilMs - nowMs).coerceAtLeast(0)

    fun reset() {
        started = false
        windowStartMs = 0
        windowDrops = 0
        pausedUntilMs = 0
    }
}
