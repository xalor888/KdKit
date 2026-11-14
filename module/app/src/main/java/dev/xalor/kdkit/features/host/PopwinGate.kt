package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RawListMemo
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 服务端下发弹窗的总闸门（默认关闭，热开关）。
 *
 * ### 为什么这个钩点值一个功能
 *
 * 首页弹窗**一条都不是本地写死的**：App 请求 `/kdapi/conf/popwindow`，服务端返回
 * 一组 `Popwindow$ListItem`（字段 `type` / `sort` / `cycle` / `user`），客户端按
 * `type` 字符串分派。分派只有**一个**地方：
 *
 * ```smali
 * ei/y.smali:3470  .method private q()V              # 队列驱动：取 d[c] 这一项
 * ei/y.smali:1049  invoke-direct {p0, v0}, Lei/y;->G(Popwindow$ListItem;)V
 * ei/y.smali:929   .method private G(ListItem)V      # 读 item.type，做 old/new/all 频控
 * ei/y.smali:3444  invoke-direct {p0, p2, p1}, Lei/y;->H(String;ListItem;)V
 * ei/y.smali:1254  .method private H(String;ListItem;)V   # ← 8 个分支全在这里
 * ```
 *
 * `H` 覆盖了"服务端能下发的**全部**弹窗种类"——10 个类型字符串，9 个分派方法。
 * 所以钩住 `H` 一个方法，就同时拿到"这次下发了哪一类"和"要不要让它继续"。
 *
 * ### 10 种类型（哈希反解 + 分支体双向确认，不是猜的）
 *
 * 分派是 `String.hashCode()` 的 `sparse-switch`，类型字符串本身留在分支体里。
 * 两边对上才写进下表（`0xa07ec2c` 就是靠分支体里的 `"winVIPBottom"` 反解出来的）：
 *
 * | `type` | 分支 | 实际弹出的东西 | 静态证据 |
 * |---|---|---|---|
 * | `winUp` | `L()` | **强制更新**（`xl.z2.t(act,true,false,cb)`） | `y.smali:2113` |
 * | `winAd` | `A()` | **插屏广告**（`aj.a.d(pos)` 读广告位） | `y.smali:147` |
 * | `winImp` | `K()` | 激励弹窗（`ef.a` 回调 `y$f`） | `y.smali:2004` |
 * | `winVIPBottom` | `F()` | **VIP 购买页**（`zyb://kd-vip/page/vip-buy-paisou`） | `y.smali:767` |
 * | `winBook` | `D()` | 首页书籍推荐（`ei.s1`） | `y.smali:555` |
 * | `winFlow` | `I()` | 流量弹窗（`ei.d0`） | `y.smali:1808` |
 * | `winGradeSelect` | `J()` | 年级选择（`Popwincontent` 请求） | `y.smali:1886` |
 * | `winGradeUp` | `J()` | 年级升级（同一个 `J`） | `y.smali:1886` |
 * | `winActivity`（前缀）| `C(item)` | **活动弹窗**（`AdConfig$PopupAdItem` → `winActivity_<bid>`）| `y.smali:1337` |
 * | `winBottom`（前缀）| `E(item)` | **底部广告弹窗**（`winBottom_<bid>`） | `y.smali:1362` |
 *
 * 后两行走 `contains()` 而不是 `equals()`：真实取值是 `"winActivity_" + bid` /
 * `"winBottom_" + bid`（由 `r(I)` / `o(I)` 拼出），所以 `H` 收到的字符串是
 * `winActivity_7` 这种形态，前缀命中才是正解。
 * 也正因为如此，拦截清单里的 `winActivity*` 通配是**必需**的，不能只写裸名。
 *
 * ### 它做什么 / 不做什么
 *
 * **默认什么都不拦**：默认关闭时钩子照装，但回调只记一条 `POPWIN seen`，不改结果。
 * 打开后按 [KdOption] `popwin_block` 里列的类型名拦截（逗号分隔，`*` 通配前缀）。
 *
 * **为什么不直接默认全拦**：`winGradeUp` / `winGradeSelect` 是年级相关，`winUp` 是强制更新
 * （已有 `skip_update` 专门处理），全拦会把"正常业务提示"一起吞掉。默认给一个
 * 明确的、只含广告与销售的清单，其余要用户自己加。
 *
 * ### 与 `skip_update` 的关系
 *
 * `winUp` 分支调用的就是 `ei.y.L()`，而 `skip_update` 钩的正是 `L`。两者同时开时
 * `popwin_gate` 先短路、`L` 根本不会进 ⇒ 两个都只在日志里记一条，行为一致（都跳过）。
 * 保留两条是因为 `skip_update` 还负责 `forceUp` 抹零那一档，且它是独立可用的。
 *
 * ### 未验证
 *
 * **所有结论都只在静态层成立**：钩点存在（④）、签名吻合（⑤）、`H` 有本类调用（⑥）、
 * 编译过、纯逻辑单测过。**没有真机**跑过这个弹窗是否真的不出现。
 */
object PopwinGate : SwitchFeature(
    id = "popwin_gate",
    title = "服务端弹窗总闸门",
    summary = "按类型拦服务端下发的首页弹窗（广告/销售类默认拦，可自定义），未开时只观测不拦截",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val CLS = "hh.y"
    private const val LIST_ITEM = "com.kuaiduizuoye.scan.common.net.model.v1.Popwindow\$ListItem"
    private const val MAX = 60

    /**
     * `H` 里**全部** 10 个类型字符串，按 smali 出现顺序。
     *
     * 2026-10-25 复核修正：原列表只有 8 个，漏了 `winActivity` 与 `winBottom`——
     * 它们在 `H` 方法体里位于 `sparse-switch` 之前（第 84 / 109 行），
     * 分别走 `C(ListItem)` 与 `E(ListItem)`，与后面 8 个 `equals` 链分支形态不同，
     * 所以只数"分支体"会漏掉。
     *
     * 10 个类型 → 9 个分派方法（`winGradeUp` 与 `winGradeSelect` 同走 `J()`）。
     */
    val KNOWN_TYPES: List<String> = listOf(
        "winActivity", "winBottom",
        "winUp", "winAd", "winImp", "winVIPBottom",
        "winBook", "winFlow", "winGradeSelect", "winGradeUp",
    )

    /**
     * 只含"广告 / 销售"的类型：这是默认拦截清单，业务提示类刻意不在内。
     *
     * 每一项都有分支体证据，不是按名字猜的：
     *
     * | 项 | 证据 |
     * |---|---|
     * | `winAd` | `A()` 调 `aj.a.d(pos)` 读广告位 |
     * | `winVIPBottom` | `F()` 跳 `zyb://kd-vip/page/vip-buy-paisou`（销售页） |
     * | `winImp` | `K()` 走 `ef.a`（激励弹窗，带广告回调） |
     * | `winBottom*` | `E()` 直接 `MainBottomAdDialog.l` —— 名字里的 "Bottom" 是底部**广告**位 |
     * | `winActivity*` | `C()` new `ei.j0(Activity, AdConfig$PopupAdItem, ci.a)`，而 `ei.j0` 里全是 `TAB_ADVERTISE_SHOW` / `TAB_ADVERTISE_CLOSE` / `bid` / `tabType` |
     *
     * 通配写法是必需的：这两族的真实取值是 `winBottom_<bid>` / `winActivity_<bid>`，
     * 裸名 `winBottom` 只能匹配到"恰好等于 winBottom"的字符串，永远命中不了真实取值。
     */
    val DEFAULT_BLOCK: List<String> = listOf(
        "winAd", "winVIPBottom", "winImp", "winBottom*", "winActivity*",
    )

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "popwin_block",
            title = "拦截哪些弹窗类型",
            summary = "逗号分隔的类型名；支持前缀通配（如 winActivity* 拦全部活动弹窗）。留空=不拦",
            kind = KdOption.Kind.STRING,
            default = DEFAULT_BLOCK.joinToString(","),
        ),
        KdOption(
            key = "popwin_observe_only",
            title = "只观测，不拦截",
            summary = "开着时即使功能已启用也只记录不短路（用来先看清这台机器收到哪些类型）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        var n = 0
        // 先把 `ListItem` 解析出来再装钩子。**不能**把 `Xp.clazzOrNull(...)` 直接塞进 vararg：
        // 它返回 null 时 `findAndHookMethod` 收到的是"一个 null 形参"，抛 NPE 后被吞成
        // "hook failed" —— 看起来像目标改名，实际是这里没解析到，排错方向会被带偏。
        val item = Xp.clazzOrNull(LIST_ITEM)
        if (item == null) {
            KdLog.w("PopwinGate: $LIST_ITEM not found, hook skipped")
        } else if (Xp.hook(
                CLS, "H",
                String::class.java, item,
                gate = id, onBefore = { p -> onDispatch(p) },
            )
        ) n++
        KdLog.i("PopwinGate installed ($n hooks, known=${KNOWN_TYPES.size})")
    }

    /**
     * `H(type, item)` 的 before 回调。
     *
     * 拆成独立函数（不在闭包里写判断）是为了可测：`PopwinGate.decide(type, block, observeOnly)`
     * 是纯函数，单测直接调它，不需要 Xposed 环境（见 `PopwinGateTest`）。
     */
    private fun onDispatch(p: de.robv.android.xposed.XC_MethodHook.MethodHookParam) {
        val type = p.args.getOrNull(0)?.toString()
        if (!RateLimit.firstN("popwin.$type", MAX)) return
        val block = KdConfig.getString("popwin_block", DEFAULT_BLOCK.joinToString(","))
        val observeOnly = KdConfig.isOn("popwin_observe_only", false)
        val verdict = decide(type, block, observeOnly)
        Capture.append("POPWIN seen type=${type ?: "?"} block=${verdict.block} action=${verdict.action}")
        when (verdict.action) {
            Action.BLOCK -> {
                // `H` 返回 void ⇒ `result = null` 就是"直接 return-void"，整个分支体不执行。
                // 这一步必须放在这里而不是闭包里：短路是行为改变，要和判定写在一起才看得见。
                p.result = null
                KdLog.i("PopwinGate: blocked popwin type=$type")
            }
            Action.OBSERVE -> KdLog.d("PopwinGate: observed popwin type=$type")
            Action.PASS -> Unit
        }
    }

    enum class Action { PASS, OBSERVE, BLOCK }

    data class Verdict(val action: Action, val block: Boolean)

    /**
     * 纯判定（无 Xposed / 无配置读）：给定类型名与拦截清单，返回该走哪条路。
     *
     * 规则顺序是契约，改动会让"只观测"的语义漂移：
     *  1. 类型为空 ⇒ `PASS`（拿不到类型就绝不拦，宁可放过不可误杀）；
     *  2. 命中清单 且 `observeOnly` ⇒ `OBSERVE`（记录但放行）；
     *  3. 命中清单 ⇒ `BLOCK`；
     *  4. 未命中 ⇒ `PASS`。
     */
    fun decide(type: String?, block: String, observeOnly: Boolean): Verdict {
        val blocked = matches(type, block)
        return when {
            type.isNullOrBlank() -> Verdict(Action.PASS, false)
            blocked && observeOnly -> Verdict(Action.OBSERVE, true)
            blocked -> Verdict(Action.BLOCK, true)
            else -> Verdict(Action.PASS, false)
        }
    }

    /**
     * 清单匹配：逗号分隔，去空白，`*` 作**尾部**通配。
     *
     * 只支持尾部 `*`（`winActivity*`）：它是真实存在的前缀拼接（`"winActivity_" + bid`），
     * 而中间通配会让"拦 winAd"意外吃掉"拦 winAdSlot"，那是另一种误杀。
     */
    /**
     * 清单解析的**单槽记忆**：`block` 是配置字符串，弹窗钩子每次分发都会问一次
     * `matches()`，而那份清单几乎不变。旧实现每次 `split + map + filter` 四趟分配
     * —— 与 R9 的 `BridgeGuard` 黑名单、R45 的 `NavFilter` 正则是同一类问题：
     * **热路径上的重复计算**。三处修法一致：按原始字符串记住解析结果。
     */
    private val listMemo = RawListMemo()

    fun matches(type: String?, block: String): Boolean {
        if (type.isNullOrBlank()) return false
        return listMemo.get(block) { raw ->
            raw.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        }.any { pat ->
                when {
                    pat == "*" -> true
                    pat.endsWith("*") -> type.startsWith(pat.dropLast(1))
                    else -> type.equals(pat, ignoreCase = true)
                }
            }
    }

    /** 诊断：本次进程里见过多少种类型（升序，便于贴进报告）。 */
    fun seenTypes(): List<String> = RateLimit.stats().keys
        .filter { it.startsWith("popwin.") }
        .map { it.removePrefix("popwin.") }
        .sorted()
}
