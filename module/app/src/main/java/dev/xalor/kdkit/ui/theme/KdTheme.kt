package dev.xalor.kdkit.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.platform.LocalContext
import io.github.neoruaa.glasmio.core.GlasmioTheme
import io.github.neoruaa.glasmio.core.GlassAppearance
import io.github.neoruaa.glasmio.core.LocalGlassAppearance
import io.github.neoruaa.glasmio.core.glasmioColorScheme

val LocalKdDark = staticCompositionLocalOf { false }

/** 设备能不能真的画玻璃（native 通道）。模拟器/弱 GPU 上会 SIGSEGV，必须先关。 */
fun glassCapable(): Boolean {
    val fp = Build.FINGERPRINT ?: ""
    val model = Build.MODEL ?: ""
    return !(fp.contains("generic", true) || fp.contains("emulator", true) ||
        model.contains("sdk_gphone", true) || model.contains("Emulator", true))
}

@Composable
fun KdTheme(
    themeMode: String = UiPrefs.THEME_AUTO,
    glass: Boolean = true,
    content: @Composable () -> Unit,
) {
    val sysDark = isSystemInDarkTheme()
    val dark = when (themeMode) {
        UiPrefs.THEME_DARK -> true
        UiPrefs.THEME_LIGHT -> false
        else -> sysDark
    }
    val usable = glass && glassCapable()
    CompositionLocalProvider(
        LocalKdDark provides dark,
        LocalGlassAppearance provides GlassAppearance(
            liquidGlassEnabled = usable,
            reduceTransparency = !usable,
        ),
    ) {
        GlasmioTheme(isDark = dark, colorScheme = glasmioColorScheme(isDark = dark), content = content)
    }
}
