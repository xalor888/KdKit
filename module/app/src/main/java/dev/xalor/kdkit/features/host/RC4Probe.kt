package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedHelpers
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.TextHeuristic
import dev.xalor.kdkit.util.Xp

/** 解密观测：记录 `com.baidu.android.common.security.RC4` 的**密钥**与**明文**。（**热开关**）
 *
 *  为什么需要：`/kdcore/submit/homebookv2` 的 `homeRecentList`（30 条书）里，
 *  `name` / `primaryName` / `subName` / `cover` 是**密文**（base64，64 字节），
 *  用"字段加密那套 RC4（RC4KEY b(1811)）"解**不通**（实测非 UTF-8，见 work/UNEXPLAINED.md）。
 *  静态定位（yl/f.smali）显示：真正干活的是 `com.baidu.android.common.security.RC4`
 *  —— 它的构造器**收一个 String 当 key**，且有 `decrypt([B)[B]` / `encrypt([B)[B]`。
 *  ⇒ hook 这两个点：**密钥**与**明文**一次拿全（对所有同类字段都有效）。
 *
 *  2026-10-25 两处修正：
 *  * 明文判定原来只看"有没有 CJK"，于是纯英文/数字的明文（书名、ID、URL）被整类丢掉；
 *    现在改用 [TextHeuristic.looksLikeText]（可打印比例 + UTF-8 可解码），并额外记录"看起来不是文本"
 *    的条数，避免"没记到"被误读成"不存在"。
 *  * 上行/下行都加了每类上限，防止大文件上传把抓取文件写爆。
 */
object RC4Probe : SwitchFeature(
    id = "rc4_probe",
    title = "解密观测",
    summary = "记录 Baidu RC4 的密钥与解密结果（解 homeRecentList 等加密字段）",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val CLS = "com.baidu.android.common.security.RC4"
    private val keys = java.util.Collections.synchronizedSet(HashSet<String>())
    private val nonText = java.util.concurrent.atomic.AtomicInteger()

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "rc4_probe_uplink",
            title = "记录上行明文",
            summary = "把 App 加密前的内容也记下来（体量更大，且含用户输入）",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        if (Xp.clazzOrNull(CLS) == null) {
            KdLog.w("RC4Probe: class not found ($CLS)")
            return
        }
        var n = 0
        // ① 密钥：hook 构造器（setKey 是 private 且只在初始化时调 ⇒ 挂它抓不到）
        // 下面四条都写**字面量**类名：静态门禁按字面量解析，用 `cls.name` 会整块失去校验
        // （2026-10-25 发现 RC4Probe 的 4 个目标此前全都没被任何门禁看过）。
        // 2026-10-26 已核对：把其中一条的类名换成变量后，`check_hook_targets` 看到的
        // RC4 目标从 5 条降到 4 条 —— 确实"整块失去校验"，不是危言耸听。
        // 构造器必须用 findAndHookConstructor —— `findAndHookMethod(类, "<init>", ...)` 在
        // Xposed 里永远返回 false（它按方法名查找，构造器没有名字）。这条是门禁的
        // `UNKNOWN(constructor; use findAndHookConstructor)` 提示出来的。
        if (Xp.hookCtor("com.baidu.android.common.security.RC4", String::class.java, gate = id, onAfter = { p ->
                val k = p.args.firstOrNull() as? String ?: return@hookCtor
                if (keys.add(k)) Capture.append("RC4KEYSTR " + k.take(80) + " | len=" + k.length)
            })
        ) n++
        // ①b 备选：setKey(byte[])
        if (Xp.hook("com.baidu.android.common.security.RC4", "setKey", ByteArray::class.java, gate = id, onAfter = { p ->
                val k = p.args.firstOrNull() as? ByteArray ?: return@hook
                val hex = k.joinToString("") { String.format("%02x", it) }
                if (keys.add(hex)) Capture.append("RC4KEY " + hex + " | len=" + k.size)
            })
        ) n++
        // ② 下行明文
        if (Xp.hook("com.baidu.android.common.security.RC4", "decrypt", ByteArray::class.java, gate = id, onAfter = { p ->
                val out = p.result as? ByteArray ?: return@hook
                emit("RC4PT", out)
            })
        ) n++
        // ③ 上行明文
        if (Xp.hook("com.baidu.android.common.security.RC4", "encrypt", ByteArray::class.java, gate = id, onBefore = { p ->
                if (!KdConfig.isOn("rc4_probe_uplink", true)) return@hook
                val inp = p.args.firstOrNull() as? ByteArray ?: return@hook
                emit("RC4UP", inp)
            })
        ) n++
        KdLog.i("RC4Probe installed (hooks=$n, keys=${keys.size})")
    }

    private fun emit(tag: String, bytes: ByteArray) {
        if (bytes.isEmpty()) return
        val text = TextHeuristic.decode(bytes)
        if (text == null) {
            // 不是文本 ⇒ 记一次计数（前 20 条），这样"某字段解不出来"是可查的，而不是静默消失
            val k = nonText.incrementAndGet()
            if (RateLimit.firstN("rc4.nontext", 20)) {
                Capture.append("$tag(nontext) len=${bytes.size} b64=" +
                    android.util.Base64.encodeToString(bytes.copyOf(minOf(bytes.size, 64)), android.util.Base64.NO_WRAP))
            }
            return
        }
        if (!RateLimit.firstN("rc4.$tag", 2_000)) return
        Capture.append("$tag " + text.take(120).replace("\n", " "))
    }
}
