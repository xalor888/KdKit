package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * H5 桥调用记录：网页调用原生的**每一个 action** 都记一笔（名字 + 参数 + 次数）。
 *
 * `work/feactions.txt` 是静态清单（215 个 `@FeAction`），但"哪些真的被调用、带什么参数"只有跑起来才知道。
 * 分发入口是 `HybridWebView.dispatchAction(ActionListener, String, JSONObject, ReturnCallback)`
 * 与 `dispatchActionToListeners(String, JSONObject, ReturnCallback, String)`。
 *
 * 输出分两路：模块日志（每 action 首几次）+ 宿主私有目录的 `kdkit_capture.txt` 里 `H5BRIDGE …`
 * 行（完整、去重后封顶），`kit/python/capture_transcript.py` 能直接读。
 * 默认关闭 —— 它记录的是页面与原生之间的真实交互数据。
 */
object H5BridgeLog : SwitchFeature(
    id = "h5_bridge_log",
    title = "H5 桥调用记录",
    summary = "记录网页调用的原生 action（名字/参数/次数），用于把静态 FeAction 清单变成实盘调用图",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val PER_ACTION_LOGS = 3
    private val seen = ConcurrentHashMap<String, AtomicInteger>()
    private const val PER_ACTION_CAPTURE = 200

    override fun install() {
        var n = 0
        // 分开写：静态门禁（check_hook_targets.py）就能逐条校验"类+方法"是否存在
        n += Xp.hookAllBefore("com.baidu.homework.common.ui.widget.HybridWebView", "dispatchAction",
            Xp.classLoader, gate = id) { param -> record(param) }
        n += Xp.hookAllBefore("com.baidu.homework.common.ui.widget.HybridWebView", "dispatchActionToListeners",
            Xp.classLoader, gate = id) { param -> record(param) }
        // 出站：`ReturnCallback.call(String)` 是**所有桥 action 把答案交回 JS 的唯一出口**
        // （全 APK 277 处调用）。只挂入站的话，抓取里能回答"页面调了什么"，
        // 但回答不了"宿主回了什么" —— 而 H5 侧的 bug 往往在后者。
        // `Xp.hook` 返回 Boolean（而 `Xp.hookAll*` 返回成功条数），所以这里用 if 累加。
        if (Xp.hook("com.baidu.homework.common.ui.widget.HybridWebView\$ReturnCallback", "call",
                String::class.java, gate = id, onBefore = { p -> recordReturn(p) })
        ) n++
        KdLog.i("H5BridgeLog installed ($n hooks)")
    }

    /**
     * 记出站返回值。
     *
     * `ReturnCallback` 不知道自己在回应哪个 action —— 它只有一个 `callbackFun` 字段
     * （构造器赋值、`call()` 里用来拼 `javascript:<fun>(...)`）。
     * 反射读出它，至少能把"这条回答发给谁"记下来。
     *
     * **不做 action 配对推断**：`dispatchAction` 与 `call` 之间没有稳定的一对一关系
     * （可能延迟回调、可能多次回调、也可能根本不回）。硬凑配对会造出看起来很确定、
     * 实际是猜的关联 —— 那比不配对更糟。所以两条记录各自带 `callbackFun`，配对留给读者。
     */
    private fun recordReturn(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        val payload = p.args.getOrNull(0) as? String ?: return
        val funName = runCatching {
            val f = p.thisObject?.javaClass?.getDeclaredField("callbackFun")
            f?.isAccessible = true
            f?.get(p.thisObject)?.toString()
        }.getOrNull()
        val count = retSeen.computeIfAbsent(funName ?: "?") { AtomicInteger() }.incrementAndGet()
        if (count > PER_ACTION_CAPTURE) return
        Capture.append("H5RET ${funName ?: "?"} count=$count len=${payload.length} ${payload.take(400)}")
    }

    private fun record(param: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        val action = param.args.firstOrNull { it is String } as? String ?: return
        if (action.isEmpty()) return
        val json = param.args.firstOrNull { it is JSONObject } as? JSONObject
        val count = seen.computeIfAbsent(action) { AtomicInteger() }.incrementAndGet()
        if (count <= PER_ACTION_LOGS) {
            KdLog.i("H5Bridge: $action #$count ${json?.toString()?.take(200) ?: ""}")
        }
        // 每 action 上限 200 条：桥是高频面（实测一页 139 次调用），不设上限会淹没整个抓取文件。
        if (count <= PER_ACTION_CAPTURE) {
            capture("H5BRIDGE $action count=$count ${json?.toString()?.take(600) ?: ""}")
        }
    }

    private val retSeen = java.util.concurrent.ConcurrentHashMap<String, AtomicInteger>()

    private fun capture(line: String) = Capture.append(line)

}
