package dev.xalor.kdkit

import dev.xalor.kdkit.util.RawListMemo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

/**
 * 热路径上的"配置串 → 列表"记忆（2026-11-02，D2）。
 *
 * 背景：`BridgeGuard.decide()` 挂在 `HybridWebView.dispatchAction` 上，
 * **每次** JS 桥调用都会走；它每趟都 `split + map + filter + toMutableList`。
 * 实测一次会话 282 次桥调用、其中单个 action 80 次 —— 这些分配完全可以省掉。
 * `HostAllowList.allows()` 同理（每趟 `split + map×3 + filter + distinct`）。
 *
 * 这组断言钉两件事：**同一个串只解析一次**、**串变了必须重解析**。
 * 第二条是正确性底线：漏了它，"改了黑名单不生效"这种 bug 会以
 * "偶尔生效"的形态出现，比彻底不生效更难查。
 */
class RawListMemoTest {

    @Test
    fun `same raw string parses exactly once`() {
        val m = RawListMemo()
        var calls = 0
        val parse: (String) -> List<String> = { r -> calls++; r.split(',') }

        repeat(50) { m.get("a,b") { parse(it) } }
        assertEquals("同一个串只能解析一次（这是本类的全部意义）", 1, calls)
    }

    @Test
    fun `result is cached by identity so the hot path allocates nothing`() {
        val m = RawListMemo()
        val first = m.get("a,b") { it.split(',') }
        val second = m.get("a,b") { it.split(',') }
        assertSame("同一串必须返回同一个 List 实例（不是每次新建再 equals）", first, second)
    }

    @Test
    fun `changed raw string re-parses immediately`() {
        val m = RawListMemo()
        var calls = 0
        val parse: (String) -> List<String> = { r -> calls++; r.split(',') }

        assertEquals(listOf("a", "b"), m.get("a,b") { parse(it) })
        assertEquals("配置串变了必须立刻重算 —— 否则『改了黑名单不生效』会变成偶发 bug",
            listOf("x"), m.get("x") { parse(it) })
        assertEquals(2, calls)
        // 变回去也要重算（不能只记"最后一次"以外的假设）
        assertEquals(listOf("a", "b"), m.get("a,b") { parse(it) })
        assertEquals(3, calls)
    }

    @Test
    fun `empty string is a valid key and is memoized`() {
        val m = RawListMemo()
        var calls = 0
        repeat(3) { m.get("") { calls++; emptyList() } }
        assertEquals(1, calls)
    }

    @Test
    fun `lastRaw tells which string is remembered`() {
        val m = RawListMemo()
        assertNull("还没算过时必须是 null，不能假装记住了空串", m.lastRaw())
        m.get("a,b") { it.split(',') }
        assertEquals("a,b", m.lastRaw())
        m.get("c") { it.split(',') }
        assertEquals("c", m.lastRaw())
    }

    @Test
    fun `case and whitespace differences are distinct keys`() {
        // 记忆层**不做规范化**：`"A"` 与 `"a"` 是两串，各自解析。
        // 规范化是 parse 的职责（`HostAllowList.parse` 会 lowercase），
        // 放在记忆层会让"大小写变了但配置没变"这种判断永远为真。
        val m = RawListMemo()
        var calls = 0
        m.get("A,B") { calls++; it.split(',') }
        m.get("a,b") { calls++; it.split(',') }
        assertEquals(2, calls)
    }

    @Test
    fun `concurrent readers never see an empty result for a known key`() {
        val m = RawListMemo()
        m.get("seed") { it.split(',') }
        val errors = java.util.Collections.synchronizedList(mutableListOf<Throwable>())
        val threads = (1..8).map {
            Thread {
                try {
                    repeat(500) {
                        val r = m.get("seed") { s -> s.split(',') }
                        if (r != listOf("seed")) throw AssertionError("读到了错误结果: $r")
                    }
                } catch (t: Throwable) {
                    errors.add(t)
                }
            }
        }
        threads.forEach { it.start() }
        threads.forEach { it.join() }
        assertEquals("并发读不该出现空列表/错值: $errors", 0, errors.size)
    }
}
