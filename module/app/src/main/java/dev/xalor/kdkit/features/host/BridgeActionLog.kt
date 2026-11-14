package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.DecodeRequestShape
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp
import org.json.JSONObject

/**
 * 高价值桥 action 的**语义级**观测（默认关闭，热开关）。
 *
 * 与 `h5_bridge_log` 的区别：那个记"所有 action 的名字与原始 JSON"（面广、噪音大）；
 * 这个只盯几条**有明确语义**的 action，把参数解析成结构化字段，因此可以直接回答业务问题：
 *
 * ```
 * BRIDGE downloadMedia type=1 url=https://.../xxx.jpg        ← 页面想让宿主存哪张图
 * BRIDGE getuserinfo asked identity=...                      ← 谁在打听用户身份
 * BRIDGE payorder submit len=... keys=payInfo,... pid=vip    ← 页面在往哪个支付接口递什么
 * ```
 *
 * ### 目标为什么是它们（`module/NEW_TARGETS.md` §3–§4）
 *
 *  * `FeDownloadMediaAction`（`@FeAction(name="downloadMedia")`，`:697`）：读 `json["type"]`，
 *    只有 `type==1`（`PIC_TYPE`）才真正 `downloadPicture(Activity,String)` 落盘并
 *    `MediaScannerConnection.scanFile` 进相册。也就是说**一个页面可以静默往相册写图片**——
 *    这条观测让"写了什么、从哪来"留痕。
 *  * `GetUserInfoWebAction`（`@FeAction(name="getuserinfo")`，`:132`）：只回
 *    `identityName` / `uid` / `uname`（**不含**手机号 / token / VIP），未登录时回空串。
 *    记它可以回答"哪类页面在打听用户身份"。
 *  * `FetchPayInfosAction`（`@FeAction(name="fetchPayInfos")`，2026-10-25 第 28 轮补）：
 *    把页面传来的 `payInfo` 字符串**原样**塞进 `Scancodecreatepayorder$Input`
 *    （`__url=/vippayui/clientpay/kdclientinnerpayorder`、`__pid=vip`、`__method=1` 即 POST），
 *    再把回包里的 `payInfo` 交回页面。也就是说**页面能直接驱动下单请求**。
 *    记它是为了回答"哪个页面、在什么时候、拿着多大的 payload 去碰了支付接口"。
 *
 * ### 为什么不用 hookAll
 *
 * 7 个 `FeAction` 类共享方法名 `onAction`，基类 `WebAction` 也有 —— `hookAllAfter("...WebAction","onAction")`
 * 会命中 397 个 action。这里必须**按精确类**钩。
 */
object BridgeActionLog : SwitchFeature(
    id = "bridge_action_log",
    title = "高价值桥 action 观测",
    summary = "结构化记录 downloadMedia / getuserinfo 的参数（页面往相册写什么、在打听哪些身份字段）",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val MAX = 8

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "bridge_action_log_url",
            title = "记录完整下载 URL",
            summary = "关掉则只记 host + 路径长度（URL 里可能带有时效签名）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        val returnCb = Xp.clazzOrNull("com.baidu.homework.common.ui.widget.HybridWebView\$ReturnCallback")
        var n = 0
        if (returnCb != null) {
            // ① downloadMedia：页面要求把某张图存进相册
            if (Xp.hook(
                    "com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction", "onAction",
                    android.app.Activity::class.java, org.json.JSONObject::class.java, returnCb,
                    gate = id, onBefore = { p -> recordDownload(p.args.getOrNull(1) as? JSONObject) },
                )
            ) n++
            // ② getuserinfo：页面在打听用户身份
            if (Xp.hook(
                    "com.kuaiduizuoye.scan.login.bridge.GetUserInfoWebAction", "onAction",
                    android.app.Activity::class.java, org.json.JSONObject::class.java, returnCb,
                    gate = id, onBefore = { recordUserInfo() },
                )
            ) n++
            // ③ fetchPayInfos：页面在驱动下单。`payInfo` 原样转发到 VIP 支付接口
            //    （`__url=/vippayui/clientpay/kdclientinnerpayorder`、`__pid=vip`、POST），
            //    所以这条记录的价值不在"值"，而在"谁、何时、多大、带哪些键"。
            if (Xp.hook(
                    "com.kuaiduizuoye.scan.web.actions.FetchPayInfosAction", "onAction",
                    android.app.Activity::class.java, org.json.JSONObject::class.java, returnCb,
                    gate = id, onBefore = { p -> recordPayOrder(p.args.getOrNull(1) as? JSONObject) },
                )
            ) n++
            // ④ decode_httpRequest：页面能让宿主**代发一条带签名的请求**。
            //    `DecodeHttpRequestWebAction.onAction` 把 params 拼成 `k=v&k=v`，
            //    再拼上字面量 `encryptPath=` + url，交给 `yl.f.h(...)` 签名，
            //    然后 `HttpCurrencyRequest$Input.buildInput(url, sign)` 直接 POST。
            //    ⇒ 页面能把请求打到**任意 url**，并且由宿主侧完成签名。
            //    这条观测回答"哪个页面在借宿主的签名手发请求"。
            if (Xp.hook(
                    "com.kuaiduizuoye.scan.web.actions.DecodeHttpRequestWebAction", "onAction",
                    android.app.Activity::class.java, org.json.JSONObject::class.java, returnCb,
                    gate = id, onBefore = { p -> recordDecodeRequest(p.args.getOrNull(1) as? JSONObject) },
                )
            ) n++
        }
        KdLog.i("BridgeActionLog installed ($n hooks)")
    }

    private fun recordDownload(json: JSONObject?) {
        if (json == null) return
        if (!RateLimit.firstN("bridge.download", 200)) return
        val type = runCatching { json.optInt("type", -1) }.getOrDefault(-1)
        val url = runCatching { json.optString("url", "") }.getOrDefault("")
        val shown = when {
            url.isEmpty() -> "(empty)"
            dev.xalor.kdkit.config.KdConfig.isOn("bridge_action_log_url", true) -> url.take(200)
            else -> runCatching {
                val u = java.net.URI(url)
                "${u.host ?: "?"}${u.path?.let { p -> " (path ${p.length} chars)" } ?: ""}"
            }.getOrDefault("(unparseable)")
        }
        Capture.append("BRIDGE downloadMedia type=$type url=$shown")
        if (type != 1) KdLog.d("BridgeActionLog: downloadMedia type=$type (host ignores non-1)")
    }

    /**
     * 只记"页面在打听身份"这件事，**不假装能拿到回包**：
     * `onAction` 里的 `JSONObject` 是方法内 `new` 的局部变量，钩子拿不到它。
     * 想改/看回包得挂在 `HybridWebView$ReturnCallback.call(JSONObject)` 上并按调用栈过滤
     * （那会命中所有 bridge 回包，代价大，见 NEW_TARGETS.md §4.3）。
     *
     * 取值侧的稳定锚点是 `qh.o.s()`（用户模型）/ `qh.n.h()`（身份名），但它们在这里
     * 只是"顺带读一眼"，绝不作为回包内容的证据。
     */
    private fun recordUserInfo() {
        if (!RateLimit.firstN("bridge.userinfo", 200)) return
        val identity = runCatching { XposedHelpersCall.staticString(Xp.clazz("qh.n"), "h") }.getOrNull()
        Capture.append("BRIDGE getuserinfo asked identity=${identity?.take(40) ?: "?"}")
    }

    /**
     * `fetchPayInfos`：页面把 `payInfo` 递进来，宿主原样 POST 到 VIP 支付接口。
     *
     * **不记 `payInfo` 的值**。它是页面拼的 JSON，里面可能有订单号 / 金额 / 商品 id，
     * 也可能带用户的支付凭据；抓取文件是明文落盘的。只记**长度与键名**，
     * 足以回答"payload 有多大、带哪些字段"，而不把支付数据抄进日志。
     */
    private fun recordPayOrder(json: JSONObject?) {
        if (json == null) return
        if (!RateLimit.firstN("bridge.payorder", 200)) return
        val payInfo = runCatching { json.optString("payInfo", "") }.getOrDefault("")
        val keys = runCatching {
            val o = JSONObject(payInfo)
            o.keys().asSequence().toList()
        }.getOrNull()
        val shape = when {
            payInfo.isEmpty() -> "empty"
            keys == null -> "not-json"
            else -> "keys=${keys.size}:${keys.take(6).joinToString(",")}"
        }
        // `pid` 来自 InputBase 的固定值（`vip`），记下来是为了让"这是支付链路"一眼可辨，
        // 而不是要读者去翻 smali。
        Capture.append("BRIDGE payorder submit len=${payInfo.length} $shape pid=vip")
    }

    /**
     * `decode_httpRequest`：页面借宿主的签名手代发请求。
     *
     * 记录**形状**而不是值（`DecodeRequestShape` 里有逐条离线断言）：
     * url 剥掉 query/fragment（那里几乎是凭证）、params 只记键名。
     */
    private fun recordDecodeRequest(json: JSONObject?) {
        if (json == null) return
        if (!RateLimit.firstN("bridge.decode", 200)) return
        val rawUrl = runCatching { json.optString("url", "") }.getOrDefault("")
        val shown = if (dev.xalor.kdkit.config.KdConfig.isOn("bridge_action_log_url", true)) {
            DecodeRequestShape.redactUrl(rawUrl)
        } else {
            // 关掉 URL 明细时仍要能分辨"是同一个接口还是不同接口"—— 只记 host 与 path 长度。
            DecodeRequestShape.redactUrl(rawUrl, maxPath = 0)
        }
        // 缺键时宿主填 -1（`if (v1 != -1)` 才发请求），所以这里必须保留"没传"这一态。
        val sd = if (runCatching { json.has("shouldDecode") }.getOrDefault(false)) {
            DecodeRequestShape.shouldDecode(runCatching { json.getInt("shouldDecode") }.getOrNull())
        } else {
            DecodeRequestShape.shouldDecode(null)
        }
        val params = runCatching { json.optJSONObject("params") }.getOrNull()
        val keys = params?.let { o -> o.keys().asSequence().toList() }
        val rawLen = runCatching { json.optString("params", "").length }.getOrDefault(0)
        Capture.append(DecodeRequestShape.line(shown, sd, DecodeRequestShape.paramsShape(keys, rawLen)))
    }

    /** 诊断：本次进程观测到多少次下载请求。 */
    fun downloadCount(): Int = RateLimit.count("bridge.download")
}

/** 小包装，避免在每个调用点写 try/catch。 */
internal object XposedHelpersCall {
    fun staticString(cls: Class<*>, method: String): String? = try {
        de.robv.android.xposed.XposedHelpers.callStaticMethod(cls, method)?.toString()
    } catch (_: Throwable) {
        null
    }
}
