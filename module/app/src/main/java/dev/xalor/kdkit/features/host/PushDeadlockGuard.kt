package dev.xalor.kdkit.features.host

import android.os.Handler
import android.os.Looper
import android.os.Message
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedBridge
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

/**
 * 宿主百度推送 SDK 的**主线程锁死**防护。
 *
 * ## 真正的根因（2026-11-15 用 ANR trace 定位，之前的结论是错的）
 *
 * 之前我一直按固定类名 `com.baidu.techain.x18.OoccOCcoCCcC$ocOooocOcO` 去找类，真机日志
 * 永远是 `target=false`。ANR trace 给出了答案 —— 这些类**不在 APK 里**：
 *
 * ```
 * "techain_thread_" sysTid=18212
 *   #08 pc … [anon:dalvik-classes.dex extracted … /-.tmp_techain/-54388927/100019.4.6.1.1.p]
 *       (com.baidu.techain.x18.EngineImpl$2.run+18)
 * ```
 *
 * 也就是说：SDK 把 dex **运行时解包到 `files/.tmp_techain/`**，再用内存 ClassLoader 加载。
 * 而且 `x18` 下的类名（`OoccOCcoCCcC`、`ocOooocOcO`、目录名 `-54388927`）是
 * **每次安装随机生成**的 —— apktool 静态 dump 里查不到，写死类名永远命中不了。
 *
 * ## 所以这个版本怎么做
 *
 * 不再猜类名，只认**包名前缀** `com.baidu.techain`，在框架层拦：
 *
 * **`android.os.Handler#dispatchMessage`** —— 这是所有主线程回调的唯一汇合点。
 * 主线程上只要发现是百度推送 SDK 的 Message（`msg.callback` 的类名或 Handler 自身
 * 类名带前缀），就**不丢、也不在主线程跑**，而是转投到我们自己的单线程队列里执行：
 *
 * ```
 * 主线程 dispatchMessage 命中 → 跳过原调用（param.result = null）
 *                            → bg.execute { handler.dispatchMessage(msg) }
 * 后台线程再进 dispatchMessage → 线程不是主线程 → 放行 → 正常执行
 * ```
 *
 * 为什么是"转投后台"而不是"丢弃"：
 * 丢弃会让 SDK 在工作线程里持有的锁永远等不到这次回调完成，等于换一种死锁；
 * 转投既保证主线程从不进那段加锁代码，又保证回调**照样执行、顺序不变**（单线程队列）。
 * 广播入口那条短路保留（少起一个 SDK 线程、少发一次请求），但不再是唯一手段。
 *
 * 开销：`dispatchMessage` 是热路径，所以判断顺序是
 * `是否主线程` → `KdConfig 开关` → `msg.callback == null`（绝大多数消息走这条直接放行）
 * → 字符串 `startsWith`。常态开销约为每帧几条消息各一次 null 判断。
 */
object PushDeadlockGuard : SwitchFeature(
    id = "push_guard",
    title = "百度推送死锁防护",
    summary = "宿主 com.baidu.techain 推送 SDK 在主线程上抢锁并与自身线程反序持锁（ABBA 死锁），" +
        "是「拍完题返回卡死」的直接原因；本功能把它的主线程回调转投后台线程。宿主另有小米推送通道",
    category = Category.HOST,
    defaultOn = true,
    hot = false,
) {
    private const val RECEIVER = "com.homework.lib_techain_push.receiver.BaiduTechainPushReceiver"

    /** 只认前缀：`x18` 下的类名每次安装都随机生成，写死任何全名都不可能命中。 */
    private const val PREFIX = "com.baidu.techain"

    /** 转投次数（用于日志与自检）。 */
    private val offloaded = AtomicLong()

    /** 单线程：保证 SDK 回调之间的先后顺序不被我们打乱。 */
    private val bg by lazy {
        Executors.newSingleThreadExecutor { r ->
            Thread(r, "kdkit-techain").apply { isDaemon = true }
        }
    }

    override fun install() {
        // ① 广播入口短路：让 SDK 少起一个线程、少发一次网络请求
        val a = Xp.hookAllBefore(RECEIVER, "onReceive", gate = id) { p -> p.result = null }

        // ② 主钩子：主线程上的百度推送回调一律转投后台线程
        val b = runCatching {
            XposedBridge.hookAllMethods(
                Handler::class.java,
                "dispatchMessage",
                object : XC_MethodHook() {
                    override fun beforeHookedMethod(param: MethodHookParam) {
                        // 最热的两个判断放最前面，非主线程/关掉开关时开销接近零
                        if (Looper.myLooper() != Looper.getMainLooper()) return
                        if (!dev.xalor.kdkit.config.KdConfig.isOn(id, defaultOn)) return

                        val handler = param.thisObject as? Handler ?: return
                        val msg = param.args.getOrNull(0) as? Message ?: return

                        // 绝大多数主线程消息 callback 为 null 且 Handler 是框架类 → 一次判断就放行
                        val cb = msg.callback
                        val hit = (cb != null && cb.javaClass.name.startsWith(PREFIX)) ||
                            handler.javaClass.name.startsWith(PREFIX)
                        if (!hit) return

                        // 跳过原调用 → 主线程不再进入 SDK 的加锁回调
                        param.result = null
                        // 转投后台：dispatchMessage 在非主线程上会穿过本钩子正常执行
                        bg.execute {
                            runCatching { handler.dispatchMessage(msg) }
                                .onFailure { KdLog.e("PushDeadlockGuard offload failed", it) }
                        }
                        val n = offloaded.incrementAndGet()
                        if (n == 1L || n % 50 == 0L) {
                            KdLog.i("PushDeadlockGuard: offloaded techain msg from main thread (#$n)")
                        }
                    }
                },
            ).size
        }.getOrElse {
            KdLog.e("PushDeadlockGuard dispatchMessage hook failed", it)
            0
        }

        KdLog.i("PushDeadlockGuard installed (receiver=$a, dispatch=$b, prefix=$PREFIX)")
    }
}
