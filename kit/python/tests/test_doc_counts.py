"""文档里写的"多少个功能 / 多少条钩子"必须与实际一致。

2026-11-05 代码审查 P3：同一批数字在四处各写一遍，而且**每一处都是错的**：

| 文档 | 说 | 实际 |
|---|---|---|
| `README.md` 工程规模表 | 28 条钩子目标 | **139**（2026-11-14：新增会员推广与皮肤后从 126 涨到 139） |
| `kit/scripts/feature_matrix.py:5` | 18 features | **40** |
| `kit/scripts/module_activity.py:31` | 11 of 28 | **40** |
| `kit/scripts/module_activity.py:13` | 15 of 28 | **40** |

危害不是"读者少知道几个数"，而是**读者据此判断"这个套件多大、值不值得信"** ——
28 个功能听起来"覆盖得差不多"，38 个是另一回事。

这个测试把三个数都钉在**唯一事实源**上：

* 功能数 ⇒ `FeatureRegistry.all` 的条目数（Kotlin 源里数）；
* 钩子签名数 ⇒ 运行 `check_hook_signatures.py` 的输出；
* 钩子目标数 ⇒ 运行 `check_hook_targets.py` 的输出。

后两个要跑脚本（各约 15 秒），所以只在 `KDKIT_SLOW_TESTS=1` 时跑 ——
默认跳过，但**跳过数是登记过的**（见 `check_skip_budget.py`）。
"""
import glob
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def registry_count():
    """`FeatureRegistry.all` 里的条目数 —— 唯一事实源。"""
    p = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev',
                     'xalor', 'kdkit', 'features', 'FeatureRegistry.kt')
    src = open(p, encoding='utf-8').read()
    m = re.search(r'val all[^=]*=\s*listOf\(', src)
    # 用括号配平取 listOf(...) 的**完整** body（第一版用正则 `\(.*?\)`，
    # 遇到带默认参数的构造调用就提前收尾 ⇒ 数出 39）。
    i = m.end()
    depth = 1
    j = i
    while j < len(src) and depth > 0:
        if src[j] == '(':
            depth += 1
        elif src[j] == ')':
            depth -= 1
        j += 1
    body = src[i:j - 1]
    # 真条目 = 形如 `        SomeFeature,` 的整行（不数注释、不数参数）
    return len([l for l in body.split('\n')
                if re.fullmatch(r'\s+\w+,?\s*', l) and l.strip()])


class DocNumbersMatchCode(unittest.TestCase):

    def test_registry_has_41(self):
        self.assertEqual(registry_count(), 41,
                         'FeatureRegistry.all 的条目数变了 ⇒ 改所有文档里的数')

    def test_readme_hook_target_count(self):
        want = registry_count()
        src = open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()
        m = re.search(r'把\s*(\d+)\s*条钩子目标', src)
        self.assertIsNotNone(m, 'README 里找不到"N 条钩子目标"')
        got = int(m.group(1))
        self.assertEqual(got, 159,
                         f'README 说 {got} 条钩子目标；常量是 159（下文 slow 测会与实跑对比）')

    def test_feature_matrix_docstring(self):
        src = open(os.path.join(ROOT, 'kit', 'scripts', 'feature_matrix.py'),
                   encoding='utf-8').read()
        m = re.search(r'The module has (\d+) features', src)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), registry_count(),
                         'feature_matrix 的 docstring 功能数与注册表不一致')

    def test_module_activity_docstring(self):
        src = open(os.path.join(ROOT, 'kit', 'scripts', 'module_activity.py'),
                   encoding='utf-8').read()
        for m in re.finditer(r'\b(\d+)\s+of\s+(\d+)\b', src):
            total = int(m.group(2))
            self.assertEqual(total, registry_count(),
                             f'module_activity 里的 "N of {total}" 与注册表不一致')

    @unittest.skipUnless(os.environ.get('KDKIT_SLOW_TESTS') == '1',
                         '慢测试（~30s）：设 KDKIT_SLOW_TESTS=1 才跑')
    def test_hook_counts_match_the_real_runs(self):
        """实跑 ④/⑤，把它们的数与 README 里的数对上。"""
        def run(script):
            p = subprocess.run([sys.executable, os.path.join(ROOT, 'kit', 'scripts', script)],
                               capture_output=True, text=True, timeout=600, cwd=ROOT)
            return (p.stdout or '') + (p.stderr or '')

        sig = run('check_hook_signatures.py')
        m = re.search(r'\[sig\]\s*(\d+) hooks', sig)
        self.assertIsNotNone(m, sig[:300])
        hooks = int(m.group(1))

        tgt = run('check_hook_targets.py')
        m2 = re.search(r'(\d+)\s*个目标', tgt)
        self.assertIsNotNone(m2, tgt[:300])
        targets = int(m2.group(1))

        readme = open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()
        m3 = re.search(r'(\d+)\s*条钩子目标、(\d+)\s*条钩子签名', readme)
        self.assertIsNotNone(m3, 'README 里没有"N 条钩子目标、M 条钩子签名"')
        self.assertEqual(int(m3.group(1)), targets,
                         f'README 说 {m3.group(1)} 条目标，实跑 {targets}')
        self.assertEqual(int(m3.group(2)), hooks,
                         f'README 说 {m3.group(2)} 条签名，实跑 {hooks}')


if __name__ == '__main__':
    unittest.main()
