package dev.xalor.kdkit.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.size
import androidx.compose.material3.IconButton
import kotlinx.coroutines.launch
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Palette
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.Warning
import androidx.activity.compose.PredictiveBackHandler
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.material.icons.filled.BlurOn
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.LightMode
import androidx.compose.material.icons.filled.SettingsBrightness
import androidx.compose.material3.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.sp
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.BaseFeature
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.ui.theme.KdKitTheme
import dev.xalor.kdkit.ui.theme.LocalGlass
import top.yukonga.miuix.kmp.basic.Card
import top.yukonga.miuix.kmp.basic.Scaffold
import top.yukonga.miuix.kmp.basic.SmallTitle
import top.yukonga.miuix.kmp.basic.TopAppBar
import top.yukonga.miuix.kmp.preference.ArrowPreference
import top.yukonga.miuix.kmp.preference.SwitchPreference
import dev.xalor.kdkit.ui.theme.UiPrefs
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 设置页（2026-11-14 发版前重做）。
 *
 * 改的是什么：**信息的组织方式**，不是功能。
 *  * 38 张独立卡 → **一组一张卡**（分段列表，参照 WeKit 的 `SegmentedColumn` 范式）；
 *  * 长技术副标题 → **一句简明**（`SettingsCopy`），技术说明降级到点击展开区；
 *  * "必须重启" 与 "即时生效" 的自相矛盾 → 顶部说一次 + 行内徽标，不再两处打架；
 *  * 灌满首屏的"配置通道"技术卡 → 缩成状态行里的一个 chip，点开才是诊断对话框；
 *  * 加批量入口：组级"全开/全关"、全量"推荐配置/恢复默认"、关于页。
 *
 * 为什么不改 `BaseFeature.summary`：它同时喂 README 功能表与门禁
 * （`check_feature_parity` 校验 id/热/选项三列）。展示文案与文档文案分开，
 * 改 UI 就不会牵动任何钩子门禁。判据见 `SettingsCopyTest` 与 `module/UI.md`。
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        KdConfig.attachApp(applicationContext)
        setContent {
            val ctx = LocalContext.current
            var mode by remember { mutableStateOf(UiPrefs.theme(ctx)) }
            var glass by remember { mutableStateOf(UiPrefs.glass(ctx)) }
            var backProgress by remember { mutableFloatStateOf(0f) }

            // 预测性返回：跟手缩放 + 淡出。`android:enableOnBackInvokedCallback="true"`
            // 在 Manifest 里开；API 33 以下这个 handler 不会触发，走系统默认返回。
            PredictiveBackHandler(enabled = true) { progress ->
                runCatching {
                    progress.collect { backProgress = it.progress }
                }
                backProgress = 0f
                finish()
            }
            val scale by animateFloatAsState(1f - 0.06f * backProgress, label = "back-scale")

            KdKitTheme(themeMode = mode, glass = glass) {
                // 关键：先铺一层**不透明**底色，再叠玻璃背景。
                // 以前这里是 Transparent Surface：一旦背景 Canvas 没画出来（新系统渲染差异），
                // 整页就是纯黑 —— 这就是「打开 KdKit 直接黑屏」的机制。
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = if (LocalGlass.current.isDark) Color(0xFF0B0D14) else Color(0xFFEDEFF7),
                ) {
                    GlassBackground {
                        Box(Modifier.graphicsLayer {
                            scaleX = scale; scaleY = scale
                            alpha = 1f - 0.18f * backProgress
                            clip = false
                        }) {
                            SettingsScreen(
                                mode = mode,
                                glass = glass,
                                onCycleTheme = {
                                    val next = UiPrefs.next(ctx)
                                    UiPrefs.setTheme(ctx, next)
                                    mode = next
                                },
                                onToggleGlass = {
                                    val on = !glass
                                    UiPrefs.setGlass(ctx, on)
                                    glass = on
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsScreen(
    mode: String,
    glass: Boolean,
    onCycleTheme: () -> Unit,
    onToggleGlass: () -> Unit,
) {
    val ctx = LocalContext.current
    var query by remember { mutableStateOf("") }
    var version by remember { mutableIntStateOf(0) }
    var showDiag by remember { mutableStateOf(false) }
    var showAbout by remember { mutableStateOf(false) }
    val expandedGroups = remember { mutableStateMapOf<Group, Boolean>() }
    // 展开的"单个功能详情"集合提升到这一层：放进 LazyColumn 的 item 里会被复用回收。
    val expandedRows = remember { mutableStateOf<Set<String>>(emptySet()) }

    val all = FeatureRegistry.all
    val enabledCount = remember(version) { all.count { KdConfig.isOn(it.id, it.defaultOn) } }

    val searching = query.isNotBlank()
    val filtered = remember(query) {
        if (!searching) emptyList() else FeatureRegistry.all.filter { f ->
            val c = SettingsCopy.of(f.id)
            f.id.contains(query, true) ||
                f.title.contains(query, true) ||
                (c != null && (c.label.contains(query, true) || c.blurb.contains(query, true)))
        }
    }

    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    val health = remember(version) { channelHealth(ctx) }

    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()

    // 底栏四个入口 → 各组在列表里的位置（非搜索态；搜索态底栏隐藏）
    val groupTop = buildMap {
        var idx = 2
        for (g in Group.values()) {
            val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
            if (items.isEmpty()) continue
            put(g, idx)
            idx += 1
            if (expandedGroups[g] ?: g.expanded) idx += 1
        }
    }

    Scaffold(
        // 不透明底：透明容器 + 绘制失败 = 整页黑屏（Android 17 上就是这样）。
        containerColor = if (LocalGlass.current.isDark) Color(0xFF0B0D14) else Color(0xFFEDEFF7),
        bottomBar = {
            if (!searching) {
                GlassBottomBar(glass) { g ->
                    scope.launch { listState.animateScrollToItem(groupTop[g] ?: 0) }
                }
            }
        },
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        topBar = {},
    ) { padding ->
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 104.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item(key = "title") {
                Column(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 4.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            "KdKit",
                            style = MaterialTheme.typography.headlineLarge,
                            fontWeight = FontWeight.Bold,
                            color = LocalGlass.current.onCard,
                        )
                        Spacer(Modifier.weight(1f))
                        IconButton(onClick = onCycleTheme) {
                            Icon(
                                when (mode) {
                                    UiPrefs.THEME_DARK -> Icons.Default.DarkMode
                                    UiPrefs.THEME_LIGHT -> Icons.Default.LightMode
                                    else -> Icons.Default.SettingsBrightness
                                },
                                contentDescription = "主题：${UiPrefs.label(mode)}",
                                tint = LocalGlass.current.onCard,
                            )
                        }
                        IconButton(onClick = onToggleGlass) {
                            Icon(
                                Icons.Default.BlurOn,
                                contentDescription = if (glass) "液态玻璃：开" else "液态玻璃：关",
                                tint = if (glass) LocalGlass.current.accent else LocalGlass.current.onCardMuted,
                            )
                        }
                        IconButton(onClick = { showAbout = true }) {
                            Icon(Icons.Default.Info, contentDescription = "关于", tint = LocalGlass.current.onCard)
                        }
                    }
                    Text(
                        "已启用 $enabledCount / ${all.size} · 快对 " +
                            dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME,
                        style = MaterialTheme.typography.bodyMedium,
                        color = LocalGlass.current.onCardMuted,
                    )
                }
            }

            item { StatusLine(health) { showDiag = true } }

            item {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                    placeholder = { Text("搜索功能（标题、说明、标识）") },
                    shape = RoundedCornerShape(14.dp),
                )
            }

            if (searching) {
                if (filtered.isEmpty()) {
                    item {
                        Text(
                            "没有匹配的功能",
                            modifier = Modifier.padding(vertical = 24.dp),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    item(key = "search_count") {
                        Text(
                            "搜索结果 ${filtered.size} 项",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    item(key = "search_card") {
                        FeatureCard(
                            features = filtered,
                            version = version,
                            expandedIds = expandedRows,
                            glass = glass,
                            onChange = { version++ },
                        )
                    }
                }
            } else {
                for (g in Group.values()) {
                    val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
                    if (items.isEmpty()) continue
                    val open = expandedGroups[g] ?: g.expanded
                    item(key = "h_${g.id}") {
                        GroupHeader(
                            group = g,
                            features = items,
                            version = version,
                            expanded = open,
                            onToggle = { expandedGroups[g] = !open },
                            onAllOn = { items.forEach { KdConfig.setApp(ctx, it.id, true) }; version++ },
                            onAllOff = { items.forEach { KdConfig.setApp(ctx, it.id, false) }; version++ },
                        )
                    }
                    if (open) {
                        item(key = "c_${g.id}") {
                            FeatureCard(
                                features = items,
                                version = version,
                                expandedIds = expandedRows,
                                glass = glass,
                                onChange = { version++ },
                            )
                        }
                    }
                }

                item { BulkActions(all, onApply = { version++ }) }
                item { FooterNote(health) }
            }
        }
    }

    if (showDiag) DiagnosticsDialog(version, onDismiss = { showDiag = false }) { version++ }
    if (showAbout) AboutDialog(onDismiss = { showAbout = false })
}

/* ───────────────────────── 悬浮玻璃底栏 ───────────────────────── */

/**
 * FuseHide 那种"浮在内容上方的玻璃胶囊底栏"：4 个分组入口 + 选中高亮。
 *
 * 为什么需要它：40 个功能滚起来很长，原来只能靠滑动找组。
 * 底栏把"去广告 / 内容 / 外观 / 诊断"变成一键跳转 —— 同时它本身也是玻璃材质的展示面。
 */
@Composable
private fun GlassBottomBar(glass: Boolean, onJump: (Group) -> Unit) {
    val entries = listOf(
        Triple(Group.ADS, Icons.Default.Block, "去广告"),
        Triple(Group.CONTENT, Icons.Default.Tune, "内容"),
        Triple(Group.LOOK, Icons.Default.Palette, "外观"),
        Triple(Group.DIAG, Icons.Default.BugReport, "诊断"),
    )
    Box(
        Modifier.fillMaxWidth()
            .navigationBarsPadding()
            .padding(horizontal = 20.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        GlassCard(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(30.dp),
            glassOff = !glass,
            elevation = 18.dp,
        ) {
            Row(
                Modifier.fillMaxWidth().padding(vertical = 6.dp),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                entries.forEach { (g, icon, label) ->
                    Column(
                        modifier = Modifier
                            .clip(RoundedCornerShape(20.dp))
                            .clickable { onJump(g) }
                            .padding(horizontal = 10.dp, vertical = 4.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Icon(icon, contentDescription = label, tint = LocalGlass.current.accent)
                        Text(
                            label,
                            style = MaterialTheme.typography.labelSmall,
                            color = LocalGlass.current.onCard,
                        )
                    }
                }
            }
        }
    }
}

/* ───────────────────────── 状态行 ───────────────────────── */

private data class Health(val ok: Boolean, val line: String)

/** 配置通道是否健康：发布文件存在且权限 644（宿主是另一个 uid，只能读 world-readable 文件）。 */
private fun channelHealth(ctx: android.content.Context): Health {
    val f = File(ctx.filesDir, "kdkit_status.txt")
    if (!f.exists()) return Health(false, "配置通道未发布：先在框架里启用模块，再打开一次本应用")
    val text = runCatching { f.readText() }.getOrDefault("")
    val mode = text.lineSequence().firstOrNull { it.startsWith("mode=") }?.removePrefix("mode=")?.trim()
    val flags = text.lineSequence().firstOrNull { it.startsWith("flags=") }?.removePrefix("flags=")?.trim()
    return if (mode == "644") Health(true, "设置已同步到快对 · $flags 条")
    else Health(false, "设置没送到快对（权限 $mode），开关可能不生效")
}

@Composable
private fun StatusLine(health: Health, onOpenDiag: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Icon(
            if (health.ok) Icons.Default.CheckCircle else Icons.Default.Warning,
            contentDescription = null,
            tint = if (health.ok) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
        )
        Text(
            health.line,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        TextButton(onClick = onOpenDiag) { Text(if (health.ok) "诊断" else "修复") }
    }
}

/* ───────────────────────── 组头 ───────────────────────── */

/** 组内已启用数。放在 @Composable 里，是因为 LazyListScope 的 builder 不能调 remember。 */
@Composable
private fun rememberCount(features: List<BaseFeature>, version: Int): Int =
    remember(version, features) { features.count { KdConfig.isOn(it.id, it.defaultOn) } }

@Composable
private fun GroupHeader(
    group: Group,
    features: List<BaseFeature>,
    version: Int,
    expanded: Boolean,
    onToggle: () -> Unit,
    onAllOn: () -> Unit,
    onAllOff: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f).clickable { onToggle() }) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.width(6.dp))
                Text(group.label, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(8.dp))
                Text(
                    "${rememberCount(features, version)}/${features.size}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                group.blurb,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        // 折叠时也留"全开"：用户想整组开掉，不该先展开再点。
        TextButton(onClick = onAllOn, contentPadding = PaddingValues(horizontal = 8.dp)) {
            Text("全开", style = MaterialTheme.typography.labelSmall)
        }
        if (expanded) {
            TextButton(onClick = onAllOff, contentPadding = PaddingValues(horizontal = 8.dp)) {
                Text("全关", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

/* ───────────────────────── 一组一张卡 ───────────────────────── */

/** 把技术说明里与"生效方式"重复的尾巴去掉，展开区只留信息量。 */
private fun techNote(summary: String): String =
    summary
        .replace("（改开关即时生效）", "")
        .replace("(改开关即时生效)", "")
        .replace("（可切为只记录）", "")
        .trim()

@Composable
private fun FeatureCard(
    features: List<BaseFeature>,
    version: Int,
    expandedIds: MutableState<Set<String>>,
    glass: Boolean,
    onChange: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        cornerRadius = 22.dp,
    ) {
        Column {
            features.forEachIndexed { i, f ->
                FeatureRow(
                    f = f,
                    version = version,
                    expanded = f.id in expandedIds.value,
                    onRowClick = {
                        expandedIds.value = if (f.id in expandedIds.value) {
                            expandedIds.value - f.id
                        } else {
                            expandedIds.value + f.id
                        }
                    },
                    onChange = onChange,
                )
                if (i != features.lastIndex) {
                    HorizontalDivider(
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp),
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                    )
                }
            }
        }
    }
}

@Composable
private fun FeatureRow(
    f: BaseFeature,
    version: Int,
    expanded: Boolean,
    onRowClick: () -> Unit,
    onChange: () -> Unit,
) {
    val ctx = LocalContext.current
    val checked = remember(f.id, version) { KdConfig.isOn(f.id, f.defaultOn) }
    val copy = SettingsCopy.of(f.id)

    Column(Modifier.clickable { onRowClick() }) {
        SwitchPreference(
            checked = checked,
            onCheckedChange = { v ->
                KdConfig.setApp(ctx, f.id, v)
                onChange()
            },
            title = copy?.label ?: f.title,
            summary = copy?.blurb ?: f.summary,
            modifier = Modifier.clickable { onRowClick() },
        )
        AnimatedVisibility(visible = expanded) {
            Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 14.dp)) {
                // 只留真正有用的两件事：标识（给排障/抓取对账用）与生效方式。
                // 标题不再重复一遍（简明标题就在上面），summary 的尾部括号提示也剥掉 ——
                // 那是"改开关即时生效 / 需重启"，这里已经单独写了。
                Text(
                    "标识 ${f.id} · " + if (f.hot) "即时生效" else "需重启快对",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    techNote(f.summary),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp),
                )
                OptionsSection(f.options, version, onChange)
            }
        }
    }
}

/* ───────────────────────── 底部批量 ───────────────────────── */

@Composable
private fun BulkActions(all: List<BaseFeature>, onApply: () -> Unit) {
    val ctx = LocalContext.current
    var confirmReset by remember { mutableStateOf(false) }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
        Button(
            onClick = {
                all.forEach { f ->
                    KdConfig.setApp(ctx, f.id, f.id in SettingsCopy.recommendedOn)
                }
                onApply()
            },
            modifier = Modifier.fillMaxWidth(),
        ) { Text("开启推荐配置") }
        Text(
            "去广告、内容与会员、省心开关、答题助手全开；诊断与抓取全关。",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { confirmReset = true }, modifier = Modifier.weight(1f)) {
                Text("恢复默认")
            }
            OutlinedButton(
                onClick = { all.forEach { KdConfig.setApp(ctx, it.id, it.id in SettingsCopy.recommendedOn) }; onApply() },
                modifier = Modifier.weight(1f),
            ) { Text("关闭全部诊断") }
        }
    }

    if (confirmReset) {
        AlertDialog(
            onDismissRequest = { confirmReset = false },
            title = { Text("恢复默认？") },
            text = { Text("所有开关回到各功能自己的默认值（多数是开）。") },
            confirmButton = {
                TextButton(onClick = {
                    // 清掉应用侧覆写，让 KdConfig.isOn 回落到 defaultOn
                    runCatching { ctx.getSharedPreferences(KdConfig.PREFS_NAME, 0).edit().clear().apply() }
                    confirmReset = false
                    onApply()
                }) { Text("恢复") }
            },
            dismissButton = { TextButton(onClick = { confirmReset = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun FooterNote(health: Health) {
    Text(
        "多数开关即时生效；标着「需重启快对」的少数几项，改完请彻底结束快对再打开。" +
            if (health.ok) "" else "\n配置通道异常时，改完的开关可能没被宿主读到 —— 点上面的「修复」。",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = 8.dp, bottom = 8.dp),
    )
}

/* ───────────────────────── 诊断对话框（原 DiagnosticsCard） ───────────────────────── */

@Composable
private fun DiagnosticsDialog(version: Int, onDismiss: () -> Unit, onChange: () -> Unit) {
    val ctx = LocalContext.current
    val status = remember(version) {
        val f = File(ctx.filesDir, "kdkit_status.txt")
        if (f.exists()) runCatching { f.readText() }.getOrDefault("") else ""
    }
    val mode = status.lineSequence().firstOrNull { it.startsWith("mode=") }?.removePrefix("mode=")?.trim()
    val flags = status.lineSequence().firstOrNull { it.startsWith("flags=") }?.removePrefix("flags=")?.trim()
    val path = status.lineSequence().firstOrNull { it.startsWith("published=") }?.removePrefix("published=")?.trim()
    val ts = status.lineSequence().firstOrNull { it.startsWith("ts=") }?.removePrefix("ts=")?.trim()?.toLongOrNull()

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("配置通道") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    when {
                        status.isEmpty() -> "尚未发布：先在框架里启用模块，再打开一次本应用。"
                        mode == "644" -> "已发布 $flags 项 · 权限 644（宿主可读）"
                        else -> "已发布 $flags 项 · 权限 $mode ⚠ 宿主读不到，功能会退回默认值"
                    },
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    "文件：${path ?: "-"}\n权限：${mode ?: "-"}\n时间：${
                        ts?.let { SimpleDateFormat("MM-dd HH:mm:ss", Locale.US).format(Date(it)) } ?: "-"
                    }",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "宿主（快对）与设置应用是不同 uid，宿主只能读这个 world-readable 文件。" +
                        "本应用重新写偏好时可能把它改成 0660，宿主随即读到空表 —— 一键重发可修复。",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = {
                runCatching {
                    File(ctx.filesDir, "kdkit_repair.request").writeText(System.currentTimeMillis().toString())
                }
                onChange()
                onDismiss()
            }) { Text("重新发布（修复权限）") }
        },
        dismissButton = {
            Row {
                TextButton(onClick = { onChange() }) { Text("刷新") }
                TextButton(onClick = onDismiss) { Text("关闭") }
            }
        },
    )
}

/* ───────────────────────── 关于（版本 / 作者 / 检查更新） ───────────────────────── */

private const val REPO_OWNER = "xalor888"
private const val REPO_NAME = "KdKit"
private const val REPO_URL = "https://github.com/$REPO_OWNER/$REPO_NAME"
private const val RELEASES_URL = "$REPO_URL/releases"
private const val API_LATEST = "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest"

/** GitHub release JSON 里的 tag 提取 —— 编译期构造一次（门禁 ⑲ 把语句位置正则算作热路径）。 */
private val TAG_RE = Regex("\"tag_name\"\\s*:\\s*\"([^\"]+)\"")

private sealed interface UpdateState {
    data object Checking : UpdateState
    data object Latest : UpdateState
    data class Newer(val tag: String) : UpdateState
    data class Failed(val why: String) : UpdateState
}

/** 拉 GitHub 最新 release 的 tag（不引入网络库：一次 GET + 正则）。 */
private fun fetchLatestTag(): String? = runCatching {
    val conn = (java.net.URL(API_LATEST).openConnection() as java.net.HttpURLConnection).apply {
        requestMethod = "GET"
        connectTimeout = 6000
        readTimeout = 6000
        setRequestProperty("Accept", "application/vnd.github+json")
        setRequestProperty("User-Agent", "KdKit-Android")
    }
    try {
        if (conn.responseCode !in 200..299) return null
        val body = conn.inputStream.bufferedReader().use { it.readText() }
        TAG_RE.find(body)?.groupValues?.get(1)
    } finally {
        conn.disconnect()
    }
}.getOrNull()

private fun openUrl(ctx: android.content.Context, url: String) {
    runCatching {
        ctx.startActivity(
            android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url))
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}

@Composable
private fun AboutDialog(onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val selfVer = remember {
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?" }
            .getOrDefault("?")
    }
    var state by remember { mutableStateOf<UpdateState>(UpdateState.Checking) }

    // 打开关于页就自动检查一次更新。
    LaunchedEffect(Unit) {
        state = runCatching {
            val tag: String? = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { fetchLatestTag() }
            if (tag == null) {
                UpdateState.Failed("连不上 GitHub，稍后再试")
            } else if (tag.trimStart('v', 'V') == selfVer) {
                UpdateState.Latest
            } else {
                UpdateState.Newer(tag)
            }
        }.getOrElse { UpdateState.Failed(it.message ?: "检查失败") }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("关于 KdKit") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("版本 $selfVer · MIT License", style = MaterialTheme.typography.bodyMedium)
                Text(
                    "适配基线 快对 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME}" +
                        "（${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_CODE}），兼容 7.10.0 / 7.9.0。",
                    style = MaterialTheme.typography.bodySmall,
                )
                HorizontalDivider(Modifier.padding(vertical = 4.dp))
                Text(
                    when (val st = state) {
                        UpdateState.Checking -> "正在检查更新…"
                        UpdateState.Latest -> "已是最新版本"
                        is UpdateState.Newer -> "有新版本 ${st.tag}"
                        is UpdateState.Failed -> "检查更新失败：${st.why}"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = when (state) {
                        is UpdateState.Newer -> MaterialTheme.colorScheme.primary
                        is UpdateState.Failed -> MaterialTheme.colorScheme.error
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
                if (state is UpdateState.Newer) {
                    TextButton(onClick = { openUrl(ctx, RELEASES_URL) }) {
                        Text("打开发布页下载")
                    }
                }
                HorizontalDivider(Modifier.padding(vertical = 4.dp))
                Text("作者 xalor", style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    TextButton(onClick = { openUrl(ctx, REPO_URL) }) { Text("项目主页") }
                    TextButton(onClick = { openUrl(ctx, RELEASES_URL) }) { Text("全部版本") }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}
