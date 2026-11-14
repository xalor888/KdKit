package dev.xalor.kdkit.ui

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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.xalor.kdkit.HostVersion
import dev.xalor.kdkit.ui.theme.LocalGlass
import dev.xalor.kdkit.ui.theme.UiPrefs

/**
 * 首次启动引导（OOBE）：欢迎 → 环境检查 → 说明 → 完成。
 *
 * 卡片是自绘圆角块（不用 miuix 的 `Card`：它在没有 `Scaffold` 的裸 `Box` 里会被测成 0 高，
 * 这是 2026-11-14 那版白屏的真因）。
 */
private enum class Step { WELCOME, CHECK, NOTICE, DONE }

@Composable
fun Oobe(onDone: () -> Unit) {
    val ctx = LocalContext.current
    val g = LocalGlass.current
    var step by remember { mutableStateOf(Step.WELCOME) }
    var agreed by remember { mutableStateOf(false) }

    val bg = if (g.isDark) Color(0xFF0C0E14) else Color(0xFFF3F4F8)
    val card = if (g.isDark) Color(0xFF1B1F2A) else Color(0xFFFFFFFF)
    val text = if (g.isDark) Color(0xFFEDEFF7) else Color(0xFF16181D)
    val muted = if (g.isDark) Color(0xFF9AA3B2) else Color(0xFF6B7280)
    val accent = if (g.isDark) Color(0xFF8B9DF5) else Color(0xFF3B5BDB)

    Box(Modifier.fillMaxSize().background(bg)) {
        Column(
            Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp),
        ) {
            Spacer(Modifier.height(56.dp))

            Text(
                when (step) {
                    Step.WELCOME -> "KdKit"
                    Step.CHECK -> "环境检查"
                    Step.NOTICE -> "使用说明"
                    Step.DONE -> "准备就绪"
                },
                fontSize = if (step == Step.WELCOME) 42.sp else 30.sp,
                fontWeight = FontWeight.SemiBold,
                color = text,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                when (step) {
                    Step.WELCOME -> "快对 的去广告 / 界面 / 稳定性增强模块"
                    Step.CHECK -> "有两件事模块自己做不到，需要你在框架里点一下"
                    Step.NOTICE -> "下面四条决定了你能用它做什么、做不到什么"
                    Step.DONE -> "全部开关就在下一页，随时可以改回来"
                },
                fontSize = 14.sp, color = muted,
            )
            Spacer(Modifier.height(26.dp))

            when (step) {
                Step.WELCOME -> CardBox(card) {
                    Text("默认配置已经偏向「少广告、少打扰」；每个开关都能单独关掉。",
                        Modifier.padding(18.dp), fontSize = 14.sp, color = text)
                }
                Step.CHECK -> Column(verticalArrangement = Arrangement.spacedBy(10.dp)) { CheckCard(ctx, card, text, muted) }
                Step.NOTICE -> Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    CardBox(card) {
                        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            NoticeLine("只修改快对 App 自身的界面与广告加载，不修改服务器数据", text, accent)
                            NoticeLine("会员 / 付费内容的解锁不在本模块范围内", text, accent)
                            NoticeLine("需要 root + Xposed 框架（LSPector / Vector / LSPosed）", text, accent)
                            NoticeLine("出问题请带 logcat 到 GitHub Issues", text, accent)
                        }
                    }
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).clickable { agreed = !agreed }
                            .padding(vertical = 12.dp, horizontal = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier.size(22.dp).clip(RoundedCornerShape(6.dp))
                                .background(if (agreed) accent else (if (g.isDark) Color(0xFF2A3040) else Color(0xFFE6E8EF))),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (agreed) Text("✓", fontSize = 13.sp, color = Color.White)
                        }
                        Spacer(Modifier.size(10.dp))
                        Text("我已阅读并理解以上说明", fontSize = 14.sp, color = text)
                    }
                }
                Step.DONE -> Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    CheckCard(ctx, card, text, muted)
                    CardBox(card) {
                        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("下一步", fontSize = 13.sp, color = muted)
                            Text("开启「去广告」组里的开关，再重启一次快对。",
                                fontSize = 14.sp, color = text)
                        }
                    }
                }
            }

            Spacer(Modifier.height(30.dp))

            when (step) {
                Step.WELCOME -> Button("开始", accent, true) { step = Step.CHECK }
                Step.CHECK -> {
                    Button("我已在框架里启用，继续", accent, true) { step = Step.NOTICE }
                    Spacer(Modifier.height(8.dp))
                    Ghost("先跳过检查", muted) { step = Step.NOTICE }
                }
                Step.NOTICE -> Button("继续", accent, agreed) { step = Step.DONE }
                Step.DONE -> Button("进入设置", accent, true) {
                    UiPrefs.setOobeDone(ctx, true)
                    onDone()
                }
            }
            Spacer(Modifier.height(72.dp))
        }

        Text(
            "${Step.entries.indexOf(step) + 1} / ${Step.entries.size}",
            modifier = Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 10.dp),
            fontSize = 12.sp, color = muted, textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun CardBox(fill: Color, content: @Composable () -> Unit) {
    Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(fill)) { content() }
}

@Composable
private fun CheckCard(ctx: android.content.Context, card: Color, text: Color, muted: Color) {
    val health = remember { channelHealth(ctx) }
    CardBox(card) {
        Column(Modifier.padding(vertical = 4.dp)) {
            CheckRow("快对版本", "${HostVersion.BASELINE_VERSION_NAME} / ${HostVersion.BASELINE_VERSION_CODE}", true, text, muted)
            CheckRow(
                "配置通道",
                if (health.ok) "已发布" else "未发布 —— 在框架里启用模块后重进本应用",
                health.ok, text, muted,
            )
            CheckRow("框架注入", if (health.ok) "正常" else "未生效", health.ok, text, muted)
        }
    }
}

@Composable
private fun CheckRow(title: String, value: String, ok: Boolean, text: Color, muted: Color) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(if (ok) "✓" else "!", color = if (ok) Color(0xFF34C759) else Color(0xFFFF9500), fontSize = 15.sp)
        Spacer(Modifier.size(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 15.sp, color = text)
            Text(value, fontSize = 12.sp, color = muted)
        }
    }
}

@Composable
private fun NoticeLine(textStr: String, text: Color, accent: Color) {
    Row {
        Text("·", fontSize = 14.sp, color = accent)
        Spacer(Modifier.size(8.dp))
        Text(textStr, fontSize = 14.sp, color = text, lineHeight = 20.sp)
    }
}

@Composable
private fun Button(label: String, accent: Color, enabled: Boolean, onClick: () -> Unit) {
    androidx.compose.material3.Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().height(50.dp),
        shape = RoundedCornerShape(16.dp),
        colors = androidx.compose.material3.ButtonDefaults.buttonColors(
            containerColor = accent,
            contentColor = Color.White,
        ),
    ) {
        Text(label, fontSize = 16.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun Ghost(label: String, muted: Color, onClick: () -> Unit) {
    androidx.compose.material3.TextButton(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth().height(42.dp),
    ) {
        Text(label, fontSize = 14.sp, color = muted)
    }
}
