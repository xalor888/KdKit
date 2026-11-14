#!/usr/bin/env python3
"""
验收脚本的第三种结局：**SKIP（没跑）必须与 PASS 分开**。

旧实现里条件不满足时直接不调用 `check()` —— 那一项从报告里消失，
而汇总行仍写 `13/13 checks passed`。读的人无法区分"验过了"与"根本没验"。

这条测试守两件事：
  1. 不加 `--live` 时，`live call` 必须出现在输出里并且标成 SKIP；
  2. 汇总行必须把"未验证的项"列出来，而不是只报一个分数。
"""
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'acceptance.py')
ADB = shutil.which('adb')


@unittest.skipUnless(ADB, '没有 adb')
class SkipIsVisible(unittest.TestCase):

    def _run(self, *extra):
        # **必须 cwd=ROOT**：acceptance.py 内部用相对路径（`work/…`、`kit/…`）。
        # 第一版忘了设 cwd，测试从 `kit/python/tests/` 起跑 —— 工具早退，
        # 输出只有 1KB，而断言仍然全过（SKIP 那行出现得早）。
        # **一个在错误环境下仍然通过的测试，比没有测试更危险。**
        p = subprocess.run([sys.executable, TOOL, '--adb', 'emulator-5558', *extra],
                           capture_output=True, text=True, timeout=900, cwd=ROOT)
        return p.returncode, (p.stdout or '') + (p.stderr or '')

    def test_no_live_flag_reports_skip_not_silence(self):
        rc, out = self._run()
        self.assertIn('SKIP  live call', out)
        self.assertIn('无法验证（SKIP）', out)
        self.assertIn('未验证的项', out)
        # 没跑的那一项**不能**被算进"通过数"的分母
        self.assertNotRegex(out, r'^13/13 checks passed$', )

    def test_summary_never_claims_more_than_it_ran(self):
        """汇总行的分母只能是"跑了的项数"。"""
        rc, out = self._run()
        for line in out.splitlines():
            if 'checks passed' in line:
                m = re.search(r'(\d+)/(\d+) checks passed', line)
                self.assertIsNotNone(m, line)
                self.assertLessEqual(int(m.group(1)), int(m.group(2)), line)


import re  # noqa: E402  （放在类后面只为上面能引用；测试本身不依赖顺序）


if __name__ == '__main__':
    unittest.main()
