package dev.xalor.kdkit.ui

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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import dev.xalor.kdkit.ui.theme.LocalGlass
import dev.xalor.kdkit.ui.theme.opaqueCardColor

/**
 * 液态玻璃背景 —— 两层纵向渐变 + 两块柔光斑（mesh 的廉价版）。
 *
 * 为什么不用真·壁纸采样模糊（proxyui / Glasmio 那条路）：
 *  * 那需要采样窗口背后的内容并逐帧重模糊，成本高、机型兼容差异大；
 *  * 设置页是全屏不透明场景，背景本来就由我们自己画 —— 画一层**本来就柔和**的渐变，
 *    玻璃卡再半透明叠上去，视觉上就是同一个"透光"效果，而不必真的去模糊什么。
 *  * 代价：不能透出桌面壁纸。这个取舍写在 `module/UI.md`。
 */
@Composable
fun GlassBackground(
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    val g = LocalGlass.current
    val top = if (g.isDark) Color(0xFF05060A) else Color(0xFFCBD3EA)

    Box(modifier.fillMaxSize()) {
        Canvas(Modifier.fillMaxSize()) {
            drawRect(
                brush = Brush.verticalGradient(
                    0f to g.bgTop,
                    0.55f to g.bgBottom,
                    1f to top,
                ),
            )
            // 两块柔光：左上偏蓝、右下偏暖 —— 玻璃卡的"高光"靠它们透出来。
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(g.bgBlob1, Color.Transparent),
                    center = Offset(size.width * 0.18f, size.height * 0.12f),
                    radius = size.minDimension * 0.75f,
                ),
                radius = size.minDimension * 0.75f,
                center = Offset(size.width * 0.18f, size.height * 0.12f),
            )
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(g.bgBlob2, Color.Transparent),
                    center = Offset(size.width * 0.86f, size.height * 0.62f),
                    radius = size.minDimension * 0.7f,
                ),
                radius = size.minDimension * 0.7f,
                center = Offset(size.width * 0.86f, size.height * 0.62f),
            )
        }
        content()
    }
}

/**
 * 玻璃卡：半透明填充 + 1dp 高光描边 + 柔和外阴影。
 *
 * @param glassOff 传 `false` 就是普通不透明卡（对应设置里的"液态玻璃"开关关掉），
 *                 这样切换时布局不会变，只是"透不透"变了。
 */
@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(22.dp),
    glassOff: Boolean = false,
    contentPadding: PaddingValues = PaddingValues(0.dp),
    elevation: Dp = 10.dp,
    content: @Composable BoxScope.() -> Unit,
) {
    val g = LocalGlass.current
    val fill = if (glassOff) {
        Brush.verticalGradient(listOf(opaqueCardColor(), opaqueCardColor()))
    } else {
        Brush.verticalGradient(listOf(g.cardFillTop, g.cardFillBottom))
    }
    val borderColor = if (glassOff) Color.Transparent else g.cardBorder

    Box(
        modifier = modifier
            .shadow(if (glassOff) 4.dp else elevation, shape, ambientColor = g.cardShadow, spotColor = g.cardShadow)
            .clip(shape)
            .background(fill, shape)
            .border(1.dp, borderColor, shape)
            .padding(contentPadding),
        content = content,
    )
}
