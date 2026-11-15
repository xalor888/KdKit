package dev.xalor.kdkit.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.ContentTransform
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.HostVersion
import dev.xalor.kdkit.ui.theme.UiPrefs
import top.yukonga.miuix.kmp.basic.Card
import top.yukonga.miuix.kmp.basic.SmallTitle
import top.yukonga.miuix.kmp.basic.Button
import top.yukonga.miuix.kmp.basic.ButtonDefaults
import top.yukonga.miuix.kmp.theme.MiuixTheme

private enum class Step(val title: String, val caption: String) {
    Welcome("KdKit", "快对 的去广告 / 界面 / 稳定性增强模块"),
    Check("环境检查", "先确认模块在框架里已经生效"),
    Notice("使用说明", "这四条决定了你能用它做什么、做不到什么"),
    Done("准备就绪", "全部开关就在下一页，随时可以改回来"),
}

/**
 * 引导页（Miuix 版）：一步一屏，横向弹簧转场 + 进度点拉长。
 *
 * 转场：进 220ms 弹簧（damping .92 / stiffness 500）+ 淡入，出 180ms 滑出 + 淡出；
 * 前进/后退方向由 `forward` 决定，所以返回是反向滑。
 */
@Composable
fun OobeFlow(onDone: () -> Unit) {
    val c = MiuixTheme.colorScheme
    val ctx = LocalContext.current
    var step by remember { mutableStateOf(Step.Welcome) }
    var forward by remember { mutableStateOf(true) }
    var agreed by remember { mutableStateOf(false) }
    val go: (Step) -> Unit = { n -> forward = n.ordinal >= step.ordinal; step = n }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        AnimatedContent(
            targetState = step,
            transitionSpec = {
                val dir = if (forward) 1 else -1
                ContentTransform(
                    targetContentEnter = slideInHorizontally(
                        spring(dampingRatio = 0.92f, stiffness = 500f), { it * dir / 5 },
                    ) + fadeIn(tween(160)),
                    initialContentExit = slideOutHorizontally(tween(180), { -it * dir / 7 }) + fadeOut(tween(140)),
                )
            },
            label = "oobe", modifier = Modifier.weight(1f),
        ) { s ->
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                Spacer(Modifier.height(30.dp))
                Text(
                    s.title,
                    fontSize = if (s == Step.Welcome) 34.sp else 26.sp,
                    fontWeight = FontWeight.Bold,
                    color = c.onSurface,
                    modifier = Modifier.padding(horizontal = 24.dp),
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    s.caption, fontSize = 14.sp, color = c.onSurfaceVariantSummary,
                    modifier = Modifier.padding(horizontal = 24.dp),
                )
                Spacer(Modifier.height(18.dp))
                when (s) {
                    Step.Welcome -> {
                        SmallTitle("默认")
                        Card(Modifier.padding(horizontal = 12.dp)) {
                            InfoLine("配置偏向「少广告、少打扰」")
                            InfoLine("每个开关都能单独关掉；即时生效的不用重启快对", muted = true)
                        }
                    }
                    Step.Check -> CheckCard()
                    Step.Notice -> {
                        SmallTitle("使用说明")
                        Card(Modifier.padding(horizontal = 12.dp)) {
                            InfoLine("只改快对 App 自身的界面与广告加载")
                            InfoLine("不修改服务器数据", muted = true)
                            InfoLine("会员 / 付费内容解锁不在范围内")
                            InfoLine("需要 root + Xposed 框架（LSPosed / Vector）")
                            InfoLine("出问题请带 logcat 到 GitHub Issues")
                        }
                        Spacer(Modifier.height(8.dp))
                        Card(Modifier.padding(horizontal = 12.dp)) {
                            Row(
                                Modifier.fillMaxWidth().clickable { agreed = !agreed }
                                    .padding(horizontal = 16.dp, vertical = 14.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Box(
                                    Modifier.size(20.dp).clip(RoundedCornerShape(50))
                                        .background(if (agreed) c.primary else c.surfaceContainerHigh),
                                    contentAlignment = Alignment.Center,
                                ) { if (agreed) Text("✓", fontSize = 12.sp, color = Color.White) }
                                Spacer(Modifier.width(10.dp))
                                Text("我已阅读并理解以上说明", fontSize = 15.sp, color = c.onSurface)
                            }
                        }
                    }
                    Step.Done -> {
                        CheckCard()
                        Spacer(Modifier.height(8.dp))
                        Card(Modifier.padding(horizontal = 12.dp)) {
                            InfoLine("下一步：开启「去广告」组，再重启一次快对")
                        }
                    }
                }
                Spacer(Modifier.height(20.dp))
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(vertical = 6.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Step.entries.forEach { s ->
                val active = s == step
                val w by animateDpAsState(
                    if (active) 18.dp else 6.dp,
                    spring(dampingRatio = 0.85f, stiffness = 600f), label = "dot",
                )
                Box(
                    Modifier.padding(horizontal = 3.dp).width(w).height(6.dp)
                        .clip(RoundedCornerShape(50))
                        .background(if (active) c.primary else c.outline),
                )
            }
        }

        Column(Modifier.navigationBarsPadding().padding(horizontal = 20.dp, vertical = 10.dp)) {
            Button(
                onClick = {
                    when (step) {
                        Step.Welcome -> go(Step.Check)
                        Step.Check -> go(Step.Notice)
                        Step.Notice -> go(Step.Done)
                        Step.Done -> { UiPrefs.setOobeDone(ctx, true); onDone() }
                    }
                },
                enabled = step != Step.Notice || agreed,
                colors = ButtonDefaults.buttonColorsPrimary(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    when (step) {
                        Step.Welcome -> "开始"
                        Step.Check -> "我已在框架里启用，继续"
                        Step.Notice -> "继续"
                        Step.Done -> "进入设置"
                    },
                    fontSize = 16.sp,
                )
            }
            if (step == Step.Check) {
                Text(
                    "先跳过检查", fontSize = 13.sp, color = c.onSurfaceVariantSummary,
                    modifier = Modifier.fillMaxWidth().clickable { go(Step.Notice) }
                        .padding(vertical = 10.dp),
                )
            }
        }
    }
}

@Composable
private fun InfoLine(text: String, muted: Boolean = false) {
    val c = MiuixTheme.colorScheme
    Text(
        text, fontSize = 14.sp,
        color = if (muted) c.onSurfaceVariantSummary else c.onSurface,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp),
    )
}

@Composable
private fun CheckCard() {
    val c = MiuixTheme.colorScheme
    val ctx = LocalContext.current
    val health = remember { channelHealth(ctx) }
    SmallTitle("环境")
    Card(Modifier.padding(horizontal = 12.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("快对版本", fontSize = 15.sp, color = c.onSurface, modifier = Modifier.weight(1f))
            Text(
                "${HostVersion.BASELINE_VERSION_NAME} / ${HostVersion.BASELINE_VERSION_CODE}",
                fontSize = 12.sp, color = c.onSurfaceVariantSummary,
            )
        }
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("配置通道", fontSize = 15.sp, color = c.onSurface, modifier = Modifier.weight(1f))
            Text(
                if (health.ok) "✓" else "✕",
                fontSize = 13.sp,
                color = if (health.ok) c.primary else c.error,
            )
        }
        if (!health.ok) {
            Text(
                health.line, fontSize = 12.sp, color = c.onSurfaceVariantSummary,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
            )
        }
    }
}
