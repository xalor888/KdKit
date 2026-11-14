package dev.xalor.kdkit.util

/**
 * 路由观测的过滤与"谁在跳"提取（纯函数，JVM 可测）。
 *
 * 两条从实测里长出来的规则（都踩过）：
 *  1. `r0.I(String)` 也被用于非路由字符串（`init` / `cacheLoaded`）⇒ 必须按**形状**过滤，
 *     而不是假设"进了这个方法就是路由"；
 *  2. 取调用方时必须跳过路由包**和模块自己** —— 早期版本没跳过 `de.xalor.kdkit`，
 *     于是每条记录都返回"调用者是 KdKit"（真机跑了一轮才发现）。
 */
object RouteFilter {

    /** `zyb://` 前缀或任意带 scheme 的串才算路由。 */
    fun looksLikeRoute(arg: String): Boolean =
        arg.isNotBlank() && (arg.contains("://") || arg.startsWith("zyb:"))

    /** 从栈里找第一个"不属于路由框架、也不属于本模块"的帧。 */
    fun caller(stack: Array<StackTraceElement>): String {
        for (e in stack) {
            val n = e.className ?: continue
            if (isInternal(n)) continue
            return n + "." + e.methodName
        }
        return "?"
    }

    fun isInternal(className: String): Boolean =
        className.startsWith("com.zuoyebang.router") ||
            className.startsWith("de.robv.android.xposed") ||
            className.startsWith("de.xalor.kdkit") ||
            className.startsWith("java.lang.") ||
            className.startsWith("android.")

    /** `zyb://kd-vip/page/vip-buy` -> `kd-vip`（诊断页按模块聚合用）。 */
    fun moduleOf(route: String): String {
        val noScheme = route.substringAfter("://", route.removePrefix("zyb:"))
        return noScheme.substringAfter("zyb:").trimStart('/').substringBefore('/').ifEmpty { "?" }
    }
}
