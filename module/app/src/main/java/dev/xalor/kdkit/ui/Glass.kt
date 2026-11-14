package dev.xalor.kdkit.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.xalor.kdkit.ui.theme.LocalGlass
import dev.xalor.kdkit.ui.theme.opaqueCardColor

/**
 * 液态玻璃背景 —— 纵向渐变 + 两块柔光斑 + 一层极细噪点。
 *
 * 噪点不是装饰：没有它，背景就是纯净渐变，"模糊"与"不模糊"看起来完全一样
 * （这就是上一版玻璃被评价成"和没有区别"的原因）。有了噪点与色斑，
 * 卡片的模糊层才有东西可糊。
 */
@Composable
fun GlassBackground(
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    val g = LocalGlass.current
    val bottom = if (g.isDark) Color(0xFF04050A) else Color(0xFFD8DDF0)

    BoxWithConstraints(modifier.fillMaxSize()) {
        val wPx = constraints.maxWidth
        val hPx = constraints.maxHeight
        // 关键（2026-11-14 真机 ANR）：背景**预渲染成一张位图**，只在尺寸/主题变化时生成一次。
        // 之前是每帧在 Compose Canvas 里画两个大半径 radialGradient 圆（半径约 1000px，
        // 在 2K 屏 + 520dpi 上填充率爆炸），ANR trace 直接指向 Glass.kt 的 drawCircle。
        val bitmap = remember(wPx, hPx, g.isDark) {
            renderBackdrop(wPx, hPx, g, bottom)
        }
        if (bitmap != null) {
            Image(
                bitmap = bitmap,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.FillBounds,
            )
        }
        content()
    }
}

/** 卡片内的彩色晕染，同样预渲染（半分辨率）。 */
private fun renderCard(wPx: Int, hPx: Int, g: dev.xalor.kdkit.ui.theme.GlassColors): ImageBitmap? {
    if (wPx <= 0 || hPx <= 0) return null
    val w = (wPx * 0.5f).toInt().coerceAtLeast(1)
    val h = (hPx * 0.5f).toInt().coerceAtLeast(1)
    val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
    val canvas = android.graphics.Canvas(bmp)
    val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
    paint.shader = android.graphics.LinearGradient(
        0f, 0f, w.toFloat(), h.toFloat(),
        intArrayOf(g.cardFillTop.toArgb(), g.cardFillBottom.toArgb()),
        floatArrayOf(0f, 1f),
        android.graphics.Shader.TileMode.CLAMP,
    )
    canvas.drawRect(0f, 0f, w.toFloat(), h.toFloat(), paint)
    val maxDim = maxOf(w, h).toFloat()
    fun tint(cx: Float, cy: Float, color: Color) {
        paint.shader = android.graphics.RadialGradient(
            cx, cy, maxDim * 0.9f,
            intArrayOf(color.toArgb(), android.graphics.Color.TRANSPARENT),
            floatArrayOf(0f, 1f), android.graphics.Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, maxDim * 0.9f, paint)
    }
    tint(w * 0.12f, 0f, g.cardTint1)
    tint(w * 0.95f, h.toFloat(), g.cardTint2)
    paint.shader = null
    return bmp.asImageBitmap()
}

/** 用系统 Canvas/Paint 生成背景位图（半分辨率即可：渐变与光斑本来就是柔和的）。 */
private fun renderBackdrop(wPx: Int, hPx: Int, g: dev.xalor.kdkit.ui.theme.GlassColors, bottom: Color): ImageBitmap? {
    if (wPx <= 0 || hPx <= 0) return null
    val scale = 0.5f
    val w = (wPx * scale).toInt().coerceAtLeast(1)
    val h = (hPx * scale).toInt().coerceAtLeast(1)
    val bmp = android.graphics.Bitmap.createBitmap(w, h, android.graphics.Bitmap.Config.ARGB_8888)
    val canvas = android.graphics.Canvas(bmp)
    val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)

    // 1) 纵向渐变底
    paint.shader = android.graphics.LinearGradient(
        0f, 0f, 0f, h.toFloat(),
        intArrayOf(g.bgTop.toArgb(), g.bgBottom.toArgb(), bottom.toArgb()),
        floatArrayOf(0f, 0.6f, 1f),
        android.graphics.Shader.TileMode.CLAMP,
    )
    canvas.drawRect(0f, 0f, w.toFloat(), h.toFloat(), paint)

    // 2) 两块柔光（预渲染，只画一次）
    fun blob(cx: Float, cy: Float, r: Float, color: Color) {
        paint.shader = android.graphics.RadialGradient(
            cx, cy, r,
            intArrayOf(color.toArgb(), android.graphics.Color.TRANSPARENT),
            floatArrayOf(0f, 1f),
            android.graphics.Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, r, paint)
    }
    val minDim = minOf(w, h).toFloat()
    blob(w * 0.16f, h * 0.10f, minDim * 0.8f, g.bgBlob1)
    blob(w * 0.88f, h * 0.58f, minDim * 0.75f, g.bgBlob2)

    paint.shader = null
    return bmp.asImageBitmap()
}

/**
 * 液态玻璃卡：**模糊的彩色晕染底层 + 半透明填充 + 双色高光边 + 柔和外阴影**。
 *
 * 结构（自下而上）：
 *  1. 背景层：渐变填充 + 两团彩色光斑（这是"液态"的颜色来源）；
 *  2. （原先这里有一层 [BlurEffect] 模糊，2026-11-14 移除：在 Android 17 上它会让整页黑屏——
 *     渲染后端拿不到 RenderEffect 时连底色都不画。现在改用「晕染渐变本身够柔和」的等价做法。）
 *  3. 高光边：上亮下暗的 1dp 渐变描边，模拟玻璃边缘；
 *  4. 内容层。
 *
 * `glassOff = true` 时只剩不透明底色 + 普通描边 —— 布局不变，只是"透不透"变了。
 */
@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(26.dp),
    glassOff: Boolean = false,
    contentPadding: PaddingValues = PaddingValues(0.dp),
    elevation: Dp = 14.dp,
    content: @Composable BoxScope.() -> Unit,
) {
    val g = LocalGlass.current
    val blurPx = 26f

    Box(
        modifier = modifier
            .shadow(
                if (glassOff) 4.dp else elevation, shape,
                ambientColor = g.cardShadow, spotColor = g.cardShadow,
            )
            .clip(shape),
    ) {
        if (glassOff) {
            Box(Modifier.matchParentSize().background(opaqueCardColor()))
        } else {
            // 卡片的彩色晕染同样**预渲染一次**（不再每帧画两个大半径 radialGradient）
            BoxWithConstraints(Modifier.matchParentSize()) {
                val wPx = constraints.maxWidth
                val hPx = constraints.maxHeight
                val bmp = remember(wPx, hPx, g.isDark) { renderCard(wPx, hPx, g) }
                if (bmp != null) {
                    Image(bitmap = bmp, contentDescription = null, modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.FillBounds)
                }
            }
            // 3) 高光边
            Box(
                Modifier.matchParentSize().border(
                    width = 1.dp,
                    brush = Brush.verticalGradient(
                        0f to g.cardHighlightTop,
                        0.45f to g.cardHighlightMid,
                        1f to g.cardHighlightBottom,
                    ),
                    shape = shape,
                ),
            )
        }
        Box(Modifier.padding(contentPadding), content = content)
    }
}
