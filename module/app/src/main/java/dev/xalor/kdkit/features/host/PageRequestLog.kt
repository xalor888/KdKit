package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.PageRequestOrigin
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 页面代发请求的**来源归属**观测（默认关闭，热开关，只记录不改行为）。
 *
 * ### 为什么钩这一个方法就够
 *
 * 宿主把一批 H5 桥 action 做成"页面给 URL + params，宿主用**自己的签名器**发出去"。
 * 它们的共同出口是下面这个静态方法：
 *
 * ```smali
 * dr/f.smali:30
 *   .method public static a(Ldr/f$e;Ljava/lang/String;Ljava/util/Map;Ljava/lang/Class;ILorg/json/JSONObject;Lorg/json/JSONObject;)Lcom/android/volley/v;
 *     → b(Activity, dr.f$e, url, params, Class, int, …)      :92
 *     → Net.post(context, InputBase, SuccessListener, ErrorListener)   :92 段内
 * ```
 *
 * 静态实测 **4 个调用点 / 3 个宿主 action**（可复跑）：
 *
 * ```
 * $ grep -rn 'Ldr/f;->a(Ldr/f$e' work/apktool_out --include=*.smali
 *   EncryptDataRequestAction.smali:190            @FeAction("encryptDataRequest")
 *   CoreHttpRequestAction.smali:905, :960         core_httpRequest（get / post 两条分支）
 * ```
 *
 * 为什么不在每个 action 上各钩一次：那样**每加一个 action 就要改一次代码**，
 * 而漏掉的那个不会有任何门禁会红（`BridgeActionLog` 已经为 `decode_httpRequest` 单钩了一次，
 * 它的姊妹 `encryptDataRequest` 就一直没人观测）。钩汇聚点则是"漏不掉"的：
 * 只要宿主仍从 `dr.f.a` 发请求，就必然经过这里。
 *
 * ### 它回答的三件事
 *
 * 1. **谁在驱动**：`dr.f.a` 的首参是接口 `dr/f$e`，每个调用点传的都是本 action 的匿名内部类
 *    （`EncryptDataRequestAction$1` 等）。取 `thisObject` 的类名、剥掉末尾纯数字后缀，
 *    就得到 action 类名 —— 见 [PageRequestOrigin.actionOf]。
 * 2. **发到哪**：URL 只留 host + path（query 里常带凭证，见 `DecodeRequestShape.redactUrl`）。
 * 3. **带了什么形状**：`params` 只记键数与键名，不记值（明文落盘，值可能有 token / 手机号）。
 *
 * ### 它不做什么
 *
 * 不拦截、不修改、不重放。也不声称能知道**哪个 H5 页面**发起的 ——
 * `thisObject` 只到 action 层，运行时调用栈不在静态证据范围内。这一格标"未验证"。
 *
 * ### 静态依据（可复跑）
 *
 * ```
 * python3 kit/scripts/smali_usage.py --target dr.f:a
 *   → USED（3 处外部 invoke）
 * ```
 */
object PageRequestLog : SwitchFeature(
    id = "page_request_log",
    title = "页面代发请求来源观测",
    summary = "钩宿主唯一的“页面代发请求”出口 dr.f.a，记录是哪个 action 让宿主把请求打到哪（URL 剥 query、params 只记键名）；只观测不改行为",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    // 类名/方法名不再做成常量：`Xp.hook` 里直接写字面量，否则 ④⑤ 只看字面量会漏掉这条钩子。
    // （`dr.f.a` 的混淆名在升级后最可能失配 —— 启动日志会点名，`HookAudit` 记 failed。）

    /** 单进程最多记这么多条，避免长时间跑把抓取文件撑爆。 */
    private const val MAX = 500

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "page_request_log_url",
            title = "记录完整 URL",
            summary = "关掉则只记 host + 路径长度（URL 的 query 里可能带有时效签名或 token）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        // 参数类型必须逐个写对，否则 `findAndHookMethod` 静默失败（⑤ 会红，但先写对更省事）：
        //   dr.f.a(Ldr/f$e;Ljava/lang/String;Ljava/util/Map;Ljava/lang/Class;ILorg/json/JSONObject;Lorg/json/JSONObject;)
        val callback = Xp.clazzOrNull("ps.f\$e")
        if (callback == null) {
            KdLog.w("PageRequestLog: dr.f\$e 缺失，跳过（宿主换版？）")
            return
        }
        // 类名/方法名写成**字面量**，不用 `CLS` / `METH` 常量：④⑤ 两道门只按字面量解析，
        // 传 `const val` 会让这条钩子对门禁**完全不可见**（`PARADIGM.md §7.6.1`）。
        // 实测：用常量时 ④ 完全看不到 `dr.f.a`，只看到 `clazzOrNull` 里的 `dr.f$e`。
        val n = if (Xp.hook(
                "ps.f", "a",
                callback,                                  // dr.f$e  —— 网络回调
                String::class.java,                        // url
                java.util.Map::class.java,                 // params
                Class::class.java,                         // 响应类型
                Int::class.javaPrimitiveType,              // method（0/1）
                org.json.JSONObject::class.java,           // 请求头
                org.json.JSONObject::class.java,           // 额外参数
                gate = id,
                onBefore = { p -> record(p) },
            )
        ) 1 else 0
        KdLog.i("PageRequestLog installed ($n hooks)")
    }

    private fun record(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!RateLimit.firstN("pageRequest", MAX)) return

        // 首参是接口实例，实现类是发起方 action 的匿名内部类。
        // 注意：**不能**用 `p.args[0].javaClass.name` 直接当 action 名 —— 它带 `$1` 编号，
        // 编号随编译变动，写进抓取会让同一逻辑在不同版本间对不上。
        val arg0 = p.args.getOrNull(0)
        val from = PageRequestOrigin.actionOf(arg0?.javaClass?.name)

        val url = p.args.getOrNull(1) as? String ?: ""
        // 形参是 `Ljava/util/Map;`，Kotlin 侧用 `Map<*, *>` 读 `.keys` 即可
        // （java.util.Map 与 kotlin.collections.Map 在这个用途上等价，但后者在 Kotlin 里
        //  能直接映射出 `.keys`；写全名 java.util.Map 反而拿到不可用投影）。
        val raw = p.args.getOrNull(2) as? Map<*, *>
        val keys = raw?.keys?.mapNotNull { it?.toString() }

        val shownUrl = if (dev.xalor.kdkit.config.KdConfig.isOn("page_request_log_url", false)) {
            url.take(300)
        } else {
            PageRequestOrigin.redactUrl(url)
        }
        val shape = PageRequestOrigin.paramsShape(keys)
        // method 形参：0=GET / 1=POST（`dr.f.a` 的 p4）。
        // 传 `null` 表示"拿不到"，由 `line()` 统一写成 `?` —— 不在这里拼字符串。
        val method = p.args.getOrNull(4) as? Int

        Capture.append(PageRequestOrigin.line(from, shownUrl, shape, method))
    }
}
