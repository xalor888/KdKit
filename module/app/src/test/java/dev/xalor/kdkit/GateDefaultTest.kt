package dev.xalor.kdkit

import dev.xalor.kdkit.util.GatePolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「没配置时算不算开」的契约（2026-11-01 审查的 P0-1）。
 *
 * 缺陷回顾：`Xp.hook(gate = id)` 的回调首行写死 `KdConfig.isOn(gate, true)`，
 * 而设置页从不预置默认值 ⇒ prefs 缺键时回落 `true` ⇒ 24 个 `defaultOn = false` 的
 * hot 功能在用户没点过开关时照跑，其中 7 个会改宿主行为（弹窗拦截/会员/水印/跳过更新…）。
 *
 * 这组断言钉的是语义，不是实现：
 *  * 已知功能 ⇒ 回落它自己的 `defaultOn`（**关的就是关的**）；
 *  * 未知 id ⇒ 回落 `true`（保守：宁可多跑一次可观测的回调，也不静默关掉真功能）。
 */
class GateDefaultTest {

    @After
    fun tearDown() {
        // 别的测试不该继承这里的注入
        GatePolicy.install(emptyMap())
    }

    @Test
    fun `known feature falls back to its own defaultOn`() {
        GatePolicy.install(mapOf("on_by_default" to true, "off_by_default" to false))

        assertTrue("defaultOn=true 的功能没配置时应为开", GatePolicy.defaultFor("on_by_default"))
        assertFalse("defaultOn=false 的功能没配置时应为关", GatePolicy.defaultFor("off_by_default"))
    }

    @Test
    fun `unknown id is conservative true`() {
        GatePolicy.install(mapOf("only" to false))
        assertTrue(
            "未登记的 gate 必须回落 true —— 静默关掉一个真功能比多跑一次回调更难查",
            GatePolicy.defaultFor("never_registered"),
        )
    }

    @Test
    fun `empty registry behaves like the old constant`() {
        GatePolicy.install(emptyMap())
        assertTrue(GatePolicy.defaultFor("anything"))
        assertEquals(0, GatePolicy.size())
    }

    @Test
    fun `install is idempotent and last write wins`() {
        GatePolicy.install(mapOf("x" to false))
        assertEquals(1, GatePolicy.size())
        GatePolicy.install(mapOf("x" to true, "y" to false))
        assertEquals(2, GatePolicy.size())
        assertTrue(GatePolicy.defaultFor("x"))
    }

    /**
     * 真实注册表里的那 7 个「会改宿主行为」的功能，默认必须是关的。
     * 这条断言在 `FeatureRegistry` 改默认值时就会红 —— 那是应该被看见的变更。
     */
    @Test
    fun `behaviour changing features default to off`() {
        val mustBeOff = listOf(
            "bridge_guard", "popwin_gate", "skip_update", "vip_unlock",
            "watermark_off", "web_picture_watermark", "block_ad_sdk",
        )
        GatePolicy.install(dev.xalor.kdkit.features.FeatureRegistry.all.associate { it.id to it.defaultOn })
        for (id in mustBeOff) {
            assertFalse("$id 会改宿主行为，必须默认关（否则界面显示关、实际在改行为）", GatePolicy.defaultFor(id))
        }
    }
}
