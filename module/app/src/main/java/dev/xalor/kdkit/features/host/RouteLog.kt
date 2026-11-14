package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.RouteFilter
import dev.xalor.kdkit.util.Xp

/** 路由观测：记录 App 内部 `zyb://` 路由的**实际跳转**（"哪个操作触发哪个路由"）。（**热开关**）
 *
 *  为什么需要：本会话反复看到 `zyb://` 路由的**定义**（`route.zybUrl` / `aidUploadGuide` / `vip.link`），
 *  但**从未观测到一次真实跳转** —— 缺口是"触发关系"，不是"路由清单"。
 *
 *  hook 点（静态定位，见 work/ROUTE_LOG_PLAN.md）：
 *  `com.zuoyebang.router.r0` —— 32 个 public 方法 / 148 处 String 引用（入口类）。
 *  首选 `h(String)`：**收 path、返回 builder**，是"path → builder"的漏斗；
 *  另挂 `I(String)` / `l(String)`（直接跳转），以防 `h` 不是唯一入口。
 *
 *  验收：点 VIP 入口 ⇒ 应出现 `zyb://kd-vip/page/vip-buy`（该路由见 R365 的 `vip.link`）。
 *
 *  2026-10-25：`I(String)` 实测也被用于非路由字符串（init/cacheLoaded），过滤规则与调用方
 *  提取抽到 [RouteFilter]（可单测）。另外加了"每条路由只记一次 + 总量上限"，
 *  避免页面轮询把 `ROUTE` 行刷成噪音。
 */
object RouteLog : SwitchFeature(
    id = "route_log",
    title = "路由观测",
    summary = "记录 zyb:// 路由的实际跳转（path + 调用方），回答\"哪个操作触发哪个路由\"",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val CLS = "com.zuoyebang.router.r0"
    private val seenOnce = java.util.Collections.synchronizedSet(HashSet<String>())

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "route_log_dedupe",
            title = "同一路由只记一次",
            summary = "关掉则记录每一次跳转（含重复），用于统计频次",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        if (Xp.clazzOrNull(CLS) == null) {
            KdLog.w("RouteLog: class not found ($CLS)")
            return
        }
        // 三个入口都写**字面量**类名与方法名，而不是传变量：
        // 静态门禁（check_hook_targets.py / check_hook_signatures.py）是按字面量解析的，
        // 用 `cls.name` / `hookOne(m)` 传进去会让这个功能**从未被任何门禁校验过**
        // —— 2026-10-25 发现的真实盲区（当时它的目标是全模块唯一 0 覆盖的）。
        var n = 0
        n += hookOne("h")
        n += hookOne("I")
        n += hookOne("l")
        KdLog.i("RouteLog installed (hooks=$n)")
    }

    private fun hookOne(name: String): Int = when (name) {
        "h" -> if (Xp.hook("com.zuoyebang.router.r0", "h", String::class.java, gate = id,
                onBefore = { onRoute(it, "h") })) 1 else 0
        "I" -> if (Xp.hook("com.zuoyebang.router.r0", "I", String::class.java, gate = id,
                onBefore = { onRoute(it, "I") })) 1 else 0
        "l" -> if (Xp.hook("com.zuoyebang.router.r0", "l", String::class.java, gate = id,
                onBefore = { onRoute(it, "l") })) 1 else 0
        else -> 0
    }

    private fun onRoute(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam, name: String) {
        val arg = p.args.firstOrNull()?.toString() ?: return
        if (!RouteFilter.looksLikeRoute(arg)) return
        val dedupe = dev.xalor.kdkit.config.KdConfig.isOn("route_log_dedupe", true)
        if (dedupe && !seenOnce.add(arg)) return
        if (!RateLimit.firstN("route.capture", 1_000)) return
        Capture.append("ROUTE $name $arg | from=" + RouteFilter.caller(Throwable().stackTrace))
    }
}
