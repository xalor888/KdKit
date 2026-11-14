"""`sign_material` 解出来的 blob **内容**必须验，不能只验长度。

2026-11-04 代码审查 P1：`_need_blob` 只查长度。长度对、内容错是
**最坏的一种错** —— 签名照样算得出来，只是每个请求都被服务端拒（errNo 6），
而现象与"参数集不对"完全一样，人会去翻参数表，翻不出来。

实测（三份真实抓取一致）：
    const_a = '8&%d*'        5 个可打印字符
    x       = 'VzYfc94fbW'  10 个可打印字符
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import kd_api  # noqa: E402


class PrintableIsEnforced(unittest.TestCase):

    def test_control_bytes_are_rejected(self):
        with self.assertRaises(RuntimeError) as cm:
            kd_api._need_printable(b'\x00\x01\x02\x03\x04', '某 blob')
        self.assertIn('不是可打印 ASCII', str(cm.exception))

    def test_the_message_names_why_it_matters(self):
        """错误信息必须说清"后果是什么"，否则下次还是查不到。"""
        with self.assertRaises(RuntimeError) as cm:
            kd_api._need_printable(b'\x80', '某 blob')
        msg = str(cm.exception)
        self.assertIn('密钥不对', msg)
        self.assertIn('errNo 6', msg)

    def test_high_bytes_are_rejected(self):
        """0x80 以上也不是可打印 ASCII —— latin1 会把它解成一个字符，
        看着"有内容"，其实是乱码。"""
        with self.assertRaises(RuntimeError):
            kd_api._need_printable(b'abc\xe9', '某 blob')

    def test_printable_passes_unchanged(self):
        got = kd_api._need_printable(b'8&%d*', '某 blob')
        self.assertEqual(got, b'8&%d*')

    def test_space_and_tilde_are_the_boundary(self):
        self.assertEqual(kd_api._need_printable(b'\x20', 'x'), b'\x20')
        self.assertEqual(kd_api._need_printable(b'\x7e', 'x'), b'\x7e')
        for bad in (b'\x1f', b'\x7f'):
            with self.assertRaises(RuntimeError):
                kd_api._need_printable(bad, 'x')


class RealTokensKeepWorking(unittest.TestCase):
    """真实令牌的形态必须原样通过 —— 否则这道检查会把正确的代码判错。"""

    TOKENS = [('work/packs/r71/signA.txt', 'work/packs/r71/signB.txt'),
              ('work/packs/api_health/signA.txt', 'work/packs/api_health/signB.txt')]

    def setUp(self):
        self.root = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def test_sign_material_still_returns_the_documented_shape(self):
        found = 0
        for a, b in self.TOKENS:
            pa, pb = os.path.join(self.root, a), os.path.join(self.root, b)
            if not (os.path.isfile(pa) and os.path.isfile(pb)):
                continue
            found += 1
            const_a, x = kd_api.sign_material('emulator-5558', pa, pb)
            self.assertEqual(len(const_a), 5, const_a)
            self.assertEqual(len(x), 10, x)
            self.assertTrue(const_a.isprintable(), const_a)
            self.assertTrue(x.isprintable(), x)
        if not found:
            self.skipTest('没有真实令牌样本')

    def test_same_tokens_give_the_same_material(self):
        """同一份令牌两次调用必须给出同一个 const_a / x —— 否则签名不可复现。"""
        pa = os.path.join(self.root, 'work/packs/r71/signA.txt')
        pb = os.path.join(self.root, 'work/packs/r71/signB.txt')
        if not (os.path.isfile(pa) and os.path.isfile(pb)):
            self.skipTest('没有真实令牌样本')
        self.assertEqual(kd_api.sign_material('emulator-5558', pa, pb),
                         kd_api.sign_material('emulator-5558', pa, pb))


if __name__ == '__main__':
    unittest.main()
