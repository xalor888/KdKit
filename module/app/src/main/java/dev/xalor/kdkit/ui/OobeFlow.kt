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
import dev.xalor.kdkit.ui.theme.IosColors
import dev.xalor.kdkit.ui.theme.LocalIos
import dev.xalor.kdkit.ui.theme.UiPrefs

private enum class Step(val title: String, val caption: String) {
    Welcome("KdKit", "快对 的去广告 / 界面 / 稳定性增强模块"),
    Check("环境检查", "先确认模块在框架里已经生效"),
    Notice("使用说明", "这四条决定了你能用它做什么、做不到什么"),
    Done("准备就绪", "全部开关就在下一页，随时可以改回来"),
}

/**
 * 引导页：一步一屏，横向弹簧转场 + 进度点拉长。
 *
 * 转场参数：进 220ms 弹簧（damping 0.92 / stiffness 500），出 180ms 线性滑出 + 淡出；
 * 前进/后退方向由 `forward` 决定，所以返回是反向滑。
 */
@Composable
fun OobeFlow(onDone: () -> Unit) {
    val ios = LocalIos.current
    var step by remember { mutableStateOf(Step.Welcome) }
    var forward by remember { mutableStateOf(true) }
    var agreed by remember { mutableStateOf(false) }
    val go: (Step) -> Unit = { n -> forward = n.ordinal >= step.ordinal; step = n }
    val ctx = LocalContext.current

    Column(Modifier.fillMaxSize().background(ios.groupedBg).statusBarsPadding()) {
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
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp)) {
                Spacer(Modifier.height(36.dp))
                Text(s.title, fontSize = if (s == Step.Welcome) 40.sp else 30.sp,
                    fontWeight = FontWeight.Bold, color = ios.content)
                Spacer(Modifier.height(6.dp))
                Text(s.caption, fontSize = 14.sp, color = ios.secondary)
                Spacer(Modifier.height(22.dp))
                when (s) {
                    Step.Welcome -> InfoCard(ios) {
                        Line("默认配置偏向「少广告、少打扰」", ios)
                        Line("每个开关都能单独关掉；标了即时生效的不用重启快对", ios, muted = true)
                    }
                    Step.Check -> CheckCard(ios)
                    Step.Notice -> Column {
                        InfoCard(ios) {
                            Line("只改快对 App 自身的界面与广告加载", ios, bold = true)
                            Line("不修改服务器数据", ios, muted = true)
                            Divider(ios)
                            Line("会员 / 付费内容解锁不在范围内", ios)
                            Line("需要 root + Xposed 框架（LSPosed / Vector）", ios)
                            Line("出问题请带 logcat 到 GitHub Issues", ios)
                        }
                        Spacer(Modifier.height(12.dp))
                        Row(Modifier.fillMaxWidth().clickable { agreed = !agreed }.padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(22.dp).clip(RoundedCornerShape(50))
                                .background(if (agreed) ios.accent else ios.card),
                                contentAlignment = Alignment.Center) {
                                if (agreed) Text("✓", fontSize = 13.sp, color = Color.White)
                            }
                            Spacer(Modifier.width(10.dp))
                            Text("我已阅读并理解以上说明", fontSize = 15.sp, color = ios.content)
                        }
                    }
                    Step.Done -> Column {
                        CheckCard(ios)
                        Spacer(Modifier.height(12.dp))
                        InfoCard(ios) { Line("下一步：开启「去广告」组，再重启一次快对", ios) }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }

        Row(Modifier.fillMaxWidth().padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Step.entries.forEach { s ->
                val active = s == step
                val w by animateDpAsState(if (active) 18.dp else 6.dp,
                    spring(dampingRatio = 0.85f, stiffness = 600f), label = "dot")
                Box(Modifier.padding(horizontal = 3.dp).width(w).height(6.dp)
                    .clip(RoundedCornerShape(50))
                    .background(if (active) ios.accent else ios.tertiary))
            }
        }

        Column(Modifier.navigationBarsPadding().padding(horizontal = 20.dp, vertical = 12.dp)) {
            PrimaryButton(
                when (step) {
                    Step.Welcome -> "开始"
                    Step.Check -> "我已在框架里启用，继续"
                    Step.Notice -> "继续"
                    Step.Done -> "进入设置"
                },
                enabled = step != Step.Notice || agreed, ios = ios,
            ) {
                when (step) {
                    Step.Welcome -> go(Step.Check)
                    Step.Check -> go(Step.Notice)
                    Step.Notice -> go(Step.Done)
                    Step.Done -> { UiPrefs.setOobeDone(ctx, true); onDone() }
                }
            }
            if (step == Step.Check) {
                Text("先跳过检查", fontSize = 13.sp, color = ios.secondary,
                    modifier = Modifier.fillMaxWidth().clickable { go(Step.Notice) }.padding(vertical = 10.dp))
            }
        }
    }
}

@Composable
private fun InfoCard(ios: IosColors, content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(ios.card)
        .padding(horizontal = 16.dp, vertical = 14.dp), content = content)
}

@Composable
private fun androidx.compose.foundation.layout.ColumnScope.Line(text: String, ios: IosColors,
                                                                bold: Boolean = false, muted: Boolean = false) {
    Text(text, fontSize = if (bold) 16.sp else 14.sp,
        fontWeight = if (bold) FontWeight.SemiBold else FontWeight.Normal,
        color = if (muted) ios.secondary else ios.content,
        modifier = Modifier.padding(vertical = 5.dp))
}

@Composable
private fun androidx.compose.foundation.layout.ColumnScope.Divider(ios: IosColors) {
    Box(Modifier.fillMaxWidth().height(1.dp).background(ios.separator).padding(vertical = 6.dp))
}

@Composable
private fun CheckCard(ios: IosColors) {
    val ctx = LocalContext.current
    val health = remember { channelHealth(ctx) }
    InfoCard(ios) {
        StateLine("快对版本", "${HostVersion.BASELINE_VERSION_NAME} / ${HostVersion.BASELINE_VERSION_CODE}", true, ios)
        Divider(ios)
        StateLine("配置通道", if (health.ok) health.line else "未发布 —— 在框架里启用模块后重开本应用",
            health.ok, ios)
        Divider(ios)
        StateLine("框架注入", if (health.ok) "正常" else "未生效", health.ok, ios)
    }
}

@Composable
private fun androidx.compose.foundation.layout.ColumnScope.StateLine(
    name: String, value: String, ok: Boolean, ios: IosColors,
) {
    Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(name, fontSize = 15.sp, color = ios.content, modifier = Modifier.weight(1f))
        Text(if (ok) "✓ " else "✕ ", fontSize = 13.sp, color = if (ok) ios.accent else ios.destructive)
        Text(value, fontSize = 12.sp, color = ios.secondary)
    }
}

@Composable
private fun PrimaryButton(label: String, enabled: Boolean, ios: IosColors, onClick: () -> Unit) {
    Box(Modifier.fillMaxWidth().height(50.dp).clip(RoundedCornerShape(14.dp))
        .background(if (enabled) ios.accent else ios.accent.copy(alpha = 0.35f))
        .clickable(enabled = enabled, onClick = onClick), contentAlignment = Alignment.Center) {
        Text(label, fontSize = 16.sp, color = Color.White, fontWeight = FontWeight.SemiBold)
    }
}
