package dev.xalor.kdkit.util

/**
 * `decode_httpRequest` 这条桥链路的**纯逻辑**部分（无 Android / Xposed 依赖，可 JVM 直测）。
 *
 * ### 它回答什么
 *
 * `DecodeHttpRequestWebAction`（`@FeAction(name = "decode_httpRequest")`）是宿主暴露给
 * H5 的一个 action：页面传 `{url, params, shouldDecode}` 进来，宿主把 `params` 拼成
 * `k=v&k=v`，**加上字面量 `encryptPath=` + url**，再交给 `yl.f.h(...)` 签名，
 * 最后用 `HttpCurrencyRequest$Input.buildInput(url, sign)` POST 出去。
 *
 * 也就是说：**页面能驱动宿主发一条带签名的、发往任意 url 的请求。**
 * 这条链路值得留痕的地方不是"值"，而是形状：
 *
 * ```
 * BRIDGE decodeHttpRequest url=<host+path> shouldDecode=1 params=3:courseId,page,size
 * ```
 *
 * ### 为什么不记值
 *
 * 抓取文件是**明文落盘**的（`files/kdkit_capture.txt`），`params` 里可能有 token、
 * 手机号、作答内容。记"几个键、键名是什么"足以回答"页面在驱动什么请求",
 * 而不会把用户数据抄进日志 —— 与 `BridgeActionLog.recordPayOrder` 同一条纪律。
 *
 * ### 静态依据（可复跑）
 *
 * ```
 * python3 kit/scripts/smali_usage.py \
 *     --target com.kuaiduizuoye.scan.web.actions.DecodeHttpRequestWebAction:onAction
 * ```
 * 给 `USED`；签名器 `yl.f:h` 亦为 `USED`（12 处外部 invoke）。
 * **运行时是否真的被页面调用过：未验证**（无设备）。
 */
object DecodeRequestShape {

    /**
     * URL 里**必须剥掉**的部分：query 与 fragment。
     *
     * 理由：这条链路的 url 常自带 `?token=...`。记 host + path 已经足够定位接口，
     * 而 query 里几乎总是凭证或用户输入。
     */
    fun redactUrl(raw: String, maxPath: Int = 80): String {
        if (raw.isEmpty()) return "(empty)"
        // 先切掉 fragment，再切掉 query —— 顺序反了会把 `#` 之后的 query 残留下来。
        val noFragment = raw.substringBefore('#')
        val noQuery = noFragment.substringBefore('?')
        val schemeEnd = noQuery.indexOf("://")
        if (schemeEnd < 0) {
            // 相对路径（`/api/x`）：没有 host 可记，整段按 path 处理。
            return noQuery.take(maxPath).ifEmpty { "(relative)" }
        }
        val afterScheme = noQuery.substring(schemeEnd + 3)
        val hostEnd = afterScheme.indexOf('/')
        val host = if (hostEnd < 0) afterScheme else afterScheme.substring(0, hostEnd)
        val path = if (hostEnd < 0) "/" else afterScheme.substring(hostEnd)
        if (host.isEmpty()) return "(unparseable)"
        return host + path.take(maxPath)
    }

    /**
     * `shouldDecode` 的三态：`null` = 页面没传这个键。
     *
     * **不能把"没传"读成 `false`** —— 看 smali（`DecodeHttpRequestWebAction:61-69`），
     * 缺键时宿主填的是 `-1`，然后 `if (v1 != -1)` 才走请求分支。
     * 所以"没传"与"传了 0"是两条不同的路径，合并会让观测结论错。
     */
    fun shouldDecode(raw: Int?): String = when (raw) {
        null -> "?"
        else -> raw.toString()
    }

    /**
     * `params` 的形状：`n:key1,key2,…`；空对象给 `0`，非对象给 `not-object`。
     *
     * 键名排序后再取前 [shown] 个 —— `JSONObject.keys()` 的顺序在实现上不稳定
     * （实测同一 payload 两次解析顺序不同），不排序会让同一请求产生两行不同记录，
     * 让"这条链路稳不稳"变成噪声。
     */
    fun paramsShape(keys: List<String>?, rawLen: Int, shown: Int = 6): String = when {
        keys == null -> "not-object"
        keys.isEmpty() -> "0"
        else -> {
            val sorted = keys.sorted()
            val head = sorted.take(shown).joinToString(",")
            if (sorted.size > shown) "keys=${sorted.size}:$head,…" else "keys=${sorted.size}:$head"
        }
    }

    /** 拼一行抓取记录。`redact` 关掉时只记 pathway 长度（与 `bridge_action_log_url` 同语义）。 */
    fun line(url: String, shouldDecode: String, params: String): String =
        "BRIDGE decodeHttpRequest url=$url shouldDecode=$shouldDecode params=$params"
}
