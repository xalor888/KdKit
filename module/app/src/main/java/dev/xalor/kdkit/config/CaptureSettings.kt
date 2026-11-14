package dev.xalor.kdkit.config

import dev.xalor.kdkit.util.Capture

/**
 * 把"抓取体量"与"日志级别"这两个**运行期参数**接到配置通道上。
 *
 * 为什么需要单独一个类：`Capture` 在 `util/` 里，而 `KdConfig` 的读取点必须有明确的所有者
 * （门禁要求每个被读的键都能被某个 feature 的 `KdOption` 认领）。这两个键属于**模块级**
 * 基础设施而不是某个功能，所以由本对象统一读、统一写，并在 `FeatureRegistry` 侧
 * 由 [dev.xalor.kdkit.features.misc.LogSink] 声明为选项（它是最自然的归属：都是"记录"类设置）。
 *
 * 三个键：
 *  * `capture_max_mb`  —— 抓取文件上限（MB）；0 = 不限制（长取证场景，宁写满磁盘也不丢证据）
 *  * `capture_max_kb_line` —— 单行上限（KB），默认 4 KB；超长的桥 JSON 不该把磁盘吃掉
 *  * `log_level`       —— 0 静默 / 1 正常 / 2 详细，对应 `KdLog.level`
 *
 * 全部在**启动时**应用一次，之后任何时刻改配置、下次 [apply] 即生效（热开关不依赖它）。
 */
object CaptureSettings {

    const val KEY_MAX_MB = "capture_max_mb"
    const val KEY_MAX_LINE_KB = "capture_max_line_kb"
    const val KEY_LOG_LEVEL = "log_level"

    const val DEFAULT_MAX_MB = 4
    const val DEFAULT_MAX_LINE_KB = 4
    const val DEFAULT_LOG_LEVEL = 2

    /**
     * 字符串配置 → 字节上限。空/非法回落默认值；`0` 或负数 = **不限制**（返回 0）。
     *
     * 抽成纯函数是为了能真正被测（而不是在测试里抄一遍公式 —— 那样测的是测试自己）。
     */
    fun mbToBytes(raw: String?): Long {
        val mb = raw?.trim()?.toIntOrNull() ?: DEFAULT_MAX_MB
        return if (mb <= 0) 0L else mb.toLong() * 1024 * 1024
    }

    /** 字符串配置 → 单行字符上限。`0`/负数 = 不限制（返回 [Int.MAX_VALUE]）。 */
    fun kbToChars(raw: String?): Int {
        val kb = raw?.trim()?.toIntOrNull() ?: DEFAULT_MAX_LINE_KB
        return if (kb <= 0) Int.MAX_VALUE else kb * 1024
    }

    /** 字符串配置 → 日志级别，夹在 0..2。 */
    fun parseLevel(raw: String?): Int {
        val v = raw?.trim()?.toIntOrNull() ?: DEFAULT_LOG_LEVEL
        return v.coerceIn(0, 2)
    }

    /** 读取当前配置并应用到 [Capture] / [dev.xalor.kdkit.util.KdLog]。返回生效值的摘要。 */
    fun apply(): String {
        val maxBytes = mbToBytes(KdConfig.getString(KEY_MAX_MB, DEFAULT_MAX_MB.toString()))
        val maxLine = kbToChars(KdConfig.getString(KEY_MAX_LINE_KB, DEFAULT_MAX_LINE_KB.toString()))
        val level = parseLevel(KdConfig.getString(KEY_LOG_LEVEL, DEFAULT_LOG_LEVEL.toString()))

        Capture.maxBytes = maxBytes
        Capture.maxLine = maxLine
        dev.xalor.kdkit.util.KdLog.level = level

        val mbShown = if (maxBytes <= 0) "unlimited" else "${maxBytes / (1024 * 1024)}MB"
        val lineShown = if (maxLine == Int.MAX_VALUE) "unlimited" else "${maxLine / 1024}KB"
        return "capture_max=$mbShown line=$lineShown log_level=$level"
    }
}
