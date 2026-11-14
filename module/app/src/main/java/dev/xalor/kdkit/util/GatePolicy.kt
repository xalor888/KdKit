package dev.xalor.kdkit.util

/**
 * 热开关「没有配置时算不算开」的**唯一判定处**。
 *
 * ### 为什么单独一个对象
 *
 * 2026-11-01 的代码审查查出一个 P0：`Xp.hook(gate = id)` 的回调首行写死了
 * `KdConfig.isOn(gate, true)` —— 而设置页**从不预置默认值**，prefs 里没有这个键时
 * `KdConfig.isOn` 会回落到传入的 `true`。于是 24 个 `hot = true && defaultOn = false`
 * 的功能里，只要用户没手动点过开关，回调照跑：
 *
 * * 7 个**改进程行为**（`bridge_guard` / `popwin_gate` / `skip_update` / `vip_unlock` /
 *   `watermark_off` / `web_picture_watermark` / `block_ad_sdk`）—— 界面上显示「关」，
 *   实际在拦弹窗、解会员、改水印；
 * * 11 个只多写观测噪声。
 *
 * 正确语义是「回落该功能**自己声明的** `defaultOn`」，不是常量 `true`。
 *
 * ### 为什么不是一个 lambda 塞进 Xp
 *
 * `Xp` 依赖 `de.robv.android.xposed.*`（compileOnly，JVM 单测里不存在），
 * 所以判据放进 `Xp` 就再也测不了 —— 而这正是当初三条 P0 都漏过去的原因：
 * `Xp` / `KdConfig` / `WebInjector` 三个要害类**零测试**。
 * 这里做成不依赖任何 Android/Xposed 的纯对象，`GateDefaultTest` 直接单测。
 */
object GatePolicy {

    /**
     * 由 `HookCore.start` 在装载功能之前灌入（`FeatureRegistry.all` 的 id → defaultOn）。
     *
     * 用 `@Volatile` 而不是 lateinit：抓取线程/钩子线程可能在灌入之前就读一次。
     */
    @Volatile
    private var defaults: Map<String, Boolean> = emptyMap()

    /** 灌入一次；重复调用以最后一次为准（诊断页"重载配置"会再灌一次）。 */
    fun install(map: Map<String, Boolean>) {
        defaults = map
    }

    /**
     * 某个 gate id 在没有配置时的缺省值。
     *
     * * 已知功能 ⇒ 它自己的 `defaultOn`；
     * * 未知 id ⇒ **`true`**（保守）：把没有登记进来的 gate 当成"开"，
     *   宁可多跑一次回调（可观测、可回滚），也不要静默把一个真实功能关掉 ——
     *   静默关闭是比误开更难的故障（用户只会觉得"功能没了"）。
     */
    fun defaultFor(id: String): Boolean = defaults[id] ?: true

    /** 诊断用：当前灌入了多少个默认值。 */
    fun size(): Int = defaults.size
}
