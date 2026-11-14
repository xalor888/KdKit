package dev.xalor.kdkit

import android.content.Context
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog

/**
 * 宿主版本守卫 —— 让"模块跑在哪个版本的快对里"这件事在日志与证据里可断言。
 *
 * 为什么需要：整套钩子都建立在 **7.10.2 (1860)** 的混淆名之上（`dj.a` / `di.a` / `vm.g` …；
 * 7.10.0 是同一套名字（`module/MIGRATION-7102.md`），7.9.0 见 `module/MIGRATION-710.md`，
 * 7.7.2 更旧的见 `module/MIGRATION-790.md`）。**6.21.11 (1865) 是另一套映射**：
 * `di.a` 在那一版里指的是**另一个类**（有 `d` 但没有 `d(I)`），所以那一版靠 `HostMap` 翻译，
 * 不是靠"同名"。—— 这一点与 7.10.0/7.9.0 的"只差常量"不是同一类兼容。
 * App 一旦自动更新，这些名字会变，表现是"功能静默失效"，而不是崩溃 ——
 * 最难查的那种故障。所以启动时把版本号写进日志第一条与抓取文件头部：
 *
 *     KdKit: host com.kuaiduizuoye.scan 7.10.2 (1860) sdk=36
 *     === KdKit vX host=7.10.2/1860
 *
 * 之后任何一轮证据都能回答"这轮结论属于哪个版本"；`kit/scripts/evidence_pack.py` 的
 * 版本守卫（`--expect-version`）也是按这行对齐的。
 */
object HostVersion {

    /** 已知适配基线；与设备实测不一致时只警告，不阻止运行（便于灰度新版本）。 */
    const val BASELINE_VERSION_NAME = "7.10.2"
    const val BASELINE_VERSION_CODE = 1860L

    /**
     * 与主基线**逐条同形**的旧宿主。
     *
     * 7.10.2 相对 7.10.0 是 4 天内的补丁版：类集合只差 1 个（`AiVipPageFragment$c`，
     * 0 删除）、126 个钩子目标全部同名（`check_hook_targets.py` 126/126）、
     * 99 条签名 0 处变化（`check_hook_signatures.py`）、钩子方法体逐条只有 `const`
     * 平移（`kit/scripts/method_diff.py`：IDENTICAL 471 / CONST-SHIFT 125 / CHANGED 0）、
     * 接口面与桥面 0 增 0 减（`kit/scripts/version_diff.py`）。
     * ⇒ 同一个模块可同时服务三版。见 `module/MIGRATION-7102.md` §兼容性。
     *
     * 注意：7.10.0 的旧文档把 `const/16 vX, 0x….` 叫"资源 ID 常量"，实测那是
     * **Robust `PatchProxy` 的方法索引**（紧跟 `invoke-static … PatchProxy->proxy` 的 I 参数），
     * 因此它的平移量随"新插桩方法数"变化，不是资源 ID 的变化。
     */
    private val COMPATIBLE_VERSIONS = setOf(
        "7.10.0/1850",
        "7.9.0/1840",
        // 6.21.11 / 1865 —— **内测构建**（versionCode 比 1860 大，但版本号更旧，是另一个发布线）。
        //
        // 它与上面两版**不同类**：7.10.0 / 7.9.0 是"同一套混淆名、只差常量"，
        // 而 1865 的 R8 映射整个重排了 —— `di.a` 在这版里是**另一个类**（有 `d` 但没有 `d(I)`），
        // 于是旧钩子在这里不是"找不到类"而是"钩到错的方法"，比 MISSING 更难发现。
        // 类名的翻译由 `HostMap` 承担（表本体在 `HostMap.RENAMES`，表的格式被
        // `kit/scripts/hook_vocab.py::host_map()` 解析），钩子安装处由 `Xp` 依次试候选名。
        // 证据与逐条依据：广告/签名观测见 `work/compat1865/ADS.md`，宿主角见
        // `work/compat1865/HOST.md`。
        "6.21.11/1865",
    )

    @Volatile
    var versionName: String = "?"
        private set

    @Volatile
    var versionCode: Long = -1
        private set

    @Volatile
    var matchesBaseline: Boolean = false
        private set

    /** 主基线或已验过的兼容版本 ⇒ 钩子名可以对齐（判定只在这里做，日志/抓取/报告都读它）。 */
    fun isSupported(name: String, code: Long): Boolean =
        (name == BASELINE_VERSION_NAME && code == BASELINE_VERSION_CODE) ||
            COMPATIBLE_VERSIONS.contains("$name/$code")

    /** 在宿主进程里读一次包信息（[ctx] 为空时用 ActivityThread 兜底）。 */
    fun read(ctx: Context?): String {
        val context = ctx ?: currentApplication()
        if (context == null) return readLater()
        return try {
            val pm = context.packageManager
            val info = pm.getPackageInfo(context.packageName, 0)
            versionName = info.versionName ?: "?"
            @Suppress("DEPRECATION")
            versionCode = if (android.os.Build.VERSION.SDK_INT >= 28) info.longVersionCode
                          else info.versionCode.toLong()
            matchesBaseline = isSupported(versionName, versionCode)
            val sdk = android.os.Build.VERSION.SDK_INT
            val line = "${context.packageName} $versionName ($versionCode) sdk=$sdk"
            KdLog.i("host $line")
            Capture.mark("KdKit host=$versionName/$versionCode sdk=$sdk baseline=$matchesBaseline")
            if (!matchesBaseline) {
                KdLog.w(
                    "HostVersion: version drift — hooks were built against " +
                        "$BASELINE_VERSION_NAME/$BASELINE_VERSION_CODE; obfuscated names may have moved",
                )
            }
            line
        } catch (t: Throwable) {
            KdLog.w("HostVersion: package info failed: $t")
            "unknown"
        }
    }

    /**
     * `handleLoadPackage` 早于 `Application` 创建，这一刻 `ActivityThread.currentApplication()` 常为 null。
     * 旧实现就此放弃（抓取里于是永远没有版本行）。改为后台最多轮询 3 s 再读一次。
     */
    private fun readLater(): String {
        KdLog.w("HostVersion: no context yet, retrying on a background thread")
        Thread({
            var i = 0
            while (i++ < 30) {
                val c = currentApplication()
                if (c != null) {
                    read(c)
                    return@Thread
                }
                try {
                    Thread.sleep(100)
                } catch (_: InterruptedException) {
                    return@Thread
                }
            }
            KdLog.w("HostVersion: still no context after 3 s; version guard disabled for this process")
        }, "KdKit-hostversion").apply { isDaemon = true }.start()
        return "unknown"
    }

    private fun currentApplication(): Context? = try {
        Class.forName("android.app.ActivityThread")
            .getMethod("currentApplication").invoke(null) as? Context
    } catch (_: Throwable) {
        null
    }
}
