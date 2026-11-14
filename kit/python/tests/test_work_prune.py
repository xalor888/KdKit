"""`work_prune.py` 必须能**安全地预演**，并且**绝不碰**保护目录。

2026-11-09 满盘事故（460 GB 用到 435 GB、只剩 126 MiB）之后加的归档工具。
它一动就会删目录，所以判据必须是硬的：

  1. 默认（无 `--apply`）只预演，**一个字节都不动**；
  2. `--apply` 只归档 `work/packs/*`，**永不动** `work/apktool_out` / `work/baselines`；
  3. 归档后必须留下 MANIFEST（原路径 → tar 内成员数/字节数），否则"归档"等于"消失"；
  4. 已在阈值内时**不动作**（不许"顺手清理一下"）。

跑法是 `--root <临时目录>`，所以这组测试完全不碰真仓库。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'work_prune.py')


class WorkPruneIsSafe(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='kdprune-')
        self.packs = os.path.join(self.tmp, 'work', 'packs')
        os.makedirs(os.path.join(self.packs, 'old_pack'))
        os.makedirs(os.path.join(self.packs, 'new_pack'))
        os.makedirs(os.path.join(self.tmp, 'work', 'apktool_out'))
        os.makedirs(os.path.join(self.tmp, 'work', 'baselines'))
        # old_pack 很大、new_pack 很小；apktool_out 也很大（必须被保护）
        self._write(os.path.join(self.packs, 'old_pack', 'capture.txt'), 3_000_000, old=True)
        self._write(os.path.join(self.packs, 'new_pack', 'capture.txt'), 10_000)
        self._write(os.path.join(self.tmp, 'work', 'apktool_out', 'x.smali'), 3_000_000)
        self._write(os.path.join(self.tmp, 'work', 'baselines', 'input.json'), 100)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, n, old=False):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('x' * n)
        if old:
            os.utime(path, (1_000_000, 1_000_000))
            os.utime(os.path.dirname(path), (1_000_000, 1_000_000))

    def _run(self, *args):
        p = subprocess.run([sys.executable, TOOL, '--root', self.tmp] + list(args),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout or '') + (p.stderr or '')

    def test_dry_run_touches_nothing(self):
        rc, out = self._run('--target-mb', '1')
        self.assertEqual(rc, 0, out)
        self.assertIn('计划归档', out)
        self.assertTrue(os.path.isdir(os.path.join(self.packs, 'old_pack')),
                        '预演阶段不许删任何目录')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'work', 'archive')),
                         '预演阶段不许写归档')

    def test_apply_archives_packs_and_protects_never_dirs(self):
        rc, out = self._run('--target-mb', '1', '--apply')
        self.assertEqual(rc, 0, out)
        arc = os.path.join(self.tmp, 'work', 'archive', 'packs', 'old_pack.tar.gz')
        self.assertTrue(os.path.exists(arc), f'归档不存在：{out[-300:]}')
        self.assertFalse(os.path.isdir(os.path.join(self.packs, 'old_pack')),
                         '归档成功之后源目录应被移除')
        # 保护目录必须原样
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'work', 'apktool_out')))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'work', 'baselines')))
        # MANIFEST 必须写
        man = [f for f in os.listdir(os.path.join(self.tmp, 'work', 'archive'))
               if f.startswith('MANIFEST-')]
        self.assertTrue(man, '归档必须留 MANIFEST（否则等于让证据消失）')
        with open(os.path.join(self.tmp, 'work', 'archive', man[0]), encoding='utf-8') as f:
            data = json.load(f)
        self.assertTrue(data['items'])
        self.assertIn('old_pack', data['items'][0]['src'])
        self.assertGreater(data['items'][0]['members'], 0)

    def test_within_target_does_nothing(self):
        rc, out = self._run('--target-mb', '100', '--apply')
        self.assertEqual(rc, 0, out)
        self.assertIn('已在限内', out)
        self.assertTrue(os.path.isdir(os.path.join(self.packs, 'old_pack')))


if __name__ == '__main__':
    unittest.main()
