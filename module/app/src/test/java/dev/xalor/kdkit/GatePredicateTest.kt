package dev.xalor.kdkit

import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.util.GatePolicy
import dev.xalor.kdkit.util.Xp
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `Xp.gateOpen` —— **gate 判据的唯一实现**（2026-11-04 收敛）。
 *
 * 缺陷回顾：这条判据原来在 `Xp.kt` 里抄了 **6 遍**：
 *
 *     if (gate != null && !KdConfig.isOn(gate, GatePolicy.defaultFor(gate))) return
 *
 * 抄 6 遍的风险不是"抄错"，而是**改的时候漏改** ——
 * 漏改的那一处会让"关掉功能"失效，症状是 UI 上开关是关的、
 * App 侧行为完全不变，**不报错**。
 *
 * 这个文件钉住收敛后的语义：
 *  * `gate == null` ⇒ 永远放行（不设 gate 的钩子本来就不受配置控制）；
 *  * gate 给定 + 配置说 false ⇒ 挡住；
 *  * gate 给定 + 配置说 true ⇒ 放行；
 *  * gate 给定 + 没有配置 ⇒ 按 `defaultOn` 走（不是"一律 false"）。
 */
class GatePredicateTest {

    @After
    fun tearDown() {
        KdConfig.hostReader = null
        KdConfig.invalidate()
        GatePolicy.install(emptyMap())
    }

    private fun source(map: Map<String, Boolean>) {
        KdConfig.hostReader = { id -> map[id] }
        KdConfig.invalidate()
    }

    @Test
    fun `null gate always passes`() {
        source(mapOf("antidetect" to false))
        assertTrue("没有 gate 的钩子不该被配置挡住", Xp.gateOpen(null))
    }

    @Test
    fun `explicit false blocks the callback`() {
        GatePolicy.install(mapOf("antidetect" to true))
        source(mapOf("antidetect" to false))
        assertFalse("配置说关就必须挡住", Xp.gateOpen("antidetect"))
    }

    @Test
    fun `explicit true passes`() {
        GatePolicy.install(mapOf("antidetect" to true))
        source(mapOf("antidetect" to true))
        assertTrue(Xp.gateOpen("antidetect"))
    }

    @Test
    fun `missing config falls back to defaultOn`() {
        GatePolicy.install(mapOf("antidetect" to false))
        source(emptyMap())
        assertFalse(
            "没配置时按 defaultOn 走 —— defaultOn=false 的功能不该在用户没表态时跑",
            Xp.gateOpen("antidetect")
        )
    }

    @Test
    fun `unknown id is conservative`() {
        GatePolicy.install(emptyMap())
        source(emptyMap())
        assertTrue(
            "未知 id 回落 true —— 宁可多跑一次可观测的回调，也不静默关掉真功能",
            Xp.gateOpen("some_id_nobody_registered")
        )
    }
}
