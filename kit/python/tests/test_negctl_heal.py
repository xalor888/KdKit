"""负对照的自愈（`run_negative_controls.py --heal-only`）必须真的工作。

2026-11-09 发现：自愈这段逻辑从 2026-11-05 加入后**从未被单独验证过**。
后果是 `kit/python/kd_api.py.negctl.bak` 从 11-05 一直躺到 11-09，
而 `kd_api.py` 一直停在注入态（`bad = []   # 负对照：故意永不报错`）——
那条 P1 校验（blob 长度对但内容乱码）三天都在**假通过**，症状只是四个单测红。

所以这里造一个探针文件，验证三件事：
  1. `.negctl.bak` 存在 ⇒ `--heal-only` 会把 live 文件还原成备份内容；
  2. 还原后备份被消费（否则下次启动还会"还原"一次旧内容）；
  3. 没有残留时 `--heal-only` 是幂等的（rc=0，不动任何文件）。
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PROBE = os.path.join(HERE, '_heal_probe.txt')
BAK = PROBE + '.negctl.bak'
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'run_negative_controls.py')


class HealLeftoversWorks(unittest.TestCase):

    def setUp(self):
        self._clean()

    def tearDown(self):
        self._clean()

    def _clean(self):
        for p in (PROBE, BAK):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass

    def _run(self):
        p = subprocess.run([sys.executable, TOOL, '--heal-only'],
                           capture_output=True, text=True, cwd=ROOT, timeout=120)
        self.assertEqual(p.returncode, 0, (p.stdout or '') + (p.stderr or ''))
        return (p.stdout or '') + (p.stderr or '')

    def test_heals_and_consumes_the_backup(self):
        with open(PROBE, 'w', encoding='utf-8') as f:
            f.write('INJECTED\n')
        with open(BAK, 'w', encoding='utf-8') as f:
            f.write('CLEAN\n')
        out = self._run()
        with open(PROBE, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'CLEAN\n', '自愈没有把 live 文件还原成备份内容')
        self.assertFalse(os.path.exists(BAK), '还原之后备份必须被消费，否则会反复还原旧内容')
        self.assertIn('_heal_probe.txt', out, f'自愈必须在输出里点名改了什么：{out[:200]}')

    def test_no_backup_is_a_no_op(self):
        with open(PROBE, 'w', encoding='utf-8') as f:
            f.write('UNTOUCHED\n')
        self._run()
        with open(PROBE, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'UNTOUCHED\n', '没有备份时不许改动任何文件')


if __name__ == '__main__':
    unittest.main()
