package dev.xalor.kdkit

import dev.xalor.kdkit.util.DropCircuit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 观测落盘的熔断器（2026-11-02，D1）。
 *
 * 被替换掉的旧逻辑是 `if (dropped.get() > 1_000_000L) return` ——
 * `dropped` 是**进程内累计值**，所以一次突发之后这个进程**此后再也不写一行抓取**，
 * 不报错、文件还在、看着一切正常，后面所有证据静默消失。
 *
 * 这里钉住新语义的四条：
 *
 * 1. 正常速率（每秒几十行）**永不熔断**；
 * 2. 写爆（1 秒内几千次）会暂停；
 * 3. 暂停**到期自动恢复** —— 这是与"永久停写"最本质的区别；
 * 4. 恢复后还能再次熔断（不是一次性开关）。
 */
class DropCircuitTest {

    @Test
    fun `normal rate never trips`() {
        val c = DropCircuit(tripPerSecond = 5_000, pauseMs = 5_000)
        var now = 0L
        repeat(600) {                       // 10 分钟，每秒 1 次
            now += 1_000
            c.onDrop(now)
            assertTrue("正常速率不该熔断（t=$now）", c.allow(now))
        }
        assertEquals(0L, c.trips)
    }

    @Test
    fun `burst trips the breaker`() {
        val c = DropCircuit(tripPerSecond = 100, pauseMs = 5_000)
        for (i in 0..200) c.onDrop(1_000)   // 同一毫秒里丢 201 次
        assertFalse("一秒内丢超过阈值必须熔断", c.allow(1_000))
        assertEquals(1L, c.trips)
    }

    /** **本用例是 D1 的核心**：暂停到期必须自己恢复，而不是像旧实现那样永久闭嘴。 */
    @Test
    fun `pause expires and writing resumes`() {
        val c = DropCircuit(tripPerSecond = 100, pauseMs = 5_000)
        for (i in 0..200) c.onDrop(1_000)
        assertFalse(c.allow(1_000))
        assertFalse("暂停期内仍然不写", c.allow(5_999))
        assertTrue("暂停到期必须自动恢复（旧实现这里是永远 false）", c.allow(6_000))
        assertEquals("恢复后剩余暂停应为 0", 0L, c.remainingPauseMs(6_000))
    }

    @Test
    fun `can trip again after recovering`() {
        val c = DropCircuit(tripPerSecond = 100, pauseMs = 1_000)
        for (i in 0..200) c.onDrop(0)
        assertEquals(1L, c.trips)
        assertTrue(c.allow(1_000))

        for (i in 0..200) c.onDrop(10_000)
        assertEquals("恢复后还能再次熔断", 2L, c.trips)
        assertFalse(c.allow(10_000))
    }

    @Test
    fun `window resets after one quiet second`() {
        val c = DropCircuit(tripPerSecond = 100, pauseMs = 5_000)
        for (i in 0..90) c.onDrop(0)        // 90 次：没超阈值
        assertTrue(c.allow(0))
        for (i in 0..90) c.onDrop(2_000)    // 秒窗口已过期，重新计数
        assertTrue("跨过窗口就重新计数，累计值不该触发熔断", c.allow(2_000))
        assertEquals(0L, c.trips)
    }

    @Test
    fun `remainingPauseMs counts down`() {
        val c = DropCircuit(tripPerSecond = 10, pauseMs = 3_000)
        for (i in 0..20) c.onDrop(1_000)
        assertEquals(3_000L, c.remainingPauseMs(1_000))
        assertEquals(1_500L, c.remainingPauseMs(2_500))
        assertEquals(0L, c.remainingPauseMs(9_999))
    }

    @Test
    fun `reset clears state`() {
        val c = DropCircuit(tripPerSecond = 10, pauseMs = 5_000)
        for (i in 0..20) c.onDrop(0)
        assertFalse(c.allow(0))
        c.reset()
        assertTrue(c.allow(0))
    }
}
