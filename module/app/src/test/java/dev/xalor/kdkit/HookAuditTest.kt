package dev.xalor.kdkit

import dev.xalor.kdkit.util.HookAudit
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * 台账是三态的：`ok` / `failed` / **`skipped`**。
 *
 * 第三种是这个测试的重点。它对应"目标类根本没找到、代码直接 return"：
 * `Xp.clazzOrNull("…") ?: return` 这种写法下，钩子连**尝试**都没有，
 * 于是既不计 ok 也不计 failed —— 在旧台账里完全隐形。
 *
 * 真机上表现为：功能开关是"已启用"，`hooks N ok` 里的 N 比预期少几，
 * 日志里连一行 warn 都没有。这比 `failed` 更难发现，所以必须有断言钉住。
 */
class HookAuditTest {

    @Before fun reset() = HookAudit.reset()
    @After fun cleanup() = HookAudit.reset()

    @Test fun countsThreeStatesSeparately() {
        HookAudit.record("f1", "a.A.m", true)
        HookAudit.record("f1", "a.A.n", true)
        HookAudit.record("f1", "a.B.m", false)
        HookAudit.recordSkipped("f1", "a.C (class not found)")

        assertEquals(2, HookAudit.okCount())
        assertEquals(1, HookAudit.failedCount())
        assertEquals(1, HookAudit.skippedCount())
    }

    @Test fun skippedIsNotCountedAsFailure() {
        // 关键区分：skipped 与 failed 是不同故障，不能合并。
        // 合并会让"类改名"和"方法签名变了"看起来是同一种问题，排查方向完全不同。
        HookAudit.recordSkipped("f2", "a.X (class not found)")
        assertEquals(0, HookAudit.failedCount())
        assertEquals(1, HookAudit.skippedCount())
        assertTrue(HookAudit.failureList().isEmpty())
    }

    @Test fun perFeatureDetailKeepsAllThree() {
        HookAudit.record("f3", "t1", true)
        HookAudit.record("f3", "t2", false)
        HookAudit.recordSkipped("f3", "t3")
        val d = HookAudit.perFeatureDetail()["f3"]
        assertEquals(Triple(1, 1, 1), d)
    }

    @Test fun summaryLineNamesSkippedTargets() {
        HookAudit.record("f4", "a.A.m", true)
        HookAudit.recordSkipped("f4", "xc.a (class not found)")
        val line = HookAudit.summaryLine(5, 4)
        assertTrue("摘要要把 skipped 点名：$line", line.contains("skipped:"))
        assertTrue("摘要要含缺失的类名：$line", line.contains("xc.a"))
        assertTrue("摘要仍要含基本计数：$line", line.contains("hooks 1 ok / 0 failed"))
    }

    @Test fun summaryLineIsCleanWhenAllGreen() {
        HookAudit.record("f5", "a.A.m", true)
        val line = HookAudit.summaryLine(5, 5)
        assertEquals("ready 5/5 features, hooks 1 ok / 0 failed", line)
    }

    @Test fun sharedOwnerBucketedSeparately() {
        // 不属于任何功能的钩子记到 <shared>，不要把计数混进具体功能
        HookAudit.record(null, "android.webkit.WebView.loadUrl", true)
        assertEquals(1, HookAudit.okCount())
        assertTrue(HookAudit.perFeatureDetail().containsKey("<shared>"))
    }
}
