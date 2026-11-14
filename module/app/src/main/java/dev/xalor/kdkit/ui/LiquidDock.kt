package dev.xalor.kdkit.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.kyant.shapes.Capsule
import io.github.neoruaa.glasmio.core.GlasmioTheme
import io.github.neoruaa.glasmio.core.IosTypography
import io.github.neoruaa.glasmio.glass.LocalGlassBackdrop
import io.github.neoruaa.glasmio.glass.render.Backdrop
import io.github.neoruaa.glasmio.glass.render.backdrops.layerBackdrop
import io.github.neoruaa.glasmio.glass.render.backdrops.rememberCombinedBackdrop
import io.github.neoruaa.glasmio.glass.render.backdrops.rememberLayerBackdrop
import io.github.neoruaa.glasmio.glass.render.drawBackdrop
import io.github.neoruaa.glasmio.glass.render.effects.blur
import io.github.neoruaa.glasmio.glass.render.effects.lens
import io.github.neoruaa.glasmio.glass.render.effects.vibrancy
import io.github.neoruaa.glasmio.glass.render.highlight.Highlight
import io.github.neoruaa.glasmio.glass.render.shadow.InnerShadow
import io.github.neoruaa.glasmio.glass.render.shadow.Shadow
import kotlinx.coroutines.launch
import kotlin.math.round

private enum class DockTab(val group: Group, val icon: ImageVector, val label: String) {
    Ads(Group.ADS, Icons.Default.Block, "去广告"),
    Content(Group.CONTENT, Icons.Default.Tune, "内容"),
    Look(Group.LOOK, Icons.Default.Palette, "外观"),
    Diag(Group.DIAG, Icons.Default.BugReport, "诊断"),
}

/**
 * 液态玻璃悬浮底栏 —— 三层结构照抄 murexide-plus 的 `LiquidBottomTabs`
 * （那份改编自 Kyant 的 AndroidLiquidGlass，Apache-2.0）。
 *
 * `glass = false` 时不建任何 backdrop、不调用 drawBackdrop —— 只画一个实色胶囊。
 * 这一条很重要：模拟器/弱 GPU 上 glasmio-glass 的 native 通道会 SIGSEGV，
 * 只要碰到 drawBackdrop 就崩，所以关玻璃必须是"完全不碰渲染通道"，不是"少画一点"。
 */
@Composable
fun LiquidDock(
    selected: Group,
    onSelect: (Group) -> Unit,
    glass: Boolean,
    modifier: Modifier = Modifier,
    backdrop: Backdrop? = null,
) {
    val tabs = remember { DockTab.entries }
    val scope = rememberCoroutineScope()
    val density = LocalDensity.current
    val isLtr = LocalLayoutDirection.current == LayoutDirection.Ltr
    val colors = GlasmioTheme.colors
    val index = remember { Animatable(selected.ordinal.toFloat()) }
    var pressed by remember { mutableStateOf(false) }
    val press = if (pressed) 1f else 0f
    val effective = glass && backdrop != null

    LaunchedEffect(selected) {
        val target = selected.ordinal.toFloat()
        if (index.value != target) index.animateTo(target, spring(dampingRatio = 1f, stiffness = 500f))
    }

    BoxWithConstraints(modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 10.dp)) {
        val tabWidth = with(density) { (constraints.maxWidth.toFloat() - 8.dp.toPx()) / tabs.size }

        Row(
            Modifier.fillMaxWidth().height(64.dp)
                .then(
                    if (effective) Modifier.drawBackdrop(
                        backdrop = backdrop!!,
                        shape = { Capsule() },
                        effects = {
                            vibrancy()
                            blur(with(density) { 22.dp.toPx() })
                        },
                        highlight = { Highlight.Default },
                        shadow = { Shadow(radius = 8.dp, alpha = 0.16f) },
                        innerShadow = { InnerShadow(radius = 3.dp, alpha = 0.10f) },
                        onDrawSurface = {
                            drawRect(if (colors.isDark) Color(0xFF121212).copy(alpha = 0.55f)
                            else Color(0xFFFAFAFA).copy(alpha = 0.50f))
                        },
                    ) else Modifier
                )
                .then(if (!effective) Modifier else Modifier)
                .padding(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (!effective) {
                // 实色底：没有 backdrop 时的外观，避免整条不可见
                Box(Modifier.fillMaxSize().background(
                    if (colors.isDark) Color(0xFF1C1C1E).copy(alpha = 0.92f)
                    else Color(0xFFFFFFFF).copy(alpha = 0.92f)
                ))
            }
        }
        // 上面的 Row 只负责玻璃/底色，tab 单独画一层（保证顺序：底 → 内容 → 指示器）
        Row(
            Modifier.fillMaxWidth().height(64.dp).padding(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            tabs.forEach { tab ->
                DockTabButton(tab, selected == tab.group, true) { onSelect(tab.group) }
            }
        }

        if (effective) {
            Box(
                Modifier
                    .padding(horizontal = 4.dp, vertical = 4.dp)
                    .graphicsLayer {
                        translationX = if (isLtr) index.value * tabWidth
                        else size.width - (index.value + 1f) * tabWidth
                    }
                    .drawBackdrop(
                        backdrop = rememberCombinedBackdrop(backdrop!!, rememberLayerBackdrop()),
                        shape = { Capsule() },
                        effects = {
                            lens(
                                refractionHeight = with(density) { 10.dp.toPx() } * press,
                                refractionAmount = with(density) { 14.dp.toPx() } * press,
                                chromaticAberration = true,
                            )
                        },
                        highlight = { Highlight.Default.copy(alpha = press) },
                        shadow = { Shadow(alpha = press * 0.5f) },
                        innerShadow = { InnerShadow(radius = 8.dp * press, alpha = press) },
                        onDrawSurface = {
                            drawRect(if (colors.isDark) Color.White.copy(alpha = 0.10f)
                            else Color.Black.copy(alpha = 0.10f))
                        },
                    )
                    .height(56.dp)
                    .fillMaxWidth(1f / tabs.size)
                    .pointerInput(tabWidth) {
                        detectHorizontalDragGestures(
                            onDragStart = { pressed = true },
                            onDragEnd = {
                                pressed = false
                                val t = round(index.value).toInt().coerceIn(0, tabs.size - 1)
                                scope.launch { index.animateTo(t.toFloat(), spring(0.9f, 500f)) }
                                onSelect(tabs[t].group)
                            },
                            onDragCancel = {
                                pressed = false
                                val t = round(index.value).toInt().coerceIn(0, tabs.size - 1)
                                scope.launch { index.animateTo(t.toFloat(), spring(0.9f, 500f)) }
                            },
                        ) { change, drag ->
                            change.consume()
                            val delta = drag / tabWidth * (if (isLtr) 1f else -1f)
                            scope.launch {
                                index.snapTo((index.value + delta).coerceIn(0f, (tabs.size - 1).toFloat()))
                            }
                        }
                    },
            )
        }
    }
}

@Composable
private fun RowScope.DockTabButton(tab: DockTab, selected: Boolean, interactive: Boolean, onClick: () -> Unit) {
    val colors = GlasmioTheme.colors
    val tint = if (selected) colors.content else colors.secondaryContent
    Column(
        Modifier
            .then(
                if (interactive) Modifier.selectable(selected = selected, role = Role.Tab, onClick = onClick)
                else Modifier.semantics { this.selected = selected; contentDescription = tab.label }
            )
            .fillMaxHeight()
            .weight(1f),
        verticalArrangement = Arrangement.spacedBy(2.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(tab.icon, tab.label, tint = tint, modifier = Modifier.size(21.dp))
        Text(tab.label, style = IosTypography.caption, fontSize = 11.sp, color = tint)
    }
}
