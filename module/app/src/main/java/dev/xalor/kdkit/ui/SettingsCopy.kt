package dev.xalor.kdkit.ui

import dev.xalor.kdkit.features.Category

/**
 * 设置页的**展示层文案**与分组 —— 与 `FeatureRegistry` 的契约分离。
 *
 * 为什么需要（2026-11-14，发版前重做设置页）
 * ────────────────────────────────
 * `BaseFeature.title/summary` 是**技术说明**：它要同时喂给 README 功能表与门禁，
 * 所以写的是"钩 dj.a 的 j/k/g / 7.7.2 里这个类是 aj.a / 服务端计次不受影响"。
 * 直接把它摊到列表里，用户看到的是一屏实现细节 —— 谁该开、开了会怎样，反而读不出来。
 *
 * 这里只做一件事：给**每个功能**一句简明（`label` / `blurb`）加一个**按用户意图**的分组。
 * 技术说明原样留在 `BaseFeature.summary`，在展开区里显示，不丢。
 *
 * 纪律（`SettingsCopyTest` 会查）：
 *  * 恰好覆盖 `FeatureRegistry.all` 的 38 个 id —— 多一个、少一个都红；
 *  * `blurb` ≤ 22 字，且不含类名/旧版本名/括号里的实现细节 —— 否则就又变成技术说明。
 */
enum class Group(
    val id: String,
    val label: String,
    val blurb: String,
    /** 首屏是否展开（诊断组默认收起，避免 23 项观测把列表压死）。 */
    val expanded: Boolean,
    /** 属于"推荐配置"（普通用户想要的），一键开启时只动这些。 */
    val recommended: Boolean,
) {
    ADS("ads", "去广告", "开屏、横幅、页签、弹窗、信息流，一次关干净", true, true),
    CONTENT("content", "内容与会员", "会员标识、水印、服务端弹窗", true, true),
    EASE("ease", "省心开关", "强制更新、首次引导、退出守卫", true, true),
    PK("pk", "答题助手", "口算 / 诗词 / 成语 / 单词 PK 自动作答", true, true),
    LOOK("look", "界面外观", "Material 3 简约皮肤（H5 与窗口配色）", true, true),
    DIAG("diag", "诊断与抓取", "观测数据写到文件，排障时才需要", false, false),
}

/** 一个功能在设置页里的样子。 */
data class Copy(val id: String, val group: Group, val label: String, val blurb: String)

object SettingsCopy {

    /** 38 条 —— 顺序即列表顺序（组内也按这个顺序）。 */
    val all: List<Copy> = listOf(
        // 去广告
        Copy("rm_splash", Group.ADS, "开屏广告", "打开 App 时那张全屏广告，不再出现"),
        Copy("rm_main_banner", Group.ADS, "主页横幅", "主页顶部的横幅广告图片"),
        Copy("rm_tab_ad", Group.ADS, "页签广告", "首页、我的等页签里的广告卡片"),
        Copy("rm_popup", Group.ADS, "弹窗广告", "突然弹出的广告窗"),
        Copy("rm_feed_ad", Group.ADS, "信息流广告", "答案页、详情页里混在内容中的广告"),
        Copy("rm_adconfig", Group.ADS, "广告位源头", "把广告位配置读成空，全部广告位一起失效"),
        Copy("block_ad_sdk", Group.ADS, "广告 SDK", "不让第三方广告 SDK 启动，彻底断掉请求"),

        // 内容与会员
        Copy("vip_unlock", Group.CONTENT, "会员标识", "客户端显示为会员；服务端仍按真实状态鉴权"),
        Copy("watermark_off", Group.CONTENT, "去水印开关", "把 App 自带的「去除水印」开关替你打开"),
        Copy("web_picture_watermark", Group.CONTENT, "大图水印", "图片浏览页给你原图，不带水印文字"),
        Copy("popwin_gate", Group.CONTENT, "服务端弹窗", "按类型拦首页的广告、销售类弹窗"),
        Copy("rm_vip_promo", Group.CONTENT, "会员推广", "底部会员弹窗、开屏后的推销、页面开通入口"),

        // 省心开关
        Copy("skip_update", Group.EASE, "强制更新", "不再被「必须升级」挡住"),
        Copy("skip_onboarding", Group.EASE, "首次引导", "自动点掉隐私同意、年龄、身份选择"),
        Copy("exit_guard", Group.EASE, "退出守卫", "拦掉 App 的自我退出，方便调试"),
        Copy("settings_entry", Group.EASE, "模块入口", "在快对设置页加一行，点开模块设置"),

        // 答题助手
        Copy("pk_assist", Group.PK, "PK 自动作答", "口算、诗词、成语、单词 PK 自动提交答案"),

        // 界面外观
        Copy("md3_skin", Group.LOOK, "MD3 皮肤", "中性配色、统一圆角、去重阴影"),

        // 诊断与抓取
        Copy("ad_probe", Group.DIAG, "广告位观测", "记录广告位读取，不拦截"),
        Copy("log_sink", Group.DIAG, "App 日志", "收录与签名、接口相关的日志行"),
        Copy("sign_observer", Group.DIAG, "签名观测", "记录请求签名参数与密钥"),
        Copy("native_probe", Group.DIAG, "签名公式探针", "读 native 字符串并当场验证签名公式"),
        Copy("rc4_probe", Group.DIAG, "解密观测", "记录 RC4 密钥与解密结果"),
        Copy("robust_probe", Group.DIAG, "热修观测", "记录 Robust 补丁是否接管了方法"),
        Copy("anti_detect", Group.DIAG, "反调试绕过", "让 App 的调试检测判定为干净"),
        Copy("native_exit_guard", Group.DIAG, "原生退出守卫", "挡住 App 的底层退出调用；不可撤销，慎开"),
        Copy("page_request_log", Group.DIAG, "页面代发请求", "记录页面让宿主打出的请求"),
        Copy("web_request_log", Group.DIAG, "网页请求", "记录 WebView 自己发出的请求"),
        Copy("req_headers", Group.DIAG, "请求头", "记录 App 请求携带的头"),
        Copy("http_body_probe", Group.DIAG, "请求响应体", "记录请求体与响应原始字节，截断显示"),
        Copy("net_error_probe", Group.DIAG, "网络失败", "记录失败错误码与消息"),
        Copy("route_log", Group.DIAG, "路由跳转", "记录 zyb:// 路由的实际跳转"),
        Copy("nav_log", Group.DIAG, "页面导航", "记录每次 H5 页面加载"),
        Copy("h5_bridge_log", Group.DIAG, "H5 桥调用", "记录网页调用的原生能力"),
        Copy("bridge_action_log", Group.DIAG, "桥参数详情", "记录桥调用带的具体参数"),
        Copy("bridge_guard", Group.DIAG, "桥守卫", "拦网页发起的调试、登出类动作"),
        Copy("page_js", Group.DIAG, "页面脚本注入", "执行配置里的 JS 片段"),
        Copy("h5_debug", Group.DIAG, "H5 调试台", "在网页里注入 eruda 控制台"),
        Copy("parent_ctrl_probe", Group.DIAG, "家长模式读取", "记录家长控制字段的取值"),
        Copy("parent_ctrl_write", Group.DIAG, "家长模式提交", "记录家长控制提交的快照"),
        Copy("vip_limit_probe", Group.DIAG, "重练额度", "记录额度判定：允许吗、用过几次"),
    )

    private val byId: Map<String, Copy> = all.associateBy { it.id }

    fun of(id: String): Copy? = byId[id]

    /** 设置页的展示用文案；`Copy` 缺项时回退到技术标题（并由单测拦住这种缺项）。 */
    fun labelOf(id: String, fallback: String): String = byId[id]?.label ?: fallback

    fun blurbOf(id: String, fallback: String): String = byId[id]?.blurb ?: fallback

    fun groupOf(id: String): Group = byId[id]?.group ?: Group.DIAG

    /** 推荐配置：只动"普通用户想要"的组，诊断一律关掉。 */
    val recommendedOn: Set<String>
        = all.filter { it.group.recommended }.map { it.id }.toSet()

    /** 分组按枚举顺序展示，组内按 [all] 顺序。 */
    fun items(group: Group): List<Copy> = all.filter { it.group == group }

    /** 门禁/UI 用来核对 `category` 与分组没有明显错配（只查技术分类与分组是否同向）。 */
    fun categoryMismatch(id: String, category: String): Boolean = when (groupOf(id)) {
        Group.ADS -> category != Category.ADS
        Group.PK -> category != Category.PK
        else -> false
    }
}
