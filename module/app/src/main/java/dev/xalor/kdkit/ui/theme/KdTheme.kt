package dev.xalor.kdkit.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/** iOS 语义色。整套界面只用这一张表，不再叠加第三方主题。 */
data class IosColors(
    val isDark: Boolean,
    val groupedBg: Color,
    val card: Color,
    val cardPressed: Color,
    val separator: Color,
    val content: Color,
    val secondary: Color,
    val tertiary: Color,
    val accent: Color,
    val destructive: Color,
    val dock: Color,
    val dockBorder: Color,
)

val LightIos = IosColors(
    isDark = false,
    groupedBg = Color(0xFFF2F2F7),
    card = Color(0xFFFFFFFF),
    cardPressed = Color(0xFFE5E5EA),
    separator = Color(0xFFD1D1D6),
    content = Color(0xFF000000),
    secondary = Color(0xFF8E8E93),
    tertiary = Color(0xFFC7C7CC),
    accent = Color(0xFF0A84FF),
    destructive = Color(0xFFFF3B30),
    dock = Color(0xF7FFFFFF),
    dockBorder = Color(0x14000000),
)

val DarkIos = IosColors(
    isDark = true,
    groupedBg = Color(0xFF000000),
    card = Color(0xFF1C1C1E),
    cardPressed = Color(0xFF2C2C2E),
    separator = Color(0xFF38383A),
    content = Color(0xFFFFFFFF),
    secondary = Color(0xFF8E8E93),
    tertiary = Color(0xFF48484A),
    accent = Color(0xFF0A84FF),
    destructive = Color(0xFFFF453A),
    dock = Color(0xF71C1C1E),
    dockBorder = Color(0x1FFFFFFF),
)

val LocalIos = staticCompositionLocalOf { LightIos }

@Composable
fun KdTheme(themeMode: String = UiPrefs.THEME_AUTO, content: @Composable () -> Unit) {
    val sysDark = isSystemInDarkTheme()
    val dark = when (themeMode) {
        UiPrefs.THEME_DARK -> true
        UiPrefs.THEME_LIGHT -> false
        else -> sysDark
    }
    val ios = if (dark) DarkIos else LightIos
    MaterialTheme(
        colorScheme = if (dark) darkColorScheme(
            primary = ios.accent, background = ios.groupedBg,
            surface = ios.card, onSurface = ios.content, onSurfaceVariant = ios.secondary,
        ) else lightColorScheme(
            primary = ios.accent, background = ios.groupedBg,
            surface = ios.card, onSurface = ios.content, onSurfaceVariant = ios.secondary,
        ),
    ) {
        CompositionLocalProvider(LocalIos provides ios, content = content)
    }
}
