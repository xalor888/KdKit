package dev.xalor.kdkit.util

/**
 * 「页面让宿主代发请求」这条链路的**来源归属**与**请求形状**（纯逻辑，无 Android / Xposed，可 JVM 直测）。
 *
 * ### 它回答的问题
 *
 * 宿主把 H5 桥里一批 action 做成了"页面给 URL + params，宿主用**自己的签名器**发出去"。
 * 这类 action 的共同出口是 `dr.f.a(dr.f$e, String url, Map params, Class, int, JSONObject, JSONObject)`：
 *
 * ```smali
 * dr/f.smali:30  .method public static a(Ldr/f$e;Ljava/lang/String;Ljava/util/Map;…)Lcom/android/volley/v;
 *                → 转调 b(Activity, dr.f$e, url, params, Class, int, …)
 *                → Net.post(context, InputBase, SuccessListener, ErrorListener)   (:92 起)
 * ```
 *
 * 静态实测有 **4 个调用点 / 3 个宿主 action** 走这条出口（`EncryptDataRequestAction:190`、
 * `CoreHttpRequestAction:905`、`:960`，另有 `HttpFileUploadRequestAction` 自己的
 * `finalExecuteRequest` 独立路径，不走 `dr.f.a`）—— 复跑：
 *
 * ```
 * grep -rn 'Ldr/f;->a(Ldr/f$e' work/apktool_out --include=*.smali
 * ```
 *
 * 也就是说：**只要钩这一个静态方法，就能看到"哪一个页面 action 让宿主发了什么请求"**，
 * 而不必每个 action 各钩一次（那样每加一个 action 就要改一次代码，且漏掉的永远不会被发现）。
 *
 * ### 为什么"来源"能算出来
 *
 * `dr.f.a` 的第一个形参是接口 `dr/f$e`（网络回调）。每个调用点传的都是**本 action 的匿名内部类**，
 * 其 `EnclosingMethod` 注解指向真正发起请求的方法：
 *
 * ```
 * dr/f$1.smali  → EnclosingMethod: EncryptDataRequestAction;->netRequest(String, Map, ReturnCallback)V
 * dr/f$…        → EnclosingMethod: CoreHttpRequestAction;->onAction(Activity, JSONObject, ReturnCallback)V
 * ```
 *
 * 所以 `thisObject.javaClass.name` 形如 `…EncryptDataRequestAction$1`。把 `$` 之后**纯数字**的
 * 后缀去掉，就得到能直接读的 action 类名 —— 这正是抓取里需要的"谁在驱动"。
 *
 * **注意**：这只能回答"是哪个 action 的内部类"。运行时真正的调用栈（哪个 H5 页面）拿不到，
 * 与 `bridge_action_log` 的其余部分同一条纪律：不假装能证明拿不到的东西。
 *
 * ### 为什么不记值
 *
 * 抓取文件是**明文落盘**的。这类请求的 `params` 里常有 token / 手机号 / 作答内容。
 * 记「几个键、键名排序后的前几个」足以回答"页面在驱动什么请求"，
 * 与 `DecodeRequestShape.paramsShape` 完全同一个口径（复用它的实现，避免两处漂移）。
 */
object PageRequestOrigin {

    /** 没拿到来源时的占位。**不编造**类名。 */
    const val UNKNOWN = "(unknown)"

    /**
     * 把内部类名收敛成"发起请求的那个 action"。
     *
     * ```
     * com.x.EncryptDataRequestAction$1        -> EncryptDataRequestAction
     * com.x.EncryptDataRequestAction$1$Inner  -> EncryptDataRequestAction$1$Inner  （非纯数字，原样保留）
     * com.x.Foo                               -> Foo
     * ```
     *
     * 只剥**末尾**那一段纯数字后缀（`$1`、`$12`），因为那是 javac/kotlinc 给匿名类的编号：
     * 它随编译变动，写进抓取会让同一逻辑在不同版本间对不上。
     * 具名内部类（`$Companion`、`$Failure`）是**稳定的语义名**，必须保留 ——
     * 一刀切 `substringBefore('$')` 会把 `$Failure` 与 `$Success` 合并成同一个来源。
     */
    fun actionOf(innerClassName: String?): String {
        if (innerClassName.isNullOrBlank()) return UNKNOWN
        val simple = innerClassName.substringAfterLast('/').substringAfterLast('.')
        if (simple.isEmpty()) return UNKNOWN
        val parts = simple.split('$')
        val kept = ArrayList<String>(parts.size)
        for (p in parts) {
            // 纯数字（且非首段）才是匿名编号；首段是真实类名，不可能被剥掉。
            if (kept.isNotEmpty() && p.isNotEmpty() && p.all { it.isDigit() }) continue
            kept.add(p)
        }
        val out = kept.joinToString("$")
        return out.ifEmpty { UNKNOWN }
    }

    /**
     * URL 只留 host + path。
     *
     * 与 `DecodeRequestShape.redactUrl` **同一口径**，这里直接复用：
     * 两处各写一遍是漂移的来源（本项目已经因为"同一规则两处实现"踩过坑）。
     */
    fun redactUrl(raw: String, maxPath: Int = 80): String = DecodeRequestShape.redactUrl(raw, maxPath)

    /**
     * `Map` 形参的形状：`n:key1,key2,…`。
     *
     * 键名**排序**后再截断 —— `HashMap` 遍历顺序不稳定，不排序会让同一请求产生两行不同记录。
     * 这里只接 `Collection<String>`（键集合）而不是 `Map`，是为了能在 JVM 单测里直接喂数据，
     * 不需要把 `java.util.Map` 伪装出来。
     */
    fun paramsShape(keys: Collection<String>?, shown: Int = 6): String =
        DecodeRequestShape.paramsShape(keys?.toList(), keys?.size ?: 0, shown)

    /**
     * 拼一行抓取记录。
     *
     * ```
     * PAGEREQ from=EncryptDataRequestAction url=host/path params=keys=3:a,b,c method=1
     * ```
     *
     * 用**独立前缀** `PAGEREQ` 而不是复用 `BRIDGE`：`capture_schema.PREFIX_FEATURE` 由
     * `setdefault` 派生（一个 token 只能有一个归属功能），`BRIDGE` 已属于
     * `bridge_action_log`。复用会让两个功能的行混在同一个前缀名下，`grep BRIDGE`
     * 就不再等于"bridge_action_log 的记录" —— 归属清晰比前缀复用重要。
     */
    fun line(from: String, url: String, params: String, method: Int? = null): String {
        // `method` 由本函数自己拼，**不留给调用方** —— 曾经是两段拼接
        // （`line(…) + " method=$method"`），任何一处漏写就静默变成 UNKNOWN，
        // 而 UNKNOWN 行在报告里只是"一行没有规则认领"，看不出是这里漏的。
        //
        // `null` 时写 `?`（schema 的正则接受 `-?[0-9]+|\?`），
        // 这样"方法未知"是一个显式状态，不是靠省略字段表达。
        val m = method?.toString() ?: "?"
        return "PAGEREQ from=$from url=$url params=$params method=$m"
    }
}
