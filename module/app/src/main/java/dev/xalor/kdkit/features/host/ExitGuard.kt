package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedBridge
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.HookAudit
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit

/**
 * 退出守卫：DProtect（libdpsdk.so）检测到注入 / 调试器时不会自己 `kill`，
 * 而是**在一条后台线程上调用 `java.lang.System.exit(0)`**（ART 打印
 * `aiduizuoye.scan: System.exit called, status: 0` + `VM exiting with result code 0`），
 * 于是进程"干净地"消失，看起来像正常退出。
 *
 * 该功能在进程内把这些退出调用拦下来并记录调用栈，进程因此不会被自杀，
 * Frida / 调试器得以继续附加，kit/hooks 的动态分析链路才能用。
 *
 * ### 2026-10-25：新增"只记录不拦截"档
 *
 * 无脑拦截所有 `exit/halt/killProcess` 有一个副作用：**宿主自己**的正常退出（用户的
 * "退出登录并重启"、系统回收、热修后的重启）也会被挡住，表现是"点了退出没反应"。
 * 所以给出 `exit_guard_block`：
 *
 *  * 开（默认）= 与旧行为一致（分析场景，进程不自杀）；
 *  * 关 = 只记 `EXITCALL` 与调用栈，放行调用（诊断"到底谁在退"时用）。
 *
 * 不论哪一档，调用栈都写进抓取文件（`EXITCALL ...` 行 + 展开的 stack），
 * 因此"是谁调的 exit"变成可离线分析的数据，而不只是 logcat 里一闪而过的 1800 字符。
 */
object ExitGuard : SwitchFeature(
    id = "exit_guard",
    title = "退出守卫",
    summary = "拦截注入检测触发的 System.exit / Process.killProcess，进程不再自杀，便于动态分析（可切为只记录）",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val TAG = "ExitGuard"
    private const val MAX_STACK = 1800
    private const val MAX_CAPTURE_STACK = 4_000
    private val blocks = java.util.concurrent.atomic.AtomicInteger(0)

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "exit_guard_block",
            title = "真的拦下来",
            summary = "关掉则只记录退出调用与调用栈、放行（宿主自己的正常退出不再被挡）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    private val blocking: Boolean
        get() = KdConfig.isOn("exit_guard_block", true)

    override fun install() {
        var n = 0
        n += hookAll("java.lang.System", "exit")
        n += hookAll("java.lang.Runtime", "exit")
        n += hookAll("java.lang.Runtime", "halt")
        n += hookAll("android.os.Process", "killProcess")
        n += hookAll("android.os.Process", "killProcessQuiet")
        KdLog.i("ExitGuard installed ($n hooks, block=${blocking})")
    }

    private fun stack(): String = try {
        android.util.Log.getStackTraceString(Throwable())
    } catch (t: Throwable) {
        "<no stack: $t>"
    }

    // **这一族钩子必须进台账**（2026-11-03 修，代码审查 P1）。
    //
    // 旧实现自己 `XposedBridge.hookMethod`，不经过 `Xp` 薄封装，于是
    // `HookAudit` 一条都不记 ⇒ **装机自检对它是盲区**：
    // `hooks N ok / M failed` 里从来没有 exit_guard 的 5 条。
    // 表现是"这个功能少挂了"时，唯一能看出问题的地方是日志里那句 warn，
    // 而自检报告一切正常。
    //
    // `HookAudit` 的三种状态在这里各自对应：
    //   record(ok=true)      这个重载挂上了
    //   record(ok=false)     hookMethod 抛了异常
    //   recordSkipped(...)   类找不到 ⇒ 连"尝试"都没有（旧实现只打一行 warn）
    private fun hookAll(cls: String, method: String): Int {
        val c = try {
            Class.forName(cls, false, javaClass.classLoader)
        } catch (t: Throwable) {
            KdLog.w("$TAG: no $cls")
            HookAudit.recordSkipped(id, "$cls.$method (class not found)")
            return 0
        }
        var n = 0
        for (m in c.declaredMethods) {
            if (m.name != method) continue
            try {
                val target = "$cls.${m.name}(${m.parameterTypes.joinToString { it.simpleName }})"
                XposedBridge.hookMethod(m, object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        if (!KdConfig.isOn(id, true)) return
                        val k = blocks.incrementAndGet()
                        val where = "${cls.substringAfterLast('.')}.$method(${param.args.joinToString()})"
                        val block = blocking
                        // 保留旧日志格式（分析脚本按 "exit blocked #N" 计数），只补一个门控态。
                        if (block) {
                            KdLog.w("$TAG: exit blocked #$k $where")
                        } else {
                            KdLog.w("$TAG: exit observed (not blocked) #$k $where")
                        }
                        val s = stack()
                        if (RateLimit.firstN("exit.stack", 40)) {
                            KdLog.w("$TAG: caller stack #$k\n${s.take(MAX_STACK)}")
                            Capture.append("EXITCALL #$k $where blocked=$block")
                            Capture.append("EXITSTACK #$k " + s.take(MAX_CAPTURE_STACK).replace("\n", " ⏎ "))
                        } else if (RateLimit.firstN("exit.tally", 1)) {
                            Capture.append("EXITCALL #$k $where blocked=$block (stack suppressed)")
                        }
                        if (block) param.result = if (m.returnType == Void.TYPE) null else 0
                    }
                })
                HookAudit.record(id, target, true)
                n++
            } catch (t: Throwable) {
                HookAudit.record(id, "$cls.$method (hook threw ${t.javaClass.simpleName})", false)
            }
        }
        return n
    }

    /** 诊断用：本进程拦了多少次。 */
    fun blockedCount(): Int = blocks.get()
}
