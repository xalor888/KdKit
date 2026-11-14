package dev.xalor.kdkit.util

/**
 * "把逗号分隔的配置串解析成列表"的**单槽记忆**。
 *
 * ### 为什么需要
 *
 * `BridgeGuard.decide()` 是 `HybridWebView.dispatchAction` 的钩子 ——
 * 页面**每一次** JS 桥调用都会走它（实测一次会话 282 次 `H5BRIDGE`，其中
 * `zybTrackerStatisticsAction` 一个 action 就 80 次）。而它每次都重新
 * `split(',').map{trim}.filter{…}.toMutableList()`：一次分发 3~4 个临时列表。
 * `HostAllowList.parse()` 同理，而且 `allows()` 每次调用都再 parse 一遍。
 *
 * 这些分配本身不致命，但它们发生在**每个页面回调**上，而且完全可以避免：
 * 配置串在两次修改之间是同一个 `String` 实例值，只需记住"上次解析的是哪串、结果是什么"。
 *
 * ### 为什么不是通用缓存
 *
 * 键只有一个（当前配置串），所以不需要 map、不需要 TTL、不会被撑爆。
 * 配置改了 ⇒ `raw` 变 ⇒ 自动重算。**没有第二个状态**，也就没有"缓存和配置不一致"的可能。
 *
 * ### 线程安全
 *
 * 两个字段都是 `@Volatile`，读路径无锁。并发下最坏情况是**多算一次**（两个线程同时
 * 发现 raw 变了），结果相同 —— 对纯函数 parse 来说这是可接受的代价，
 * 换来的是热路径上没有 `synchronized`。
 */
class RawListMemo {

    @Volatile private var raw: String? = null
    @Volatile private var parsed: List<String> = emptyList()

    /** 命中返回上次结果；未命中调用 [parse] 并记住。 */
    fun get(rawNow: String, parse: (String) -> List<String>): List<String> {
        if (raw == rawNow) return parsed
        val fresh = parse(rawNow)
        raw = rawNow
        parsed = fresh
        return fresh
    }

    /** 诊断用：当前记住的是哪一串（null = 还没算过）。 */
    fun lastRaw(): String? = raw
}
