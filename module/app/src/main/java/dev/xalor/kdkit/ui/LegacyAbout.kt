package dev.xalor.kdkit.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.unit.sp

/** 降级「关于/更新」页：纯 Material3，不碰 Glasmio。 */
@Composable
fun LegacyAbout(onBack: () -> Unit) {
    val ctx = LocalContext.current
    var state by remember { mutableStateOf("正在检查更新…") }
    var selfVer by remember { mutableStateOf("?") }
    var reload by remember { mutableStateOf(0) }
    LaunchedEffect(reload) {
        state = "正在检查更新…"
        selfVer = runCatching {
            ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
        }.getOrDefault("?")
        val tag = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { UpdateApi.fetchLatestTag() }
        state = when {
            tag == null -> "检查更新失败：连不上 GitHub（点这里重试）"
            UpdateApi.isNewer(tag, selfVer) -> "有新版本 $tag（点这里去打开发布页）"
            else -> "已是最新版本（$selfVer）"
        }
    }
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
        .statusBarsPadding().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("← 返回", fontSize = 14.sp,
                modifier = Modifier.clickable(onClick = onBack).padding(8.dp))
        }
        Text("关于 KdKit", fontSize = 26.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.padding(top = 8.dp))
        Text("版本 $selfVer · MIT · 作者 xalor", fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Column(Modifier.fillMaxWidth().padding(top = 18.dp).clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.surface)
            .clickable {
                if (state.startsWith("有新版本")) UpdateApi.openReleases(ctx) else reload++
            }.padding(14.dp)) {
            Text(state, fontSize = 15.sp)

        }
        Spacer(Modifier.height(12.dp))
        Text("项目主页", fontSize = 14.sp,
            modifier = Modifier.clickable { UpdateApi.openReleases(ctx) }.padding(vertical = 6.dp))
        Text("基线 快对 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME}" +
            "（${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_CODE}）；兼容 7.10.0 / 7.9.0 / 1865",
            fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 12.dp))
    }
}

/** 极简的 GitHub 版本查询（降级页与液态页共用的只有这段语义比较逻辑）。 */
internal object UpdateApi {
    private const val OWNER = "xalor888"
    private const val NAME = "KdKit"
    private const val API = "https://api.github.com/repos/$OWNER/$NAME/releases/latest"
    private const val REPO = "https://github.com/$OWNER/$NAME"
    val repoUrl: String get() = REPO

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
        val a = tag.trim().removePrefix("v").removePrefix("V").substringBefore("-")
            .split(".").map { it.toIntOrNull() ?: 0 }
        val b = local.trim().removePrefix("v").substringBefore("-")
            .split(".").map { it.toIntOrNull() ?: 0 }
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrNull(i) ?: 0
            val y = b.getOrNull(i) ?: 0
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
