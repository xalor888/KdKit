package dev.xalor.kdkit.features.misc

import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedHelpers
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 签名 / 密钥观测：把 kit/hooks/01_rc4_helper.js + 02_net_sign.js 的 Frida 钩子搬进
 * 进程内（模块自带，不经过 ptrace，因此不会被宿主的反调试链杀掉 —— 见 ROADMAP R1）。
 *
 * 观测点（链路见 work/TRIAGE.md §3.1 / §3.2）：
 *   Net.appendSign(InputBase)          最终拼接出的完整签名 URL（含加密 param=）
 *   com.zuoyebang.baseutil.a.d(List)   排序后的待签参数 + nativeGetSign 结果
 *   com.zuoyebang.baseutil.a.b(String) nativeGetKey —— 实时 RC4 密钥
 *   yl.f.g/h(String)                   H5 / 请求体 RC4 解密、加密
 *   yl.f.y()                           密钥刷新（随后读字段 b）
 *
 * 输出分两路：
 *   * 模块日志 / logcat（KdKit tag）—— 截断到 300 字符，便于人看；
 *   * **宿主应用私有目录里的完整抓取文件** `<filesDir>/kdkit_capture.txt` —— 供 `adb pull`
 *     后离线解密（`kit/python/kd_crypto.py`）。宿主进程写自己的目录，不需要任何额外权限。
 *
 * ### 2026-10-25
 *  * 落盘统一走 [Capture]（原来这里自己开一套 file + stamp + rotation，三份重复实现之一）；
 *  * 三条"输出对"（DECRYPT in/out、ENCRYPT in/out）原先共用一个预算计数器 ⇒ 谁先跑谁把预算吃光，
 *    其余永久静默。现在**每类独立预算**，并可由 `sign_observer_pairs` 调整；
 *  * 钩子常驻 + 调用点门控 ⇒ 开关即时生效。
 */
object SignObserver : SwitchFeature(
    id = "sign_observer",
    title = "签名 / 密钥观测",
    summary = "记录请求签名参数、nativeGetKey 的 RC4 密钥、H5 负载加解密（进程内版 kit 钩子）",
    category = Category.MISC,
    defaultOn = false,
    hot = true,
) {
    private const val MAX = 300

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "sign_observer_pairs",
            title = "加解密明密文条数",
            summary = "每类（NET/H5/RC4）最多记录多少对明文-密文，0 = 只记结果不记输入",
            kind = KdOption.Kind.STRING,
            default = "30",
        ),
        KdOption(
            key = "sign_observer_logcat",
            title = "同时写 logcat",
            summary = "关掉则只写抓取文件（降低日志压力，适合长期跑）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    private fun pairsBudget(tag: String): Boolean {
        val n = dev.xalor.kdkit.config.KdConfig.getString("sign_observer_pairs", "30").toIntOrNull() ?: 30
        if (n <= 0) return false
        return RateLimit.firstN("sign.pairs.$tag", n)
    }

    private fun fmt(v: Any?): String = when (v) {
        null -> "null"
        is ByteArray -> "byte[${v.size}] " + android.util.Base64.encodeToString(
            v.copyOf(minOf(v.size, 300)), android.util.Base64.NO_WRAP
        )
        else -> v.toString()
    }

    override fun install() {
        var n = 0
        n += hook("com.baidu.homework.common.net.Net", "appendSign") {
            record("SIGN URL", it.result?.toString())
        }
        n += hook("com.zuoyebang.baseutil.a", "d") { p ->
            record("SIGN params", join(p.args.firstOrNull()))
            record("SIGN result", peek(p.result))
        }
        n += hook("com.zuoyebang.baseutil.a", "b") { p ->
            record("RC4KEY b(${p.args.firstOrNull()})", p.result?.toString())
        }
        n += hook("vm.g", "h") { p ->
            if (pairsBudget("h5dec")) record("H5 DECRYPT in", p.args.firstOrNull()?.toString())
            record("H5 DECRYPT out", p.result?.toString())
        }
        n += hook("vm.g", "i") { p ->
            if (pairsBudget("h5enc")) record("H5 ENCRYPT in", p.args.firstOrNull()?.toString())
            record("H5 ENCRYPT out", p.result?.toString())
        }
        n += hook("vm.g", "z") { p ->
            val key = try {
                XposedHelpers.getObjectField(p.thisObject, "b")
            } catch (t: Throwable) {
                "<field b unreadable: $t>"
            }
            record("RC4KEY refreshed", key?.toString())
        }
        // Whole-response / whole-request crypto (work/TRIAGE.md §3.2):
        //   com.kuaiduizuoye.scan.base.d.decrypt(T)      -> yl.f.j(T)
        //   com.kuaiduizuoye.scan.base.d.encrypt(T,bool) -> yl.f.s(T,bool)
        n += hook("vm.g", "k") { p ->
            if (pairsBudget("netdec")) record("NET DECRYPT in", fmt(p.args.firstOrNull()))
            record("NET DECRYPT out", fmt(p.result))
        }
        n += hook("vm.g", "t") { p ->
            if (pairsBudget("netenc")) record("NET ENCRYPT in", fmt(p.args.firstOrNull()))
            record("NET ENCRYPT out", fmt(p.result))
        }
        // String-level crypto primitives behind yl.f.j / yl.f.s
        for (m in listOf("o", "p", "u", "m")) {
            n += hook("vm.g", m) { p ->
                if (pairsBudget("prim")) record("H5 $m in", fmt(p.args.firstOrNull()))
                record("H5 $m out", fmt(p.result))
            }
        }
        // 地面真值：所有 RC4 负载加解密都走这一个类
        for (m in listOf("encrypt", "decrypt")) {
            n += hookBytes("com.baidu.android.common.security.RC4", m)
        }
        KdLog.i("SignObserver installed ($n hooks, capture via Capture)")
    }

    private fun hook(className: String, methodName: String, line: (XC_MethodHook.MethodHookParam) -> Unit): Int =
        Xp.hookAll(className, methodName, Xp.classLoader, object : XC_MethodHook() {
            override fun afterHookedMethod(param: MethodHookParam) {
                if (!dev.xalor.kdkit.config.KdConfig.isOn(id, false)) return
                try {
                    line(param)
                } catch (t: Throwable) {
                    KdLog.w("SignObserver failed on $className.$methodName: $t")
                }
            }
        })

    /** [hook] for byte[] crypto primitives: also prints the instance's working key. */
    private fun hookBytes(className: String, methodName: String): Int =
        Xp.hookAll(className, methodName, Xp.classLoader, object : XC_MethodHook() {
            override fun afterHookedMethod(param: MethodHookParam) {
                if (!dev.xalor.kdkit.config.KdConfig.isOn(id, false)) return
                if (!pairsBudget("rc4.$methodName")) return
                try {
                    val key = try {
                        XposedHelpers.getObjectField(param.thisObject, "workingKey")
                    } catch (t: Throwable) {
                        null
                    }
                    record(
                        "RC4 $methodName key=${b64(key)} in=${b64(param.args.firstOrNull())}",
                        b64(param.result),
                    )
                } catch (t: Throwable) {
                    KdLog.w("SignObserver byte-hook failed on $className.$methodName: $t")
                }
            }
        })

    private fun b64(v: Any?): String = when (v) {
        null -> "null"
        is ByteArray -> "b64[${v.size}]" + android.util.Base64.encodeToString(v, android.util.Base64.NO_WRAP)
        else -> v.toString()
    }

    /** 一行进抓取文件（共享通道，含轮转与限长）。 */
    private fun record(tag: String, value: String?) {
        val full = value ?: return
        if (dev.xalor.kdkit.config.KdConfig.isOn("sign_observer_logcat", true)) {
            KdLog.i("$tag: ${peek(full)}")
        }
        Capture.append("$tag: $full")
    }

    private fun join(v: Any?): String = when (v) {
        is Iterable<*> -> v.joinToString(" | ") { it?.toString() ?: "null" }
        null -> "null"
        else -> v.toString()
    }

    private fun peek(v: Any?): String {
        val s = v?.toString() ?: "null"
        return if (s.length > MAX) s.substring(0, MAX) + " …(${s.length})" else s
    }
}
