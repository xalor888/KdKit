package dev.xalor.kdkit.features.web

/**
 * 注入判定的**纯逻辑**部分 —— 不碰 `WebView`、不碰 `Handler`、不碰配置。
 *
 * ### 为什么单独抽出来
 *
 * `WebInjector` 依赖 `WebView` / `Handler` / `Looper` / `KdConfig`，JVM 单测里根本加载不起来，
 * 于是"拼脚本"和"同一页面只注入一次"这两件最容易写错的事**零覆盖**（代码审查 B1）。
 * 抽成纯对象后，边界条件（空 payload、空 userJs、去重键）都能直接断言。
 *
 * 注意：去重表的**容量控制**没有搬到这里 —— `WebInjector` 里那个
 * `LinkedHashMap(accessOrder=true) + removeEldestEntry` 本来就是正确的有界 LRU，
 * 再包一层只会引入第二份真相。这里只放"键怎么算"。
 */
object InjectPlan {

    /**
     * 把功能脚本与用户自定义脚本拼成一段。
     *
     * 用 `"\n;\n"` 而不是 `"\n"`：各 provider 返回的片段未必自己带结尾分号，
     * 直接换行拼接在"上一段以 `}` 结尾、下一段以 `(` 开头"时会被解析成函数调用。
     * 一个分号就把两个 IIFE 隔开。
     */
    fun compose(payload: String, userJs: String): String = when {
        userJs.isBlank() -> payload
        // payload 为空时别留一个孤零零的前导 `\n;\n`：语法上合法（空语句），
        // 但 eval 报错时那一行会指向一个空片段，排查时误导人。
        payload.isBlank() -> userJs
        else -> payload + "\n;\n" + userJs
    }

    /** 同一 `WebView` 实例 + 同一 URL ⇒ 同一个键（重复加载同页不重复注入）。 */
    fun dedupeKey(identityHash: Int, url: String): String = "$identityHash@$url"
}
