package dev.xalor.kdkit.config

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import dev.xalor.kdkit.util.TtlCache

/**
 * Feature flags shared between the settings app (writer) and the hooked 快对 process (reader).
 *
 * IMPORTANT: this class is loaded by the *app* ClassLoader (the settings UI touches it), so it
 * must never reference `de.robv.android.xposed.*` — those classes only exist on the framework's
 * module ClassLoader. The Xposed-facing side lives in [KdConfigBridge].
 *
 * ### 2026-10-25 重构：从"永久缓存"到"带 TTL 的热读"
 *
 * 旧实现把每个 key 的第一次读取结果**永久**放进 `ConcurrentHashMap` ⇒ 进程内改了配置要重启宿主
 * 才生效（这正是"改完开关必须重启"的根因，不只是钩子只在启动时装）。
 *
 * 现在：命中缓存在 [ttlMs] 后过期并重新问一次来源。默认 2 秒 —— 热开关切一下，
 * 一两秒内就生效；而高频钩子（每个请求几十次）仍然只承担一次 map 查找的开销。
 * 钩子直接调用 [isOn] 是安全的：它不阻塞、不抛异常。
 */
object KdConfig {
    const val MODULE_PKG = "dev.xalor.kdkit"
    const val PREFS_NAME = "kdkit"
    const val TARGET_PKG = "com.kuaiduizuoye.scan"

    private const val TAG = "KdKit"

    /**
     * 缓存有效期。0 = 每次直读来源（诊断用，很慢，别长期开）。
     *
     * 真正的 TTL 判定在 [TtlCache] 里（纯对象、有单测）；这里只是把值转给两个缓存。
     */
    var ttlMs: Long
        get() = boolCache.ttlMs
        set(v) {
            boolCache.ttlMs = v
            strCache.ttlMs = v
        }

    // 2026-11-02：原先是两个 `ConcurrentHashMap<String, Slot<…>>` + 内联的 TTL 判定，
    // 而 `KdConfig` 依赖 Android Context/Log ⇒ JVM 单测里连类都加载不起来 ⇒
    // 这段最容易写错的逻辑零覆盖（代码审查 B1）。抽成 [TtlCache] 后可直接单测。
    private val boolCache = TtlCache<Boolean>()
    private val strCache = TtlCache<String>()

    @Volatile private var appPrefs: SharedPreferences? = null
    /** Set by [KdConfigBridge] inside the hooked host process. */
    @Volatile var hostReader: ((String) -> Boolean?)? = null
    /** Same, for the few settings that are not booleans (e.g. the bridge-guard blacklist). */
    @Volatile var hostStringReader: ((String) -> String?)? = null

    fun attachApp(ctx: Context) {
        appPrefs = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        invalidate()
        Log.i(TAG, "config attached (app)")
    }

    fun isOn(id: String, def: Boolean = true): Boolean =
        boolCache.get(id, System.currentTimeMillis()) { readSource(id) } ?: def

    private fun readSource(id: String): Boolean? =
        hostReader?.invoke(id)
            ?: appPrefs?.let { if (it.contains(id)) it.getBoolean(id, true) else null }

    /**
     * `readSource` 的测试可见版本（2026-11-04）。
     *
     * 为什么需要暴露它：`readSource` 是**私有**的，而"没有 reader 时必须给 null
     * 而不是 false"这条契约是 `GateOffStopsCallbackTest` 要钉的核心 ——
     * 少了它，"读不到"会被悄悄当成"关"，于是**热功能在用户没表态时被静默关掉**。
     */
    internal fun readSourceForTest(id: String): Boolean? = readSource(id)

    fun setApp(ctx: Context, id: String, value: Boolean) {
        ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putBoolean(id, value).apply()
        // 写者本地立即生效（宿主侧靠 TTL 过期后读到新的发布文件）
        boolCache.put(id, value, System.currentTimeMillis())
    }

    /** String-valued setting (fallback: the app's own prefs, then [def]). */
    fun getString(id: String, def: String = ""): String =
        strCache.get(id, System.currentTimeMillis()) { readStringSource(id) } ?: def

    private fun readStringSource(id: String): String? =
        hostStringReader?.invoke(id)
            ?: appPrefs?.let { if (it.contains(id)) it.getString(id, "") else null }

    fun setAppString(ctx: Context, id: String, value: String) {
        ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit().putString(id, value).apply()
        strCache.put(id, value, System.currentTimeMillis())
    }

    /** 立即丢弃缓存（诊断页"刷新"、以及门禁自检用）。 */
    fun invalidate() {
        boolCache.invalidate()
        strCache.invalidate()
    }

    /** 已缓存多少个 key（诊断用：判断 TTL 是否真的在工作）。 */
    fun cacheSize(): Int = boolCache.size + strCache.size
}
