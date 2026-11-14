package dev.xalor.kdkit

import dev.xalor.kdkit.util.TtlCache
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 热开关的 TTL 缓存（2026-11-02，代码审查 B1）。
 *
 * `KdConfig` 依赖 `android.content.Context` / `android.util.Log`，JVM 单测里连类都加载不起来
 * ⇒ 这段"改配置多久生效"的逻辑此前**零覆盖**。抽成 [TtlCache] 后把三条语义钉死：
 *
 * 1. 新鲜 ⇒ 不回源（缓存的全部意义：钩子回调一页上百次，不能每次都读文件）
 * 2. 过期 ⇒ 立刻回源（热开关在 `ttlMs` 内生效）
 * 3. 回源返回 null ⇒ **不缓存**（进程刚起、发布文件还没写出来，是瞬时状态）
 */
class TtlCacheTest {

    @Test
    fun `fresh value does not hit the source`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 1_000
        var reads = 0
        val load = { reads++; true }

        assertEquals(true, c.get("k", 0, load))
        assertEquals(true, c.get("k", 500, load))
        assertEquals("TTL 内重复读不该回源", 1, reads)
    }

    @Test
    fun `expired value re-reads immediately`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 1_000
        var reads = 0
        val load = { reads++; reads < 2 }        // 第一次 true，第二次 false

        assertEquals(true, c.get("k", 0, load))
        assertEquals("刚好到 TTL 就该重读", false, c.get("k", 1_000, load))
        assertEquals(2, reads)
    }

    @Test
    fun `null from source is not cached`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 60_000
        var reads = 0
        // 前两次读不到（发布文件还没写出来），第三次读到了
        val load = { reads++; if (reads < 3) null else true }

        assertNull(c.get("k", 0, load))
        assertNull("读失败被缓存住 = 配置看起来一直是默认值", c.get("k", 1, load))
        assertEquals(true, c.get("k", 2, load))
        assertEquals(3, reads)
        assertEquals(1, c.size)
    }

    @Test
    fun `put is visible immediately and skips the source`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 60_000
        var reads = 0
        c.put("k", false, 0)
        assertEquals(false, c.get("k", 10) { reads++; true })
        assertEquals("setApp 之后不该再回源", 0, reads)
    }

    @Test
    fun `ttl zero means always re-read`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 0
        var reads = 0
        repeat(3) { c.get("k", it.toLong()) { reads++; true } }
        assertEquals(3, reads)
    }

    @Test
    fun `invalidate drops everything`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 60_000
        c.put("a", true, 0)
        c.put("b", false, 0)
        assertEquals(2, c.size)
        c.invalidate()
        assertEquals(0, c.size)
    }

    @Test
    fun `string cache keeps distinct keys apart`() {
        val c = TtlCache<String>()
        c.ttlMs = 60_000
        c.put("list", "a,b", 0)
        c.put("script", "console.log(1)", 0)
        assertEquals("a,b", c.get("list", 1) { null })
        assertEquals("console.log(1)", c.get("script", 1) { null })
    }

    @Test
    fun `ttl boundary is exclusive on the stored timestamp`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 100
        var reads = 0
        c.get("k", 1_000) { reads++; true }
        c.get("k", 1_099) { reads++; false }
        assertEquals("999 ms < 100 的 TTL 判定必须稳定", 1, reads)
        c.get("k", 1_100) { reads++; false }
        assertEquals("ts + ttl 必须过期", 2, reads)
    }

    @Test
    fun `concurrent reads do not corrupt the cache`() {
        val c = TtlCache<Boolean>()
        c.ttlMs = 1
        val threads = (1..8).map { i ->
            Thread {
                repeat(500) { n -> c.get("k$i", n.toLong()) { true } }
            }
        }
        threads.forEach { it.start() }
        threads.forEach { it.join() }
        assertTrue("8 线程 × 500 次之后每个键都该在", c.size == 8)
    }
}
