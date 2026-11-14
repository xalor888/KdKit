#!/usr/bin/env python3
"""
Offline tests: `trend_report.norm` must not invert a gate's verdict.

Why this file exists
--------------------
2026-11-03 代码审查（`work/code_review/00-CODE-MAP.md` 的 P1 清单）说
"`trend_report.py:30-34` 判据反了"。实测确认，而且是**两处反向**：

| 门值 | 旧判据 | 正确 |
|---|---|---|
| `变化 0 条` | **FAIL** | PASS（0 条漂移是好事） |
| `FAIL 目标 App 版本不一致` | **PASS** | FAIL |

第二处更糟：一个**写着 FAIL 的门值**在趋势表里显示成 ✔。
原因是 `不一致` 里含 `一致` 两个字，而旧的"通过"分支排在失败分支**之前**
⇒ 显式的 FAIL 从来没走到判据那里。

这正是"判据的范围比它以为的窄"那一类：子串匹配没有边界，
而分支顺序让错误的那一支先命中。

趋势表是拿来看"哪道门曾经绿后来红"的。判据一反，
它给出的就是一份**反着的地图** —— 比没有地图更危险。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', '..', 'scripts', 'trend_report.py')


def _tool():
    spec = importlib.util.spec_from_file_location('trend_report', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class NormVerdict(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _tool()

    def n(self, val):
        return self.t.norm('whatever', val)

    def test_explicit_fail_wins(self):
        """写着 FAIL 就是 FAIL —— 哪怕同一行里另有"一致"两个字。"""
        self.assertEqual(self.n('FAIL 目标 App 版本不一致'), 'FAIL')
        self.assertEqual(self.n('FAIL  hooks 3 failed'), 'FAIL')

    def test_zero_changes_is_good(self):
        """`变化 0 条` = 没有漂移 = PASS。旧判据只要出现"变化"就判 FAIL。"""
        self.assertEqual(self.n('变化 0 条'), 'PASS')

    def test_nonzero_changes_is_bad(self):
        self.assertEqual(self.n('变化 3 条'), 'FAIL')

    def test_agreement_is_pass(self):
        self.assertEqual(self.n('一致'), 'PASS')
        self.assertEqual(self.n('目标 App 版本一致'), 'PASS')

    def test_disagreement_is_fail(self):
        self.assertEqual(self.n('目标 App 版本不一致'), 'FAIL')

    def test_empty_is_skip_not_pass(self):
        """空值是该轮没跑 —— **不能算绿**。旧判据这里是对的，钉住它。"""
        for v in ('', '   ', '-', '—'):
            self.assertEqual(self.n(v), 'SKIP', f'{v!r} 应是 SKIP')

    def test_plain_success_marker_is_pass(self):
        self.assertEqual(self.n('server_shape ✓'), 'PASS')


class NormOrdering(unittest.TestCase):
    """分支顺序：失败标记必须在"通过"分支之前。"""

    def test_bad_markers_are_checked_first(self):
        t = _tool()
        with open(TOOL, encoding='utf-8') as _f:
            src = _f.read()
        i_bad = src.index('BAD_MARKERS')
        i_pass = src.index("return 'PASS'", src.index('def norm'))
        self.assertLess(i_bad, i_pass,
                        '失败标记必须排在"通过"之前 —— 顺序一反，'
                        '`FAIL … 不一致` 会被判成 PASS')


if __name__ == '__main__':
    unittest.main()
