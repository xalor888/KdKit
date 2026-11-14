package dev.xalor.kdkit.util

import java.util.concurrent.ConcurrentHashMap

/**
 * 带 TTL 的键值缓存 —— 热开关"改了就能立刻生效"的机制本身。
 *
 * ### 为什么单独抽出来
 *
 * `KdConfig.isOn()` 每次钩子回调都会被问一次（`dispatchAction` 一类热点一页上百次），
 * 直接读 `XSharedPreferences` 是**每次跨进程读文件**；所以必须有缓存；
 * 而缓存一旦有 TTL，"改配置多久生效"就成了用户能感觉到的行为。
 *
 * 2026-11-02 之前这段逻辑长在 `KdConfig` 内部 —— 而 `KdConfig` 依赖
 * `android.content.Context` / `android.util.Log`，JVM 单测里连类都加载不起来，
 * 于是**这段最容易写错的逻辑零覆盖**（代码审查 B1）。抽成纯对象后可直接单测。
 *
 * ### 三条语义（都有对应断言）
 *
 * 1. **新鲜 ⇒ 不再问来源**：TTL 内重复读不触发 `load`（这是缓存的全部意义）。
 * 2. **过期 ⇒ 重新问**：超过 TTL 立刻重读，热开关才能在 2 秒内生效。
 * 3. **来源返回 null ⇒ 不缓存**：读失败（文件还没发布、进程刚起）是**瞬时**状态，
 *    把它缓存住会让"配置看起来一直是默认值"。旧实现没有这条，正是
 *    "改了配置要等一整轮才生效"这类问题的来源。
 */
class TtlCache<V> {

    private class Slot<V>(@Volatile var value: V, @Volatile var at: Long)

    private val map = ConcurrentHashMap<String, Slot<V>>()

    /** 过期时间（毫秒）。`<= 0` 表示**永不过期**（诊断/测试用）。 */
    @Volatile
    var ttlMs: Long = 2_000

    /**
     * 取一个值。
     *
     * @param key   配置键
     * @param nowMs 当前时间（由调用方注入 —— 这样测试不需要 `Thread.sleep`）
     * @param load  回源函数；返回 `null` 表示"这次读不到"，**不会**被缓存
     * @return 缓存值或本次回源值；读不到时为 `null`（由调用方决定回落值）
     */
    fun get(key: String, nowMs: Long, load: () -> V?): V? {
        if (ttlMs > 0) {
            val slot = map[key]
            if (slot != null && nowMs - slot.at < ttlMs) return slot.value
        }
        val fresh = load() ?: return null
        map[key] = Slot(fresh, nowMs)
        return fresh
    }

    /** 直接写入（`setApp` / `setAppString` 之后调用，避免"刚写完又读到旧值"）。 */
    fun put(key: String, value: V, nowMs: Long) {
        map[key] = Slot(value, nowMs)
    }

    /** 清空（诊断页"重载配置"）。 */
    fun invalidate() = map.clear()

    val size: Int get() = map.size
}
