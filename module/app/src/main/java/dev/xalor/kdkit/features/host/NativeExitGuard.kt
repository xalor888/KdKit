package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog

/**
 * 原生退出守卫（**实验性 / 仅实验室**，默认关闭）。
 *
 * 背景（见 `work/dpsdk/FINDINGS.md` 与 `ROADMAP.md` R12）：宿主的原生反注入层在决定"自杀"时
 * **不走 libc** —— Frida 挂在 `exit/_exit/exit_group/abort` 上一条都不触发，`strace -f -i`
 * 只看到一个裸的 `exit_group(0)`（报出来的 IP 还落在不可执行的映射里），Java 侧的
 * `System.exit` 守卫（`exit_guard`）也拦不住。
 *
 * 用户态唯一还能否决它的地方是 **seccomp**：本功能加载 `libkdhide.so`，装一个
 * "只把 `exit_group`/`exit` 改成返回 EPERM、其余全部放行" 的 seccomp-bpf 过滤器。
 *
 * 注意：seccomp 过滤器**对该进程不可撤销**（装了就一直在），所以默认关闭；
 * 打开后该进程的正常退出也会被改写（例如宿主的自杀式重启），属于实验室手段。
 */
object NativeExitGuard : SwitchFeature(
    id = "native_exit_guard",
    title = "原生退出守卫（实验）",
    summary = "用 seccomp 否决 exit_group/exit 系统调用，测试宿主原生自杀路径是否被挡住（不可撤销，默认关闭）",
    category = Category.HOST,
    defaultOn = false,
) {
    override val options: List<KdOption> = listOf(
        KdOption(
            key = "native_exit_guard_control",
            title = "对照组：只拦 personality",
            summary = "装一个拦没人用的 syscall 的过滤器，用来区分\"App 在反应 seccomp 存在\"与\"App 真调了 exit\"",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        if (!loadNative()) {
            KdLog.w("NativeExitGuard: libkdhide.so 加载失败 —— 本功能不生效（这是显式失败，不是静默）")
            return
        }
        val control = KdConfig.isOn("native_exit_guard_control", false)
        val rc = try {
            if (control) nativeInstallControl() else nativeInstall()
        } catch (t: Throwable) {
            KdLog.e("NativeExitGuard: install threw", t)
            return
        }
        if (rc != 0) {
            // 负数是 -errno（见 kdhide.c：`return -(int) errno`）
            KdLog.w("NativeExitGuard: seccomp install failed rc=$rc (-1=EPERM -22=EINVAL -38=ENOSYS)")
            return
        }
        val installed = nativeIsInstalled()
        // 自证：装完立刻试一次 exit_group，被 EPERM 否决才算真的生效。
        // control 组只拦 personality，所以 exit 不会被拦 —— 这里如实报告"未拦"。
        val selfTest = if (control) -2 else try { nativeSelfTest() } catch (t: Throwable) { -3 }
        val blocked = try { nativeBlockedCount() } catch (t: Throwable) { -1L }
        KdLog.i(
            "NativeExitGuard: seccomp installed=$installed selfTest=$selfTest " +
                "(1=已拦住 0=没拦住 -1=未安装 -2=对照组 -3=调用失败) selfProofCount=$blocked",
        )
        // 落抓取要**等 Application 创建**：本功能跑在 `handleLoadPackage` 早期，
        // `ActivityThread.currentApplication()` 那一刻还是 null，`Capture.resolve()`
        // 返回 null ⇒ 行会挂在待写队列里；而这个功能一旦生效，宿主可能几秒内就被杀掉，
        // 等不到"路径可用再补写"。所以这里主动等：最多 5 s，拿到 context 就写并立刻刷盘。
        val line = "NEXIT installed=$installed control=$control selfTest=$selfTest selfProof=$blocked"
        Thread({
            var i = 0
            while (i++ < 50) {
                val app = runCatching {
                    Class.forName("android.app.ActivityThread")
                        .getMethod("currentApplication").invoke(null) as? android.content.Context
                }.getOrNull()
                if (app != null) {
                    Capture.append(line)
                    Capture.flush()
                    return@Thread
                }
                try {
                    Thread.sleep(100)
                } catch (_: InterruptedException) {
                    return@Thread
                }
            }
            KdLog.w("NativeExitGuard: 5 s 内没拿到 context，NEXIT 行只留在日志里")
        }, "KdKit-nexit-capture").apply { isDaemon = true }.start()
        if (!control && selfTest != 1) {
            KdLog.w("NativeExitGuard: 过滤器装上了但自证没拦住 exit_group —— 内核可能不支持，别把「没死」当成功")
        }
    }

    /**
     * 加载 `libkdhide.so`。
     *
     * 关键：本代码跑在**宿主**进程里，`System.loadLibrary` 按**宿主**的 native 库目录解析，
     * 而 `libkdhide.so` 只存在于**模块 APK** 的 `jniLibs/` ⇒ 旧实现必然 `UnsatisfiedLinkError`，
     * 又被 catch 成一行日志后 return（2026-11-01 审查 P1-6，静默不生效）。
     *
     * 兜底路线：从宿主 ClassLoader 的 DexPathList 里找到模块 APK，把 `lib/<abi>/libkdhide.so`
     * 解到宿主 cacheDir，再 `System.load(绝对路径)`。
     */
    private fun loadNative(): Boolean {
        try {
            System.loadLibrary("kdhide")
            KdLog.i("NativeExitGuard: loaded via loadLibrary")
            return true
        } catch (_: Throwable) {
            // 走兜底
        }
        return try {
            val apk = moduleApk() ?: run {
                KdLog.w("NativeExitGuard: 找不到模块 APK 路径（DexPathList 里没有 kdkit）")
                return false
            }
            val abi = android.os.Build.SUPPORTED_ABIS.firstOrNull { it.startsWith("arm64") }
                ?: android.os.Build.SUPPORTED_ABIS.firstOrNull()
                ?: "arm64-v8a"
            val entry = "lib/$abi/libkdhide.so"
            val cacheDir = currentApp()?.cacheDir ?: run {
                KdLog.w("NativeExitGuard: 拿不到 cacheDir")
                return false
            }
            val out = java.io.File(cacheDir, "libkdhide-$abi.so")
            if (!out.exists() || out.length() == 0L) {
                java.util.zip.ZipFile(apk).use { zip ->
                    val e = zip.getEntry(entry) ?: run {
                        KdLog.w("NativeExitGuard: 模块 APK 里没有 $entry")
                        return false
                    }
                    zip.getInputStream(e).use { input ->
                        out.outputStream().use { o -> input.copyTo(o) }
                    }
                }
            }
            System.load(out.absolutePath)
            KdLog.i("NativeExitGuard: loaded via extracted $entry (${out.length()} B)")
            true
        } catch (t: Throwable) {
            KdLog.e("NativeExitGuard: 兜底加载也失败", t)
            false
        }
    }

    /** 宿主 ClassLoader 的 DexPathList 里，名字含 `kdkit` 的那个 APK。 */
    private fun moduleApk(): String? = try {
        val cl = javaClass.classLoader ?: return null
        val pathList = cl.javaClass.getField("pathList").get(cl)
        val elements = pathList.javaClass.getField("dexElements").get(pathList) as? Array<*>
        elements?.asSequence()
            ?.mapNotNull { el ->
                runCatching { el!!.javaClass.getField("path").get(el) as? String }.getOrNull()
            }
            ?.firstOrNull { it.contains("kdkit") && it.endsWith(".apk") }
    } catch (t: Throwable) {
        KdLog.d("NativeExitGuard: moduleApk() failed: $t")
        null
    }

    private fun currentApp(): android.content.Context? = try {
        Class.forName("android.app.ActivityThread")
            .getMethod("currentApplication").invoke(null) as? android.content.Context
    } catch (_: Throwable) {
        null
    }

    private external fun nativeInstall(): Int
    private external fun nativeInstallControl(): Int
    private external fun nativeIsInstalled(): Boolean
    private external fun nativeBlockedCount(): Long
    private external fun nativeSelfTest(): Int

    /** 供诊断用：过滤器是否已生效。 */
    fun status(): String = try {
        "installed=${nativeIsInstalled()} blocked=${nativeBlockedCount()}"
    } catch (t: Throwable) {
        "unavailable: $t"
    }
}
