package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/**
 * 百度推送 SDK 的**主线程死锁**防护。
 *
 * ### 现场（2026-11-15，真机 Redmi M332BF / Android 17 抓到的 ANR 主线程栈）
 *
 * ```
 * "Thread-45" prio=5 tid=1 Blocked          ← 主线程
 *   at com.baidu.techain.x18.…ocOooocOcO.OoccOCcoCCcC(PushManager.java:642)
 *   - waiting to lock <0x0031b67d> held by thread 40
 * "Thread-48" prio=5 tid=40 Blocked
 *   at com.baidu.techain.x18.…OoccOCcoCCcC(Client.java:486)
 *   - waiting to lock <0x0c72f972> held by thread 1
 * ```
 *
 * 典型的 ABBA 交叉死锁：主线程拿着 `ocOooocOcO` 等 `CcooOoocOOo`，
 * SDK 自己的线程 40 反过来拿着 `CcooOoocOOo` 等 `ocOooocOcO`。
 * 一旦撞上，主线程就永久 Blocked —— 用户看到的就是「从拍题返回后整机卡住、
 * 只能强杀」，而 dumpsys 里是 `Input dispatching timed out`。
 *
 * ### 为什么可以安全关掉
 *
 * 宿主的推送通道不止一条：同一份 ANR trace 里还有 `com.xiaomi.mipush.sdk`
 * （`MessageHandleService` / `PushMessageHandler` 都在跑）。百度 techain 只是其中一条，
 * 关掉它不影响通知到达，但能彻底拆掉这对锁的其中一头。
 *
 * ### 手法
 *
 * 直接让 `BaiduTechainPushReceiver.onReceive` 提前返回：广播进来不进 SDK，
 * SDK 就不起那批线程，也就没有 ABBA 的另一半。
 */
object PushDeadlockGuard : SwitchFeature(
    id = "push_guard",
    title = "百度推送死锁防护",
    summary = "绕过 com.baidu.techain 推送回调：该 SDK 与主线程持锁顺序相反（ABBA 死锁），" +
        "是「从拍题返回后卡死」的直接原因；宿主另有小米推送通道，通知不受影响",
    category = Category.HOST,
    defaultOn = true,
    hot = false,
) {
    private const val RECEIVER = "com.homework.lib_techain_push.receiver.BaiduTechainPushReceiver"

    /** 判定过的 Runnable 类：命中一次就记住，之后每次 post 只查一个 Set。 */
    private val baiduRunnables = java.util.concurrent.ConcurrentHashMap<Class<*>, Boolean>()

    private fun isBaidu(r: Runnable?): Boolean {
        val c = r?.javaClass ?: return false
        return baiduRunnables.getOrPut(c) { c.name.startsWith(BAIDU_PREFIX) }
    }

    override fun install() {
        // ① 广播入口直接返回（SDK 根本不起线程）
        val a = Xp.hookAllBefore(RECEIVER, "onReceive", gate = id) { p -> p.result = null }

        // ② 真正的死锁点：SDK 把自己的回调 post 到主线程，回调里先拿 ocOooocOcO，
        //    再去拿 CcooOoocOOo；而 SDK 线程 27 反着拿 —— ABBA 死锁。
        //    在 post 处把百度 SDK 的 Runnable 丢掉，主线程就永远不会进入那段加锁代码。
        //    （只按类名前缀过滤，其他任何 Handler.post 原样放行。）
        var b = 0
        // 注意：hookAllBefore 的第 3 个参数是 ClassLoader，不是方法签名 ——
        // 传 Runnable::class.java 会被当成 classLoader（编译期就报类型不匹配）。
        // 这里按方法名挂全部重载，回调里自己判第一个参数是不是 Runnable。
        b += Xp.hookAllBefore("android.os.Handler", "post", gate = id) { p ->
            val r = p.args.getOrNull(0)
            if (r is Runnable && isBaidu(r)) p.result = false
        }
        b += Xp.hookAllBefore("android.os.Handler", "postDelayed", gate = id) { p ->
            val r = p.args.getOrNull(0)
            if (r is Runnable && isBaidu(r)) p.result = false
        }
        // ③ 决定性的一刀：连主线程都不许进入 PushManager 那段加锁代码。
        //
        //    真机 trace（两次独立抓取，pid 3744 / 08:44）：
        //      "Thread-47" tid=1 Blocked
        //        at …ocOooocOcO.OoccOCcoCCcC(PushManager.java:642)  - locked <ocOooocOcO>
        //        at …ocOooocOcO$2.run(PushManager.java:1015)
        //        - waiting to lock <CcooOoocOOo> held by thread 134
        //    也就是说：只要这个 Runnable 在主线程上跑过一次，就会和 SDK 线程互锁。
        //    这里在方法入口处判线程：主线程直接跳过（子线程照旧），SDK 的推送逻辑移到后台。
        var c = 0
        c += Xp.hookAllBefore(
            "com.baidu.techain.x18.OoccOCcoCCcC\$ocOooocOcO", "OoccOCcoCCcC", gate = id,
        ) { p ->
            if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) p.result = null
        }
        KdLog.i("PushDeadlockGuard installed (receiver=$a hooks, post=$b hooks, lock=$c hooks)")
    }

    private const val BAIDU_PREFIX = "com.baidu.techain"
}
