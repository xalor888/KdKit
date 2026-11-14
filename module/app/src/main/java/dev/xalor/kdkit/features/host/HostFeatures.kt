package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedHelpers
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.features.web.WebInjector
import dev.xalor.kdkit.features.web.WebScripts
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/** H5 调试台：在所有宿主 WebView 里注入 eruda。（**热开关**） */
object H5DebugConsole : SwitchFeature(
    id = "h5_debug",
    title = "H5 调试台",
    summary = "在网页里注入 eruda 控制台，可查看日志 / DOM / 网络",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    override fun install() {
        // 注册即常驻；provider 每次页面加载都问一次配置 ⇒ 关掉后新页面不再注入。
        WebInjector.register("eruda") { if (KdConfig.isOn(id, false)) WebScripts.debugConsole() else "" }
        KdLog.i("H5DebugConsole registered")
    }
}

/**
 * 宿主请求头观测：记录 App 的 OkHttp/Volley 请求**带了哪些头**（观测面里"URL 之外"的那一半）。
 *
 * 为什么需要：某些接口的失败无法用"参数/签名"解释（例如 `kdapi/popup/gradeupgrade` 的 `906003`），
 * 而差异只可能在 URL 之外 —— 头就是最可能的那一项。
 *
 * 2026-10-25：改为走共享 [Capture]（原来自己开一套 file + stamp + cap，三份重复实现之一），
 * 并加预算（[RateLimit]）—— 头表每请求一次，不设上限会在一轮会话里写出几百 MB。
 */
object ReqHeaders : SwitchFeature(
    id = "req_headers",
    title = "宿主请求头观测",
    summary = "记录 OkHttp/Volley 请求构造时的头（名与值，值截断），回答\"App 带了哪些我们没带的头\"",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val MAX = 200
    private const val BUDGET = 400

    override fun install() {
        val g = id
        var n = 0
        n += hookStaticHeaders(g)
        n += hookPerRequestHeaders(g)
        n += hookVolleyHeaders(g)
        KdLog.i("ReqHeaders armed (hooks=$n, budget=$BUDGET)")
    }

    /** Volley 的规范钩点：`com.android.volley.v.getHeaders()`（每个请求都会走） */
    private fun hookVolleyHeaders(gate: String): Int = try {
        XposedHelpers.findAndHookMethod("com.android.volley.v", Xp.classLoader,
            "getHeaders", object : XC_MethodHook() {
                override fun afterHookedMethod(p: MethodHookParam) {
                    if (!KdConfig.isOn(gate, false)) return
                    if (!RateLimit.firstN("hdr.volley", BUDGET)) return
                    val m = p.result as? Map<*, *> ?: return
                    val url = runCatching {
                        XposedHelpers.callMethod(p.thisObject, "getUrl").toString()
                    }.getOrNull() ?: ""
                    val short = url.substringAfter("://").substringBefore('?')
                    val line = m.entries.joinToString(" | ") { (k, v) -> "$k=${v.toString().take(64)}" }
                    // 业务域 `__pid`：决定服务端按哪个域校验。重放工具此前不看它，
                    // 于是"pid 带错"会被误归因成"签名不对"。
                    // 链路：volley 请求对象 → HWRequest.mInputBase → InputBase.__pid。
                    // 拿不到就写 `-`，不猜也不省略（省略会让人以为这个接口没有域）。
                    val pid = pidOf(p.thisObject)
                    KdLog.i("HDR(v) $short pid=$pid :: ${line.take(MAX)}")
                    Capture.append("HDR(v) $short pid=$pid :: $line")
                }
            })
        1
    } catch (t: Throwable) {
        KdLog.w("ReqHeaders: volley hook failed: ${t.message}")
        0
    }

    /**
     * 从 volley 请求对象读出业务域 `__pid`。
     *
     * 反射链：`request.mInputBase`（`HWRequest` 的 protected final 字段）→ `InputBase.__pid`。
     * 两者都由 `api_pid_map.py` 从 smali 静态确认过存在。
     *
     * 返回 `-` 表示拿不到（非 `HWRequest` 子类、字段改名、或 pid 为空）——
     * **不省略这一列**：省略会让人以为"这个接口没有业务域"，而实际可能是读取失败。
     */
    private fun pidOf(req: Any?): String = try {
        // 用 `util.Reflect` 而不是直接反射：`mInputBase` 是 `protected`，
        // `getField` 对它抛异常而非返回 null（第一版就栽在这里，pid 恒为 "-"）。
        val base = dev.xalor.kdkit.util.Reflect.field(req, "mInputBase") ?: return "-"
        dev.xalor.kdkit.util.Reflect.stringField(base, "__pid")?.ifEmpty { "-" } ?: "-"
    } catch (t: Throwable) {
        "-"
    }

    /** 静态头表：`public static getStaticHeaders()Ljava/util/Map;` */
    private fun hookStaticHeaders(gate: String): Int = try {
        XposedHelpers.findAndHookMethod("com.baidu.homework.common.net.Net", Xp.classLoader,
            "getStaticHeaders", object : XC_MethodHook() {
                override fun afterHookedMethod(p: MethodHookParam) {
                    if (!KdConfig.isOn(gate, false)) return
                    if (!RateLimit.firstN("hdr.static", 4)) return
                    val m = p.result as? Map<*, *> ?: return
                    val line = m.entries.joinToString(" | ") { (k, v) -> "$k=${v.toString().take(64)}" }
                    KdLog.i("HDR(static) ${line.take(MAX)}")
                    Capture.append("HDR(static) $line")
                }
            })
        1
    } catch (t: Throwable) {
        KdLog.w("ReqHeaders: getStaticHeaders hook failed: ${t.message}")
        0
    }

    /** 每次请求的头表：`d(String,String,String,HashMap)`（synthetic，但会被调用） */
    private fun hookPerRequestHeaders(gate: String): Int = try {
        XposedHelpers.findAndHookMethod("com.baidu.homework.common.net.Net", Xp.classLoader,
            "d", String::class.java, String::class.java, String::class.java, HashMap::class.java,
            object : XC_MethodHook() {
                override fun beforeHookedMethod(p: MethodHookParam) {
                    if (!KdConfig.isOn(gate, false)) return
                    if (!RateLimit.firstN("hdr.request", BUDGET)) return
                    val m = p.args.getOrNull(3) as? Map<*, *> ?: return
                    val url = (p.args.getOrNull(0) as? String) ?: ""
                    val short = url.substringAfter("://").substringBefore('?')
                    val line = m.entries.joinToString(" | ") { (k, v) -> "$k=${v.toString().take(64)}" }
                    KdLog.i("HDR $short :: ${line.take(MAX)}")
                    Capture.append("HDR $short :: $line")
                }
            })
        1
    } catch (t: Throwable) {
        KdLog.w("ReqHeaders: per-request hook failed: ${t.message}")
        0
    }
}

/**
 * 页面脚本注入（通用）：把配置通道里的 `page_js_script` 字符串作为用户脚本执行。
 *
 * 由 kit 侧的 `call_page_js.py` 写入 —— 便于"从外部触发页面自身逻辑"（如点击页面里的快门）。
 * 它是**唯一**由脚本而不是界面驱动的设置，因此在 schema 里标 `userEditable = false`。
 */
object PageJs : SwitchFeature(
    id = "page_js",
    title = "页面脚本注入（page_js_script）",
    summary = "执行配置通道里 page_js_script 字符串（写给 kit 的 call_page_js.py 用）",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    override val options: List<KdOption> = listOf(
        KdOption(
            key = "page_js_script",
            title = "页面脚本",
            summary = "任意 JS，每次页面加载后执行；由 kit/scripts/call_page_js.py 写入",
            kind = KdOption.Kind.STRING,
        ),
    )

    override fun install() {
        // WebInjector 每次注入都会读 page_js_script，因此本功能不需要自己的钩子；
        // 台账里记 0 条是**正确的**，不是漏装。
        KdLog.i("PageJs armed (WebInjector reads page_js_script)")
    }
}

/** 页面自有请求记录：把 WebView 原生请求（页面自己的 XHR / 资源）写进抓取。（**热开关**） */
object WebRequestLog : SwitchFeature(
    id = "web_request_log",
    title = "页面自有请求记录",
    summary = "记录 WebView 自己发出的请求（不经过宿主 OkHttp 的那批），写入抓取文件",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    override fun install() {
        // Java 侧：WebView 原生请求的 URL/头（WebInjector 里）；JS 侧：页面 XHR/fetch 的 **body**（这里）。
        // 两侧同一个开关 —— body 只有页面里才拿得到（shouldInterceptRequest 看不到 body）。
        WebInjector.register("xhrlog") {
            if (KdConfig.isOn(id, false) && KdConfig.isOn("web_request_log_bodies", true)) {
                WebScripts.xhrRecorder()
            } else ""
        }
        KdLog.i("WebRequestLog armed (java hook + page-side xhr recorder)")
    }

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "web_request_log_bodies",
            title = "记录请求体",
            summary = "页面 XHR/fetch 的 body 也一起记（体量更大，默认开）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )
}

/** 广告 SDK 阻断：不初始化穿山甲 / 优量汇 / 快手 / 百度 广告 SDK。（**热开关**） */
object BlockAdSdk : SwitchFeature(
    id = "block_ad_sdk",
    title = "广告 SDK 阻断",
    summary = "不初始化第三方广告 SDK，从进程内彻底断开广告请求（改开关即时生效）",
    category = Category.ADS,
    defaultOn = false,
    hot = true,
) {
    private const val ARG = "yc.a"

    override fun install() {
        // 四个 SDK 各写一遍字面量：门禁按字面量解析（用 listOf 循环变量会让 4 条全失去校验）。
        // `xc.a` 是这些 init 方法共同的形参类型，只能在运行时解析。
        // 这个 `arg` 不再传给钩子（那样会让 ⑤ 拼成 `(*)`），只作**前置守卫**：
        // `xc.a` 缺失说明宿主换了广告 SDK 版本，提前返回比装 4 个注定失败的钩子更好，
        // 而且日志能直接指出是哪个类缺了。
        Xp.clazzOrNull(ARG) ?: run {
            KdLog.w("BlockAdSdk: $ARG not found, cannot hook SDK inits")
            return
        }
        var n = 0
        // 形参写字面量 `Xp.clazz("yc.a")`：⑤ 按整行的字面量序列拼签名，
        // 传变量 `arg`/`ARG` 都拼成 `(*)` ——「匹配任意参数个数」，等于这条完全没校验。
        if (Xp.hook("com.fastad.csj.FastAdCsjManager", "initCsjSDK", Xp.clazz("yc.a"), gate = id, onBefore = { it.result = null })) n++
        if (Xp.hook("com.fastad.ylh.FastAdYlhManager", "initYlhSDK", Xp.clazz("yc.a"), gate = id, onBefore = { it.result = null })) n++
        if (Xp.hook("com.fastad.ks.FastAdKsManager", "initKsSdk", Xp.clazz("yc.a"), gate = id, onBefore = { it.result = null })) n++
        if (Xp.hook("com.fastad.baidu.FastAdBDManager", "initBaiduSDK", Xp.clazz("yc.a"), gate = id, onBefore = { it.result = null })) n++
        KdLog.i("BlockAdSdk installed ($n hooks)")
    }
}
