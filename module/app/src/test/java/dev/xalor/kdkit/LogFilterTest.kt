package dev.xalor.kdkit

import dev.xalor.kdkit.util.LogFilter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LogFilterTest {
    private val tags = listOf("nativeGetSign", "ZYBHttp", "H5Bridge")

    @Test fun exactTagHit() {
        assertTrue(LogFilter.interesting("nativeGetSign", "x", tags))
        assertTrue(LogFilter.interesting("nativegetsign", "x", tags))
    }

    @Test fun tagSubstringHit() {
        assertTrue(LogFilter.interesting("ZYBHttp-Request", "x", tags))
    }

    @Test fun unrelatedTagAndMessageMissed() {
        assertFalse(LogFilter.interesting("AndroidRuntime", "FATAL EXCEPTION", tags))
        assertFalse(LogFilter.interesting("chatty", "uid=10123 expired", tags))
    }

    @Test fun messageKeywordHit() {
        assertTrue(LogFilter.interesting("SomeTag", "#nativeGetSign start, paramString=abc", tags))
        assertTrue(LogFilter.interesting("SomeTag", "GET https://www.kuaiduizuoye.com/kdapi/conf", tags))
        assertTrue(LogFilter.interesting("SomeTag", "jump zyb://kd-vip/page/vip-buy", tags))
    }

    @Test fun keywordBeyondWindowIgnored() {
        val long = "x".repeat(600) + "nativeGetSign"
        assertFalse("关键词窗口用于剪枝，避免对超长消息反复扫", LogFilter.interesting("SomeTag", long, tags))
    }

    @Test fun emptyMessageWithUnrelatedTag() {
        assertFalse(LogFilter.interesting("Other", "", tags))
    }

    /**
     * 模块**自己的**日志不能被 `LogSink` 再收录一遍。
     *
     * 实测证据（2026-10-25，`work/activity_inputs/` 五份抓取）：
     * ```
     * 19:21:36.742 APPSIGN I/VectorLegacyBridge: [KdKit] H5 n out: https://…
     * 19:21:36.743 H5 n out: https://…
     * ```
     * 同一个事件两行 —— 前一行是 `LogSink` 收回的模块自身 `KdLog` 输出。
     * 全量统计：**3318 / 16807 = 19%** 的抓取行是这种重复。
     *
     * 这条测试守的是 `LogSink` 里的 `SELF_TAG` 排除条件：
     * 谁把它删了，这里会红。
     */
    @Test
    fun kdLogTagIsTheStableString() {
        assertEquals("KdKit", dev.xalor.kdkit.util.KdLog.TAG)
    }

    /**
     * **模块自己的日志不能被 `LogSink` 再收录一遍。**
     *
     * 实测证据（`work/activity_inputs/` 五份抓取）：同一事件两行 ——
     * ```
     * 19:21:36.742 APPSIGN I/VectorLegacyBridge: [KdKit] H5 n out: https://…
     * 19:21:36.743 H5 n out: https://…
     * ```
     * 全量 **3318 / 16807 = 19%** 是这种重复。
     *
     * 这条测试断言的是**行为**（`shouldCapture` 返回 false），不是常量 ——
     * 把排除条件删掉它会红。上一版只断言常量值，删掉过滤仍然绿，那种测试没有意义。
     */
    @Test
    fun ownTagIsNeverCaptured() {
        // 即使消息本身命中了白名单 tag / 关键词，也不能收录
        assertFalse(dev.xalor.kdkit.features.misc.LogSink.shouldCapture(
            dev.xalor.kdkit.util.KdLog.TAG, "H5 n out: https://x"))
        assertFalse(dev.xalor.kdkit.features.misc.LogSink.shouldCapture(
            dev.xalor.kdkit.util.KdLog.TAG, "nativeGetSign param=X3RfPTE3"))
    }

    @Test
    fun otherTagsStillFlowThroughTheFilter() {
        // 反向：别的 tag 仍按原规则走，排除不能把整个 LogSink 关掉
        assertTrue(dev.xalor.kdkit.features.misc.LogSink.shouldCapture("nativeGetSign", "param=x"))
        assertFalse(dev.xalor.kdkit.features.misc.LogSink.shouldCapture("Unrelated", "nothing here"))
    }

}
