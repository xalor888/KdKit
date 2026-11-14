package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 重练/练习**额度检查**观测（默认关闭，热开关，只记录不拦截）。
 *
 * ### 为什么这个点是"用户真正会撞到的限制"
 *
 * 之前找 VIP 相关入口时连着踩了三次空：`app_kdzy_userinfo_vip_text` 和 `t.c()/t.d()`
 * 只读**偏好开关**（控制标签显不显示），`vipPrivilege` 只是个营销弹窗。它们都不影响放行。
 *
 * 真正的额度判定在 `com.kuaiduizuoye.scan.web.VipLimitViewModel`：
 *
 * ```smali
 * :1437  invoke-virtual {p1, v1, v8, v0}, L…/VipLimitViewModel;->b(Ljava/lang/String;ILkotlin/jvm/functions/Function2;)V
 * :1557  同上（另一个入口）
 *        fh/g.smali:1898  （H5 侧同名调用）
 * ```
 *
 * 形参是 `(产品名, 已用次数, 回调)`：
 *  * 产品名目前只见到 `examRHW`（试卷重练）；
 *  * 回调是 `Function2<Boolean, Integer, Unit>` —— **第一个参数是"允许吗"**。
 *
 * 也就是说：钩住它就能看到"App 认为你还能不能重练、依据的次数是多少"。
 *
 * ### 它不做什么
 *
 * **只观测，不改结果。** 不改 Boolean、不改次数 —— 服务端仍按它自己的规则算额度。
 * 想"强行放行"不在本功能的范围内：那需要让回调收到 true，而服务端在真正下发试卷时
 * 会再校验一次，改了客户端只会得到"看起来能点、点了失败"的体验。
 *
 * ### 为什么值得观测
 *
 * 额度拒绝是**静默**的：页面只是按钮变灰或弹个会员页，看不出是"次数用完"还是"没权限"。
 * 记下 `allowed=false` 与当时的次数，就能回答"我这台机器到底被什么规则挡住了"。
 */
object VipLimitProbe : SwitchFeature(
    id = "vip_limit_probe",
    title = "重练额度检查观测",
    summary = "记录 App 对 examRHW 等产品的额度判定（允许吗、已用几次）；只观测不拦截",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val CLS = "com.kuaiduizuoye.scan.web.VipLimitViewModel"
    private const val MAX = 200

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "vip_limit_probe_result",
            title = "同时记录判定结果",
            summary = "钩回调的 invoke 拿 (Boolean, Integer)；关掉则只记\"被问了几次\"",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        var n = 0
        val fn2 = Xp.clazzOrNull("kotlin.jvm.functions.Function2")
        if (fn2 != null && Xp.hook(
                CLS, "b",
                String::class.java, Int::class.javaPrimitiveType, fn2,
                gate = id, onBefore = { p -> recordAsk(p) },
            )
        ) n++
        KdLog.i("VipLimitProbe installed ($n hooks)")
    }

    /** 记"谁在问、问的是哪个产品、已用几次"。 */
    private fun recordAsk(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!RateLimit.firstN("viplimit.ask", MAX)) return
        val product = p.args.getOrNull(0)?.toString() ?: "?"
        val used = p.args.getOrNull(1) as? Int ?: -1
        val cb = p.args.getOrNull(2)
        Capture.append("VIPLIMIT ask product=$product used=$used")
        // 回调是 Kotlin 的 Function2<Boolean,Integer,Unit>：钩它的 invoke 才能看到判定。
        // 但那个 invoke 是**所有** Function2 共享的实现类，按类钩会命中全 App 的 lambda
        // ⇒ 只在拿到具体实例时按实例类名钩，且只钩一次。
        if (cb != null && dev.xalor.kdkit.config.KdConfig.isOn("vip_limit_probe_result", true)) {
            hookResultOnce(cb)
        }
    }

    private val hookedResultClasses = java.util.Collections.synchronizedSet(mutableSetOf<String>())

    private fun hookResultOnce(cb: Any) {
        val name = cb.javaClass.name
        if (!hookedResultClasses.add(name)) return
        // 这是 lambda 的合成类（如 `...PaperMainView$e`），钩它的 `invoke`。
        //
        // **不能**按 `(Boolean, Int)` 精确匹配：该 lambda 实现的是
        // `kotlin.jvm.functions.Function2`，其 `invoke` 被**擦除**成
        // `(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;`。
        // 旧写法因此 `findAndHookMethod` 必然失败，异常被 `Xp.hook` 吞成 false，
        // 症状是"有 VIPLIMIT ask、永远没有 VIPLIMIT result"（2026-11-01 审查 P0-3）。
        //
        // 用 `hookAllBefore` 钩**全部** `invoke` 重载，运行时再按类型取 —— 擦除与否都能中。
        val n = Xp.hookAllBefore(name, "invoke", Xp.classLoader, gate = id) { p ->
            val allowed = p.args.getOrNull(0) as? Boolean ?: return@hookAllBefore
            val left = p.args.getOrNull(1) as? Int ?: -1
            if (RateLimit.firstN("viplimit.result", MAX)) {
                Capture.append("VIPLIMIT result allowed=$allowed remaining=$left")
            }
        }
        if (n == 0) {
            // 钩不上必须点名，而不是让"没有 result"看起来像"没发生过判定"。
            KdLog.w("VipLimitProbe: $name#invoke 一条也没钩上 —— VIPLIMIT result 将不可见")
        }
    }

    /** 诊断：本次进程里被问过多少次额度。 */
    fun askCount(): Int = RateLimit.count("viplimit.ask")
}
