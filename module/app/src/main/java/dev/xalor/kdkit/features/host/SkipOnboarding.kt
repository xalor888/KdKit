package dev.xalor.kdkit.features.host

import android.app.Activity
import android.app.Dialog
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp
import java.util.concurrent.atomic.AtomicInteger

/**
 * 跳过首次启动引导（**自动化 / 测试用**，默认关闭）。
 *
 * 冷装后会拦三个原生界面：隐私「同意并使用」→ 青少年守护「已满14岁」→ 身份选择「暂不设置」。
 * 手工点一遍很烦，脚本化回归（例如 e2e 验收、单元重装）每次都要点。
 *
 * 实现刻意**不依赖混淆后的类名**：只挂 `Activity.onResume` 与 `Dialog.show`，
 * 然后在 decorView 里**按文案**找可点的祖先并 `performClick()`。宿主改版只要文案不变就还能用。
 */
object SkipOnboarding : SwitchFeature(
    id = "skip_onboarding",
    title = "跳过首次启动引导",
    summary = "自动点掉隐私同意 / 青少年守护 / 身份选择（自动化验收用，默认关闭）",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    /** 文案 → 说明；命中即点它的可点祖先。 */
    private val TARGETS = listOf(
        "同意并使用" to "隐私政策",
        "已满14岁" to "青少年守护",
        "暂不设置" to "身份选择",
    )
    private val clicked = AtomicInteger(0)

    override fun install() {
        var n = 0
        n += Xp.hookAll("android.app.Activity", "onResume", cl = null, cb = object : XC_MethodHook() {
            override fun afterHookedMethod(param: MethodHookParam) {
                if (!dev.xalor.kdkit.config.KdConfig.isOn(id, false)) return
                val act = param.thisObject as? Activity ?: return
                schedule("activity ${act.javaClass.simpleName}") { act.window?.decorView }
            }
        })
        n += Xp.hookAll("android.app.Dialog", "show", cl = null, cb = object : XC_MethodHook() {
            override fun afterHookedMethod(param: MethodHookParam) {
                if (!dev.xalor.kdkit.config.KdConfig.isOn(id, false)) return
                val dlg = param.thisObject as? Dialog ?: return
                schedule("dialog ${dlg.javaClass.simpleName}") { dlg.window?.decorView }
            }
        })
        KdLog.i("SkipOnboarding installed ($n hooks)")
    }

    /**
     * UI 出现有延迟（尤其是服务端下发文案的弹窗），分几次重试直到点到或超时。
     *
     * ### 旧实现会**永久放弃**（2026-11-02 审查 P2-8，已在 7.9.0 上核实成立）
     *
     * ```kotlin
     * if (tries[0]++ < 6) v?.postDelayed(this, 700)    // v 为 null ⇒ 什么都不做
     * root()?.postDelayed(run, 500) ?: run.run()
     * ```
     *
     * `onResume` 那一刻 `window.decorView` 常常还没挂上（`onCreate` 刚跑完、`setContentView`
     * 可能还没执行）。这时 `v` 是 null：
     *  * 重试链挂在 `v` 上 ⇒ 没人再排下一次；
     *  * 初次调度也走 `?: run.run()` ⇒ 立刻跑一次、立刻结束。
     *
     * 结果：**只要第一次拿不到 decorView，这个功能就再也不试了**，而且没有任何日志。
     *
     * ### 现在
     *
     * 重试链挂在**主线程 Handler** 上，与 View 的生死无关 —— decorView 什么时候出现都接得上。
     * 超时后写一行抓取，让"试了 6 次没找到"变成可见结论，而不是静默无声。
     */
    private val mainHandler by lazy { android.os.Handler(android.os.Looper.getMainLooper()) }

    private fun schedule(where: String, root: () -> View?) {
        var tries = 0
        val run = object : Runnable {
            override fun run() {
                val v = root()
                if (v != null && click(v)) return
                if (tries++ < MAX_TRIES) {
                    mainHandler.postDelayed(this, 700)
                } else {
                    KdLog.d("SkipOnboarding: $where 重试 $MAX_TRIES 次仍未命中（decorView=${v != null}）")
                    dev.xalor.kdkit.util.Capture.append(
                        "ONBOARD giveup where=\"$where\" tries=$MAX_TRIES decorReady=${v != null}",
                    )
                }
            }
        }
        mainHandler.postDelayed(run, 500)
    }

    /** 6 次 × 700 ms ≈ 4.2 s —— 覆盖"服务端下发文案再弹窗"的延迟。 */
    private const val MAX_TRIES = 6

    private fun click(root: View): Boolean {
        for ((text, label) in TARGETS) {
            val tv = find(root, text) ?: continue
            val target = clickableAncestor(tv) ?: tv
            val ok = target.performClick()
            val k = clicked.incrementAndGet()
            KdLog.i("SkipOnboarding: clicked '$text' ($label) #$k ok=$ok")
            dev.xalor.kdkit.util.Capture.append("ONBOARD clicked='$text' label=$label #$k ok=$ok")
            return true
        }
        return false
    }

    private fun find(v: View, text: String): TextView? {
        if (v is TextView && v.text?.toString()?.trim() == text) return v
        if (v is ViewGroup) {
            for (i in 0 until v.childCount) find(v.getChildAt(i), text)?.let { return it }
        }
        return null
    }

    private fun clickableAncestor(v: View): View? {
        var cur: View? = v
        var depth = 0
        while (cur != null && depth < 6) {
            if (cur.isClickable) return cur
            cur = cur.parent as? View
            depth++
        }
        return null
    }
}
