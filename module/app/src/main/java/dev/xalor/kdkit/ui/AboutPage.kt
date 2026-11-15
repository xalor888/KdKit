package dev.xalor.kdkit.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.ui.theme.IosColors
import dev.xalor.kdkit.ui.theme.LocalIos
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

private sealed interface Ui {
    data object Checking : Ui
    data object Latest : Ui
    data class Newer(val tag: String) : Ui
    data class Failed(val why: String) : Ui
}

/** 关于 + 更新：整页，不弹窗。 */
@Composable
fun AboutPage(onBack: () -> Unit) {
    val ios = LocalIos.current
    val ctx = LocalContext.current
    val selfVer = remember {
        runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?" }
            .getOrDefault("?")
    }
    var state by remember { mutableStateOf<Ui>(Ui.Checking) }
    var checking by remember { mutableStateOf(true) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(reload) {
        checking = true; state = Ui.Checking
        val tag = withContext(Dispatchers.IO) { UpdateApi.fetchLatestTag() }
        state = when {
            tag == null -> Ui.Failed("连不上 GitHub，点这里重试")
            UpdateApi.isNewer(tag, selfVer) -> Ui.Newer(tag)
            else -> Ui.Latest
        }
        checking = false
    }

    Column(Modifier.fillMaxSize().background(ios.groupedBg).statusBarsPadding()
        .verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("← 关于", fontSize = 16.sp, color = ios.accent,
                modifier = Modifier.clickable(onClick = onBack).padding(vertical = 6.dp))
        }
        Text("KdKit", fontSize = 34.sp, fontWeight = FontWeight.Bold, color = ios.content,
            modifier = Modifier.padding(top = 6.dp))
        Text("版本 $selfVer · MIT · 作者 xalor", fontSize = 13.sp, color = ios.secondary)

        SectionTitle("更新", ios)
        Card(ios) {
            Row(Modifier.fillMaxWidth().clickable {
                if (state is Ui.Newer) UpdateApi.openReleases(ctx)
                else if (state !is Ui.Checking) reload++
            }.padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                if (checking) CircularProgressIndicator(Modifier.height(18.dp).padding(end = 10.dp),
                    strokeWidth = 2.dp)
                Column(Modifier.weight(1f)) {
                    Text(
                        when (val s = state) {
                            Ui.Checking -> "正在检查更新…"
                            Ui.Latest -> "已是最新版本"
                            is Ui.Newer -> "有新版本 ${s.tag}"
                            is Ui.Failed -> "检查失败：${s.why}"
                        },
                        fontSize = 16.sp, color = ios.content,
                    )
                    Text("当前 $selfVer · 远端读取 GitHub Releases", fontSize = 12.sp, color = ios.secondary)
                }
            }
        }

        SectionTitle("项目", ios)
        Card(ios) {
            LinkRow("项目主页", UpdateApi.repoUrl, ios) { UpdateApi.openReleases(ctx) }
            Box(Modifier.fillMaxWidth().padding(start = 16.dp).height(1.dp).background(ios.separator))
            LinkRow("全部版本", null, ios) { UpdateApi.openReleases(ctx) }
        }

        SectionTitle("兼容", ios)
        Card(ios) {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 14.dp)) {
                Column {
                    Text("快对 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_NAME}", fontSize = 16.sp, color = ios.content)
                    Text("基线 ${dev.xalor.kdkit.HostVersion.BASELINE_VERSION_CODE}；兼容 7.10.0 / 7.9.0 / 1865",
                        fontSize = 12.sp, color = ios.secondary)
                }
            }
        }
        Spacer(Modifier.height(20.dp))
        Text("本模块只修改快对 App 自身的界面与广告加载，不修改服务器数据。",
            fontSize = 12.sp, color = ios.secondary)
        Spacer(Modifier.height(40.dp))
    }
}

@Composable
private fun SectionTitle(t: String, ios: IosColors) {
    Text(t, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = ios.secondary,
        modifier = Modifier.padding(top = 20.dp, bottom = 6.dp))
}

@Composable
private fun Card(ios: IosColors, content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ios.card), content = content)
}

@Composable
private fun LinkRow(title: String, subtitle: String?, ios: IosColors, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp)) {
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 16.sp, color = ios.content)
            if (subtitle != null) Text(subtitle, fontSize = 12.sp, color = ios.secondary)
        }
        Text("›", fontSize = 18.sp, color = ios.tertiary)
    }
}
