package dev.xalor.kdkit.util

/**
 * 导航观测的**过滤与归一化**逻辑（纯函数，JVM 可测）。
 *
 * 抽出来的原因很具体：这些规则全都写在钩子闭包里过一次，只能靠真机跑一轮才知道对不对；
 * 而它们决定"某个页面到底算不算被观测到"（`UNVISITED_PAGES.md` 的分母就在这里）。
 *
 * 规则：
 *  * 只认 `http(s)://` 与含 `hycache` 的本地页（`file:///.../hycache/xxx.html`）；
 *  * `javascript:` / `about:blank` / 空串一律不算页面；
 *  * **页面 key = 去查询串后的文件名**（`pk-home.html`）—— 同一页面带不同 query 只算一次；
 *  * 文件名里若没有 `.html` 就退回整条路径的最后一段（兼容路由式页面）。
 */
object NavFilter {

    fun isHostClass(className: String): Boolean =
        className.startsWith("com.kuaiduizuoye.scan") ||
            className.startsWith("com.baidu.homework")

    fun activityName(className: String): String = className.substringAfterLast('.')

    /** 返回归一化后的页面 key；不是页面则返回 null。 */
    fun pageKey(url: String?): String? {
        if (url == null) return null
        val u = url.trim()
        if (u.isEmpty()) return null
        if (u.startsWith("javascript:") || u.startsWith("about:") || u.startsWith("data:")) return null
        val isHttp = u.startsWith("http://") || u.startsWith("https://")
        val isLocal = u.contains("hycache")
        if (!isHttp && !isLocal) return null

        val path = u.substringBefore('?').substringBefore('#')
        val last = path.substringAfterLast('/')
        if (last.isEmpty()) return null
        // 文件名（含 .html）就是页面标识；没有扩展名时也接受最后一段（SPA 路由）
        return last
    }

    /**
     * 静态资源扩展名 —— **编译一次，不要每次调用都编译**。
     *
     * 2026-11-02 审查（P-性能）：`isAsset` 被 `WebInjector` 的
     * `shouldInterceptRequest` 钩子调用，而那个钩子在**页面每发一个请求**时都会跑
     * （一个 H5 页面上百次）。旧实现每次调用都 `Regex("…")` 重新编译 ——
     * 编译一个 12 选 1 的正则是几十微秒，且每次都新分配对象，
     * 于是纯粹为了判断"这是不是静态资源"就在最热的路径上反复分配。
     *
     * 这与 R9 的 `RawListMemo` / R10 的 `DropCircuit` 是同一类问题：
     * **热路径上的重复计算**。区别是那两次是"每次重新解析配置"，这次是"每次重新编译正则"。
     */
    // `IGNORE_CASE`：CDN 上的 `.JPG` / `.Png` 很常见，不分大小写会把它们误判成接口请求
    // （后果是**多记**一层请求头摘要，不是丢数据 —— 但判据错了就是错了）。
    private val ASSET_RX = Regex(
        """\.(js|css|png|jpe?g|ico|woff2?|svg|webp|map|ttf|otf|mp4|m4a|mp3)(\?.*)?$""",
        RegexOption.IGNORE_CASE,
    )

    /** 是否静态资源（`.js/.css/图片/字体/map`）—— 页面观测要排除它们。 */
    fun isAsset(url: String): Boolean = ASSET_RX.containsMatchIn(url)
}
