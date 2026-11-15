package dev.xalor.kdkit.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import top.yukonga.miuix.kmp.theme.MiuixTheme
import top.yukonga.miuix.kmp.theme.darkColorScheme
import top.yukonga.miuix.kmp.theme.lightColorScheme

val LocalKdDark = staticCompositionLocalOf { false }

/**
 * 主题入口 —— 只包 **Miuix**，不自造色板。
 *
 * 为什么不自造：miuix 的一整套观感（圆角、按压反馈、文字层级、分隔线）都建立在
 * `MiuixTheme.colorScheme` 上；在外面再套一层自己的颜色，就会立刻"不像 miuix"。
 * 之前几版正是这么跑偏的，这一版全部交回 miuix 默认值。
 */
@Composable
fun KdTheme(themeMode: String = UiPrefs.THEME_AUTO, content: @Composable () -> Unit) {
    val sysDark = isSystemInDarkTheme()
    val dark = when (themeMode) {
        UiPrefs.THEME_DARK -> true
        UiPrefs.THEME_LIGHT -> false
        else -> sysDark
    }
    CompositionLocalProvider(LocalKdDark provides dark) {
        MiuixTheme(colors = if (dark) darkColorScheme() else lightColorScheme()) {
            content()
        }
    }
}
