package dev.xalor.kdkit.util

import java.util.concurrent.ConcurrentHashMap

/**
 * 钩子安装台账 —— 回答"这个功能到底挂上了几条钩子、哪一条没挂上"。
 *
 * 为什么需要：`Xp.hook` 失败时只写一行 `hook failed ...` 就返回 false，功能本身照旧"已启用"。
 * 于是宿主改版后最常见的故障形态是：**模块报告 ready，功能静默失效**（29 条目标里少挂 3 条，
 * 日志里只有 3 行 warn 淹没在几千行里）。台账把它变成可机读的结论：
 *
 *     HookCore: ready 25/25 features, hooks 96 ok / 0 failed
 *     失败时：... hooks 93 ok / 3 failed -> RemoveSplashAd:lk.a.j, NavLog:... 
 *
 * `kit/scripts/module_report.py` 与 `check_hook_targets.py` 都可以直接读这两行。
 */
object HookAudit {

    private data class Stat(var ok: Int = 0, var failed: Int = 0, var skipped: Int = 0)

    private val byFeature = ConcurrentHashMap<String, Stat>()
    private val failures = java.util.Collections.synchronizedList(mutableListOf<String>())
    private val skipped = java.util.Collections.synchronizedList(mutableListOf<String>())

    /** 由 [Xp] 在每次 hook 尝试后调用；[owner] 为空表示"不属于任何功能"（框架/共享管道）。 */
    fun record(owner: String?, target: String, ok: Boolean) {
        val key = owner ?: "<shared>"
        val s = byFeature.computeIfAbsent(key) { Stat() }
        synchronized(s) { if (ok) s.ok++ else s.failed++ }
        if (!ok) failures += "$key:$target"
    }

    /**
     * **从未被尝试**的钩子：通常是 `clazzOrNull("…")` 返回 null 后代码直接 return。
     *
     * 为什么单独记：这类既不算 ok 也不算 failed —— 它在台账里**完全隐形**。
     * 表现是"功能已启用、hook 数比预期少几"，而日志里连一行 warn 都没有
     * （`clazzOrNull` 静默返回 null）。这是比 `failed` 更隐蔽的失效形态。
     */
    fun recordSkipped(owner: String?, what: String) {
        val key = owner ?: "<shared>"
        val s = byFeature.computeIfAbsent(key) { Stat() }
        synchronized(s) { s.skipped++ }
        skipped += "$key:$what"
    }

    fun okCount(): Int = byFeature.values.sumOf { it.ok }
    fun failedCount(): Int = byFeature.values.sumOf { it.failed }
    fun skippedCount(): Int = byFeature.values.sumOf { it.skipped }

    /** 从未被尝试的目标（`功能:类`），一行日志点名用。 */
    fun skippedList(): List<String> = synchronized(skipped) { skipped.toList() }

    /** 未挂上的目标（`功能:类.方法`），用于一行日志点名。 */
    fun failureList(): List<String> = synchronized(failures) { failures.toList() }

    /** 每个功能挂了多少条（诊断页/报告用）。 */
    fun perFeature(): Map<String, Pair<Int, Int>> =
        byFeature.entries.associate { it.key to (it.value.ok to it.value.failed) }

    /** 三态明细：功能 -> (ok, failed, skipped)。诊断页用。 */
    fun perFeatureDetail(): Map<String, Triple<Int, Int, Int>> =
        byFeature.entries.associate { it.key to Triple(it.value.ok, it.value.failed, it.value.skipped) }

    fun featuresWithNoHooks(): List<String> =
        byFeature.entries.filter { it.value.ok == 0 }.map { it.key }

    fun summaryLine(totalFeatures: Int, enabledFeatures: Int): String {
        val base = "ready $enabledFeatures/$totalFeatures features, hooks ${okCount()} ok / ${failedCount()} failed"
        val f = failureList()
        val sk = skippedList().distinct()
        val parts = mutableListOf(base)
        if (f.isNotEmpty()) {
            parts += "failed: " + f.take(8).joinToString(", ") + if (f.size > 8) " (+${f.size - 8})" else ""
        }
        // `skipped` = 目标类根本没找到（clazzOrNull 返回 null），连尝试都没有。
        // 不点名的话它完全隐形：hook 数比预期少、日志里一行都没有。
        if (sk.isNotEmpty()) {
            parts += "skipped: " + sk.take(8).joinToString(", ") +
                if (sk.size > 8) " (+${sk.size - 8})" else ""
        }
        return parts.joinToString(" -> ")
    }

    fun reset() {
        byFeature.clear()
        failures.clear()
        // 漏掉这一行会让 skipped 跨 reset 累积 —— JUnit 里表现为"上个测试的失败串到下一个"，
        // 生产里表现为"重载模块后 skipped 列表越来越长"。两边都是真 bug。
        skipped.clear()
    }
}
