package dev.xalor.kdkit

import dev.xalor.kdkit.util.NavFilter
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `NavFilter.isAsset` 的正则判定。
 *
 * 为什么值得单测：它决定"页面观测"把哪些请求当静态资源跳过。
 * 判错一类的后果是**静默少数据**（把接口当静态资源跳过 ⇒ 埋点请求全丢），
 * 而这类丢失不会让任何门禁变红。
 */
class NavFilterTest {

    @Test
    fun `assets are recognised`() {
        for (u in listOf(
            "https://x.com/a/app.js",
            "https://x.com/a/app.js?v=12",
            "https://x.com/a/style.css",
            "https://x.com/a/logo.png",
            "https://x.com/a/logo.JPG",
            "https://x.com/a/f.woff2",
            "https://x.com/a/m.map",
            "https://x.com/a/v.mp4",
        )) assertTrue(u, NavFilter.isAsset(u))
    }

    @Test
    fun `api calls are not assets`() {
        for (u in listOf(
            "https://x.com/kdapi/exam/searchconfigv2",
            "https://x.com/adxlog/log/hit?content=eventTime%3D1",
            "https://x.com/pigai/config/list",
            "https://x.com/pluto/app/hotfix",
            "https://x.com/a/page.html",
            "https://x.com/a/",
        )) assertFalse(u, NavFilter.isAsset(u))
    }
}
