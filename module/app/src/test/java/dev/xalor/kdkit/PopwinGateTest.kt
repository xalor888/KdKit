package dev.xalor.kdkit

import dev.xalor.kdkit.features.host.PopwinGate
import dev.xalor.kdkit.features.host.PopwinGate.Action
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `popwin_gate` 的纯判定逻辑（不碰 Xposed / 不读配置）。
 *
 * 这些断言盯的是**规则顺序**：`decide` 的四个分支有先后，改动顺序会让"只观测"
 * 静默变成"真拦截"（或反过来），而那种错误在真机上表现为"开关看着对、行为不对"。
 */
class PopwinGateTest {

    private val block = PopwinGate.DEFAULT_BLOCK.joinToString(",")

    // ── matches(): 清单匹配 ────────────────────────────────────────────────────

    @Test
    fun `exact type matches`() {
        assertTrue(PopwinGate.matches("winAd", block))
        assertTrue(PopwinGate.matches("winVIPBottom", block))
        assertTrue(PopwinGate.matches("winImp", block))
    }

    @Test
    fun `non-listed type does not match`() {
        // 年级类与强制更新刻意不在默认清单里：它们是业务提示，不是广告/销售。
        assertFalse(PopwinGate.matches("winUp", block))
        assertFalse(PopwinGate.matches("winGradeUp", block))
        assertFalse(PopwinGate.matches("winBook", block))
        assertFalse(PopwinGate.matches("winFlow", block))
    }

    @Test
    fun `whitespace and empty entries are ignored`() {
        assertTrue(PopwinGate.matches("winAd", " winUp ,, winAd , "))
        assertFalse(PopwinGate.matches("winAd", " , , "))
    }

    @Test
    fun `trailing wildcard matches the prefix family`() {
        // 真实存在的前缀拼接：`"winActivity_" + bid` / `"winBottom_" + bid`
        assertTrue(PopwinGate.matches("winActivity_7", "winActivity*"))
        assertTrue(PopwinGate.matches("winBottom_3", "winBottom*"))
        assertFalse(PopwinGate.matches("winBottomAd", "winActivity*"))
    }

    @Test
    fun `wildcard star matches everything`() {
        assertTrue(PopwinGate.matches("winUp", "*"))
        assertTrue(PopwinGate.matches("任何东西", "*"))
    }

    @Test
    fun `wildcard is trailing-only, not infix`() {
        // `win*d` 不是合法形态 ⇒ 按字面量比对，不会意外命中 winAd。
        // 这条是防"我以后想加中间通配"时把语义搞乱：中间通配会让 winAd 吃掉 winAdSlot。
        assertFalse(PopwinGate.matches("winAd", "win*d"))
    }

    @Test
    fun `null or blank type never matches`() {
        assertFalse(PopwinGate.matches(null, "*"))
        assertFalse(PopwinGate.matches("", "*"))
        assertFalse(PopwinGate.matches("   ", "*"))
    }

    @Test
    fun `empty block matches nothing`() {
        assertFalse(PopwinGate.matches("winAd", ""))
    }

    // ── decide(): 规则顺序 ────────────────────────────────────────────────────

    @Test
    fun `blocked type blocks when observe_only is off`() {
        val v = PopwinGate.decide("winAd", block, observeOnly = false)
        assertEquals(Action.BLOCK, v.action)
        assertTrue(v.block)
    }

    @Test
    fun `blocked type only observes when observe_only is on`() {
        val v = PopwinGate.decide("winAd", block, observeOnly = true)
        assertEquals(Action.OBSERVE, v.action)
        // block=true 仍如实反映"它本来会被拦"——观测模式不该把事实抹掉。
        assertTrue(v.block)
    }

    @Test
    fun `unlisted type passes in both modes`() {
        assertEquals(Action.PASS, PopwinGate.decide("winUp", block, false).action)
        assertEquals(Action.PASS, PopwinGate.decide("winUp", block, true).action)
    }

    @Test
    fun `null type passes even with wildcard block`() {
        // 宁可放过不可误杀：拿不到类型就绝不短路，否则会在分派层把未知弹窗全吞掉。
        val v = PopwinGate.decide(null, "*", observeOnly = false)
        assertEquals(Action.PASS, v.action)
        assertFalse(v.block)
    }

    @Test
    fun `blank type passes`() {
        assertEquals(Action.PASS, PopwinGate.decide("", "*", false).action)
        assertEquals(Action.PASS, PopwinGate.decide("  ", "*", false).action)
    }

    @Test
    fun `empty block never blocks anything`() {
        for (t in PopwinGate.KNOWN_TYPES) {
            assertEquals("type=$t", Action.PASS, PopwinGate.decide(t, "", false).action)
        }
    }

    // ── 类型表本身 ─────────────────────────────────────────────────────────────

    @Test
    fun `known types cover every dispatch string in H`() {
        // 这 10 个是 `ei.y.H` 方法体里**全部** `const-string "win…"`。
        //
        // 2026-10-25 修正：原期望是 8 个，漏了 `winActivity` / `winBottom`。
        // 它们出现在 `sparse-switch` **之前**（`y.smali` 方法体第 84 / 109 行），
        // 走 `C(ListItem)` / `E(ListItem)`，与后面 8 个 `equals` 链分支**形态不同** ——
        // 只数"分支体"会漏掉，必须把方法体里所有 win* 常量都数一遍。
        //
        // 10 个类型 → 9 个分派方法（`winGradeUp` 与 `winGradeSelect` 同走 `J()`）。
        assertEquals(10, PopwinGate.KNOWN_TYPES.size)
        assertEquals(
            listOf("winActivity", "winBottom",
                   "winUp", "winAd", "winImp", "winVIPBottom",
                   "winBook", "winFlow", "winGradeSelect", "winGradeUp").sorted(),
            PopwinGate.KNOWN_TYPES.sorted(),
        )
    }

    @Test
    fun `default block names are all known types`() {
        // 清单里允许带尾部 `*`（`winBottom*`），比较前先剥掉，否则这条断言会因为
        // "winBottom*" 不在 KNOWN_TYPES 里而假红 —— 而假红会教人无视门禁。
        val names = PopwinGate.DEFAULT_BLOCK.map { it.removeSuffix("*") }
        assertTrue(
            "这些不在 KNOWN_TYPES 里: ${names - PopwinGate.KNOWN_TYPES.toSet()}",
            PopwinGate.KNOWN_TYPES.containsAll(names),
        )
        // 强制更新有专门的 `skip_update`；年级相关是业务提示。三条都不该被默认拦。
        assertFalse(PopwinGate.DEFAULT_BLOCK.contains("winUp"))
        assertFalse(PopwinGate.DEFAULT_BLOCK.contains("winGradeUp"))
        assertFalse(PopwinGate.DEFAULT_BLOCK.contains("winGradeSelect"))
    }

    @Test
    fun `default block covers ad and sales families with the wildcard forms`() {
        // 两族**必须**用通配：真实取值是 `winBottom_<bid>` / `winActivity_<bid>`。
        // 只写裸名会得到"清单看着有、实际永不命中"的假功能。
        assertEquals(
            listOf("winAd", "winImp", "winVIPBottom", "winActivity*", "winBottom*").sorted(),
            PopwinGate.DEFAULT_BLOCK.sorted(),
        )
    }

    @Test
    fun `bare family name would never match the real dispatch string`() {
        // 这条钉的是本项目真实存在过的判断错误：把 `winBottom` 当类型名写进清单，
        // 看似覆盖了底部广告，实际 APK 传来的永远是 `winBottom_3` 这种带 bid 的串。
        val real = "winBottom_3"
        assertTrue("通配才命中真实取值", PopwinGate.matches(real, "winBottom*"))
        assertFalse("裸名命中不了真实取值", PopwinGate.matches(real, "winBottom"))
        // 而清单里同时保留裸名是有意义的：它覆盖"恰好等于 winBottom"的那种形态。
        assertTrue(PopwinGate.matches("winBottom", "winBottom"))
    }

    // 注意：这里**不**断言 `H` 是 void —— JVM 单测的 CWD 是 `module/app`，
    // 读不到仓库根的 `work/apktool_out`，写成读文件会静默 `return`（假测试，已踩过一次）。
    // 该断言放在 `kit/python/tests/test_smali_usage.py::PopwinDispatchIsVoid`，
    // 那里本来就在仓库根跑，且已有 smali 解析工具。
}
