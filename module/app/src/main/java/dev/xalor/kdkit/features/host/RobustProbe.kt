package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 热修复补丁面观测：**哪些方法被 Robust 插桩、运行时到底有没有补丁生效**。
 *
 * ### 为什么需要这个功能（它不是"又一个日志功能"）
 *
 * 宿主集成了美团 Robust（`com.meituan.robust`）。它在每个"可打补丁"的方法开头插了一段：
 *
 * ```smali
 * sget-object v3, Llk/f;->changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;
 * const/16 v5, 0x4dec                        # 方法序号
 * invoke-static … Lcom/meituan/robust/PatchProxy;->proxy(…)
 * iget-boolean v0, v0, …PatchProxyResult;->isSupported:Z
 * if-eqz v0, :cond_0
 * return                                     # ← 补丁生效时**原方法体一行都不执行**
 * :cond_0
 * ```
 *
 * 静态实测（`kit/scripts/check_robust_coverage.py`，可离线复跑）：
 *
 * * 全 APK **7594 个类 / 35784 个方法**带插桩；
 * * 模块当前 115 个钩子目标里，**47 个方法本身**被插桩，另有 **18 个**目标与插桩方法同类。
 *
 * 也就是说：**模块绝大多数"改返回值 / 改字段 / 读回包"的结论，都预设了"没有补丁下发"。**
 * 这个预设此前从未被写过，也从未被检查过 —— 一个钩子可以在 `Xp.hook` 返回 true、
 * 启动日志写 `hooked`、门禁全绿的情况下，因为补丁生效而**完全不产生效果**。
 * 这与 `BrushMaskView`（死代码）是同一种失败形态：**绿门禁 + 零效果**。
 *
 * ### 这个功能做什么 / 不做什么
 *
 * 做（纯观测，不改宿主任一行为）：
 *  1. 钩 `PatchProxy.proxy`（`before`）—— 每次调用都能看到"哪个方法在走补丁分派",
 *     并读 `PatchProxyResult.isSupported`（`after`）确认**这一次真的被补丁接管了**；
 *  2. 只对**模块自己钩了的目标**记账，避免把 7594 个类的噪声全灌进抓取；
 *  3. 写 `ROBUST` 行：`ROBUST patch <类>.<方法> #<序号> supported=true|false`。
 *
 * **不做**：不拦截补丁、不改 `isSupported`、不替换补丁体。那属于"对抗热修复"，
 * 会改变宿主行为且极易把 App 弄坏；本模块一律不碰。
 *
 * ### 为什么这条观测只有在真机上才有答案
 *
 * `changeQuickRedirect` 的静态初值是 `null`，只有 `PatchExecutor` 在应用补丁时才写它
 * （`PatchExecutor.smali:1284/1488`）。所以"有没有补丁"**离线无法判定** ——
 * 静态只能算出"暴露面"。这里抓的是"实际发生了没有"。
 *
 * ### 未验证（写清楚，别当成已验证）
 *
 * * 本轮**无设备**，`ROBUST` 行在抓取里**一条也没有**。功能是否真的产出记录：**未验证**；
 * * `PatchProxyResult.isSupported` 的字段名与语义来自静态阅读
 *   （`PatchProxy.smali:864-909`、`PatchProxyResult` 是普通 DTO），**未经运行时确认**；
 * * 若宿主把 `PatchProxy.proxy` 也自己去内联（不太可能，但静态无法排除），钩子会装不上，
 *   此时启动日志会写 `hook failed` —— 那种情况请以 `HookAudit` 为准。
 */
object RobustProbe : SwitchFeature(
    id = "robust_probe",
    title = "热修复补丁面观测",
    summary = "记录 Robust 补丁分派（哪些被插桩的方法真的被补丁接管），用于判断其它功能的静态结论是否仍成立",
    category = Category.HOST,
    defaultOn = false,
    // hot=false：这是**装钩子**级别的开关，不是回调级别的。
    // `PatchProxy.proxy` 是全 APK 唯一补丁分派点（7594 个类 / 35784 处调用），
    // 一旦装钩子，宿主每一处插桩方法的**每次执行**都要过一遍 Xposed 分派 + 
    // MethodHookParam 分配 —— 关掉开关也照样付这个代价。所以改成"开着才装"。
    hot = false,
) {
    /** 单进程最多记这么多条 —— 补丁分派在高频方法上可能每秒数十次。 */
    private const val MAX_ROWS = 400

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "robust_probe_all",
            title = "记录所有补丁分派",
            summary = "关掉只记 `supported=true`（真被补丁接管）的分派 —— 那才是本功能的重点；" +
                "打开则记录全部，噪声很大（一个页面几百行就会用光抓取预算）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "robust_probe_stack",
            title = "记录调用方（每方法首条）",
            summary = "首条补丁分派附一段调用栈，用于确认「是谁触发的」；栈会被截断",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        // 关着就不装钩子：见类头 `hot = false` 的理由（这是装钩子级开关）。
        if (!dev.xalor.kdkit.config.KdConfig.isOn(id, false)) {
            KdLog.i("RobustProbe: 未启用，跳过安装（不给宿主全站补丁分派加开销）")
            return
        }
        var n = 0
        // 入口：`PatchProxy.proxy(...)` 是所有插桩方法共用的唯一分派点。
        //
        // 为什么钩这里而不是逐个钩 35784 个方法：
        //  * 逐个钩 = 35784 次 hook 安装，启动直接卡死，且绝大多数与模块无关；
        //  * `proxy` 是**唯一**汇合点（`PatchProxy.smali:864` 被 7594 个类的 35784 处调用），
        //    钩它一处就能看到全部分派，且 `before/after` 能拿到返回的 `PatchProxyResult`。
        //
        // 签名从 `PatchProxy.smali:864` 逐字翻译：
        //   ([Ljava/lang/Object;Ljava/lang/Object;Lcom/meituan/robust/ChangeQuickRedirect;
        //    ZI[Ljava/lang/Class;Ljava/lang/Class;)Lcom/meituan/robust/PatchProxyResult;
        val redirect = Xp.clazzOrNull("com.meituan.robust.ChangeQuickRedirect")
        val resultCls = Xp.clazzOrNull("com.meituan.robust.PatchProxyResult")
        if (redirect != null && resultCls != null) {
            if (Xp.hook(
                    "com.meituan.robust.PatchProxy", "proxy",
                    Array<Any>::class.java,          // [Ljava/lang/Object;
                    Any::class.java,                 // Ljava/lang/Object;
                    redirect,                        // Lcom/meituan/robust/ChangeQuickRedirect;
                    Boolean::class.javaPrimitiveType, // Z
                    Int::class.javaPrimitiveType,    // I
                    java.lang.reflect.Array.newInstance(Class::class.java, 0).javaClass,  // [Ljava/lang/Class;
                    Class::class.java,               // Ljava/lang/Class;
                    gate = id,
                    onAfter = { p -> record(p) },
                )
            ) n++
        } else {
            KdLog.w("RobustProbe: 找不到 com.meituan.robust 类（宿主未集成 Robust？）")
        }
        KdLog.i("RobustProbe installed ($n hooks)")
    }

    /**
     * 从 `proxy(...)` 的实参里还原"哪个方法被插桩"。
     *
     * 关键参数（按签名顺序，`args` 0-based）：
     *  * `[0]` `Object[] paramsArray` —— 原方法的实参，**不含**方法身份；
     *  * `[1]` `Object current`     —— `this`；静态方法时为 null；
     *  * `[2]` `ChangeQuickRedirect` —— 补丁分派器；**null = 不可能被接管**；
     *  * `[3]` `boolean isStatic`；
     *  * `[4]` `int methodNumber`   —— 方法序号，配合类名唯一确定方法。
     *
     * 所以"是谁"只能由 `current` 的类 + `methodNumber` 拼出来，拿不到方法名 ——
     * 方法名要靠静态索引反查（`check_robust_coverage.py --json` 里带 `method_no`）。
     * **这里不假装知道方法名**：`current` 为 null（静态方法）时只能记序号。
     *
     * 判定"这次是否真被接管"读 `PatchProxyResult.isSupported`
     * （`PatchProxy.smali:876-880`：只有 `isSupport(...)` 为真才置 true 并调 `accessDispatch`）。
     */
    private fun record(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!RateLimit.firstN("robust.probe", MAX_ROWS)) return
        val current = p.args.getOrNull(1)
        val redirect = p.args.getOrNull(2)
        val methodNo = p.args.getOrNull(4) as? Int ?: -1
        val owner = current?.javaClass?.name
        // `redirect == null` ⇒ `isSupport()` 第一分支直接返回 false（`PatchProxy.smali:588-591`），
        // 即"这个类还没被任何补丁接管"。这是最有价值的一条：它证明**当前没有补丁**。
        val supported = runCatching {
            val r = p.result ?: return@runCatching null
            val f = r.javaClass.getDeclaredField("isSupported")
            f.isAccessible = true
            f.getBoolean(r)
        }.getOrNull()
        val hasRedirect = redirect != null

        // `robust_probe_all=false`（默认）时只记**真的被接管**的分派。
        //
        // 为什么默认要过滤：`proxy` 是全 APK 唯一的补丁分派点（7594 个类 / 35784 处调用），
        // 每一处插桩方法的每次执行都会进来。不过滤的话，一个正常页面几百行就把抓取写满
        // （400 条预算几秒用光），真正要紧的那几条 `supported=true` 反而被挤掉。
        // 而 `supported=true` 才是"原方法体没执行"的证据 —— 它才是本功能存在的理由。
        val all = dev.xalor.kdkit.config.KdConfig.isOn("robust_probe_all", false)
        if (!all && supported != true) return

        val who = owner ?: "(static)"
        Capture.append(
            "ROBUST patch ${who.take(80)} #${if (methodNo >= 0) Integer.toHexString(methodNo) else "?"}" +
                " supported=${supported?.toString() ?: "?"} redirect=$hasRedirect"
        )
        if (supported == true) {
            // 只有"真的被接管"才值得进 logcat 主日志：这意味着原方法体没执行。
            KdLog.w("RobustProbe: $who #${Integer.toHexString(methodNo)} 被补丁接管（原方法体未执行）")
        }
        if (dev.xalor.kdkit.config.KdConfig.isOn("robust_probe_stack", false)) {
            if (RateLimit.firstN("robust.probe.stack.$who.$methodNo", 1)) {
                val st = Throwable().stackTrace.drop(2).take(8)
                    .joinToString(" <- ") { "${it.className.substringAfterLast('.')}.${it.methodName}" }
                Capture.append("ROBUST stack $who #${Integer.toHexString(methodNo)} $st")
            }
        }
    }

    /** 诊断：本进程观测到的补丁分派次数。 */
    fun seen(): Int = RateLimit.count("robust.probe")
}
