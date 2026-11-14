package dev.xalor.kdkit.features.web

import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.NavFilter
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * Shared WebView injection plumbing.
 *
 * Every userscript is concatenated and injected on each page load. `onPageFinished` is hooked on
 * the *concrete* client captured from `setWebViewClient`, because the host's client overrides it
 * without calling super — hooking the base class silently never fires.
 *
 * ### 2026-10-25
 *  * **注入去重**：同一 (WebView, url) 在同一页面生命周期里只注入一次。此前 `loadUrl` 与
 *    `onPageFinished` 都会调 `inject()`（带 300ms 延迟），于是每次页面加载实际注入两遍 ——
 *    PK 脚本有 `__kdkit` 守卫所以看不出来，但 eruda / xhr recorder 会各初始化两套。
 *  * **空载荷不注入**：所有 provider 都关着时 `payload()` 是空串，旧实现仍会 post 一个空
 *    `evaluateJavascript` —— 每个页面一次无意义跨进程调用。
 *  * **页面自有请求**改为走共享 [Capture]，并复用 [NavFilter.isAsset]（原来这里有一份自己的正则）。
 */
object WebInjector {

    private val providers = mutableListOf<Pair<String, () -> String>>()

    /**
     * 已注入过的 `webviewIdentity@url`。
     *
     * 用**有界** LRU 集合而不是 WeakHashMap：键是新建的 String，弱引用挂在字符串上永远不回收
     * ⇒ 反而会无界增长（这一点是写完才发现并改的）。容量取 256，覆盖一次会话里所有页面绰绰有余。
     */
    private val injected = object : LinkedHashMap<String, Boolean>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Boolean>?): Boolean =
            size > MAX_INJECT_MEMORY
    }

    private const val MAX_INJECT_MEMORY = 256

    /** 当前注册了哪些 provider —— 供 `BaseFeature` 判断"注册型功能确实注册了"。 */
    fun providerNames(): List<String> = synchronized(providers) { providers.map { it.first } }

    fun register(name: String, provider: () -> String) {
        providers.removeAll { it.first == name }
        providers.add(name to provider)
    }

    private fun payload(): String =
        providers.joinToString("\n;\n") { (_, p) ->
            runCatching { p() }.getOrElse { "" }
        }

    fun install(): Int {
        val main = Handler(Looper.getMainLooper())
        var n = 0

        fun inject(wv: WebView?, url: String?) {
            if (wv == null || url == null || url.startsWith("javascript:")) return
            // page_js 的开关必须在这里判：`PageJs` 自己没有钩子（只贡献一个配置字符串），
            // 所以"关掉 page_js"曾经没有任何效果 —— 只要 page_js_script 非空就注入。
            val userJs = if (KdConfig.isOn("page_js", false)) {
                runCatching { KdConfig.getString("page_js_script", "") }.getOrDefault("")
            } else {
                ""
            }
            val code = InjectPlan.compose(payload(), userJs)
            if (code.isBlank()) return                     // 全部关闭：不做任何跨进程调用
            val token = InjectPlan.dedupeKey(System.identityHashCode(wv), url)
            synchronized(injected) {
                if (injected.put(token, true) != null) return   // 同一页面已注入过
            }
            main.postDelayed({
                runCatching { wv.evaluateJavascript(code, null) }
                    .onFailure { KdLog.e("inject failed", it) }
            }, 300)
        }

        val hookedClients = HashSet<String>()
        fun hookClient(client: Any?) {
            val name = client?.javaClass?.name ?: return
            if (!hookedClients.add(name)) return
            val c = Xp.hookAllAfter(name, "onPageFinished", onAfterCb = { p ->
                val wv = p.args.getOrNull(0) as? WebView
                val url = p.args.getOrNull(1) as? String
                if (KdConfig.isOn("nav_log", true) && url != null) KdLog.d("page: $url")
                inject(wv, url)
            })
            KdLog.d("client $name onPageFinished hooks=$c")
            // 页面**自己**发的请求（WebView 原生 XHR / 资源加载）不经过宿主的 OkHttp，因此抓取里看不到。
            // 挂 shouldInterceptRequest 才能把它们记下来 —— 由功能 web_request_log 控制（默认关）。
            val r = Xp.hookAllBefore(name, "shouldInterceptRequest") { p ->
                if (!KdConfig.isOn("web_request_log", false)) return@hookAllBefore
                val req = p.args.getOrNull(1) ?: return@hookAllBefore
                val url = runCatching {
                    req.javaClass.getMethod("getUrl").invoke(req)?.toString()
                }.getOrNull() ?: return@hookAllBefore
                if (!url.startsWith("http")) return@hookAllBefore
                if (!RateLimit.firstN("webreq", 3_000)) return@hookAllBefore
                // 静态资源只记 URL；**非静态**（接口/埋点）多记一层请求头摘要 —— 回答"页面自己的接口怎么鉴权"。
                if (NavFilter.isAsset(url)) {
                    Capture.append("WEBREQ $url")
                } else {
                    val hdrs = runCatching {
                        req.javaClass.getMethod("getRequestHeaders").invoke(req) as? Map<*, *>
                    }.getOrNull()
                    val brief = hdrs?.entries
                        ?.filter { (k, _) -> !k.toString().equals("Accept-Encoding", true) }
                        ?.take(12)
                        ?.joinToString(", ") { (k, v) -> "$k=${v.toString().take(48)}" }
                        ?: ""
                    Capture.append("WEBREQ $url | $brief")
                }
            }
            if (r > 0) KdLog.d("client $name shouldInterceptRequest hooks=$r")
        }

        if (Xp.hook(
                "android.webkit.WebView", "setWebViewClient",
                android.webkit.WebViewClient::class.java,
                onAfter = { p -> hookClient(p.args.getOrNull(0)) },
            )
        ) n++
        if (Xp.hook(
                "android.webkit.WebView", "loadUrl", String::class.java,
                onAfter = { p -> inject(p.thisObject as? WebView, p.args.getOrNull(0) as? String) },
            )
        ) n++
        if (Xp.hook(
                "android.webkit.WebView", "loadUrl", String::class.java, java.util.Map::class.java,
                onAfter = { p -> inject(p.thisObject as? WebView, p.args.getOrNull(0) as? String) },
            )
        ) n++
        if (Xp.hook(
                "android.webkit.WebView", "loadDataWithBaseURL",
                String::class.java, String::class.java, String::class.java, String::class.java, String::class.java,
                onAfter = { p -> inject(p.thisObject as? WebView, p.args.getOrNull(0) as? String) },
            )
        ) n++
        return n
    }
}
