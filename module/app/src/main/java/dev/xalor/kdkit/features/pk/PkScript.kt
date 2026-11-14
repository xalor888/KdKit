package dev.xalor.kdkit.features.pk

/**
 * Userscript injected into the host's WebViews.
 *
 * 口算/语文/单词 PK lives in the `kd-pk` H5 app (pk-home.html -> pk-room.html). Its round state
 * keeps the correct answer for every question in the client:
 *
 *     questions[ownerIndex].answer      // 口算 answers are "<", ">" or "="
 *
 * so a fully reliable auto-answer is a matter of reading that field and activating the matching
 * option element. The script is deliberately DOM-shape agnostic: it locates the option by its
 * visible text instead of hard-coding component internals.
 */
object PkScript {

    fun build(mockMode: Boolean, autoAnswer: Boolean, answerDelayMs: Int = 180): String = """
(function () {
  if (window.__kdkit) {
    // 热开关：同一个页面里重新注入（关掉再打开）不该被这条 if 挡住 —— 只更新标志位。
    window.__kdkit.mockMode = $mockMode;
    window.__kdkit.autoAnswer = $autoAnswer;
    window.__kdkit.answerDelayMs = ${answerDelayMs.coerceIn(0, 5000)};
    return;
  }
  window.__kdkit = { version: '1.1', mockMode: $mockMode, autoAnswer: $autoAnswer, answerDelayMs: ${answerDelayMs.coerceIn(0, 5000)} };
  var LOG = function (m) { try { console.log('[KdKit] ' + m); } catch (e) {} };

  LOG('injected into ' + location.href);

  // ── optional: jump straight into the built-in practice match for verification ──
  if (window.__kdkit.mockMode && /\/kd-pk\//.test(location.href) && !/[?&]mock=/.test(location.href)) {
    var base = location.href.replace(/[?#].*$/, '').replace(/[^/]*$/, '');
    var u = base + 'pk-room.html?mock=1';
    LOG('entering mock match: ' + u);
    location.replace(u);
    return;
  }

  // ── locate the PK round state ──
  // Vue replaces #app on mount, so walk every element that carries a `__vue__` handle.
  function roots() {
    var out = [], seen = [];
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var v = all[i].__vue__;
      if (!v) continue;
      var r = v.${'$'}root || v;
      if (seen.indexOf(r) >= 0) continue;
      seen.push(r);
      out.push(r);
    }
    return out;
  }

  function findState() {
    var rs = roots(), seen = 0;
    for (var r = 0; r < rs.length; r++) {
      var stack = [rs[r]];
      while (stack.length && seen < 800) {
        var c = stack.shift(); seen++;
        if (!c) continue;
        var q = c.questions, idx = c.ownerIndex;
        if (q && typeof q.length === 'number' && q.length > 0 && typeof idx === 'number') {
          return { q: q, idx: idx, state: c.pageStatue, comp: c };
        }
        var ch = c.${'$'}children || [];
        for (var i = 0; i < ch.length; i++) stack.push(ch[i]);
      }
    }
    return null;
  }

  // ── drive the round through the component's own answer handler ──
  // The PK room exposes `checkResult(answer)` which compares the argument with the current
  // question's answer and advances the index. Calling it directly is independent of what the
  // game happens to have rendered.
  function findGame() {
    var rs = roots(), seen = 0;
    for (var r = 0; r < rs.length; r++) {
      var stack = [rs[r]];
      while (stack.length && seen < 900) {
        var c = stack.shift(); seen++;
        if (!c) continue;
        var q = c.questions, idx = c.ownerIndex;
        if (q && typeof q.length === 'number' && q.length > 0 &&
            typeof idx === 'number' && typeof c.checkResult === 'function') {
          return c;
        }
        var ch = c.${'$'}children || [];
        for (var i = 0; i < ch.length; i++) stack.push(ch[i]);
      }
    }
    return null;
  }

  function status(text) {
    try {
      var el = document.getElementById('kdkit-badge');
      if (!el) {
        el = document.createElement('div');
        el.id = 'kdkit-badge';
        el.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;' +
          'background:rgba(0,0,0,.62);color:#ffd24a;font:11px/1.5 -apple-system,sans-serif;' +
          'padding:2px 8px;border-radius:10px;pointer-events:none';
        (document.body || document.documentElement).appendChild(el);
      }
      el.textContent = text;
    } catch (e) {}
  }

  var answered = {}, lastIdx = -1;
  var timer = setInterval(function () {
    try {
      var c = findGame();
      if (!c) return;
      var q = c.questions, idx = c.ownerIndex;
      if (idx >= q.length) { status('KdKit · 已完成 ' + q.length + ' 题'); return; }
      var cur = q[idx];
      if (!cur) return;
      var answer = cur.answer;
      var key = idx + '|' + String(answer);
      if (idx !== lastIdx) {
        lastIdx = idx;
        LOG('Q' + idx + ': ' + (cur.questionLeft || '') + ' ? ' + (cur.questionRight || '') + ' => ' + answer);
      }
      status('KdKit · ' + idx + '/' + q.length + '  答案 ' + answer);
      if (!window.__kdkit.autoAnswer) return;
      if (answer === undefined || answer === null || answer === '') return;
      // 作答节奏：太快（同一 tick 连续提交）容易被判异常，延迟由配置给（默认 180ms）。
      var due = Date.now() + (window.__kdkit.answerDelayMs || 0);
      if (due > (window.__kdkit._notBefore || 0)) {
        window.__kdkit._notBefore = due;
        setTimeout(function () {
          try { if (window.__kdkit.autoAnswer) c.checkResult(answer); } catch (e) {}
        }, window.__kdkit.answerDelayMs || 0);
        return;
      }
      c.checkResult(answer);
    } catch (err) {
      if (!window.__kdkit_err) { window.__kdkit_err = 1; LOG('pk drive error: ' + (err && err.message ? err.message : err)); }
    }
  }, 250);

  function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }
  function isDisabled(el) {
    return el.disabled === true || el.getAttribute('aria-disabled') === 'true';
  }
})();
"""
}
