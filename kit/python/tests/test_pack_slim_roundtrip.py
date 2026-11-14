#!/usr/bin/env python3
"""
Offline tests: `pack_slim.roundtrip_ok` — 删原文之前必须证明 .gz 解压回来一样。

Why this file exists
--------------------
2026-11-03 代码审查 P1：

> `pack_slim.py:46-49` gzip 写完立即删原文且不校验

旧实现 `gzip.open(...)` 写完就 `os.remove(p)`。压缩成功 ≠ 内容对：
磁盘满、写入被截断、读取方与 compresslevel 不匹配时，拿到的是一个
**打不开或内容不全的 .gz**，而原文已经没了 —— 永久丢失一份证据，只为省几百 MB。

判据是"解压回来的字节与原文逐字节相同"，**不是**"文件存在且非空"：
后者证不了内容。今天已经在 `check_capture_claimed` /
`verify_membership.pull_capture` / `device_backup` 三次遇到
"有文件但内容不是那回事"这一类。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import gzip
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', '..', 'scripts', 'pack_slim.py')


def _tool():
    spec = importlib.util.spec_from_file_location('pack_slim', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class RoundtripOk(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _tool()

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.orig = os.path.join(self.d, 'capture.txt')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.d, ignore_errors=True)

    def _write_gz(self, body):
        with open(self.orig, 'wb') as f:
            f.write(body)
        with gzip.open(self.orig + '.gz', 'wb', compresslevel=9) as f:
            f.write(body)

    def test_good_gzip_passes(self):
        self._write_gz(b'hello capture line\n' * 5000)
        self.assertTrue(self.t.roundtrip_ok(self.orig))

    def test_truncated_gzip_fails(self):
        """截断的 .gz 必须判不通过 —— 原文因此被保留。"""
        body = b'hello capture line\n' * 5000
        with open(self.orig, 'wb') as f:
            f.write(body)
        with gzip.open(self.orig + '.gz', 'wb') as f:
            f.write(body)
        with open(self.orig + '.gz', 'rb') as _f:
            raw = _f.read()
        open(self.orig + '.gz', 'wb').write(raw[:len(raw) // 2])   # 拦腰截断
        self.assertFalse(self.t.roundtrip_ok(self.orig))

    def test_corrupt_gzip_fails(self):
        body = b'x' * 10000
        with open(self.orig, 'wb') as f:
            f.write(body)
        with gzip.open(self.orig + '.gz', 'wb') as f:
            f.write(body)
        raw = bytearray(open(self.orig + '.gz', 'rb').read())
        raw[len(raw) // 2] ^= 0xFF                       # 翻一个字节
        open(self.orig + '.gz', 'wb').write(bytes(raw))
        self.assertFalse(self.t.roundtrip_ok(self.orig))

    def test_missing_gzip_fails(self):
        """没有 .gz 也要判不通过（不能因为"文件不在"就放行）。"""
        with open(self.orig, 'wb') as f:
            f.write(b'nothing compressed')
        self.assertFalse(self.t.roundtrip_ok(self.orig))

    def test_content_mismatch_fails(self):
        """.gz 能解压但内容不同 ⇒ 不通过。这正是"存在且非空"证不了的那一类。"""
        with open(self.orig, 'wb') as f:
            f.write(b'original')
        with gzip.open(self.orig + '.gz', 'wb') as f:
            f.write(b'different')
        self.assertFalse(self.t.roundtrip_ok(self.orig))


if __name__ == '__main__':
    unittest.main()
