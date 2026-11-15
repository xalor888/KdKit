package dev.xalor.kdkit.features.host

import android.os.Looper
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedBridge
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/**
 * 宿主百度推送 SDK 的**主线程 ABBA 死锁**防护。
 *
 * ### 现场（真机 Redmi M332BF / Android 17，两次独立 kill -3 抓到同一处）
 *
 * ```
 * "Thread-47" prio=5 tid=1 Blocked                     ← 主线程
 *   at com.baidu.techain.x18.…ocOooocOcO.OoccOCcoCCcC(PushManager.java:642)
 *   - locked <ocOooocOcO>
 *   at com.baidu.techain.x18.…ocOooocOcO$2.run(PushManager.java:1015)
 *   - waiting to lock <CcooOoocOOo> held by thread 134
 * ```
 *
 * 主线程持 `ocOooocOcO` 等 `CcooOoocOOo`，SDK 自己的线程 134 反序持锁 —— 交叉死锁，
 * 主线程永久 Blocked，系统判 `Input dispatching timed out`。用户看到的就是
 * 「拍完题返回就卡死」。
 *
 * ### 为什么以前的写法挂不上（关键教训）
 *
 * 第一版直接按名字 `Xp.hookAllBefore("com.baidu.techain.x18.…$2", "run")` ——
 * 真机日志是 `run=0 hooks`。原因：**这个 SDK 的类不在宿主的 base ClassLoader 里**
 * （base PathClassLoader 解析不到 `com.baidu.techain.x18`），而 `Xp.clazzOrNull` 只用
 * `Xp.classLoader`。所以这里改成"**等它自己把类加载出来**"：
 *
 *   监听 `java.lang.ClassLoader#loadClass`（只看 `com.baidu.techain` 前缀，别的类一行就走），
 *   一旦发现目标类被某个 loader 加载成功，立刻在这个 Class 上挂方法钩子
 *   （主线程调用就跳过，子线程照旧）。
 *
 * 这样既不需要知道 loader 是谁，也不依赖类名解析。
 */
object PushDeadlockGuard : SwitchFeature(
    id = "push_guard",
    title = "百度推送死锁防护",
    summary = "宿主 com.baidu.techain 推送 SDK 与主线程反序持锁（ABBA 死锁），是「拍完题返回卡死」" +
        "的直接原因；本功能在主线程上跳过那段加锁回调。宿主另有小米推送通道，通知不受影响",
    category = Category.HOST,
    defaultOn = true,
    hot = false,
) {
    private const val RECEIVER = "com.homework.lib_techain_push.receiver.BaiduTechainPushReceiver"
    private const val PREFIX = "com.baidu.techain"
    private const val TARGET = "com.baidu.techain.x18.OoccOCcoCCcC\$ocOooocOcO"
    private const val METHOD = "OoccOCcoCCcC"

    @Volatile private var installedOn: Class<*>? = null
    @Volatile private var skipped = 0

    override fun install() {
        // ① 广播入口短路（SDK 不起线程）
        val a = Xp.hookAllBefore(RECEIVER, "onReceive", gate = id) { p -> p.result = null }

        // ② 已在别处加载过就先直接挂（有 loader 时能命中）
        runCatching {
            val c = Xp.clazzOrNull(TARGET)
            if (c != null) hookClass(c)
        }

        // ③ 主钩子：ClassLoader 加载到这里时再挂（跨 ClassLoader 也能命中）
        val b = Xp.hookAllAfter(
            "java.lang.ClassLoader", "loadClass", cl = null, gate = null,
        ) { p ->
            val n = p.args.getOrNull(0) as? String ?: return@hookAllAfter
            // 热路径：绝大多数类名不是 baidu 前缀，一次 startsWith 就返回
            if (!n.startsWith(PREFIX)) return@hookAllAfter
            val loaded = p.getResult() as? Class<*> ?: return@hookAllAfter
            if (loaded.name == TARGET) hookClass(loaded)
        }

        KdLog.i("PushDeadlockGuard installed (receiver=$a, loaderWatch=$b, target=${installedOn != null})")
    }

    /** 在目标类上挂"主线程跳过"的钩子。 */
    private fun hookClass(c: Class<*>) {
        if (installedOn === c) return
        installedOn = c
        var n = 0
        for (m in c.declaredMethods) {
            if (m.name != METHOD) continue
            runCatching {
                XposedBridge.hookMethod(m, object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        if (!dev.xalor.kdkit.config.KdConfig.isOn(id, defaultOn)) return
                        if (Looper.myLooper() == Looper.getMainLooper()) {
                            param.result = null
                            if (++skipped % 20 == 1) {
                                KdLog.i("PushDeadlockGuard: skipped SDK lock on main (#$skipped)")
                            }
                        }
                    }
                })
                n++
            }.onFailure { KdLog.e("PushDeadlockGuard hook failed", it) }
        }
        KdLog.i("PushDeadlockGuard hooked ${c.name} ($n methods, loader=${c.classLoader?.javaClass?.simpleName})")
    }
}
