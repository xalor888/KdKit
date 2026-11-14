package dev.xalor.kdkit.features.web

import dev.xalor.kdkit.config.KdConfig

/** Ready-made userscripts contributed by features. */
object WebScripts {

    /** eruda: a mobile devtools console, loaded from the CDN the host already trusts. */
    fun debugConsole(): String = """
(function () {
  if (window.__kdkit_eruda) return;
  window.__kdkit_eruda = true;
  var s = document.createElement('script');
  s.src = 'https://static.kuaiduizuoye.com/product/eruda.min.js';
  s.onload = function () {
    try {
      if (window.eruda) { eruda.init(); console.log('[KdKit] eruda ready'); }
    } catch (e) {}
  };
  (document.head || document.documentElement).appendChild(s);
})();
"""

    /** 页面侧 XHR/fetch 记录：`shouldInterceptRequest` 看不到 POST body，只能在页面里包一层。
     *  记到 `console.log` —— Chromium 会把页面控制台透到 logcat（kit 侧可 grep），不额外占用桥通道。 */
    fun xhrRecorder(): String = """
(function () {
  if (window.__kdkit_xhrlog) return;
  window.__kdkit_xhrlog = true;
  function brief(v, n) { try { var s = (typeof v === 'string') ? v : JSON.stringify(v); return s ? s.slice(0, n) : ''; } catch (e) { return ''; } }
  var open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__kdm = m; this.__kdu = u; return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (b) {
    try { console.log('[KdKit] XHR ' + (this.__kdm || '?') + ' ' + String(this.__kdu).slice(0, 300) + ' body=' + brief(b, 900)); } catch (e) {}
    return send.apply(this, arguments);
  };
  if (window.EventSource) {
    var ES = window.EventSource;
    window.EventSource = function (u, c) {
      try { console.log('[KdKit] SSE ' + String(u).slice(0, 400)); } catch (e) {}
      return new ES(u, c);
    };
    window.EventSource.prototype = ES.prototype;
  }
  if (window.fetch) {
    var f = window.fetch;
    window.fetch = function (input, init) {
      try {
        var u = (typeof input === 'string') ? input : (input && input.url) || '';
        console.log('[KdKit] FETCH ' + ((init && init.method) || 'GET') + ' ' + String(u).slice(0, 300) + ' body=' + brief(init && init.body, 900));
      } catch (e) {}
      return f.apply(this, arguments);
    };
  }
  console.log('[KdKit] xhr recorder ready');
})();
"""

    fun enabled(): List<Pair<String, () -> String>> = buildList {
        if (KdConfig.isOn("h5_debug", false)) add("eruda" to ::debugConsole)
    }
}
