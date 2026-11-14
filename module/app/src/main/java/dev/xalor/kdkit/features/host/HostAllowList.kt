package dev.xalor.kdkit.features.host

/**
 * 域名后缀白名单的**纯匹配逻辑**（无 android / 无 Xposed 依赖 ⇒ 可在 JVM 里精确测试）。
 *
 * 语义（这是最容易写错、也最容易把功能写成"永不放行"或"永远放行"的一段）：
 *
 *  * 空名单 = **不放行**（保守；用户清空输入框不该意外变成"任意域名都允许"）；
 *  * `example.com` 命中 `example.com` 本身与任意子域 `a.example.com`；
 *  * 匹配按 **label 边界**，不是字符串后缀 —— `evilexample.com` **不**命中 `example.com`
 *    （否则白名单形同虚设，这是同名子串绕过）；
 *  * 大小写不敏感；条目可带前导 `.`（`.example.com` 等价 `example.com`）；
 *  * 拒绝带端口 / 路径的条目（那是配置错误，静默忽略而不是让它匹配失败）。
 */
object HostAllowList {

    /**
     * 解析结果按配置串记忆：`allows()` 在每次桥请求判定时被调用，
     * 而 [parse] 是 `split + map×3 + filter + distinct` —— 六趟分配。
     * 配置串在两次修改之间是同一个值，只需记住"上次解析的是哪串"。
     */
    private val memo = dev.xalor.kdkit.util.RawListMemo()

    fun allows(host: String, rawAllowList: String): Boolean {
        if (host.isBlank()) return false
        val h = host.trim().lowercase().trimEnd('.')
        val entries = memo.get(rawAllowList) { parse(it) }
        if (entries.isEmpty()) return false
        return entries.any { matchesSuffix(h, it) }
    }

    /** 单个后缀条目是否允许 [h]（[h] 应已 lowercase）。 */
    private fun matchesSuffix(h: String, suffix: String): Boolean {
        if (suffix.isEmpty()) return false
        if (h == suffix) return true
        if (!h.endsWith("." + suffix)) return false
        // 额外保险：命中段的 label 数必须严格多于后缀（上面 endsWith 已保证），且后缀本身不像 IP 片段
        return true
    }

    /** 把逗号分隔的配置拆成规范化后缀集合（丢弃非法/重复项）。 */
    fun parse(raw: String): List<String> =
        raw.split(',')
            .map { it.trim().lowercase().trimStart('.').trimEnd('.') }
            .filter { isPlausibleSuffix(it) }
            .distinct()

    private fun isPlausibleSuffix(s: String): Boolean {
        if (s.isEmpty()) return false
        if (s.contains('/') || s.contains(':') || s.contains(' ')) return false
        if (!s.contains('.')) return false
        // 只允许 label 字符；IP 字面量（1.2.3.4）作为"后缀"是误配，直接拒
        if (s.all { it.isDigit() || it == '.' }) return false
        return s.all { it.isLetterOrDigit() || it == '.' || it == '-' }
    }
}
