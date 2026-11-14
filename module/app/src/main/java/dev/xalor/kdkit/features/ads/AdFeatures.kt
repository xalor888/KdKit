package dev.xalor.kdkit.features.ads

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

private const val PKG = "com.kuaiduizuoye.scan"
private const val MODEL = "$PKG.common.net.model.v1"

/**
 * 开屏广告。（**热开关**：钩子常驻，关掉即恢复原行为，不必重启宿主）
 *
 * `lk.a` is the app's splash-ad controller: `j(Activity)` launches ResumeSplashActivity and
 * `k()` decides whether an ad slot is configured at all. Neutralising both means the splash
 * screen never appears.
 *
 * 混淆名：基线（7.10.2/1860）是 `dj.a`，**1865（6.21.11）叫 `bj.a`**（`HostMap` id
 * `ads.splash`）。调用点照基线名写，翻译在 `HostMap`/`Xp` 的候选循环里 ——
 * 不要在这里改成新名，那会打断 7.10.2。证据见 `work/compat1865/ADS.md` §3.1。
 */
object RemoveSplashAd : SwitchFeature(
    id = "rm_splash",
    title = "开屏广告",
    summary = "启动/切回前台时不再展示开屏广告（改开关即时生效）",
    category = Category.ADS,
    hot = true,
) {
    override fun install() {
        val g = id
        var n = 0
        if (Xp.hook("dj.a", "j", android.app.Activity::class.java, gate = g, onBefore = { it.result = null })) n++
        if (Xp.hook("dj.a", "k", gate = g, onBefore = { it.result = false })) n++
        if (Xp.hook("dj.a", "g", gate = g, onBefore = { it.result = false })) n++
        KdLog.i("RemoveSplashAd installed ($n hooks)")
    }
}

/**
 * 广告槽位配置（全线）。（**热开关**）
 *
 * `aj.a` is the runtime accessor for InitAdConfig ad slots. Returning null / false for every
 * slot removes the app's *own* ad inventory before any renderer, mediation SDK or splash
 * controller can act on it — this is the broadest single cut.
 *
 * 混淆名：`aj.a` 是 7.7.2 的叫法，7.9.0 起是 `di.a`（本文件的字面量），
 * **1865 里是 `bi.a`**（`HostMap` id `ads.slot`）。1865 的 `di.a` 是**另一个类** ——
 * 它有 `d`/`f` 但签名不同，所以旧钩子在那里是"假命中"，不是"没找到"。
 */
object RemoveAdSlotConfig : SwitchFeature(
    id = "rm_adconfig",
    title = "广告配置拦截",
    summary = "拦截广告位配置读取，从源头禁用全部内置广告位（改开关即时生效）",
    category = Category.ADS,
    hot = true,
) {
    private const val ADLIST = "$MODEL.InitAdConfig\$ListItem\$AdlistItem"

    override fun install() {
        val g = id
        var n = 0
        for (m in listOf("d", "f", "h")) {
            if (Xp.hook("di.a", m, Int::class.javaPrimitiveType, gate = g, onBefore = {
                    val pos = it.args.getOrNull(0)
                    // 限流：只写前 20 条，避免广告位轮询把抓取文件刷满
                    if (RateLimit.firstN("adslot.$m", 20)) {
                        val line = "blocked ad slot read: di.a.$m($pos)"
                        KdLog.i(line)
                        Capture.append(line)
                    }
                    it.result = null
                })
            ) n++
        }
        // j()Z / k()Z -> "an ad is configured"
        //
        // **拦截本身也留一行证据**（2026-11-02 加）：旧实现只改 `it.result`，
        // 于是"这个钩子到底触发过没有"在抓取里**完全看不出来** ——
        // 广告面（C1）的判据只能数 `ADSLOT`（读数），数不到 `ADBLOCK`（拦截）。
        // 而"读了 88 次但一次没拦"与"拦了 88 次"是两件完全不同的事。
        // 限流 20 条：与上面的读数同量级，不会把抓取刷满。
        for (m in listOf("j", "k")) {
            if (Xp.hook("di.a", m, gate = g, onBefore = {
                    if (RateLimit.firstN("adblock.$m", 20)) {
                        Capture.append("ADBLOCK di.a.$m -> false")
                    }
                    it.result = false
                })) n++
        }
        KdLog.i("RemoveAdSlotConfig installed ($n hooks)")
    }
}

/** Tab 广告（首页/我的 等页签内的广告卡片）。（**热开关**） */
object RemoveTabAd : SwitchFeature(
    id = "rm_tab_ad",
    title = "Tab 广告",
    summary = "移除首页 / 我的 等页签内嵌广告卡片（改开关即时生效）",
    category = Category.ADS,
    hot = true,
) {
    override fun install() {
        val g = id
        var n = 0
        if (Xp.hook(
                "$PKG.activity.main.widget.TabAdvertisementView", "initData",
                Xp.clazzOrNull("$MODEL.AdConfig\$PopupAdItem"),
                gate = g, onBefore = { it.result = null },
            )
        ) n++
        if (Xp.hook("$PKG.activity.main.widget.TabAdvertisementView", "isInitDataSuccess", gate = g, onBefore = { it.result = false })) n++
        if (Xp.hook(
                "$PKG.activity.main.widget.TabAdvertisementContainerView", "initData",
                Xp.clazzOrNull("$MODEL.AdConfig"),
                gate = g, onBefore = { it.result = null },
            )
        ) n++
        if (Xp.hook("$PKG.activity.main.widget.TabAdvertisementContainerView", "isDataNullOrEmpty", gate = g, onBefore = { it.result = true })) n++
        KdLog.i("RemoveTabAd installed ($n hooks)")
    }
}

/** 首页主界面横幅广告。（**热开关**） */
object RemoveMainBannerAd : SwitchFeature(
    id = "rm_main_banner",
    title = "主页横幅广告",
    summary = "移除主页顶部的横幅广告图片（改开关即时生效）",
    category = Category.ADS,
    hot = true,
) {
    override fun install() {
        val g = id
        var n = 0
        val fragment = Xp.clazzOrNull("androidx.fragment.app.Fragment")
        if (fragment != null && Xp.hook("$PKG.activity.main.widget.MainAdvertiseImageView", "show", fragment, gate = g, onBefore = { it.result = null })) n++
        if (Xp.hook("$PKG.activity.main.widget.MainAdvertiseImageView", "showOrHideAdvertise", Boolean::class.javaPrimitiveType, gate = g, onBefore = { it.result = null })) n++
        KdLog.i("RemoveMainBannerAd installed ($n hooks)")
    }
}

/** 信息流 / 详情页广告（搜索结果、答案页等由 Adx 下发的自渲染广告）。（**热开关**） */
object RemoveFeedAd : SwitchFeature(
    id = "rm_feed_ad",
    title = "信息流广告",
    summary = "清空 Adx 下发的自渲染广告（答案页、详情页等，改开关即时生效）",
    category = Category.ADS,
    hot = true,
) {
    private const val SELL = "$PKG.activity.advertisement.sell.widget"

    override fun install() {
        val g = id
        var n = 0
        val list = java.util.List::class.java
        if (Xp.hook("$SELL.DetailSellAdxContainerAdView", "setAdData", list, gate = g, onBefore = { it.args[0] = java.util.ArrayList<Any>() })) n++
        if (Xp.hook("$SELL.DetailSellAdxImageAdView", "showData", gate = g, onBefore = { it.result = null })) n++
        KdLog.i("RemoveFeedAd installed ($n hooks)")
    }
}

/** 弹窗广告。（**热开关**） */
object RemovePopupAd : SwitchFeature(
    id = "rm_popup",
    title = "弹窗广告",
    summary = "拦截广告弹窗的展示（改开关即时生效）",
    category = Category.ADS,
    hot = true,
) {
    override fun install() {
        val g = id
        var n = 0
        // 类名写字面量：静态门禁按字面量解析（用 `dialog.name` 会让这条钩子失去校验）。
        //
        // 1865 的同名宿主类**类名不变**，但 `g` 的第二个形参换了短名：`fh.a` → `dh.a`
        // （`HostMap` id `ads.popup.showArg`；两个接口的方法集逐条相同）。
        // 所以这里仍写基线名，运行时 `clazzOrNull` 会给出 1865 的那一侧。
        // 第二个形参 `ci.a` 只能在运行时解析（它是混淆名，脚本无法从字面量推出），
        // 所以仍用 clazzOrNull。
        //
        // 门禁对它的标注是 **`TYPE-ONLY`**（`class_refs=121`、`direct=0`），
        // 意思是"这个类被大量当作类型使用，但没有任何 `invoke-*` 直接调用它" ——
        // 正是形参类型的典型形态，不是死代码。
        //
        // 早前这里写的是"门禁会标 UNKNOWN"，那是**过期的**：`smali_usage` 后来
        // 细分出了 `TYPE-ONLY` / `SUPER-SLOT` / `REFLECTIVE-ENTRY` 三层。
        // 注释比代码更容易过期，且过期后不会有人发现 —— 这行也不例外，
        // 是 2026-10-26 核对 ④ 的 21 个 TYPE-ONLY 目标时才发现的。
        if (Xp.clazzOrNull("$PKG.activity.advertisement.popup.widget.PopupAdvertisementDialog") != null) {
            val showArg = Xp.clazzOrNull("fh.a")
            if (showArg != null && Xp.hook(
                    "com.kuaiduizuoye.scan.activity.advertisement.popup.widget.PopupAdvertisementDialog",
                    "g", Boolean::class.javaPrimitiveType, showArg,
                    gate = g, onBefore = { it.result = null },
                )
            ) n++
        }
        KdLog.i("RemovePopupAd installed ($n hooks)")
    }
}

/**
 * 广告位读取**观测**（默认关闭，只记录、不改结果）。（**热开关**）
 *
 * 为什么需要它：去广告功能在 `aj.a.d/f/h` 上返回 null，于是"App 到底问过哪些位号、本来会拿到什么"
 * 就永远看不见了。挂在**同一个入口**但只观察，写两行：
 *
 *   ADSLOT call di.a.d(501)                 ← 调用发生（无论有没有别的钩子短路）
 *   ADSLOT ret  di.a.d(501) -> null          ← 返回（被 blocker 短路时这行不会出现）
 *
 * 类名变更：7.7.2 里这个类是 `aj.a`；7.9.0 的 R8 重排把它挪到 `di.a`，
 * 而 `aj.a` 这个名字转给了旧的 `bk.a`（会员闸门）。证据里写错类名会让人
 * 去 smali 里 `aj.a` 找广告位、结果找到会员类 —— 2026-11-02 改正。
 *
 * 实现上刻意把"调用"记在 **before**：实测当另一个钩子在 before 里 `setResult` 短路后，
 * 同一方法上后续钩子的 **after 回调不再执行** —— 只靠 after 记日志的观测钩子会整个哑掉（遇到过）。
 *
 * 另外它回答了一个此前的疑问：测试设备上 App 自己的广告位读取**本来就返回 null**（`/init/ad/config` 是空表），
 * 所以"看不到广告"里有一段与模块无关。
 */
object AdSlotProbe : SwitchFeature(
    id = "ad_probe",
    title = "广告位读取观测",
    summary = "只记录不拦截：把 App 对 di.a 各广告位的调用与返回写进抓取文件（7.7.2 里这个类是 aj.a；本功能与去广告功能可同时开启）",
    category = Category.ADS,
    defaultOn = false,
    hot = true,
) {
    private const val PER_KEY = 12

    override fun install() {
        val g = id
        var n = 0
        for (m in listOf("d", "f", "h")) {
            if (Xp.hook("di.a", m, Int::class.javaPrimitiveType, gate = g,
                    onBefore = { p ->
                        val pos = p.args?.firstOrNull()?.toString() ?: "?"
                        val key = "$m($pos)"
                        val c = RateLimit.count("adslot.call.$key")
                        if (RateLimit.firstN("adslot.call.$key", PER_KEY)) {
                            Capture.append("ADSLOT call di.a.$key #$c")
                        }
                        if (RateLimit.firstN("adslot.log.$key", 1)) KdLog.i("AdSlotProbe: call di.a.$key")
                    },
                    onAfter = { p ->
                        val pos = p.args?.firstOrNull()?.toString() ?: "?"
                        if (!RateLimit.firstN("adslot.ret.$m", PER_KEY)) return@hook
                        val r = p.result
                        val shown = when (r) {
                            null -> "null"
                            is Boolean -> r.toString()
                            else -> r.javaClass.simpleName
                        }
                        Capture.append("ADSLOT ret  di.a.$m($pos) -> $shown")
                    })) n++
        }
        // `j()` / `k()` 返回"这个宿位到底配没配广告" —— 去广告功能正是把这两个改成 false。
        // 只探 `d/f/h` 的话，开/关 `rm_adconfig` 在证据上**看不出任何差别**（两者都 `-> null`），
        // 于是"广告位已被禁用"这件事无法被验证（2026-11-02 实测发现）。
        for (m in listOf("j", "k")) {
            if (Xp.hook("di.a", m, gate = g, onBefore = null,
                    onAfter = { p ->
                        if (RateLimit.firstN("adslot.bool.$m", PER_KEY)) {
                            val r = p.result
                            Capture.append("ADSLOT ret  di.a.$m() -> ${r ?: "null"}")
                        }
                    })) n++
        }
        KdLog.i("AdSlotProbe installed ($n hooks, observe-only)")
    }
}
