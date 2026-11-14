package dev.xalor.kdkit.config

import android.content.Context
import android.content.SharedPreferences
import de.robv.android.xposed.XSharedPreferences
import de.robv.android.xposed.XposedBridge
import android.system.Os
import java.io.File

/**
 * Framework-side config plumbing. Loaded only on the framework's module ClassLoader, so using
 * `de.robv.android.xposed.*` here is safe.
 *
 * 1. In the hooked host process: make [KdConfig] read the framework-published prefs file.
 * 2. In the module's own app process: mirror the app's SharedPreferences into that published
 *    file, because the app cannot reach the daemon-owned publish path on its own and the host
 *    cannot read the app's private directory (per-app mount namespaces).
 */
object KdConfigBridge {

    private const val TAG = "KdKit"

    /** Where the publisher leaves its status note for the settings UI (same process, app dir). */
    @Volatile private var statusFile: File? = null

    /**
     * The settings app's live pref store. Strings must come from here: the *published* target is a
     * different file (the framework's per-app mount maps it elsewhere), and it only carries what we
     * wrote — reading it back for the source data would always come up empty (found 2026-10-11:
     * a UI-saved blacklist reached the app's store but never the host).
     */
    @Volatile private var publishPrefs: SharedPreferences? = null

    /**
     * The settings UI cannot reach the framework-owned publish path (and must not touch Xposed
     * classes), and the two sides may hold *different* SharedPreferences instances for the same
     * file — so a change listener is not a reliable channel between them. The UI therefore drops
     * a request file in the app's own files dir and the watchdog here picks it up.
     */
    @Volatile private var repairRequest: File? = null

    /** Reader installed inside the hooked host process. */
    fun installHostReader() {
        val prefs = try {
            XSharedPreferences(KdConfig.MODULE_PKG, KdConfig.PREFS_NAME).also {
                it.reload()
                XposedBridge.log("[KdKit] xprefs published=${it.file?.absolutePath} all=${it.all}")
            }
        } catch (t: Throwable) {
            XposedBridge.log("[KdKit] XSharedPreferences unavailable: $t")
            null
        } ?: return

        KdConfig.hostReader = { id ->
            try {
                prefs.reload()
                if (prefs.contains(id)) prefs.getBoolean(id, true) else null
            } catch (t: Throwable) { null }
        }
        KdConfig.hostStringReader = { id ->
            try {
                prefs.reload()
                prefs.getString(id, null)
            } catch (t: Throwable) { null }
        }
    }

    /**
     * Called from the module's own app process (the framework injects the module there too).
     * Mirrors the app's prefs into the framework-published file on every change.
     */
    fun startPublisher() {
        val app = try {
            android.app.AndroidAppHelper.currentApplication() as? Context
        } catch (t: Throwable) {
            null
        }
        if (app == null) {
            XposedBridge.log("[KdKit] publisher: no application context yet")
            return
        }
        val publish = try {
            XSharedPreferences(KdConfig.MODULE_PKG, KdConfig.PREFS_NAME).file
        } catch (t: Throwable) {
            XposedBridge.log("[KdKit] publisher: cannot resolve publish path: $t")
            return
        } ?: return

        val prefs = app.getSharedPreferences(KdConfig.PREFS_NAME, Context.MODE_PRIVATE)
        publishPrefs = prefs
        val file = File(File(app.dataDir, "shared_prefs"), "${KdConfig.PREFS_NAME}.xml")
        XposedBridge.log(
            "[KdKit] publisher: ctx=${app.packageName} dataDir=${app.dataDir} " +
                "prefsFile=${file.exists()} (${file.length()} B) map=${prefs.all.size}"
        )
        XposedBridge.log("[KdKit] publisher path = ${publish.absolutePath}")

        // If the in-memory map is empty but the file on disk is not, the process is reading a
        // different pref store than the one the UI wrote (seen on 2026-10-11: "published 0
        // flag(s)"). Parsing the file directly keeps the channel working either way.
        var snapshot: Map<String, Boolean> = prefs.all
            .mapNotNull { (k, v) -> if (k.startsWith("_")) null else (v as? Boolean)?.let { k to it } }
            .toMap()
        if (snapshot.isEmpty()) {
            val fromDisk = readBooleanPrefs(file)
            if (fromDisk.isNotEmpty()) {
                XposedBridge.log("[KdKit] publisher: in-memory map empty, using ${fromDisk.size} flag(s) from ${file.absolutePath}")
                snapshot = fromDisk
            }
        }
        statusFile = File(app.filesDir, "kdkit_status.txt")
        repairRequest = File(app.filesDir, "kdkit_repair.request")
        publish(snapshot, publish)
        startModeRepairWatchdog(publish, snapshot)
        // **必须用强引用持有监听器**。
        //
        // `SharedPreferences` 对监听器只存**弱引用**（Android 官方文档明写）。写法
        // `registerOnSharedPreferenceChangeListener { … }` 传的是一个**匿名 lambda 实例**，
        // 除了 SharedPreferences 自己那份弱引用之外，没有任何地方强引用它 ⇒
        // 一次 GC 之后它就没了，配置变更**不再被发布**，而设置页 UI 看上去一切正常
        // （2026-11-02 代码审查 D3）。
        //
        // `startModeRepairWatchdog` 只修文件权限，补不了"监听器已被回收"这一半。
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { p, changed ->
            changeListenerFires++
            publishPrefs = p
            val flags = p.all
                .mapNotNull { (k, v) -> if (k.startsWith("_")) null else (v as? Boolean)?.let { k to it } }
                .toMap()
            if (changed != null && changed.startsWith("_")) {
                XposedBridge.log("[KdKit] publisher: request '$changed' -> republish")
            }
            publish(flags, publish)
        }
        changeListener = listener                  // ← 强引用，别删
        prefs.registerOnSharedPreferenceChangeListener(listener)
        XposedBridge.log("[KdKit] publisher: change listener registered (strong ref held)")
    }

    /**
     * The settings app's own SharedPreferences rewrite the file through AtomicFile, which
     * re-creates it with mode 0660 — unreadable for the host (a different uid), which then
     * silently parses an empty map and every feature falls back to its default. The change
     * listener alone is not enough (it can fire before that final rename), so a cheap watchdog
     * re-applies 0644 whenever the mode drifts.
     */
    /**
     * 强引用持有上面注册的监听器。**这个字段存在的唯一理由**就是防止它被 GC ——
     * 删掉它代码照样编译、照样"看起来能跑"，只是某次 GC 之后配置就不再同步了。
     */
    @Volatile
    private var changeListener: SharedPreferences.OnSharedPreferenceChangeListener? = null

    /** 监听器累计触发次数（诊断：0 说明它从来没工作过，或者已经被回收）。 */
    @Volatile
    private var changeListenerFires: Int = 0

    /** 诊断：监听器当前是否仍然被强引用持有。 */
    fun listenerAlive(): Boolean = changeListener != null

    fun listenerFireCount(): Int = changeListenerFires

    private fun startModeRepairWatchdog(target: File, initial: Map<String, Boolean>) {
        var lastRequest = repairRequest?.takeIf { it.exists() }?.readText()?.trim() ?: ""
        var flags = initial
        var ticks = 0
        Thread({
            while (true) {
                ticks++
                try {
                    if (target.exists()) {
                        val mode = Os.stat(target.absolutePath).st_mode and 0x1FF
                        if (mode != 0x1A4) {
                            Os.chmod(target.absolutePath, 0x1A4)
                            XposedBridge.log("[KdKit] publisher: repaired mode ${"%o".format(mode)} -> 644")
                        }
                    }
                    val req = repairRequest
                    if (req != null && req.exists()) {
                        val token = req.readText().trim()
                        if (token.isNotEmpty() && token != lastRequest) {
                            lastRequest = token
                            readBooleanPrefs(target).takeIf { it.isNotEmpty() }?.let { flags = it }
                            XposedBridge.log("[KdKit] publisher: republish requested ($token)")
                            publish(flags, target, stringSnapshot(publishPrefs))
                        }
                    }
                    // **对账**：每 ~20 秒比一次"应用里的开关"与"已发布的内容"。
                    //
                    // 为什么必须有它：发布链的主通道是 SharedPreferences 的变更监听器，
                    // 而它对监听器只存**弱引用** —— 被 GC 之后，"改了开关但没发布"就再也没人管
                    // （R11 已用强引用修掉主因，但那是"不该死"；这里补的是"死了也能自愈"）。
                    // 原来的看门狗只在 `kdkit_repair.request` 变化时重发，覆盖不到这条路径
                    // （2026-11-02 审查 P2-7 的后半句）。
                    if (ticks % 10 == 0 && publishPrefs != null) {
                        val live = publishPrefs!!.all
                            .mapNotNull { (k, v) -> if (k.startsWith("_")) null else (v as? Boolean)?.let { k to it } }
                            .toMap()
                        if (live.isNotEmpty() && live != flags) {
                            flags = live
                            publish(flags, target, stringSnapshot(publishPrefs))
                            XposedBridge.log(
                                "[KdKit] publisher: 对账发现 ${live.size} 个开关与已发布内容不同，已重发",
                            )
                        }
                    }
                } catch (_: Throwable) {
                }
                try { Thread.sleep(2000) } catch (_: InterruptedException) { return@Thread }
            }
        }, "KdKit-prefs-repair").apply { isDaemon = true }.start()
        XposedBridge.log("[KdKit] publisher: mode repair watchdog started")

        // 每 5 分钟一次心跳：把"监听器还在不在、触发过几次"写进日志。
        // 为什么需要：`SharedPreferences` 对监听器只存弱引用，一旦被回收，
        // 设置页改开关就**不再发布**，而 UI 一切正常 —— 只有靠这种心跳才看得出来。
        Thread({
            while (true) {
                try { Thread.sleep(300_000) } catch (_: InterruptedException) { return@Thread }
                XposedBridge.log(
                    "[KdKit] publisher heartbeat: listenerAlive=${listenerAlive()} fires=$changeListenerFires",
                )
            }
        }, "KdKit-prefs-heartbeat").apply { isDaemon = true }.start()
    }

    /** chmod 0644 through android.system.Os (Shell `chmod` is not always executable here). */
    private fun makeWorldReadable(file: File) {
        try {
            Os.chmod(file.absolutePath, 0x1A4 /* 0644 */)
        } catch (t: Throwable) {
            XposedBridge.log("[KdKit] publisher: chmod failed: $t")
        }
        try {
            if (!file.canRead()) XposedBridge.log("[KdKit] publisher: file still unreadable")
        } catch (_: Throwable) {}
    }

    /**
     * Mirrors the publish result into the app's own files dir so the settings UI can show it
     * (the UI cannot read the framework-owned publish path, and it must not touch Xposed classes).
     * The UI's "重新发布" button writes the `_repair` flag; that change lands here through the
     * shared-preferences listener and re-runs publish() + chmod.
     */
    private fun writeStatus(flags: Map<String, Boolean>, target: File, mode: String) {
        val f = statusFile ?: return
        try {
            f.writeText(
                "published=" + target.absolutePath + "\n" +
                    "mode=" + mode + "\n" +
                    "flags=" + flags.count { !it.key.startsWith("_") } + "\n" +
                    "flags_list=" + flags.entries.joinToString(",") { "${it.key}=${it.value}" } + "\n" +
                    "ts=" + System.currentTimeMillis() + "\n"
            )
        } catch (t: Throwable) {
            XposedBridge.log("[KdKit] publisher: status write failed: $t")
        }
    }

    /** Current string-valued settings (memory first, then the on-disk XML). */
    private fun stringSnapshot(prefs: SharedPreferences?): Map<String, String> {
        val fromMem = prefs?.all
            ?.mapNotNull { (k, v) -> if (k.startsWith("_")) null else (v as? String)?.let { k to it } }
            ?.toMap()
            .orEmpty()
        if (fromMem.isNotEmpty()) return fromMem
        return try {
            readStringPrefs(File(File(appDataDir(), "shared_prefs"), "${KdConfig.PREFS_NAME}.xml"))
        } catch (t: Throwable) {
            emptyMap()
        }
    }

    private var dataDirCache: File? = null
    private fun appDataDir(): File {
        dataDirCache?.let { return it }
        val d = try {
            val app = android.app.AndroidAppHelper.currentApplication() as? Context
            app?.let { File(it.dataDir.absolutePath) }
        } catch (t: Throwable) { null }
        return (d ?: File("/dev/null")).also { dataDirCache = it }
    }

    // 这两个正则在每次读 prefs 时都会用到（R20 的对账每 ~20 秒一次、每次发布也各读一次）。
    // 编译一次即可，没必要每次现编 —— 与 `NavFilter.ASSET_RX` 同一处置由。
    private val STRING_PREF_RX = Regex("<string\\s+name=\"([^\"]+)\">([^<]*)</string>")
    private val BOOL_PREF_RX = Regex("""<boolean\s+name="([^"]+)"\s+value="(true|false)"\s*/>""")

    /** String settings are published as `<string name="…">value</string>` next to the booleans. */
    private fun readStringPrefs(file: File): Map<String, String> {
        if (!file.exists()) return emptyMap()
        val rx = STRING_PREF_RX
        return try {
            rx.findAll(file.readText())
                .filter { !it.groupValues[1].startsWith("_") }
                .associate { it.groupValues[1] to it.groupValues[2] }
        } catch (t: Throwable) {
            emptyMap()
        }
    }

    /** Minimal parser for the app's own SharedPreferences XML (booleans only). */
    private fun readBooleanPrefs(file: File): Map<String, Boolean> {
        if (!file.exists()) return emptyMap()
        val rx = BOOL_PREF_RX
        return try {
            rx.findAll(file.readText())
                .filter { !it.groupValues[1].startsWith("_") }   // meta keys never go to the host
                .associate { it.groupValues[1] to (it.groupValues[2] == "true") }
        } catch (t: Throwable) {
            XposedBridge.log("[KdKit] publisher: file parse failed: $t")
            emptyMap()
        }
    }

    private fun publish(flags: Map<String, Boolean>, target: File,
                        strings: Map<String, String> = stringSnapshot(publishPrefs)) {
        try {
            target.parentFile?.mkdirs()
            val xml = buildString {
                append("<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n")
                for ((k, v) in flags) if (!k.startsWith("_")) append("    <boolean name=\"$k\" value=\"$v\" />\n")
                for ((k, v) in strings) if (!k.startsWith("_")) {
                    append("    <string name=\"$k\">").append(v).append("</string>\n")
                }
                append("</map>\n")
            }
            target.writeText(xml)
            // The host runs as a *different* uid: the file MUST be world-readable or
            // XSharedPreferences silently parses an empty map and every feature falls back to its
            // default (found 2026-10-11: file was 0660 -> host logged "all={}").
            makeWorldReadable(target)
            val mode = try { "%o".format(Os.stat(target.absolutePath).st_mode and 0x1ff) } catch (t: Throwable) { "?" }
            XposedBridge.log("[KdKit] published ${flags.size} flag(s) + ${strings.size} string(s) mode=$mode -> $target")
            writeStatus(flags, target, mode)
        } catch (t: Throwable) {
            XposedBridge.log("[KdKit] publish failed: $t")
        }
    }

}
