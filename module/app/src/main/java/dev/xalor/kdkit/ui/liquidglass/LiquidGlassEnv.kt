package dev.xalor.kdkit.ui.liquidglass

import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.luminance
import com.kyant.backdrop.Backdrop

/**
 * 液态玻璃的三个环境值（与本地 `murexide-plus` 的 `ui/theme/LiquidGlass.kt` 保持一致）。
 *
 * 为什么用 `CompositionLocal` 而不是参数一路往下传：玻璃控件散落在底栏、卡片、按钮里，
 * 逐个透传会把签名串成一条长链；而这几个值是**整屏统一**的（一个页面一个 backdrop、
 * 一个模糊倍率），正好是 CompositionLocal 的适用场景。
 */
val LocalLiquidGlassEnabled = staticCompositionLocalOf { true }

/** 模糊半径**倍率**（不是 dp）：具体 dp 由各控件按自身尺寸换算，大小屏观感才一致。 */
val LocalLiquidGlassBlur = staticCompositionLocalOf { 1f }

/**
 * 当前作用域可采样的背景。null = 这里没有可采样的东西（弹窗里、独立窗口根上），
 * 此时必须降级成纯色 —— 拿空 Backdrop 硬算会画出一块黑。
 */
val LocalLiquidGlassBackdrop = staticCompositionLocalOf<Backdrop?> { null }

private const val DEFAULT_MINIMUM_TEXT_CONTRAST = 3f

/**
 * 为玻璃上的文字算一个"看得清"的前景色。
 *
 * 普通控件的 `onSurface` 在这里不成立：玻璃的底色取决于它背后采到的东西，
 * 浅色壁纸配浅色玻璃时黑字会糊掉，所以要按实际合成色算对比度。
 */
internal fun liquidGlassContentColor(
    preferredColor: Color,
    glassColor: Color,
    backgroundColor: Color,
    minimumContrast: Float = DEFAULT_MINIMUM_TEXT_CONTRAST,
): Color {
    val visibleGlassColor = glassColor.compositeOver(backgroundColor)
    if (contrastRatio(preferredColor, visibleGlassColor) >= minimumContrast) return preferredColor
    val blackContrast = contrastRatio(Color.Black, visibleGlassColor)
    val whiteContrast = contrastRatio(Color.White, visibleGlassColor)
    return if (blackContrast >= whiteContrast) Color.Black else Color.White
}

private fun contrastRatio(foreground: Color, background: Color): Float {
    val visibleForeground = foreground.compositeOver(background)
    val lighter = maxOf(visibleForeground.luminance(), background.luminance())
    val darker = minOf(visibleForeground.luminance(), background.luminance())
    return (lighter + 0.05f) / (darker + 0.05f)
}
