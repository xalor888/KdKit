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
 * 与 [VipUnlock] 的分界（很重要，别混）：
 *  * `vip_unlock` 改的是**状态判定**（我是不是会员）；
 *  * 本功能改的是**推销**（弹不弹"立即开通/限时特惠/续费"的界面）。
 *    它**不**改变你会不会真的成为会员，也不碰服务端鉴权。
 *
 * ### 拦在哪三个地方（都是静态确认过的入口）
 *
 * | # | 目标 | 为什么是它 |
 * |---|---|---|
 * | 1 | `MainBottomPayDialog.Q(FragmentActivity)V` / `P(Lfh/a;)V` | 底部会员支付弹窗的两个 public 打开入口（H5 支付页宿主），短路即不创建、不 show |
 * | 2 | `androidx.fragment.app.DialogFragment.show(...)` → **类型判断**后短路 | 兜底：宿主可能绕开上面的入口直接 `show()`；只拦 `MainBottomPayDialog`，别的 DialogFragment 一律放行 |
 * | 3 | `hh.y.F()V` | 服务端弹窗总闸门里 `winVIPBottom` 分支的实现体（`y.smali:767`，VIP 购买页 `zyb://kd-vip/page/vip-buy-paisou`） |
 *
 * ### 页面内（H5）的推广入口
 *
 * `rm_vip_promo_h5` 打开时注入一段 JS：把**文本很短、且含推广词**的可点击块隐藏掉
 * （"立即开通 / 开通会员 / 限时特惠 / 首月 / 续费 / 会员权益"）。
 * 这是**内容级**过滤，不是资源级：它不会拦请求、不会让页面报错，只是把这些按钮藏起来。
 * 测不准就不开 —— 这是它默认关、并且单独的开关的原因。
 *
 * ### 不做什么
 *
 * 不拦 `/kdapi`、`/plutus` 的会员推广接口（那是服务端权威，拦了会让页面缺数据）；
 * 不动开屏**广告素材**（那是 `rm_splash` 的活）。开屏之后弹的会员推广，走的就是上面第 1、3 条。
 */
object VipPromo : SwitchFeature(
    id = "rm_vip_promo",
    title = "会员推广清理",
    summary = "关掉底部会员支付弹窗、服务端 winVIPBottom 弹窗与页面内的开通入口；不改会员判定",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val DIALOG = "com.kuaiduizuoye.scan.activity.main.util.MainBottomPayDialog"

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "rm_vip_promo_h5",
            title = "同时隐藏页面内的开通入口",
            summary = "注入 JS 隐藏含「立即开通 / 限时特惠 / 首月 / 续费」的短文案按钮；怕误伤就关掉",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
    )

    override fun install() {
        val g = id
        var n = 0

        // 1) 底部会员支付弹窗：两个 public 入口直接短路。
        //
        // 形参类型走**运行时解析**而不是编译期 import：模块不依赖 androidx.fragment
        // （少一个依赖 = 少一处与宿主 fragment 版本打架的可能），且这些类名本身是可读的。
        val fragActivity = Xp.clazzOrNull("androidx.fragment.app.FragmentActivity")
        if (fragActivity != null && Xp.hook(DIALOG, "Q", fragActivity, gate = g, onBefore = {
                if (Xp.returnsVoid(it)) it.result = null
            })) n++

        // `P(Lfh/a;)V` 的形参类型是混淆名，只能运行时解析；解析不到就跳过（不硬失败）。
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

        // 4) 「我的」页的会员推广卡（原生 FrameLayout 视图，数据绑定入口就在 bindView）。
        //    它不是 H5，JS 碰不到 —— 这也是为什么"整页去推广"必须原生与页面两条路都做。
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

        // 5) 页面内的开通入口（H5，内容级过滤）。
        WebInjector.register("rm_vip_promo_h5") {
            if (!KdConfig.isOn("rm_vip_promo", defaultOn) ||
                !KdConfig.isOn("rm_vip_promo_h5", true)
            ) "" else HIDE_PROMO_JS
        }

        KdLog.i("VipPromo installed ($n hooks + h5 provider)")
    }

    /** 短文案 + 推广词 ⇒ 隐藏最近的"可点击容器"（不是粗暴地把整块内容删掉）。 */
    private const val HIDE_PROMO_JS = """
(function(){
  if (window.__kdkit_vip_promo) return; window.__kdkit_vip_promo = 1;
  var RE = /(立即开通|开通会员|会员专享|限时特惠|限时优惠|首月|续费|会员权益|升级会员|开通\\s*VIP)/;
  function sweep(){
    var nodes = document.querySelectorAll('button,[role="button"],a,div,span');
    var hit = 0;
    for (var i = 0; i < nodes.length && hit < 40; i++) {
      var el = nodes[i];
      if (el.__kdkit_promo_hidden) continue;
      var t = (el.innerText || '').trim();
      if (t.length === 0 || t.length > 20) continue;      // 长文本是正文，不动
      if (!RE.test(t)) continue;
      // 找可点击的祖先（或自身），整块隐藏
      var box = el;
      for (var k = 0; k < 3 && box.parentElement; k++) {
        if (box.tagName === 'BUTTON' || box.tagName === 'A' ||
            getComputedStyle(box).cursor === 'pointer') break;
        box = box.parentElement;
      }
      box.style.setProperty('display', 'none', 'important');
      box.__kdkit_promo_hidden = 1; hit++;
    }
  }
  sweep();
  try { new MutationObserver(function(){ clearTimeout(window.__kdkit_vip_t); window.__kdkit_vip_t = setTimeout(sweep, 400); })
        .observe(document.documentElement, {childList:true, subtree:true}); } catch(e){}
})();
"""
}
