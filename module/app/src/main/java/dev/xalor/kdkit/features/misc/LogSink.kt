package dev.xalor.kdkit.features.misc

import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.LogFilter
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 把 App 自己打的日志收一份 —— 2026-10-15 加（R581）。（**热开关**）
 *
 * 由来：`files/tdLogDir/` 下的 .xlog 是 App 自己的 4 天日志，但它是 **Mars 私有封装**
 * （R580：试过大端分帧与 zlib/zstd 直解，都不成）⇒ 移植解码器成本高。
 * 而 App 在 dex 里带着两行格式串（R537 读到）：
 *     `#nativeGetSign start, paramString=%s`
 *     `@nativeGetSign end, sign=%s, serverTimeParam=%s, signTimeParam=%s`
 * ⇒ **那就绕开格式，直接收那几行** —— hook `android.util.Log` 的四个静态方法即可。
 *
 * ### 2026-10-25：这条钩子是全模块**最热**的一条
 *
 * `android.util.Log.*` 是进程级静态方法，整个 App（含所有第三方 SDK）的每条日志都会进来。
 * 旧实现每次做 `tag.lowercase()`（分配）＋ 线性扫 8 个 tag ＋ 若干 `contains`，
 * 在高频日志下等于给主线程加了一层字符串 GC 压力。
 *
 * 现在：
 *  * tag 集合**预lowercase**，判定改为哈希集合 O(1)；
 *  * 消息侧的关键词预编译成小写前缀/子串常量，先按长度剪枝；
 *  * 每 tag 有独立预算（默认 2000 条/tag/进程），超了只累加丢弃计数；
 *  * 记录默认走共享 [Capture]，标签 `APPSIGN`，与其它观测同一个文件（一次 pull 收全）。
 */
object LogSink : SwitchFeature(
    id = "log_sink",
    title = "App 日志收录",
    summary = "把 App 自己打的、与签名/接口相关的日志行收进抓取文件（APPSIGN 行，绕开 xlog 私有格式）",
    category = Category.MISC,
    defaultOn = true,
    hot = true,
) {
    /** 只收关心的 tag（避免把整台设备的日志都吞进来）。 */
    private val TAGS = listOf(
        "nativeGetSign", "VectorLegacyBridge", "KDNative", "baseutil", "ZYBHttp",
        "kuaiduizuoye", "H5Bridge", "zyb",
    )

    /** 上限：每条最多这么长（超长截断，避免把文件写爆）。 */
    private const val MAX_LINE = 600
    private const val PER_TAG = 2_000

    /**
     * 排除自身输出用的 tag —— **直接引用 `KdLog.TAG`**，不写第二份字面量。
     * 写两份的后果：改一边忘记另一边，排除条件静默失效，抓取里又开始出现重复行。
     */
    private val SELF_TAG = dev.xalor.kdkit.util.KdLog.TAG

    private val dropped = java.util.concurrent.atomic.AtomicLong()

    override val options: List<KdOption> = listOf(
        // 模块级的基础设施设置也挂在这里：它们都属于"记录/观测"这一类，
        // 而门禁要求"每个被读的键都必须有 owner 认领"。
        KdOption(
            key = dev.xalor.kdkit.config.CaptureSettings.KEY_MAX_MB,
            title = "抓取文件上限 (MB)",
            summary = "0 = 不限制（长取证时宁写满磁盘也不丢证据）；默认 4",
            kind = KdOption.Kind.STRING,
            default = dev.xalor.kdkit.config.CaptureSettings.DEFAULT_MAX_MB.toString(),
        ),
        KdOption(
            key = dev.xalor.kdkit.config.CaptureSettings.KEY_MAX_LINE_KB,
            title = "单行上限 (KB)",
            summary = "超长桥 JSON 会被截断到这么长；0 = 不限制；默认 4",
            kind = KdOption.Kind.STRING,
            default = dev.xalor.kdkit.config.CaptureSettings.DEFAULT_MAX_LINE_KB.toString(),
        ),
        KdOption(
            key = dev.xalor.kdkit.config.CaptureSettings.KEY_LOG_LEVEL,
            title = "日志级别",
            summary = "0 静默 / 1 正常 / 2 详细（写 logcat 与 XposedBridge 的量）",
            kind = KdOption.Kind.STRING,
            default = dev.xalor.kdkit.config.CaptureSettings.DEFAULT_LOG_LEVEL.toString(),
        ),
        KdOption(
            key = "log_sink_per_tag",
            title = "每 tag 上限",
            summary = "每个 tag 每个进程最多记多少条，0 = 不限制（会长得很快）",
            kind = KdOption.Kind.STRING,
            default = PER_TAG.toString(),
        ),
    )

    override fun install() {
        var n = 0
        // 级别清单按宿主**实际用量**定（2026-10-25 数过 invoke-static 调用点）：
        //   v 236 / d 708 / i 309 / w 399 / e 800 / wtf 10
        // 原来只钩 d/i/w/e —— 漏掉 v（236 处，调试路径里常有关键线索）与 wtf（10 处，
        // 崩溃前的最后一条）。`println` 只有 16 处且不带级别，不值得加。
        for (method in listOf("v", "d", "i", "w", "e", "wtf")) {
            // 级别字符**在装钩子时就算好**：`m.uppercase()[0]` 原来在每一条日志上执行一次，
            // 每次都要 `uppercase()` 分配一个新 String。日志是高频路径，这条白拿。
            val levelChar = method[0].uppercaseChar()
            n += Xp.hookAll("android.util.Log", method, Xp.classLoader, object : XC_MethodHook() {
                override fun afterHookedMethod(param: MethodHookParam) {
                    if (!KdConfig.isOn(id, true)) return
                    val a = param.args ?: return
                    if (a.size < 2) return
                    val tag = a[0] as? String ?: return
                    val msg = a[1] as? String ?: return
                    if (!shouldCapture(tag, msg)) return
                    val cap = KdConfig.getString("log_sink_per_tag", PER_TAG.toString()).toIntOrNull() ?: PER_TAG
                    if (cap > 0 && !RateLimit.firstN("applog.$tag", cap)) {
                        dropped.incrementAndGet()
                        return
                    }
                    Capture.append("APPSIGN $levelChar/$tag: ${msg.take(MAX_LINE)}")
                }
            })
        }
        KdLog.i("LogSink ready (hooks=$n)")
    }

    /**
     * 这一条 App 日志该不该收录。
     *
     * **排除模块自己的日志**：`KdLog` 打到 logcat 的每一行都会回到这里，而同一个事件
     * 已经由 `SignObserver` 等用结构化前缀（`H5 n out` 等）记过一次 ⇒ 不排除就一行变两行。
     *
     * 实测证据（2026-10-25，`work/activity_inputs/` 五份抓取）：
     * ```
     * 19:21:36.742 APPSIGN I/VectorLegacyBridge: [KdKit] H5 n out: https://…
     * 19:21:36.743 H5 n out: https://…
     * ```
     * 全量：**3318 / 16807 = 19%** 的抓取行是这种重复。
     *
     * 抽成独立函数是为了**能被测到** —— 内联在 lambda 里时测试只能断言常量，
     * 把排除条件删掉测试也不会红（本轮验证过一次，确实不红）。
     */
    internal fun shouldCapture(tag: String, msg: String): Boolean {
        if (tag == SELF_TAG) return false
        return LogFilter.interesting(tag, msg, TAGS)
    }

    /** 因为预算被丢掉的条数（诊断：区分"没有日志"与"被限流"）。 */
    fun droppedCount(): Long = dropped.get()
}
