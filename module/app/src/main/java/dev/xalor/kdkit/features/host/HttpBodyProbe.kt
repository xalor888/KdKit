package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.TextHeuristic
import dev.xalor.kdkit.util.Xp

/**
 * HTTP 请求体 / 响应体观测（默认关闭，热开关，只记录不改行为）。
 *
 * ### 为什么需要它（这是观测面里最后一个洞）
 *
 * 已有观测点覆盖了 URL（`SIGN URL`）、待签参数（`SIGN params`）、请求头（`HDR`）、
 * 响应**明文**（`NET DECRYPT out`）—— 但**没有请求体**。`work/SIGNED_SURFACE.md`
 * 追加五到追加七把它记成了一条悬案：`/kdapi/popup/gradeupgrade` 用**与服务端完全一致的
 * sign + 同一套 29 个参数**重放，仍返回 `906003 时间校验失败`。
 *
 * 那里逐条推翻了三层假设（重放时间顺序、缺参数、POST body）。第三层之所以只能"弱推断"，
 * 原因就写在文件里 —— 抓取的记录类型统计是：
 *
 * ```
 * 41  NET DECRYPT out        ← 响应体有
 * 43  SIGN params / SIGN URL ← 参数与 URL 有
 *  0  （请求体）              ← 没有
 * ```
 *
 * 缺了请求体，就分不清"App 也没送 body"和"App 送了但我们没看见"。本功能补上这一格。
 *
 * ### 钩点与静态证据（每条都能在 smali 里复查）
 *
 * | 目标 | 静态证据 |
 * |---|---|
 * | `com.baidu.homework.common.net.core.HWRequest.getBody()[B` | `smali_classes5/ql/a.smali:1524` 直接 `invoke-virtual`；`getBody` 是 volley 交出请求体的唯一出口 |
 * | `com.baidu.homework.common.net.core.HWRequest.parseNetworkResponse(Lcom/android/volley/r;)` | `Net.smali:8364`、`ql/a.smali:2226` 两处直接调用 —— 宿主所有成功响应都从这里解析 |
 * | `ql.a.getBody()[B` | `ql.a` 直接 `extends Lcom/android/volley/d;`（**不在** `HWRequest` 继承链上）⇒ 必须单独钩，否则 Compose 侧请求体全丢 |
 * | `com.baidu.homework.common.net.model.v1.common.InputBase.getJsonBody()String` | 读字段 `__jsonBody`（`InputBase.smali:435`），是结构化 POST 的**加密前**载体 |
 *
 * `getBody` 在 4 个类里有调用点，但只有 `HWRequest` 与 `ql.a` 是宿主的请求类
 * （另两个是 volley 基类槽位）。
 *
 * ### 它不做什么
 *
 * 不改 body、不改响应、不重放、不落第二份文件。只 `Capture.append` 一行。
 *
 * ### 限制（写进文档，别当成已验证）
 *
 * * **真机是否真的出现 `REQBODY` / `RESPBODY` 行 —— 未验证**（本轮无设备）；
 * * 二进制 body（图片/文件上传）**只记长度**，除非 `TextHeuristic.decode` 判得出文本；
 *   判定是纯函数，有 JVM 单测（`TextHeuristicTest`）；
 * * body 含用户输入（姓名、作文正文）⇒ 默认只记前 [MAX] 字符，另有
 *   `http_body_probe_full` 让使用者显式选择全记；
 * * `parseNetworkResponse` 的 `p.args[0]` 是 volley `NetworkResponse`，字段是**单字母**
 *   （`a`=status、`b`=body、`c`=headers，见 `com/android/volley/r.smali`）。若宿主换 volley
 *   分支导致字段改名，读不到时本功能会记一行 `RESPBODY unreadable`（而不是安静少记）——
 *   但那种情况下 `RESPBODY` 确实为 0 而功能仍显示"已启用"，这是与 `NetErrorProbe`
 *   读 `ErrorCode` 同一类的脆弱点。
 */
object HttpBodyProbe : SwitchFeature(
    id = "http_body_probe",
    title = "HTTP 请求/响应体观测",
    summary = "记录宿主请求体与响应原始字节（截断），补上\"URL 之外还剩 body\"这一格；只观测不改行为",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    // 下面的类名全部写**字面量**（不用 const），因为 ④⑤⑥ 按字面量解析；
    // 集中成常量会让这三道门看不到目标 —— `RouteLog` 遇到过，见 PARADIGM §7.6.1。

    /** 单行上限。body 可能很长（作文、列表），落盘必须限长 —— PARADIGM §7.5。 */
    private const val MAX = 600

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "http_body_probe_response",
            title = "同时记录响应体",
            summary = "关掉则只记请求体（响应体通常比请求体大一个数量级）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
        KdOption(
            key = "http_body_probe_full",
            title = "不截断 body",
            summary = "默认只记前 $MAX 字符；打开后记全文（抓取文件显著变大，且含用户输入）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "http_body_probe_param_values",
            title = "记表单参数的值",
            summary = "关掉则只记参数名（值可能是手机号/学校名等个人输入；默认开，因为判断\"时间字段在哪\"要靠值）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
        KdOption(
            key = "http_body_probe_binary",
            title = "记录二进制 body 的长度",
            summary = "图片/文件上传只记字节数（不记内容）；关掉则完全跳过",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        var n = 0
        n += hookRequestBody()
        n += hookOtherRequestBody()
        n += hookJsonBody()
        n += hookVolleyParams()
        n += hookResponse()
        KdLog.i("HttpBodyProbe installed ($n hooks)")
    }

    /**
     * 请求体：`HWRequest.getBody()[B`。
     *
     * 钩 getter 而不是在构造器里拼 —— `getBody` 是 volley 真正取 body 交出去的**唯一**出口
     * （`ql/a.smali:1524` 直接调用），所以 `onAfter` 里读 `p.result` 拿到的就是**实际发出去的字节**，
     * 而不是"构造参数按想象拼起来应该是什么"。
     *
     * 两个类名/方法名都写**字面量**，不传变量：④⑤⑥ 三道门按字面量解析，
     * 传 `cls` 会让这条钩子对门禁**不可见**（`RouteLog` 里遇到过同一个坑，
     * `PARADIGM.md §7.6.1` 已写成规则）。
     */
    private fun hookRequestBody(): Int {
        if (Xp.clazzOrNull("com.baidu.homework.common.net.core.HWRequest") == null) {
            KdLog.w("HttpBodyProbe: HWRequest not found")
            return 0
        }
        return if (Xp.hook("com.baidu.homework.common.net.core.HWRequest", "getBody",
                gate = id, onAfter = { p -> onBody(p, "HWRequest") })
        ) 1 else 0
    }

    /** Compose 侧另一个 `d` 子类（`ql.a`）。它**不在** `HWRequest` 继承链上，必须单独钩。 */
    private fun hookOtherRequestBody(): Int =
        if (Xp.clazzOrNull("kl.a") == null) 0
        else if (Xp.hook("kl.a", "getBody",
                gate = id, onAfter = { p -> onBody(p, "kl.a") })
        ) 1 else 0

    /**
     * 结构化 POST 的**加密前**载体：`InputBase.getJsonBody()String`。
     *
     * 为什么还要这条：`getBody()` 返回的是**编码后**字节（可能已被 `yl.f.s` 整体加密），
     * 而 `__jsonBody` 是加密前的结构。两者都记，才能回答"时间字段是在明文里还是在密文里"。
     *
     * ### 覆盖范围的诚实说明（2026-10-25 实测）
     *
     * **这条钩子对绝大多数请求是空的。** `__jsonBody` 全 APK 只有两处 `iput-object`：
     *  * `InputBase.<init>` 写死 `"{}"`；
     *  * `JsonInput.<init>` 写真实值 —— 而 `new-instance JsonInput` 全 APK **只有 1 处**。
     *
     * 所以它只在极少数走 `JsonInput` 的路径上有内容。绝大多数请求的 body 在
     * `getParams()` 里（见下面的 `hookVolleyParams`）。保留这条是因为它便宜，
     * 且一旦命中就是**加密前明文**，价值很高 —— 但不要指望它普遍有输出。
     *
     * 同一个 `InputBase` 实例只记一次：一个请求可能被查多次，重复记会把抓取刷成噪音。
     */
    private fun hookJsonBody(): Int {
        if (Xp.clazzOrNull("com.baidu.homework.common.net.model.v1.common.InputBase") == null) return 0
        return if (Xp.hook("com.baidu.homework.common.net.model.v1.common.InputBase", "getJsonBody", gate = id, onAfter = { p ->
                val body = p.result as? String
                if (body.isNullOrEmpty()) return@hook
                val who = System.identityHashCode(p.thisObject)
                if (!RateLimit.firstN("httpbody.json.$who", 1)) return@hook
                Capture.append("REQBODY json ${describe(body)}")
            })
        ) 1 else 0
    }

    /**
     * **表单参数**：`com.android.volley.v.getParams()Map`。
     *
     * ### 为什么必须补这条（本轮发现 `getJsonBody` 覆盖不到）
     *
     * 补之前我以为 `getJsonBody()` 就能拿到请求体。查 `__jsonBody` 的写入点后否掉了：
     * 全 APK 只有**两处** `iput-object … __jsonBody`——
     * * `InputBase.<init>` 写死 `"{}"`；
     * * `JsonInput.<init>` 写真实值，而 `new-instance JsonInput` 全 APK **只有 1 处**。
     *
     * 也就是说绝大多数请求的 `__jsonBody` 恒为 `"{}"`，`getJsonBody` 钩子基本抓空。
     *
     * 真正的 body 在 `getParams()`：**316 个子类**重写它
     * （`Popwincontent$Input` 就是其中之一 —— 正是 `SIGNED_SURFACE.md` 里
     * `/kdapi/popup/gradeupgrade` 那条 `906003` 悬案对应的类）。
     *
     * 基类 `InputBase.getParams()` 是 **abstract**，钩不到；但 `volley.v.getParams()`
     * 是 public 父类方法，所有请求经虚分派都会走到这里覆盖的版本 ⇒ 钩它即可。
     */
    private fun hookVolleyParams(): Int =
        if (Xp.hook("com.android.volley.v", "getParams", gate = id,
                onAfter = { p -> onParams(p) })
        ) 1 else 0

    private fun onParams(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        @Suppress("UNCHECKED_CAST")
        val m = p.result as? Map<Any?, Any?> ?: return
        if (m.isEmpty()) return
        if (!RateLimit.firstN("httpbody.params", 400)) return
        // 只记参数名与值的摘要 —— 值是用户输入（手机号、学校名等），不该整段落盘。
        val who = p.thisObject?.javaClass?.simpleName ?: "?"
        val withValues = KdConfig.isOn("http_body_probe_param_values", true)
        val pairs = m.entries.take(24).joinToString("&") { (k, v) ->
            if (!withValues) "$k"
            else {
                val sval = v?.toString() ?: ""
                "$k=${if (sval.length <= 40) sval else sval.take(40) + "…"}"
            }
        }
        val more = if (m.size > 24) " …+${m.size - 24}" else ""
        Capture.append("REQBODY params $who n=${m.size} $pairs$more")
    }

    /**
     * 响应体：`HWRequest.parseNetworkResponse(NetworkResponse)`。
     *
     * 在 `onBefore` 里读 `args[0]`，因为该方法返回的是**解析后**的对象，原始字节在参数里。
     */
    private fun hookResponse(): Int {
        val respCls = Xp.clazzOrNull("com.android.volley.r") ?: return 0
        if (Xp.clazzOrNull("com.baidu.homework.common.net.core.HWRequest") == null) return 0
        return if (Xp.hook("com.baidu.homework.common.net.core.HWRequest", "parseNetworkResponse",
                respCls, gate = id,
                onBefore = { p -> onResponse(p) })
        ) 1 else 0
    }

    private fun onBody(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam, cls: String) {
        val body = p.result as? ByteArray ?: return
        if (body.isEmpty()) return
        if (!RateLimit.firstN("httpbody.req", 400)) return
        val who = cls.substringAfterLast('.')
        val text = TextHeuristic.decode(body)
        if (text == null) {
            if (KdConfig.isOn("http_body_probe_binary", true)) {
                Capture.append("REQBODY bin $who len=${body.size}")
            }
            return
        }
        Capture.append("REQBODY text $who ${describe(text)}")
    }

    private fun onResponse(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!KdConfig.isOn("http_body_probe_response", true)) return
        if (!RateLimit.firstN("httpbody.resp", 400)) return
        val resp = p.args.getOrNull(0) ?: return
        val bytes = readField(resp, "b") as? ByteArray
        val status = readField(resp, "a")
        if (bytes == null) {
            // 字段名换了 ⇒ 明确记一行"读不到"。安静少记会与"响应体为空"混成同一件事。
            Capture.append("RESPBODY unreadable fields=${fieldNames(resp)}")
            return
        }
        val text = TextHeuristic.decode(bytes)
        if (text == null) {
            if (KdConfig.isOn("http_body_probe_binary", true)) {
                Capture.append("RESPBODY bin status=$status len=${bytes.size}")
            }
            return
        }
        Capture.append("RESPBODY text status=$status ${describe(text)}")
    }

    private fun readField(obj: Any, name: String): Any? = runCatching {
        de.robv.android.xposed.XposedHelpers.getObjectField(obj, name)
    }.getOrNull()

    private fun fieldNames(obj: Any): String =
        runCatching { obj.javaClass.declaredFields.joinToString(",") { it.name } }.getOrElse { "?" }

    /** 截断 + 压平换行。抓取格式是"一行一条"，换行会把一条记录撑成两条（PARADIGM §7.5）。 */
    private fun describe(s: String): String {
        val flat = s.replace('\n', '⏎').replace('\r', ' ')
        val full = KdConfig.isOn("http_body_probe_full", false)
        return if (full || flat.length <= MAX) "len=${s.length} $flat"
        else "len=${s.length} ${flat.take(MAX)}…"
    }
}
