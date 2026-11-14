#!/usr/bin/env python3
"""
Offline test: the three hook gates must see **the same** targets.

Why this file exists
--------------------
④ `check_hook_targets.py`、⑤ `check_hook_signatures.py`、⑥ `check_hook_callers.py`
各有一份"从 Kotlin 源码里找出钩子目标"的正则。2026-10-25 实测它们的清单**互不相同**：

   ④ 73 条（含 `clazzOrNull` 纯类引用）
   ⑤ 48 条  —— 看不到 `Xp.hookAll*(`，也看不到 const 类名（`Xp.hook(CLS, "b", …)`）
   ⑥ 48 条  —— 连 `ExitGuard` 自写的 `hookAll("类", "方法")` 包装也看不到

后果不是"少报几条"，而是**功能被显示成没有证据**：`VERIFICATION.md` 的「静态钩子」列
对 7 个功能显示 `-`，读起来像"这些功能没有静态依据"，实际是"门禁没看它们"。

本测试把"三份清单必须相等"变成断言，任何一份再演一套正则都会立刻红。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import os
import re
from pathlib import Path
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCRIPTS = os.path.join(ROOT, 'kit', 'scripts')
MODULE = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit')

sys.path.insert(0, SCRIPTS)


class GatesAgree(unittest.TestCase):
    """④⑤⑥ 必须看到同一批 (类, 方法)。"""

    def setUp(self):
        if not os.path.isdir(SCRIPTS):
            self.skipTest(f'找不到 {SCRIPTS}')
        import check_hook_targets
        import check_hook_signatures
        import check_hook_callers
        self.t = check_hook_targets
        self.s = check_hook_signatures
        self.c = check_hook_callers

    def targets(self):
        """④ 的目标里**有方法名**的那些（`clazzOrNull` 只有类，没有方法可判）。"""
        return {(cls, meth) for cls, meth, _w in self.t.collect_targets(MODULE) if meth}

    def signatures(self):
        return {(r['class'], r['method']) for r in self.s.collect(MODULE)}

    def callers(self):
        return {(cls, meth) for cls, meth, _w in self.c.hook_targets(MODULE)}

    # ④ 能展开、⑤ 结构上展开不了的形态。**每一条都要有确定的理由**，
    # 不许为了让门禁变绿而往里塞东西。
    # 这里**曾经**有 6 条例外（`android.util.Log` 的 v/d/i/w/e/wtf）：④ 能展开
    # `for (m in listOf(…)) Xp.hookAll("android.util.Log", m, …)`，⑤ 不做循环展开。
    # 2026-10-25 第 11 轮给了 ⑤ 同样的作用域展开（`hook_vocab.loop_scopes` + `ALL_VAR_RE`），
    # 缺口从 6 条变成 0 条 ⇒ 例外清单删空。
    #
    # 保留这个空集合而不是删掉整套机制：将来若再出现"某一层结构性看不到"的情形，
    # 它必须显式登记并配上自我检查（`test_structural_exceptions_are_real`），
    # 而不是悄悄放宽断言。
    STRUCTURAL_EXCEPTIONS = set()  # (类, 方法) 精确匹配

    def test_signature_gate_sees_every_target(self):
        missing = sorted(
            t for t in (self.targets() - self.signatures())
            if t not in self.STRUCTURAL_EXCEPTIONS)
        self.assertEqual(missing, [],
                         '⑤ 看不到 ④ 的这些目标（签名因此从未被校验过）：' + str(missing))

    def test_structural_exceptions_are_real(self):
        """例外清单必须真有用：那对 (类,方法) 确实被 ④ 看到。

        否则有人删了循环展开后，例外会一直躺着掩盖新出现的真缺口 —— 这正是
        上一轮 `Log.*` 那 6 条例外的下场：第 11 轮补齐 ⑤ 的作用域展开后，
        缺口变成 0，例外就成了纯噪声（现已删空）。
        """
        for pair in sorted(self.STRUCTURAL_EXCEPTIONS):
            with self.subTest(target=f'{pair[0]}.{pair[1]}'):
                self.assertIn(pair, self.targets(),
                              f'{pair} 不在 ④ 的目标里 —— 例外已过期，删掉')
        # **不**断言 "⑤ 里没有它"：`check_hook_signatures` 在模块级缓存了扫描结果，
        # 别的测试若先导入并跑过（例如 doc_generators 会调它的 CLI），缓存里可能已经
        # 包含这些目标 —— 那样这里会因为**执行顺序**而红，与代码无关。

    def test_no_gap_between_targets_and_signatures(self):
        """④ 与 ⑤ 的目标集合必须**完全相等**（除显式例外）。

        这条比 `test_signature_gate_sees_every_target` 更强：后者只在"缺了且不在例外里"
        时报红，于是一旦某处悄悄往例外里加一条，断言就永远绿。这里直接算差集，
        并把例外显式减掉 —— 想让缺口通过，必须改这个文件（留下 diff）。
        """
        gap = self.targets() - self.signatures() - self.STRUCTURAL_EXCEPTIONS
        self.assertEqual(sorted(gap), [],
                         f'④ 有 {len(gap)} 个目标 ⑤ 看不到（签名从未被校验）：' + str(sorted(gap)))

    def test_signature_gate_invents_nothing(self):
        extra = sorted(self.signatures() - self.targets())
        self.assertEqual(extra, [],
                         '⑤ 报了 ④ 没有的目标（多半是把运行时类名当成了静态类名）：' + str(extra))

    def test_caller_gate_sees_every_target(self):
        self.assertEqual(sorted(self.targets() - self.callers()), [],
                         '⑥ 看不到这些目标（它们因此从未被判过 DEAD）')

    def test_caller_gate_invents_nothing(self):
        self.assertEqual(sorted(self.callers() - self.targets()), [],
                         '⑥ 报了 ④ 没有的目标')

    def test_minimum_coverage(self):
        """数量下限：防止某次重构把三条正则同时改窄、而三者"一致地"都变少。

        26 条是 2026-10-25 之前的真实值；现在的数字只会更大。写死下限而不是精确值，
        是因为加钩子不该让测试变红 —— 但**丢**一批钩子必须红。
        """
        n = len(self.targets())
        self.assertGreaterEqual(n, 45, f'只剩 {n} 个目标，疑似三条正则同时改窄了')


class HookAllAndWrapersReach(unittest.TestCase):
    """几类**曾经完全逃掉**的钩子形态，各自必须能被看到。

    每一条都对应一次真实漏检，不是假想：
      * `hookAllBefore`  —— `BridgeGuard` / `H5BridgeLog` / `ReqHeaders` 用它
      * const 类名       —— `Xp.hook(CLS, "b", …)`（`VipLimitProbe` / `RouteLog` / `RC4Probe`）
      * 局部 hookAll 包装 —— `ExitGuard` 的 `hookAll("java.lang.System", "exit")`
    """

    def setUp(self):
        import check_hook_targets
        import check_hook_signatures
        self.t = check_hook_targets
        self.s = check_hook_signatures
        if not os.path.isdir(MODULE):
            self.skipTest('找不到模块源码')

    def both(self):
        return ({(c, m) for c, m, _ in self.t.collect_targets(MODULE) if m},
                {(r['class'], r['method']) for r in self.s.collect(MODULE)})

    def test_hook_all_before_is_seen_by_both(self):
        t, s = self.both()
        for pair in (('com.baidu.homework.common.ui.widget.HybridWebView', 'dispatchAction'),
                     ('com.baidu.homework.common.ui.widget.HybridWebView', 'dispatchActionToListeners')):
            with self.subTest(target=pair):
                self.assertIn(pair, t)
                self.assertIn(pair, s)

    def test_const_class_name_is_seen_by_both(self):
        t, s = self.both()
        pair = ('com.kuaiduizuoye.scan.web.VipLimitViewModel', 'b')
        self.assertIn(pair, t, '`Xp.hook(CLS, "b", …)` 的 const 没被展开')
        self.assertIn(pair, s, '⑤ 没展开 `private const val CLS`')

    def test_local_wrapper_is_seen_by_both(self):
        t, s = self.both()
        for meth in ('exit', 'halt', 'killProcess'):
            pair = (('java.lang.System' if meth == 'exit' else
                     ('java.lang.Runtime' if meth == 'halt' else 'android.os.Process')), meth)
            with self.subTest(target=pair):
                self.assertIn(pair, t, 'ExitGuard 的局部 hookAll 包装没被扫到')
                self.assertIn(pair, s)

    def test_escaped_inner_class_is_seen_by_both(self):
        """Kotlin 内部类写成 `Outer\\$Inner` —— 反斜杠必须在建目标前还原掉。

        这条是一次真实漏检（2026-10-25 第 14 轮）：`H5BridgeLog` 的出站钩子

            Xp.hook("com.baidu.homework.common.ui.widget.HybridWebView\\$ReturnCallback",
                    "call", String::class.java, …)

        字面量里带着转义反斜杠，而 ④ 的类名过滤器
        `'$' in cls and not re.fullmatch(r'[\\w.$]+', cls)` 把**带反斜杠的名字整条丢掉**
        ⇒ 这个钩子对 ④⑤⑥ **全部不可见**。它恰恰是全 APK **277 处调用点**的
        "桥返回值唯一出口"，也是 `H5BridgeLog` 能否记出站答案的唯一开关 ——
        方法名拼错时功能静默不装，而三道门一直是绿的。

        ⑤ 早就做了 `.replace('\\\\$','$')`（否则每个内部类目标都会误报不符），
        ④ 漏了 —— 这就是"三份清单各写一套"的代价。现在 ④ 的 `expand()` 也做同一件事。
        """
        t, s = self.both()
        pair = ('com.baidu.homework.common.ui.widget.HybridWebView$ReturnCallback', 'call')
        self.assertIn(pair, t, '④ 把带 `\\$` 的内部类名整条丢掉了（反斜杠没还原）')
        self.assertIn(pair, s, '⑤ 没还原 `\\$`')
        # 反过来的方向也要挡：**不许**有任何目标名里带反斜杠。
        # 只断言"某条在"是不够的 —— 换个人写 `Outer$Inner` 而不转义时，
        # 这里靠的就是下一行。
        dirty = sorted(name for name, _m in t | s if '\\' in name)
        self.assertEqual(dirty, [], f'目标类名里还残留反斜杠：{dirty}')


if __name__ == '__main__':
    unittest.main()


class DynamicClassHooks(unittest.TestCase):
    """`Xp.hookAllBefore(name, "shouldInterceptRequest")` —— 类名是**运行时发现**的
    WebViewClient 子类（全 APK 88 个，不可能写成字面量），方法名是字面量。

    这种形态 ④⑤⑥ 都只能看到"没有目标"，因此没有任何门禁校验它。实际风险很具体：

    * 若方法名拼错（例如写成 `shouldInterceptRequests`），`hookAllBefore` 返回 0，
      **功能静默不装** —— 而 `HookAudit` 只是少一条 ok，启动日志照绿；
    * 若不慎把平台 API 名换成宿主自己的方法名，同样静默失效。

    所以这里做两件事：把这种形态**列出来**（让人知道它们没被常规门禁覆盖），
    并断言方法名属于已知的 Android WebViewClient API。
    """

    MODULE = MODULE
    PATTERN = re.compile(r'Xp\.hookAll\w*\(\s*(?!")[A-Za-z_]\w*\s*,\s*"([\w$<>]+)"')

    # Android `WebViewClient` / `WebView` 的公开方法名。平台类不在解码目录里，
    # 无法从 APK 验，只能靠这份清单。
    KNOWN_PLATFORM_METHODS = {
        'shouldInterceptRequest', 'onPageFinished', 'onPageStarted',
        'shouldOverrideUrlLoading', 'onReceivedError', 'onLoadResource',
        'loadUrl', 'loadDataWithBaseURL', 'setWebViewClient', 'addJavascriptInterface',
    }

    def _found(self):
        out = []
        for f in Path(self.MODULE).rglob('*.kt'):
            text = f.read_text(encoding='utf-8')
            for m in self.PATTERN.finditer(text):
                line = text[:m.start()].count('\n') + 1
                out.append((f.name, line, m.group(1)))
        return out

    def test_dynamic_targets_are_listed(self):
        """至少要有这条测试：把"没被常规门禁覆盖"的钩子显式列出来。

        `web_request_log` 的 `shouldInterceptRequest` 就是这样一条 ——
        它是 `WEBREQ` 记录能否生效的唯一开关，却不在 ④⑤⑥ 任何一列里。
        """
        found = self._found()
        self.assertTrue(found, '一条动态类名钩子都没找到 —— 正则或代码形态变了，检查一下')
        names = {n for _f, _l, n in found}
        self.assertIn('shouldInterceptRequest', names,
                      f'web_request_log 的 shouldInterceptRequest 钩子不见了：{sorted(found)}')

    def test_dynamic_method_names_are_real(self):
        """动态钩法用的方法名必须真实存在。

        拼错时 `hookAllBefore` 返回 0、功能静默不装 —— 本仓库最想防的失效形态。

        分两种情况：
          * 平台 API（`shouldInterceptRequest` 等）不在解码目录 ⇒ 只能对白名单；
          * 宿主方法（`BridgeGuard` 的 `dispatchAction`）⇒ **去 APK 里查**，
            能真正验证，不必依赖白名单。
        """
        root = os.path.join(ROOT, 'work', 'apktool_out')
        have_apk = os.path.isdir(root)

        def method_exists_anywhere(meth):
            if not have_apk:
                return None
            pat = re.compile(r'^\.method [\w\s-]*?' + re.escape(meth) + r'\(', re.M)
            for d in os.listdir(root):
                if not (d == 'smali' or re.fullmatch(r'smali_classes\d+', d)):
                    continue
                for base, _x, files in os.walk(os.path.join(root, d)):
                    for fn in files:
                        if not fn.endswith('.smali'):
                            continue
                        try:
                            # 用 with 而不是裸 open().read()：这个循环要扫 5 万个 smali，
                            # 裸 open 靠 CPython 的引用计数才恰好不泄漏；换成 PyPy/开 GC
                            # 差异的运行时就会撞 `Too many open files`（默认 ulimit -n 只有
                            # 256）。同时它也是那 49931 条 ResourceWarning 的唯一来源，
                            # 足以把全绿的 `-q` 输出淹没成 15 万行。
                            with open(os.path.join(base, fn), encoding='utf-8',
                                      errors='replace') as fh:
                                hit = pat.search(fh.read())
                            if hit:
                                return True
                        except OSError:
                            continue
            return False

        bad = []
        for f, l, n in self._found():
            if n in self.KNOWN_PLATFORM_METHODS:
                continue
            if method_exists_anywhere(n) is True:
                continue
            bad.append(f'{f}:{l} {n}')
        self.assertEqual(bad, [],
                         '这些动态钩子的方法名既不在平台白名单、也不在 APK 里 '
                         '（拼错会导致功能静默不装）：' + str(bad))


class TargetNamesAreIdentifiers(unittest.TestCase):
    """目标收集器扫的是**源码文本**，于是注释里的示例也能被当成钩子。

    2026-10-26 第 40 轮实测到的实例（`HookAuditTest.kt:14` 的文档注释）：

        `Xp.clazzOrNull("…") ?: return` 这种写法下，钩子连**尝试**都没有

    `CALL_RE` 把 `"…"` 读成类名、方法名 `None`。后果不是"多一条噪声"：

    * ④ 的结论从 `123/123` 变成 123 真 + 1 假；
    * 假目标永远 `MISSING`，把 `smali_usage` 的汇总从 `114/114 有静态使用证据`
      拉成 `113/114`；
    * **没有任何门禁会红** —— 它只是让"全部有证据"退化成"几乎全部"，
      从此这句话再也不能当结论用。

    为什么不靠"剥注释"来修：Kotlin 的块注释可嵌套、字符串里可以出现 `//`，
    剥注释的正则一定会写漏。而"类名必须是合法标识符"是**无例外**的判据 ——
    真实类名不可能含 `…`，含了就一定是解析错误。
    """

    def setUp(self):
        import check_hook_targets as cht
        self.cht = cht
        self.targets = cht.collect_targets(MODULE)

    def test_whole_module_scan_is_clean_too(self):
        """扫**整个 module**（含 `src/test`）时也不能产出非标识符目标。

        这条比只扫 `src/main` 更严格，而它才是收集器真正的能力边界：
        `--module` 的默认值恰好是 `src/main/.../kdkit`，所以 CLI 一直没暴露
        `HookAuditTest.kt:14` 那个 `"…"`。**默认值替我挡掉了 bug** ——
        别的调用方（`smali_usage --from-module module`）不享受这个默认值。
        """
        whole = self.cht.collect_targets(os.path.join(ROOT, 'module'))
        bad = [(c, m, w) for c, m, w in whole
               if not re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', c)]
        self.assertEqual(bad, [],
                         '整个 module 扫描产出了非法类名（注释/示例被当成钩子）：'
                         + str(bad))

    def test_every_target_class_is_a_java_identifier(self):
        bad = [(c, m, w) for c, m, w in self.targets
               if not re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', c)]
        self.assertEqual(bad, [],
                         '这些"目标"不是合法类名 ⇒ 源码里的注释/示例被抓成了钩子：'
                         + str(bad))

    def test_collector_does_not_scan_test_sources(self):
        """测试源码不进 APK，里面的类名不该被要求能在 APK 里解析到。"""
        for _c, _m, where in self.targets:
            with self.subTest(where=where):
                self.assertNotIn('/src/test/', where.replace(os.sep, '/'))
                self.assertNotIn('/src/androidTest/', where.replace(os.sep, '/'))

    def test_the_ellipsis_case_is_really_gone(self):
        """钉住那一个具体实例 —— 它曾经真实存在过。"""
        names = {c for c, _m, _w in self.targets}
        self.assertNotIn('…', names)
        self.assertTrue(all('\u2026' not in n for n in names))
