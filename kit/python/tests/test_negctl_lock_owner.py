"""㉰ 的"另一条链正在跑"判据：锁的 **owner** 记录优先于"标记文件看没看见"。

## 为什么（2026-11-09 04:54 实测一次假红）

另一条链正在注入、`.bak` 在树上，而 `work/.negctl.inflight` 那一瞬读不到
（被清掉 / 恰好不可读）⇒ ㉰ 把它读成"上一轮倒在中途" ⇒ **rc=1 假红**。
假红是门禁最贵的失败：它训练人忽略门禁（《PARADIGM》§7 的原话）。

判据改成"锁的持有者是谁"：`with_lock.py` 会写 `<lock>.owner`（pid/label/cmd），
这个文件跨进程、跨语言都看得见，而 `KD_NEGCTL` 环境变量跨不了层。

## 三件事被钉住

1. owner 是 `negctl`（且 pid 活着）+ 有 `.bak` ⇒ **rc=2 无法验证**（不是红）；
2. owner 是别人（例如 `verify`）+ 有 `.bak` ⇒ 仍然是 **rc=1 红**（那才是真残留）；
3. 没有 owner + 有 `.bak` ⇒ **rc=1 红**（上一轮真的没善终）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'check_negctl_leftovers.py')


class LockOwnerDecides(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='kd-leftovers-')
        self.tree = os.path.join(self.dir, 'kit', 'src')
        os.makedirs(self.tree)
        self.live = os.path.join(self.tree, 'a.py')
        self.bak = self.live + '.negctl.bak'
        with open(self.live, 'w', encoding='utf-8') as f:
            f.write('bad = []   # 注入态\n')
        with open(self.bak, 'w', encoding='utf-8') as f:
            f.write('good = []\n')
        self.marker = os.path.join(self.dir, '.negctl.inflight')
        self.lock = os.path.join(self.dir, 'run.lock')

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _owner(self, pid, label, cmd=''):
        with open(self.lock + '.owner', 'w', encoding='utf-8') as f:
            json.dump({'pid': pid, 'label': label, 'since': '2026-11-09 04:54:00',
                       'cmd': cmd}, f, ensure_ascii=False)

    def _run(self):
        p = subprocess.run(
            [sys.executable, TOOL, '--root', self.dir, '--marker', self.marker,
             '--lock', self.lock, '--wait', '0'],
            capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout + p.stderr

    def test_negctl_owner_means_cannot_verify(self):
        self._owner(os.getpid(), 'negctl',
                    '/usr/bin/python3 kit/scripts/run_negative_controls.py --force')
        rc, out = self._run()
        self.assertEqual(rc, 2, f'期望"无法验证"(2)，实际 {rc}\n{out}')
        self.assertIn('无法验证', out)

    def test_other_owner_still_red(self):
        self._owner(os.getpid(), 'verify', 'bash module/scripts/verify.sh')
        rc, out = self._run()
        self.assertEqual(rc, 1, f'验证链持锁时残留仍是真红\n{out}')

    def test_dead_negctl_owner_still_red(self):
        """owner 记录里的 pid 已死 ⇒ 那是"倒在中途"的尸体，必须红。"""
        self._owner(999999999, 'negctl',
                    'python3 kit/scripts/run_negative_controls.py --force')
        rc, out = self._run()
        self.assertEqual(rc, 1, f'死 pid 的 owner 不能当"正在跑"\n{out}')


if __name__ == '__main__':
    unittest.main()
