package dev.xalor.kdkit.features

import dev.xalor.kdkit.features.ads.AdSlotProbe
import dev.xalor.kdkit.features.ads.RemoveAdSlotConfig
import dev.xalor.kdkit.features.ads.RemoveFeedAd
import dev.xalor.kdkit.features.ads.RemoveMainBannerAd
import dev.xalor.kdkit.features.ads.RemovePopupAd
import dev.xalor.kdkit.features.ads.RemoveSplashAd
import dev.xalor.kdkit.features.ads.RemoveTabAd
import dev.xalor.kdkit.features.host.AntiDetect
import dev.xalor.kdkit.features.host.BlockAdSdk
import dev.xalor.kdkit.features.host.BridgeActionLog
import dev.xalor.kdkit.features.host.BridgeGuard
import dev.xalor.kdkit.features.host.ExitGuard
import dev.xalor.kdkit.features.host.H5BridgeLog
import dev.xalor.kdkit.features.host.H5DebugConsole
import dev.xalor.kdkit.features.host.HttpBodyProbe
import dev.xalor.kdkit.features.host.NativeExitGuard
import dev.xalor.kdkit.features.host.NavLog
import dev.xalor.kdkit.features.host.NetErrorProbe
import dev.xalor.kdkit.features.host.PageRequestLog
import dev.xalor.kdkit.features.host.ParentCtrlProbe
import dev.xalor.kdkit.features.host.ParentModeWriteProbe
import dev.xalor.kdkit.features.host.PageJs
import dev.xalor.kdkit.features.host.PopwinGate
import dev.xalor.kdkit.features.host.RC4Probe
import dev.xalor.kdkit.features.host.ReqHeaders
import dev.xalor.kdkit.features.host.RobustProbe
import dev.xalor.kdkit.features.host.RouteLog
import dev.xalor.kdkit.features.host.SkipForceUpdate
import dev.xalor.kdkit.features.host.VipLimitProbe
import dev.xalor.kdkit.features.host.VipPromo
import dev.xalor.kdkit.features.host.VipUnlock
import dev.xalor.kdkit.features.host.WatermarkOff
import dev.xalor.kdkit.features.host.WebPictureWatermark
import dev.xalor.kdkit.features.host.SkipOnboarding
import dev.xalor.kdkit.features.host.WebRequestLog
import dev.xalor.kdkit.features.misc.LogSink
import dev.xalor.kdkit.features.misc.NativeProbe
import dev.xalor.kdkit.features.misc.SignObserver
import dev.xalor.kdkit.features.pk.PkAssist
import dev.xalor.kdkit.features.web.Md3Skin

/**
 * Every feature the module knows about, in UI order.
 *
 * **唯一事实源**：设置页、README 功能表、门禁脚本（`module/scripts/check_feature_parity.py`）
 * 都以这份清单为准。新增功能只改这里 + 功能自己的 object + README 表格。
 */
object FeatureRegistry {
    val all: List<BaseFeature> = listOf(
        // 广告
        AdSlotProbe,
        RemoveAdSlotConfig,
        RemoveSplashAd,
        RemoveTabAd,
        RemoveMainBannerAd,
        RemovePopupAd,
        RemoveFeedAd,
        BlockAdSdk,
        // PK
        PkAssist,
        // 其他
        SignObserver,
        NativeProbe,
        LogSink,
        // 宿主
        AntiDetect,
        SkipOnboarding,
        ExitGuard,
        NativeExitGuard,
        H5BridgeLog,
        WebRequestLog,
        PageJs,
        ReqHeaders,
        RouteLog,
        RC4Probe,
        NavLog,
        NetErrorProbe,
        HttpBodyProbe,
        BridgeGuard,
        BridgeActionLog,
        PageRequestLog,
        ParentCtrlProbe,
        ParentModeWriteProbe,
        PopwinGate,
        SkipForceUpdate,
        VipPromo,
        VipUnlock,
        VipLimitProbe,
        WatermarkOff,
        WebPictureWatermark,
        RobustProbe,
        H5DebugConsole,
        Md3Skin,
    )

    val categories: List<Pair<String, String>> = listOf(
        Category.ADS to "广告",
        Category.PK to "口算PK",
        Category.HOST to "宿主",
        Category.MISC to "其他",
    )

    fun byId(id: String): BaseFeature? = all.firstOrNull { it.id == id }

    /** 所有被声明的子选项（门禁用：判断"代码读的键是否都有人认领"）。 */
    val allOptions: List<Pair<String, dev.xalor.kdkit.config.KdOption>> =
        all.flatMap { f -> f.options.map { f.id to it } }

    /** 开着的功能数（诊断页/报告用；不做性能判断，直接算）。 */
    fun enabledCount(): Int = all.count { it.shouldRun() }
}
