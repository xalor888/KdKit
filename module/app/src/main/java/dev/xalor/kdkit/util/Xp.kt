package dev.xalor.kdkit.util

import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedBridge
import de.robv.android.xposed.XposedHelpers
import dev.xalor.kdkit.config.KdConfig

/**
 * Xposed 薄封装：所有钩子都从这里过，因此**台账**（[HookAudit]）与**门控**（`gate`）只需要实现一次。
 *
 * 三条不变式：
 *  1. 钩子失败**永不抛出**给宿主 —— 一个类被改名不该让 App 崩掉；
 *  2. 每条钩子的成败都记账（`HookAudit`），这样"少挂了几条"是可查的结论而不是被淹没的日志行；
 *  3. `gate` 非空时，回调在**调用点**先问配置 —— 于是开关切换不必重启宿主（热开关），
 *     而且"关掉"等价于"回调不执行"，原方法照旧跑，行为可预测。
 *
 * 第 3 条里的「没有配置时算不算开」必须走 [GatePolicy.defaultFor]（= 功能自己声明的
 * `defaultOn`），**不能**写常量 `true`：2026-11-01 审查查出，写死 `true` 会让 24 个
 * `defaultOn = false` 的 hot 功能在用户没点过开关时照样生效，界面显示「关」而实际在改行为。
 */
object Xp {

    /**
     * 目标方法是否返回 `void`。
     *
     * `param.result = null` 的语义是"跳过原实现、用这个值当返回值"。对 `V` 无害；
     * 对有返回值的方法，调用方会拿到 `null` 并崩溃，而症状与拦截本身毫无关系
     * （2026-11-02 审查 P2-10）。
     */
    fun returnsVoid(param: XC_MethodHook.MethodHookParam): Boolean =
        (param.method as? java.lang.reflect.Method)?.returnType == Void.TYPE

    /**
     * 目标方法是否返回 `boolean`（`Z`）。
     *
     * 在 before 钩里写 `param.result = false` 只对 boolean 方法成立；
     * 写到一个返回对象的方法上，调用方拿到的会是 `Boolean.FALSE` 而不是它期望的类型
     * （2026-11-02 审查 P2-11）。
     */
    fun returnsBoolean(param: XC_MethodHook.MethodHookParam): Boolean =
        (param.method as? java.lang.reflect.Method)?.returnType == java.lang.Boolean.TYPE
    @Volatile var classLoader: ClassLoader? = null

    /** 当前正在安装哪个功能的钩子（由 [under] 设置），用于台账归属。 */
    private val owner = ThreadLocal<String?>()

    /** 在 [ownerId] 名下安装钩子；之后每条 [hook] 都记到它账上。 */
    fun <T> under(ownerId: String, block: () -> T): T {
        val prev = owner.get()
        owner.set(ownerId)
        try {
            return block()
        } finally {
            owner.set(prev)
        }
    }

    fun clazz(name: String, cl: ClassLoader? = classLoader): Class<*> =
        XposedHelpers.findClass(name, cl)

    /**
     * 解析类，失败返回 null。
     *
     * **null 本身要记账**：调用点通常写 `val c = clazzOrNull(X) ?: return`，
     * 于是这条钩子连"尝试"都没有 —— 在 [HookAudit] 里既不是 ok 也不是 failed，
     * 完全隐形。所以这里在返回 null 时记一条 `skipped`，启动日志能点名。
     *
     * 代价：同一功能多次调用同一个缺失类会重复计数，所以去重交给 [HookAudit]
     * 的列表（按 `功能:类` 字符串去重后再打印）。
     */
    fun clazzOrNull(name: String, cl: ClassLoader? = classLoader): Class<*>? =
        try {
            XposedHelpers.findClass(name, cl)
        } catch (t: Throwable) {
            HookAudit.recordSkipped(owner.get(), "$name (class not found)")
            KdLog.d("clazzOrNull miss: $name")
            null
        }

    /**
     * Hook 一个方法。返回 false 表示目标缺失/签名不符（已记账，不抛）。
     *
     * [gate] 是功能 id：非空时，回调执行前会检查该开关的**当前**值 —— 关着就直接返回，
     * 原方法行为不变。这让"装了钩子"与"功能生效"解耦（热开关）。
     */
    /**
     * `gate` 的**唯一判据**（2026-11-04 收敛）。
     *
     * 原来这条判据在 `Xp.kt` 里**抄了 6 遍**（`hook` ×2 / `hookCtor` ×2 /
     * `hookAllBefore` / `hookAllAfter`）。抄 6 遍的风险不是"抄错"，
     * 而是**改的时候漏改** —— 而漏改的那一处会让"关掉功能"失效，
     * 症状是 UI 上开关是关的、App 侧行为完全不变，**不报错**。
     *
     * 收敛成一个函数后：改一处 ⇒ 六处一起变；
     * 而且"这六处都调用它"这件事由 `check_hook_gate_predicate.py` 静态钉住。
     */
    internal fun gateOpen(gate: String?): Boolean {
        if (gate == null) return true
        return KdConfig.isOn(gate, GatePolicy.defaultFor(gate))
    }

    fun hook(
        className: String,
        methodName: String,
        vararg paramTypes: Class<*>?,
        cl: ClassLoader? = classLoader,
        gate: String? = null,
        onBefore: ((XC_MethodHook.MethodHookParam) -> Unit)? = null,
        onAfter: ((XC_MethodHook.MethodHookParam) -> Unit)? = null,
    ): Boolean {
        val tag = "$className.$methodName"
        return try {
            XposedHelpers.findAndHookMethod(className, cl, methodName, *paramTypes, object : XC_MethodHook() {
                override fun beforeHookedMethod(param: MethodHookParam) {
                    if (!gateOpen(gate)) return
                    onBefore?.invoke(param)
                }
                override fun afterHookedMethod(param: MethodHookParam) {
                    if (!gateOpen(gate)) return
                    onAfter?.invoke(param)
                }
            })
            HookAudit.record(owner.get(), tag, true)
            KdLog.d("hooked $tag${if (gate != null) " [gate=$gate]" else ""}")
            true
        } catch (t: Throwable) {
            HookAudit.record(owner.get(), tag, false)
            KdLog.w("hook failed $tag: $t")
            false
        }
    }

    /**
     * Hook 一个**构造器**。
     *
     * 为什么单独一个函数：`XposedHelpers.findAndHookMethod(cls, "<init>", args...)` 永远失败
     * —— 它按方法名查找，而构造器没有名字。必须走 `findAndHookConstructor`。
     * 这个坑此前一直没暴露，因为那条钩子所在的 `RC4Probe` 目标没被静态门禁覆盖。
     */
    fun hookCtor(
        className: String,
        vararg paramTypes: Class<*>?,
        cl: ClassLoader? = classLoader,
        gate: String? = null,
        onBefore: ((XC_MethodHook.MethodHookParam) -> Unit)? = null,
        onAfter: ((XC_MethodHook.MethodHookParam) -> Unit)? = null,
    ): Boolean {
        val tag = "$className.<init>"
        return try {
            XposedHelpers.findAndHookConstructor(className, cl, *paramTypes, object : XC_MethodHook() {
                override fun beforeHookedMethod(param: MethodHookParam) {
                    if (!gateOpen(gate)) return
                    onBefore?.invoke(param)
                }
                override fun afterHookedMethod(param: MethodHookParam) {
                    if (!gateOpen(gate)) return
                    onAfter?.invoke(param)
                }
            })
            HookAudit.record(owner.get(), tag, true)
            KdLog.d("hooked ctor $tag${if (gate != null) " [gate=$gate]" else ""}")
            true
        } catch (t: Throwable) {
            HookAudit.record(owner.get(), tag, false)
            KdLog.w("hook ctor failed $tag: $t")
            false
        }
    }

    /** Hook 一个类上所有同名方法（任何签名），统一回调。返回成功条数。 */
    fun hookAll(className: String, methodName: String, cl: ClassLoader? = classLoader, cb: XC_MethodHook): Int {
        val c = clazzOrNull(className, cl) ?: run {
            HookAudit.record(owner.get(), "$className.$methodName", false)
            return 0
        }
        var n = 0
        for (m in c.declaredMethods) {
            if (m.name != methodName) continue
            try { XposedBridge.hookMethod(m, cb); n++ } catch (_: Throwable) {}
        }
        HookAudit.record(owner.get(), "$className.$methodName", n > 0)
        return n
    }

    /** [hookAll] 的 before 版（观测用：只看参数、不改行为）；`gate` 语义同 [hook]。 */
    fun hookAllBefore(
        className: String,
        methodName: String,
        cl: ClassLoader? = classLoader,
        gate: String? = null,
        cb: (XC_MethodHook.MethodHookParam) -> Unit,
    ): Int {
        val c = clazzOrNull(className, cl) ?: run {
            HookAudit.record(owner.get(), "$className.$methodName", false)
            return 0
        }
        var n = 0
        for (m in c.declaredMethods) {
            if (m.name != methodName) continue
            try {
                XposedBridge.hookMethod(m, object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        if (!gateOpen(gate)) return
                        cb(param)
                    }
                })
                n++
            } catch (_: Throwable) {}
        }
        HookAudit.record(owner.get(), "$className.$methodName", n > 0)
        return n
    }

    /** [hookAll] 的 after 版（与 [hookAllBefore] 成对命名，避免重载歧义）。 */
    fun hookAllAfter(
        className: String,
        methodName: String,
        cl: ClassLoader? = classLoader,
        gate: String? = null,
        onAfterCb: (XC_MethodHook.MethodHookParam) -> Unit,
    ): Int {
        val c = clazzOrNull(className, cl) ?: run {
            HookAudit.record(owner.get(), "$className.$methodName", false)
            return 0
        }
        var n = 0
        for (m in c.declaredMethods) {
            if (m.name != methodName) continue
            try {
                XposedBridge.hookMethod(m, object : XC_MethodHook() {
                    override fun afterHookedMethod(param: MethodHookParam) {
                        if (!gateOpen(gate)) return
                        onAfterCb(param)
                    }
                })
                n++
            } catch (_: Throwable) {}
        }
        HookAudit.record(owner.get(), "$className.$methodName", n > 0)
        return n
    }
}
