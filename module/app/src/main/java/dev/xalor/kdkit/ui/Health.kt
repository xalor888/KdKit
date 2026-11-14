package dev.xalor.kdkit.ui

import android.content.Context
import java.io.File

data class Health(val ok: Boolean, val line: String)

/** 读 publisher 写下的状态文件（filesDir/kdkit_status.txt）。 */
internal fun channelHealth(ctx: Context): Health {
    val f = File(ctx.filesDir, "kdkit_status.txt")
    if (!f.isFile) return Health(false, "还没有发布过配置：在框架里启用模块，再打开一次本应用")
    val text = runCatching { f.readText() }.getOrNull() ?: return Health(false, "状态文件读不出来")
    val flags = text.lineSequence().firstOrNull { it.startsWith("flags=") }
        ?.removePrefix("flags=")?.trim()?.toIntOrNull() ?: 0
    val ts = text.lineSequence().firstOrNull { it.startsWith("ts=") }
        ?.removePrefix("ts=")?.trim()?.toLongOrNull() ?: 0L
    val days = if (ts > 0) (System.currentTimeMillis() - ts) / 86_400_000L else Long.MAX_VALUE
    return when {
        flags < 1 -> Health(false, "发布过但 0 条开关 —— 点「修复」重发")
        days > 7 -> Health(false, "上次发布是 $days 天前，可能已过期")
        else -> Health(true, "已发布 $flags 条开关（${days} 天前）")
    }
}
