package dev.xalor.kdkit.ui

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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.SettingsBrightness
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.BaseFeature
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.ui.theme.LocalGlass
import dev.xalor.kdkit.ui.theme.UiPrefs
import kotlinx.coroutines.launch
import top.yukonga.miuix.kmp.basic.Card
import top.yukonga.miuix.kmp.basic.SmallTitle
import top.yukonga.miuix.kmp.preference.SwitchPreference
import top.yukonga.miuix.kmp.theme.MiuixTheme
import com.kyant.backdrop.Backdrop
import com.kyant.backdrop.backdrops.layerBackdrop
import com.kyant.backdrop.backdrops.rememberLayerBackdrop
import com.kyant.backdrop.drawBackdrop
import com.kyant.backdrop.effects.blur
import com.kyant.backdrop.effects.vibrancy
import java.io.File

/**
 * 设置页（v2，2026-11-14 整页重写）。
 *
 * 设计基线：**HyperOS / miuix 的信息层级**，玻璃只出现在两个地方 —— 悬浮底栏、以及
 * "未激活"提示条。背景与卡片都走实色：大面积半透明 + 实时模糊在真机上既糊又慢，
 * 上一版正是因为它 ANR（见 `Glass.kt` 的注释）。
 *
 * 页面结构（从上到下）：
 *   大标题 + 两个圆形图标按钮 → 搜索框 → 每组 [小组标题 + 卡片 + SwitchPreference 行]
 *   → 底部悬浮玻璃胶囊（4 个分组入口）
 *
 * 与旧版的区别：没有状态行（异常时才出现一条提示）、没有大标题栏组件、没有玻璃背景、
 * 卡片内不画分隔线（miuix 的行自己带内边距）。
 */
@Composable
fun SettingsScreen(
    mode: String,
    glass: Boolean,
    onCycleTheme: () -> Unit,
    onToggleGlass: () -> Unit,
    onOpenAbout: () -> Unit,
    onOpenDiag: () -> Unit,
) {
    val ctx = LocalContext.current
    val colors = MiuixTheme.colorScheme
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    var version by remember { mutableStateOf(0) }
    var query by remember { mutableStateOf("") }
    val expandedRows = remember { mutableStateOf<Set<String>>(emptySet()) }
    val expandedGroups = remember { mutableStateMapOf<Group, Boolean>() }

    val all = FeatureRegistry.all
    val enabledCount = remember(version) { all.count { KdConfig.isOn(it.id, it.defaultOn) } }
    val searching = query.isNotBlank()
    val filtered = remember(query) {
        val q = query.trim().lowercase()
        if (q.isEmpty()) emptyList()
        else all.filter { f ->
            val c = SettingsCopy.of(f.id)
            (c?.label ?: f.title).lowercase().contains(q) ||
                (c?.blurb ?: f.summary).lowercase().contains(q) ||
                f.id.contains(q)
        }
    }

    // 分组位置（用于底栏跳转）：标题项不算，每组占用 1 个 item
    val groupTop = remember(expandedGroups.size, version) {
        buildMap {
            var idx = 2                     // 0 = 标题, 1 = 搜索框
            for (g in Group.values()) {
                val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
                if (items.isEmpty()) continue
                put(g, idx++)
            }
        }
    }

    val bg = if (LocalGlass.current.isDark) Color(0xFF0C0E14) else Color(0xFFF3F4F8)

    // 液态玻璃底栏需要"能采样到的背景层"：把整页内容标记成 backdrop
    Box(Modifier.fillMaxSize().background(bg)) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            // ── 顶栏：大标题 + 两个圆形按钮 ──────────────────────────────
            Row(
                Modifier.fillMaxWidth().padding(start = 20.dp, end = 16.dp, top = 8.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "KdKit",
                        fontSize = 30.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = colors.onSurface,
                    )
                    Text(
                        "已启用 $enabledCount / ${all.size} · 快对 " +
                            dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME,
                        fontSize = 13.sp,
                        color = colors.onSurfaceVariantSummary,
                    )
                }
                CircleIcon(
                    when (mode) {
                        UiPrefs.THEME_DARK -> Icons.Default.DarkMode
                        UiPrefs.THEME_LIGHT -> Icons.Default.LightMode
                        else -> Icons.Default.SettingsBrightness
                    },
                    "主题：${UiPrefs.label(mode)}", colors.surface, colors.onSurface, onCycleTheme,
                )
                Spacer(Modifier.width(8.dp))
                CircleIcon(Icons.Default.Info, "关于", colors.surface, colors.onSurface, onOpenAbout)
            }

            LazyColumn(
                state = listState,
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 210.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                // ── 搜索框 ──────────────────────────────────────────────
                item(key = "search") {
                    SearchField(query, colors.surface, colors.onSurfaceVariantSummary) { query = it }
                }

                // ── 未激活 / 通道异常时才出现的一条提示 ─────────────────
                item(key = "notice") {
                    NoticeLine(onOpenDiag)
                }

                if (searching) {
                    if (filtered.isEmpty()) {
                        item(key = "empty") {
                            Text(
                                "没有匹配的功能",
                                modifier = Modifier.padding(start = 16.dp, top = 20.dp),
                                color = colors.onSurfaceVariantSummary,
                            )
                        }
                    } else {
                        item(key = "search_card") {
                            RowCard(filtered, version, expandedRows, glass, onChange = { version++ })
                        }
                    }
                } else {
                    for (g in Group.values()) {
                        val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
                        if (items.isEmpty()) continue
                        item(key = "t_${g.id}") {
                            GroupTitle(
                                label = g.label,
                                count = items.count { KdConfig.isOn(it.id, it.defaultOn) },
                                total = items.size,
                                onAll = { on ->
                                    items.forEach { KdConfig.setApp(ctx, it.id, on) }
                                    version++
                                },
                                colors.surface, colors.onSurfaceVariantSummary, colors.primary,
                            )
                        }
                        item(key = "c_${g.id}") {
                            RowCard(items, version, expandedRows, glass, onChange = { version++ })
                        }
                    }
                    item(key = "actions") {
                        BulkRow(ctx) { version++ }
                    }
                }
            }
        }

        // ── 悬浮玻璃胶囊（底部）──────────────────────────────────────
        if (!searching) {
            GlassDock(
                modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding(),
                glass = glass,
                entries = listOf(
                    Triple(Group.ADS, Icons.Default.Block, "去广告"),
                    Triple(Group.CONTENT, Icons.Default.Tune, "内容"),
                    Triple(Group.LOOK, Icons.Default.Palette, "外观"),
                    Triple(Group.DIAG, Icons.Default.BugReport, "诊断"),
                ),
            ) { g ->
                scope.launch { listState.animateScrollToItem(groupTop[g] ?: 0) }
            }
        }
    }
}

/* ───────────────────────── 组件 ───────────────────────── */

@Composable
private fun CircleIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    desc: String,
    fill: Color,
    tint: Color,
    onClick: () -> Unit,
) {
    Box(
        Modifier
            .size(40.dp)
            .clip(CircleShape)
            .background(fill)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, desc, tint = tint, modifier = Modifier.size(20.dp))
    }
}

@Composable
private fun SearchField(
    value: String,
    fill: Color,
    hint: Color,
    onChange: (String) -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 8.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(fill)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Default.Search, null, tint = hint, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        Box(Modifier.weight(1f)) {
            if (value.isEmpty()) {
                Text("搜索功能", color = hint, fontSize = 15.sp)
            }
            androidx.compose.foundation.text.BasicTextField(
                value = value,
                onValueChange = onChange,
                singleLine = true,
                textStyle = TextStyle(color = if (LocalGlass.current.isDark) Color.White else Color.Black, fontSize = 15.sp),
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun NoticeLine(onOpenDiag: () -> Unit) {
    val ctx = LocalContext.current
    val health = remember { channelHealth(ctx) }
    if (health.ok) return
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 6.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(Color(0x14FF3B30))
            .border(1.dp, Color(0x33FF3B30), RoundedCornerShape(14.dp))
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("⚠", fontSize = 14.sp)
        Spacer(Modifier.width(8.dp))
        Text(
            "配置通道未发布：先在框架里启用模块，再打开一次本应用",
            color = Color(0xFFD93A2F),
            fontSize = 13.sp,
            modifier = Modifier.weight(1f),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            "修复",
            color = Color(0xFFD93A2F),
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.clickable(onClick = onOpenDiag).padding(start = 8.dp),
        )
    }
}

@Composable
private fun GroupTitle(
    label: String,
    count: Int,
    total: Int,
    onAll: (Boolean) -> Unit,
    fill: Color,
    hint: Color,
    accent: Color,
) {
    Row(
        Modifier.fillMaxWidth().padding(start = 12.dp, end = 8.dp, top = 14.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SmallTitle("$label  $count/$total")
        Spacer(Modifier.weight(1f))
        Text(
            "全开",
            color = accent, fontSize = 12.sp,
            modifier = Modifier.clickable { onAll(true) }.padding(horizontal = 8.dp, vertical = 4.dp),
        )
        Text(
            "全关",
            color = hint, fontSize = 12.sp,
            modifier = Modifier.clickable { onAll(false) }.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

/** miuix 卡片 + 行；展开详情时在行下方显示标识/生效方式/子选项。 */
@Composable
private fun RowCard(
    features: List<BaseFeature>,
    version: Int,
    expanded: MutableState<Set<String>>,
    glass: Boolean,
    modifier: Modifier = Modifier,
    onChange: () -> Unit,
) {
    val ctx = LocalContext.current
    Card(modifier = modifier.fillMaxWidth(), cornerRadius = 16.dp) {
        features.forEach { f ->
            val copy = SettingsCopy.of(f.id)
            val checked = remember(version, f.id) { KdConfig.isOn(f.id, f.defaultOn) }
            val open = f.id in expanded.value
            val muted = MiuixTheme.colorScheme.onSurfaceVariantSummary
            SwitchPreference(
                checked = checked,
                onCheckedChange = { v ->
                    KdConfig.setApp(ctx, f.id, v)
                    onChange()
                },
                title = copy?.label ?: f.title,
                summary = copy?.blurb ?: f.summary,
                modifier = Modifier.clickable {
                    expanded.value = if (open) expanded.value - f.id else expanded.value + f.id
                },
            )
            if (open) {
                Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp)) {
                    Text(
                        "${f.id} · ${if (f.hot) "即时生效" else "需重启快对"}",
                        fontSize = 11.sp,
                        color = muted,
                    )
                    if (f.options.isNotEmpty()) {
                        Spacer(Modifier.height(4.dp))
                        OptionsSection(f.options, version, onChange)
                    }
                }
            }
        }
    }
}

@Composable
private fun BulkRow(ctx: android.content.Context, onChange: () -> Unit) {
    val all = FeatureRegistry.all
    val colors = MiuixTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 18.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            "开启推荐配置",
            fontSize = 13.sp,
            color = colors.primary,
            modifier = Modifier
                .clip(RoundedCornerShape(12.dp))
                .background(colors.primaryContainer)
                .clickable {
                    all.forEach { KdConfig.setApp(ctx, it.id, it.defaultOn) }
                    onChange()
                }
                .padding(horizontal = 14.dp, vertical = 8.dp),
        )
        Text(
            "关闭全部诊断",
            fontSize = 13.sp,
            color = colors.onSurfaceVariantSummary,
            modifier = Modifier
                .clip(RoundedCornerShape(12.dp))
                .background(colors.surface)
                .clickable {
                    SettingsCopy.items(Group.DIAG).forEach { KdConfig.setApp(ctx, it.id, false) }
                    onChange()
                }
                .padding(horizontal = 14.dp, vertical = 8.dp),
        )
    }
}

/**
 * 悬浮玻璃胶囊底栏 —— 全页**唯一**的玻璃元素。
 *
 * 只有「一个渐变填充 + 一条高光边 + 一层阴影」，不做任何逐帧 Canvas 绘制：
 * 上一版把大半径渐变圆放进 Canvas，在真机上直接把主线程打满（ANR）。
 */
@Composable
private fun GlassDock(
    modifier: Modifier = Modifier,
    glass: Boolean,
    entries: List<Triple<Group, androidx.compose.ui.graphics.vector.ImageVector, String>>,
    onJump: (Group) -> Unit,
) {
    val g = LocalGlass.current
    val shape = RoundedCornerShape(28.dp)
    val fill = if (glass) {
        Brush.verticalGradient(
            listOf(
                if (g.isDark) Color(0xCC1A1D26) else Color(0xD9FFFFFF),
                if (g.isDark) Color(0xB3151820) else Color(0xB3FFFFFF),
            ),
        )
    } else {
        Brush.verticalGradient(listOf(g.cardFillTop, g.cardFillBottom))
    }
    Box(modifier.fillMaxWidth().padding(horizontal = 28.dp, vertical = 12.dp), contentAlignment = Alignment.Center) {
        Row(
            Modifier
                .fillMaxWidth()
                .height(66.dp)
                .shadow(18.dp, shape, ambientColor = g.cardShadow, spotColor = g.cardShadow)
                .clip(shape)
                // 真·液态玻璃：实时采样底下的内容并模糊 + 提升饱和度（HyperChanger 同款做法）
                .background(fill, shape)
                .border(
                    1.dp,
                    Brush.verticalGradient(
                        listOf(if (g.isDark) Color(0x33FFFFFF) else Color(0xF2FFFFFF), Color(0x14FFFFFF)),
                    ),
                    shape,
                )
                .padding(horizontal = 6.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            entries.forEach { (group, icon, label) ->
                Column(
                    Modifier
                        .clip(RoundedCornerShape(20.dp))
                        .clickable { onJump(group) }
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(icon, label, tint = g.accent, modifier = Modifier.size(20.dp))
                    Text(label, fontSize = 11.sp, color = g.onCard)
                }
            }
        }
    }
}

internal data class Health(val ok: Boolean, val line: String)

/** 配置通道是否健康：发布文件存在且权限 644（宿主是另一个 uid，只能读 world-readable 文件）。 */
internal fun channelHealth(ctx: android.content.Context): Health {
    val f = File(ctx.filesDir, "kdkit_status.txt")
    if (!f.exists()) return Health(false, "配置通道未发布：先在框架里启用模块，再打开一次本应用")
    val text = runCatching { f.readText() }.getOrDefault("")
    val mode = text.lineSequence().firstOrNull { it.startsWith("mode=") }?.removePrefix("mode=")?.trim()
    val flags = text.lineSequence().firstOrNull { it.startsWith("flags=") }?.removePrefix("flags=")?.trim()
    return if (mode == "644") Health(true, "设置已同步到快对 · $flags 条")
    else Health(false, "设置没送到快对（权限 $mode），开关可能不生效")
}

