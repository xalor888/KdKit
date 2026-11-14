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
            var oobeDone by remember { mutableStateOf(UiPrefs.oobeDone(ctx)) }
            var showAbout by remember { mutableStateOf(false) }
            var showDiag by remember { mutableStateOf(false) }
            var version by remember { mutableStateOf(0) }

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
                Box(Modifier.graphicsLayer {
                    scaleX = scale; scaleY = scale
                    alpha = 1f - 0.18f * backProgress
                    clip = false
                }) {
                    if (!oobeDone) {
                        Oobe(onDone = { oobeDone = true })
                        return@Box
                    }
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
                        onOpenAbout = { showAbout = true },
                        onOpenDiag = { showDiag = true },
                    )
                }
            }
            if (showAbout) AboutDialog(onDismiss = { showAbout = false })
            if (showDiag) DiagnosticsDialog(version, onDismiss = { showDiag = false }) { version++ }
        }
    }
}

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
private fun fetchLatestTag(): String? {
    // 1) GitHub API（国外网络首选）
    runCatching {
        val conn = (java.net.URL(API_LATEST).openConnection() as java.net.HttpURLConnection).apply {
            requestMethod = "GET"; connectTimeout = 5000; readTimeout = 5000
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", "KdKit-Android")
        }
        try {
            if (conn.responseCode in 200..299) TAG_RE.find(conn.inputStream.bufferedReader().use { it.readText() })
                ?.groupValues?.get(1) else null
        } finally { conn.disconnect() }
    }.getOrNull()?.let { return it }

    // 2) 回退：releases/latest 的 302（国内多数网络能到，API 常被挡）
    return runCatching {
        val conn = (java.net.URL("https://github.com/$REPO_OWNER/KdKit/releases/latest")
            .openConnection() as java.net.HttpURLConnection).apply {
            instanceFollowRedirects = false; connectTimeout = 8000; readTimeout = 8000
            setRequestProperty("User-Agent", "KdKit-Android")
        }
        try {
            val loc = conn.getHeaderField("Location") ?: return@runCatching null
            loc.trimEnd('/').substringAfterLast('/').takeIf { it.isNotEmpty() }
        } finally { conn.disconnect() }
    }.getOrNull()
}

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
