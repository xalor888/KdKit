package dev.xalor.kdkit

import dev.xalor.kdkit.features.host.HostAllowList
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HostAllowListTest {

    @Test fun exactAndSubdomainMatch() {
        val L = "kuaiduizuoye.com"
        assertTrue(HostAllowList.allows("www.kuaiduizuoye.com", L))
        assertTrue(HostAllowList.allows("kuaiduizuoye.com", L))
        assertTrue(HostAllowList.allows("a.b.kuaiduizuoye.com", L))
    }

    @Test fun suffixLookalikeIsRejected() {
        // 这是白名单最容易出的洞：字符串后缀匹配会让 evilkuaiduizuoye.com 通过
        assertFalse(HostAllowList.allows("evilkuaiduizuoye.com", "kuaiduizuoye.com"))
        assertFalse(HostAllowList.allows("kuaiduizuoye.com.evil.net", "kuaiduizuoye.com"))
    }

    @Test fun emptyListDeniesEverything() {
        assertFalse("清空输入框不该变成'任意域名放行'", HostAllowList.allows("www.kuaiduizuoye.com", ""))
        assertFalse(HostAllowList.allows("www.kuaiduizuoye.com", "  , ,"))
    }

    @Test fun multipleEntriesAndCaseInsensitive() {
        val L = " Kuaiduizuoye.com , zuoyebang.com "
        assertTrue(HostAllowList.allows("WWW.KUAIDUIZUOYE.COM", L))
        assertTrue(HostAllowList.allows("ptactivity.zuoyebang.com", L))
        assertFalse(HostAllowList.allows("example.com", L))
    }

    @Test fun leadingDotNormalised() {
        assertTrue(HostAllowList.allows("www.kuaiduizuoye.com", ".kuaiduizuoye.com"))
        assertTrue(HostAllowList.allows("www.kuaiduizuoye.com", "kuaiduizuoye.com."))
    }

    @Test fun invalidEntriesDropped() {
        assertTrue(HostAllowList.parse("localhost, http://x.com, 1.2.3.4, ok.com").contains("ok.com"))
        assertFalse(HostAllowList.parse("localhost").contains("localhost"))
        assertFalse("IP 字面量当前缀是误配", HostAllowList.parse("1.2.3.4").contains("1.2.3.4"))
    }

    @Test fun blankHostDenied() {
        assertFalse(HostAllowList.allows("", "kuaiduizuoye.com"))
        assertFalse(HostAllowList.allows("   ", "kuaiduizuoye.com"))
    }
}
