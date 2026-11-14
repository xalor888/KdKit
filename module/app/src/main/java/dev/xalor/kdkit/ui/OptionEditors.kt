package dev.xalor.kdkit.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption

/**
 * 通用子选项编辑器：设置页不再为每个功能写一遍界面。
 *
 * 由来：模块里已经存在 7 个"代码在读、界面写不了"的键（`pk_mock` / `pk_auto_answer` /
 * `bridge_guard_probe_remove_loading` / `native_exit_guard_control` / `page_js_script` /
 * `bridge_guard_list` / `bridge_guard_http_allow`）。它们只能靠 kit 脚本或手工改 prefs 才能设置。
 * 现在每个键都是 [KdOption]，由功能自己声明，这里按 `kind` 渲染：
 *  * BOOLEAN → 开关行；
 *  * STRING  → 文本框 + 保存（多行不换行、立即写回 app prefs）。
 *
 * `userEditable = false` 的键（目前只有 `page_js_script`）只显示当前值 —— 它由
 * `kit/scripts/call_page_js.py` 写入，手输一段 JS 到手机输入框里没有实际意义。
 */
@Composable
fun OptionsSection(options: List<KdOption>, version: Int, onChange: () -> Unit) {
    if (options.isEmpty()) return
    Column(Modifier.padding(top = 10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        for (o in options) {
            when (o.kind) {
                KdOption.Kind.BOOLEAN -> BooleanOptionRow(o, version, onChange)
                KdOption.Kind.STRING -> StringOptionRow(o, version, onChange)
            }
        }
    }
}

@Composable
private fun BooleanOptionRow(o: KdOption, version: Int, onChange: () -> Unit) {
    val ctx = LocalContext.current
    val checked = remember(o.key, version) { KdConfig.isOn(o.key, o.defaultBool) }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(o.title, style = MaterialTheme.typography.bodyMedium)
            Text(
                o.summary,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Switch(
            checked = checked,
            onCheckedChange = { v ->
                KdConfig.setApp(ctx, o.key, v)
                onChange()
            },
        )
    }
}

@Composable
private fun StringOptionRow(o: KdOption, version: Int, onChange: () -> Unit) {
    val ctx = LocalContext.current
    var text by remember(o.key, version) { mutableStateOf(KdConfig.getString(o.key, o.default)) }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(o.title, style = MaterialTheme.typography.bodyMedium)
        Text(
            o.summary,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (!o.userEditable) {
            Text(
                "当前值：${KdConfig.getString(o.key, o.default).ifBlank { "（空）" }}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return
        }
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            placeholder = { Text(o.default.ifBlank { "（空）" }) },
            shape = RoundedCornerShape(12.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                KdConfig.setAppString(ctx, o.key, text.trim())
                onChange()
            }) { Text("保存") }
            OutlinedButton(onClick = {
                text = o.default
                KdConfig.setAppString(ctx, o.key, o.default)
                onChange()
            }) { Text("恢复默认") }
        }
    }
}
