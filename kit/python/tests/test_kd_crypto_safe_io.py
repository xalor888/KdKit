#!/usr/bin/env python3
"""
Offline tests: `kd_crypto.rc4` / `decrypt` / `encrypt` 与 `safe_io` 的三个写入原语。

Why this file exists
--------------------
代码审查 P2 的“测试空白”名单里有 `kd_crypto` 与 `safe_io`。这两个都很小，
但**小的东西被改错的概率并不小**，而且：

* `rc4` 是 `com.baidu.android.common.security.RC4` 的逐字节移植 ——
  移植错了不会报错，只会**解出乱码**，而乱码与“密钥不对”长得一样；
* `safe_io` 的三个原语是**今天一整天在修的那一族的执行端**：
  `write_verified` / `append_verified` / `patch_at_anchor` 都是
  “写之前先说要写什么、写之后验一遍”。它们的失败模式
  （写了个空文件却报告成功）正是 `check_capture_claimed` /
  `verify_membership.pull_capture` / `device_backup` 三次修过的东西。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import base64
import gzip
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))

import kd_crypto                                                  # noqa: E402
import safe_io                                                    # noqa: E402
import urllib.parse                                               # noqa: E402
import device_entry_crypto as dec                                 # noqa: E402
import textio                                                    # noqa: E402
import memread                                                    # noqa: E402
import subprocess                                                 # noqa: E402


class Rc4(unittest.TestCase):

    def test_known_vector(self):
        """RFC 6229 之外的常用测试向量：key='Key', plain='Plaintext'。

        用一个**外部已知值**而不是“自己加密再自己解密” ——
        后者只能证明可逆，证明不了与 Android 那份一致。
        """
        self.assertEqual(
            kd_crypto.rc4(b'Key', b'Plaintext').hex(), 'bbf316e8d940af0ad3')
        self.assertEqual(kd_crypto.rc4(b'Wiki', b'pedia').hex(), '1021bf0420')
        self.assertEqual(kd_crypto.rc4(b'Secret', b'Attack at dawn').hex(),
                         '45a01f645fc35b383552544b9bf5')

    def test_empty_key_raises_a_useful_error(self):
        """空 key 必须抛**说得清的错**。

        原来是 `ZeroDivisionError: division by zero` —— 那个错因指向“除法”，
        而真正的问题是“你没给密钥”（`kd_api.decode_token` 解错了）。
        2026-11-03 改成 ValueError 并在消息里说清是谁的问题。
        """
        with self.assertRaises(ValueError) as cm:
            kd_crypto.rc4(b'', b'')
        self.assertIn('key', str(cm.exception))
        with self.assertRaises(ValueError):
            kd_crypto.rc4(b'', b'x')

    def test_empty_data_is_fine(self):
        """空 data 不抛 —— 只有空 key 才是错。"""
        self.assertEqual(kd_crypto.rc4(b'k', b''), b'')

    def test_is_symmetric(self):
        data = os.urandom(64)
        key = os.urandom(7)
        self.assertEqual(kd_crypto.rc4(key, kd_crypto.rc4(key, data)), data)


class DecryptEncrypt(unittest.TestCase):

    def test_roundtrip(self):
        ct = kd_crypto.encrypt('hello 快对', 'k')
        self.assertEqual(kd_crypto.decrypt(ct, 'k'), 'hello 快对')

    def test_wrong_key_gives_garbage_not_error(self):
        """密钥不对 ⇒ 乱码，**不抛异常**。

        这一点很重要：调用方（`kd_api.decode_token`）靠“解出来是不是可打印”
        判断密钥对不对。若这里抛异常，那条判断就永远走不到。
        """
        ct = kd_crypto.encrypt('x' * 40, 'right')
        out = kd_crypto.decrypt(ct, 'wrong')
        self.assertIsInstance(out, str)

    def test_b64_without_padding_is_accepted(self):
        """Android 的 `NO_WRAP` 不含 padding ⇒ `_b64d` 必须补齐。"""
        raw = b'\x00\x01\x02\x03'
        stripped = base64.b64encode(raw).decode().rstrip('=')
        self.assertNotIn('=', stripped or '')          # 先证明真的没 padding
        self.assertEqual(kd_crypto._b64d(stripped), raw)

    def test_non_base64_falls_back_to_raw(self):
        """不是 base64 时退回原始字节 —— 不能抛。

        **这条以前是死的**：`base64.b64decode('!!!!')` 不抛异常，返回 `b''`，
        于是 `except` 分支永远不执行，“退回原文”的承诺从来没兑现过
        （docstring 却一直这么写）。2026-11-03 修了 `_b64d`。
        """
        self.assertEqual(kd_crypto._b64d('!!!!'), b'!!!!')
        self.assertEqual(kd_crypto._b64d('****'), b'****')
        # 而正常的 base64 仍要正常解
        self.assertEqual(kd_crypto._b64d('YWJj'), b'abc')


class SafeIo(unittest.TestCase):
    """`safe_io` 的三个原语：写之前说要写什么，写之后验一遍。"""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, 'out.txt')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def test_write_verified_writes_and_checks(self):
        safe_io.write_verified(self.p, 'hello\n', must_contain=('hello',))
        self.assertEqual(open(self.p, encoding='utf-8').read(), 'hello\n')

    def test_write_verified_refuses_when_content_missing(self):
        """内容不含必须出现的串 ⇒ **必须抛错**，不能假装写成了。

        至于文件在不在：`write_verified` 是“先写后验”，所以校验失败时
        坏内容**留在原地**（docstring 2026-11-03 补上了这句）。
        第一版这里断言“不该有文件” —— 那是我把“没写”当成了安全。
        真正要钉的是：**异常必须抛出来**，且坏内容是看得见的。
        """
        with self.assertRaises(RuntimeError):
            safe_io.write_verified(self.p, 'nope\n', must_contain=('hello',))
        # 坏内容留在原地，且能看见它 —— 这比静默退回旧内容好
        if os.path.exists(self.p):
            self.assertEqual(open(self.p, encoding='utf-8').read(), 'nope\n')

    def test_append_verified_appends(self):
        safe_io.append_verified(self.p, 'a\n')
        safe_io.append_verified(self.p, 'b\n', must_contain=('b',))
        self.assertEqual(open(self.p, encoding='utf-8').read(), 'a\nb\n')

    def test_patch_at_anchor_replaces(self):
        safe_io.write_verified(self.p, 'head\nANCHOR\ntail\n')
        safe_io.patch_at_anchor(self.p, 'ANCHOR', 'REPLACED')
        self.assertIn('REPLACED', open(self.p, encoding='utf-8').read())
        self.assertNotIn('ANCHOR', open(self.p, encoding='utf-8').read())

    def test_patch_at_anchor_missing_anchor_fails_loudly(self):
        """锚点不在 ⇒ 必须报错。静默跳过会让“我以为改了”变成假的。"""
        safe_io.write_verified(self.p, 'nothing here\n')
        with self.assertRaises(Exception):
            safe_io.patch_at_anchor(self.p, 'ANCHOR', 'X')


if __name__ == '__main__':
    unittest.main()


class EntryCryptoPadding(unittest.TestCase):
    """`device_entry_crypto.decrypt` 的 padding 必须按 **unquote 之后**的长度算。

    2026-11-03 代码审查 P1：旧实现

        base64.b64decode(urllib.parse.unquote(b64) + '=' * (-len(b64) % 4))

    `unquote` 只会缩短字符串（`%2B`→`+`、`%3D`→`=`），
    所以按**编码前**的长度算会**多补** padding —— 实测 29 种原始长度里 15 种算错。

    现在还没炸，是因为 Python 的 `b64decode` 对多余 padding 宽容；
    而 Android 的 `Base64.decode(s, NO_WRAP)` 不宽容。
    “Python 解得开、设备上解不开”是最难查的那一类。

    **这里钉的是算出来的 padding 本身，不是 roundtrip** ——
    否则这条 bug 会因为“恰好还能用”而一直被掩盖。
    """

    def _pad_of(self, quoted):
        """走**真正的代码**（`dec.b64d`），不自己重算。

        第一版在这里重算了一遍 `-len(unquote(q)) % 4` ——
        于是把 `decrypt` 改回旧公式，这条测试照样绿。
        **测了概念，没测代码。**
        """
        raw = dec.b64d(quoted)
        unq = urllib.parse.unquote(quoted)
        # 从 raw 反推补了几个 `=`：能解出来的字节数对应真实长度
        return len(raw), -len(unq) % 4

    def test_padding_follows_unquoted_length(self):
        """`dec.b64d` 补的 padding 必须按 **unquote 之后**的长度算。

        **判据是"传给 b64decode 的那个串"**，不是解出来的字节 ——
        Python 的 `b64decode` 对多余 padding 完全宽容（实测暴力搜索
        几千组随机输入，旧公式一次都没解错），所以从外面看不出区别。
        而 Android 的 `Base64.decode(s, NO_WRAP)` 不宽容。

        第一版这里自己重算了一遍 padding，于是把 `decrypt` 改回旧公式
        测试照样绿 —— **测了概念，没测代码**。
        """
        seen = []
        orig = dec.base64.b64decode

        def spy(s_, *a, **k):
            seen.append(s_)
            return orig(s_, *a, **k)

        dec.base64.b64decode = spy
        try:
            b = b'\xf8' * 7
            b64 = base64.b64encode(b).decode()
            self.assertEqual(b64, '+Pj4+Pj4+A==')
            quoted = urllib.parse.quote(b64, safe='')
            dec.b64d(quoted)
        finally:
            dec.base64.b64decode = orig

        self.assertEqual(seen[-1], '+Pj4+Pj4+A==',
                         '多补了 padding ⇒ 换到 Android 的 Base64 会解不开')

    def test_roundtrip_still_works(self):
        """修完之后 roundtrip 仍然要对（别修坏好的那一半）。"""
        for plain in ('abc', 'YWJjZGVm', 'x' * 7, '', 'entry-token-abc123'):
            e = dec.encrypt(plain)
            self.assertEqual(dec.decrypt(urllib.parse.quote(e, safe='')), plain)
            self.assertEqual(dec.decrypt(e), plain)


if __name__ == '__main__':
    unittest.main()


class TextioGz(unittest.TestCase):
    """`textio.read_lines` —— 四份逐字相同的 `.gz` 读取器收敛到一处之后的行为契约。

    2026-11-03 代码审查 P2："`.gz` 感知读取器 4 份逐字相同"。
    一模一样意味着**改一处要改四处**，而这类读取器是"证据的入口"：
    任何一处漏了 `.gz`，那个工具就会**静默少读一半抓取**。

    这几条同时是 `textio` 自己的规格：四个工具现在都走它，
    它错了四个一起错。
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def test_txt_and_gz_read_the_same(self):
        body = 'alpha\nbeta\ngamma\n'
        p = os.path.join(self.d, 'c.txt')
        open(p, 'w', encoding='utf-8').write(body)
        q = os.path.join(self.d, 'c.txt.gz')
        with gzip.open(q, 'wt', encoding='utf-8') as f:
            f.write(body)
        self.assertEqual(textio.read_lines(p), textio.read_lines(q))
        self.assertEqual(textio.read_lines(q), ['alpha', 'beta', 'gamma'])

    def test_missing_file_raises_not_silent(self):
        """文件不在必须抛 —— **不能返回空 list**。

        空 list 会让调用方得出"这个包里没有这类行"的结论，
        而真相是"文件压根没读到"（今天已经为这种假阴性修过 3 处）。
        """
        with self.assertRaises(OSError):
            textio.read_lines(os.path.join(self.d, 'nope.txt'))
        with self.assertRaises(OSError):
            textio.read_lines(os.path.join(self.d, 'nope.txt.gz'))

    def test_expand_covers_both_globs(self):
        p = os.path.join(self.d, 'c.txt')
        open(p, 'w').write('x\n')
        q = os.path.join(self.d, 'c.txt.gz')
        with gzip.open(q, 'wt') as f:
            f.write('x\n')
        got = textio.expand([os.path.join(self.d, '*.txt'),
                             os.path.join(self.d, '*.txt.gz')])
        self.assertEqual(got, [p, q])


if __name__ == '__main__':
    unittest.main()


class MemreadFallback(unittest.TestCase):
    """`memread` 的两次尝试 —— 特别是“`base64 -w0` 不受支持时要有兜底”。

    2026-11-03 代码审查 P2：“root 读内存 3 份 3 种引号写法”。
    三份不只是写法不同：**只有一份有 `-w0` 的兜底**。
    换一台 `base64` 不支持 `-w`（某些 busybox）的设备时，
    另外两份会**静默返回 `b''`** —— 而 `b''` 与"那个地址没有字节"长得一样。

    这几条用一个假的 `adb` 驱动，不碰真机。
    """

    def setUp(self):
        self.real_adb = memread.adb
        self.calls = []

    def tearDown(self):
        memread.adb = self.real_adb

    def _fake(self, outputs):
        """`outputs` 是每次调用返回的 (stdout, stderr)。"""
        it = iter(outputs)

        def fake(serial, *args, **kw):
            self.calls.append(args)
            try:
                o, e = next(it)
            except StopIteration:
                o, e = '', ''
            return subprocess.CompletedProcess(args, 0, o, e)
        memread.adb = fake

    def test_first_attempt_wins(self):
        self._fake([('QUJD', '')])
        self.assertEqual(memread.read_mem('s', 1, 0x1000, 3), b'ABC')
        self.assertEqual(len(self.calls), 1, '第一次就成功时不该再试第二次')

    def test_falls_back_when_w0_unsupported(self):
        """`-w0` 那遍没输出 ⇒ 必须再试一遍不带 `-w` 的。"""
        self._fake([('', 'base64: unrecognized option'), ('QUJD', '')])
        self.assertEqual(memread.read_mem('s', 1, 0x1000, 3), b'ABC')
        self.assertEqual(len(self.calls), 2, '没有兜底 ⇒ 换台设备就静默返回空')

    def test_both_fail_returns_empty_with_reason(self):
        self._fake([('', 'no su'), ('', 'no su')])
        data, why = memread.read_mem_verbose('s', 1, 0x1000, 3)
        self.assertEqual(data, b'')
        self.assertIn('no su', why, '空结果必须带原因，否则与"地址没字节"无法区分')

    def test_garbage_output_is_reported(self):
        """解出来不是 base64 ⇒ 要说出来，不要当成功。"""
        self._fake([('!!!!not base64!!!!', '')])
        data, why = memread.read_mem_verbose('s', 1, 0x1000, 3)
        self.assertTrue(why, '坏输出必须留下说明')


if __name__ == '__main__':
    unittest.main()


class RedactGzFalseClean(unittest.TestCase):
    """`redact_capture --check` 对 `.gz` **不许**给出假的清白证明。

    2026-11-03：`redact_capture.read_text()` 直接 `open(path)`，于是
    `.txt.gz` 被当成 gzip 二进制读进来。二进制的字节里没有任何凭证模式
    ⇒ `residual()` 返回空 ⇒ `--check` 打印 **“✓ 无残留”**。

    而这是一个**隐私检查**：它说的是“这份抓取可以外传”，
    而真相是“我没读到”。实测同一份内容：

        work/packs/r793/capture.txt      → ✗ 1399 处未脱敏凭证
        work/packs/r793/capture.txt.gz   → ✓ 无残留          ← 修好之前

    "报成功而不报读不到"是今天出现次数最多的缺陷类，这一处最严重：
    它让人以为敏感数据已经清干净了。
    """

    def setUp(self):
        self.d = tempfile.mkdtemp()
        # 一份**确实有凭证**的抓取
        body = ('12:00:00.000 APPSIGN I/KdKit: token=1_XPXQH3c5HRw\n'
                '12:00:00.100 NET I/KdKit: cuid=00000000000000000000000000000000|0\n')
        self.plain = os.path.join(self.d, 'capture.txt')
        open(self.plain, 'w', encoding='utf-8').write(body)
        self.gz = os.path.join(self.d, 'capture.txt.gz')
        with gzip.open(self.gz, 'wt', encoding='utf-8') as f:
            f.write(body)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def test_gz_and_plain_agree(self):
        """两种形态必须给出**同样的**脱敏结论。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'rc', os.path.join(ROOT, 'kit', 'python', 'redact_capture.py'))
        rc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rc)
        a = rc.redact_text(rc.read_text(self.plain))[1]
        b = rc.redact_text(rc.read_text(self.gz))[1]
        self.assertGreater(a, 0, '样本本身要有凭证，否则这条测试什么都没验')
        self.assertEqual(a, b, '.gz 与 .txt 数出来的凭证数不一样 ⇒ 有一边没读到')

    def test_residual_is_not_empty_for_gz(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'rc', os.path.join(ROOT, 'kit', 'python', 'redact_capture.py'))
        rc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rc)
        left = rc.residual(rc.read_text(self.gz))
        self.assertTrue(left, '.gz 抓取查不出残留 ⇒ --check 会打印“无残留”')


if __name__ == '__main__':
    unittest.main()
