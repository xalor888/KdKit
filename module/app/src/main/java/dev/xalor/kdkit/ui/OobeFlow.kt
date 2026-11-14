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
import com.kyant.shapes.Capsule
import dev.xalor.kdkit.HostVersion
import dev.xalor.kdkit.ui.theme.UiPrefs
import io.github.neoruaa.glasmio.core.GlassColors
import io.github.neoruaa.glasmio.core.GlasmioTheme
import io.github.neoruaa.glasmio.core.IosTypography
import io.github.neoruaa.glasmio.glass.GlasmioBackdropHost
import io.github.neoruaa.glasmio.ui.GlasmioGroupedList
import io.github.neoruaa.glasmio.ui.GlasmioListRow

private enum class Step(val title: String, val caption: String) {
    Welcome("KdKit", "快对 的去广告 / 界面 / 稳定性增强模块"),
    Check("环境检查", "先确认模块在框架里已经生效"),
    Notice("使用说明", "这四条决定了你能用它做什么、做不到什么"),
    Done("准备就绪", "全部开关就在下一页，随时可以改回来"),
}

/**
 * 引导页 v4：转场是 AnimatedContent 的横滑 + 淡入淡出（进 220ms 弹簧、出 180ms），
 * 方向由 `forward` 决定，所以返回是反向滑；进度点用 animateDpAsState 拉长成胶囊。
 */
@Composable
fun OobeFlow(glass: Boolean, onDone: () -> Unit) {
    var step by remember { mutableStateOf(Step.Welcome) }
    var forward by remember { mutableStateOf(true) }
    var agreed by remember { mutableStateOf(false) }
    val go: (Step) -> Unit = { next ->
        forward = next.ordinal >= step.ordinal
        step = next
    }

    if (glass) {
        GlasmioBackdropHost(modifier = Modifier.fillMaxSize(), sampledContent = {
            Column(Modifier.fillMaxSize().background(GlasmioTheme.colors.groupedBackground)) {}
        }) { Body(step, forward, agreed, { agreed = !agreed }, go, onDone) }
    } else {
        Box(Modifier.fillMaxSize().background(GlasmioTheme.colors.groupedBackground)) {
            Body(step, forward, agreed, { agreed = !agreed }, go, onDone)
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.BoxScope.Body(
    step: Step,
    forward: Boolean,
    agreed: Boolean,
    onToggleAgree: () -> Unit,
    go: (Step) -> Unit,
    onDone: () -> Unit,
) {
    val ctx = LocalContext.current
    val colors = GlasmioTheme.colors

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        AnimatedContent(
            targetState = step,
            transitionSpec = {
                val dir = if (forward) 1 else -1
                ContentTransform(
                    targetContentEnter = slideInHorizontally(
                        animationSpec = spring(dampingRatio = 0.92f, stiffness = 500f),
                        initialOffsetX = { it * dir / 6 },
                    ) + fadeIn(tween(160)),
                    initialContentExit = slideOutHorizontally(
                        animationSpec = tween(180), targetOffsetX = { -it * dir / 8 },
                    ) + fadeOut(tween(140)),
                )
            },
            label = "oobe",
            modifier = Modifier.weight(1f),
        ) { s ->
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp)) {
                Spacer(Modifier.height(40.dp))
                Text(s.title,
                    style = if (s == Step.Welcome) IosTypography.largeTitle else IosTypography.title1,
                    fontWeight = FontWeight.Bold, color = colors.content,
                    fontSize = if (s == Step.Welcome) 40.sp else 32.sp)
                Spacer(Modifier.height(8.dp))
                Text(s.caption, style = IosTypography.subheadline, color = colors.secondaryContent)
                Spacer(Modifier.height(22.dp))
                when (s) {
                    Step.Welcome -> GlasmioGroupedList {
                        GlasmioListRow(showTopSeparator = false,
                            title = "默认配置偏向「少广告、少打扰」",
                            subtitle = "每个开关都能单独关掉；标了即时生效的不用重启快对")
                    }
                    Step.Check -> CheckGroup()
                    Step.Notice -> Column {
                        GlasmioGroupedList {
                            GlasmioListRow(showTopSeparator = false, title = "只改快对 App 自身的界面与广告加载", subtitle = "不修改服务器数据")
                            GlasmioListRow(title = "会员 / 付费内容解锁不在范围内", showDisclosure = false)
                            GlasmioListRow(title = "需要 root + Xposed 框架（LSPosed / Vector）", showDisclosure = false)
                            GlasmioListRow(title = "出问题请带 logcat 到 GitHub Issues", showDisclosure = false)
                        }
                        Spacer(Modifier.height(10.dp))
                        Row(Modifier.fillMaxWidth().clickable(onClick = onToggleAgree)
                            .padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(22.dp).clip(Capsule())
                                .background(if (agreed) colors.accent else colors.container),
                                contentAlignment = Alignment.Center) {
                                if (agreed) Text("✓", fontSize = 13.sp, color = Color.White)
                            }
                            Spacer(Modifier.width(10.dp))
                            Text("我已阅读并理解以上说明", style = IosTypography.body, color = colors.content)
                        }
                    }
                    Step.Done -> Column {
                        CheckGroup()
                        Spacer(Modifier.height(10.dp))
                        GlasmioGroupedList {
                            GlasmioListRow(showTopSeparator = false,
                                title = "下一步：开启「去广告」组，再重启一次快对")
                        }
                    }
                }
                Spacer(Modifier.height(28.dp))
            }
        }

        Row(Modifier.fillMaxWidth().padding(bottom = 6.dp),
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Step.entries.forEach { s ->
                val active = s == step
                val w by animateDpAsState(if (active) 18.dp else 6.dp,
                    animationSpec = spring(dampingRatio = 0.85f, stiffness = 600f), label = "dot")
                Box(Modifier.padding(horizontal = 3.dp).width(w).height(6.dp).clip(Capsule())
                    .background(if (active) colors.accent else colors.tertiaryContent.copy(alpha = 0.5f)))
            }
        }

        Column(Modifier.navigationBarsPadding().padding(horizontal = 24.dp, vertical = 12.dp)) {
            PrimaryAction(
                label = when (step) {
                    Step.Welcome -> "开始"
                    Step.Check -> "我已在框架里启用，继续"
                    Step.Notice -> "继续"
                    Step.Done -> "进入设置"
                },
                enabled = step != Step.Notice || agreed,
            ) {
                when (step) {
                    Step.Welcome -> go(Step.Check)
                    Step.Check -> go(Step.Notice)
                    Step.Notice -> go(Step.Done)
                    Step.Done -> { UiPrefs.setOobeDone(ctx, true); onDone() }
                }
            }
            if (step == Step.Check) {
                Text("先跳过检查", style = IosTypography.caption1, color = colors.tertiaryContent,
                    modifier = Modifier.fillMaxWidth().clickable { go(Step.Notice) }
                        .padding(vertical = 10.dp))
            }
        }
    }
}

@Composable
private fun PrimaryAction(label: String, enabled: Boolean, onClick: () -> Unit) {
    val colors = GlasmioTheme.colors
    Box(Modifier.fillMaxWidth().height(52.dp).clip(Capsule())
        .background(if (enabled) colors.accent else colors.accent.copy(alpha = 0.35f))
        .clickable(enabled = enabled, onClick = onClick), contentAlignment = Alignment.Center) {
        Text(label, style = IosTypography.body, color = Color.White, fontWeight = FontWeight(600))
    }
}

@Composable
private fun CheckGroup() {
    val ctx = LocalContext.current
    val health = remember { channelHealth(ctx) }
    GlasmioGroupedList {
        GlasmioListRow(showTopSeparator = false, showDisclosure = false,
            title = "快对版本",
            subtitle = "${HostVersion.BASELINE_VERSION_NAME} / ${HostVersion.BASELINE_VERSION_CODE}",
            systemName = "checkmark")
        GlasmioListRow(showDisclosure = false,
            title = "配置通道",
            subtitle = if (health.ok) health.line else "未发布 —— 在框架里启用模块后重开本应用",
            systemName = if (health.ok) "checkmark" else "xmark")
        GlasmioListRow(showDisclosure = false,
            title = "框架注入", subtitle = if (health.ok) "正常" else "未生效",
            systemName = if (health.ok) "checkmark" else "xmark")
    }
}
