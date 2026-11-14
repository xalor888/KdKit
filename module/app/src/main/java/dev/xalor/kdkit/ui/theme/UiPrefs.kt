package dev.xalor.kdkit.ui.theme

import android.content.Context

/**
 * 设置应用**自己的**外观偏好（不是发给宿主的配置）。
 *
 * 为什么不走 `KdConfig`：那是"宿主进程要读的功能开关"，会被发布成 world-readable 文件；
 * 而"我这个设置页长什么样"只属于本应用，混进去会污染宿主配置表，也会让 `allOptions`
 * 门禁多出一堆没人认领的键。
 */
object UiPrefs {

    const val THEME_AUTO = "auto"
    const val THEME_LIGHT = "light"
    const val THEME_DARK = "dark"

    const val GLASS_ON = "on"
    const val GLASS_OFF = "off"

    private const val NAME = "kdkit_ui"
    private const val KEY_THEME = "theme"
    private const val KEY_GLASS = "glass"
    private const val KEY_OOBE = "oobe_done"

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun theme(ctx: Context): String =
        prefs(ctx).getString(KEY_THEME, THEME_AUTO) ?: THEME_AUTO

    fun setTheme(ctx: Context, value: String) {
        prefs(ctx).edit().putString(KEY_THEME, value).apply()
    }

    fun glass(ctx: Context): Boolean = prefs(ctx).getString(KEY_GLASS, GLASS_ON) != GLASS_OFF

    fun setGlass(ctx: Context, on: Boolean) {
        prefs(ctx).edit().putString(KEY_GLASS, if (on) GLASS_ON else GLASS_OFF).apply()
    }

    /** 首次启动引导是否已完成（OOBE 只在 false 时显示）。 */
    fun oobeDone(ctx: Context): Boolean = prefs(ctx).getBoolean(KEY_OOBE, false)

    fun setOobeDone(ctx: Context, done: Boolean) {
        prefs(ctx).edit().putBoolean(KEY_OOBE, done).apply()
    }

    /** 主题下一档（auto → light → dark → auto），给顶栏那个按钮用。 */
    fun next(ctx: Context): String = when (theme(ctx)) {
        THEME_LIGHT -> THEME_DARK
        THEME_DARK -> THEME_AUTO
        else -> THEME_LIGHT
    }

    fun label(value: String): String = when (value) {
        THEME_LIGHT -> "浅色"
        THEME_DARK -> "深色"
        else -> "跟随系统"
    }
}
