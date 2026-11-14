package dev.xalor.kdkit

import dev.xalor.kdkit.util.PageRequestOrigin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `PageRequestOrigin` 的离线单测 —— `page_request_log` 观测点把什么写进抓取。
 *
 * 全部可在无设备、无宿主 APK 的情况下复跑（门禁 ①）。它们证明的是
 * **给定输入会写出什么行**，不证明"真机上页面真的会驱动这个 action" ——
 * 后者标 `未验证`（见 `module/VERIFICATION.md` 的「真机」列与 `ACTIVITY.md`）。
 */
class PageRequestOriginTest {

    // ── actionOf：匿名编号必须剥掉，具名内部类必须保留 ──────────────────────

    @Test
    fun `anonymous numeric suffix is stripped`() {
        // 这正是 smali 里 dr.f.a 首参的实际形态：
        //   EncryptDataRequestAction$1 implements dr/f$e
        assertEquals(
            "EncryptDataRequestAction",
            PageRequestOrigin.actionOf(
                "com.kuaiduizuoye.scan.web.actions.EncryptDataRequestAction\$1"),
        )
    }

    @Test
    fun `descriptor style path is handled too`() {
        assertEquals(
            "EncryptDataRequestAction",
            PageRequestOrigin.actionOf(
                "com/kuaiduizuoye/scan/web/actions/EncryptDataRequestAction\$1"),
        )
    }

    @Test
    fun `multi digit anonymous suffix is stripped`() {
        assertEquals("Foo", PageRequestOrigin.actionOf("com.x.Foo\$12"))
    }

    @Test
    fun `named inner class is preserved`() {
        // 一刀切 substringBefore('$') 会把 Failure 与 Success 合并成同一个来源 ——
        // 那样"哪个分支发的请求"就永远查不出来。
        assertEquals("Foo\$Failure", PageRequestOrigin.actionOf("com.x.Foo\$Failure"))
        assertEquals("Foo\$Companion", PageRequestOrigin.actionOf("com.x.Foo\$Companion"))
    }

    @Test
    fun `named inner then anonymous keeps the named part`() {
        assertEquals("Foo\$Failure", PageRequestOrigin.actionOf("com.x.Foo\$Failure\$1"))
    }

    @Test
    fun `plain class without inner suffix`() {
        assertEquals("CoreHttpRequestAction", PageRequestOrigin.actionOf("com.x.CoreHttpRequestAction"))
    }

    @Test
    fun `null and blank are unknown not invented`() {
        // 不编造来源：拿不到就写 (unknown)，让读者知道这一格**没有**证据。
        assertEquals(PageRequestOrigin.UNKNOWN, PageRequestOrigin.actionOf(null))
        assertEquals(PageRequestOrigin.UNKNOWN, PageRequestOrigin.actionOf(""))
        assertEquals(PageRequestOrigin.UNKNOWN, PageRequestOrigin.actionOf("   "))
    }

    // ── redactUrl：与 DecodeRequestShape 同一口径（不是各写一遍） ────────────

    @Test
    fun `url query is stripped`() {
        assertEquals(
            "api.example.com/kdapi/x",
            PageRequestOrigin.redactUrl("https://api.example.com/kdapi/x?token=SECRET&uid=42"),
        )
    }

    @Test
    fun `redactUrl delegates to the same implementation`() {
        // 防"同一规则两处实现"漂移：若哪天有人在这里另写一份，这条会立刻红。
        val samples = listOf(
            "https://a.example.com/p/q?t=1#f",
            "/relative/path?x=2",
            "",
            "https://h.example.com/very/long/" + "z".repeat(200),
        )
        for (s in samples) {
            assertEquals(
                "redactUrl 与 DecodeRequestShape 不一致：$s",
                dev.xalor.kdkit.util.DecodeRequestShape.redactUrl(s),
                PageRequestOrigin.redactUrl(s),
            )
        }
    }

    // ── paramsShape：只记键，不记值 ─────────────────────────────────────────

    @Test
    fun `params shape records keys sorted and never values`() {
        val shape = PageRequestOrigin.paramsShape(listOf("uid", "token", "q"))
        assertEquals("keys=3:q,token,uid", shape)
        assertFalse("绝不能把值写进去", shape.contains("SECRET"))
    }

    @Test
    fun `empty and null params are distinguished`() {
        assertEquals("0", PageRequestOrigin.paramsShape(emptyList()))
        // null = 页面没传（形参为 null），与"传了空对象"是两条不同路径，不能合并。
        assertEquals("not-object", PageRequestOrigin.paramsShape(null))
    }

    @Test
    fun `many keys are truncated with a count`() {
        val keys = (1..10).map { "k$it" }
        val shape = PageRequestOrigin.paramsShape(keys)
        assertTrue("应带上总数，否则读者以为只有 6 个：$shape", shape.contains("keys=10"))
        assertTrue("应显示被截断：$shape", shape.contains("…"))
    }

    @Test
    fun `shape is stable regardless of input order`() {
        // HashSet/HashMap 的遍历顺序不稳定；不排序会让同一请求产生两行不同记录。
        val a = PageRequestOrigin.paramsShape(listOf("b", "a", "c"))
        val b = PageRequestOrigin.paramsShape(listOf("c", "b", "a"))
        assertEquals(a, b)
    }

    // ── line：前缀与字段名是契约 ────────────────────────────────────────────

    @Test
    fun `line carries the from field so sources are greppable`() {
        val line = PageRequestOrigin.line("EncryptDataRequestAction", "h.example.com/p", "keys=1:a")
        // **独立前缀 `PAGEREQ`**，不是 `BRIDGE pageRequest`。
        //
        // 为什么不用 `BRIDGE`：`capture_schema.PREFIX_FEATURE` 由 `setdefault` 派生，
        // 一个 token 只能归属一个功能，而 `BRIDGE` 已属于 `bridge_action_log`。
        // 复用会让两个功能的行混在同一前缀下，`grep BRIDGE` 不再等于
        // "bridge_action_log 的记录" —— 归属清晰比前缀复用重要。
        //
        // 这条断言原先写的是 `BRIDGE pageRequest`（旧设计），实现改成 `PAGEREQ` 后
        // 测试没跟着改，于是红了。**红的原因是实现更新、测试过期**，不是代码有 bug。
        assertEquals(
            "PAGEREQ from=EncryptDataRequestAction url=h.example.com/p params=keys=1:a method=?",
            line,
        )
        assertTrue(line.startsWith("PAGEREQ "))
    }

    @Test
    fun `method is always emitted even when unknown`() {
        // `method` 由 `line()` 自己拼，不留给调用方 —— 曾经是两段拼接
        // （`line(…) + " method=$method"`），漏写就静默变成 UNKNOWN 行。
        //
        // 这里钉住三种情况：已知 0 / 已知 1 / 未知。**未知也必须写出 `?`**，
        // 因为 schema 的正则要求这个字段存在（`method=(?P<meth>-?[0-9]+|\?)`）。
        assertEquals(
            "PAGEREQ from=A url=u params=p method=0",
            PageRequestOrigin.line("A", "u", "p", 0),
        )
        assertEquals(
            "PAGEREQ from=A url=u params=p method=1",
            PageRequestOrigin.line("A", "u", "p", 1),
        )
        // 注意 JUnit 的参数顺序：assertTrue(message, condition)，消息在前。
        assertTrue(
            "拿不到 method 时必须写 ?，不能省略字段（省略会让整行落 UNKNOWN）",
            PageRequestOrigin.line("A", "u", "p", null).endsWith(" method=?"),
        )
    }
}
