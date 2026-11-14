#!/usr/bin/env python3
"""
Offline tests: `device_backup.backup_capture` must produce a **real capture**.

Why this file exists
--------------------
2026-11-03 代码审查 P1 点名两处破坏性操作：

> `coldstart_snapshot.py:50` / `path_diff.py:49` `rm -f` 设备上的累积抓取（不备份）

两个脚本都要"只看这一次冷启动写了什么"，于是删掉设备上的 `kdkit_capture.txt`。
用意没错，但那个文件是**不可再生的证据** —— 删了就没了。

修法是删之前先拉一份到本地。而"拉一份"这件事本身也可能静默失败
（今天已经在 `check_capture_claimed` / `verify_membership.pull_capture`
修过两次"adb 的错误信息冒充成抓取内容"）。所以备份产物也要被断言：

* 文件必须存在且非空；
* 内容必须**真被 capture_schema 认领**，而不是一句 `adb: device not found`；
* 两代（当前 + `.prev.txt`）都要拉 —— 模块轮转会把当前累积挪去 `.prev.txt`。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'python'))
import sh  # noqa: E402
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, '..', '..')
TOOL = os.path.join(KIT, 'python', 'device_backup.py')
SERIAL = os.environ.get('KD_TEST_SERIAL', 'emulator-5558')


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@unittest.skipUnless(os.environ.get('KD_TEST_SERIAL'),
                     '需要真机：设 KD_TEST_SERIAL=<serial> 才跑（默认跳过，不假装验过）')
class BackupProducesRealCapture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db = _mod('device_backup', TOOL)
        cls.dir = cls.db.backup_capture(SERIAL, verbose=False)
        if cls.dir is None:
            raise unittest.SkipTest(f'{SERIAL} 上没有抓取可备份')

    def test_files_exist_and_nonempty(self):
        names = os.listdir(self.dir)
        self.assertIn('kdkit_capture.txt', names)
        for n in names:
            with open(os.path.join(self.dir, n), encoding='utf-8', errors='replace') as _f:
                body = _f.read()
            self.assertTrue(body.strip(), f'{n} 是空的')

    def test_content_is_a_capture_not_an_adb_error(self):
        """备份内容必须是真抓取 —— 不能是一句 `adb: device not found`。

        这条与 `check_capture_claimed` / `verify_membership.pull_capture` 里
        修的守卫是同一个理由：**失败步骤的输出冒充成证据**。
        """
        sys.path.insert(0, os.path.join(KIT, 'python'))
        import capture_schema as cs
        p = os.path.join(self.dir, 'kdkit_capture.txt')
        kinds = {r.kind for r in cs.iter_records(p)}
        self.assertTrue(kinds - {'UNKNOWN'},
                        f'备份里一个 kind 都没解析出来 ⇒ 它大概不是抓取：{sorted(kinds)}')
        self.assertNotIn('adb: device', open(p, encoding='utf-8',
                                             errors='replace').read(200))

    def test_second_call_does_not_overwrite(self):
        """再调一次必须生成**另一个**目录 —— 备份不许互相覆盖。"""
        d2 = self.db.backup_capture(SERIAL, verbose=False)
        self.assertIsNotNone(d2)
        self.assertNotEqual(d2, self.dir)
        self.assertTrue(os.path.isdir(d2))


class PullContract(unittest.TestCase):
    """`pull` 对离线设备必须给空串，不能把错误信息当内容。"""

    @classmethod
    def setUpClass(cls):
        cls.db = _mod('device_backup', TOOL)

    def test_offline_serial_gives_empty(self):
        out = self.db.pull('emulator-7777', '/data/data/x/files/y.txt')
        self.assertEqual(out, '',
                         'adb 的错误信息不能当成文件内容 —— '
                         '今天已经在两处修过同一类问题')


if __name__ == '__main__':
    unittest.main()


class ShAcceptsListAndString(unittest.TestCase):
    """`sh.run()` / `sh.sh()` 必须**同时**收 list 与 str。

    2026-11-03 差点因此毁掉 acceptance：那 12 个文件里的本地
    `sh(cmd, …)` 一向是 `subprocess.run(cmd, shell=isinstance(cmd, str), …)`
    —— **传 list 时不过 shell**，直接 exec。而 `kit/python/sh.py`
    的 `Popen(shell=True)` 对 list 会把第一个元素当命令串、其余当 `$0/$1…`
    ⇒ `adb` 收不到参数 ⇒ 打印自己的版本号 ⇒ 13 条真机断言**全部**变成
    `sdk=Android Debug Bridge version 1.0.41`。

    "同名不同契约"正是今天反复修的那一类。
    """

    def test_list_is_quoted_into_one_shell_string(self):
        got = sh._as_shell(['adb', '-s', 'emulator-5558', 'shell',
                            'getprop', 'ro.build.version.sdk'])
        self.assertIsInstance(got, str)
        self.assertTrue(got.startswith('adb -s emulator-5558 shell getprop '))

    def test_string_passes_through(self):
        self.assertEqual(sh._as_shell('adb devices'), 'adb devices')

    def test_embedded_space_gets_quoted(self):
        got = sh._as_shell(['echo', 'hello world'])
        self.assertIn('"hello world"', got)

    def test_timeout_kills_the_whole_group(self):
        """2026-11-02 的那个泄漏：`sleep 300 | cat` + timeout=2。

        必须**约 2 秒**返回，且不留 `sleep` 进程。
        """
        import subprocess
        t0 = time.time()
        rc, out = sh.run('sleep 300 | cat', timeout=2)
        dt = time.time() - t0
        self.assertLess(dt, 10, f'耗时 {dt:.1f}s ⇒ 没杀干净')
        self.assertEqual(rc, 124)
        leaked = subprocess.run(['pgrep', '-f', 'sleep 300'],
                                capture_output=True, text=True, timeout=30).stdout.split()
        self.assertEqual(leaked, [], '管道里的子进程还活着 ⇒ timeout 是假有界')


if __name__ == '__main__':
    unittest.main()
