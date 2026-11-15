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
    private const val KEY_OOBE_VER = "oobe_version"

    /**
     * 引导的版本号。**改了引导内容就把这个数字 +1** —— 已装用户升级后会再看一次。
     * 只存"完成到第几版"，所以从 1 升到 2 时老用户（存着 1）也会重新触发。
     */
    const val OOBE_VERSION = 2

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /* ── Glasmio 液态玻璃 UI 的自愈开关 ────────────────────────────────────
     *
     * glasmio-glass 的渲染依赖 Skia RuntimeEffect，**模拟器/部分弱 GPU 上会直接
     * 在 RenderThread 里 SIGSEGV**（不是抛异常，抓不到）。所以这里做"先试后定"：
     *   1. 切到液态界面前置 `pending`；
     *   2. 真正画出两帧后置 `ok`；
     *   3. 下次启动如果看到 `pending` 还在 → 说明上次就是死在那里的，标记 `broken`，
     *      这次直接用普通界面。
     * 用户在真机上只要成功显示过一次，之后就一直用液态界面；在会崩的机器上则自动降级，
     * 不需要人肉判断。
     */
    private const val KEY_GLASS_STATE = "glass_state"
    private const val GLASS_PENDING = "pending"
    private const val GLASS_OK = "ok"
    private const val GLASS_BROKEN = "broken"

    fun glassState(ctx: Context): String = prefs(ctx).getString(KEY_GLASS_STATE, "") ?: ""

    fun markGlassPending(ctx: Context) {
        prefs(ctx).edit().putString(KEY_GLASS_STATE, GLASS_PENDING).apply()
    }

    fun confirmGlass(ctx: Context) {
        prefs(ctx).edit().putString(KEY_GLASS_STATE, GLASS_OK).apply()
    }

    /** 上次启动留下 pending → 判定这台机器画不了液态玻璃。 */
    fun glassBroken(ctx: Context): Boolean {
        val st = glassState(ctx)
        if (st == GLASS_PENDING) {
            prefs(ctx).edit().putString(KEY_GLASS_STATE, GLASS_BROKEN).apply()
            return true
        }
        return st == GLASS_BROKEN
    }

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
    /** 引导是否已看到当前版本。 */
    fun oobeDone(ctx: Context): Boolean =
        prefs(ctx).getInt(KEY_OOBE_VER, 0) >= OOBE_VERSION

    /** 手动"重看引导"（关于页里那个入口）。 */
    fun resetOobe(ctx: Context) {
        prefs(ctx).edit().putInt(KEY_OOBE_VER, 0).apply()
    }

    fun setOobeDone(ctx: Context, done: Boolean) {
        if (done) {
            prefs(ctx).edit().putInt(KEY_OOBE_VER, OOBE_VERSION).apply()
            return
        }
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
