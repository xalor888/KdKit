package dev.xalor.kdkit

import dev.xalor.kdkit.util.RouteFilter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RouteFilterTest {

    @Test fun routeShapesAccepted() {
        assertTrue(RouteFilter.looksLikeRoute("zyb://kd-vip/page/vip-buy"))
        assertTrue(RouteFilter.looksLikeRoute("https://x/y"))
        assertTrue(RouteFilter.looksLikeRoute("zyb:kd-vip"))
    }

    @Test fun nonRoutesRejected() {
        // 实测这几个值真的进过 r0.I(String)
        assertFalse(RouteFilter.looksLikeRoute("init"))
        assertFalse(RouteFilter.looksLikeRoute("cacheLoaded"))
        assertFalse(RouteFilter.looksLikeRoute(""))
        assertFalse(RouteFilter.looksLikeRoute("   "))
    }

    @Test fun callerSkipsFrameworkAndSelf() {
        val stack = arrayOf(
            StackTraceElement("java.lang.Thread", "run", null, -1),
            StackTraceElement("com.zuoyebang.router.r0", "h", null, -1),
            StackTraceElement("de.xalor.kdkit.features.host.RouteLog", "hook", null, -1),
            StackTraceElement("com.kuaiduizuoye.scan.vip.VipEntry", "onClick", null, -1),
        )
        assertEquals("com.kuaiduizuoye.scan.vip.VipEntry.onClick", RouteFilter.caller(stack))
    }

    @Test fun callerFallsBackToQuestionMark() {
        val stack = arrayOf(StackTraceElement("de.xalor.kdkit.A", "b", null, -1))
        assertEquals("?", RouteFilter.caller(stack))
    }

    @Test fun moduleExtraction() {
        assertEquals("kd-vip", RouteFilter.moduleOf("zyb://kd-vip/page/vip-buy"))
        assertEquals("kd-user", RouteFilter.moduleOf("zyb://kd-user"))
        assertEquals("?", RouteFilter.moduleOf("zyb://"))
    }
}
