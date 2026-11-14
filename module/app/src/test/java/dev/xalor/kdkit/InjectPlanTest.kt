package dev.xalor.kdkit

import dev.xalor.kdkit.features.web.InjectPlan
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 页面注入的两件纯逻辑（2026-11-02，代码审查 B1）。
 *
 * 原来这里写着“`WebInjector` 依赖 `WebView`/`Handler`/`Looper`/`KdConfig`，
 * JVM 里加载不起来” —— 2026-11-03 证明**那句只对 `install()` 成立**：
 * `register()` / `providerNames()` 只碰一个 MutableList，object 的静态初始化也是纯的，
 * 类在 JVM 里加载得好好的。见 `WebInjectorRegistryTest`。
 * ⇒ "拼脚本"与"去重键"零覆盖。这里只测纯函数，不假装测了 `evaluateJavascript`。
 */
class InjectPlanTest {

    // ── compose ──────────────────────────────────────────────────────────────

    @Test
    fun `no user js keeps payload untouched`() {
        val p = "console.log('a')"
        assertEquals(p, InjectPlan.compose(p, ""))
        assertEquals("纯空白也算没有", p, InjectPlan.compose(p, "   \n\t "))
    }

    @Test
    fun `user js is separated by a semicolon on its own line`() {
        assertEquals(
            "A();\n;\nB()",
            InjectPlan.compose("A();", "B()"),
        )
    }

    /**
     * 分隔符必须是**分号**，不是裸换行。
     *
     * 典型翻车形态：功能片段以 `}` 结尾、用户片段以 `(` 开头，
     * 用 `"\n"` 拼接会被 JS 解析成 `}(…)` 调用，整段脚本在第一个括号处报语法错，
     * 症状是"注入失败但没有任何日志"。
     */
    @Test
    fun `bare newline would be unsafe here`() {
        val payload = "(function(){var x=1;})()"
        val userJs = "(function(){var y=2;})()"
        val joined = InjectPlan.compose(payload, userJs)
        assertTrue("必须含 `\\n;\\n` 分隔", joined.contains("\n;\n"))
        assertFalse("不能只是换行", joined == "$payload\n$userJs")
    }

    @Test
    fun `payload and user js both empty stays empty`() {
        assertEquals("", InjectPlan.compose("", ""))
        assertFalse("空代码不该被当成需要注入", InjectPlan.compose("", "").isNotBlank())
    }

    @Test
    fun `empty payload with user js does not start with a separator`() {
        assertEquals("B()", InjectPlan.compose("", "B()").trimStart())
    }

    // ── dedupeKey ────────────────────────────────────────────────────────────

    @Test
    fun `same webview and url map to the same key`() {
        assertEquals(
            InjectPlan.dedupeKey(1234, "https://a.example/p?x=1"),
            InjectPlan.dedupeKey(1234, "https://a.example/p?x=1"),
        )
    }

    @Test
    fun `different url means a different key`() {
        assertNotEquals(
            InjectPlan.dedupeKey(1234, "https://a.example/p?x=1"),
            InjectPlan.dedupeKey(1234, "https://a.example/p?x=2"),
        )
    }

    @Test
    fun `different webview means a different key`() {
        assertNotEquals(
            InjectPlan.dedupeKey(1, "https://a.example/p"),
            InjectPlan.dedupeKey(2, "https://a.example/p"),
        )
    }

    /**
     * 键里必须能区分"实例号 + URL"，不能只是拼接后恰好相等。
     * 反例：`1` + `"2@u"` 与 `12` + `"@u"` 都拼成 `12@u`。
     */
    @Test
    fun `key cannot be forged by moving characters across the seam`() {
        assertNotEquals(
            InjectPlan.dedupeKey(1, "2@u"),
            InjectPlan.dedupeKey(12, "@u"),
        )
    }
}
