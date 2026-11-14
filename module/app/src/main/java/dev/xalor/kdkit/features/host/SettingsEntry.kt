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
          // 只在设置页留下一条痕迹，方便真机排障：console 输出会进 logcat 的 chromium 通道
          if (window.__kdkit_settings_entry) { return; }
          window.__kdkit_settings_entry = 1;
          var ROW_ID = 'kdkit-settings-row';
          var LABEL = '$ROW_LABEL';
          var MARKS = ['检查新版本', '第三方信息共享清单', '个人信息收集清单',
                       '撤回同意隐私政策', '系统权限列表', '问题诊断', '图标设置'];
          function norm(s) { return (s || '').replace(/[\s\u00a0]+/g, ''); }

          /**
           * 这是不是「设置」页。
           *
           * **绝不用 innerText**：它会强制一次同步布局（reflow）。以前 observer 每触发一次就
           * 调一次 innerText，拍题页/详情页那种高频改 DOM 的页面每秒能触发上百次
           * ⇒ WebView 主线程被 reflow 打满 ⇒ **从子页面返回直接卡死**（2026-11-14 事故）。
           * textContent 只读已有文本节点，不触发布局。
           */
          function looksLikeSettings() {
            var b = document.body;
            if (!b) { return false; }
            var t = b.textContent || '';
            var hits = 0;
            for (var i = 0; i < MARKS.length; i++) { if (t.indexOf(MARKS[i]) >= 0) { hits++; } }
            return hits >= 2;
          }
          /** URL 判据最便宜：设置页是 `zyb://app-vue/page/newSetUp`。 */
          function urlSaysSettings() {
            var u = location.href || '';
            return u.indexOf('newSetUp') >= 0;
          }
          function isSettingsPage() { return urlSaysSettings() || looksLikeSettings(); }

          /**
           * 找"文案正好是 t"的最深元素。
           *
           * 原来只接受 `children.length <= 2`：快对的设置行是「图标 + 文案 + 右箭头」三个子节点，
           * 于是永远匹配不到，行就插不进去（2026-11-15 在模拟器上实测：注入成功但行不出现）。
           * 现在放宽到 8 个子节点，并额外要求整块文本长度接近 t（避免把整页容器当命中）。
           */
          function leafByText(t) {
            var all = document.getElementsByTagName('*');
            var want = norm(t);
            var best = null;
            for (var i = 0; i < all.length; i++) {
              var el = all[i];
              if (el.children.length > 8) { continue; }
              var txt = norm(el.textContent);
              if (txt === want) { return el; }               // 精确命中直接返回
              if (!best && txt.length > want.length && txt.length < want.length + 6 &&
                  txt.indexOf(want) === 0) { best = el; }   // 允许"文案 + 箭头字符"
            }
            return best;
          }

          /** 复制相邻设置行（同一套 class / 内边距 / 右侧箭头），只把文字换掉。 */
          function insert() {
            if (!isSettingsPage()) { console.log('[KdKit] insert: not settings'); return false; }
            var anchor = null;
            for (var i = 0; i < MARKS.length && !anchor; i++) { anchor = leafByText(MARKS[i]); }
            if (!anchor) { console.log('[KdKit] insert: no anchor'); return false; }
            /**
             * 从文案元素往上走，直到"整行的宽度"（≥ 视口 70%）。
             *
             * 原来的条件是"父元素文本和文案完全相同" —— 快对设置行是
             * 「图标 + 文案 + 右箭头」，父元素文本里还带箭头字符，条件永远不成立，
             * 于是只克隆了文案那个 300px 宽的小块（2026-11-15 模拟器实测：
             * 行确实插进去了，但只有"KdKit 模块设置"几个字，没有整行热区）。
             */
            var row = anchor;
            var viewportW = document.documentElement.clientWidth || 360;
            while (row.parentNode) {
              var rect = row.getBoundingClientRect();
              if (rect.width >= viewportW * 0.7) { break; }
              row = row.parentNode;
            }
            var mine = row.cloneNode(true);
            mine.id = ROW_ID;
            mine.style.cursor = 'pointer';
            mine.style.width = '100%';
            var nodes = [];
            var walker = document.createTreeWalker(mine, NodeFilter.SHOW_TEXT, null, false);
            while (walker.nextNode()) { nodes.push(walker.currentNode); }
            var replaced = false;
            for (var i = 0; i < nodes.length; i++) {
              if (norm(nodes[i].nodeValue) === norm(anchor.textContent)) {
                nodes[i].nodeValue = LABEL; replaced = true; break;
              }
            }
            if (!replaced) { mine.insertBefore(document.createTextNode(LABEL), mine.firstChild); }
            // Vue 会重建 DOM，所以用 pointerdown + click 双绑（capture 阶段，先于框架处理）
            var go = function (e) {
              e.preventDefault(); e.stopPropagation();
              location.href = '$SCHEME';
            };
            mine.addEventListener('pointerdown', go, true);
            mine.addEventListener('click', go, true);
            if (row.parentNode) { row.parentNode.insertBefore(mine, row.nextSibling); }
            console.log('[KdKit] insert: row added, parent=' + (row.parentNode && row.parentNode.tagName));
            return true;
          }

          /* ── 重插：observer 只挂在「确认是设置页」的时候，且带冷却 ────────── */
          var lastRun = -1e9;   // 保证第一次一定不被冷却挡掉
          var pending = false;
          function ensure() {
            if (document.getElementById(ROW_ID)) { return; }   // 最便宜的一步，已存在就收工
            var now = (window.performance && performance.now) ? performance.now() : Date.now();
            if (now - lastRun < 800) { return; }
            lastRun = now;
            insert();
          }
          function schedule() {
            if (pending) { return; }
            pending = true;
            var raf = window.requestAnimationFrame || function (f) { return setTimeout(f, 16); };
            raf(function () { pending = false; ensure(); });
          }

          var armed = false;
          function arm() {
            if (armed) { return; }
            armed = true;
            ensure();
            try {
              new MutationObserver(function () {
                // 行还在就立刻返回（一次 getElementById，不触发布局）
                if (document.getElementById(ROW_ID)) { return; }
                schedule();
              }).observe(document.body, { childList: true, subtree: true });
            } catch (e) {}
          }

          /**
           * 只有设置页才挂 observer。别的页面（拍题、详情、答题）**一次都不挂** ——
           * 这是"返回必卡死"的根治手段：不再有跨页面的常驻观察者。
           */
          var tries = 0;
          function boot() {
            if (urlSaysSettings() || looksLikeSettings()) { arm(); return; }
            if (++tries < 8) { setTimeout(boot, 600); }
          }
          setTimeout(boot, 300);
          // 兜底：observer 万一没挂上（body 被替换等），这两个定时器仍会把行插进去
          setTimeout(ensure, 900);
          setTimeout(ensure, 2200);
        })();
    """.trimIndent()
}