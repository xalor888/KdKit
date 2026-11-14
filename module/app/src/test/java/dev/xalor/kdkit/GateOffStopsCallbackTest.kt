package dev.xalor.kdkit

import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.util.GatePolicy
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「`gate = id` 到底能不能把回调挡住」（2026-11-04，目标里的"关不掉的功能"）。
 *
 * 缺陷回顾：`AntiDetect` 是 `hot = true`，而 `BaseFeature.enable()` 的判据是
 * `if (!hot && !shouldRun()) return` ⇒ **hot 绕过配置检查，无论如何都装钩子**。
 * 它的四个钩子又是**写侧**（把 `isDebuggerConnected` / `TracerPid` /
 * `FLAG_DEBUGGABLE` 统统改成 false），且文件里既没有 `gate =` 也没有 `KdConfig.isOn`
 * ⇒ 用户关掉 `antidetect` 之后，它照样在骗 App。
 *
 * `Xp.hook` 的实际拦截逻辑是：
 *
 *     if (gate != null && !KdConfig.isOn(gate, GatePolicy.defaultFor(gate))) return
 *     onBefore?.invoke(param)
 *
 * 所以这个文件钉的是那条判据本身：**gate 给定时，配置说关就必须判成关**。
 * （`XposedHelpers` 在 JVM 单测里不可用，测不了 `hook()` 的外壳；
 *  外壳的"有没有传 gate"由 `kit/scripts/check_hook_gated.py` 静态保证。）
 */
class GateOffStopsCallbackTest {

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
    fun `explicit false wins over a hot feature's default`() {
        GatePolicy.install(mapOf("antidetect" to true))   // defaultOn = true（hot 的常态）
        source(mapOf("antidetect" to false))

        assertFalse(
            "配置里写了 false，`Xp.hook(gate = \"antidetect\")` 必须判成关",
            KdConfig.isOn("antidetect", GatePolicy.defaultFor("antidetect"))
        )
    }

    @Test
    fun `explicit true keeps it on`() {
        GatePolicy.install(mapOf("antidetect" to true))
        source(mapOf("antidetect" to true))

        assertTrue(KdConfig.isOn("antidetect", GatePolicy.defaultFor("antidetect")))
    }

    @Test
    fun `missing key falls back to defaultOn not to false`() {
        GatePolicy.install(mapOf("antidetect" to true))
        source(emptyMap())

        assertTrue(
            "没有配置时按 defaultOn 走 —— 否则 hot 功能会在用户没表态时被静默关掉",
            KdConfig.isOn("antidetect", GatePolicy.defaultFor("antidetect"))
        )
    }

    @Test
    fun `a null reader means unknown not off`() {
        KdConfig.hostReader = null
        KdConfig.invalidate()
        assertNull("没有 reader 时 readSource 必须给 null（让调用方决定回落）",
            KdConfig.readSourceForTest("antidetect"))
    }
}
