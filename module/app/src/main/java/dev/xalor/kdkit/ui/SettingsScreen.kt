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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.BaseFeature
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.ui.liquidglass.LiquidBottomTabs
import dev.xalor.kdkit.ui.theme.UiPrefs
import kotlinx.coroutines.launch
import top.yukonga.miuix.kmp.basic.Card
import top.yukonga.miuix.kmp.basic.SmallTitle
import top.yukonga.miuix.kmp.preference.ArrowPreference
import top.yukonga.miuix.kmp.preference.SwitchPreference
import top.yukonga.miuix.kmp.theme.MiuixTheme

/** 底栏四个入口，顺序即屏幕顺序。 */
private val DockIcons = listOf(
    Icons.Default.Block to "去广告",
    Icons.Default.Tune to "内容",
    Icons.Default.Palette to "外观",
    Icons.Default.BugReport to "诊断",
)
private val DockGroups = listOf(Group.ADS, Group.CONTENT, Group.LOOK, Group.DIAG)

/**
 * 设置页：**Miuix** 列表 + **液态玻璃悬浮底栏**。
 *
 * 底栏是 `liquidglass/LiquidNavigation.kt` 里的 `LiquidBottomTabs` —— 从本地
 * `murexide-plus` 的 `ui/theme/liquidglass/` 原样搬过来的（Kyant AndroidLiquidGlass，Apache-2.0），
 * 连四层结构、拖拽弹簧、按压高光、透镜色散都没改。
 *
 * @param backdrop 由 MainActivity 提供的可采样背景；为 null 时底栏退化成纯色
 */
@Composable
fun SettingsScreen(
    mode: String,
    onCycleTheme: () -> Unit,
    onOpenAbout: () -> Unit,
) {
    val ctx = LocalContext.current
    val all = remember { FeatureRegistry.all }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val states = remember {
        mutableStateMapOf<String, Boolean>().apply {
            all.forEach { put(it.id, KdConfig.isOn(it.id, it.defaultOn)) }
        }
    }
    val enabled by remember { derivedStateOf { states.count { it.value } } }
    var query by remember { mutableStateOf("") }
    var currentTab by remember { mutableStateOf(0) }

    fun set(id: String, on: Boolean) {
        states[id] = on
        KdConfig.setApp(ctx, id, on)
    }

    // 每个分组的列表下标（搜索项占 1 项，每分组 = 标题 + 卡片）
    val groupTop = remember {
        buildMap {
            var idx = 1
            for (g in Group.values()) {
                if (SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }.isEmpty()) continue
                put(g, idx); idx += 2
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize().statusBarsPadding(),
            // 底部留出底栏高度 + 余量，最后一行不会被压住
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 150.dp),
        ) {
            item(key = "header") {
                Column(Modifier.padding(start = 6.dp, top = 10.dp)) {
                    Text("KdKit", fontSize = 30.sp, fontWeight = FontWeight.Bold)
                    Text(
                        "已启用 $enabled / ${all.size} · 快对 " +
                            dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME,
                        fontSize = 12.sp, color = MiuixTheme.colorScheme.onSurfaceVariantSummary,
                    )
                }
            }
            item(key = "appearance") {
                SmallTitle("外观")
                Card {
                    ArrowPreference(
                        title = "主题",
                        summary = UiPrefs.label(mode),
                        onClick = onCycleTheme,
                    )
                    ArrowPreference(title = "关于与更新", summary = null, onClick = onOpenAbout)
                }
            }

            val q = query.trim().lowercase()
            if (q.isNotEmpty()) {
                val hits = all.filter { f ->
                    val c = SettingsCopy.of(f.id)
                    (c?.label ?: f.title).lowercase().contains(q) ||
                        (c?.blurb ?: f.summary).lowercase().contains(q) || f.id.contains(q)
                }
                item(key = "search_result") {
                    SmallTitle("搜索结果（${hits.size}）")
                    Card {
                        hits.forEach { f -> FeatureRow(f, states[f.id] == true) { v -> set(f.id, v) } }
                    }
                }
            } else {
                for (g in Group.values()) {
                    val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
                    if (items.isEmpty()) continue
                    item(key = "t_${g.id}") {
                        val on by remember { derivedStateOf { items.count { states[it.id] == true } } }
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.weight(1f)) { SmallTitle("${g.label}  $on/${items.size}") }
                            Text(
                                "全开", fontSize = 12.sp, color = MiuixTheme.colorScheme.primary,
                                modifier = Modifier
                                    .padding(end = 6.dp)
                                    .clickableCompat { items.forEach { set(it.id, true) } }
                                    .padding(4.dp),
                            )
                            Text(
                                "全关", fontSize = 12.sp,
                                color = MiuixTheme.colorScheme.onSurfaceVariantSummary,
                                modifier = Modifier
                                    .padding(end = 18.dp)
                                    .clickableCompat { items.forEach { set(it.id, false) } }
                                    .padding(4.dp),
                            )
                        }
                    }
                    item(key = "c_${g.id}") {
                        Card {
                            items.forEach { f -> FeatureRow(f, states[f.id] == true) { v -> set(f.id, v) } }
                        }
                    }
                }
            }
        }

        // 液态玻璃悬浮底栏：只有拿到 backdrop 才画玻璃，否则退化成普通胶囊
        if (true) {
            LiquidBottomTabs(
                selectedTabIndex = currentTab,
                onTabSelected = { i ->
                    currentTab = i
                    val target = groupTop[DockGroups[i]] ?: 0
                    scope.launch { listState.animateScrollToItem(target) }
                },
                tabsCount = DockIcons.size,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .navigationBarsPadding()
                    .padding(horizontal = 20.dp, vertical = 10.dp)
                    .fillMaxWidth(),
            ) { index, selected, overflowPass ->
                DockItem(index, selected, overflowPass)
            }
        }
    }
}

@Composable
private fun DockItem(index: Int, selected: Boolean, overlayPass: Boolean) {
    val (icon, label) = DockIcons[index]
    val tint = if (selected) {
        MiuixTheme.colorScheme.primary
    } else {
        MiuixTheme.colorScheme.onSurfaceVariantSummary
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Icon(icon, label, tint = tint, modifier = Modifier.size(21.dp))
        if (!overlayPass) {
            Text(label, fontSize = 10.sp, color = tint)
        }
    }
}

@Composable
private fun FeatureRow(f: BaseFeature, checked: Boolean, onChange: (Boolean) -> Unit) {
    val copy = SettingsCopy.of(f.id)
    SwitchPreference(
        checked = checked,
        onCheckedChange = onChange,
        title = copy?.label ?: f.title,
        summary = copy?.blurb ?: f.summary,
    )
}

private fun Modifier.clickableCompat(onClick: () -> Unit): Modifier =
    this.then(Modifier.clickable(onClick = onClick))
