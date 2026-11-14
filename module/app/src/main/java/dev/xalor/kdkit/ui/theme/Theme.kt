package dev.xalor.kdkit.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import top.yukonga.miuix.kmp.theme.MiuixTheme
import top.yukonga.miuix.kmp.theme.darkColorScheme as miuixDarkScheme
import top.yukonga.miuix.kmp.theme.lightColorScheme as miuixLightScheme

/**
 * 玻璃色板 —— "液态玻璃"这套视觉需要的颜色全在这里算一次。
 *
 * 为什么单独一个色板而不是直接用 `MaterialTheme.colorScheme`：
 * 玻璃卡片要的是**半透明填充 + 高光描边 + 背景渐变的三层色**，而 M3 的
 * `surface/surfaceVariant` 是不透明的语义色，直接套上去会得到"实心卡片"，
 * 看起来和普通 Material 3 一模一样（这正是这版之前的观感）。
 */
data class GlassColors(
    val isDark: Boolean,
    val bgTop: Color,
    val bgBottom: Color,
    val bgBlob1: Color,
    val bgBlob2: Color,
    val cardFillTop: Color,
    val cardFillBottom: Color,
    val cardBorder: Color,
    val cardShadow: Color,
    val onCard: Color,
    val onCardMuted: Color,
    val accent: Color,
    // 玻璃卡内部的两团彩色晕染与三段高光边（"液态"的来源）
    val cardTint1: Color,
    val cardTint2: Color,
    val cardHighlightTop: Color,
    val cardHighlightMid: Color,
    val cardHighlightBottom: Color,
)

private val LightGlass = GlassColors(
    isDark = false,
    bgTop = Color(0xFFF5F6FB),
    bgBottom = Color(0xFFE3E7F3),
    bgBlob1 = Color(0x995B6BC0),
    bgBlob2 = Color(0x99F2C572),
    cardFillTop = Color(0xCCFFFFFF),
    cardFillBottom = Color(0x99FFFFFF),
    cardBorder = Color(0x66FFFFFF),
    cardShadow = Color(0x1A1B1B24),
    onCard = Color(0xFF1B1B22),
    onCardMuted = Color(0xFF5A5A68),
    accent = Color(0xFF4C5BC4),
    cardTint1 = Color(0x66A8B6FF),
    cardTint2 = Color(0x66FFD7A1),
    cardHighlightTop = Color(0xEEFFFFFF),
    cardHighlightMid = Color(0x33FFFFFF),
    cardHighlightBottom = Color(0x14FFFFFF),
)

private val DarkGlass = GlassColors(
    isDark = true,
    bgTop = Color(0xFF12141C),
    bgBottom = Color(0xFF080A10),
    bgBlob1 = Color(0x995B6BC0),
    bgBlob2 = Color(0x995E4B8C),
    cardFillTop = Color(0x661C1F2A),
    cardFillBottom = Color(0x4D14161F),
    cardBorder = Color(0x1AFFFFFF),
    cardShadow = Color(0x66000000),
    onCard = Color(0xFFECEBF4),
    onCardMuted = Color(0xFF9A9AAC),
    accent = Color(0xFF9AA6FF),
    cardTint1 = Color(0x55808CFF),
    cardTint2 = Color(0x55C9A2FF),
    cardHighlightTop = Color(0x59FFFFFF),
    cardHighlightMid = Color(0x1FFFFFFF),
    cardHighlightBottom = Color(0x0AFFFFFF),
)

val LocalGlass = staticCompositionLocalOf { LightGlass }

private val LightScheme = lightColorScheme(
    primary = Color(0xFF4C5BC4),
    onPrimary = Color.White,
    secondary = Color(0xFF6B5EA8),
    surface = Color(0xFFF5F6FB),
    onSurface = Color(0xFF1B1B22),
)

private val DarkScheme = darkColorScheme(
    primary = Color(0xFF9AA6FF),
    onPrimary = Color(0xFF10131F),
    secondary = Color(0xFFC7BDFF),
    surface = Color(0xFF101219),
    onSurface = Color(0xFFECEBF4),
)

/**
 * @param themeMode [UiPrefs.THEME_AUTO] / LIGHT / DARK —— 顶栏那个按钮切的就是它。
 * @param glass 关掉玻璃 = 用不透明卡片（低端机/不喜欢通透感时的退路）。
 */
@Composable
fun KdKitTheme(
    themeMode: String = UiPrefs.THEME_AUTO,
    glass: Boolean = true,
    content: @Composable () -> Unit,
) {
    val ctx = LocalContext.current
    val sysDark = isSystemInDarkTheme()
    val dark = when (themeMode) {
        UiPrefs.THEME_DARK -> true
        UiPrefs.THEME_LIGHT -> false
        else -> sysDark
    }

    // 动态取色只在"玻璃关掉"时才用：玻璃卡片自带色板，混进 wallpaper 色会让卡片和背景打架。
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !glass ->
            if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
        dark -> DarkScheme
        else -> LightScheme
    }

    val glassColors = if (dark) DarkGlass else LightGlass

    // Miuix 的色板与文字样式：设置页的行（SuperSwitch / SmallTitle）从它取色。
    val miuixColors = if (dark) miuixDarkScheme() else miuixLightScheme()

    MiuixTheme(colors = miuixColors) {
        CompositionLocalProvider(LocalGlass provides glassColors) {
            MaterialTheme(colorScheme = scheme, content = content)
        }
    }
}

/** 玻璃关掉时给卡片用的不透明底色（其它地方统一从这里取，避免两套颜色）。 */
@Composable
fun opaqueCardColor(): Color = if (LocalGlass.current.isDark) Color(0xFF1B1E27) else Color(0xFFFFFFFF)
