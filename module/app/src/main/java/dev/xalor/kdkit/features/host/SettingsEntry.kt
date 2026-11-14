package dev.xalor.kdkit.features.host

import android.content.Context
import android.content.Intent
import android.view.View
import de.robv.android.xposed.XC_MethodHook
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.features.web.WebInjector
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 在快对**自己的「设置」页**里插一行「KdKit 模块设置」，点它打开模块设置页。
 *
 * ### 为什么是 H5 注入而不是"往列表数据模型里插一条"
 *
 * 「我的」页里那个「设置」项（`MineTabModel.DXSingleItem`，item type `0x1f`）走
 * `MineFragment` → `ri.a.a(Context)` → `CommonCacheHybridActivity.createIntent(ctx,
 * "zyb://app-vue/page/newSetUp")`。也就是说 7.10.2 的**设置页本身是一个 Vue H5 页面**
 * （`res/values/strings.xml` 里连「清除缓存 / 检查更新 / 关于快对」都没有 —— 设置项文案
 * 全在 H5 包里）。所以原生侧没有可插的 adapter：要在设置页里多一行，只能往页面 DOM 里插，
 * 而"点它回到原生"必须有一条回传通道 —— 这里用的是自定义 scheme `kdkit://open-settings`。
 *
 * 注入走 [WebInjector] 的 provider（与 `md3_skin` / `pk_assist` 同一条通道）：
 * 页面 `loadUrl` / `onPageFinished` 时统一 `evaluateJavascript`，脚本自己判"这是设置页"。
 *
 * ### 回传通道
 *
 * 快对的 hybrid 客户端是 `com.zuoyebang.widget.CacheHybridWebView$d` →
 * `HybridWebView$HybridWebViewClient` → `com.zuoyebang.common.web.WebViewClient`
 * （最后一个的 `shouldOverrideUrlLoading(WebView, String)` 只 `return false`，是所有
 * 未处理 URL 的兜底）。子类只在"自己认识的 URL"上短路，不认识的会一路 `invoke-super` 下来，
 * 所以钩住这个**公共基类**即可拿到 `kdkit://`：命中就把返回值改成 `true`（消费掉，页面不跳走），
 * 再用 WebView 的 Context 启动模块 Activity。
 *
 * 同时也钩 `android.webkit.WebViewClient`：原生页面里若用系统 WebView 而不是快对包装类，
 * 仍然能命中同一条逻辑（两处都命中时用 [RateLimit] 只放行一次）。
 */
object SettingsEntry : SwitchFeature(
    id = "settings_entry",
    title = "设置页 KdKit 入口",
    summary = "在快对「设置」页注入一行「KdKit 模块设置」；点击走 kdkit://open-settings，" +
        "由 com.zuoyebang.common.web.WebViewClient.shouldOverrideUrlLoading 消费并启动模块设置页",
    category = Category.HOST,
    defaultOn = true,
    hot = false,
) {
    /** 注入行点击后跳的地址；前缀比较，后面的 query 随便带。 */
    const val SCHEME = "kdkit://open-settings"

    private const val MODULE_ACTIVITY = "dev.xalor.kdkit.ui.MainActivity"

    /** 行文案 —— 用户看到的那一行。 */
    private const val ROW_LABEL = "KdKit 模块设置"

    override fun install() {
        WebInjector.register(id) {
            if (KdConfig.isOn(id, defaultOn)) script() else ""
        }

        // 两个类名都写成**字面量**，一条一条列出来（不放进 listOf 循环）：
        // 门禁 ④ 只认 `Xp.hook` 后跟两个字符串字面量的形态，循环变量形态它看不见 ——
        // 那就等于这两条钩子从未被"类/方法还在不在"校验过。
        val g = id
        val n = Xp.hookAllBefore(
            "com.zuoyebang.common.web.WebViewClient", "shouldOverrideUrlLoading",
            gate = g,
        ) { p -> onNavigate(p) } +
            Xp.hookAllBefore(
                "android.webkit.WebViewClient", "shouldOverrideUrlLoading",
                gate = g,
            ) { p -> onNavigate(p) }
        KdLog.i("SettingsEntry installed ($n hooks)")
    }

    // ── 原生侧：kdkit:// → 模块设置页 ─────────────────────────────────────────

    private fun onNavigate(p: XC_MethodHook.MethodHookParam) {
        val url = urlOf(p) ?: return
        if (!url.startsWith(SCHEME)) return
        // 两层客户端都会回调；一次点击只该启动一次。
        if (!RateLimit.every("settings_entry_open", 800)) return
        // 消费掉这次导航：boolean 版返回 true，void 版直接跳过原方法。
        // 两种都写死会把返回值类型搞错（见 Xp.returnsBoolean/returnsVoid 的注释）。
        if (Xp.returnsBoolean(p)) p.result = true else if (Xp.returnsVoid(p)) p.result = null

        val ctx = contextOf(p)
        if (ctx == null) {
            KdLog.w("SettingsEntry: clicked but no Context on the WebView; cannot launch module UI")
            Capture.append("SETTINGS entry clicked without a Context")
            return
        }
        val intent = Intent()
            .setClassName(KdConfig.MODULE_PKG, MODULE_ACTIVITY)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        try {
            ctx.startActivity(intent)
            KdLog.i("SettingsEntry: module settings launched from ${ctx.javaClass.simpleName}")
            Capture.append("SETTINGS entry opened from ${ctx.javaClass.simpleName}")
        } catch (t: Throwable) {
            // 宿主进程可能看不到模块包（Android 11+ 包可见性）或被 OEM 拦；
            // 这条要落进抓取文件，否则现象只是"点了没反应"。
            KdLog.w("SettingsEntry: startActivity failed: $t")
            Capture.append("SETTINGS launch failed ${t.javaClass.simpleName}: " +
                (t.message ?: "").take(120))
        }
    }

    /** `(WebView, String)` → args[1] 是字符串；`(WebView, WebResourceRequest)` → 反射 `getUrl()`。 */
    @Volatile
    private var getUrlMethod: java.lang.reflect.Method? = null

    private fun urlOf(p: XC_MethodHook.MethodHookParam): String? {
        val arg = p.args.getOrNull(1) ?: return null
        if (arg is String) return arg
        val getter = getUrlMethod ?: runCatching { arg.javaClass.getMethod("getUrl") }
            .getOrNull()?.also { getUrlMethod = it }
        if (getter == null) return null
        return runCatching { getter.invoke(arg)?.toString() }.getOrNull()
    }

    /**
     * 从 WebView 参数取 Context。
     *
     * 快对的 `com.zuoyebang.common.web.WebView` 是包着真 WebView 的 **FrameLayout 包装类**
     * （不是 `android.webkit.WebView` 的子类），所以按 `View` 取 `context` 就能拿到宿主 Activity，
     * 不用去碰它的私有 `_kit` 字段。
     */
    private fun contextOf(p: XC_MethodHook.MethodHookParam): Context? {
        (p.args.getOrNull(0) as? View)?.context?.let { return it }
        return runCatching { android.app.AndroidAppHelper.currentApplication() }.getOrNull()
    }

    // ── 页面侧：往设置页 DOM 里插一行 ─────────────────────────────────────────

    /**
     * 注入脚本。三条纪律：
     *
     *  1. **幂等**：`window.__kdkit_settings_entry` 只置一次，重复注入直接返回；
     *  2. **只在自己是设置页时动手**：页面里出现 ≥2 个设置项文案才继续，别的页面零开销；
     *  3. **不改页面既有样式**：复制已有一行的节点（`cloneNode` 不复制监听器，所以点它
     *     不会触发原来那一行的事），只把它第一段文字换成「KdKit 模块设置」，其余节点原样保留
     *     （右侧箭头是字体图标，文字节点必须留着）。不设背景、不加 blur —— 上一轮已证实
     *     改背景会让某些页面白屏。
     */
    private fun script(): String = """
        (function () {
          if (window.__kdkit_settings_entry) { return; }
          var ROW_ID = 'kdkit-settings-row';
          var LABEL = '$ROW_LABEL';
          var MARKS = ['第三方信息共享清单', '个人信息收集清单', '撤回同意隐私政策',
                       '系统权限列表', '问题诊断', '图标设置'];
          function norm(s) { return (s || '').replace(/[\s\u00a0]+/g, ''); }
          function bodyText() { return (document.body && document.body.innerText) || ''; }
          function isSettingsPage() {
            var txt = bodyText(), hits = 0;
            for (var i = 0; i < MARKS.length; i++) { if (txt.indexOf(MARKS[i]) >= 0) { hits++; } }
            return hits >= 2;
          }
          /**
           * 固定在右下角的胶囊按钮 —— 不再 clone 列表行。
           *
           * 为什么改（2026-11-14 真机）：clone 出来的行会被 Vue 的 diff 重建冲掉，
           * 有时在、有时不在，点击热区也随列表滚动变化（同一个坐标两次点击落到不同行）。
           * 挂在 body 上、position:fixed 的按钮不受页面重渲染影响，点击面积也固定。
           */
          function insert() {
            if (document.getElementById(ROW_ID)) { return true; }
            if (!isSettingsPage()) { return false; }
            var btn = document.createElement('div');
            btn.id = ROW_ID;
            btn.textContent = LABEL;
            btn.style.cssText = [
              'position:fixed', 'right:16px', 'bottom:104px', 'z-index:2147483000',
              'padding:12px 18px', 'border-radius:22px', 'color:#fff',
              'background:linear-gradient(135deg,#5B6BC0,#7C6BE0)',
              'box-shadow:0 8px 22px rgba(20,24,40,.28)', 'font:500 14px/1.2 sans-serif',
              'letter-spacing:.02em', 'cursor:pointer', 'user-select:none',
              'backdrop-filter:blur(10px)', '-webkit-backdrop-filter:blur(10px)'
            ].join(';');
            btn.addEventListener('click', function (e) {
              e.preventDefault();
              e.stopPropagation();
              location.href = '$SCHEME';
            }, true);
            (document.body || document.documentElement).appendChild(btn);
            console.log('[KdKit] settings-entry button inserted');
            return true;
          }
          var tries = 0;
          function tick() {
            tries++;
            insert();
            if (tries < 40) { setTimeout(tick, 700); }
          }
          function start() {
            if (window.__kdkit_settings_entry) { return; }
            if (!isSettingsPage()) { return; }
            window.__kdkit_settings_entry = true;
            console.log('[KdKit] settings-entry: settings page detected');
            tick();
          }
          setTimeout(start, 400);
          setTimeout(start, 1500);
          setTimeout(start, 4000);
        })();
    """.trimIndent()
}