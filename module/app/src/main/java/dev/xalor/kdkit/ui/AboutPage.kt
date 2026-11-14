package dev.xalor.kdkit.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.neoruaa.glasmio.core.GlasmioTheme
import io.github.neoruaa.glasmio.core.IosTypography
import io.github.neoruaa.glasmio.glass.GlasmioBackdropHost
import io.github.neoruaa.glasmio.icons.SfIcon
import io.github.neoruaa.glasmio.ui.GlasmioGroupedList
import io.github.neoruaa.glasmio.ui.GlasmioListRow
import io.github.neoruaa.glasmio.ui.GlasmioSectionTitle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private const val REPO_OWNER = "xalor888"
private const val REPO_NAME = "KdKit"
private const val REPO_URL = "https://github.com/$REPO_OWNER/$REPO_NAME"
private const val RELEASES_URL = "$REPO_URL/releases"
private const val API_LATEST = "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest"

private sealed interface UpdateUi {
    data object Checking : UpdateUi
    data object Latest : UpdateUi
    data class Newer(val tag: String) : UpdateUi
    data class Failed(val why: String) : UpdateUi
}

/** 关于 + 更新：一整页，不是弹窗。 */
@Composable
fun AboutPage(onBack: () -> Unit, glass: Boolean) {
    if (!glass) {
        Box(Modifier.fillMaxSize()) { AboutBody(onBack) }
        return
    }
    GlasmioBackdropHost(modifier = Modifier.fillMaxSize(), sampledContent = { }) { AboutBody(onBack) }
}

@Composable
private fun AboutBody(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val colors = GlasmioTheme.colors
    val selfVer = remember {
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?" }
            .getOrDefault("?")
    }
    var state by remember { mutableStateOf<UpdateUi>(UpdateUi.Checking) }
    var checking by remember { mutableStateOf(true) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(reload) {
        checking = true
        state = UpdateUi.Checking
        val tag = withContext(Dispatchers.IO) { fetchLatestTag() }
        state = when {
            tag == null -> UpdateUi.Failed("连不上 GitHub，稍后再试")
            semverGreater(tag, selfVer) -> UpdateUi.Newer(tag)
            else -> UpdateUi.Latest
        }
        checking = false
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(38.dp).clickable(onClick = onBack),
                contentAlignment = Alignment.Center) {
                SfIcon("chevron.backward", "返回", Modifier.size(20.dp), colors.accent)
            }
            Spacer(Modifier.padding(horizontal = 3.dp))
            Text("关于", style = IosTypography.title3, fontWeight = FontWeight(600), color = colors.content)
        }
        Text("KdKit", style = IosTypography.largeTitle, fontWeight = FontWeight.Bold,
            color = colors.content, modifier = Modifier.padding(top = 10.dp))
        Text("版本 $selfVer · MIT License · 作者 xalor", style = IosTypography.subheadline,
            color = colors.secondaryContent)

        Spacer(Modifier.height(18.dp))
        GlasmioSectionTitle("更新")
        GlasmioGroupedList {
            GlasmioListRow(
                title = when (val s = state) {
                    UpdateUi.Checking -> "正在检查更新…"
                    UpdateUi.Latest -> "已是最新版本"
                    is UpdateUi.Newer -> "有新版本 ${s.tag}"
                    is UpdateUi.Failed -> "检查失败：${s.why}"
                },
                subtitle = "当前 $selfVer · 远端读取 GitHub Releases",
                showTopSeparator = false,
                leading = {
                    if (checking) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    else SfIcon(if (state is UpdateUi.Newer) "arrow.down" else "checkmark", null,
                        Modifier.size(20.dp),
                        if (state is UpdateUi.Newer) colors.accent else colors.secondaryContent)
                },
                onClick = {
                    if (state is UpdateUi.Newer) openUrl(ctx, RELEASES_URL) else reload++
                },
            )
            if (state is UpdateUi.Newer) {
                GlasmioListRow(title = "打开发布页下载", systemName = "safari",
                    onClick = { openUrl(ctx, RELEASES_URL) })
            }
        }

        Spacer(Modifier.height(18.dp))
        GlasmioSectionTitle("项目")
        GlasmioGroupedList {
            GlasmioListRow(title = "项目主页", subtitle = REPO_URL, systemName = "safari",
                showTopSeparator = false, onClick = { openUrl(ctx, REPO_URL) })
            GlasmioListRow(title = "全部版本", systemName = "arrow.up.right",
                onClick = { openUrl(ctx, RELEASES_URL) })
        }

        Spacer(Modifier.height(18.dp))
        GlasmioSectionTitle("兼容")
        GlasmioGroupedList {
            GlasmioListRow(
                title = "快对 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME}",
                subtitle = "基线 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_CODE}；兼容 7.10.0 / 7.9.0 / 内测 1865",
                showTopSeparator = false,
                showDisclosure = false,
            )
            GlasmioListRow(title = "模块", subtitle = "Xposed / LSPosed / Vector，需 root", showDisclosure = false)
        }
        Spacer(Modifier.height(26.dp))
        Text("本模块只修改快对 App 自身的界面与广告加载，不修改服务器数据。",
            style = IosTypography.footnote, color = colors.tertiaryContent)
        Spacer(Modifier.height(80.dp))
    }
}

/* ── 版本与网络 ── */
private val TAG_RE = Regex("\"tag_name\"\\s*:\\s*\"([^\"]+)\"")

private fun versionParts(raw: String): List<Int> =
    raw.trim().removePrefix("v").removePrefix("V").substringBefore('-')
        .split('.').map { it.toIntOrNull() ?: 0 }

private fun semverGreater(a: String, b: String): Boolean {
    val pa = versionParts(a); val pb = versionParts(b)
    for (i in 0 until maxOf(pa.size, pb.size)) {
        val x = pa.getOrNull(i) ?: 0; val y = pb.getOrNull(i) ?: 0
        if (x != y) return x > y
    }
    return false
}

private fun fetchLatestTag(): String? {
    runCatching {
        val conn = (java.net.URL(API_LATEST).openConnection() as java.net.HttpURLConnection).apply {
            requestMethod = "GET"; connectTimeout = 5000; readTimeout = 5000
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", "KdKit-Android")
        }
        try {
            if (conn.responseCode in 200..299)
                TAG_RE.find(conn.inputStream.bufferedReader().use { it.readText() })
                    ?.groupValues?.get(1) else null
        } finally { conn.disconnect() }
    }.getOrNull()?.let { return it }
    return runCatching {
        val conn = (java.net.URL("$REPO_URL/releases/latest").openConnection() as java.net.HttpURLConnection).apply {
            instanceFollowRedirects = false; connectTimeout = 8000; readTimeout = 8000
            setRequestProperty("User-Agent", "KdKit-Android")
        }
        try {
            val loc = conn.getHeaderField("Location") ?: return@runCatching null
            loc.trimEnd('/').substringAfterLast('/').takeIf { it.isNotEmpty() }
        } finally { conn.disconnect() }
    }.getOrNull()
}

private fun openUrl(ctx: Context, url: String) {
    runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
}
