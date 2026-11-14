#!/usr/bin/env python3
"""
`verify_membership.py` 的四个分支 —— 尤其是**退出码**。

为什么退出码值得单独测：这个脚本的存在意义就是"不把测不了说成通过"。
一旦"游客态"返回 0，报告里就会出现"跑了一遍全绿、其实什么都没验"那种假结论。
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'verify_membership.py')

MARK = '10:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true'


def verdict(*lines):
    fd, path = tempfile.mkstemp(suffix='.txt')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        p = subprocess.run([sys.executable, TOOL, '--capture', path],
                           capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    finally:
        os.unlink(path)


class Verdicts(unittest.TestCase):

    def test_guest_device_is_blocked_not_passed(self):
        rc, out = verdict(MARK, '10:00:01.000 NET identityIdV2=0&vipStatus=0')
        self.assertEqual(rc, 2, out)          # 2 = 无法验证，**不是** 0
        self.assertIn('无法验证', out)

    def test_logged_in_with_unlock_is_verified(self):
        rc, out = verdict(MARK,
                          '10:00:01.000 NET identityIdV2=123456&vipStatus=0',
                          '10:00:02.000 VIP unlock applied')
        self.assertEqual(rc, 0, out)
        self.assertIn('已验证', out)

    def test_logged_in_without_unlock_is_not_verified(self):
        rc, out = verdict(MARK, '10:00:01.000 NET identityIdV2=123456&vipStatus=0')
        self.assertEqual(rc, 2, out)
        self.assertIn('未验证', out)

    def test_no_identity_field_is_unknown(self):
        rc, out = verdict(MARK)
        self.assertEqual(rc, 2, out)
        self.assertIn('无法验证', out)

    def test_ad_slots_read_but_not_blocked_is_worded_correctly(self):
        """
        广告面最容易说错的一句：把"读了 88 次广告位、没拦住"说成"广告位是空的"。
        前者是"读到了但没东西可拦"，后者是"根本没读" —— 对结论影响完全不同。
        """
        _rc, out = verdict(MARK, '10:00:01.000 NET identityIdV2=0&vipStatus=0',
                           '10:00:02.000 ADSLOT call di.a.j #1')
        self.assertIn('广告位被读了', out)
        self.assertNotIn('广告位也是空的', out)


if __name__ == '__main__':
    unittest.main()


class PullCaptureContract(unittest.TestCase):
    """`pull_capture` 的返回形状 —— R64 那个 bug 就死在这里。

    R53 把 `sh()` 换成 `kit/python/sh.py` 的共享实现（修"超时只杀 shell、`adb` 泄漏"），
    新实现返回**单个字符串**；而 `pull_capture` 还在按旧的 `(returncode, output)` 解包
    ⇒ `ValueError: too many values to unpack` ⇒ `--adb` 那条路从 R53 起就是坏的。

    最坏的地方在于它**不崩溃**：`face_board` 把异常吃成"未知"，于是之后每一轮的
    C1/C3 两面其实都没有结论，而看板只写"有面异常"。

    而 `--capture` 那条路不走 `pull_capture` ⇒ 原有 5 条离线用例全过，**覆盖不到出事的那条路**。
    这几条把那条路钉住。
    """

    @staticmethod
    def _tool():
        """把被测脚本当模块加载（与 `--capture` 那条路走子进程不同，这里要进到函数里）。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location('verify_membership', TOOL)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_returns_a_string(self):
        vm = self._tool()
        out = vm.pull_capture('emulator-7777')   # 这个 serial 不存在，必然读不到
        self.assertIsInstance(out, str,
                              'pull_capture 必须返回字符串 —— 按元组解包的调用方会 ValueError')

    def test_offline_serial_does_not_raise(self):
        vm = self._tool()
        try:
            out = vm.pull_capture('emulator-7777')
        except ValueError as e:
            self.fail(f'解包形状又变回元组了（R64 的 bug 复发）：{e}')
        self.assertEqual(out, '', '设备不在线时应给空串，由调用方判"无法验证"')

    def test_adblock_is_counted_separately_from_ad_read(self):
        """`ADBLOCK` 与 `ADSLOT` 是两个数，不是同一个（R63 加的这条证据）。"""
        vm = self._tool()
        text = ('21:00:00.000 ADSLOT call di.a.d(501) #0\n'
                '21:00:00.001 ADBLOCK di.a.j -> false\n'
                '21:00:00.002 ADBLOCK di.a.k -> false\n')
        self.assertEqual(sum(len(r.findall(text)) for r in vm.AD_RX), 1)
        self.assertEqual(sum(len(r.findall(text)) for r in vm.AD_BLOCK_RX), 2)
