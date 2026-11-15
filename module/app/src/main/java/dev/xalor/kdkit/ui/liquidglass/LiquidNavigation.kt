/*
 * Adapted from the AndroidLiquidGlass catalog application's LiquidBottomTabs.
 * Copyright 2025 Kyant. Licensed under the Apache License, Version 2.0.
 * Modified for Murexide; 材质层改为自绘（见 LiquidGlassMaterial.kt 里为什么不能用 RenderEffect）。
 */
package dev.xalor.kdkit.ui.liquidglass

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.EaseOut
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.fastCoerceIn
import androidx.compose.ui.util.lerp
import com.kyant.shapes.Capsule
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sign
import kotlinx.coroutines.launch

private val LocalLiquidNavigationScale = compositionLocalOf { { 1f } }

internal fun snapNavigationIndex(value: Float, tabsCount: Int): Int {
    require(tabsCount > 0) { "tabsCount 必须为正：$tabsCount" }
    return value.roundToInt().coerceIn(0, tabsCount - 1)
}

/**
 * 液态玻璃悬浮底栏。
 *
 * 结构与本地 `murexide-plus` 的 `LiquidBottomTabs`（Kyant AndroidLiquidGlass，Apache-2.0）一致：
 *
 *  * **拖拽**：`DampedDragAnimation` —— 弹簧状态机，跟手时更新目标值、松手吸附到最近 tab；
 *    拖动过程中整条栏还会按位移做 `panelOffset`（4dp 以内的 EaseOut 位移），这是"被手指带弯"的量感。
 *  * **按压高光**：`InteractiveHighlight` —— 按下处出现径向高光（AGSL 或纯色回退），
 *    并驱动指示器与整条栏的 scale。
 *  * **双通道内容**：`content(index, selected, overlayPass)` 同一份内容画两遍
 *    （下层的 alpha=0 版本给"透镜"当采样源，上层清晰版给用户看），保证像素级对齐。
 *  * **指示器**：跟随 `dragAnimation.value`，按压放大、按速度做各向异性拉伸。
 *
 * **材质层是自绘的**（`liquidGlassSurface`），不是 `drawBackdrop` ——
 * 原因写在 `LiquidGlassMaterial.kt`：小米这版 libhwui 在收到带 RenderEffect 的
 * RenderNode 时会 SIGSEGV（真机 tombstone：`MiBackgroundBlurBlend::postUpdateInfo`）。
 */
@Composable
fun LiquidBottomTabs(
    selectedTabIndex: Int,
    onTabSelected: (Int) -> Unit,
    tabsCount: Int,
    modifier: Modifier = Modifier,
    onTabLongClick: ((Int) -> Unit)? = null,
    onTabLongClickLabel: ((Int) -> String?)? = null,
    content: @Composable (index: Int, selected: Boolean, overlayPass: Boolean) -> Unit,
) {
    val isLightTheme = MaterialTheme.colorScheme.background.luminance() > 0.5f
    val containerColor = if (isLightTheme) {
        Color(0xFFFAFAFA).copy(alpha = 0.6f)
    } else {
        Color(0xFF121212).copy(alpha = 0.6f)
    }
    val navigationContentColor = liquidGlassContentColor(
        preferredColor = MaterialTheme.colorScheme.onSurfaceVariant,
        glassColor = containerColor,
        backgroundColor = MaterialTheme.colorScheme.background,
    )

    BoxWithConstraints(modifier, contentAlignment = Alignment.CenterStart) {
        val density = LocalDensity.current
        val tabWidth = with(density) {
            (constraints.maxWidth.toFloat() - 8.dp.toPx()) / tabsCount
        }
        val offsetAnimation = remember { Animatable(0f) }
        val panelOffset by remember(density) {
            derivedStateOf {
                val fraction = (offsetAnimation.value / constraints.maxWidth.coerceAtLeast(1))
                    .fastCoerceIn(-1f, 1f)
                with(density) { 4.dp.toPx() * fraction.sign * EaseOut.transform(abs(fraction)) }
            }
        }
        val isLtr = LocalLayoutDirection.current == LayoutDirection.Ltr
        val animationScope = rememberCoroutineScope()
        var currentIndex by remember { mutableIntStateOf(selectedTabIndex) }
        val dragAnimation = remember(animationScope, tabsCount) {
            DampedDragAnimation(
                animationScope = animationScope,
                initialValue = selectedTabIndex.toFloat(),
                valueRange = 0f..(tabsCount - 1).toFloat(),
                visibilityThreshold = 0.001f,
                initialScale = 1f,
                pressedScale = 78f / 56f,
                onDragStarted = {},
                onDragStopped = {
                    val target = snapNavigationIndex(targetValue, tabsCount)
                    currentIndex = target
                    animateToValue(target.toFloat())
                    onTabSelected(target)
                    animationScope.launch { offsetAnimation.animateTo(0f, spring(1f, 300f, 0.5f)) }
                },
                onDrag = { _, dragAmount ->
                    updateValue(
                        (targetValue + dragAmount.x / tabWidth * if (isLtr) 1f else -1f)
                            .fastCoerceIn(0f, (tabsCount - 1).toFloat()),
                    )
                    animationScope.launch { offsetAnimation.snapTo(offsetAnimation.value + dragAmount.x) }
                },
            )
        }
        LaunchedEffect(selectedTabIndex) {
            if (selectedTabIndex != currentIndex) {
                currentIndex = selectedTabIndex
                dragAnimation.animateToValue(selectedTabIndex.toFloat())
            }
        }
        // ① 本体：玻璃材质 + 按压时整体放大
        Row(
            Modifier
                .graphicsLayer {
                    translationX = panelOffset
                    val scale = lerp(1f, 1f + 16.dp.toPx() / size.width, dragAnimation.pressProgress)
                    scaleX = scale
                    scaleY = scale
                }
                .liquidGlassSurface(Capsule(), isLightTheme)
                .height(64.dp)
                .fillMaxWidth()
                .padding(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            repeat(tabsCount) { index ->
                LiquidBottomTab(
                    selected = currentIndex == index,
                    contentColor = navigationContentColor,
                    onClick = {
                        currentIndex = index
                        dragAnimation.animateToValue(index.toFloat())
                        onTabSelected(index)
                    },
                    onLongClick = onTabLongClick?.let { callback -> { callback(index) } },
                    onLongClickLabel = onTabLongClickLabel?.invoke(index),
                ) {
                    Box(Modifier.alpha(0f)) { content(index, currentIndex == index, true) }
                }
            }
        }

        // ② 清晰内容层
        Row(
            Modifier
                .padding(horizontal = 4.dp)
                .height(56.dp)
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            repeat(tabsCount) { index ->
                LiquidBottomTab(
                    selected = currentIndex == index,
                    contentColor = navigationContentColor,
                    onClick = {},
                    interactive = false,
                ) {
                    content(index, currentIndex == index, false)
                }
            }
        }

        // ③ 选中指示器
        Box(
            Modifier
                .padding(horizontal = 4.dp)
                .graphicsLayer {
                    translationX = if (isLtr) {
                        dragAnimation.value * tabWidth + panelOffset
                    } else {
                        size.width - (dragAnimation.value + 1f) * tabWidth + panelOffset
                    }
                }
                .then(dragAnimation.modifier)
                .liquidGlassIndicator(
                    progress = dragAnimation.pressProgress,
                    light = isLightTheme,
                    scaleX = dragAnimation.scaleX,
                    scaleY = dragAnimation.scaleY,
                    velocity = dragAnimation.velocity,
                )
                .height(56.dp)
                .fillMaxWidth(1f / tabsCount),
        )
    }
}

/** 指示器材质：按压放大 + 速度拉伸 + 内层高光（替代原来的 lens/Highlight/Shadow）。 */
private fun Modifier.liquidGlassIndicator(
    progress: Float,
    light: Boolean,
    scaleX: Float,
    scaleY: Float,
    velocity: Float,
): Modifier = this
    .graphicsLayer {
        this.scaleX = scaleX
        this.scaleY = scaleY
        val v = velocity / 10f
        this.scaleX /= 1f - (v * 0.75f).fastCoerceIn(-0.2f, 0.2f)
        this.scaleY *= 1f - (v * 0.25f).fastCoerceIn(-0.2f, 0.2f)
    }
    .clip(Capsule())
    .liquidLensHighlight(progress, light)
    .border(1.dp, Color.White.copy(alpha = 0.30f + 0.24f * progress), Capsule())

@Composable
private fun androidx.compose.foundation.layout.RowScope.LiquidBottomTab(
    selected: Boolean,
    contentColor: Color,
    onClick: () -> Unit,
    onLongClick: (() -> Unit)? = null,
    onLongClickLabel: String? = null,
    interactive: Boolean = true,
    content: @Composable () -> Unit,
) {
    val scale = LocalLiquidNavigationScale.current
    Column(
        Modifier
            .then(if (interactive) Modifier.clip(Capsule()) else Modifier)
            .then(
                if (interactive) {
                    Modifier.combinedClickable(
                        onClick = onClick,
                        onLongClick = onLongClick,
                        onLongClickLabel = onLongClickLabel,
                    )
                } else {
                    Modifier
                },
            )
            .then(
                if (interactive) {
                    Modifier.semantics {
                        this.selected = selected
                        role = Role.Tab
                    }
                } else {
                    Modifier
                },
            )
            .fillMaxHeight()
            .weight(1f)
            .graphicsLayer {
                scaleX = scale()
                scaleY = scale()
            },
        verticalArrangement = Arrangement.spacedBy(2.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CompositionLocalProvider(LocalContentColor provides contentColor) {
            content()
        }
    }
}

private fun Color.luminance(): Float =
    (0.2126f * red) + (0.7152f * green) + (0.0722f * blue)
