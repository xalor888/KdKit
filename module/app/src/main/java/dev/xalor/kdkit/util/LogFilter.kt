package dev.xalor.kdkit.util

/**
 * App 日志筛选（纯函数，JVM 可测）。
 *
 * 调用于 `android.util.Log.*` 的**每一条**日志上 —— 这是全模块最热的路径，
 * 所以这里刻意只用"哈希集合 + 常量子串"，不做正则、不分配 lowercase 副本。
 */
object LogFilter {

    /** 与签名/接口相关的关键词（全小写；判定前只 lowercase 一次 [msg] 的前缀窗口）。 */
    private val MSG_KEYWORDS = listOf(
        "nativegetsign", "paramstring", "servertimamparam", "servertimeparam",
        "signtimeparam", "kdapi/", "zyb://", "kdcore/",
    )

    private val tagCache = java.util.concurrent.ConcurrentHashMap<String, Set<String>>()

    /**
     * [tagLowerSet] 传 **已经 lowercase** 的 tag 集合（调用方在 install 时算一次）。
     *
     * 命中条件：tag 精确等于集合成员，**或** tag 里包含某个关键词；
     * 或者消息里出现签名/接口关键词（大小写不敏感，只看前 [窗口] 个字符 —— 关键词总在开头附近）。
     */
    fun interesting(tag: String, msg: String, tags: List<String>, maxKeywordWindow: Int = 512): Boolean {
        val lowerTags = tagCache.computeIfAbsent(tags.joinToString(",")) {
            tags.map { t -> t.lowercase() }.toSet()
        }
        val t = tag.lowercase()
        if (lowerTags.contains(t)) return true
        if (lowerTags.any { t.contains(it) }) return true
        if (msg.isEmpty()) return false
        val window = if (msg.length <= maxKeywordWindow) msg else msg.substring(0, maxKeywordWindow)
        val m = window.lowercase()
        return MSG_KEYWORDS.any { m.contains(it) }
    }
}
