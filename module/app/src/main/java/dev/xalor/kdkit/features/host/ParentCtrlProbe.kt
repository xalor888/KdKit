package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.ParentCtrlShape
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 家长模式闸门的**形状观测**（默认关闭，热开关，只记录不改行为）。
 *
 * ### 它观测什么
 *
 * 宿主有一套家长控制（家长模式），四个子项的开关由服务端 AB 配置下发：
 *
 * | 字段 | 语义（按类名推断，**未验证**） |
 * |---|---|
 * | `aiwriting` | AI 写作 |
 * | `book` | 书本/搜题 |
 * | `correctsearch` | 批改搜索 |
 * | `picsearch` | 拍照搜索 |
 *
 * 页面侧还能通过 H5 桥读到同一份数据（`app_kdzy_parent_model_current_mode`
 * → `ParentModeCurrentModeWebAction` → `dj.e.f()` → Gson 序列化后回给页面）。
 *
 * ### 为什么钩 `dj.e.f()`
 *
 * ```smali
 * smali_classes5/dj/e.smali:2144
 *   .method public final f()Lcom/kuaiduizuoye/scan/activity/parentmodel/util/ParentCtrlData;
 *     → g()                                      本类：本地缓存
 *     → AbSdkGetValueUtil.k()                    远程下发的 AB 值
 *     → c(ParentCtrlData)                        两者合并
 *     → 返回合并结果
 * ```
 *
 * 它是那份数据的**唯一汇聚点**：本地缓存和远程 AB 在方法体内合并，
 * 之后所有消费方（页面桥、设置页、各功能判定）拿到的都是这一份。
 * 钩它的好处是**不必逐个 action 追**：新加一个读家长模式的页面 action 也不用改代码。
 *
 * 静态证据（可复跑）：
 *
 * ```
 * $ python3 kit/scripts/smali_usage.py --target dj.e:f
 *   USED    直接 3 / 类引 28
 *   例: MainActivity$b.smali:133
 *        BookCompleteDetailsPictureBrowseActivity.smali:8342
 *        ParentModeCurrentModeWebAction.smali:133
 * ```
 *
 * ### 钩子的形态（不写 `const val`，见 `PARADIGM.md` §7.6.1）
 *
 * 类名与方法名写成**字面量**。写 `const val CLS` 会让 ④⑤⑥ 三道门完全看不见这条钩子 ——
 * 这个盲区在本仓库已经出现过三次（`RouteLog` / `HttpBodyProbe` / `PageRequestLog`）。
 *
 * ### 它不做什么
 *
 * * **不改**任何闸门取值（不是"解锁家长模式"）。只读，`after` 里读返回值。
 * * **不**把取值翻译成"已限制 / 已解锁" —— 哪个值代表允许只能从服务端语义看，
 *   抓取里拿不到。所以只记录原始 `int` + 一个掩码（见 [ParentCtrlShape]）。
 * * 不声称覆盖"所有家长模式判定"：`dj.e.f()` 是数据出口，但判定可能还有别处。
 *   这一格标**未验证**。
 */
object ParentCtrlProbe : SwitchFeature(
    id = "parent_ctrl_probe",
    title = "家长模式闸门观测",
    summary = "钩 dj.e.f()（家长控制数据的唯一汇聚点：本地缓存 + 远程 AB 合并），记录四个闸门字段的原始取值与掩码；只观测不改行为",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    /** 单进程最多记这么多条 —— 这个方法会被设置页/页面桥反复调用。 */
    private const val MAX = 300

    override fun install() {
        // 返回类型在 after 回调里按类名取字段，所以**必须**先确认类存在；
        // 否则钩子装上了、每次回调解引用都抛 NoClassDefFound，表现为"功能静默无输出"。
        val data = Xp.clazzOrNull(DATA_CLS)
        if (data == null) {
            KdLog.w("ParentCtrlProbe: $DATA_CLS 缺失，跳过（宿主换版？）")
            return
        }
        // 类名/方法名写字面量：④⑤⑥ 只按字面量解析。
        val n = if (Xp.hook(
                "ul.b", "f",
                gate = id,
                onAfter = { p -> record(p) },
            )
        ) 1 else 0
        KdLog.i("ParentCtrlProbe installed ($n hooks)")
    }

    private fun record(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!RateLimit.firstN("parentCtrl", MAX)) return
        val v = p.result ?: run {
            // 返回 null 本身是信息（可能是"还没拉到配置"），记一条就够，别每帧刷。
            if (RateLimit.firstN("parentCtrl.null", 3)) {
                Capture.append("${ParentCtrlShape.PREFIX} unavailable reason=null-return")
            }
            return
        }
        // 反射读四个 getter。**逐个 try**：某一个 getter 改名不该让整条记录消失。
        Capture.append(
            ParentCtrlShape.line(
                intOf(v, "getAiwriting"),
                intOf(v, "getBook"),
                intOf(v, "getCorrectsearch"),
                intOf(v, "getPicsearch"),
            )
        )
    }

    /**
     * 读一个 `getXxx()I`。读不到返回 `null`（→ 写 `?`），**不返回 0**。
     *
     * 三个不同的失败原因（方法不存在 / 调用抛异常 / 返回值不是 Int）都归到 `null`：
     * 抓取只能表达"读到了什么"，分不清原因时写 `?` 比猜一个原因更诚实。
     */
    private fun intOf(obj: Any, getter: String): Int? = try {
        val m = obj.javaClass.getMethod(getter)
        (m.invoke(obj) as? Int)
    } catch (t: Throwable) {
        null
    }

    private const val DATA_CLS = "com.kuaiduizuoye.scan.parentmode.api.ParentCtrlData"
}
