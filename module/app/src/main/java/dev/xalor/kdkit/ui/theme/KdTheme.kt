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
            // 关键：**再套一层 MaterialTheme**。
            // 我们的页面里 `Text` / `Icon` 用的是 androidx.compose.material3，
            // 它们的默认颜色来自 MaterialTheme.colorScheme —— 不套这一层的话，
            // 深色模式下 MiuixTheme 变深、Material 仍是浅色方案，标题就成了"黑字黑底"
            // （2026-11-15 实测：KdKit 大标题在深色下几乎看不见）。
            // 这里把 miuix 的语义色映射成 Material 的角色，两套组件才共享同一份"当前是深色"。
            val m = MiuixTheme.colorScheme
            val base = if (dark) {
                androidx.compose.material3.darkColorScheme()
            } else {
                androidx.compose.material3.lightColorScheme()
            }
            androidx.compose.material3.MaterialTheme(
                colorScheme = base.copy(
                    primary = m.primary,
                    background = m.background,
                    onBackground = m.onSurface,
                    surface = m.surface,
                    onSurface = m.onSurface,
                    onSurfaceVariant = m.onSurfaceVariantSummary,
                ),
                content = content,
            )
        }
    }
}
