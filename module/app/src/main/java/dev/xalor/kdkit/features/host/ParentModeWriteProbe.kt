package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.ParentModeWriteShape
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 家长模式**写入侧**的形状观测（默认关闭，热开关，只记录不改行为）。
 *
 * ### 为什么需要它：只钩读侧分不清"下发"与"本地改动"
 *
 * `parent_ctrl_probe` 钩 `dj.e.f()`，看的是宿主**当前**认为四个闸门是什么。
 * 但看到 `aiwriting=0` 有两种完全不同的成因：
 *
 * * 服务端下发的就是 0（策略如此）；
 * * 本地被改成了 0，正等着提交（或提交已经失败）。
 *
 * 读侧**结构上无法区分**这两件事 —— 它只看到一个结果值。
 * 写侧那行出现即证明"确实发生过一次提交尝试"，六个字段是**提交时的快照**。
 * 两行的时间戳一前一后，"下发"与"提交"就分开了。
 *
 * ### 钩点与静态证据（可复跑）
 *
 * ```smali
 * smali_classes5/dj/e.smali:1169
 *   .method private final l(L…/ParentCtrlData;IL…/Callback;)V
 *     → KdcoreUserSetParentMode$Input.buildInput(IIIIII)   组装六个 int
 *     → Net.post(context, input, success, error)           POST /kdcore/user/setparentmode
 * ```
 *
 * 六个字段与读侧的关系：
 *
 * | 字段 | 读侧有吗 | 语义（按类名推断，**未验证**） |
 * |---|---|---|
 * | `aiwriting` | 有 | AI 写作 |
 * | `book` | 有 | 书本/搜题 |
 * | `correctsearch` | 有 | 批改搜索 |
 * | `picsearch` | 有 | 拍照搜索 |
 * | `from` | **无** | 本次提交的来源（枚举语义未验证） |
 * | `userMode` | **无** | 提交时的模式（枚举语义未验证） |
 *
 * 写侧比读侧多两个字段，这不是冗余：`from` 可能区分"用户在设置页手动改"
 * 与"宿主按引导流程自动写"，而那两种在抓取里的处置方式完全不同。
 *
 * 静态证据：
 *
 * ```
 * $ python3 kit/scripts/smali_usage.py --target dj.e:l
 *   USED(self)   直接 0 / 自调 2 / 类引 28
 *   例: MainActivity$b.smali:129
 *        BookCompleteDetailsPictureBrowseActivity$a.smali:346
 * ```
 *
 * `USED(self)` 是因为 `l` 是 `private final`，入口在本类的公开方法上
 * （`PARADIGM.md` §7.6 第 6 条：非 `DEAD` 即可钩）。
 *
 * ### 钩子的形态（不写 `const val`，见 `PARADIGM.md` §7.6.1）
 *
 * 类名与方法名写成**字面量**。写 `const val CLS` 会让 ④⑤⑥ 三道门完全看不见这条钩子 ——
 * 这个盲区在本仓库已经出现过三次（`RouteLog` / `HttpBodyProbe` / `PageRequestLog`）。
 *
 * ### 它不做什么
 *
 * * **不改**任何提交内容（不是"伪造家长模式"）。只在 `before` 里读实参。
 * * 不记录 `Callback` 的结果：那是"服务端是否接受"，属于另一层证据，
 *   静态无法证明它一定会被调用。本功能只证明"发起了提交"。
 * * 不声称覆盖"所有家长模式写入"：`dj.e.l` 是这条链路的汇聚点，
 *   但 `setparentmode` 也可能有别的调用方。这一格标**未验证**。
 */
object ParentModeWriteProbe : SwitchFeature(
    id = "parent_ctrl_write",
    title = "家长模式提交观测",
    summary = "钩 dj.e.l()（家长控制写入侧：组装六个 int 后 POST /kdcore/user/setparentmode），记录提交快照；与 parent_ctrl_probe 的读侧对照可分开\"下发\"与\"提交\"",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    /** 单进程最多记这么多条 —— 家长设置页可能被反复操作。 */
    private const val MAX = 100

    override fun install() {
        // 方法名/类名写字面量：④⑤⑥ 只按字面量解析。
        // `l` 是 private，但 Xposed 按名字找方法，可见性不影响。
        // 形参必须写全：`dj.e.l(LParentCtrlData;ILCallback;)V`
        // （`record()` 已经在按这三个实参读 `args[0]`/`args[1]`）。
        // 只写类名+方法名会让 ⑤ 报 `SIGNATURE-MISMATCH` —— 而这条钩子
        // 在真机上会因为形参数不匹配**静默拿不到 args**，正是 ⑤ 存在的理由。
        // 三个形参都写成**字面量**（`Xp.clazz(...)` 按类名解析成 Class）：
        // ⑤ 只按字面量拼签名，传变量会让它拼出不完整的签名并误报 MISMATCH。
        val n = if (Xp.hook(
                "ul.b", "l",
                Xp.clazz("com.kuaiduizuoye.scan.parentmode.api.ParentCtrlData"),
                Int::class.javaPrimitiveType,
                Xp.clazz("com.baidu.homework.base.Callback"),
                gate = id,
                onBefore = { p -> record(p) },
            )
        ) 1 else 0
        KdLog.i("ParentModeWriteProbe installed ($n hooks)")
    }

    /**
     * 从实参读提交快照。
     *
     * 形参是 `(ParentCtrlData, int, Callback)`：
     *
     * * `args[0]` —— 要提交的数据对象，四个闸门从它的 getter 读；
     * * `args[1]` —— `from`（int，直接是实参，不用反射）；
     * * `args[2]` —— 回调，**不读**（见类文档）。
     *
     * `userMode` 不在这三个实参里：它由 `buildInput` 从对象内部取。
     * 这里尝试从数据对象读（`getUserMode`），读不到写 `?` —— 不猜。
     */
    private fun record(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        if (!RateLimit.firstN("parentWrite", MAX)) return
        val args = p.args
        if (args == null || args.isEmpty()) return
        val data = args[0] ?: run {
            // 实参是 null 本身是信息（"清空家长模式"可能就是发 null），记一条。
            Capture.append("${ParentModeWriteShape.PREFIX} unavailable reason=null-arg")
            return
        }
        val from = args.getOrNull(1) as? Int
        // `userMode` 不在实参里；从数据对象上试读，读不到写 `?`。
        Capture.append(
            ParentModeWriteShape.line(
                intOf(data, "getAiwriting"),
                intOf(data, "getBook"),
                intOf(data, "getCorrectsearch"),
                intOf(data, "getPicsearch"),
                from,
                intOf(data, "getUserMode"),
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
}
