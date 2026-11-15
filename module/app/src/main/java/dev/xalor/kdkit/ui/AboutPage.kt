package dev.xalor.kdkit.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import top.yukonga.miuix.kmp.basic.SmallTitle
import top.yukonga.miuix.kmp.preference.ArrowPreference
import top.yukonga.miuix.kmp.theme.MiuixTheme

private sealed interface Ui {
    data object Checking : Ui
    data object Latest : Ui
    data class Newer(val tag: String) : Ui
    data class Failed(val why: String) : Ui
}

/** 关于 + 更新（Miuix）：更新检查是页面里的一行，不弹窗。 */
@Composable
fun AboutPage(onBack: () -> Unit, onReplayOobe: () -> Unit = {}) {
    val c = MiuixTheme.colorScheme
    val ctx = LocalContext.current
    val selfVer = remember {
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?" }
            .getOrDefault("?")
    }
    var state by remember { mutableStateOf<Ui>(Ui.Checking) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(reload) {
        state = Ui.Checking
        val tag = withContext(Dispatchers.IO) { UpdateApi.fetchLatestTag() }
        state = when {
            tag == null -> Ui.Failed("连不上 GitHub，点这里重试")
            UpdateApi.isNewer(tag, selfVer) -> Ui.Newer(tag)
            else -> Ui.Latest
        }
    }

    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()
            .verticalScroll(rememberScrollState()),
    ) {
        // 返回：一行文字就好（用 ArrowPreference 会出现"返回 ›"的怪样子）
        Row(
            Modifier.fillMaxWidth().padding(start = 24.dp, top = 10.dp, bottom = 2.dp),
        ) {
            Text(
                "← 返回", fontSize = 15.sp, color = c.primary,
                modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp),
            )
        }
        Text(
            "关于 KdKit", fontSize = 26.sp, modifier = Modifier.padding(start = 24.dp, top = 8.dp),
            color = c.onSurface,
        )
        Text(
            "版本 $selfVer · MIT · 作者 xalor", fontSize = 12.sp,
            color = c.onSurfaceVariantSummary,
            modifier = Modifier.padding(start = 24.dp, top = 2.dp, bottom = 6.dp),
        )

        SmallTitle("更新")
        GroupCard(Modifier.padding(horizontal = 12.dp)) {
            ArrowPreference(
                title = when (val s = state) {
                    Ui.Checking -> "正在检查更新…"
                    Ui.Latest -> "已是最新版本"
                    is Ui.Newer -> "有新版本 ${s.tag}"
                    is Ui.Failed -> "检查失败：${s.why}"
                },
                summary = "当前 $selfVer · 远端读取 GitHub Releases",
                onClick = {
                    if (state is Ui.Newer) UpdateApi.openReleases(ctx)
                    else if (state !is Ui.Checking) reload++
                },
            )
        }

        SmallTitle("引导")
        GroupCard(Modifier.padding(horizontal = 12.dp)) {
            ArrowPreference(
                title = "重看引导",
                summary = "重新走一遍首次启动的四步说明",
                onClick = onReplayOobe,
            )
        }

        SmallTitle("项目")
        GroupCard(Modifier.padding(horizontal = 12.dp)) {
            ArrowPreference(title = "项目主页", summary = UpdateApi.repoUrl, onClick = {
                UpdateApi.openReleases(ctx)
            })
            ArrowPreference(title = "全部版本", summary = null, onClick = { UpdateApi.openReleases(ctx) })
        }

        SmallTitle("兼容")
        GroupCard(Modifier.padding(horizontal = 12.dp)) {
            Text(
                "基线 快对 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME}" +
                    "（${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_CODE}）",
                fontSize = 14.sp, color = c.onSurface,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            )
            Text(
                "兼容 7.10.0 / 7.9.0 / 内测 1865；需 root + Xposed 框架",
                fontSize = 12.sp, color = c.onSurfaceVariantSummary,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp),
            )
        }
        Spacer(Modifier.height(24.dp))
    }
}
