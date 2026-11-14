"""`with_lock.py` 的**可重入**与**诊断**必须真的工作（2026-11-09 04:0x 修的真死锁）。

事故：`with_lock --label r3-nd2 -- bash verify.sh` 拿到锁后，`verify.sh` 又"自锁"
（`exec with_lock … -- bash verify.sh`）⇒ 子进程等父进程的锁，永远等不到。
现场证据：`work/program/verify_r3.log` 只有 `[lock] 持有 …：r3-final2` 一行，
**一道门都没跑**；两条链同时卡了 12 分钟才被人 `kill`。

所以这里钉三件事：
  1. **同链重入不阻塞**：父进程持锁时，子进程再套 `with_lock` 立刻跑（且打印"继承"）；
  2. **跨链仍然互斥**：别人持锁时，`--timeout 1` 拿不到 ⇒ rc=3，且**点名持有者**；
  3. **owner 文件**：持锁期间可读（pid/label/since），释放后清掉。

锁文件用 /tmp 下的唯一临时路径，绝不碰 `/tmp/kdkit/run.lock`（那是真链在用的）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'with_lock.py')


class WithLockIsReentrant(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='kdlock-')
        self.lock = os.path.join(self.tmp, 'run.lock')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, args, timeout=30, env=None):
        e = dict(os.environ)
        e.pop('KD_LOCK_HELD', None)          # 测试必须从"未持锁"开始
        e.pop('KD_LOCK_LABEL', None)
        if env:
            e.update(env)
        return subprocess.run([sys.executable, TOOL, '--lock', self.lock, *args],
                              capture_output=True, text=True, timeout=timeout, env=e)

    def test_nested_same_chain_does_not_deadlock(self):
        """父持锁 → 子再套 with_lock：必须秒过（重入），不是 30s 超时。"""
        inner = [sys.executable, TOOL, '--lock', self.lock, '--label', 'inner',
                 '--', sys.executable, '-c', 'print("INNER-RAN")']
        t0 = time.time()
        r = self._run(['--label', 'outer', '--', *inner], timeout=20)
        dt = time.time() - t0
        self.assertEqual(r.returncode, 0, f'rc={r.returncode}\nstderr={r.stderr}')
        self.assertIn('INNER-RAN', r.stdout)
        self.assertIn('继承同链的锁', r.stderr)
        self.assertLess(dt, 15, f'重入花了 {dt:.1f}s ⇒ 还在等锁')

    def test_other_chain_is_excluded_and_named(self):
        """别人持锁 ⇒ rc=3，且错误里点名持有者（否则只能盲等 30 分钟）。"""
        hold = subprocess.Popen(
            [sys.executable, TOOL, '--lock', self.lock, '--label', 'holder',
             '--', sys.executable, '-c', 'import time; time.sleep(6)'])
        try:
            for _ in range(60):
                if os.path.exists(self.lock + '.owner'):
                    break
                time.sleep(0.1)
            r = self._run(['--timeout', '1', '--', sys.executable, '-c', 'print(1)'],
                          timeout=20)
            self.assertEqual(r.returncode, 3, f'rc={r.returncode}\nstderr={r.stderr}')
            self.assertIn('holder', r.stderr)
        finally:
            hold.wait(timeout=30)

    def test_owner_file_written_then_cleared(self):
        """owner 文件：持锁期间有内容；释放后不残留（否则下一次诊断会被骗）。"""
        hold = subprocess.Popen(
            [sys.executable, TOOL, '--lock', self.lock, '--label', 'owner-probe',
             '--', sys.executable, '-c', 'import time; time.sleep(3)'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            rec = None
            for _ in range(60):
                try:
                    with open(self.lock + '.owner', encoding='utf-8') as f:
                        rec = json.load(f)
                    break
                except (OSError, ValueError):
                    time.sleep(0.1)
            self.assertIsNotNone(rec, 'owner 文件从未出现 ⇒ 等锁的人看不到持有者')
            self.assertEqual(rec.get('label'), 'owner-probe')
            self.assertIsInstance(rec.get('pid'), int)
        finally:
            hold.wait(timeout=30)
        self.assertFalse(os.path.exists(self.lock + '.owner'),
                         '进程退出后 owner 文件没清 ⇒ --status 会报假持有者')

    def test_status_reports_free_lock(self):
        """--status 不获取锁，只回答"谁在持有"。"""
        r = self._run(['--status'], timeout=10)
        self.assertEqual(r.returncode, 0)
        rec = json.loads(r.stdout)
        self.assertFalse(rec['held'])
        self.assertIsNone(rec['owner'])


if __name__ == '__main__':
    unittest.main()
