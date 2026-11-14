package dev.xalor.kdkit.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.SettingsBrightness
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.kyant.shapes.Capsule
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.BaseFeature
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.ui.theme.UiPrefs
import io.github.neoruaa.glasmio.core.GlassColors
import io.github.neoruaa.glasmio.core.GlasmioTheme
import io.github.neoruaa.glasmio.core.IosTypography
import io.github.neoruaa.glasmio.glass.GlasmioBackdropHost
import io.github.neoruaa.glasmio.preference.GlasmioSwitchPreference
import io.github.neoruaa.glasmio.ui.GlasmioGroupedList
import io.github.neoruaa.glasmio.ui.GlasmioSectionTitle
import io.github.neoruaa.glasmio.ui.GlasmioTextField
import kotlinx.coroutines.launch

/**
 * 设置页：Glasmio 分组列表 + 液态玻璃悬浮底栏。
 *
 * 关键约束（Glasmio 的硬要求）：**玻璃必须画在它采样的内容之外**。
 * 所以 `GlasmioBackdropHost` 里 sampledContent 是列表，overlayContent 才是底栏；
 * 顺序反了会自己采样自己（玻璃发黑/闪烁）。
 *
 * `glass = false` 时不建 host，直接普通 Box —— 避免在模拟器/弱 GPU 上碰到 native 渲染通道。
 */
@Composable
fun SettingsPage(
    mode: String,
    glass: Boolean,
    onCycleTheme: () -> Unit,
    onToggleGlass: () -> Unit,
    onOpenAbout: () -> Unit,
) {
    if (glass) {
        GlasmioBackdropHost(
            modifier = Modifier.fillMaxSize(),
            sampledContent = { },
        ) { backdrop ->
            SettingsBody(mode, true, onCycleTheme, onToggleGlass, onOpenAbout, backdrop)
        }
    } else {
        Box(Modifier.fillMaxSize()) {
            SettingsBody(mode, false, onCycleTheme, onToggleGlass, onOpenAbout, null)
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.BoxScope.SettingsBody(
    mode: String,
    glass: Boolean,
    onCycleTheme: () -> Unit,
    onToggleGlass: () -> Unit,
    onOpenAbout: () -> Unit,
    backdrop: io.github.neoruaa.glasmio.glass.render.Backdrop?,
) {
    val ctx = LocalContext.current
    val colors = GlasmioTheme.colors
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    var version by remember { mutableStateOf(0) }
    var query by remember { mutableStateOf("") }
    val expanded = remember { mutableStateOf<Set<String>>(emptySet()) }
    val all = FeatureRegistry.all
    val enabledCount = remember(version) { all.count { KdConfig.isOn(it.id, it.defaultOn) } }
    val searching = query.isNotBlank()
    val filtered = remember(query, version) {
        val q = query.trim().lowercase()
        if (q.isEmpty()) emptyList() else all.filter { f ->
            val c = SettingsCopy.of(f.id)
            (c?.label ?: f.title).lowercase().contains(q) ||
                (c?.blurb ?: f.summary).lowercase().contains(q) || f.id.contains(q)
        }
    }
    val groupTop = remember(version) {
        buildMap {
            var idx = 1
            for (g in Group.values()) {
                if (SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }.isEmpty()) continue
                put(g, idx++)
            }
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        SettingsHeader(mode, enabledCount, all.size, glass, onCycleTheme, onToggleGlass, onOpenAbout)
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 130.dp),
        ) {
            item(key = "search") {
                GlasmioTextField(
                    value = query,
                    onValueChange = { query = it },
                    placeholder = "搜索功能",
                    modifier = Modifier.padding(vertical = 6.dp),
                )
            }
            if (searching) {
                if (filtered.isEmpty()) {
                    item(key = "empty") {
                        Text("没有匹配的功能", style = IosTypography.subheadline,
                            color = colors.secondaryContent, modifier = Modifier.padding(16.dp))
                    }
                } else {
                    item(key = "search_list") {
                        FeatureGroup(filtered, version, expanded) { version++ }
                    }
                }
            } else {
                for (g in Group.values()) {
                    val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
                    if (items.isEmpty()) continue
                    item(key = "t_${g.id}") {
                        GroupHeader(g, items.count { KdConfig.isOn(it.id, it.defaultOn) }, items.size) { want ->
                            items.forEach { KdConfig.setApp(ctx, it.id, want) }
                            version++
                        }
                    }
                    item(key = "c_${g.id}") {
                        FeatureGroup(items, version, expanded) { version++ }
                    }
                }
                item(key = "bulk") { BulkActions { version++ } }
            }
        }
    }

    if (glass) {
        LiquidDock(
            selected = Group.ADS,
            onSelect = { g -> scope.launch { listState.animateScrollToItem(groupTop[g] ?: 0) } },
            glass = true,
            backdrop = backdrop,
            modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding(),
        )
    }
}

@Composable
private fun SettingsHeader(
    mode: String, enabled: Int, total: Int, glass: Boolean,
    onCycleTheme: () -> Unit, onToggleGlass: () -> Unit, onOpenAbout: () -> Unit,
) {
    val colors = GlasmioTheme.colors
    Row(
        Modifier.fillMaxWidth().padding(start = 20.dp, end = 14.dp, top = 10.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("KdKit", style = IosTypography.largeTitle, fontWeight = FontWeight.Bold, color = colors.content)
            Text("已启用 $enabled / $total · 快对 " + dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME,
                style = IosTypography.subheadline, color = colors.secondaryContent)
        }
        RoundIcon(
            when (mode) {
                UiPrefs.THEME_DARK -> Icons.Default.DarkMode
                UiPrefs.THEME_LIGHT -> Icons.Default.LightMode
                else -> Icons.Default.SettingsBrightness
            },
            "主题：${UiPrefs.label(mode)}",
            if (mode == UiPrefs.THEME_DARK) colors.accent else colors.secondaryContent,
            onCycleTheme,
        )
        Spacer(Modifier.width(4.dp))
        RoundIcon(Icons.Default.SettingsBrightness, if (glass) "液态玻璃：开" else "液态玻璃：关",
            if (glass) colors.accent else colors.tertiaryContent, onToggleGlass)
        Spacer(Modifier.width(4.dp))
        RoundIcon(Icons.Default.Info, "关于与更新", colors.secondaryContent, onOpenAbout)
    }
}

@Composable
private fun RoundIcon(icon: ImageVector, desc: String, tint: Color, onClick: () -> Unit) {
    val colors = GlasmioTheme.colors
    Box(
        Modifier.size(38.dp).clip(Capsule())
            .background(colors.container.copy(alpha = if (colors.isDark) 0.55f else 0.75f))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, desc, tint = tint, modifier = Modifier.size(19.dp)) }
}

@Composable
private fun GroupHeader(g: Group, on: Int, total: Int, onAll: (Boolean) -> Unit) {
    val colors = GlasmioTheme.colors
    Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.weight(1f)) { GlasmioSectionTitle("${g.label}  $on/$total") }
        SmallAction("全开", colors.accent) { onAll(true) }
        SmallAction("全关", colors.secondaryContent) { onAll(false) }
    }
}

@Composable
private fun SmallAction(label: String, tint: Color, onClick: () -> Unit) {
    Text(label, style = IosTypography.caption1, color = tint,
        modifier = Modifier.clip(Capsule()).clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp))
}

@Composable
private fun FeatureGroup(
    features: List<BaseFeature>,
    version: Int,
    expanded: MutableState<Set<String>>,
    onVersion: () -> Unit,
) {
    val ctx = LocalContext.current
    GlasmioGroupedList {
        features.forEachIndexed { index, f ->
            val copy = SettingsCopy.of(f.id)
            val checked = remember(version, f.id) { KdConfig.isOn(f.id, f.defaultOn) }
            val open = f.id in expanded.value
            GlasmioSwitchPreference(
                title = { Text(copy?.label ?: f.title, style = IosTypography.body) },
                description = copy?.blurb ?: f.summary,
                checked = checked,
                onCheckedChange = { v -> KdConfig.setApp(ctx, f.id, v); onVersion() },
                showTopSeparator = index > 0,
            )
            if (open) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                    Text("${f.id} · ${if (f.hot) "即时生效" else "需重启快对"}",
                        style = IosTypography.caption2, color = GlasmioTheme.colors.tertiaryContent)
                }
            }
        }
    }
}

@Composable
private fun BulkActions(onVersion: () -> Unit) {
    val ctx = LocalContext.current
    val all = FeatureRegistry.all
    val colors = GlasmioTheme.colors
    Row(Modifier.fillMaxWidth().padding(top = 16.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        SmallAction("开启推荐配置", colors.accent) {
            all.forEach { KdConfig.setApp(ctx, it.id, it.defaultOn) }
            onVersion()
        }
        SmallAction("关闭全部诊断", colors.secondaryContent) {
            SettingsCopy.items(Group.DIAG).forEach { KdConfig.setApp(ctx, it.id, false) }
            onVersion()
        }
    }
}
