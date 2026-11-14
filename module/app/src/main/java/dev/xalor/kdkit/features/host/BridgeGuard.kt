package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.RawListMemo
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicInteger

/**
 * 桥守卫：按黑名单拦下网页侧发起的原生 action（默认关闭）。（**热开关**）
 *
 * 走查结论（`work/TRIAGE.md` §8.3）：第二层核心桥把不少宿主能力直接交给页面 ——
 * `core_showDebuger`（打开宿主调试面板）、`core_login` 里的 `logout`（**页面能把用户登出**）、
 * `core_openWxApplet`（拉微信小程序）…… 这是 App 的设计，但页面一旦被第三方内容/注入影响，
 * 这些就是最直接的着力点。
 *
 * 另有一条 **HTTP 域名白名单**：`core_httpRequest` 的 URL 会先解析 host（相对路径 = 宿主自己的域名），
 * 不在白名单里就拒掉 —— 对着 §8.1"页面能借已签名通道发任意请求、没有 host 白名单"那条发现。
 *
 * 默认黑名单：
 *  * `core_showDebuger` —— 一律拦；
 *  * `core_login` —— 只在载荷含 `logout` 时拦（正常登录放行）。
 *
 * 另有 `bridge_guard_probe_remove_loading`：把页面每次都会调的 `core_removeLoading` 也拦下来，
 * **专门用来做开/关对照验收**（不用它就没法在日常浏览里观察到"确实拦到了"）。
 */
object BridgeGuard : SwitchFeature(
    id = "bridge_guard",
    title = "桥守卫（页面侧敏感 action）",
    summary = "拦下网页发起的 core_showDebuger / 登出类 core_login；另有对照开关可验证拦截确实生效",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private val blocked = AtomicInteger()

    override val options: List<KdOption> = listOf(
        KdOption(
            key = KEY_LIST,
            title = "黑名单 action",
            summary = "逗号分隔；core_login 特判为只拦登出",
            kind = KdOption.Kind.STRING,
            default = DEFAULT_LIST,
        ),
        KdOption(
            key = KEY_HTTP_ALLOW,
            title = "HTTP 允许域名后缀",
            summary = "逗号分隔；相对路径按宿主域名判定",
            kind = KdOption.Kind.STRING,
            default = DEFAULT_HTTP_ALLOW,
        ),
        KdOption(
            key = PROBE_KEY,
            title = "对照开关：拦 core_removeLoading",
            summary = "打开它才能在正常浏览里观察到拦截计数增长（验收用）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        var n = 0
        n += Xp.hookAllBefore(CLASS, "dispatchAction", Xp.classLoader, gate = id) { param -> decide(param) }
        n += Xp.hookAllBefore(CLASS, "dispatchActionToListeners", Xp.classLoader, gate = id) { param -> decide(param) }
        KdLog.i("BridgeGuard installed ($n hooks, blacklist=${blacklist()})")
    }

    /**
     * 黑名单来自设置页（逗号分隔）；默认 `core_showDebuger`。`core_login` 特判为"只拦登出"。
     *
     * 解析结果用 [RawListMemo] 记住：本方法在**每次** JS 桥分发时被调用
     * （实测一次会话 282 次），原来每次都要 `split + map + filter + toMutableList` 四趟分配。
     */
    private val listMemo = RawListMemo()

    /** 非 void 只告警一次，避免每次分派都刷日志。 */
    private val nonVoidWarned = java.util.concurrent.atomic.AtomicBoolean(false)

    private fun blacklist(): List<String> {
        val raw = KdConfig.getString(KEY_LIST, DEFAULT_LIST)
        val base = listMemo.get(raw) { r ->
            r.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        }
        if (KdConfig.isOn(PROBE_KEY, false) && !base.contains("core_removeLoading")) {
            return base + "core_removeLoading"
        }
        return base
    }

    /**
     * 页面侧 HTTP 允许的域名后缀。
     *
     * 相对路径不是"放行"，而是**解析成宿主自己的域名**（`/kdchat/api/...` → [SELF_HOST]）再一起判定 ——
     * 这才是它真实的语义；否则白名单对绝大多数桥请求不起作用（实测：捕获里 100% 是相对路径）。
     */
    private fun httpAllowed(url: String): Boolean {
        val host = if (url.startsWith("http://") || url.startsWith("https://")) {
            try { java.net.URI(url).host ?: return false } catch (t: Throwable) { return false }
        } else {
            SELF_HOST
        }
        return HostAllowList.allows(
            host = host,
            rawAllowList = KdConfig.getString(KEY_HTTP_ALLOW, DEFAULT_HTTP_ALLOW),
        )
    }

    private fun decide(param: XC_MethodHook.MethodHookParam) {
        val action = param.args.firstOrNull { it is String } as? String ?: return
        val json = param.args.firstOrNull { it is JSONObject } as? JSONObject
        val url = json?.optString("url").orEmpty()
        val hit = when {
            blacklist().contains(action) -> true
            action == "core_login" && json?.has("logout") == true -> true
            action == "core_httpRequest" && url.isNotEmpty() && !httpAllowed(url) -> true
            else -> false
        }
        if (!hit) return
        // **只在方法是 void 时**才 `result = null`。
        //
        // `param.result` 的语义是"跳过原方法实现，用这个值当返回值"。原方法 `V` 时它无害；
        // 但一旦某个重载变成有返回值（例如改成 `boolean dispatchAction(...)`），
        // 调用方就会拿到 `null` —— 拆箱 NPE 或直接判空崩溃，而**症状与本次拦截毫无关系**，
        // 极难查（2026-11-02 审查 P2-10）。
        //
        // 现状：7.9.0 的两个重载都是 `V`（`check_bridge_guard_void.py` 逐条断言）。
        // 这里加运行时判断，是为了让下个版本即使变成非 void 也只是"拦截失效"而不是"宿主崩"。
        // `MethodHookParam.method` 声明成 `Member`，`returnType` 在 `Method` 上 —— 要转。
        val hooked = param.method as? java.lang.reflect.Method
        if (hooked == null || hooked.returnType != Void.TYPE) {
            if (nonVoidWarned.compareAndSet(false, true)) {
                KdLog.w(
                    "BridgeGuard: ${param.method.name} 现在返回 " +
                        "${hooked?.returnType?.name ?: "?"}，" +
                        "**不是 void ⇒ 本功能不拦它**（置 null 会让调用方拿到 null 并崩溃）。" +
                        "钩子目标变了，需重新评估拦截写法。",
                )
            }
            return
        }
        param.result = null                       // 跳过原实现（dispatchAction 无返回值语义）
        val why = if (action == "core_httpRequest") " host_not_allowed" else " blacklist"
        val n = blocked.incrementAndGet()
        KdLog.w("BridgeGuard: blocked $action$why #$n ${json?.toString()?.take(110) ?: ""}")
        // 也给 kit 留一份（guard_report.py 会把它汇总成"拦了什么、拦了多少"）。
        // 上限 5000：拦的是敏感 action，量级本来就小；但页面卡死循环时也要有硬边界。
        if (RateLimit.firstN("guard.capture", 5_000)) {
            Capture.append("GUARD blocked=$action reason=${why.trim()} url=$url #$n")
        }
    }

    /** 诊断用：本次进程拦了多少次。 */
    fun blockedCount(): Int = blocked.get()

    const val KEY_LIST = "bridge_guard_list"
    const val DEFAULT_LIST = "core_showDebuger"
    /** 相对路径解析出的宿主域名（与 `work/API_SURFACE.md` 里捕获到的 host 一致）。 */
    const val SELF_HOST = "www.kuaiduizuoye.com"
    const val KEY_HTTP_ALLOW = "bridge_guard_http_allow"
    const val DEFAULT_HTTP_ALLOW = "kuaiduizuoye.com,zuoyebang.com"
    const val PROBE_KEY = "bridge_guard_probe_remove_loading"
    private const val CLASS = "com.baidu.homework.common.ui.widget.HybridWebView"
}
