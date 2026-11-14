package dev.xalor.kdkit.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import android.os.Build
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.FeatureRegistry
import dev.xalor.kdkit.ui.theme.UiPrefs

/** Android 12L 及以下的降级界面：这个文件不许出现任何 Glasmio 引用。 */
@Composable
fun LegacyPage(
    mode: String, glass: Boolean,
    onCycleTheme: () -> Unit, onToggleGlass: () -> Unit, onOpenAbout: () -> Unit,
) {
    val ctx = LocalContext.current
    var version by remember { mutableStateOf(0) }
    val all = FeatureRegistry.all
    val enabled = remember(version) { all.count { KdConfig.isOn(it.id, it.defaultOn) } }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
        .statusBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(top = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("KdKit", fontSize = 28.sp, fontWeight = FontWeight.Bold)
                Text("已启用 $enabled / ${all.size} · 快对 " +
                    dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME, fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text("主题：${UiPrefs.label(mode)}", fontSize = 12.sp,
                modifier = Modifier.clickable(onClick = onCycleTheme).padding(8.dp))
            Text(if (glass) "玻璃：开" else "玻璃：关", fontSize = 12.sp,
                modifier = Modifier.clickable(onClick = onToggleGlass).padding(8.dp))
            Text("关于", fontSize = 12.sp, modifier = Modifier.clickable(onClick = onOpenAbout).padding(8.dp))
        }
        Text(
            if (Build.VERSION.SDK_INT < 33) "此设备低于 Android 13：液态玻璃界面需要 13+，功能不受影响。"
            else "此设备的 GPU 不支持液态玻璃渲染（模拟器/弱 GPU），已自动切换为普通界面，功能不受影响。",
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(vertical = 8.dp))

        for (g in Group.values()) {
            val items = SettingsCopy.items(g).mapNotNull { FeatureRegistry.byId(it.id) }
            if (items.isEmpty()) continue
            Text("${g.label}  ${items.count { KdConfig.isOn(it.id, it.defaultOn) }}/${items.size}",
                fontSize = 13.sp, fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(top = 14.dp, bottom = 4.dp))
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp))
                .background(MaterialTheme.colorScheme.surface)) {
                items.forEach { f ->
                    val copy = SettingsCopy.of(f.id)
                    val checked = remember(version, f.id) { KdConfig.isOn(f.id, f.defaultOn) }
                    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(copy?.label ?: f.title, fontSize = 15.sp)
                            Text(copy?.blurb ?: f.summary, fontSize = 12.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(checked = checked, onCheckedChange = { KdConfig.setApp(ctx, f.id, it); version++ })
                    }
                }
            }
        }
        Spacer(Modifier.height(40.dp))
    }
}

/**
 * 降级「关于/更新」页：纯 Material3，不碰 Glasmio —— 与 [LegacyPage] 同一套理由。
 * 更新检查做成页面内的一个可点行（不是弹窗），版本比较用语义比较。
 */
@Composable
fun LegacyAbout(onBack: () -> Unit) {
    val ctx = LocalContext.current
    var state by remember { mutableStateOf("正在检查更新…") }
    var detail by remember { mutableStateOf("") }
    var selfVer by remember { mutableStateOf("?") }
    LaunchedEffect(Unit) {
        selfVer = runCatching {
            ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
        }.getOrDefault("?")
        val tag = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            LegacyUpdateChecker.fetchLatestTag()
        }
        state = when {
            tag == null -> "检查更新失败：连不上 GitHub"
            LegacyUpdateChecker.isNewer(tag, selfVer) -> "有新版本 $tag（点这里去打开发布页）"
            else -> "已是最新版本（$selfVer）"
        }
        detail = "远端读取 GitHub Releases"
    }
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
        .statusBarsPadding().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("← 返回", fontSize = 14.sp, modifier = Modifier.clickable(onClick = onBack).padding(8.dp))
        }
        Text("关于 KdKit", fontSize = 26.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 8.dp))
        Text("版本 $selfVer · MIT · 作者 xalor", fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Column(Modifier.fillMaxWidth().padding(top = 18.dp).clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surface)
            .clickable {
                if (state.startsWith("有新版本")) LegacyUpdateChecker.openReleases(ctx)
                else {
                    state = "正在检查更新…"
                }
            }.padding(14.dp)) {
            Text(state, fontSize = 15.sp)
            if (detail.isNotEmpty()) Text(detail, fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Text("项目主页", fontSize = 14.sp, modifier = Modifier.padding(top = 16.dp)
            .clickable { LegacyUpdateChecker.openReleases(ctx) }.padding(vertical = 6.dp))
        Text("Basline 快对 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME}（${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_CODE}）；兼容 7.10.0 / 7.9.0 / 1865",
            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 12.dp))
    }
}

private object LegacyUpdateChecker {
    private const val OWNER = "xalor888"
    private const val NAME = "KdKit"
    private const val API = "https://api.github.com/repos/$OWNER/$NAME/releases/latest"
    private const val REPO = "https://github.com/$OWNER/$NAME"
    private val TAG_RE = Regex("\"tag_name\"\\s*:\\s*\"([^\"]+)\"")

    fun fetchLatestTag(): String? = runCatching {
        val c = (java.net.URL(API).openConnection() as java.net.HttpURLConnection).apply {
            connectTimeout = 5000; readTimeout = 5000
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", "KdKit-Android")
        }
        try {
            if (c.responseCode in 200..299)
                TAG_RE.find(c.inputStream.bufferedReader().use { it.readText() })?.groupValues?.get(1)
            else null
        } finally { c.disconnect() }
    }.getOrNull()

    fun isNewer(tag: String, local: String): Boolean {
        val a = tag.trim().removePrefix("v").removePrefix("V").substringBefore('-').split('.')
            .map { it.toIntOrNull() ?: 0 }
        val b = local.trim().removePrefix("v").substringBefore('-').split('.')
            .map { it.toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrNull(i) ?: 0; val y = b.getOrNull(i) ?: 0
            if (x != y) return x > y
        }
        return false
    }

    fun openReleases(ctx: android.content.Context) {
        runCatching {
            ctx.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW,
                android.net.Uri.parse("$REPO/releases")))
        }
    }
}
