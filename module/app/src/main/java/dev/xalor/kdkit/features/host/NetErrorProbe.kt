package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 网络失败原因观测（默认关闭，热开关，只记录不改行为）。
 *
 * ### 为什么钩这个
 *
 * `com.baidu.homework.common.net.NetError` 是宿主**所有网络失败的唯一载体**：
 * 全 APK **30 处** `invoke-direct … NetError-><init>`，而 `getErrorCode()` 被调用
 * **229 次** —— 说明上层到处都在读它做分支判断。
 *
 * `ErrorCode` 有 **110 个**常量，覆盖的正是我们会关心的一类东西：
 *
 * ```
 * ANTISPAM_SIGNERR          ← 签名不对（这类最想知道）
 * CLIENT_AUTH_EXCEPTION     ← 鉴权失败
 * CLIENT_NO_NETWORK_EXCEPTION / CLIENT_TIMEOUT_EXCEPTION
 * COMPOSITION_UPLOAD_NO_USER_DATA
 * DATA_EXCEED_MAX_LENGTH
 * …（共 110 个）
 * ```
 *
 * 钩住构造器 = 抓到**每一次**网络失败及其错误码。回答"这个请求为什么失败"
 * 从"猜"变成"读日志"。
 *
 * ### 它不做什么
 *
 * 不吞异常、不改 `ErrorCode`、不让失败变成功。只记录。
 *
 * ### 为什么钩构造器而不是 `getErrorCode()`
 *
 * 构造器是**创建点**（30 处），getter 是**读取点**（229 处）。
 * 钩 getter 会把同一个错误重复记 229/30 ≈ 7 次；钩构造器一错一条。
 *
 * ### 限制
 *
 * * `ErrorCode` **不是** Java enum（它 `extends Object`，靠 `static final` 常量 +
 *   `valueOf(int,String)` 构造）⇒ 拿不到 `name()`，只能调 `getErrorNo()`/`getErrorInfo()`；
 * * 真机能否看到这些行 —— **未验证**（无设备）。
 */
object NetErrorProbe : SwitchFeature(
    id = "net_error_probe",
    title = "网络失败原因观测",
    summary = "记录每次网络失败的错误码（ErrorCode，110 种）与消息；只观测不改行为",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val CLS = "com.baidu.homework.common.net.NetError"
    private const val EC = "com.baidu.homework.common.net.ErrorCode"
    private const val MAX = 500

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "net_error_probe_stack",
            title = "记录失败摘要",
            summary = "把 ErrorCode 的消息一并与错误号记下（否则只有号，要另查含义）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        var n = 0
        val ecCls = Xp.clazzOrNull(EC)
        if (ecCls != null && Xp.hookCtor(
                CLS, ecCls, String::class.java,
                gate = id, onAfter = { p -> onError(p) },
            )
        ) n++
        KdLog.i("NetErrorProbe installed ($n hooks)")
    }

    private fun onError(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!RateLimit.firstN("neterr", MAX)) return
        val ec = p.args.getOrNull(0)
        val msg = p.args.getOrNull(1) as? String
        val (no, info) = describe(ec)
        val detail = if (dev.xalor.kdkit.config.KdConfig.isOn("net_error_probe_stack", true)) {
            val m = msg?.take(160) ?: info?.take(160)
            if (m.isNullOrBlank()) "" else " | $m"
        } else ""
        Capture.append("NETERR no=$no${if (info != null) " code=$info" else ""}$detail")
    }

    /** `ErrorCode` 不是 enum：只能调 `getErrorNo()I` 与 `getErrorInfo()String`。 */
    private fun describe(ec: Any?): Pair<String, String?> {
        if (ec == null) return "?" to null
        val no = runCatching {
            ec.javaClass.getMethod("getErrorNo").invoke(ec)?.toString()
        }.getOrNull() ?: "?"
        val info = runCatching {
            ec.javaClass.getMethod("getErrorInfo").invoke(ec)?.toString()
        }.getOrNull()
        // `getErrorInfo()` 可能返回空串或常量名以外的东西；空就不写，避免 `code=`
        return no to info?.takeIf { it.isNotBlank() }
    }

    /** 诊断：本次进程记了多少条失败。 */
    fun errorCount(): Int = RateLimit.count("neterr")
}
