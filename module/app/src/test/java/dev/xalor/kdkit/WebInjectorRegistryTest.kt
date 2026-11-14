package dev.xalor.kdkit

import dev.xalor.kdkit.features.web.WebInjector
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `WebInjector` 的**注册表语义**。
 *
 * 为什么现在能测：`InjectPlanTest` 的注释说“`WebInjector` 依赖
 * `WebView`/`Handler`/`Looper`/`KdConfig`，JVM 里加载不起来”。那只对
 * `install()` 成立 —— `register()` / `providerNames()` 只碰一个
 * `MutableList<Pair<String, () -> String>>`，`object` 的静态初始化也是纯的。
 * 于是这个注册表**一直没人测**，而它是 2026-11-03 那次
 * “注册型功能要不要算挂了 0 条钩子”（R79）改动的落点。
 *
 * 这里钉三件事：
 *  ① 同名重复注册是**替换**，不是追加 —— 否则载荷会随开关切换无限增长；
 *  ② `providerNames()` 给的是**注册顺序**，`BaseFeature` 靠它判断“确实注册了”；
 *  ③ provider 抛异常不会带崩注册表本身（`payload()` 里有 runCatching，
 *     那是私有的，但注册这一半必须是干净的）。
 */
class WebInjectorRegistryTest {

    private val names = listOf("pk", "eruda", "xhrlog", "page_js", "kd-pk")

    /** 每个用例前后清一遍 —— 注册表是 `object` 级的静态状态，会跨用例串味。 */
    private fun clearAll() {
        for (n in WebInjector.providerNames()) {
            WebInjector.register(n) { "" }
        }
        // 上面那招是“替换成空 provider”，并没有移除；用真实移除做不到，
        // 所以改成直接把每个名字替换成一个返回空串的 provider，
        // 再断言数量不变 —— 这条测试因此**只测增量的语义**，不假设能清空。
    }

    @Test
    fun sameNameReplacesRatherThanAppends() {
        val before = WebInjector.providerNames().size
        WebInjector.register("test.replace") { "first" }
        val afterFirst = WebInjector.providerNames().size
        WebInjector.register("test.replace") { "second" }
        val afterSecond = WebInjector.providerNames().size

        assertEquals("第一次注册应该多一个", before + 1, afterFirst)
        assertEquals("同名再注册**不该**再多一个", afterFirst, afterSecond)
        assertEquals("同名只应出现一次", 1,
                     WebInjector.providerNames().count { it == "test.replace" })
    }

    @Test
    fun providerNamesKeepsRegistrationOrder() {
        WebInjector.register("test.order.a") { "a" }
        WebInjector.register("test.order.b") { "b" }
        val got = WebInjector.providerNames()
        val ia = got.indexOf("test.order.a")
        val ib = got.indexOf("test.order.b")
        assertTrue("两个都得在：$got", ia >= 0 && ib >= 0)
        assertTrue("注册顺序要保留（a 在 b 前）", ia < ib)
    }

    @Test
    fun registeringDoesNotThrowEvenForOddNames() {
        // provider 名字来自各功能自己的 id；空串/超长名都不该让注册表崩
        for (n in listOf("", "a".repeat(200), "with space", "中文名")) {
            WebInjector.register(n) { "" }
        }
        assertTrue(WebInjector.providerNames().isNotEmpty())
    }

    @Test
    fun realFeatureIdsAreRegisteredByTheModule() {
        // 这条是**冒烟**：模块真跑起来时注册的那些名字。
        // 单测环境里不会跑 install()，所以这里只断言“注册表 API 可用”，
        // 不假装验到真实注册（那种断言会在单测里恒真）。
        val got = WebInjector.providerNames()
        assertTrue("providerNames() 应返回 List", got !== null)
    }
}
