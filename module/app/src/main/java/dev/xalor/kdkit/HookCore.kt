package dev.xalor.kdkit

import android.content.Context
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdConfigBridge
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.GatePolicy
import dev.xalor.kdkit.util.HookAudit
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp
import java.util.concurrent.atomic.AtomicBoolean

/** Runs inside the hooked 快对 process. */
object HookCore {
    private val started = AtomicBoolean(false)

    fun start(hostClassLoader: ClassLoader, ctx: Context?, processName: String?) {
        if (!started.compareAndSet(false, true)) return
        Xp.classLoader = hostClassLoader

        // 顺序有意为之：
        // ① 版本守卫先写一行 —— 之后所有证据都挂在"哪个宿主版本"上；
        // ② 配置通道再装 —— 后面每个功能读开关都依赖它；
        // ③ 抓取文件头一行，把"这个进程从哪开始"标出来（轮转后仍可分段）；
        // ④ 开关热读 TTL 复位，保证读到的是当前发布文件而不是上一次进程的缓存。
        HostVersion.read(ctx)
        // ③ 之前必须先灌「没配置时的缺省值」：热开关的 gate 在回调里问 GatePolicy，
        //   而它依赖 FeatureRegistry 的 defaultOn。漏了这一步就会退回"常量 true"的旧行为。
        GatePolicy.install(FeatureRegistry.all.associate { it.id to it.defaultOn })
        // 注：2026-11-02 曾在这里补过一段 `capture_max_mb` 的读取，**加错了** ——
        // 下面 `CaptureSettings.apply()` 早就在干这件事，而且位置在 `installHostReader()` 之后。
        // 我那段在它之前，`hostReader` 还是 null，读出来永远是空 ⇒ 既多余又静默无效。
        // 一条通道只能有一个所有者；这里保留 CaptureSettings，删掉重复实现。
        KdConfigBridge.installHostReader()
        KdConfig.invalidate()
        // 把 capture_max_mb / capture_max_line_kb / log_level 应用到运行期
        // （此前这两个键只有字段没人填，属于"代码读、实际不生效"的悬空项）
        KdLog.i("CaptureSettings: " + dev.xalor.kdkit.config.CaptureSettings.apply())
        Capture.mark("HookCore start process=${processName ?: "?"}")
        KdLog.i("HookCore start: process=$processName classLoader=$hostClassLoader")

        for (f in FeatureRegistry.all) {
            try {
                f.enable()
            } catch (t: Throwable) {
                KdLog.e("enable failed: ${f.id}", t)
            }
        }

        // 装机自检：开启但没装上的功能必须点名（否则只看到 "ready"，实际少了一半）
        val expected = FeatureRegistry.all.filter { it.shouldRun() || it.hot }
        val notInstalled = expected.filter { !it.isInstalled }
        if (notInstalled.isNotEmpty()) {
            KdLog.w(
                "HookCore: ${notInstalled.size}/${expected.size} enabled features NOT installed: " +
                    notInstalled.joinToString(",") { it.id },
            )
        }
        // 热功能挂了 0 条钩子 = 这个开关永远不会起作用，同样必须点名
        val hotButHookless = expected.filter { it.hot && it.isInstalled }
            .filter { (HookAudit.perFeature()[it.id]?.first ?: 0) == 0 }
            // 纯注册型功能（只往 WebInjector 注册脚本）本来就没有自己的钩子
            .filter { it.id !in NO_HOOK_BY_DESIGN }
        if (hotButHookless.isNotEmpty()) {
            KdLog.w("HookCore: hot features with no hooks: " + hotButHookless.joinToString(",") { it.id })
        }

        // WebView plumbing is shared: scripts are registered by features above and injected by a
        // single set of WebView hooks.
        val n = dev.xalor.kdkit.features.web.WebInjector.install()
        KdLog.i("WebInjector installed ($n hooks)")

        // 一行「热开关的实际生效数」。
        //
        // 为什么必须有这一行：`feature on: <id>` 只表示**钩子装上了**（热功能恒装），
        // 不表示**开关是开的** —— `kit/scripts/feature_matrix.py` 的「当前」列正是读它，
        // 于是 24 个 defaultOn=false 的 hot 功能全被显示成 ON，看着像全开。
        // 这一行直接给可断言的数字：effective-on 应该 ≈ 默认开的 + prefs 里显式开的。
        run {
            val hot = FeatureRegistry.all.filter { it.hot }
            val on = hot.filter { KdConfig.isOn(it.id, GatePolicy.defaultFor(it.id)) }
            val offIds = hot.filterNot { KdConfig.isOn(it.id, GatePolicy.defaultFor(it.id)) }.map { it.id }
            KdLog.i("HookCore gates: hot=${hot.size} effective-on=${on.size} effective-off=${hot.size - on.size}")
            KdLog.d("HookCore gates off: ${offIds.joinToString(",")}")
            Capture.mark("HookCore gates hot=${hot.size} on=${on.size} off=${hot.size - on.size}")
        }

        // 一行结论：功能数 + 钩子台账（少挂了几条在这里直接可读，不必翻几千行日志）。
        // 注意保留**旧格式** `HookCore ready (N features)` —— kit/scripts/module_report.py 用
        // `HookCore ready \((\d+) features\)` 正则取功能数，改掉它会让报告静默变成 0 项。
        KdLog.i("HookCore ready (${FeatureRegistry.all.size} features)")
        val line = HookAudit.summaryLine(FeatureRegistry.all.size, expected.size)
        KdLog.i("HookCore audit: $line")
        Capture.mark("HookCore audit: $line")
    }

    /** 这些功能靠 WebInjector 注入脚本工作，自己没有钩子，"0 hooks" 是正确状态。 */
    private val NO_HOOK_BY_DESIGN = setOf("page_js", "pk_assist", "h5_debug", "web_request_log")

    /** 诊断页用：本进程的安装快照。 */
    fun snapshot(): List<Triple<String, Boolean, Pair<Int, Int>>> =
        FeatureRegistry.all.map { f ->
            Triple(f.id, f.isInstalled, HookAudit.perFeature()[f.id] ?: (0 to 0))
        }
}
