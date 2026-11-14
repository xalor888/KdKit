#!/usr/bin/env python3
"""
Offline tests: `kd_api` 的签名与请求体组装 —— **纯函数部分**。

Why this file exists
--------------------
代码审查 P2 明写：

> `kd_api / probe_paths / pageapi / composition_flow / extract_* …` 从未被测试提及

而 `kd_api` 正是 P0-4（“死分支”）与 P0-5（“请求体里参数重复”）的所在，
也是 R78 那次 TLS 重构动过的文件之一。它一条测试都没有。

这一轮先补**纯函数**：`sign_for` / `sign_from_url` / `pairs_of` /
`enum_hint_for` / `hint_for`。这些不碰网络、不碰设备，可以完全离线钉住。

### 重点钉的三件事

1. **`sign_for` 对参数排序后再拼，且 Base64 保留 padding** ——
   代码注释里写着“去掉 padding 会静默弄坏 54/80 个请求”，
   那个 54 是个具体数字，值得有一条测试把它钉住；
2. **`sign_from_url` 必须排除 `sign` 自己** —— 否则签名会把自己的结果算进去；
3. `pairs_of` 对畸形行不能抛异常（它吃的是抓取文本，什么都有）。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import base64
import hashlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'python'))

import kd_api                                                    # noqa: E402

CONST_A = '0123456789abcdef0123456789abcdef'
X = 'const_x_value'


class SignFor(unittest.TestCase):

    def test_is_deterministic_and_order_independent(self):
        """参数顺序不影响签名 —— App 端是排序后拼接的。"""
        a = kd_api.sign_for(CONST_A, X, ['a=1', 'b=2', 'c=3'])
        b = kd_api.sign_for(CONST_A, X, ['c=3', 'a=1', 'b=2'])
        self.assertEqual(a, b)

    def test_padding_is_kept(self):
        """Base64 **保留 padding** —— 去掉它会静默弄坏长度不是 3 的倍数的请求。

        代码注释说“54 of the 80 captured ones”。这里钉住机制本身：
        `sign_for` 返回的 param 必须与 `base64.b64encode(…).decode()` 完全一致，
        也就是说 padding 一个字符都不能少。

        **先证明这一组真的会产生 padding**，否则这条测试会在没有 padding 的
        输入上“通过”，而什么都没验（今天已经为这种假通过修过 3 处）。
        """
        params = ['x=abcdefgh']          # 拼出来 10 字节 ⇒ 10 % 3 == 1 ⇒ 有 padding
        raw = ''.join(sorted(params)).encode()
        # 拼出来长度 % 3 != 0 才有 padding
        self.assertNotEqual(len(raw) % 3, 0,
                            '这一组不产生 padding ⇒ 换一组，否则这条测试什么都没验')
        _sign, param = kd_api.sign_for(CONST_A, X, params)
        self.assertEqual(param, base64.b64encode(raw).decode())
        self.assertIn('=', param)

    def test_different_params_give_different_signs(self):
        self.assertNotEqual(kd_api.sign_for(CONST_A, X, ['a=1'])[0],
                            kd_api.sign_for(CONST_A, X, ['a=2'])[0])

    def test_empty_params_still_works(self):
        s, p = kd_api.sign_for(CONST_A, X, [])
        self.assertEqual(len(s), 32, 'md5 hex 长度')
        self.assertEqual(p, base64.b64encode(b'').decode())


class SignFromUrl(unittest.TestCase):

    def test_excludes_sign_itself(self):
        """`sign` 字段必须被排除 —— 否则签名会把自己的结果算进去。"""
        url = ('https://ptactivity.zuoyebang.com/kdapi/conf/appconfig'
               '?appId=123&vc=1840&sign=deadbeef')
        s = kd_api.sign_from_url(CONST_A, X, url)
        self.assertNotEqual(s, 'deadbeef')
        # 与手工按字段重算的结果一致
        want = kd_api.sign_for(CONST_A, X, ['appId=123', 'vc=1840'])[0]
        self.assertEqual(s, want)

    def test_blank_values_are_kept(self):
        """`keep_blank_values=True`：空值字段也要参与签名。"""
        url = 'https://h/x?a=&b=2'
        s = kd_api.sign_from_url(CONST_A, X, url)
        want = kd_api.sign_for(CONST_A, X, ['a=', 'b=2'])[0]
        self.assertEqual(s, want)


class PairsOf(unittest.TestCase):
    """`pairs_of` 吃的是抓取文本 —— 什么都有，不能抛异常。"""

    def _pairs(self, text):
        fd, path = tempfile.mkstemp(suffix='.txt')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(text)
            return kd_api.pairs_of(path)
        finally:
            os.unlink(path)

    def test_normal_lines(self):
        """输入是 `SIGN params:` / `SIGN URL:` 两种行，不是裸的 `k=v`。"""
        text = ('10:00:00.000 SIGN params: appId=123 | vc=1840\n'
                '10:00:00.001 SIGN URL: https://h/x?appId=123&vc=1840&sign=abc\n')
        out = self._pairs(text)
        self.assertTrue(out, '一对 params+URL 应该配得上')
        self.assertEqual(len(out), 1)

    def test_malformed_lines_do_not_raise(self):
        """畸形行不能抛异常 —— **并且要真的返回一个 list**。

        第一版只写 `self._pairs(junk)`，被 `fake_test_detector` 抓出来：
        “没有任何断言 —— 它只会通过，不会失败”。
        那个判断是对的：`pairs_of` 完全可能**返回 None** 而不抛异常，
        那样这条测试照样绿，而调用方下一行就炸。
        """
        for junk in ('', '\n', '=====\n', '&&&\n', '=noname\n', 'novalue=\n',
                     'a=1&b\n', '%%%\n', '\x00\xff\n'):
            out = self._pairs(junk)
            self.assertIsInstance(out, list,
                                  f'{junk!r} 应当返回 list，实际 {type(out).__name__}')

    def test_empty_file(self):
        self.assertEqual(self._pairs(''), [])


class Hints(unittest.TestCase):

    def test_enum_hint_for_known(self):
        """`errNo:4000` 会把缺的字段名报出来，此时追加枚举提示。

        注意：**不是 errNo=6**。6 是 antispam sign error，走 `hint_for()`。
        第一版在这里断言 errNo=6 有提示 —— 那是把两个不同的 errNo 混成一个，
        测试写在错误的对象上（与 `test_acceptance_skip_state` 同类：
        检查在错误的前提下“通过”了）。
        """
        self.assertTrue(kd_api.enum_hint_for('{"errNo":4000,"msg":"param invalid: vc"}'))
        self.assertTrue(kd_api.enum_hint_for('param invalid'))
        self.assertEqual(kd_api.enum_hint_for('{"errNo":6}'), '')

    def test_enum_hint_for_unknown_is_empty_not_error(self):
        self.assertEqual(kd_api.enum_hint_for('errNo=99999'), '')

    def test_hint_for_errno6(self):
        """errNo 6 = antispam sign error，`hint_for` 认识它。"""
        out = kd_api.hint_for('6')
        self.assertIn('6', out)
        self.assertTrue(out.strip(), 'errNo=6 应该有提示')

    def test_hint_for_never_raises(self):
        """同样：不能抛异常，且**必须返回 str**（调用方直接拼进输出）。"""
        for junk in ('', '???', 'a' * 5000, None, 'abc', b'bytes', 3.14):
            out = kd_api.hint_for(junk)
            self.assertIsInstance(out, str,
                                  f'{junk!r} 应当返回 str，实际 {type(out).__name__}')


if __name__ == '__main__':
    unittest.main()


class SignMaterialGuards(unittest.TestCase):
    """`sign_material` 的前置校验（2026-11-03 代码审查 P1）。

    旧实现直接 `open(sign_a_file)`，而 `export_content.token_files()`
    找不到令牌时返回 **None** ⇒ `TypeError: … not NoneType`。
    那个错因指向"类型"，而真正的问题是"你没有先跑证据包"。

    `_need_blob` 那一半同理：短 blob 会静默给出一串短字符，
    签名照样算得出来，只是每个请求都被服务端拒（errNo 6），
    而现象与"参数集不对"完全一样。
    """

    def test_none_path_raises_runtime_not_type(self):
        for args in ((None, None), (None, 'x'), ('x', None)):
            with self.assertRaises(RuntimeError, msg=f'{args} 应当报 RuntimeError'):
                kd_api.sign_material('emulator-5558', *args)

    def test_missing_file_names_the_path(self):
        with self.assertRaises(RuntimeError) as cm:
            kd_api.sign_material('emulator-5558', '/tmp/_nope_a.txt', '/tmp/_nope_b.txt')
        self.assertIn('_nope_a.txt', str(cm.exception))

    def test_empty_file_is_rejected(self):
        fd, p = tempfile.mkstemp()
        try:
            with self.assertRaises(RuntimeError) as cm:
                kd_api._need_file(p, 'signA 令牌')
            self.assertIn('空文件', str(cm.exception))
        finally:
            os.close(fd)
            os.unlink(p)

    def test_short_blob_is_rejected_with_the_real_reason(self):
        with self.assertRaises(RuntimeError) as cm:
            kd_api._need_blob(b'short', 16, 'signA 解出的 blob')
        msg = str(cm.exception)
        self.assertIn('密钥不对', msg)
        self.assertIn('5', msg)          # 实际长度要出现在消息里


if __name__ == '__main__':
    unittest.main()
