package dev.xalor.kdkit.ui.liquidglass

import androidx.compose.foundation.background
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

/**
 * 液态玻璃的**材质层**（纯色绘制，不用任何 shader / RenderEffect）。
 *
 * ### 为什么这么保守
 *
 * 真机 tombstone（Redmi M332BF / HyperOS V816 / Android 17）反复指向同一处：
 * ```
 * #00 libhwui.so (MiBackgroundBlurBlend::postUpdateInfo(TreeInfo&)+52)   ← SIGSEGV
 * #01 libhwui.so (RenderNode::prepareTreeImpl …)
 * ```
 * `MiBackgroundBlurBlend` 是小米在 libhwui 里的私有"背景模糊/合成"实现。实测结论：
 *  * Kyant 的 `drawBackdrop`（RenderEffect）→ 崩
 *  * Glasmio 的玻璃（RuntimeShader + RenderEffect）→ 崩
 *  * **`Modifier.shadow`** → 崩（合成阶段走同一个 node）
 *  * **任何 `Brush` 渐变**（包括给了有限坐标的）画在"被 clip + graphicsLayer 缩放"的层上 → 崩
 *  * 纯色 `drawRect` / `drawRoundRect` / `Stroke` → **稳**
 *
 * 所以玻璃的"厚度感"改用**多层纯色**堆出来，而不是渐变或模糊：
 *  1. 主体：半透明白（浅色）/ 半透明深灰（深色）
 *  2. 顶部高光：上半部分叠一层 +8% 白，模拟玻璃上缘的 specular
 *  3. 底缘压暗：下缘叠一层 -5% 黑，让下缘"沉下去"
 *  4. 1dp 描边：提亮轮廓
 *
 * 交互层（拖拽弹簧、按压放大、指示器形变）仍然保留 murexide 原版实现。
 */
fun Modifier.liquidGlassSurface(
    shape: Shape,
    light: Boolean,
): Modifier = this
    .clip(shape)
    .drawBehind {
        val r = CornerRadius(size.height / 2f, size.height / 2f)

        // ① 主体
        drawRoundRect(
            color = if (light) Color(0xFAF4F4F6) else Color(0xFA1C1C1E),
            cornerRadius = r,
        )
        // ② 上半高光：用**内嵌实色圆角矩形**模拟，不用 Brush
        //    （真机上任何渐变 Brush 都会让小米 libhwui 在 MiBackgroundBlurBlend 崩，
        //     例如 2026-11-15 10:51 那次；纯色多层是唯一稳的路子）
        val inset = 1.dp.toPx()
        drawRoundRect(
            color = if (light) Color(0x1FFFFFFF) else Color(0x1AFFFFFF),
            topLeft = Offset(inset, inset),
            size = Size(size.width - inset * 2, size.height * 0.46f),
            cornerRadius = r,
        )
        // ③ 下缘压暗
        drawRoundRect(
            color = Color.Black.copy(alpha = if (light) 0.05f else 0.10f),
            topLeft = Offset(0f, size.height * 0.72f),
            size = Size(size.width, size.height * 0.28f),
            cornerRadius = r,
        )
        // ④ 描边
        drawRoundRect(
            color = if (light) Color(0x33000000) else Color(0x33FFFFFF),
            cornerRadius = r,
            style = Stroke(width = 1.dp.toPx()),
        )
    }

/** 选中指示器：实色高光（不使用任何 Brush，避免踩到同一个 hwui 崩溃点）。 */
fun Modifier.liquidLensHighlight(progress: Float, light: Boolean): Modifier = this
    .background(
        if (light) Color.White.copy(alpha = 0.72f)
        else Color.White.copy(alpha = 0.22f),
    )
