package dev.xalor.kdkit.features.host

import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.GatePolicy
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * 反检测：既中和宿主自带的 Java 反调试看门狗，也把**环境探测面**（包名 / 文件 / `su` /
 * Xposed 类 / `/proc/self/maps`）按"干净设备"回答。
 *
 * ### 一、宿主自带看门狗（原有，未改语义）
 *
 * `AntiDebugThread`（`dj.f.b(Context)` 里 new 出来的线程，每 800 ms 轮询一次）会做两个判断，
 * 任一为真就 `System.exit(0)`：
 *
 *   1. `android.os.Debug.isDebuggerConnected()`
 *   2. `dj.f.d()` —— 读 `/proc/<pid>/status`，`TracerPid != 0` 就认为被调试/被注入
 *
 * 另：`dj.f.b()` 入口还有一次 `dj.f.c(ctx)`（`ApplicationInfo.flags & FLAG_DEBUGGABLE`）。
 * 该功能把这三个判断按"干净"返回，轮询线程因此永不触发退出——Frida / 调试器可以正常附加。
 *
 * ### 二、环境探测面（2026-11-14 新增）
 *
 * 宿主里跑着两套第三方风控 SDK，它们不看调试器，而是查"这台设备上装了/加载了什么"：
 *
 * | SDK | 类 | 探测 |
 * |---|---|---|
 * | 快手 Weapon | `com.kuaishou.weapon.p0.an` | `ClassLoader.loadClass("de.robv.android.xposed.XposedBridge")`、`XposedBridge.jar`、包名集合 |
 * | 快手 Weapon | `com.kuaishou.weapon.p0.ac` / `z` | `FileReader("/proc/self/maps")` + `BufferedReader.readLine()` 扫映射 |
 * | 快手 Weapon | `com.kuaishou.weapon.p0.aj` / `af` | `System.getenv("PATH")`、`su`、`su -v`、`/sbin/.magisk`、`/proc/<pid>/mounts` |
 * | 快手 Weapon | `com.kuaishou.weapon.p0.ak` | `data/dalvik-cache/xposed_*.dex` |
 * | KSAd | `com.kwad.sdk.utils.s$e$1/2` | `getPackageInfo("de.robv.android.xposed.installer")`、栈帧里的 `XposedBridge.main` |
 * | 百度 MobAds | `...mobads...DeviceUtils` | `/sbin/.magisk`、`/data/adb/magisk` |
 *
 * 因此这里在**框架层**（`java.io.File` / `java.lang.Runtime` / `java.lang.Class` /
 * `PackageManager` 实现类 / `BufferedReader`）统一回答干净结果，而不是逐个去钩混淆过的
 * SDK 内部方法——后者一换版本就静默失效，且每个 SDK 都有一套。
 *
 * 每一条都满足四条约束：
 *  1. **静态可解析的钩点**（框架类，`cl = null`；由 `kit/scripts/check_hook_targets.py`
 *     判为 `OK(platform)`）；
 *  2. `gate = id` —— 开关关掉时回调不执行，原方法照跑（热开关，不必重启宿主）；
 *  3. **白名单**：只对"模块/框架/su 探测"命中的输入返回假值，其余一律透传；
 *  4. **失败不影响宿主**：装钩子与回调体都有兜底，异常只降级为日志（[warn] 限流）。
 *
 * 覆盖面还可以按向量关掉（`anti_detect_vectors`，见 [options]）——排查"是不是我这条
 * 过滤把宿主弄坏了"时，不必整体关功能。
 */
object AntiDetect : SwitchFeature(
    id = "anti_detect",
    title = "反调试检测绕过",
    summary = "让宿主自带的 AntiDebugThread 判定为干净，并过滤包名/文件/su 探测/Xposed 类/maps 五类环境探测",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    /** 非 boolean 只告警一次，避免每次调用都刷日志。 */
    private val nonBooleanWarned = AtomicBoolean(false)

    // ── 覆盖面（子选项）───────────────────────────────────────────────
    private const val VECTOR_KEY = "anti_detect_vectors"
    private const val VECTOR_DEFAULT = "pkg,file,exec,class,maps"

    override val options: List<KdOption> = listOf(
        KdOption(
            key = VECTOR_KEY,
            title = "反检测覆盖面",
            summary = "逗号分隔：pkg 包名 / file 文件 / exec su 探测 / class Xposed 类 / maps 进程映射；" +
                "all=全开，留空=只保留反调试（用来二分定位「哪条过滤影响了宿主」）",
            kind = KdOption.Kind.STRING,
            default = VECTOR_DEFAULT,
        ),
    )

    @Volatile private var vectorSrc: String? = null
    @Volatile private var vectorSet: Set<String> = emptySet()

    /**
     * 某个向量是否开启。
     *
     * 热路径（`File.exists` 每个进程上万次）上只做**一次字符串比较 + 一次 set 查找**：
     * 配置串没变就不重新切分。`KdConfig.getString` 自带 TTL 缓存，切开关 2 秒内生效。
     */
    private fun vectorOn(name: String): Boolean {
        val raw = KdConfig.getString(VECTOR_KEY, VECTOR_DEFAULT)
        if (raw != vectorSrc) {
            vectorSet = raw.split(',', ';', ' ', '|')
                .map { it.trim().lowercase() }
                .filter { it.isNotEmpty() }
                .toSet()
            vectorSrc = raw
        }
        return name in vectorSet || "all" in vectorSet
    }

    override fun install() {
        var n = 0
        // **`gate = id` 必须传**（2026-11-04 修，代码审查 P2-13 / 目标里的"关不掉的功能"）。
        //
        // 这个功能是 `hot = true`，而 `BaseFeature.enable()` 的判据是
        // `if (!hot && !shouldRun()) return` —— **hot 直接绕过配置检查**，
        // 于是它无论如何都会装钩子。对"读侧"功能这没问题（回调里判 isOn 就行），
        // 但这个功能的钩子是**写侧**：它们把 `isDebuggerConnected()`、
        // `TracerPid`、`FLAG_DEBUGGABLE` 统统改成 false ——
        // **用户把 `antidetect` 关掉之后，它照样在骗 App。**
        //
        // 症状：UI 上开关是关的，App 侧行为完全不变。这一类缺陷不会报错，
        // 只会让人觉得"这个开关没用"。
        // 1) android.os.Debug.isDebuggerConnected() -> false （boot 类，用 boot ClassLoader）
        if (Xp.hook("android.os.Debug", "isDebuggerConnected", cl = null, gate = id, onBefore = {
            it.result = false
            note("Debug.isDebuggerConnected")
        })) n++

        // 2) lk.f.d() -> false：TracerPid 解析
        if (Xp.hook("dj.f", "d", cl = Xp.classLoader, gate = id, onBefore = {
            it.result = false
            note("lk.f.d (TracerPid)")
        })) n++

        // 3) 同义的 synthetic bridge（不同 ROM/构建可能走这条）
        //
        // **只在目标是 boolean 时**才置 false：`hookAll` 钩的是同名**全部重载**，
        // 一旦某个重载返回别的类型，写 false 会让调用方拿到一个 `Boolean.FALSE`
        // 而不是它期望的类型 —— 与"只改判定、不动其它逻辑"的自述冲突（审查 P2-11）。
        // 现状（7.9.0）：`dj.f.a()` 只有一个重载且返回 `Z`，见 check_hook_result_types.py。
        val bridge = Xp.hookAll("dj.f", "a", cl = Xp.classLoader, cb = object : XC_MethodHook() {
            override fun beforeHookedMethod(param: MethodHookParam) {
                // `hookAll` 没有 gate 形参 ⇒ 回调里自己判（与上面三个 hook 的语义一致）。
                if (!KdConfig.isOn(id, GatePolicy.defaultFor(id))) return
                if (!Xp.returnsBoolean(param)) {
                    if (nonBooleanWarned.compareAndSet(false, true)) {
                        KdLog.w("AntiDetect: dj.f.a 现在返回非 boolean ⇒ 跳过不改（否则会污染调用方）")
                    }
                    return
                }
                param.result = false
                note("lk.f.a bridge")
            }
        })

        // 4) 可调试标志判定（release 包恒为 false，留着防御性兜底）
        if (Xp.hook("dj.f", "c", android.content.Context::class.java, cl = Xp.classLoader, gate = id, onBefore = {
            it.result = false
            note("lk.f.c (FLAG_DEBUGGABLE)")
        })) n++

        // 5) 环境探测面（五类向量，逐类独立安装）
        n += installProbes()

        KdLog.i("AntiDetect installed ($n direct hooks + $bridge bridge)")
        // 6) 装机自检：等宿主起来后，用**宿主自己的 API**问一遍环境，
        //    把每条过滤的"过滤后结果"写一行 —— 这是"钩子真的生效"的进程内证据。
        //    对照面（包到底装没装、/data/adb 在不在）由 `adb shell` 另行取证。
        scheduleSelfCheck()
    }

    // ── 五类环境探测 ──────────────────────────────────────────────────

    /**
     * 逐向量安装。**每一类都在自己的 `safe()` 里**：一类装不上（框架类被厂商改签名、
     * 某个 loader 不让钩）不该拖累另外四类，更不该让 `enable()` 抛出。
     */
    private fun installProbes(): Int {
        var n = 0
        if (vectorOn("pkg")) n += safe("pkg") { installPackageFilters() }
        if (vectorOn("file")) n += safe("file") { installFileFilters() }
        if (vectorOn("exec")) n += safe("exec") { installExecFilters() }
        if (vectorOn("maps")) n += safe("maps") { installMapsFilters() }
        // **类过滤必须最后装**：装完它之后，`de.robv.android.xposed.*` 的解析会被拦。
        // 前面的安装过程（`Xp.hook*`）要反射 `XposedHelpers`/`XC_MethodHook` 等类，
        // 先装就会把自己也拦掉（症状是后面每条钩子都"装不上"且不报原因）。
        if (vectorOn("class")) n += safe("class") { installClassFilters() }
        return n
    }

    private inline fun safe(name: String, block: () -> Int): Int =
        try {
            block()
        } catch (t: Throwable) {
            KdLog.e("AntiDetect: $name 过滤装不上，跳过（宿主行为不变）", t)
            0
        }

    // ── (1) 包名：getInstalledPackages / getInstalledApplications / getPackageInfo ──

    private fun installPackageFilters(): Int {
        var k = 0
        k += Xp.hookAllAfter("android.app.ApplicationPackageManager", "getInstalledPackages", cl = null, gate = id) { p ->
            runCatching { p.result = filterPkgList(p.result, "getInstalledPackages") }
                .onFailure { warn("pkg.list", it) }
        }
        k += Xp.hookAllAfter("android.app.ApplicationPackageManager", "getInstalledApplications", cl = null, gate = id) { p ->
            runCatching { p.result = filterPkgList(p.result, "getInstalledApplications") }
                .onFailure { warn("pkg.apps", it) }
        }
        k += Xp.hookAllBefore("android.app.ApplicationPackageManager", "getPackageInfo", cl = null, gate = id) { p ->
            runCatching { denyPackage(p, "getPackageInfo") }.onFailure { warn("pkg.info", it) }
        }
        k += Xp.hookAllBefore("android.app.ApplicationPackageManager", "getApplicationInfo", cl = null, gate = id) { p ->
            runCatching { denyPackage(p, "getApplicationInfo") }.onFailure { warn("pkg.appinfo", it) }
        }
        return k
    }

    /** 模块自身 + 常见框架/管理器包。**精确名或前缀**，不做子串匹配（子串会误伤正常 App）。 */
    private val PKG_MARKS = arrayOf(
        "de.robv.android.xposed",
        "com.saurik.substrate",
        "org.lsposed",
        "io.github.lsposed",
        "com.elderdrivers.riru",
        "org.meowcat.edxposed",
        "com.topjohnwu.magisk",
        "me.weishu.kernelsu",
        "com.rifsxd.ksunext",
        "me.bmax.apatch",
        "eu.chainfire.supersu",
        "com.koushikdutta.superuser",
        "com.thirdparty.superuser",
    )

    private fun blockedPkg(name: String?): Boolean {
        if (name.isNullOrEmpty()) return false
        if (name.contains("kdkit", ignoreCase = true)) return true
        for (m in PKG_MARKS) if (name == m || name.startsWith("$m.")) return true
        return false
    }

    private fun pkgOf(o: Any?): String? = when (o) {
        is PackageInfo -> o.packageName
        is ApplicationInfo -> o.packageName
        else -> null
    }

    /** 命中则返回**去掉命中项的新列表**；没命中返回原对象（不复制、不改调用方的数据）。 */
    private fun filterPkgList(src: Any?, what: String): Any? {
        val list = src as? List<*> ?: return src
        var hit = false
        for (e in list) if (blockedPkg(pkgOf(e))) { hit = true; break }
        if (!hit) return src
        val out = ArrayList<Any?>(list.size)
        var dropped = 0
        for (e in list) {
            if (blockedPkg(pkgOf(e))) dropped++ else out.add(e)
        }
        fnote("$what -$dropped")
        return out
    }

    /** `getPackageInfo("de.robv...")` 在真机上就是 `NameNotFoundException`，这里保持一致。 */
    private fun denyPackage(p: XC_MethodHook.MethodHookParam, what: String) {
        val name = p.args.firstOrNull() as? String ?: return
        if (!blockedPkg(name)) return
        p.setThrowable(PackageManager.NameNotFoundException(name))
        fnote("$what $name")
    }

    // ── (2) 文件：exists / isFile / isDirectory / list / listFiles ──────────

    private fun installFileFilters(): Int {
        var k = 0
        k += Xp.hookAllBefore("java.io.File", "exists", cl = null, gate = id) { p ->
            runCatching { denyFile(p, "exists") }.onFailure { warn("file.exists", it) }
        }
        k += Xp.hookAllBefore("java.io.File", "isFile", cl = null, gate = id) { p ->
            runCatching { denyFile(p, "isFile") }.onFailure { warn("file.isfile", it) }
        }
        k += Xp.hookAllBefore("java.io.File", "isDirectory", cl = null, gate = id) { p ->
            runCatching { denyFile(p, "isDirectory") }.onFailure { warn("file.isdir", it) }
        }
        k += Xp.hookAllAfter("java.io.File", "list", cl = null, gate = id) { p ->
            runCatching {
                val dir = p.thisObject as? File ?: return@runCatching
                val got = p.result as? Array<*> ?: return@runCatching
                if (blockedPath(dir.path)) {
                    p.result = emptyArray<String>()
                    fnote("File.list ${dir.path}")
                    return@runCatching
                }
                var hit = false
                for (e in got) if (e is String && blockedPath(e)) { hit = true; break }
                if (!hit) return@runCatching
                val out = ArrayList<String>(got.size)
                for (e in got) if (e is String && !blockedPath(e)) out.add(e)
                p.result = out.toTypedArray()
                fnote("File.list ${dir.path} -${got.size - out.size}")
            }.onFailure { warn("file.list", it) }
        }
        k += Xp.hookAllAfter("java.io.File", "listFiles", cl = null, gate = id) { p ->
            runCatching {
                val dir = p.thisObject as? File ?: return@runCatching
                val got = p.result as? Array<*> ?: return@runCatching
                if (blockedPath(dir.path)) {
                    p.result = emptyArray<File>()
                    fnote("File.listFiles ${dir.path}")
                    return@runCatching
                }
                var hit = false
                for (e in got) if (e is File && blockedPath(e.path)) { hit = true; break }
                if (!hit) return@runCatching
                val out = ArrayList<File>(got.size)
                for (e in got) if (e is File && !blockedPath(e.path)) out.add(e)
                p.result = out.toTypedArray()
                fnote("File.listFiles ${dir.path} -${got.size - out.size}")
            }.onFailure { warn("file.listFiles", it) }
        }
        return k
    }

    /** `File.exists/isFile/isDirectory` 命中敏感路径 ⇒ 按"不存在"回答。 */
    private fun denyFile(p: XC_MethodHook.MethodHookParam, what: String) {
        val f = p.thisObject as? File ?: return
        if (!blockedPath(f.path)) return
        p.result = false
        fnote("File.$what ${f.path}")
    }

    /**
     * 路径标记。**全部忽略大小写比较**（宿主里 `XposedBridge.jar` 与 `xposed` 两种写法都有）。
     *
     * `/data/adb` 是 Magisk / KernelSU / APatch 的公共根，比逐个列 `magisk` 目录更稳。
     */
    private val PATH_MARKS = arrayOf(
        "kdkit",
        "xposed",
        "de.robv",
        "magisk",
        "/data/adb",
        "frida",
        "substrate",
        "lsposed",
        "riru",
        "edxp",
        "zygisk",
        "apatch",
    )

    private fun blockedPath(p: String): Boolean {
        for (m in PATH_MARKS) if (p.contains(m, ignoreCase = true)) return true
        return false
    }

    // ── (3) su 探测：Runtime.exec / ProcessBuilder.start ──────────────────

    /**
     * 假的 `Process`：`exitValue()/waitFor() = 1`（非 0 = "没 root"），三个流都是空的。
     *
     * 为什么返回假进程而不是抛异常：探测代码通常写成
     * `try { p = exec("su"); p.waitFor(); ... } catch (IOException ignored) {}`，
     * 抛异常也会被吞；但**不写 try 的调用方**（少数）会因此崩掉。
     * 返回非 0 退出码在两种写法下都等价于"没有 root"，且不会把异常漏到宿主栈上。
     */
    private class ProbeProcess : Process() {
        private fun empty(): java.io.InputStream = java.io.ByteArrayInputStream(ByteArray(0))
        override fun getOutputStream(): java.io.OutputStream = java.io.ByteArrayOutputStream(0)
        override fun getInputStream(): java.io.InputStream = empty()
        override fun getErrorStream(): java.io.InputStream = empty()
        override fun waitFor(): Int = 1
        override fun exitValue(): Int = 1
        override fun isAlive(): Boolean = false
        override fun destroy() {}
    }

    private fun installExecFilters(): Int {
        var k = 0
        k += Xp.hookAllBefore("java.lang.Runtime", "exec", cl = null, gate = id) { p ->
            runCatching {
                val cmd = commandOf(p.args.firstOrNull()) ?: return@runCatching
                if (!isRootProbe(cmd)) return@runCatching
                p.result = ProbeProcess()
                fnote("Runtime.exec(${cmd.take(40)})")
            }.onFailure { warn("exec.runtime", it) }
        }
        k += Xp.hookAllBefore("java.lang.ProcessBuilder", "start", cl = null, gate = id) { p ->
            runCatching {
                val pb = p.thisObject as? ProcessBuilder ?: return@runCatching
                val cmd = pb.command().joinToString(" ")
                if (!isRootProbe(cmd)) return@runCatching
                p.result = ProbeProcess()
                fnote("ProcessBuilder.start(${cmd.take(40)})")
            }.onFailure { warn("exec.pb", it) }
        }
        return k
    }

    private fun commandOf(arg: Any?): String? = when (arg) {
        is String -> arg
        is Array<*> -> arg.joinToString(" ") { it?.toString() ?: "" }
        else -> null
    }

    /**
     * 只认**明确是 root 探测**的命令形态（白名单），其余一律放行：
     *
     *  * 首 token 的 basename ∈ {su, magisk, ksud, supersu, daemonsu}（`/system/xbin/su -c id` 命中）；
     *  * 首 token 是 `which` / `type` / `command -v` 且参数是 `su`；
     *  * 含 `su -c` / `su -v` / `su --version`（宿主自己的 `sh -c`、`getprop`、`logcat` 不碰）。
     */
    private fun isRootProbe(cmd: String): Boolean {
        val c = cmd.trim()
        if (c.isEmpty()) return false
        val head = c.substringBefore(' ').substringBefore('\t').substringAfterLast('/').lowercase()
        if (head == "su" || head == "magisk" || head == "ksud" || head == "supersu" || head == "daemonsu") {
            return true
        }
        val low = c.lowercase()
        return low.startsWith("which su") || low.startsWith("command -v su") ||
            low.startsWith("type su") || low.contains("su -c") ||
            low.contains("su -v") || low.contains("su --version")
    }

    // ── (4) Xposed 类：Class.forName / ClassLoader.loadClass ─────────────

    /**
     * 模块自己要用、且**必须在过滤器安装之前**解析好的框架类。
     *
     * 否则（LSPosed 里模块的 ClassLoader 以宿主 loader 为 parent）：装完过滤器后模块自己
     * 去解析 `XposedHelpers` 会被同一条规则拦掉 —— 症状是后面每条钩子静默失败。
     */
    private val SELF_CLASSES = arrayOf(
        "de.robv.android.xposed.XposedBridge",
        "de.robv.android.xposed.XposedHelpers",
        "de.robv.android.xposed.XC_MethodHook",
        "de.robv.android.xposed.XC_MethodReplacement",
    )

    /** 模块自己的 ClassLoader：它对 `de.robv.*` 的解析一律放行（见 [SELF_CLASSES]）。 */
    private val selfLoader: ClassLoader? = AntiDetect::class.java.classLoader

    private fun installClassFilters(): Int {
        for (c in SELF_CLASSES) runCatching { Class.forName(c) }
        var k = 0
        // **`Class.forName` 不在启动路径上直接装**：本宿主带 DProtect 加固，
        // `InitializationProvider` 安装期间它会重新用反射调用 `Class.forName`，
        // 而那次重入拿不到 caller ClassLoader ⇒ 连 `androidx.emoji2...` 都 CNFE ⇒ 启动崩溃
        // （2026-11-14 实测：只装 forName 必崩、只装 loadClass 正常；见 `work/anti_detect_audit.md` §验证）。
        // 因此延后 15 秒（启动完成之后）再装；代价是启动窗口内的探测拦不到。
        runCatching {
            android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                runCatching {
                    Xp.under(id) {
                        Xp.hookAllBefore("java.lang.Class", "forName", cl = null, gate = id) { p ->
                            runCatching { denyClass(p, "Class.forName", false) }.onFailure { warn("class.forname", it) }
                        }
                    }
                    KdLog.i("AntiDetect: Class.forName 过滤已延后装上（避开加固的启动自检）")
                }.onFailure { warn("class.forname.late", it) }
            }, 15_000)
        }.onFailure { warn("class.forname.post", it) }
        k += Xp.hookAllBefore("java.lang.ClassLoader", "loadClass", cl = null, gate = id) { p ->
            runCatching { denyClass(p, "ClassLoader.loadClass", true) }.onFailure { warn("class.load", it) }
        }
        return k
    }

    /**
     * 命中框架类名 ⇒ 按真机语义抛 `ClassNotFoundException`。
     *
     * `loadClass` 额外做两件事（比 `forName` 多一层顾忌）：
     *  1. 请求方是**模块自己的 loader** 就放行 —— 否则模块自己的类解析会被自己拦掉；
     *  2. 只拦"宿主 loader（= 进程的 system ClassLoader）"发起的解析：
     *     风控 SDK 用的正是 `ClassLoader.getSystemClassLoader().loadClass(...)`。
     */
    private fun denyClass(p: XC_MethodHook.MethodHookParam, what: String, isLoadClass: Boolean) {
        val name = p.args.firstOrNull() as? String ?: return
        if (!isHookClassName(name)) return
        if (isLoadClass) {
            if (p.thisObject === selfLoader) return
            if (p.thisObject !== Xp.classLoader) return
        } else {
            // `forName(String, boolean, ClassLoader)`：显式指定模块自己的 loader 就放行，
            // 与 loadClass 同一条豁免（三参数重载才看得到 loader）。
            if (p.args.getOrNull(2) === selfLoader) return
        }
        p.setThrowable(ClassNotFoundException(name))
        fnote("$what $name")
    }

    private fun isHookClassName(n: String): Boolean {
        if (n.startsWith("de.robv.android.xposed")) return true
        if (n.startsWith("com.saurik.substrate")) return true
        if (n.startsWith("com.elderdrivers.riru")) return true
        if (n.startsWith("org.lsposed") || n.startsWith("io.github.lsposed")) return true
        if (n.startsWith("org.meowcat.edxposed")) return true
        return n.contains("XposedBridge") || n.contains("XposedHelpers")
    }

    // ── (5) /proc/self/maps 行过滤（只过滤读，不动进程）────────────────────

    /** 当前线程是否正处在"读 /proc/self/maps 族"的窗口里。 */
    private val mapsWindow = ThreadLocal<Boolean>()

    /** 跳过循环的重入深度（避免 after 钩子里再调原方法时无限递归）。 */
    private val skipDepth = ThreadLocal<Int>()

    private fun installMapsFilters(): Int {
        var k = 0
        // 窗口起点：真机上两条 SDK 路径都是 FileReader(String) / FileInputStream(File) 起手
        // （`com/kuaishou/weapon/p0/z`: FileReader("/proc/self/maps")；`.../ac`: FileInputStream）。
        k += Xp.hookCtor("java.io.FileReader", String::class.java, cl = null, gate = id, onBefore = { p ->
            runCatching { markMaps(p) }.onFailure { warn("maps.reader", it) }
        }).let { if (it) 1 else 0 }
        k += Xp.hookCtor("java.io.FileReader", File::class.java, cl = null, gate = id, onBefore = { p ->
            runCatching { markMaps(p) }.onFailure { warn("maps.reader.f", it) }
        }).let { if (it) 1 else 0 }
        k += Xp.hookCtor("java.io.FileInputStream", String::class.java, cl = null, gate = id, onBefore = { p ->
            runCatching { markMaps(p) }.onFailure { warn("maps.stream", it) }
        }).let { if (it) 1 else 0 }
        k += Xp.hookCtor("java.io.FileInputStream", File::class.java, cl = null, gate = id, onBefore = { p ->
            runCatching { markMaps(p) }.onFailure { warn("maps.stream.f", it) }
        }).let { if (it) 1 else 0 }
        k += Xp.hookAllAfter("java.io.BufferedReader", "readLine", cl = null, gate = id) { p ->
            runCatching { filterMapsLine(p) }.onFailure { warn("maps.line", it) }
        }
        return k
    }

    private fun markMaps(p: XC_MethodHook.MethodHookParam) {
        val path = when (val a = p.args.firstOrNull()) {
            is String -> a
            is File -> a.path
            else -> return
        }
        if (path.contains("/proc/") && path.contains("maps")) mapsWindow.set(true)
    }

    /**
     * 丢掉命中的行 —— 做法是**继续读下一行**，而不是把行改成空串（空串会被"逐行解析"的
     * 代码当成一条合法但字段为空的映射记录）。
     *
     * 读完（`readLine()` 返回 null）就把窗口关掉：maps 只读一次，窗口随之结束，
     * 之后同一线程上任何读文件都不再被扫描。
     */
    private fun filterMapsLine(p: XC_MethodHook.MethodHookParam) {
        if (mapsWindow.get() != true) return
        val line = p.result as? String
        if (line == null) {
            mapsWindow.set(false) // EOF：窗口结束
            return
        }
        if (!blockedPath(line)) return
        if ((skipDepth.get() ?: 0) > 0) return // 重入：这一次是我们自己发起的读
        val m = p.method as? java.lang.reflect.Method ?: return
        var cur: String? = line
        var dropped = 0
        while (cur != null && blockedPath(cur) && dropped < 64) {
            skipDepth.set(1)
            cur = try {
                m.invoke(p.thisObject) as? String
            } finally {
                skipDepth.set(0)
            }
            dropped++
        }
        p.result = cur
        fnote("maps dropped $dropped line(s)")
    }

    // ── 装机自检：把"过滤后的回答"写一行 ────────────────────────────────

    /**
     * 6 秒后跑一次（等 `Application.onCreate` 与包管理器就绪）。
     *
     * 自检**走的是宿主自己的 API**（`PackageManager.getInstalledPackages`、`File.exists`、
     * `Runtime.exec`、`Class.forName`），因此它测的是"钩子是否真的改变了下游结果"，
     * 而不是"我有没有装上钩子"。同一份环境用 `adb shell` 另取一次真值，
     * 两边的差值就是这份过滤的净效果。
     */
    private fun scheduleSelfCheck() {
        runCatching {
            val h = android.os.Handler(android.os.Looper.getMainLooper())
            // 两次：t+6s（`Class.forName` 过滤还**没**装，作为基线）与 t+25s（装完之后）。
            // 两行差异就是"延时装上的 forName 过滤真的改变了结果"的证据。
            h.postDelayed({
                runCatching { selfCheck("t+6s") }.onFailure { warn("selfcheck.run", it) }
            }, 6_000)
            h.postDelayed({
                runCatching { selfCheck("t+25s") }.onFailure { warn("selfcheck.run2", it) }
            }, 25_000)
        }.onFailure { warn("selfcheck.post", it) }
    }

    private fun selfCheck(whenTag: String) {
        val ctx = android.app.AndroidAppHelper.currentApplication() ?: run {
            KdLog.w("AntiDetect selfcheck: 还拿不到 Application，跳过")
            return
        }
        val pm = ctx.packageManager
        val pkgs = runCatching { pm.getInstalledPackages(0) }.getOrNull()
        val seesModule = pkgs?.any { it.packageName == KdConfig.MODULE_PKG }
        val seesFramework = pkgs?.any { it.packageName.startsWith("de.robv.android.xposed") || it.packageName.startsWith("org.lsposed") }
        val adbDir = runCatching { File("/data/adb").exists() }.getOrDefault(false)
        val kdkitUnderDataApp = runCatching { File("/data/app").list()?.any { it.contains("kdkit") } }.getOrDefault(false)
        val suExit = runCatching { Runtime.getRuntime().exec("su").waitFor() }.getOrDefault(-999)
        val forNameOk = runCatching { Class.forName("de.robv.android.xposed.XposedBridge"); true }.getOrDefault(false)
        KdLog.i(
            "AntiDetect selfcheck[$whenTag]: pkgs=${pkgs?.size} seesModule=$seesModule seesFramework=$seesFramework " +
                "/data/adb=$adbDir /data/app~kdkit=$kdkitUnderDataApp exec(su).exit=$suExit forName(XposedBridge)=$forNameOk",
        )
    }

    // ── 日志：命中不刷屏 ────────────────────────────────────────────────

    private fun warn(where: String, t: Throwable) {
        if (RateLimit.every("antidetect.warn.$where", 60_000)) KdLog.w("AntiDetect: $where 过滤异常（已降级）：$t")
    }

    /**
     * 过滤类命中：前 [MAX_FILTER_LOG] 条逐条记（证明每条过滤都真的生效过），
     * 之后每 5 分钟一条心跳（证明它**持续**在工作，而不是只在启动时生效过一次）。
     */
    private fun fnote(what: String) {
        val k = filterHits.incrementAndGet()
        if (k <= MAX_FILTER_LOG) {
            KdLog.i("AntiDetect: filtered $what (#$k)")
            return
        }
        if (RateLimit.every("antidetect.filter.heartbeat", 300_000)) {
            KdLog.i("AntiDetect: filter heartbeat #$k ($what)")
        }
    }

    private val filterHits = AtomicInteger(0)
    private val MAX_FILTER_LOG = 8

    /**
     * 看门狗每 800ms 轮询一次、每次都问同一批判定点 ⇒ 日志量是"时间 × 4"。
     * 旧实现每条都写一行（一天下来几十万行）。现在：前 6 条逐条记（证明四个判定点都被中和），
     * 之后每 5 分钟一条心跳（证明它**持续**在工作，而不是只在启动时生效过一次）。
     */
    private fun note(what: String) {
        val k = hits.incrementAndGet()
        if (k <= MAX_LOG) {
            KdLog.i("AntiDetect: neutralised $what (#$k)")
            return
        }
        if (RateLimit.every("antidetect.heartbeat", 300_000)) {
            KdLog.i("AntiDetect: heartbeat #$k (still neutralising $what)")
        }
    }

    private val hits = AtomicInteger(0)
    private val MAX_LOG = 6

}
