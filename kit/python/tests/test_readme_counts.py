"""README 里写的"多少个工具/模块"必须与实际一致。

2026-11-04 代码审查 P2：README 说 `kit/python/` 有 **10 个**模块，实际 **28 个**；
说 kit 有"12 个脚本"，实际 `kit/scripts/` 有 **117 个 .py + 12 个 .sh**。

数字过期的危害不是"读者少知道几个模块"，而是**读者据此判断"这个套件多大、
值不值得读"** —— 10 个模块听起来一晚上能看完，28 个是另一回事。

这个测试把 README 的说法与磁盘上的实际情况并排比。
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def readme():
    return open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()


class CountsMatchDisk(unittest.TestCase):

    def test_python_modules_count(self):
        want = len(glob.glob(os.path.join(ROOT, 'kit', 'python', '*.py')))
        # 注意：这一段在 README 的表格里，`kit/python/` 后面紧跟一个 `|` 列分隔符 ——
        # 第一版把 `|` 排除了，于是**永远匹配不到**（而"匹配不到"看起来像"没写"）。
        m = re.search(r'`kit/python/`[^\n]*?等\s*(\d+)\s*个模块', readme())
        self.assertIsNotNone(m, 'README 里找不到 `kit/python/` 的模块数')
        self.assertEqual(int(m.group(1)), want,
                         f'README 说 {m.group(1)} 个模块，磁盘上 {want} 个')

    def test_scripts_count(self):
        py = len(glob.glob(os.path.join(ROOT, 'kit', 'scripts', '*.py')))
        sh = len(glob.glob(os.path.join(ROOT, 'kit', 'scripts', '*.sh')))
        m = re.search(r'(\d+)\s*个 python 工具\s*\+\s*(\d+)\s*个 shell 脚本', readme())
        self.assertIsNotNone(m, 'README 里找不到工具/脚本数')
        self.assertEqual(int(m.group(1)), py,
                         f'README 说 {m.group(1)} 个 python 工具，磁盘上 {py} 个')
        self.assertEqual(int(m.group(2)), sh,
                         f'README 说 {m.group(2)} 个 shell 脚本，磁盘上 {sh} 个')


if __name__ == '__main__':
    unittest.main()
