#!/usr/bin/env python3
"""
`module_activity.py` 的**表内数字**是不是真的数出来的（不只是"结论文案对得上"）。

已有测试（`test_doc_generators.py`）验的是"文案里的 11/27 与表里的行数一致"、
"附录齐全"、"ownerless 是派生的"。它们都**没有碰表里的具体数字**：
把 `parent_ctrl_probe` 的计数从 3 改成 0，那些测试照样全绿。

而"每行几次"正是这张表唯一的硬信息 —— 判断"某功能到底跑没跑"全靠它。
所以这里喂一份**已知条数**的合成抓取，逐行核对表里的数字。
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
GEN = os.path.join(ROOT, 'kit', 'scripts', 'module_activity.py')

#: 故意选三个不写 logcat 之外噪声、前缀互不重叠的功能
#
# 样本行**照抄真实格式**，不是我编的形状。
# 第一版我写的是 `PCTRL mask=0xf` / `POPWIN blocked=X` —— 两条都解析不出来（UNCKNOWN），
# 于是测试报"表里写了 0，抓取里有 3 行"，看起来像生成器坏了，其实是**测试数据错了**。
# 这是 2026-11-02 同一天里第二次犯（上一次在 `session_report` 的合成抓取）：
# **合成数据必须先看一眼真实行**，否则测的是自己想象出来的格式。
# 下面的样本取自 `tests/fixtures/all_prefixes.txt`（那本身就是"规则 ↔ 真实行"的对照物）。
CASES = {
    'parent_ctrl_probe': ('PCTRL aiwriting=1 book=0 correctsearch=1 picsearch=1 mask=0xf', 3),
    'popwin_gate': ('POPWIN seen type=winAd block=true action=BLOCK', 1),
    'route_log': ('ROUTE zyb://webview/main abc123 | from=com.kuaiduizuoye.scan.MainActivity',
                  0),
}


def build_capture(path):
    lines, seq = [], 0
    for _feat, (sample, n) in CASES.items():
        for _ in range(n):
            seq += 1
            lines.append(f'10:00:{seq:02d}.000 {sample}')
    # 一条启动标记：让报告知道样本属于哪个宿主（否则会走"没有版本行"的分支）
    lines.insert(0, '10:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


class CountsComeFromTheCapture(unittest.TestCase):

    def setUp(self):
        fd, self.cap = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        build_capture(self.cap)
        self.out = self.cap + '.md'
        p = subprocess.run([sys.executable, GEN, '--capture', self.cap, '--out', self.out],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, (p.stdout or '') + (p.stderr or ''))

    def tearDown(self):
        for p in (self.cap, self.out):
            if os.path.exists(p):
                os.unlink(p)

    def _row(self, feature):
        with open(self.out, encoding='utf-8') as f:
            text = f.read()
        m = re.search(r'^\|\s*`' + re.escape(feature) + r'`\s*\|\s*(\d+)\s*\|', text, re.M)
        self.assertIsNotNone(m, f'表里找不到 `{feature}` 这一行')
        return int(m.group(1))

    def test_counts_match_the_capture(self):
        for feat, (_sample, n) in CASES.items():
            with self.subTest(feature=feat):
                self.assertEqual(self._row(feat), n,
                                 f'`{feat}` 在抓取里有 {n} 行，表里却写了别的数')

    def test_zero_and_nonzero_are_distinguishable(self):
        """0 与"有几行"必须是两种不同的结论 —— 这张表存在的意义就在这里。"""
        self.assertEqual(self._row('route_log'), 0)
        self.assertGreater(self._row('parent_ctrl_probe'), 0)


if __name__ == '__main__':
    unittest.main()
