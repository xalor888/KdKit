package dev.xalor.kdkit.config

/**
 * 一个**非开关型**配置项（子选项）。
 *
 * 由来（2026-10-25）：模块里已经存在 7 个"代码在读、界面写不了"的键 ——
 * `pk_mock` / `pk_auto_answer` / `bridge_guard_probe_remove_loading` /
 * `native_exit_guard_control` / `page_js_script` / `bridge_guard_list` /
 * `bridge_guard_http_allow`。它们只靠 kit 脚本或手工改 prefs 才能设置，
 * 于是"功能文档说有这个能力"和"用户能打开它"之间断了一截。
 *
 * 现在每个键都必须是 [KdOption] 的实例，由所属 feature 通过
 * `BaseFeature.options` 声明；设置页据此**通用渲染**（不需要为每个功能写界面），
 * 门禁脚本据此校验"代码读的键都有人声明"（`check_feature_parity.py --keys`）。
 */
data class KdOption(
    /** 持久化 key（= SharedPreferences 名），永不改名。 */
    val key: String,
    /** 设置页上显示的名字。 */
    val title: String,
    /** 一句话说明"改了会发生什么"。 */
    val summary: String,
    val kind: Kind,
    /** BOOLEAN 的默认值；STRING 的默认文本（空串表示没有默认）。 */
    val default: String = "",
) {
    enum class Kind { BOOLEAN, STRING }

    /** 布尔默认值（仅 [Kind.BOOLEAN] 有意义）。 */
    val defaultBool: Boolean
        get() = default == "true"

    /**
     * 这个键是否"值得在设置页露出"。`page_js_script` 这类由脚本写入的键不需要输入框，
     * 但**必须**在 schema 里存在（否则门禁会把它当幽灵键）。
     */
    val userEditable: Boolean
        get() = key != "page_js_script"
}
