package dev.xalor.kdkit.ui

import android.os.Build
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlurEffect
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.graphicsLayer
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

    Box(modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            drawRect(
                brush = Brush.verticalGradient(0f to g.bgTop, 0.6f to g.bgBottom, 1f to bottom),
            )
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(g.bgBlob1, Color.Transparent),
                    center = Offset(size.width * 0.16f, size.height * 0.10f),
                    radius = size.minDimension * 0.8f,
                ),
                radius = size.minDimension * 0.8f,
                center = Offset(size.width * 0.16f, size.height * 0.10f),
            )
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(g.bgBlob2, Color.Transparent),
                    center = Offset(size.width * 0.88f, size.height * 0.58f),
                    radius = size.minDimension * 0.75f,
                ),
                radius = size.minDimension * 0.75f,
                center = Offset(size.width * 0.88f, size.height * 0.58f),
            )
            // 细噪点：给模糊层提供高频细节
            val dot = if (g.isDark) Color(0x14FFFFFF) else Color(0x12000000)
            var y = 0f
            while (y < size.height) {
                var x = (y * 0.7f) % 6f
                while (x < size.width) {
                    drawCircle(dot, radius = 0.9f, center = Offset(x, y))
                    x += 6f
                }
                y += 6f
            }
        }
        content()
    }
}

/**
 * 液态玻璃卡：**模糊的彩色晕染底层 + 半透明填充 + 双色高光边 + 柔和外阴影**。
 *
 * 结构（自下而上）：
 *  1. 背景层：渐变填充 + 两团彩色光斑（这是"液态"的颜色来源）；
 *  2. 模糊层：对 1 施加 [BlurEffect]（API 31+；低版本自动退化成不糊，视觉仍成立）；
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
            // 1) 彩色晕染底层（会在下一步被模糊）
            Canvas(Modifier.matchParentSize()) {
                drawRect(Brush.verticalGradient(listOf(g.cardFillTop, g.cardFillBottom)))
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(g.cardTint1, Color.Transparent),
                        center = Offset(size.width * 0.12f, 0f),
                        radius = size.maxDimension * 0.9f,
                    ),
                    radius = size.maxDimension * 0.9f,
                    center = Offset(size.width * 0.12f, 0f),
                )
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(g.cardTint2, Color.Transparent),
                        center = Offset(size.width * 0.95f, size.height),
                        radius = size.maxDimension * 0.85f,
                    ),
                    radius = size.maxDimension * 0.85f,
                    center = Offset(size.width * 0.95f, size.height),
                )
            }
            // 2) 模糊层（只糊上面那层绘制，不糊内容）
            Box(
                Modifier.matchParentSize().graphicsLayer {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                        renderEffect = BlurEffect(blurPx, blurPx, TileMode.Clamp)
                    }
                },
            ) {
                Canvas(Modifier.matchParentSize()) {
                    drawRect(Brush.verticalGradient(listOf(g.cardFillTop, g.cardFillBottom)))
                    drawCircle(
                        brush = Brush.radialGradient(
                            colors = listOf(g.cardTint1, Color.Transparent),
                            center = Offset(size.width * 0.12f, 0f),
                            radius = size.maxDimension * 0.9f,
                        ),
                        radius = size.maxDimension * 0.9f,
                        center = Offset(size.width * 0.12f, 0f),
                    )
                    drawCircle(
                        brush = Brush.radialGradient(
                            colors = listOf(g.cardTint2, Color.Transparent),
                            center = Offset(size.width * 0.95f, size.height),
                            radius = size.maxDimension * 0.85f,
                        ),
                        radius = size.maxDimension * 0.85f,
                        center = Offset(size.width * 0.95f, size.height),
                    )
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
