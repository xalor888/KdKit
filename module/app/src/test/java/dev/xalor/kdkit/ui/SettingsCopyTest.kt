package dev.xalor.kdkit.ui

import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.FeatureRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 设置页文案的纪律测试 —— 这几条是"重做设置页"这件事的判据，不是装饰。
 *
 * 为什么是测试而不是脚本门禁：`Copy` 是纯数据，出错只有两种 ——
 * **漏了某个功能**（那个功能在设置页里没有可读的标题）或**文案又写回技术说明**
 * （用户又看不懂）。两种都能在 JVM 里一次跑完，不需要设备、不需要 APK。
 *
 * 历史背景：这一版之前，设置页直接摊 `BaseFeature.summary`（里面是
 * `钩 dj.e.f()` / `7.7.2 里这个类是 aj.a` / `服务端计次`），用户读不出"该不该开"。
 */
class SettingsCopyTest {

    private val registryIds: Set<String> = FeatureRegistry.all.map { it.id }.toSet()
    private val copyIds: Set<String> = SettingsCopy.all.map { it.id }.toSet()

    @Test
    fun `copy covers every registered feature exactly once`() {
        assertEquals(
            "设置页文案必须与 FeatureRegistry 一一对应（缺了谁就没有可读标题，多了谁就是死文案）",
            registryIds.sorted(),
            copyIds.sorted(),
        )
        assertEquals("id 不能重复", SettingsCopy.all.size, copyIds.size)
    }

    @Test
    fun `blurb is one line of plain language`() {
        val bad = SettingsCopy.all.filter { it.blurb.length > 22 || it.blurb.contains('\n') }
        assertTrue("副标题要一行、≤22 字：${bad.map { "${it.id}=${it.blurb}" }}", bad.isEmpty())
    }

    @Test
    fun `blurb contains no implementation detail`() {
        // 括号里的实现细节、混淆类名、旧版本号 —— 这些属于展开区的技术说明，不属于列表。
        val leaky = listOf("(", "（", "）", ")", "钩", "RS4", "7.7.2", "7.10.", "PatchProxy", "seccomp")
        val bad = SettingsCopy.all.filter { c -> leaky.any { c.blurb.contains(it) } }
        assertTrue("副标题里出现了实现细节：${bad.map { "${it.id}=${it.blurb}" }}", bad.isEmpty())
    }

    @Test
    fun `label stays short`() {
        val bad = SettingsCopy.all.filter { it.label.length > 8 }
        assertTrue("标题要短：${bad.map { "${it.id}=${it.label}" }}", bad.isEmpty())
    }

    @Test
    fun `ads and pk groups do not mix categories`() {
        val bad = SettingsCopy.all.filter { c ->
            val f = FeatureRegistry.byId(c.id)
            f != null && SettingsCopy.categoryMismatch(c.id, f.category)
        }
        assertTrue("广告组里混进了非广告功能：${bad.map { it.id }}", bad.isEmpty())
        // 只做单向核对：**去广告组里的功能必须是 ADS 分类**。
        // 反向不成立是设计选择 —— `ad_probe` 的技术分类仍是 ADS（它观测的就是广告位），
        // 但它是观测类，必须归「诊断与抓取」，否则用户会以为它是去广告开关。
        val adsInCopy = SettingsCopy.items(Group.ADS).map { it.id }.toSet()
        val adsInRegistry = FeatureRegistry.all.filter { it.category == Category.ADS }.map { it.id }.toSet()
        assertTrue("去广告组里出现了非 ADS 分类的功能：${adsInCopy - adsInRegistry}", adsInCopy.containsAll(adsInRegistry - setOf("ad_probe")))
    }

    @Test
    fun `recommended set is exactly the non diagnostic groups`() {
        val expected = SettingsCopy.all.filter { it.group != Group.DIAG }.map { it.id }.toSet()
        assertEquals(expected, SettingsCopy.recommendedOn)
    }

    @Test
    fun `group counts match the design doc`() {
        // module/UI.md §3 写的 7 / 4 / 3 / 1 / 23 —— 两边一起改才算改完
        assertEquals(7, SettingsCopy.items(Group.ADS).size)
        assertEquals(5, SettingsCopy.items(Group.CONTENT).size)
        assertEquals(3, SettingsCopy.items(Group.EASE).size)
        assertEquals(1, SettingsCopy.items(Group.PK).size)
        assertEquals(1, SettingsCopy.items(Group.LOOK).size)
        assertEquals(23, SettingsCopy.items(Group.DIAG).size)
    }
}
