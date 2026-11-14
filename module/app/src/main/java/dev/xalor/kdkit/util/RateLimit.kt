package dev.xalor.kdkit.util

/**
 * 计数与限流小工具 —— 模块里所有"高频回调"共用的节流层。
 *
 * 为什么需要：钩子挂在**宿主的业务线程**上。此前 `LogSink` 对每一条匹配的 `Log.*` 都做一次
 * `appendText`（open/write/close 三次 syscall），`AdSlotProbe` 对每次广告位读取都算一遍 key，
 * 而 `KdLog` 每行都同步写两份（XposedBridge + logcat）。在真实 App 里这些都在网络线程上，
 * 观测本身就可能成为掉帧/超时的原因。
 *
 * 三条约束（也是本类存在的理由）：
 *  1. **不得阻塞调用方**：只做内存操作，毫秒级；
 *  2. **不得无界增长**：每个 key 都有独立的预算，超出后静默丢弃（丢弃计数可查）；
 *  3. **可测试**：时间来自可注入的 [clock]，测试里不 sleep。
 */
object RateLimit {

    /** 可注入时钟（毫秒）；测试用它把"等待"变成"改数"。 */
    @Volatile
    var clock: () -> Long = { System.nanoTime() / 1_000_000L }

    /**
     * 每 [intervalMs] 只放行一次，用于"同一条日志刷屏"（例如 800ms 轮询的反调试看门狗）。
     *
     * 用法：`if (RateLimit.every("antidetect", 5_000)) KdLog.i(...)`
     */
    fun every(key: String, intervalMs: Long): Boolean {
        val now = clock()
        val slot = STAMPS[key]
        if (slot == null) {
            STAMPS[key] = now
            return true
        }
        if (now - slot < intervalMs) return false
        // 用 CAS 风格重放：并发下最多多放行一两次，对日志无害，省掉一把全局锁。
        STAMPS[key] = now
        return true
    }

    /**
     * 计数型预算：前 [limit] 次返回 true，之后 false（"只记前 N 条"）。
     *
     * 与 [every] 的区别：它不随时间恢复 —— 用于"每类事件看几眼就够"的场景。
     */
    fun firstN(key: String, limit: Int): Boolean {
        val c = COUNTS.computeIfAbsent(key) { java.util.concurrent.atomic.AtomicInteger() }
        return c.incrementAndGet() <= limit
    }

    /** 当前计数（诊断用）。 */
    fun count(key: String): Int = COUNTS[key]?.get() ?: 0

    /** 每 key 的放行总次数（诊断用，含 [every] 与 [firstN]）。 */
    fun stats(): Map<String, Int> = COUNTS.mapValues { it.value.get() }

    fun reset() {
        STAMPS.clear()
        COUNTS.clear()
    }

    private val STAMPS = java.util.concurrent.ConcurrentHashMap<String, Long>()
    private val COUNTS = java.util.concurrent.ConcurrentHashMap<String, java.util.concurrent.atomic.AtomicInteger>()
}
