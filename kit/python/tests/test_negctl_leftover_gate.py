#!/usr/bin/env python3
"""
Offline tests: `check_negctl_leftovers.py` must go red on an injected tree, stay quiet
on a clean one, and **not** mistake "another chain is mid-run" for "the last chain died".

Why this file exists
--------------------
2026-11-05 → 11-09：`kit/python/kd_api.py.negctl.bak` 躺了三天，而 `kd_api.py` 一直是
注入态（`bad = []`）。P1 校验三天假通过，唯一症状是四条单测红 —— 与病状不像。

新门禁 ㉰ 要防的正是这件事，但"`find . -name '*.negctl.bak'`" 那种写法有三个看不见的坑，
而三处都只能在代码里钉住：

1. 扫到 `work/archive/` 就**永远红**（那里按规矩保留历史文件名）；
2. 只报"有残留"而不区分"源文件还在"与"**源文件被吞了**"——后者要恢复，前者只要还原；
3. **正在跑**与**崩了**在文件系统上长得一模一样（都是一对 `.bak` + 活文件）。
   2026-09 实测撞上过：另一条链的 ㉖ 正在注入时，扫残留会假红 40 秒。

第 3 条靠 `kit/python/negctl_state.py` 的"在跑标记"（pid + 开始时间）区分：
标记 + 活 pid ⇒ 等；标记 + 死 pid ⇒ 红（那就是"倒在中途"的形状）。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', '..', 'scripts', 'check_negctl_leftovers.py')


def _tool():
    spec = importlib.util.spec_from_file_location('check_negctl_leftovers', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class LeftoverGate(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _tool()
        cls.state = cls.t.negctl_state

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='negctl-gate-')
        self.marker = os.path.join(self.root, 'inflight.json')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _touch(self, rel, text='x'):
        path = os.path.join(self.root, rel)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def _main(self, wait=0):
        return self.t.main(['--root', self.root, '--marker', self.marker,
                            '--wait', str(wait), '--quiet'])

    # ── 基本判据 ────────────────────────────────────────────────────────────

    def test_clean_tree_passes(self):
        """干净树 ⇒ 无命中，退出码 0。"""
        self._touch('kit/python/kd_api.py')
        self._touch('module/app/src/main/java/foo/Bar.kt')
        self.assertEqual(self.t.scan(self.root), [])
        self.assertEqual(self._main(), 0)

    def test_leftover_is_red(self):
        """有 .negctl.bak ⇒ 退出码 1，且点名备份与源文件。"""
        self._touch('kit/python/kd_api.py')
        self._touch('kit/python/kd_api.py.negctl.bak')
        hits = self.t.scan(self.root)
        self.assertEqual([h['bak'] for h in hits],
                         [os.path.join('kit', 'python', 'kd_api.py.negctl.bak')])
        self.assertTrue(hits[0]['live_exists'])
        self.assertEqual(self._main(), 1)

    def test_missing_source_is_distinguished(self):
        """备份还在、源文件没了 ⇒ live_exists=False（要恢复，不只是还原）。"""
        self._touch('kit/python/gone.py.negctl.bak')
        hits = self.t.scan(self.root)
        self.assertEqual(len(hits), 1)
        self.assertFalse(hits[0]['live_exists'])

    def test_archive_is_not_scanned(self):
        """work/archive 里的历史文件名不算残留（只在活代码树里找）。"""
        self._touch('work/archive/old.py.negctl.bak')
        self._touch('kit/python/kd_api.py')
        self.assertEqual(self.t.scan(self.root), [])

    def test_module_tree_is_scanned(self):
        """module/ 也要扫 —— 负对照同样会往 Kotlin 源码上注入。"""
        self._touch('module/app/src/main/java/foo/Bar.kt')
        self._touch('module/app/src/main/java/foo/Bar.kt.negctl.bak')
        hits = self.t.scan(self.root)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]['live_exists'])

    # ── 第 3 条：正在跑 ≠ 崩了 ──────────────────────────────────────────────

    def test_live_marker_makes_it_unverifiable_not_red(self):
        """另一条链正在跑（pid 活着）⇒ 退出码 2（无法验证），**不是红**。"""
        self._touch('kit/python/kd_api.py')
        self._touch('kit/python/kd_api.py.negctl.bak')
        self.state.write_marker(['㉖ 负对照总检'], path=self.marker, pid=os.getpid())
        self.assertEqual(self._main(wait=0), 2,
                         '正在注入的窗口里判红，会训练人忽略门禁')

    def test_dead_marker_with_residue_is_red(self):
        """标记在、pid 死了、还有残留 ⇒ 红（"倒在中途"的形状）。"""
        self._touch('kit/python/kd_api.py')
        self._touch('kit/python/kd_api.py.negctl.bak')
        # 999999 在本机不会存在；用"活着但已陈旧"的两条都测一遍更稳，这里用死 pid。
        self.state.write_marker(['㉖ 负对照总检'], path=self.marker, pid=999999)
        self.assertEqual(self._main(wait=0), 1)

    def test_stale_marker_is_not_treated_as_running(self):
        """pid 活着但标记太旧 ⇒ 当陈旧（防 pid 复用把死进程看活）。"""
        self.state.write_marker(['x'], path=self.marker, pid=os.getpid(),
                                started=1.0)
        self.assertIsNone(self.state.active_pid(self.marker),
                          '30 分钟前的标记不可能是"还在跑"')

    def test_clean_with_stale_marker_still_passes(self):
        """无残留 + 陈旧标记 ⇒ 绿（标记该清，但不是门禁要红的事）。"""
        self._touch('kit/python/kd_api.py')
        self.state.write_marker(['x'], path=self.marker, pid=999999)
        self.assertEqual(self._main(), 0)

    def test_corrupt_marker_is_unverifiable(self):
        """标记读不出 ⇒ 退出码 2（门禁不该因为标记坏了而崩或假绿）。"""
        self._touch('kit/python/kd_api.py')
        with open(self.marker, 'w', encoding='utf-8') as f:
            f.write('{not json')
        self.assertEqual(self._main(wait=0), 2)
        self.assertTrue(self.state.read_marker(self.marker)['corrupt'])


if __name__ == '__main__':
    unittest.main()
