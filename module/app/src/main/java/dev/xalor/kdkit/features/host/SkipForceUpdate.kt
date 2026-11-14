package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XposedHelpers
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/**
 * 跳过强制更新弹窗（默认关闭，热开关）。
 *
 * ### 钩点是怎么定下来的（`module/NEW_TARGETS.md` §1）
 *
 * 线索文件 `HMSCheckUpdateWebAction` 其实是**华为 HMS JOS 的更新外壳**，钩它对 App 自己的
 * 强制升级弹窗无效。真正的闸门是：
 *
 * ```smali
 * ei/y.smali:2166  sget-object v1, CommonPreference;->FORCE_UPDATE
 *        :2170  invoke-static {v1}, PreferenceUtils;->getBoolean(...)Z
 *        :2181  if-eqz v1, :cond_1        # 不强制 → 走普通更新
 *        :2193  invoke-static {..}, Lxl/z2;->t(Activity;ZZLci/a;)V   # 强制更新流程
 * ```
 *
 * `ei.y.L()` 是**唯一**读 `FORCE_UPDATE` 并据此进入强制流程的地方（全 APK 该枚举只有
 * 3 处引用：写入 `z2$b`、读取 `ei.y`、定义 `CommonPreference`）。它在 `H(...)` 的
 * `pswitch_5` 分支被调用，而 `pswitch_5` 对应服务端下发的 `Popwindow` 类型 5 = 强制更新弹窗。
 *
 * ### 两档力度（`update_force_neutralise`）
 *
 *  * **关（默认）**：只让 `ei.y.L()` 直接 return ⇒ 弹窗不出现，**不写入任何偏好**，完全可逆；
 *  * **开**：另外把 `xl.z2.k(CheckAppUpdate)` 收到的 `forceUp` 抹成 0 ⇒ 连"是否强制"的判定
 *    都变成普通更新。代价是 `z2$b` 会把 0 写进 `CommonPreference.FORCE_UPDATE`（持久），
 *    下次冷启动就是普通更新提示 —— 想要"可逆"就保持关闭。
 *
 * 风险都写在 `NEW_TARGETS.md` §1.2/§1.3：`ei.y` / `xl.z2` 是混淆名，升级后必须重跑
 * `check_hook_targets.py`；稳定锚点是 `CommonPreference.FORCE_UPDATE` 与
 * `CheckAppUpdate` 模型类（语义名，不会被混淆）。
 */
object SkipForceUpdate : SwitchFeature(
    id = "skip_update",
    title = "跳过强制更新",
    summary = "服务端下发\"必须升级\"时不再弹强制更新窗（钩 ei.y.L，可逆；可选连判定一起改）",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    override val options: List<KdOption> = listOf(
        KdOption(
            key = "update_force_neutralise",
            title = "连\"是否强制\"的判定也改掉",
            summary = "把 CheckAppUpdate.forceUp 抹成 0（会写入偏好，持久；想要可逆就保持关闭）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        var n = 0
        // ① 闸门：直接跳过整个强制更新流程
        if (Xp.hook("hh.y", "L", gate = id, onBefore = {
                it.result = null
                KdLog.i("SkipForceUpdate: suppressed force-update popup (ei.y.L)")
                Capture.append("UPDATE suppressed force-update popup")
            })
        ) n++
        // ② 可选：把判定输入改掉（走普通更新而不是完全不提示）
        val model = Xp.clazzOrNull("com.kuaiduizuoye.scan.common.net.model.v1.CheckAppUpdate")
        if (model != null) {
            if (Xp.hook("um.z2", "k", model, gate = id, onBefore = { p ->
                    if (!KdConfig.isOn("update_force_neutralise", false)) return@hook
                    val arg = p.args.firstOrNull() ?: return@hook
                    runCatching {
                        val f = arg.javaClass.getField("forceUp")
                        val before = f.getInt(arg)
                        f.setInt(arg, 0)
                        KdLog.i("SkipForceUpdate: forceUp $before -> 0")
                        Capture.append("UPDATE forceUp $before -> 0")
                    }.onFailure { KdLog.w("SkipForceUpdate: forceUp patch failed: $it") }
                })
            ) n++
        }
        KdLog.i("SkipForceUpdate installed ($n hooks)")
    }

    /** 诊断用：本机是不是"强制更新"版本（读偏好，不写）。 */
    fun forceUpdateFlag(): String = try {
        val cls = Xp.clazzOrNull("com.kuaiduizuoye.scan.preference.CommonPreference")
        if (cls == null) "unavailable" else {
            val enumConst = java.lang.Enum.valueOf(cls as Class<out Enum<*>>, "FORCE_UPDATE")
            XposedHelpers.callStaticMethod(
                Xp.clazz("com.baidu.homework.common.utils.PreferenceUtils"), "getBoolean", enumConst,
            ).toString()
        }
    } catch (t: Throwable) {
        "unavailable: ${t.message}"
    }
}
