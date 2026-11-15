package dev.xalor.kdkit.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import dev.xalor.kdkit.ui.theme.LocalKdDark
import top.yukonga.miuix.kmp.theme.MiuixTheme

/**
 * 分组卡片容器（**自己画，不用 miuix 的 `Card`**）。
 *
 * 为什么不用 `Card`：miuix 的 `Surface`（Card 的底层）在**颜色带透明度**时会走一条
 * RenderEffect 路径 —— 那正好撞上小米这版 libhwui 的
 * `MiBackgroundBlurBlend::postUpdateInfo` 崩溃点（2026-11-15 10:02 实测：
 * 换成 `CardDefaults.defaultColors(surfaceContainerHigh)` 之后启动即白屏 + SIGSEGV）。
 *
 * 这里只做三件事：圆角 + 不透明底色 + 内边距。深浅色各给一个**不透明**色值，
 * 保证深色模式下卡片能和页面底色区分开（之前用 miuix 默认色两者几乎同色，
 * 整页看着像"没有卡片"）。
 */
@Composable
fun GroupCard(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val dark = LocalKdDark.current
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(if (dark) Color(0xFF1C1C1E) else Color(0xFFFFFFFF))
            .padding(vertical = 2.dp),
        content = content,
    )
}
