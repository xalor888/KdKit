package dev.xalor.kdkit

import dev.xalor.kdkit.util.DecodeRequestShape
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * `DecodeRequestShape` 的离线单测 —— 覆盖 `decode_httpRequest` 观测点的四个判断。
 *
 * 这些断言全部可以在没有设备、没有宿主 APK 的情况下复跑（JVM 单测，门禁 ①）。
 * 它们证明的是"给定输入，我们会写出什么行"，**不**证明"真机上页面真的会调它" ——
 * 后者标 `未验证`。把静态推导写成已验证，是这个项目最反复踩的坑。
 */
class DecodeRequestShapeTest {

    // ── redactUrl：必须剥掉 query 与 fragment ───────────────────────────────

    @Test
    fun `query is stripped because it carries credentials`() {
        assertEquals(
            "api.example.com/kdapi/exam/detail",
            DecodeRequestShape.redactUrl("https://api.example.com/kdapi/exam/detail?token=SECRET&uid=42"),
        )
    }

    @Test
    fun `fragment is stripped before query`() {
        // 顺序错了会把 `#` 之后的内容残留下来 —— 这条就是防那个。
        assertEquals(
            "h.example.com/a",
            DecodeRequestShape.redactUrl("https://h.example.com/a?x=1#/frag?token=SECRET"),
        )
    }

    @Test
    fun `relative path has no host`() {
        assertEquals("/api/x", DecodeRequestShape.redactUrl("/api/x?token=SECRET"))
    }

    @Test
    fun `empty url is explicit not blank`() {
        // 空串必须写成 `(empty)`：一行 `url= ` 在抓取里和"解析失败"没法区分。
        assertEquals("(empty)", DecodeRequestShape.redactUrl(""))
    }

    @Test
    fun `host without path gets a slash`() {
        assertEquals("h.example.com/", DecodeRequestShape.redactUrl("https://h.example.com?a=1"))
    }

    @Test
    fun `path is capped so one record stays one line`() {
        val long = "https://h.example.com/" + "a".repeat(500)
        val got = DecodeRequestShape.redactUrl(long)
        // 截断的是 **path**（80），host 必须完整保留 —— 否则"哪个接口"就看不出来了。
        assertEquals("h.example.com".length + 80, got.length)
        assert(got.startsWith("h.example.com/")) { "host 被截断了: $got" }
    }

    @Test
    fun `scheme-less absolute is unparseable not silently wrong`() {
        // `api.example.com/x` 没有 `://` ⇒ 按相对路径处理（这是唯一安全的解读）。
        assertEquals("api.example.com/x", DecodeRequestShape.redactUrl("api.example.com/x"))
    }

    // ── shouldDecode：三态，缺键不是 false ──────────────────────────────────

    @Test
    fun `missing shouldDecode is not false`() {
        // smali: 缺键填 -1，`if (v1 != -1)` 才发请求 ⇒ "没传" 与 "传了 0" 是两条路径。
        assertEquals("?", DecodeRequestShape.shouldDecode(null))
    }

    @Test
    fun `zero is distinct from missing`() {
        assertEquals("0", DecodeRequestShape.shouldDecode(0))
        assertEquals("1", DecodeRequestShape.shouldDecode(1))
    }

    // ── paramsShape：键名排序，不记值 ────────────────────────────────────────

    @Test
    fun `keys are sorted so the same payload yields the same line`() {
        val a = DecodeRequestShape.paramsShape(listOf("b", "a", "c"), 10)
        val b = DecodeRequestShape.paramsShape(listOf("c", "b", "a"), 10)
        assertEquals(a, b)
        assertEquals("keys=3:a,b,c", a)
    }

    @Test
    fun `long key lists are truncated with an ellipsis`() {
        assertEquals(
            "keys=8:a,b,c,d,e,f,…",
            DecodeRequestShape.paramsShape(listOf("a", "b", "c", "d", "e", "f", "g", "h"), 99),
        )
    }

    @Test
    fun `empty object is zero not not-object`() {
        // `{}` 与"没有 params 键"必须分开：前者页面明确传了空对象。
        assertEquals("0", DecodeRequestShape.paramsShape(emptyList(), 2))
        assertEquals("not-object", DecodeRequestShape.paramsShape(null, 0))
    }

    @Test
    fun `values are never part of the shape`() {
        // 用一组带明显敏感值的数据走一遍，确认输出里不含任何"值"。
        val line = DecodeRequestShape.line(
            DecodeRequestShape.redactUrl("https://h.example.com/api?token=SECRET"),
            DecodeRequestShape.shouldDecode(1),
            DecodeRequestShape.paramsShape(listOf("phone", "token"), 40),
        )
        assertEquals("BRIDGE decodeHttpRequest url=h.example.com/api shouldDecode=1 params=keys=2:phone,token", line)
        assert(!line.contains("SECRET")) { "URL 的 query 泄漏进了记录: $line" }
    }
}
