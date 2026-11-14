package dev.xalor.kdkit.features.pk

import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.features.web.WebInjector
import dev.xalor.kdkit.util.KdLog

/**
 * 口算 / 语文 / 单词 PK 辅助。
 *
 * The PK screens are the `kd-pk` H5 app. Its round component exposes the correct answer for each
 * question and a `checkResult(answer)` handler, so the userscript can drive the round directly.
 */
object PkAssist : SwitchFeature(
    id = "pk_assist",
    title = "PK 自动作答",
    summary = "在口算 / 诗词 / 成语 / 单词 PK 中自动提交正确答案",
    category = Category.PK,
    hot = true,
) {
    override val options: List<KdOption> = listOf(
        KdOption(
            key = "pk_mock",
            title = "直接进练习对局",
            summary = "打开后加载 PK 页时自动跳到 pk-room.html?mock=1（验收用）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "pk_auto_answer",
            title = "自动作答",
            summary = "在口算/诗词/成语/单词 PK 中自动选中正确答案",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
        KdOption(
            key = "pk_answer_delay_ms",
            title = "作答延迟 (ms)",
            summary = "每题延迟多久再点，太快容易被判异常（默认 180）",
            kind = KdOption.Kind.STRING,
            default = "180",
        ),
    )

    override fun install() {
        // 主开关必须在这里判：`pk_assist` 是纯 register 型功能（自己没有钩子），
        // 旧实现只读两个**子选项**，于是关掉主开关照样自动作答。
        WebInjector.register("pk") {
            if (!KdConfig.isOn(id, true)) {
                ""
            } else {
                PkScript.build(
                    mockMode = KdConfig.isOn("pk_mock", false),
                    autoAnswer = KdConfig.isOn("pk_auto_answer", true),
                    answerDelayMs = KdConfig.getString("pk_answer_delay_ms", "180").toIntOrNull() ?: 180,
                )
            }
        }
        KdLog.i("PkAssist registered (webs will be injected by WebInjector)")
    }
}
