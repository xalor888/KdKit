package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.NavFilter
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 页面导航观测：记录**每一次 H5 页面加载**（"去了哪个页面"）。（**热开关**）
 *
 * 为什么需要：`UNVISITED_PAGES.md` 算出 **45 个 H5 页面**没被观测到，
 * 而"靠坐标点击去点"**不可靠**（试过 6 次以上，见 R412）⇒ **换成让模块记**。
 *
 * hook 点：`android.webkit.WebView.loadUrl(String)` —— **框架类** ⇒ 一处挂、
 * 覆盖**所有** WebView 的**每一次**加载（含带 header 的重载）。
 * 原生侧用 `android.app.Activity.onCreate(Bundle)` 补上"原生页面"那一半。
 *
 * 与既有功能互补：`RouteLog` 记**路由**、`PageJs` 记**打开后的页面内部**、
 * 本功能记**"打开动作"本身**。
 *
 * 2026-10-25：URL 归一化 / 去重 / 过滤逻辑抽到 [NavFilter]（纯函数，可单测）——
 * 原来这些都在钩子闭包里，一改就得靠真机验证，而它恰好是"页面名少数一位就统计不到"的地方。
 */
object NavLog : SwitchFeature(
    id = "nav_log",
    title = "页面导航观测",
    summary = "记录每一次 H5 页面加载（WebView.loadUrl），回答\"去了哪个页面\"（改开关即时生效）",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val CLS = "android.webkit.WebView"
    private val seen = java.util.Collections.synchronizedSet(HashSet<String>())

    override fun install() {
        var n = 0
        // ① loadUrl(String)
        if (Xp.hook("android.webkit.WebView", "loadUrl", String::class.java, gate = id, onBefore = {
                record(it.args.firstOrNull() as? String)
            })
        ) n++
        // ② loadUrl(String, Map)（带 header 的重载）
        if (Xp.hook("android.webkit.WebView", "loadUrl", String::class.java, java.util.Map::class.java, gate = id, onBefore = {
                record(it.args.firstOrNull() as? String)
            })
        ) n++
        // ③ 原生侧：Activity.onCreate(Bundle) —— 框架类，一处挂覆盖所有子类
        if (Xp.hook("android.app.Activity", "onCreate", android.os.Bundle::class.java, cl = null,
                gate = id, onAfter = {
                    val cls = it.thisObject?.javaClass?.name ?: return@hook
                    if (!NavFilter.isHostClass(cls)) return@hook
                    val short = NavFilter.activityName(cls)
                    if (seen.add("ACT:$short")) Capture.append("NAVACT " + short.take(90))
                })
        ) n++
        KdLog.i("NavLog installed (hooks=$n)")
    }

    /** 只记"页面"（含 hycache 的本地页 或 http(s)），且**同一页面只记一次**。 */
    private fun record(url: String?) {
        val name = NavFilter.pageKey(url) ?: return
        if (!seen.add(name)) return
        if (!RateLimit.firstN("nav.capture", 2_000)) return
        Capture.append("NAV " + name.take(90) + " | " + url!!.take(120))
    }

    /** 本次进程观测到多少个不同页面（诊断用）。 */
    fun pageCount(): Int = seen.size
}
