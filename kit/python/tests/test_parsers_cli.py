#!/usr/bin/env python3
"""
End-to-end tests for the six capture parsers — the layer above `capture_schema.py`.

`test_capture_schema.py` proves a line *parses*; this file proves each parser *uses* it, i.e.
that a new prefix changes the report. That distinction matters: the 2026-10-25 rewrite was
prompted by parsers that parsed nothing while exiting 0, so a test that only checks exit
codes would have passed before and after.

Run:

    python3 -m unittest discover -s kit/python/tests -v

Every test drives the real CLI in a subprocess against a temporary capture file, so
`sys.exit` codes, argparse defaults and stdout formatting are all covered.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_PY = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, 'fixtures', 'all_prefixes.txt')

# 让 `import capture_schema` 在**单独运行本文件**时也能成功。
#
# 之前没这行，于是这 5 条测试只在**完整套件**里通过 —— 因为别的测试文件先把
# KIT_PY 插进了 sys.path。单独跑 `python3 -m unittest <本文件>` 会
# `ModuleNotFoundError: capture_schema`（ERROR 而不是 FAIL，容易被误读成"环境问题"）。
#
# 这类"顺序依赖"是测试隔离缺陷：它让"这个文件自己能跑通吗"这个问题无法回答。
if KIT_PY not in sys.path:
    sys.path.insert(0, KIT_PY)


def run(script, *args):
    """Run one parser; return (rc, stdout+stderr)."""
    p = subprocess.run([sys.executable, os.path.join(KIT_PY, script), *args],
                       capture_output=True, text=True, cwd=KIT_PY, timeout=300)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def capture_of(text: str) -> str:
    fd, path = tempfile.mkstemp(suffix='.txt')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return path


class CaptureSchemaCLI(unittest.TestCase):
    def test_fixture_covers_every_capturable_feature(self):
        """fixture 必须覆盖 schema 里**每一个**能写抓取的功能。

        这条不写死数字：功能增加时，是 fixture 需要补一行（应该失败），而不是断言需要改小
        （那会让"新前缀没被覆盖"悄悄通过）。
        """
        import capture_schema as cs
        n = len(cs.FEATURES_WITH_CAPTURE)
        rc, out = run('capture_schema.py', FIXTURE)
        self.assertEqual(rc, 0)
        self.assertIn(f'{n}/{n} capturable feature(s)', out)
        self.assertIn('anti_detect', out)          # logcat-only list
        self.assertIn('1 UNKNOWN line(s)', out)

    def test_unknown_flag_lists_the_line(self):
        rc, out = run('capture_schema.py', FIXTURE, '--unknown')
        self.assertEqual(rc, 0)
        self.assertIn('no known prefix', out)

    def test_json_output_is_complete(self):
        import json
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            rc, out = run('capture_schema.py', FIXTURE, '--json', path)
            self.assertEqual(rc, 0)
            with open(path, encoding='utf-8') as fh:
                doc = json.load(fh)
            with open(FIXTURE, encoding='utf-8') as fh:
                want_lines = sum(1 for ln in fh if ln.strip())
            self.assertEqual(doc['lines'], want_lines)
            self.assertEqual(len(doc['unknown']), 1)
            self.assertIn('exit_guard', doc['features'])
            self.assertIn('vip_unlock', doc['features'])
        finally:
            os.unlink(path)


class CaptureTranscript(unittest.TestCase):
    def test_every_new_prefix_renders_meaningfully(self):
        rc, out = run('capture_transcript.py', FIXTURE)
        self.assertEqual(rc, 0)
        for needle in ('**EXITCALL #1**', '↳ 栈 #1', '**BRIDGE downloadMedia**',
                       '**VIP**', '**UPDATE**', '**ONBOARD**', '**RC4PT(nontext)**',
                       '**GUARD 拦截**', '**WEBREQ**', '**HDR(static)**', '**HDR(v)**'):
            with self.subTest(needle=needle):
                self.assertIn(needle, out)

    def test_nontext_is_not_rendered_as_text(self):
        out = run('capture_transcript.py', FIXTURE)[1]
        # The b64 payload of a (nontext) line must not be echoed as if it were plaintext.
        self.assertNotIn('RC4PT** `3q2+7w==', out)
        self.assertIn('不是文本', out)

    def test_rc4_triple_is_decrypted_inline(self):
        out = run('capture_transcript.py', FIXTURE)[1]
        self.assertIn('RC4 decrypt', out)
        self.assertIn('{"md5":"","url":"","version":"","jarTime":0}', out)

    def test_unknown_line_is_marked_not_dropped(self):
        out = run('capture_transcript.py', FIXTURE)[1]
        self.assertIn('__UNKNOWN__', out)
        self.assertIn('no known prefix', out)


class VerifyRc4Capture(unittest.TestCase):
    def test_real_capture_matches(self):
        cap = os.path.join(os.path.dirname(os.path.dirname(KIT_PY)),
                           'work', 'dpsdk', 'kdkit_capture_r3.txt')
        if not os.path.exists(cap):
            self.skipTest('real capture not present')
        rc, out = run('verify_rc4_capture.py', cap)
        self.assertEqual(rc, 0)
        self.assertIn('MATCH', out)
        self.assertIn('match=1 mismatch=0', out)
        # The key line must be surfaced, not just counted.
        self.assertIn('RC4KEY: 1 distinct key(s)', out)

    def test_mismatch_is_a_failure(self):
        """A tampered output byte must make the script exit 1 — it is a gate, not a report."""
        cap = capture_of(
            '00:00:00.000 RC4 decrypt key=b64[4]YWJjZA== in=b64[3]eHl6: b64[3]AAAA\n')
        rc, out = run('verify_rc4_capture.py', cap)
        self.assertEqual(rc, 1)
        self.assertIn('MISMATCH', out)

    def test_truncated_triple_is_skipped_not_crashed(self):
        cap = capture_of('00:00:00.000 RC4 decrypt key=b64[128]YWI in=b64[3]eHl6: b64[3]\n')
        rc, out = run('verify_rc4_capture.py', cap)
        self.assertEqual(rc, 0)
        self.assertIn('skipped=1', out)


class ParserPrefixCoverage(unittest.TestCase):
    """**每个** schema kind 都必须被该管它的解析器真正处理，而不是只被 schema 认识。

    这条测试的由来（2026-10-25 第 3 轮）：`WATERMARK` 在 `capture_schema.py` 里能解析，
    `capture_transcript.py` 却没有对应分支 —— 整行被渲染成 `__UNKNOWN__`，而同一份输出的
    统计表却在 `WATERMARK` 名下计了 1 行。**两处数字互相矛盾，却没有一条测试会红**：
    既有测试只断言"某几个新前缀出现过"，没断言"每个前缀都被处理过"。

    所以这里改成**反向枚举**：从 `cs.RULES` 取全部 kind，逐个断言。
    新增一个前缀而忘了改解析器时，这里自动报出它的名字，不依赖谁记得来补测试。
    """

    #: 解析器 -> 它**必须**处理的 kind。故意不要求每个解析器认识所有 kind（职责不同），
    #: 但每个 kind 至少要有一个"主要消费者"为它负责，且该消费者必须真的处理它。
    OWNERS = {
        'capture_transcript.py': None,      # None = 该文件必须处理**全部** kind
        'session_report.py': None,
    }

    #: 这两个是窄职责脚本，只认与自身主题相关的 kind；它们漏掉别的 kind 是设计，不是 bug。
    NARROW = {
        'guard_report.py': {'GUARD'},
        'verify_rc4_capture.py': {'RC4', 'RC4KEY', 'RC4KEYSTR'},
        'bridge_inventory.py': {'H5BRIDGE', 'BRIDGE'},
    }

    @staticmethod
    def all_kinds():
        return sorted({k for k, *_ in __import__('capture_schema').RULES})

    @staticmethod
    def one_line_per_kind():
        """每个 kind 取一行代表性记录（来自 fixture，缺的补一条）。"""
        import capture_schema as cs
        seen = {}
        for rec in cs.iter_records(FIXTURE):
            seen.setdefault(rec.kind, rec)
        return seen

    def test_transcript_has_a_branch_for_every_kind(self):
        """`WATERMARK` 就是这样漏的：schema 认识，transcript 不认识。"""
        import capture_schema as cs
        import capture_transcript as ct
        recs = self.one_line_per_kind()
        missing = [k for k in self.all_kinds() if k not in recs]
        self.assertEqual(missing, [], f'fixture 缺这些 kind 的样本: {missing}')
        bad = []
        for kind in self.all_kinds():
            if kind == 'UNKNOWN':
                continue                      # UNKNOWN 的正解就是渲染成 __UNKNOWN__
            out = ct.one_line(recs[kind])
            if '__UNKNOWN__' in out:
                bad.append(kind)
        self.assertEqual(bad, [], f'capture_transcript.py 没有处理这些 kind，'
                                  f'整行会渲染成 __UNKNOWN__: {bad}')

    def test_session_report_covers_every_feature_kind(self):
        """`session_report.py` 的 9 节必须覆盖每一个能写抓取的功能。

        判据不是"代码里出现了这个字符串"（那太弱），而是**真的跑一遍**：
        用 fixture 生成报告，要求每个 capturable feature 都在覆盖表里出现一行。
        """
        import capture_schema as cs
        rc, out = run('session_report.py', FIXTURE)
        self.assertEqual(rc, 0)
        # §8 的覆盖表列出每个 capturable feature，行数必须等于功能数。
        table_rows = [ln for ln in out.splitlines()
                      if ln.startswith('| `') and ln.count('|') == 3]
        self.assertGreaterEqual(len(table_rows), len(cs.FEATURES_WITH_CAPTURE),
                                '§8 覆盖表比功能数还短 —— 有功能没被列出')
        for f in cs.FEATURES_WITH_CAPTURE:
            with self.subTest(feature=f):
                self.assertIn(f'| `{f}` |', out)

    # ── 把 `OWNERS` / `NARROW` 从"写了但没人用"变成真的判据 ────────────────
    #
    # 2026-10-25 本轮的发现：这两张表**声明了却从未被任何断言读过**
    # （`grep -rn "OWNERS\|NARROW" kit/python/tests` 只有定义处）。于是
    # "每个 kind 都有主要消费者"只是注释里的一句话，而实际情况是
    # `POPWIN` / `NETERR` / `VIPLIMIT` / `H5RET` / `REQBODY` / `RESPBODY`
    # 六个前缀**只被逐行渲染、从未被汇总分析** —— 抓到了数据，没有任何一处
    # 回答"抓到了什么形状"。而门禁全绿。
    #
    # 判据不能用"源码里出现这个字符串"（那正是漏掉它们的原因：`'POPWIN'` 的确
    # 在 `capture_transcript.py` 里），也不能用"输出里含 kind 名"（§ 开头的
    # `记录种类：POPWIN×2` 那行永远含它 —— 第一版就是这样写的，反向验证时
    # 把 §7b 整段改名它照样绿）。正确判据见下。

    NEUTRAL = '00:00:00.000 === KdKit probe\n'

    @staticmethod
    def _analysed_body(out):
        """报告正文里**能证明"这个 kind 被分析过"**的行集合。

        排除两类 —— 它们对所有 kind 都机械变化，不能算证据：
        * `## 8.` 之后（覆盖表逐个列出全部功能，任何一行都会让它变）；
        * `记录种类：…` 那一行（它逐字包含 kind 名 —— 第一版就是拿
          "输出含 kind 名"当判据，把 §7b 整段改名它照样绿，是假测试）。
        """
        head = out.split('## 8.')[0]
        return {ln for ln in head.splitlines()
                if ln.strip()
                # 这四类对**任意**一行输入都会机械变化，不能算"为某个 kind 而产出的行"：
                and '会话报告 —' not in ln          # 临时文件路径，每次都不同
                and '记录种类' not in ln            # 逐字含 kind 名
                and not ln.startswith('* 记录行：')  # `记录行：1，时间跨度 …`（同一时刻则连它都不变）
                and not ln.startswith('* 时间跨度')}

    def test_every_kind_is_actually_analysed(self):
        """每个 kind 单独喂一行，正文必须**多出内容** —— 否则它只被计数。

        这是"被分析"与"被计数"的可判定分界，且不靠猜文案：

        * 底稿只放一条会话标记，记下它无条件打印的全部正文；
        * 逐 kind 单独跑，要求正文出现底稿里没有的行。

        为什么不用"必须新开一个节标题"：很多 kind 是往**已有**小节里加行
        （`EXITCALL` 进 §7、`HDR` 进 §6），新开小节会把它们误判成"没被分析"。
        第一版就是这么写的，反向验证时一次误报 26 个 kind。

        反向验证（2026-10-25 实做）：把 §7b 的标题+三行首行文案改名 ⇒
        本测试精确报出 `POPWIN` / `NETERR` / `VIPLIMIT`；
        把 §2b / §6b 同理改名 ⇒ 精确报出 `H5RET` / `REQBODY` / `RESPBODY`。
        """
        rc, neutral = run('session_report.py', self._write(self.NEUTRAL))
        self.assertEqual(rc, 0)
        base = self._analysed_body(neutral)
        unanalysed = []
        for kind in self.all_kinds():
            rec = self.one_line_per_kind().get(kind)
            if rec is None or kind in ('MARK', 'UNKNOWN'):
                continue          # MARK 只是会话标记；UNKNOWN 的正解就是不分析
            path = self._write(rec.raw + '\n')
            try:
                rc, out = run('session_report.py', path)
            finally:
                os.unlink(path)
            self.assertEqual(rc, 0)
            missing = self._analysed_body(out) - base
            if not missing:
                unanalysed.append(kind)
        self.assertEqual(unanalysed, [],
                         '这些 kind 只被计数/逐行渲染，报告正文里没有任何'
                         f'**为它而产出**的行（抓到了但没人读）: {unanalysed}')

    def test_narrow_parsers_stay_narrow(self):
        """`NARROW` 里声明的窄职责脚本，必须**真的**只处理那几个 kind。

        反过来也要紧：如果某个"窄"脚本其实处理了更多 kind，那 `NARROW` 就是
        一张过期的许可证 —— 它让"漏了别的 kind"看起来像设计。
        判据：给它一行别的 kind，输出必须与空输入逐字相同。
        """
        for script, owns in self.NARROW.items():
            path = os.path.join(KIT_PY, script)
            if not os.path.exists(path):
                self.fail(f'NARROW 声明了不存在的脚本: {script}')
            # 输出里会带临时文件路径（每次不同），归一化后再比 —— 否则
            # 每一对都"不同"，测试变成永远红或永远绿。
            rc, empty = run(script, self._write(''))
            empty = re.sub(r'/\S+tmp\w+\.txt', '<tmp>', empty)
            for kind in self.all_kinds():
                if kind in owns or kind in ('MARK', 'UNKNOWN'):
                    continue
                rec = self.one_line_per_kind().get(kind)
                if rec is None:
                    continue
                rc2, out = run(script, self._write(rec.raw + '\n'))
                out = re.sub(r'/\S+tmp\w+\.txt', '<tmp>', out)
                with self.subTest(script=script, kind=kind):
                    self.assertEqual((rc2, out), (rc, empty),
                                     f'{script} 处理了 {kind}，但它不在 NARROW 声明里 ——'
                                     f'要么补进 NARROW，要么这条声明该删')

    @staticmethod
    def _write(text):
        fd, path = tempfile.mkstemp(suffix='.txt')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        return path

    def test_no_hardcoded_feature_count_in_reports(self):
        """报告里的功能数必须**派生**，不能写死任何一个数字。

        原来 `session_report.py` 第 8 节标题写死 `28 个功能`，而注册表当时已经是 29 项 ——
        文档口径与代码真值分叉，且没有任何门禁会发现。

        第一版这条测试只匹配"当前数字"（`\\b29\\s*个功能`），那样**抓不到**原来的 28：
        它只在数字恰好等于当前真值时才响亮，正是最没用的那种断言。现在改成匹配**任意**
        字面量数字 + `个功能`，并要求该行没有 `len(...)` —— 写死的数字一律算违规。
        """
        offenders = []
        for name in ('session_report.py', 'capture_transcript.py'):
            path = os.path.join(KIT_PY, name)
            with open(path, encoding='utf-8') as fh:
                for lineno, line in enumerate(fh, 1):
                    stripped = line.strip()
                    if stripped.startswith('#'):
                        continue
                    # 只看**会打印出来**的行（注释里的历史解释不算）。
                    if not (stripped.startswith('w(') or stripped.startswith('print(')
                            or stripped.startswith('return f')):
                        continue
                    if re.search(r'\b\d+\s*个功能', line) and 'len(' not in line:
                        offenders.append(f'{name}:{lineno}: {stripped[:80]}')
        self.assertEqual(offenders, [],
                         '这些行把功能数写死了，注册表一变就过期；'
                         f'改用 len(FEATURE_IDS)/len(FEATURES_WITH_CAPTURE): {offenders}')

    def test_watermark_line_renders_and_counts_consistently(self):
        """同一行不能"统计表计数 1、时间线却是 UNKNOWN"。"""
        import capture_schema as cs
        out = run('capture_transcript.py', FIXTURE)[1]
        # 统计表
        self.assertIn('`WATERMARK`', out)
        # 时间线必须也认得它
        self.assertIn('**WATERMARK**', out)
        self.assertNotIn('__UNKNOWN__ `WATERMARK', out)
        # session_report 也要给出 watermark 的观测行
        rep = run('session_report.py', FIXTURE)[1]
        self.assertIn('`watermark_off`', rep)
        self.assertIn('只证明钩子执行过', rep)


class GuardReport(unittest.TestCase):
    def test_counts_and_hosts(self):
        rc, out = run('guard_report.py', FIXTURE)
        self.assertEqual(rc, 0)
        self.assertIn('3 block(s)', out)
        self.assertIn('core_httpRequest=2', out)
        self.assertIn('blacklist=1', out)
        self.assertIn('evilkuaiduizuoye.com', out)     # absolute URL host
        self.assertIn('self:www.kuaiduizuoye.com', out)  # relative URL resolved

    def test_no_guard_lines_is_exit_1_with_explanation(self):
        cap = capture_of('00:00:00.000 VIP unlock applied\n')
        rc, out = run('guard_report.py', cap)
        self.assertEqual(rc, 1)
        self.assertIn('没有 GUARD 行', out)

    def test_slice_detection(self):
        """#n far beyond the line count means the pulled file is a slice, and says so."""
        cap = capture_of('00:00:00.000 GUARD blocked=a reason=blacklist url= #9\n')
        out = run('guard_report.py', cap)[1]
        self.assertIn('切片', out)


class BridgeInventory(unittest.TestCase):
    def test_wide_and_semantic_layers_kept_apart(self):
        rc, out = run('bridge_inventory.py', FIXTURE)
        self.assertEqual(rc, 0)
        self.assertIn('2 distinct action(s) via H5BRIDGE', out)
        self.assertIn('语义层', out)
        self.assertIn('downloadMedia', out)
        self.assertIn('identity=student_42', out)
        # Merging the two layers would double-count; the semantic section must be separate.
        self.assertIn('← 语义层也记到', out)

    def test_type_not_one_is_visible(self):
        out = run('bridge_inventory.py', FIXTURE)[1]
        self.assertIn('type=2', out)


class UnknownTriage(unittest.TestCase):
    """三份报告都必须把 UNKNOWN 分档，并只在 `new-prefix` 上示警。

    由来：5 份冻结抓取里 564 行 UNKNOWN 中 560 行是同一张 PEM 证书的续行。
    "有 N 行没人认领"读起来像模块在写未知格式，实际是旧构建没压平换行。
    分档后这条告警重新指向**真正要处理的那一类**。
    """

    MIXED = ('00:00:00.000 NEWTHING a=1\n'
             '00:00:00.001 MIIFoTCCA4mgAwIBAgICO/cwDQYJKoZIhvcNAQELBQAwgYAx\n')

    def test_schema_splits_and_points_at_new_prefix(self):
        cap = capture_of(self.MIXED)
        try:
            rc, out = run('capture_schema.py', cap)
            self.assertEqual(rc, 0)
            self.assertIn('legacy-wrap=1, new-prefix=1', out)
            self.assertIn('未登记的前缀', out)
        finally:
            os.unlink(cap)

    def test_session_report_splits(self):
        cap = capture_of(self.MIXED)
        try:
            out = run('session_report.py', cap)[1]
            self.assertIn('`new-prefix`×1', out)
            self.assertIn('`legacy-wrap`×1', out)
        finally:
            os.unlink(cap)

    def test_transcript_splits_and_warns_only_for_new_prefix(self):
        cap = capture_of(self.MIXED)
        try:
            out = run('capture_transcript.py', cap)[1]
            self.assertIn('`new-prefix`×1', out)
            self.assertIn('未登记的新前缀', out)
        finally:
            os.unlink(cap)

    def test_legacy_only_capture_does_not_cry_wolf(self):
        """只有 legacy-wrap 时**不能**出现"疑似新前缀"的告警 —— 否则告警就失效了。"""
        cap = capture_of('00:00:00.000 -----BEGIN CERTIFICATE-----\n'
                         '00:00:00.001 MIIFoTCCA4mgAwIBAgICO/cwDQYJKoZIhvcNAQELBQAwgYAx\n')
        try:
            for script in ('capture_schema.py', 'capture_transcript.py'):
                with self.subTest(script=script):
                    out = run(script, cap)[1]
                    self.assertNotIn('未登记的前缀', out)
                    self.assertNotIn('未登记的新前缀', out)
        finally:
            os.unlink(cap)


class SessionReport(unittest.TestCase):
    def test_all_nine_sections_present(self):
        rc, out = run('session_report.py', FIXTURE)
        self.assertEqual(rc, 0)
        for i in range(1, 9):
            with self.subTest(section=i):
                self.assertIn(f'## {i}.', out)

    def test_new_features_show_up_in_coverage(self):
        import capture_schema as cs
        out = run('session_report.py', FIXTURE)[1]
        self.assertIn(f'有抓取能力的功能 {len(cs.FEATURES_WITH_CAPTURE)} 个', out)
        self.assertIn(f'只写 logcat、不写抓取的功能（{len(cs.FEATURES_LOGCAT_ONLY)} 个', out)
        self.assertIn('`skip_update`', out)

    def test_unknown_line_is_flagged_in_overview(self):
        out = run('session_report.py', FIXTURE)[1]
        self.assertIn('没有任何规则认领', out)

    def test_exit_guard_blocked_vs_observed_counts(self):
        out = run('session_report.py', FIXTURE)[1]
        self.assertIn('2 次退出调用', out)
        self.assertIn('**真拦下 1** 次、只记录 1 次', out)

    def test_out_file_written(self):
        fd, path = tempfile.mkstemp(suffix='.md')
        os.close(fd)
        try:
            rc, _ = run('session_report.py', FIXTURE, '--out', path)
            self.assertEqual(rc, 0)
            with open(path, encoding='utf-8') as fh:
                body = fh.read()
            self.assertTrue(body.startswith('# 会话报告'))
        finally:
            os.unlink(path)

    def test_legacy_capture_without_timestamp_and_empty_file(self):
        for text in ('', 'VIP unlock applied\n', '\n\n'):
            with self.subTest(text=text):
                cap = capture_of(text)
                rc, out = run('session_report.py', cap)
                self.assertEqual(rc, 0, out)
                self.assertIn('# 会话报告', out)


class SessionReportRendersEveryBehaviourPrefix(unittest.TestCase):
    """`session_report.py` 的 §7 必须把每个"行为改变类"前缀都渲染出来。

    为什么单独一条：§7 按**序号**配对记录（`EXITCALL #1` 与 `EXITSTACK #1`），
    早先只取 `EXITCALL`，于是 `EXITSTACK`（从哪条链退出）**整类被丢掉** ——
    报告读起来像"这个功能不记栈"，而模块其实写了。这类"解析器认得、报告不显示"
    的缺口，`test_capture_schema` 与 `test_every_prefix` 都抓不到（它们只证明解析正确）。
    """

    def test_exitstack_rows_reach_the_report(self):
        cap = capture_of(
            '00:00:00.000 EXITCALL #1 com.x.A.run() blocked=true\n'
            '00:00:00.001 EXITSTACK #1 java.lang.System.exit(System.java:1) ⏎ com.x.A.run(A.java:9)\n')
        rc, out = run('session_report.py', cap)
        self.assertEqual(rc, 0, out)
        self.assertIn('EXITSTACK', out, '§7 没有提到 EXITSTACK')
        self.assertIn('java.lang.System.exit', out, '§7 没有渲染栈内容')
        self.assertIn('1/1', out, '没有说明"几条 EXITCALL 配到了栈"')

    def test_orphan_stack_is_reported_not_silently_dropped(self):
        """轮转会把 `EXITCALL` 切掉、只留 `EXITSTACK` —— 报告要说出来，不能装作没有。"""
        cap = capture_of('00:00:00.000 EXITSTACK #77 com.x.B.run(B.java:3)\n')
        rc, out = run('session_report.py', cap)
        self.assertEqual(rc, 0, out)
        # 栈内容必须渲染出来：它单独就能回答"谁在调 System.exit"，
        # 是这一节最有用的证据之一，不该因为缺 EXITCALL 就整段消失。
        self.assertIn('com.x.B.run', out, '孤立栈的内容被丢弃')
        self.assertIn('没有对应的 `EXITCALL`', out,
                      '没有说明"为什么没有配对的 EXITCALL"')
        self.assertIn('轮转', out, '没有点出这多半是轮转截断，而不是功能坏了')

    def test_all_behaviour_prefixes_appear_somewhere(self):
        """整份 fixture 过一遍：§7 要把**每一项**行为类记录都反映出来。

        §7 是按**功能名**渲染的（`exit_guard` / `skip_update` / …），不是按原始前缀名 ——
        这是有意的：读报告的人关心"哪个功能有痕迹"，不是"哪个 token 出现几次"。
        所以这里断言功能名 + 那两类必须带出原文的前缀（`EXITSTACK` 的栈、
        `APPSIGN` 的 tag），而不是逐个前缀字面量。
        """
        rc, out = run('session_report.py', FIXTURE)
        self.assertEqual(rc, 0, out)
        # 功能名：每个行为类功能都该在 §7 里被点到
        for feature in ('exit_guard', 'skip_update', 'vip_unlock', 'skip_onboarding',
                        'log_sink', 'watermark_off'):
            with self.subTest(feature=feature):
                self.assertIn(f'`{feature}`', out, f'§7 完全没有提到 {feature}')
        # 必须带出原文的两处：栈内容、宿主 tag
        for token in ('EXITSTACK', 'DProtect'):
            with self.subTest(token=token):
                self.assertIn(token, out, f'§7 没有把 {token} 的原文带出来')


class DecryptCapture(unittest.TestCase):
    def test_reads_all_four_key_shapes(self):
        """The old parser only saw `RC4KEY …: <hex>`; RC4KEYSTR/`| len=` were invisible."""
        cap = capture_of(
            '00:00:00.000 RC4KEY b(1811): aabb\n'
            '00:00:00.001 RC4KEY refreshed: ccdd\n'
            '00:00:00.002 RC4KEYSTR eeff | len=4\n'
            '00:00:00.003 RC4KEY 00112233 | len=4\n')
        rc, out = run('decrypt_capture.py', cap)
        self.assertEqual(rc, 0)
        self.assertIn('4 RC4 key(s)', out)
        for k in ('aabb', 'ccdd', 'eeff', '00112233'):
            with self.subTest(key=k):
                self.assertIn(k, out)

    def test_device_side_plaintext_is_echoed_as_cross_check(self):
        cap = capture_of('00:00:00.000 RC4PT {"title":"x"}\n')
        out = run('decrypt_capture.py', cap)[1]
        self.assertIn('设备解出', out)

    def test_nothing_decryptable_is_stated_not_hidden(self):
        cap = capture_of('00:00:00.000 RC4KEY b(1811): aabb\n')
        rc, out = run('decrypt_capture.py', cap)
        self.assertEqual(rc, 0)
        self.assertIn('没有任何字段被解开', out)


class EachNewPrefixHasItsOwnSemantics(unittest.TestCase):
    """10 个新前缀各自的**独有语义**各一条断言 —— 不是"fixture 里能解析"。

    为什么不能只靠 fixture：`ParseEveryPrefix.CASES` 证明"这行能解析出字段"，
    `test_every_kind_is_actually_analysed` 证明"报告里有为它产出的行"。
    两者都不回答**这个前缀最容易搞错的那件事**。每个新前缀都有一个特定的坑：

    | 前缀 | 最容易错的地方 |
    |---|---|
    | `EXITCALL` | `(stack suppressed)` 后缀是**可选**的，漏判会让"栈被省略"读成"没有栈" |
    | `EXITSTACK` | `#n` 必须能配到 `EXITCALL #n`，靠的是同一个 seq |
    | `BRIDGE` | 两个 variant 共用一个 token，`download` 的 `type != 1` 意为"宿主不落盘" |
    | `VIP` | 自由文本 note，**不含**判定结果 —— 不能从它推出"已解锁" |
    | `UPDATE` | 两种形状共用一个 token，靠 builder 判 variant |
    | `ONBOARD` | 文案里有中文/空格/引号，必须整段保留 |
    | `APPSIGN` | `级别/tag: msg` 三段，tag 里可能含 `:` |
    | `RC4PT(nontext)` | **不能**被当成明文（b64 不是文本），且必须比 `RC4PT` 先命中 |
    | `GUARD` | 相对 url 要归到 `SELF_HOST`，绝对 url 取其 host |
    | `WEBREQ` | 头摘要为空与"没记头"是两件事（空串 vs 缺键） |
    | `HDR` | 三种 variant（request / v / static），`pid=-` 意为"读不到" |
    """

    def test_exitcall_optional_stack_suffix(self):
        with_suffix = capture_of(
            '00:00:00.000 EXITCALL #41 com.x.A.run() blocked=false (stack suppressed)\n')
        rc, out = run('session_report.py', with_suffix)
        self.assertEqual(rc, 0)
        self.assertIn('只记录', out, 'blocked=false 应渲染成"只记录"而不是"拦下"')
        # 语义层：后缀必须被解析出来，否则"栈被省略"会被读成"这个功能不记栈"
        import capture_schema as cs
        rec = cs.parse_line('00:00:00.000 EXITCALL #41 com.x.A.run() blocked=false (stack suppressed)')
        self.assertTrue(rec.get('stack_suppressed'))
        rec2 = cs.parse_line('00:00:00.000 EXITCALL #41 com.x.A.run() blocked=false')
        self.assertFalse(rec2.get('stack_suppressed'))

    def test_exitstack_pairs_by_seq(self):
        cap = capture_of(
            '00:00:00.000 EXITCALL #7 com.x.A.run() blocked=true\n'
            '00:00:00.001 EXITSTACK #7 java.lang.System.exit ⏎ com.x.A.run\n')
        out = run('session_report.py', cap)[1]
        self.assertIn('1/1', out, '按 seq 配对应为 1/1')

    def test_bridge_two_variants_differ(self):
        import capture_schema as cs
        d = cs.parse_line('00:00:00.000 BRIDGE downloadMedia type=2 url=https://x/b.jpg')
        u = cs.parse_line('00:00:00.000 BRIDGE getuserinfo asked identity=s42')
        self.assertEqual((d.variant, u.variant), ('download', 'userinfo'))
        self.assertEqual(d.get('type'), 2)
        # `type != 1` 是语义分界线，报告必须点出来（页面请求了但宿主不落盘）
        cap = capture_of('00:00:00.000 BRIDGE downloadMedia type=2 url=https://x/b.jpg\n')
        self.assertIn('不落盘', run('session_report.py', cap)[1])

    def test_vip_note_is_free_text_and_not_a_verdict(self):
        import capture_schema as cs
        rec = cs.parse_line('00:00:00.000 VIP unlock applied because flag=true')
        self.assertEqual(rec.kind, 'VIP')
        self.assertEqual(rec.get('note'), 'unlock applied because flag=true')
        # note 是自由文本 —— 报告**不能**把它渲染成"已解锁"。必须是"判定被改写 + 未验证"
        cap = capture_of('00:00:00.000 VIP unlock applied\n')
        out = run('session_report.py', cap)[1]
        self.assertIn('服务端未验证', out)
        self.assertNotIn('已解锁', out)

    def test_update_two_shapes_one_token(self):
        import capture_schema as cs
        a = cs.parse_line('00:00:00.000 UPDATE forceUp 1 -> 0')
        b = cs.parse_line('00:00:00.000 UPDATE suppressed force-update popup')
        self.assertEqual((a.kind, a.variant), ('UPDATE', 'forceup'))
        self.assertEqual((b.kind, b.variant), ('UPDATE', 'suppressed'))
        self.assertEqual((a.get('before'), a.get('after')), (1, 0))

    def test_onboard_keeps_quoted_cjk_text(self):
        import capture_schema as cs
        rec = cs.parse_line("00:00:00.000 ONBOARD clicked='跳过 引导' label=skip #3 ok=true")
        self.assertEqual(rec.get('text'), '跳过 引导')
        self.assertEqual(rec.get('label'), 'skip')
        self.assertTrue(rec.get('ok'))

    def test_appsign_splits_on_the_inserted_separator_not_the_first_colon(self):
        """写入侧拼的是 `"$tag: $msg"`，tag 本身可以含冒号。

        实测三种写法的结果（都试过）：

        | 正则 | `Some:Tag: message with: colons` |
        |---|---|
        | `([^:]+):` | tag=`Some`，msg=`Tag: message with: colons`（tag 被截断） |
        | `(.+?):` | 同上（后面 `(.*)$` 贪婪，引擎在第一个可行冒号处停） |
        | `(.+)`   | tag=`Some:Tag: message with`，msg=`colons`（吃到行尾回溯） |
        | `((?:(?!: ).)+): ` | tag=`Some:Tag`，msg=`message with: colons` ✅ |

        前三种都能让 kind/feature 全对，所以只有逐字段断言能发现。
        """
        import capture_schema as cs
        rec = cs.parse_line('00:00:00.000 APPSIGN W/Some:Tag: message with: colons')
        self.assertEqual(rec.get('level'), 'W')
        self.assertEqual(rec.get('tag'), 'Some:Tag')
        self.assertEqual(rec.get('msg'), 'message with: colons')
        # msg 里含 URL 的形态也必须保住（冒号后面不是空格，不能当分隔符）
        url = cs.parse_line(
            '00:00:00.000 APPSIGN I/VectorLegacyBridge: [KdKit] H5 n out: https://x')
        self.assertEqual(url.get('tag'), 'VectorLegacyBridge')
        self.assertEqual(url.get('msg'), '[KdKit] H5 n out: https://x')
        # 普通一行（tag 无冒号）行为不变
        plain = cs.parse_line('00:00:00.000 APPSIGN D/DProtect: init failed rc=-1')
        self.assertEqual((plain.get('tag'), plain.get('msg')), ('DProtect', 'init failed rc=-1'))

    def test_rc4pt_nontext_is_not_plaintext(self):
        """`RC4PT(nontext)` 的 b64 一旦被当正文，报告里就会出现假的"明文"。"""
        import capture_schema as cs
        rec = cs.parse_line('00:00:00.000 RC4PT(nontext) len=6 b64=3q2+7w==')
        self.assertEqual(rec.variant, 'nontext')
        self.assertIsNone(rec.get('text'))
        self.assertEqual(rec.get('b64'), '3q2+7w==')
        cap = capture_of('00:00:00.000 RC4PT(nontext) len=6 b64=3q2+7w==\n')
        out = run('session_report.py', cap)[1]
        self.assertIn('加解密活动', out, 'nontext 行仍应进入 §4 的计数')
        self.assertNotIn('3q2+7w==', out, 'b64 不应作为明文被回显')

    def test_guard_relative_url_maps_to_self_host(self):
        import capture_schema as cs
        rel = cs.parse_line('00:00:00.000 GUARD blocked=a reason=host_not_allowed url=/x/y #2')
        absu = cs.parse_line('00:00:00.000 GUARD blocked=a reason=host_not_allowed url=https://e.example/p #3')
        self.assertEqual(rel.get('host'), 'self:www.kuaiduizuoye.com')
        self.assertEqual(absu.get('host'), 'e.example')

    def test_webreq_empty_header_summary_is_not_missing(self):
        import capture_schema as cs
        bare = cs.parse_line('00:00:00.000 WEBREQ https://cdn/a.js')
        withh = cs.parse_line('00:00:00.000 WEBREQ https://cdn/a.js | X-Sign=1 | _t_=2')
        self.assertEqual(bare.get('headers'), '')
        self.assertNotIn('header_names', bare.fields)
        self.assertEqual(withh.get('header_names'), ['X-Sign', '_t_'])

    def test_hdr_three_variants_and_unreadable_pid(self):
        import capture_schema as cs
        req = cs.parse_line('00:00:00.000 HDR h/p :: A=1')
        v = cs.parse_line('00:00:00.000 HDR(v) h/p pid=cube :: A=1')
        static = cs.parse_line('00:00:00.000 HDR(static) A=1')
        bad = cs.parse_line('00:00:00.000 HDR(v) h/p pid=- :: A=1')
        self.assertEqual(req.variant, 'request')
        self.assertEqual(v.variant, 'v')
        self.assertEqual(static.variant, 'static')
        self.assertEqual(v.get('pid'), 'cube')
        # `-` 是"读不到"，不是"没有业务域" —— 与缺键必须可区分
        self.assertEqual(bad.get('pid'), '-')
        self.assertNotIn('pid', req.fields)


if __name__ == '__main__':
    unittest.main()


class CoverageSectionExplainsTheThreeCauses(unittest.TestCase):
    """第 8 节必须把"没有行"的**三种原因**分开列，而不是只说"可能是钩子失效"。

    这是本项目反复踩的误读点：一份 2026-10-18 的抓取里，2026-10-25 才加的功能
    必然是 0 行。报告如果只写"可能钩子失效"，读的人会去查一个不存在的问题 ——
    `module/ACTIVITY.md` §四 那张表就是为这件事存在的。

    这里用真实样本（`work/activity_inputs/`）验证，因为它们**必然**缺功能；
    fixture 覆盖全部前缀，触发不到这个分支。
    """

    REAL = os.path.join(os.path.dirname(KIT_PY), '..', 'work', 'activity_inputs')

    def test_three_causes_are_listed_separately(self):
        d = os.path.normpath(self.REAL)
        if not os.path.isdir(d):
            self.skipTest('work/activity_inputs 不存在')
        files = [f for f in sorted(os.listdir(d)) if f.endswith('.txt')]
        if not files:
            self.skipTest('没有抓取样本')
        rc, out = run('session_report.py', os.path.join(d, files[0]))
        self.assertEqual(rc, 0, out[-400:])
        if '本抓取里没有行' not in out:
            self.skipTest('这份样本恰好覆盖了全部功能，触发不到该分支')
        for cause in ('功能没开', '没被走到', '钩子失效'):
            self.assertIn(cause, out, f'第 8 节应列出原因「{cause}」')
        self.assertIn('结构性 0', out,
                      '必须提示"样本早于功能 ⇒ 结构性 0，不是失效"')
