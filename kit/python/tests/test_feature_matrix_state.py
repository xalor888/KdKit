"""功能矩阵的「当前」列必须以**真实生效**为准，不是"钩子装上了"。

2026-11-09 实测：矩阵说 `block_ad_sdk` = **ON**，而同一份模块日志里
`HookCore gates off:` 清单明确列着 `block_ad_sdk` ——
读报告的人不会去翻日志，于是"关着的功能"在报告里显示成开着的（B4）。

判据（`parse_state()`）：
  * `feature on: <id>` 只表示**钩子装上了**（hot 功能恒装）；
  * `HookCore gates off: a,b,c` 才是**配置层面被关**的清单；
  * 两者冲突时，以 gates off 为准。
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SPEC = os.path.join(ROOT, 'kit', 'scripts', 'feature_matrix.py')
# `feature_matrix` 用 `from hook_vocab import read_text`（同目录）；importlib 加载时
# 脚本目录不会自动进 sys.path（命令行跑才会）⇒ 这里显式补上。
sys.path.insert(0, os.path.join(ROOT, 'kit', 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))


def load_module():
    spec = importlib.util.spec_from_file_location('fm', SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LOG = """\
[KdKit] feature on: log_sink (hooks 6 ok / 0 failed, hot)
[KdKit] feature on: block_ad_sdk (hooks 4 ok / 0 failed, hot)
[KdKit] feature on: popwin_gate (hooks 2 ok / 0 failed, hot)
[KdKit] feature on: sign_observer (hooks 14 ok / 0 failed, hot)
[KdKit] feature off: native_exit_guard (seccomp filter not revocable)
[KdKit] HookCore gates off: block_ad_sdk,popwin_gate
"""


class CurrentColumnIsRealState(unittest.TestCase):

    def setUp(self):
        self.fm = load_module()

    def test_gates_off_wins_over_feature_on(self):
        st = self.fm.parse_state(LOG)
        self.assertFalse(st['block_ad_sdk'],
                         'feature on 只是"装上了"；gates off 里点名 ⇒ 必须是 False')
        self.assertFalse(st['popwin_gate'])
        self.assertTrue(st['log_sink'])
        self.assertTrue(st['sign_observer'])
        self.assertFalse(st['native_exit_guard'], 'feature off 行仍应生效')

    def test_without_gates_line_falls_back_to_feature_lines(self):
        st = self.fm.parse_state('feature on: ad_probe (x)\n')
        self.assertTrue(st['ad_probe'], '没有 gates off 行时，按 feature on/off 判')

    def test_empty_log_is_empty_state(self):
        self.assertEqual(self.fm.parse_state(''), {})

    def test_gates_off_does_not_invent_features(self):
        """gates off 里有、但从未 feature on 的 id ⇒ 不能凭空出现在 state 里。"""
        st = self.fm.parse_state('HookCore gates off: ghost_feature\n')
        self.assertEqual(st, {})


if __name__ == '__main__':
    unittest.main()
