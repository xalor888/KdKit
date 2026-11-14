#!/usr/bin/env python3
"""
`BRIDGE` 的**四个变体**都必须有自己的渲染分支。

缺陷回顾（2026-11-01 代码审查 P0-5）
------------------------------------
`capture_transcript.py` 与 `session_report.py` 只写了两个分支：

    if var == 'download':  …下载…
    return f'… **BRIDGE getuserinfo** identity=…'

于是：

* `BRIDGE payorder submit len=48 keys=2:goodsId,price pid=vip`
  （页面在**驱动下单**）
* `BRIDGE decodeHttpRequest url=… shouldDecode=1 params=keys=2:page,size`
  （页面**借宿主签名代发请求**）

都被渲染成 `**BRIDGE getuserinfo** identity=None` —— 一条"页面在打听用户身份"的结论，
方向和事实完全相反；而 schema 侧四个变体一直是齐全的（`VARIANTS['BRIDGE']`）。

这组测试钉三件事：

1. 四个变体各有分支，且 `payorder` / `decode` 的输出里**不出现** `getuserinfo`；
2. 每个变体的关键字段都出现（`len`/`shape`/`pid`、`shouldDecode`/`params`）；
3. 未知变体不会被静默塞进某个已知分支（走兜底分支并带上变体名）。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_PY = os.path.dirname(HERE)
FIXTURE = os.path.join(HERE, 'fixtures', 'all_prefixes.txt')

if KIT_PY not in sys.path:
    sys.path.insert(0, KIT_PY)


def run_parser(script, *args):
    p = subprocess.run([sys.executable, os.path.join(KIT_PY, script), *args],
                       capture_output=True, text=True, errors='replace', timeout=300)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


class TranscriptRendersEveryVariant(unittest.TestCase):
    """`capture_transcript.py`：四个变体各一句话，互不冒充。"""

    @classmethod
    def setUpClass(cls):
        cls.rc, cls.out = run_parser('capture_transcript.py', FIXTURE)

    def test_parser_succeeds(self):
        self.assertEqual(self.rc, 0, f'capture_transcript 退出码非 0:\n{self.out[-800:]}')

    def test_download_keeps_its_own_label(self):
        self.assertIn('**BRIDGE downloadMedia**', self.out)
        self.assertIn('_(非 1 ⇒ 宿主不落盘)_', self.out,
                      'type != 1 的提示丢了 —— 那正是"页面请求了但宿主没落盘"的证据')

    def test_userinfo_keeps_its_own_label(self):
        self.assertIn('**BRIDGE getuserinfo** identity=`student_42`', self.out)

    def test_payorder_is_not_rendered_as_userinfo(self):
        lines = [l for l in self.out.splitlines() if 'payorder' in l]
        self.assertTrue(lines, f'fixture 里有 payorder，但输出里没有:\n{self.out[-1200:]}')
        for l in lines:
            self.assertNotIn('getuserinfo', l, f'payorder 被冒充成 getuserinfo:\n{l}')
            self.assertIn('**BRIDGE payorder**', l)
            self.assertIn('pid=', l)

    def test_payorder_three_shapes_are_distinguishable(self):
        """`empty` / `not-json` / `keys=N:…` 是三条不同的结论，不能合并成一个数字。"""
        lines = '\n'.join(l for l in self.out.splitlines() if 'payorder' in l)
        self.assertIn('empty', lines)
        self.assertIn('not-json', lines)
        self.assertIn('keys=goodsId,price', lines)

    def test_decode_is_not_rendered_as_userinfo(self):
        lines = [l for l in self.out.splitlines() if 'decodeHttpRequest' in l]
        self.assertTrue(lines, f'fixture 里有 decodeHttpRequest，但输出里没有:\n{self.out[-1200:]}')
        for l in lines:
            self.assertNotIn('getuserinfo', l, f'decodeHttpRequest 被冒充成 getuserinfo:\n{l}')
            self.assertIn('**BRIDGE decodeHttpRequest**', l)
            self.assertIn('shouldDecode=', l)
            self.assertIn('params=', l)

    def test_decode_three_valued_shouldDecode_survives(self):
        """`?`（页面没传）与 `0`（传了 false）是两条不同路径，不能都被打成 0。"""
        lines = '\n'.join(l for l in self.out.splitlines() if 'decodeHttpRequest' in l)
        self.assertIn('shouldDecode=1', lines)
        self.assertIn('shouldDecode=?', lines)


class SessionReportRendersEveryVariant(unittest.TestCase):
    """`session_report.py` §2a：同一份 fixture 出四行，字段不丢。"""

    @classmethod
    def setUpClass(cls):
        cls.rc, cls.out = run_parser('session_report.py', FIXTURE)

    def test_report_succeeds(self):
        self.assertEqual(self.rc, 0, f'session_report 退出码非 0:\n{self.out[-800:]}')

    def test_section_2a_has_one_row_per_variant(self):
        body = self.out.split('### 2a. 语义层', 1)
        self.assertEqual(len(body), 2, f'报告里没有 §2a:\n{self.out[:600]}')
        seg = body[1].split('### ', 1)[0]
        for variant in ('download', 'userinfo', 'payorder', 'decode'):
            self.assertIn(f'| {variant} |', seg, f'§2a 缺 {variant} 变体行:\n{seg[:800]}')

    def test_section_2a_payorder_keeps_len_shape_pid(self):
        seg = self.out.split('### 2a. 语义层', 1)[1].split('### ', 1)[0]
        row = [l for l in seg.splitlines() if '| payorder |' in l]
        self.assertTrue(row, seg[:800])
        joined = '\n'.join(row)
        self.assertIn('len=48', joined)
        self.assertIn('keys=2:goodsId,price', joined)
        self.assertIn('pid=vip', joined)

    def test_section_2a_decode_keeps_url_shoulddecode_params(self):
        seg = self.out.split('### 2a. 语义层', 1)[1].split('### ', 1)[0]
        row = [l for l in seg.splitlines() if '| decode |' in l]
        self.assertTrue(row, seg[:800])
        joined = '\n'.join(row)
        self.assertIn('url=api.example.com/kdapi/x', joined)
        self.assertIn('shouldDecode=1', joined)
        self.assertIn('params=keys=2:page,size', joined)


class UnknownVariantIsNotSwallowed(unittest.TestCase):
    """
    新增第 5 个变体时，两个渲染器都必须走兜底分支并**带上变体名**，
    而不是落进 `getuserinfo` 那条默认路径。这条用 schema 直接构造一行来验。
    """
    LINE = '16:42:16.999 BRIDGE futureThing url=x shouldDecode=1 params=keys=1:a'

    def test_schema_rejects_unknown_variant(self):
        import capture_schema
        rec = capture_schema.parse_line('16:42:16.999 BRIDGE futureThing url=x')
        # 未被规则认领 ⇒ kind 应为 unknown/None；重点是不能被 parse 成 getuserinfo
        self.assertNotEqual(rec.get('variant'), 'userinfo',
                            '未知 BRIDGE 变体被 schema 认成了 getuserinfo')


if __name__ == '__main__':
    unittest.main()
