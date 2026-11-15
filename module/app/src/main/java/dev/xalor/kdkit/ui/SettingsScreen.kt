package dev.xalor.kdkit.ui

import androidx.compose.animation.core.animateDpAsState
import kotlinx.coroutines.launch
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.SettingsBrightness
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.BaseFeature
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.ui.theme.LocalIos
import dev.xalor.kdkit.ui.theme.UiPrefs

private val CardRadius = 16.dp
private val RowHPad = 16.dp
private val DockHeight = 64.dp

/**
 * 设置页 —— 自己画的 iOS 分组列表（不依赖 miuix / HyperChanger / Glasmio）。
 *
 * 为什么会走到这一步：Glasmio 的玻璃在模拟器上 SIGSEGV、在你真机上整页白屏，
 * 两次跨设备验证都失败。组件库不能用，就自己画 —— 视觉目标是 iOS 设置页：
 * 大标题 + 灰底 + 白卡片 + inset 分隔线 + 蓝色开关 + 悬浮胶囊底栏。
 *
 * 性能：LazyColumn + 每行独立状态（`mutableStateMapOf`）。点一个开关只重组那一行，
 * 不再有"整页 41 行一起重组"的情况；也没有任何模糊/着色器。
 */
@Composable
fun SettingsScreen(
    mode: String,
    onCycleTheme: () -> Unit,
    onOpenAbout: () -> Unit,
) {
    val ios = LocalIos.current
    val ctx = LocalContext.current
    val all = remember { FeatureRegistry.all }
    val listState = rememberLazyListState()
    val states = remember {
        mutableStateMapOf<String, Boolean>().apply {
            all.forEach { put(it.id, KdConfig.isOn(it.id, it.defaultOn)) }
        }
    }
    val enabled by remember { derivedStateOf { states.count { it.value } } }
    var query by remember { mutableStateOf("") }
    fun set(id: String, on: Boolean) {
        states[id] = on
        KdConfig.setApp(ctx, id, on)
    }

    Box(Modifier.fillMaxSize().background(ios.groupedBg)) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize().statusBarsPadding(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 108.dp),
        ) {
            item(key = "h") { Header(mode, enabled, all.size, ios, onCycleTheme, onOpenAbout) }
            item(key = "s") { SearchField(query, { query = it }, ios) }

            val q = query.trim().lowercase()
            if (q.isNotEmpty()) {
                val hits = all.filter { f ->
                    val c = SettingsCopy.of(f.id)
                    (c?.label ?: f.title).lowercase().contains(q) ||
                        (c?.blurb ?: f.summary).lowercase().contains(q) ||
                        f.id.contains(q)
                }
                if (hits.isEmpty()) {
                    item(key = "none") {
                        Text("没有匹配的功能", fontSize = 13.sp, color = ios.secondary,
                            modifier = Modifier.padding(vertical = 24.dp))
                    }
                } else {
                    item(key = "res") { Card(hits, states, ios) { id, on -> set(id, on) } }
                }
            } else {
                for (g in Group.values()) {
                    val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
                    if (items.isEmpty()) continue
                    item(key = "t_${g.id}") {
                        val on by remember { derivedStateOf { items.count { states[it.id] == true } } }
                        GroupHeader(g, on, items.size, ios) { want -> items.forEach { set(it.id, want) } }
                    }
                    item(key = "c_${g.id}") { Card(items, states, ios) { id, on -> set(id, on) } }
                }
                item(key = "bulk") {
                    Row(Modifier.padding(top = 18.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Pill("开启推荐配置", ios.accent) {
                            all.filter { SettingsCopy.of(it.id)?.group?.recommended != false }
                                .forEach { set(it.id, it.defaultOn) }
                        }
                        Pill("关闭全部诊断", ios.secondary) {
                            SettingsCopy.items(Group.DIAG).forEach { set(it.id, false) }
                        }
                    }
                }
            }
        }

        val scope = androidx.compose.runtime.rememberCoroutineScope()
        Dock(ios, onSelect = { g ->
            val idx = runCatching {
                var n = 1
                for (gg in Group.values()) {
                    if (SettingsCopy.items(gg).mapNotNull { FeatureRegistry.byId(it.id) }.isEmpty()) continue
                    if (gg == g) break
                    n += 2
                }
                n
            }.getOrDefault(1)
            scope.launch { listState.animateScrollToItem(idx) }
        }, Modifier.align(Alignment.BottomCenter).navigationBarsPadding())
    }
}

@Composable
private fun Header(
    mode: String, enabled: Int, total: Int,
    ios: dev.xalor.kdkit.ui.theme.IosColors,
    onCycleTheme: () -> Unit, onOpenAbout: () -> Unit,
) {
    Column(Modifier.padding(top = 8.dp, bottom = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("KdKit", fontSize = 34.sp, fontWeight = FontWeight.Bold, color = ios.content)
                Text("已启用 $enabled / $total · 快对 " + dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME,
                    fontSize = 13.sp, color = ios.secondary)
            }
            CircleButton(
                when (mode) {
                    UiPrefs.THEME_DARK -> Icons.Default.DarkMode
                    UiPrefs.THEME_LIGHT -> Icons.Default.LightMode
                    else -> Icons.Default.SettingsBrightness
                },
                "主题：${UiPrefs.label(mode)}", ios, onCycleTheme,
            )
            Spacer(Modifier.width(8.dp))
            CircleButton(Icons.Default.SettingsBrightness, "关于与更新", ios, onOpenAbout)
        }
    }
}

@Composable
private fun CircleButton(icon: ImageVector, desc: String,
                         ios: dev.xalor.kdkit.ui.theme.IosColors, onClick: () -> Unit) {
    Box(
        Modifier.size(38.dp).clip(RoundedCornerShape(50)).background(ios.card)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, desc, tint = ios.accent, modifier = Modifier.size(19.dp)) }
}

@Composable
private fun SearchField(query: String, onChange: (String) -> Unit,
                        ios: dev.xalor.kdkit.ui.theme.IosColors) {
    Box(
        Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 6.dp).height(38.dp)
            .clip(RoundedCornerShape(10.dp)).background(ios.card),
        contentAlignment = Alignment.CenterStart,
    ) {
        BasicTextField(
            value = query, onValueChange = onChange, singleLine = true,
            textStyle = TextStyle(fontSize = 15.sp, color = ios.content),
            cursorBrush = SolidColor(ios.accent),
            decorationBox = { inner ->
                Box(Modifier.fillMaxSize().padding(horizontal = 12.dp), contentAlignment = Alignment.CenterStart) {
                    if (query.isEmpty()) Text("搜索功能", fontSize = 15.sp, color = ios.tertiary)
                    inner()
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun GroupHeader(g: Group, on: Int, total: Int,
                        ios: dev.xalor.kdkit.ui.theme.IosColors, onAll: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(top = 18.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text("${g.label}   $on/$total", fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            color = ios.secondary, modifier = Modifier.weight(1f))
        Text("全开", fontSize = 12.sp, color = ios.accent,
            modifier = Modifier.clickable { onAll(true) }.padding(start = 10.dp, top = 4.dp, bottom = 4.dp))
        Text("全关", fontSize = 12.sp, color = ios.secondary,
            modifier = Modifier.clickable { onAll(false) }.padding(start = 10.dp, top = 4.dp, bottom = 4.dp))
    }
}

@Composable
private fun Pill(label: String, tint: Color, onClick: () -> Unit) {
    Text(label, fontSize = 12.sp, color = tint,
        modifier = Modifier.clip(RoundedCornerShape(50))
            .background(LocalIos.current.card)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp))
}

@Composable
private fun Card(
    features: List<BaseFeature>,
    states: androidx.compose.runtime.snapshots.SnapshotStateMap<String, Boolean>,
    ios: dev.xalor.kdkit.ui.theme.IosColors,
    onChange: (String, Boolean) -> Unit,
) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(CardRadius)).background(ios.card)) {
        features.forEachIndexed { index, f ->
            RowItem(f, states[f.id] == true, ios, showDivider = index > 0) { v -> onChange(f.id, v) }
        }
    }
}

@Composable
private fun RowItem(
    f: BaseFeature, checked: Boolean,
    ios: dev.xalor.kdkit.ui.theme.IosColors,
    showDivider: Boolean, onCheckedChange: (Boolean) -> Unit,
) {
    val copy = SettingsCopy.of(f.id)
    Column {
        if (showDivider) {
            Box(Modifier.fillMaxWidth().padding(start = RowHPad).height(1.dp).background(ios.separator))
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = RowHPad, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(copy?.label ?: f.title, fontSize = 16.sp, color = ios.content)
                Text(copy?.blurb ?: f.summary, fontSize = 12.sp, color = ios.secondary)
            }
            Switch(
                checked = checked, onCheckedChange = onCheckedChange,
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Color.White,
                    checkedTrackColor = ios.accent,
                    uncheckedThumbColor = Color.White,
                    uncheckedTrackColor = ios.tertiary,
                ),
            )
        }
    }
}

@Composable
private fun Dock(
    ios: dev.xalor.kdkit.ui.theme.IosColors,
    onSelect: (Group) -> Unit,
    modifier: Modifier = Modifier,
) {
    val tabs = remember {
        listOf(
            Triple(Group.ADS, Icons.Default.Block, "去广告"),
            Triple(Group.CONTENT, Icons.Default.Tune, "内容"),
            Triple(Group.LOOK, Icons.Default.Palette, "外观"),
            Triple(Group.DIAG, Icons.Default.BugReport, "诊断"),
        )
    }
    var current by remember { mutableStateOf(0) }
    Row(
        modifier.padding(horizontal = 24.dp, vertical = 10.dp).fillMaxWidth().height(DockHeight)
            .clip(RoundedCornerShape(50)).background(ios.dock)
            .border(1.dp, ios.dockBorder, RoundedCornerShape(50)),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        tabs.forEachIndexed { i, (group, icon, label) ->
            val selected = current == i
            val tint = if (selected) ios.accent else ios.secondary
            Column(
                Modifier.weight(1f).fillMaxSize().clickable {
                    current = i
                    onSelect(group)
                }, 
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(icon, label, tint = tint, modifier = Modifier.size(20.dp))
                Text(label, fontSize = 10.sp, color = tint)
            }
        }
    }
}


