package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.util.GatePolicy
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp
import java.util.concurrent.atomic.AtomicInteger

/**
 * 反调试检测绕过：宿主自带的 `AntiDebugThread`（`lk.f.b(Context)` 里 new 出来的线程，
 * 每 800 ms 轮询一次）会做两个判断，任一为真就 `System.exit(0)`：
 *
 *   1. `android.os.Debug.isDebuggerConnected()`
 *   2. `lk.f.d()` —— 读 `/proc/<pid>/status`，`TracerPid != 0` 就认为被调试/被注入
 *      （`lk/f.smali` 里可读；`lk.f.a()` 是指向它的 synthetic bridge）
 *
 * 另：`lk.f.b()` 入口还有一次 `lk.f.c(ctx)`（`ApplicationInfo.flags & FLAG_DEBUGGABLE`）。
 *
 * 该功能把这两个判断按"干净"返回，轮询线程因此永不触发退出——
 * Frida / 调试器可以正常附加，kit 的动态钩子（01/02/03）才有用武之地。
 * 只在宿主进程内改判定结果，不动 dex、不动 so。
 */
object AntiDetect : SwitchFeature(
    id = "anti_detect",
    title = "反调试检测绕过",
    summary = "让宿主自带的 AntiDebugThread（isDebuggerConnected / TracerPid 轮询）判定为干净，Frida 可附加",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private val hits = AtomicInteger(0)
    private val MAX_LOG = 6

    /** 非 boolean 只告警一次，避免每次调用都刷日志。 */
    private val nonBooleanWarned = java.util.concurrent.atomic.AtomicBoolean(false)

    override fun install() {
        var n = 0
        // **`gate = id` 必须传**（2026-11-04 修，代码审查 P2-13 / 目标里的"关不掉的功能"）。
        //
        // 这个功能是 `hot = true`，而 `BaseFeature.enable()` 的判据是
        // `if (!hot && !shouldRun()) return` —— **hot 直接绕过配置检查**，
        // 于是它无论如何都会装钩子。对"读侧"功能这没问题（回调里判 isOn 就行），
        // 但这个功能的四个钩子是**写侧**：它们把 `isDebuggerConnected()`、
        // `TracerPid`、`FLAG_DEBUGGABLE` 统统改成 false ——
        // **用户把 `antidetect` 关掉之后，它照样在骗 App。**
        //
        // 症状：UI 上开关是关的，App 侧行为完全不变。这一类缺陷不会报错，
        // 只会让人觉得"这个开关没用"。
        // 1) android.os.Debug.isDebuggerConnected() -> false （boot 类，用 boot ClassLoader）
        if (Xp.hook("android.os.Debug", "isDebuggerConnected", cl = null, gate = id, onBefore = {
            it.result = false
            note("Debug.isDebuggerConnected")
        })) n++

        // 2) lk.f.d() -> false：TracerPid 解析
        if (Xp.hook("dj.f", "d", cl = Xp.classLoader, gate = id, onBefore = {
            it.result = false
            note("lk.f.d (TracerPid)")
        })) n++

        // 3) 同义的 synthetic bridge（不同 ROM/构建可能走这条）
        //
        // **只在目标是 boolean 时**才置 false：`hookAll` 钩的是同名**全部重载**，
        // 一旦某个重载返回别的类型，写 false 会让调用方拿到一个 `Boolean.FALSE`
        // 而不是它期望的类型 —— 与"只改判定、不动其它逻辑"的自述冲突（审查 P2-11）。
        // 现状（7.9.0）：`dj.f.a()` 只有一个重载且返回 `Z`，见 check_hook_result_types.py。
        val bridge = Xp.hookAll("dj.f", "a", cl = Xp.classLoader, cb = object : XC_MethodHook() {
            override fun beforeHookedMethod(param: MethodHookParam) {
                // `hookAll` 没有 gate 形参 ⇒ 回调里自己判（与上面三个 hook 的语义一致）。
                if (!KdConfig.isOn(id, GatePolicy.defaultFor(id))) return
                if (!Xp.returnsBoolean(param)) {
                    if (nonBooleanWarned.compareAndSet(false, true)) {
                        KdLog.w("AntiDetect: dj.f.a 现在返回非 boolean ⇒ 跳过不改（否则会污染调用方）")
                    }
                    return
                }
                param.result = false
                note("lk.f.a bridge")
            }
        })

        // 4) 可调试标志判定（release 包恒为 false，留着防御性兜底）
        if (Xp.hook("dj.f", "c", android.content.Context::class.java, cl = Xp.classLoader, gate = id, onBefore = {
            it.result = false
            note("lk.f.c (FLAG_DEBUGGABLE)")
        })) n++

        KdLog.i("AntiDetect installed ($n direct hooks + $bridge bridge)")
    }

    /**
     * 看门狗每 800ms 轮询一次、每次都问同一批判定点 ⇒ 日志量是"时间 × 4"。
     * 旧实现每条都写一行（一天下来几十万行）。现在：前 6 条逐条记（证明四个判定点都被中和），
     * 之后每 5 分钟一条心跳（证明它**持续**在工作，而不是只在启动时生效过一次）。
     */
    private fun note(what: String) {
        val k = hits.incrementAndGet()
        if (k <= MAX_LOG) {
            KdLog.i("AntiDetect: neutralised $what (#$k)")
            return
        }
        if (RateLimit.every("antidetect.heartbeat", 300_000)) {
            KdLog.i("AntiDetect: heartbeat #$k (still neutralising $what)")
        }
    }
}
