package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 会员状态解锁（**仅客户端**，默认关闭，热开关）。
 *
 * ### 为什么钩 `bk.a.p()`
 *
 * `bk.a.p()`（`smali_classes5/bk/a.smali:2139`）是"是否会员"的判定入口：
 *
 * ```smali
 * :2208  invoke-static {}, Lbk/a;->f()I     # 取 Userinfov3$Vip.status
 * :2219  if-ne v1, v2(v2=1) → true          # status == 1 ⇒ 会员
 * ```
 *
 * **最强的旁证**：`VipCurrentStatusWebAction`（`@FeAction(name="app_kdzy_vip_current_status")`）
 * 把 `bk.a.p()` 当作唯一来源直接回给 H5（`VipCurrentStatusWebAction.smali:169`）——
 * 也就是说**H5 判断会员与否走的就是这一个方法**，钩一处，页面侧全部生效。
 *
 * ### 它不做什么（必须说清）
 *
 * 只改**客户端判定**。真正的资源鉴权在服务端（`/kdapi/…`、图片合成、题库解析），
 * 钩完之后页面会显示会员样式并放开前端入口，但服务端仍可能拒绝实际请求。
 * 这是"服务端权威"，静态层绕不过去 —— 详见 `NEW_TARGETS.md` §5.6。
 *
 * ### 埋点副作用（所以给了选项）
 *
 * `MainActivity:2660` 也调 `bk.a.p()` 拼 `isvip` 打点参数 ⇒ 钩了它会上报"会员"。
 * 在意数据就把 `vip_unlock_silent` 打开 —— 那时只对 H5 的回包生效（改
 * `VipCurrentStatusWebAction.onAction` 而不是 `bk.a.p()`）。
 */
object VipUnlock : SwitchFeature(
    id = "vip_unlock",
    title = "会员状态解锁（客户端）",
    summary = "让客户端判定为会员（改 bk.a.p / n）；服务端鉴权不受影响，详见 NEW_TARGETS.md §5",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    override val options: List<KdOption> = listOf(
        KdOption(
            key = "vip_unlock_tbx",
            title = "同时解锁 tbxVip",
            summary = "App 有两套会员字段（vip / tbxVip），全解锁需要一起改",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
        KdOption(
            key = "vip_unlock_silent",
            title = "不改全局判定（只影响 H5 回包）",
            summary = "避免污染 isvip 埋点：改为只改 app_kdzy_vip_current_status 的回包",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        var n = 0
        // ① H5 状态回包（silent 模式的唯一钩点；非 silent 时也装上，无害）
        // 三参：Activity, JSONObject, HybridWebView$ReturnCallback
        // （少写第三个参数时 check_hook_signatures.py 会报 SIGNATURE-MISMATCH —— 这正是它存在的理由）
        // 2026-10-26 已核对：删掉第三个参数后门禁确实报
        // `SIGNATURE-MISMATCH …onAction(Landroid/app/Activity;Lorg/json/JSONObject;)` 并指到本行。
        val returnCb = Xp.clazzOrNull("com.baidu.homework.common.ui.widget.HybridWebView\$ReturnCallback")
        if (returnCb != null && Xp.hook(
                "com.kuaiduizuoye.scan.web.actions.VipCurrentStatusWebAction", "onAction",
                android.app.Activity::class.java, org.json.JSONObject::class.java, returnCb,
                gate = id, onBefore = { note() },
            )
        ) n++

        // ② 全局判定（silent 模式下不装，避免污染埋点）
        if (!dev.xalor.kdkit.config.KdConfig.isOn("vip_unlock_silent", false)) {
            // p()Z —— 是否会员
            if (Xp.hook("aj.a", "p", gate = id, onBefore = {
                    it.result = true
                    note()
                })
            ) n++
            // n()Z —— tbxVip（第二套会员体系）
            if (Xp.hook("aj.a", "n", gate = id, onBefore = {
                    if (!dev.xalor.kdkit.config.KdConfig.isOn("vip_unlock_tbx", true)) return@hook
                    it.result = true
                    note()
                })
            ) n++
        }
        val silent = dev.xalor.kdkit.config.KdConfig.isOn("vip_unlock_silent", false)
        KdLog.i("VipUnlock installed (" + n + " hooks, silent=" + silent + ")")
    }

    /** 只记前几条 + 每分钟一条心跳，避免每次会员判定都写一行。 */
    private fun note() {
        if (RateLimit.firstN("vip.note", 5) || RateLimit.every("vip.heartbeat", 60_000)) {
            Capture.append("VIP unlock applied")
        }
    }
}
