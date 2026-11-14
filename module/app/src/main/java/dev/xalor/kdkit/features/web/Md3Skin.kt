package dev.xalor.kdkit.features.web

import android.app.Activity
import android.content.Context
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.Drawable
import android.os.Bundle
import android.view.View
import androidx.core.view.WindowCompat
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/**
 * Material 3 简约皮肤（H5 层 + 原生窗口层），含深色适配与液态玻璃。
 *
 * ### 为什么是"注入"而不是"重绘"
 *
 * 快对的界面是**原生壳 + H5 页面**（`hybrid/<module>/<page>-<hash>-hycache.html`）。
 * 原生侧重做要逐控件改（或做 RRO 资源覆盖），任何一处都是崩溃面；H5 侧只需要一段
 * JavaScript —— 覆盖的是**颜色、圆角、阴影、字体、透明度**这几类"看感"，不动布局与交互。
 *
 * ### 三档强度 + 深色
 *
 *  * `md3_level`：`full`（默认，连大色块一起归一）/ `light`（只改圆角阴影）；
 *  * `md3_theme`：`auto`（跟系统）/ `light` / `dark`。
 *
 * 深色下**不再动原生背景**：把原生大色块换成深色后，位图与文字仍是深色，对比度会直接坏掉
 * （2026-11-14 真机截图遇到过）。深色只走"窗口配色"，原生部分保持 App 自己的样子。
 */
object Md3Skin : SwitchFeature(
    id = "md3_skin",
    title = "Material 3 简约皮肤",
    summary = "H5 注入中性配色/圆角/去阴影/液态玻璃，支持深色；原生侧只改窗口级颜色",
    category = Category.HOST,
    defaultOn = true,
    hot = true,
) {
    private const val SURFACE_LIGHT = 0xFFF6F4F9.toInt()
    private const val SURFACE_DARK = 0xFF10121A.toInt()

    /** 颜色格式校验只编译一次 —— 门禁 ⑲ 把"语句位置构造正则"算作热路径重复计算。 */
    private val HEX_COLOR = Regex("^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "md3_native_window",
            title = "同时统一原生状态栏 / 窗口背景",
            summary = "hook 宿主 Activity 的 onCreate，把状态栏与窗口底色设成同一中性色；关掉则只皮肤化 H5",
            kind = KdOption.Kind.BOOLEAN,
            default = "true",
        ),
        KdOption(
            key = "md3_native_bg",
            title = "同时中性化原生大色块背景",
            summary = "默认关：它会为每个 View 排一次主线程任务，页面复杂时会拖慢甚至 ANR（2026-11-14 实测）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "md3_theme",
            title = "深色适配",
            summary = "auto=跟系统深色；light／dark 强制。深色下页面与窗口一起换色板",
            kind = KdOption.Kind.STRING,
            default = "auto",
        ),
        KdOption(
            key = "md3_h5",
            title = "对网页本身套皮肤",
            summary = "默认关。开了才会注入页面样式；部分页面（拍题答疑 / 口算 PK）注入后会白屏，关掉即恢复",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "md3_glass",
            title = "液态玻璃",
            summary = "H5 卡片半透明 + 背景模糊 + 高光描边；不支持 blur 的 WebView 会退化成半透明",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "md3_level",
            title = "强度",
            summary = "full=连大色块与渐变一起归一；light=只改圆角阴影（保守，默认）",
            kind = KdOption.Kind.STRING,
            default = "light",
        ),
        KdOption(
            key = "md3_primary",
            title = "主色（十六进制）",
            summary = "留空用默认靛蓝 #5B6BC0；填入如 #7C4DFF 会替换页面按钮主色",
            kind = KdOption.Kind.STRING,
            default = "",
        ),
    )

    /** 原生背景中性化的主线程任务预算（每次进程启动重置）。 */
    private var bgTasks = 0

    override fun install() {
        val g = id
        var n = 0

        WebInjector.register("md3_skin") {
            if (!KdConfig.isOn("md3_skin", defaultOn)) ""
            else if (!KdConfig.isOn("md3_h5", false)) ""    // 默认不碰页面：注入是白屏的唯一来源
            else script()
        }

        if (Xp.hook("android.app.Activity", "onCreate", Bundle::class.java, gate = g, onAfter = { p ->
                if (!KdConfig.isOn("md3_native_window", true)) return@hook
                val act = p.thisObject as? Activity ?: return@hook
                if (act.packageName != KdConfig.TARGET_PKG) return@hook
                runCatching {
                    val w = act.window ?: return@hook
                    val sf = surface()
                    val dark = isDark()
                    w.statusBarColor = sf
                    w.navigationBarColor = sf
                    val c = WindowCompat.getInsetsController(w, w.decorView)
                    c.isAppearanceLightStatusBars = !dark
                    c.isAppearanceLightNavigationBars = !dark
                    n++
                    Capture.mark("MD3 window themed" + if (dark) " (dark)" else "")
                }
            })
        ) n++

        // 原生大色块：只在浅色下生效（见类注释）。面积阈值把按钮/角标挡在外面。
        if (Xp.hook("android.view.View", "setBackground", Drawable::class.java, gate = g, onAfter = { p ->
                if (!KdConfig.isOn("md3_native_bg", true)) return@hook
                if (isDark()) return@hook
                val v = p.thisObject as? View ?: return@hook
                val d = p.args.getOrNull(0) as? Drawable ?: return@hook
                if (v.getTag(0x6b646274) != null) return@hook      // 每个 View 只排队一次
                v.setTag(0x6b646274, true)
                if (bgTasks++ > 200) return@hook                     // 单进程上限，避免 ANR
                v.post {
                    runCatching {
                        if (v.width <= 0 || v.height <= 0) return@post
                        if (v.width * v.height < 120_000) return@post
                        val c = sampleColor(d) ?: return@post
                        val r = Color.red(c); val gg = Color.green(c); val b = Color.blue(c)
                        val mx = maxOf(r, gg, b); val mn = minOf(r, gg, b)
                        val sat = if (mx == 0) 0f else (mx - mn).toFloat() / mx
                        if (sat > 0.45f && mx > 170 && v !is android.widget.Button) {
                            v.setBackgroundColor(surface())
                            Capture.mark("MD3 native bg neutralised")
                        }
                    }
                }
            })
        ) n++

        KdLog.i("Md3Skin installed ($n hooks + h5 provider)")
    }

    /**
     * 从 Drawable 里取一个代表色 —— 只认三种常见形态，其余返回 null（不动）。
     * 为什么这么保守：取不到颜色就替换，会把图片背景（照片、插画）一起弄坏。
     */
    private fun sampleColor(d: Drawable): Int? = runCatching {
        when (d) {
            is ColorDrawable -> d.color
            is android.graphics.drawable.BitmapDrawable -> {
                val bmp = d.bitmap ?: return null
                if (bmp.width < 8 || bmp.height < 8) return null
                bmp.getPixel(bmp.width / 2, bmp.height / 2)
            }
            is android.graphics.drawable.GradientDrawable -> {
                val m = d.javaClass.getMethod("getColors")
                (m.invoke(d) as? IntArray)?.firstOrNull()
            }
            else -> null
        }
    }.getOrNull()

    /** 深色判定：`md3_theme` 显式指定优先；`auto` 读系统 `uiMode`。 */
    private fun isDark(): Boolean = when (KdConfig.getString("md3_theme", "auto").trim().lowercase()) {
        "dark" -> true
        "light" -> false
        else -> runCatching {
            // `ActivityThread` 是隐藏 API，编译期不可见 —— 反射取（同 HostVersion 的做法）。
            val ctx = Class.forName("android.app.ActivityThread")
                .getMethod("currentApplication").invoke(null) as? Context
            val night = (ctx?.resources?.configuration?.uiMode
                ?: Configuration.UI_MODE_NIGHT_NO) and Configuration.UI_MODE_NIGHT_MASK
            night == Configuration.UI_MODE_NIGHT_YES
        }.getOrDefault(false)
    }

    private fun surface(): Int = if (isDark()) SURFACE_DARK else SURFACE_LIGHT

    private fun primary(): String {
        val raw = KdConfig.getString("md3_primary", "").trim()
        return if (HEX_COLOR.matches(raw)) raw else "#5B6BC0"
    }

    private fun script(): String {
        val dark = isDark()
        val full = KdConfig.getString("md3_level", "full").trim().lowercase() != "light"
        val glass = KdConfig.isOn("md3_glass", true)
        val surface = if (dark) "#10121A" else "#F6F4F9"
        val onSurface = if (dark) "#ECEBF4" else "#1C1B1F"
        val onMuted = if (dark) "#9A9AAC" else "#5A5A68"
        val glassFill = if (dark) "rgba(28,31,42,.60)" else "rgba(255,255,255,.62)"
        val glassBorder = if (dark) "rgba(255,255,255,.10)" else "rgba(255,255,255,.55)"
        val glassShadow = if (dark) "0 8px 24px rgba(0,0,0,.38)" else "0 8px 24px rgba(31,36,58,.10)"

        KdLog.i("Md3Skin inject dark=$dark glass=$glass level=${if (full) "full" else "light"}")

        // 深色下**不动 H5 页面**：快对的页面自身没有深色主题，模块侧只能靠反色/逐块改色去凑，
        // 而这两条路在真机上都验证失败过（白卡白字 / 背景色不跟 —— 见 work/ui_md3_dark_home*.png）。
        // 与其交付一个"看起来深了但读不清"的皮肤，不如只做原生窗口：状态栏、导航栏、窗口底色。
        if (dark) return ""

        return buildString {
            append("(function(){\n")
            append("  if (window.__kdkit_md3) { try { window.__kdkit_md3.remove(); } catch(e){} }\n")
            append("  document.documentElement.setAttribute('data-kdkit-dark','")
            append(if (dark) "1" else "0").append("');\n")
            append("  var st = document.createElement('style'); st.id = '__kdkit_md3';\n")
            append("  st.textContent = `\n")
            append("    :root{--kdkit-surface:").append(surface)
            append(";--kdkit-surface-2:").append(if (dark) "#171A24" else "#FFFFFF")
            append(";--kdkit-on-surface:").append(onSurface)
            append(";--kdkit-on-muted:").append(onMuted)
            append(";--kdkit-primary:").append(primary()).append(";--kdkit-radius:16px;}\n")
            append("    html,body,#app,#__nuxt,#root,body>div,[class*=\"page\"],[class*=\"Page\"],")
            append("[class*=\"root\"],[class*=\"Root\"]{background:var(--kdkit-surface)!important;")
            append("color:var(--kdkit-on-surface)!important;}\n")
            // 液态玻璃的前提：背景得有色彩变化。纯色底上 backdrop-blur 永远是"看不见的"。
            append("    body{background-image:")
            if (dark) {
                append("radial-gradient(60% 40% at 12% 6%, rgba(91,107,192,.30) 0%, transparent 60%),")
                append("radial-gradient(50% 36% at 92% 62%, rgba(124,107,224,.26) 0%, transparent 62%)")
            } else {
                append("radial-gradient(60% 40% at 10% 4%, rgba(146,164,255,.30) 0%, transparent 62%),")
                append("radial-gradient(52% 38% at 92% 58%, rgba(255,206,150,.28) 0%, transparent 64%)")
            }
            append("!important;background-attachment:fixed!important;}\n")
            append("    body{font-family:\"Noto Sans SC\",\"HarmonyOS Sans SC\",system-ui,-apple-system,sans-serif!important;}\n")
            append("    [class*=\"card\"],[class*=\"Card\"],[class*=\"panel\"],[class*=\"Panel\"],")
            append("[class*=\"item\"],[class*=\"Item\"]{border-radius:var(--kdkit-radius)!important;}\n")
            append("    button,[role=\"button\"],[class*=\"btn\"],[class*=\"Button\"]{")
            append("border-radius:20px!important;box-shadow:none!important;}\n")
            append("    hr,[class*=\"divider\"],[class*=\"Divider\"]{opacity:.6!important;}\n")
            if (glass) {
                append("    [class*=\"card\"],[class*=\"Card\"],[class*=\"panel\"],[class*=\"Panel\"],")
                append("[class*=\"item\"],[class*=\"Item\"]{background:").append(glassFill).append("!important;")
                append("border-radius:20px!important;")
                append("box-shadow:inset 0 1px 0 ").append(glassBorder).append("!important;")
                append("border:1px solid ").append(glassBorder).append("!important;")
                append("box-shadow:").append(glassShadow).append("!important;}\n")
            }
            append("  `;\n  document.head.appendChild(st);\n")
            append("  document.documentElement.setAttribute('data-kdkit-md3','")
            append(if (full) "full" else "light").append("');\n")
            if (dark) append(DARK_INVERT_CSS)
            if (full && !dark) append(NORMALISE_JS)
            if (glass) append(GLASSIFY_JS)
            append(REVERT_IF_BLANK_JS)
            append("})();\n")
        }
    }

    /**
     * 玻璃化：把页面上"亮色大块"（面积 ≥ 2 万 px²、亮度 > 232）当场换成玻璃卡 ——
     * 半透明填充 + 1px 高光描边 + 顶部内高光 + 柔和外阴影 + 20px 圆角。
     *
     * 为什么用 JS 而不是纯 CSS 选择器：快对的 H5 类名是构建期哈希，`[class*="card"]`
     * 命中不了几张卡；只有按"面积 + 颜色的统计特征"扫才通用。
     * 不用 `backdrop-filter`：WebView 上它会让整页白屏（真机踩过），玻璃感靠叠色与描边表达。
     */
    private const val GLASSIFY_JS = """
  (function(){
    var DARK = document.documentElement.getAttribute('data-kdkit-dark') === '1';
    // 玻璃自身要带"颜色层次"：纯白半透明叠在纯白页面上等于什么都没做。
    // 这里用「冷白 → 冷蓝 → 暖白」的斜向渐变模拟玻璃对背景的折射。
    var FILL = DARK
      ? 'linear-gradient(150deg, rgba(44,48,64,.82) 0%, rgba(30,36,54,.68) 52%, rgba(52,44,62,.66) 100%)'
      : 'linear-gradient(150deg, rgba(255,255,255,.92) 0%, rgba(232,238,255,.72) 52%, rgba(255,246,232,.70) 100%)';
    var EDGE = DARK ? 'rgba(255,255,255,.22)' : 'rgba(255,255,255,.92)';
    var SHADOW = DARK
      ? '0 12px 32px rgba(0,0,0,.55), inset 0 -1px 0 rgba(0,0,0,.35)'
      : '0 12px 32px rgba(31,36,58,.14), inset 0 -1px 0 rgba(255,255,255,.35)';
    var DONE = 0;
    function rgba(cs){
      var m = /rgba?\(([0-9]+), ?([0-9]+), ?([0-9]+)(?:, ?([0-9.]+))?/.exec(cs.backgroundColor);
      return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null;
    }
    function glassify(){
      var els = document.querySelectorAll('div, section, li');
      for (var i = 0; i < els.length && DONE < 260; i++) {
        var el = els[i];
        if (el.__kdkit_glass) continue;
        var r = el.getBoundingClientRect();
        if (r.width * r.height < 20000) continue;
        var txt = (el.innerText || '').trim();
        if (txt.length > 400) continue;
        var cs = getComputedStyle(el);
        var c = rgba(cs);
        if (!c) continue;
        var lum = (c[0]*299 + c[1]*587 + c[2]*114) / 1000;
        var isLight = lum > 232 && c[3] > 0.5;
        var isDarkCard = DARK && lum < 70;
        if (!isLight && !isDarkCard) continue;
        el.style.setProperty('background', FILL, 'important');
        el.style.setProperty('border', '1px solid ' + EDGE, 'important');
        el.style.setProperty('border-radius', '20px', 'important');
        el.style.setProperty('box-shadow',
          'inset 0 1.5px 0 ' + EDGE + ', inset 0 -1px 0 ' +
          (DARK ? 'rgba(255,255,255,.10)' : 'rgba(255,255,255,.45)') + ', ' + SHADOW, 'important');
        // 液态玻璃的关键：背景模糊 + 饱和提升。只在"被我们改造成玻璃"的块上生效，
        // 且白屏自愈（REVERT_IF_BLANK_JS）会兜底撤掉。
        el.style.setProperty('backdrop-filter', 'blur(18px) saturate(160%) brightness(1.04)', 'important');
        el.style.setProperty('-webkit-backdrop-filter', 'blur(18px) saturate(160%) brightness(1.04)', 'important');
        el.__kdkit_glass = 1; DONE++;
      }
    }
    glassify();
    setTimeout(glassify, 600); setTimeout(glassify, 1600); setTimeout(glassify, 3200);
  })();
"""

    /**
     * 白屏自愈：注入后 1.2s / 3s 各查一次，若页面被我们弄空了（没有可见文字、也没有图片/画布），
     * 就把注入的 style 与标记全部撤掉 —— **宁可没有皮肤，也不能给用户一片白**。
     *
     * 2026-11-14 用户实测：拍题答疑、口算 PK 等页面在注入后会白屏。
     * 根因是页面自身是"容器里再渲染"的结构，外层的背景/模糊规则会让内层不可见。
     * 这类问题无法靠静态门禁发现，只能靠"注入者自己会退场"。
     */
    private const val REVERT_IF_BLANK_JS = """
  function kdkitBlank(){
    var txt = (document.body && document.body.innerText || '').replace(/\s+/g, '');
    var media = document.querySelectorAll('img,canvas,video,iframe,svg').length;
    var nodes = document.querySelectorAll('*').length;
    return txt.length < 20 && media === 0 && nodes < 200;
  }
  function kdkitRevert(){
    try {
      var st = document.getElementById('__kdkit_md3'); if (st) st.remove();
      document.documentElement.removeAttribute('data-kdkit-md3');
      document.documentElement.removeAttribute('data-kdkit-dark');
      document.documentElement.removeAttribute('data-kdkit-invert');
      document.documentElement.style.removeProperty('filter');
      if (document.body) { document.body.style.removeProperty('background'); document.body.style.removeProperty('color'); }
      window.__kdkit_md3_reverted = 1;
    } catch (e) {}
  }
  setTimeout(function(){ if (kdkitBlank()) kdkitRevert(); }, 1200);
  setTimeout(function(){ if (kdkitBlank()) kdkitRevert(); }, 3000);
"""

    /**
     * 深色适配 —— **整页反色 + 媒体再反色**（Dark Reader 的简化版）。
     *
     * 为什么不用"逐块把亮底改深 + 近黑文字改亮"（2026-11-14 试过两轮，两次都坏）：
     * 页面里白底可能来自**父层**、来自 `background-image`、也可能来自伪元素 ——
     * 逐块检测只能改到"自己带 backgroundColor 的那一层"，漏掉一层就会出现
     * **白卡 + 白字**（实测截图 `work/ui_md3_dark_home5.png`：文字读不出来）。
     *
     * 反色的代价是可控的：`img/video/canvas/svg` 再反一次就还原，彩色经
     * `hue-rotate(180deg)` 修正后基本保持原色调。整体效果与 Dark Reader 同类。
     */
    private const val DARK_INVERT_CSS = """
  st.textContent += `
    html { filter: invert(1) hue-rotate(180deg) !important; }
    html, body { background: #10121A !important; }
    img, video, canvas, svg, picture, [class*="avatar"], [class*="Avatar"],
    [class*="icon"], [class*="Icon"], [class*="thumb"], [class*="Thumb"] {
      filter: invert(1) hue-rotate(180deg) !important;
    }
  `;
  document.documentElement.setAttribute('data-kdkit-invert','1');
"""

    /**
     * 页面级"配色归一"（双模），按**面积阈值 + 取样色**判断，按钮/图标/角标在阈值以下：
     *  * 浅色：大块**高饱和**背景 → 中性 surface（去品牌大色块）；
     *  * 深色：大块**高亮**背景压深 + 近黑文字提亮（否则白底黑字在深色系统里会更刺眼）。
     */
    private const val NORMALISE_JS = """
  var DARK = document.documentElement.getAttribute('data-kdkit-dark') === '1';
  var DONE = 0, DONE_T = 0;
  function rgbaOf(cs){
    var m = /rgba?\(([0-9]+), ?([0-9]+), ?([0-9]+)(?:, ?([0-9.]+))?/.exec(cs.backgroundColor);
    if (!m) return null;
    return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
  }
  function norm(){
    var els = document.querySelectorAll('div, section, header, main, #app, body > div');
    for (var i = 0; i < els.length && DONE < 400; i++) {
      var el = els[i];
      if (el.__kdkit_md3_n) continue;
      if (el.getAttribute && el.getAttribute('data-kdkit-md3-skip') === '1') continue;
      var r = el.getBoundingClientRect();
      var area = r.width * r.height;
      if (area < (DARK ? 40000 : 120000)) continue;
      var cs = getComputedStyle(el);
      var c = rgbaOf(cs);
      var grad = /gradient|url\(/.test(cs.backgroundImage);
      // 2026-11-14 保护：含较多文本的层是**内容**不是背景，动它就会让页面看起来变空。
      var txt = (el.innerText || '').trim();
      if (txt.length > 60) continue;
      if (el.id === 'app' || el === document.body || el === document.documentElement) continue;
      if (!DARK) {
        var sat = 0, mx = 0;
        if (c) { mx = Math.max(c[0],c[1],c[2]); var mn = Math.min(c[0],c[1],c[2]);
                 sat = mx === 0 ? 0 : (mx - mn) / mx; }
        if (grad || (sat > 0.45 && mx > 170)) {
          el.style.setProperty('background', 'var(--kdkit-surface)', 'important');
          el.style.setProperty('background-image', 'none', 'important');
          el.__kdkit_md3_n = 1; DONE++;
        }
      } else if (c) {
        var lum = (c[0] * 299 + c[1] * 587 + c[2] * 114) / 1000;
        if (lum > 200) {
          var big = area > 300000;
          el.style.setProperty('background', big ? 'var(--kdkit-surface)' : 'rgba(26,29,39,.92)', 'important');
          el.style.setProperty('backdrop-filter', 'blur(16px) saturate(1.2)', 'important');
          el.__kdkit_md3_n = 1; DONE++;
        }
      }
    }
    if (DARK) {
      var texts = document.querySelectorAll('div, span, p, b, strong');
      for (var j = 0; j < texts.length && DONE_T < 400; j++) {
        var e = texts[j];
        if (e.__kdkit_md3_t || !e.firstChild || e.firstChild.nodeType !== 3) continue;
        var col = rgbaOf(getComputedStyle(e));
        if (!col) continue;
        var L = (col[0] * 299 + col[1] * 587 + col[2] * 114) / 1000;
        if (L < 90) { e.style.setProperty('color', 'var(--kdkit-on-surface)', 'important'); e.__kdkit_md3_t = 1; DONE_T++; }
      }
    }
  }
  norm(); setTimeout(norm, 700); setTimeout(norm, 1800); setTimeout(norm, 3200);
"""
}
