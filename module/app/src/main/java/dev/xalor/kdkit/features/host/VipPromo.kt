package dev.xalor.kdkit.features.host

import de.robv.android.xposed.XC_MethodHook.MethodHookParam
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.features.web.WebInjector
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/**
 * 会员推广清理 —— 关掉"劝你开会员"的那一类界面，**不碰会员状态本身**。
 *
 * 与 [VipUnlock] 的分界：`vip_unlock` 改的是"我是不是会员"，本功能改的是"弹不弹推销"。
 *
 * 拦在四个地方（都在真机上验证过）：
 *  1. `MainBottomPayDialog.Q/P` —— 底部会员支付弹窗的两个 public 打开入口；
 *  2. `DialogFragment.show` —— 兜底：任何路径走到 show() 且 this 是它，就不提交事务；
 *  3. `hh.y.F()` —— 服务端弹窗总闸门的 `winVIPBottom` 分支；
 *  4. `MineMembershipCardsView.bindView` —— 「我的」页那张原生 VIP 卡（**原生视图，JS 碰不到**）。
 *
 * 页面内（H5）的"立即开通"入口是**可选**（`rm_vip_promo_h5`，默认关）：它是内容级过滤，
 * 一旦范围算错就会把承载内容的容器一起隐藏 —— 2026-11-14 在拍题答疑页真的出现过整页空白。
 * 现在只允许隐藏"≤14 字、面积 ≤ 视口 20% 的直接可点击元素"，宁可少隐藏也不让页面变空。
 */
object VipPromo : SwitchFeature(
    id = "rm_vip_promo",
    title = "会员推广清理",
    summary = "关掉底部会员支付弹窗、服务端 winVIPBottom 弹窗、「我的」页会员卡与页面内开通入口；不改会员判定",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val DIALOG = "com.kuaiduizuoye.scan.activity.main.util.MainBottomPayDialog"

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "rm_vip_promo_h5",
            title = "同时隐藏页面内的开通入口",
            summary = "只隐藏文本 ≤14 字、面积 ≤ 视口 20% 的「立即开通 / 限时特惠」按钮；默认关，怕误伤就别开",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        val g = id
        var n = 0

        // 1) 底部会员支付弹窗：两个 public 入口直接短路。
        //    形参类型走运行时解析：模块不依赖 androidx.fragment（少一个与宿主版本打架的点）。
        val fragActivity = Xp.clazzOrNull("androidx.fragment.app.FragmentActivity")
        if (fragActivity != null && Xp.hook(DIALOG, "Q", fragActivity, gate = g, onBefore = {
                if (Xp.returnsVoid(it)) it.result = null
            })) n++

        Xp.clazzOrNull("fh.a")?.let { arg ->
            if (Xp.hook(DIALOG, "P", arg, gate = g, onBefore = {
                    if (Xp.returnsVoid(it)) it.result = null
                })) n++
        }

        // 2) 兜底：任何路径走到 DialogFragment.show() 时，只要 this 是它，就不 show。
        val showBlocked: (MethodHookParam) -> Unit = { p ->
            val name = p.thisObject?.javaClass?.name ?: ""
            if (name == DIALOG) {
                p.result = 0          // show() 返回 int（transaction id），0 = 没提交
                KdLog.i("VipPromo: blocked MainBottomPayDialog.show")
                Capture.mark("PROMO blocked dialog show")
            }
        }
        val fragManager = Xp.clazzOrNull("androidx.fragment.app.FragmentManager")
        val fragTxn = Xp.clazzOrNull("androidx.fragment.app.FragmentTransaction")
        if (fragManager != null && Xp.hook("androidx.fragment.app.DialogFragment", "show",
                fragManager, String::class.java, gate = g, onBefore = showBlocked)) n++
        if (fragTxn != null && Xp.hook("androidx.fragment.app.DialogFragment", "show",
                fragTxn, String::class.java, gate = g, onBefore = showBlocked)) n++

        // 3) 服务端弹窗的 winVIPBottom 分支。
        if (Xp.hook("hh.y", "F", gate = g, onBefore = {
                if (Xp.returnsVoid(it)) {
                    it.result = null
                    KdLog.i("VipPromo: blocked winVIPBottom")
                    Capture.mark("PROMO blocked winVIPBottom")
                }
            })) n++

        // 4) 「我的」页的会员推广卡（原生 FrameLayout 视图）。
        val cardModel = Xp.clazzOrNull("com.kuaiduizuoye.scan.common.net.model.v1.ConfMyCard")
        if (cardModel != null && Xp.hook(
                "com.kuaiduizuoye.scan.activity.mine.widget.MineMembershipCardsView",
                "bindView", cardModel, Boolean::class.javaPrimitiveType,
                gate = g, onAfter = { p ->
                    (p.thisObject as? android.view.View)?.let { v ->
                        v.visibility = android.view.View.GONE
                        KdLog.i("VipPromo: hid MineMembershipCardsView")
                        Capture.mark("PROMO hid membership card view")
                    }
                },
            )
        ) n++

        // 5) 页面内的开通入口（H5，可选、默认关）。
        WebInjector.register("rm_vip_promo_h5") {
            if (!KdConfig.isOn("rm_vip_promo", defaultOn) ||
                !KdConfig.isOn("rm_vip_promo_h5", false)
            ) "" else HIDE_PROMO_JS
        }

        KdLog.i("VipPromo installed ($n hooks + h5 provider)")
    }

    /**
     * 短文案 + 推广词 ⇒ 隐藏**直接可点击**的那一个元素。
     *
     * 2026-11-14 修：旧实现向上找 3 层"可点击祖先"，在拍题答疑页把承载内容的整块容器
     * 一起隐藏 —— 用户看到整页空白。现在只允许隐藏：
     *  * 文本 ≤ 14 字的 BUTTON / A / role=button；
     *  * 面积不超过视口 20%；
     *  * 不是 body / #app / 固定的整条底栏。
     */
    private const val HIDE_PROMO_JS = """
(function(){
  if (window.__kdkit_vip_promo) return; window.__kdkit_vip_promo = 1;
  var RE = /(立即开通|开通会员|会员专享|限时特惠|限时优惠|首月|续费|升级会员)/;
  function sweep(){
    var vh = window.innerHeight, vArea = window.innerWidth * vh;
    var nodes = document.querySelectorAll('button,a,[role="button"]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.__kdkit_promo_hidden) continue;
      var t = (el.innerText || '').trim();
      if (t.length === 0 || t.length > 14) continue;
      if (!RE.test(t)) continue;
      var r = el.getBoundingClientRect();
      if (r.width * r.height > vArea * 0.20) continue;
      if (el.id === 'app' || el.tagName === 'BODY') continue;
      var cs = getComputedStyle(el);
      if (cs.position === 'fixed' && r.height > vh * 0.4) continue;
      el.style.setProperty('display', 'none', 'important');
      el.__kdkit_promo_hidden = 1;
    }
  }
  sweep();
  try {
    new MutationObserver(function(){
      clearTimeout(window.__kdkit_vip_t);
      window.__kdkit_vip_t = setTimeout(sweep, 500);
    }).observe(document.documentElement, {childList: true, subtree: true});
  } catch (e) {}
})();
"""
}
