#!/usr/bin/env python3
"""
README 承诺的产物必须**真的被生成**（2026-11-02，扩展队列第一条）。

缺陷回顾
--------
`kit/README.md` 写着 `evidence_pack.py` 会写出：

    work/packs/<tag>/{capture.txt,session_report.md,module_report.md,acceptance.{txt,json},
                      device_compare.md,index.md}

`evidence_pack.py` 的文件头也复述了同一个承诺。实际上：

* `device_compare.md` **从来没有被生成过** —— `--adb-b` 只被用来在 index 里多打一个设备名
  （`evidence_pack.py:626` / `:657`），从来没有真的调用 `compare_devices.py`；
* 于是 README 里的那行 `--adb-b emulator-5556` 是个**装饰**。

这类"文档承诺、代码没做"的缺陷最难发现：命令照抄能跑，产物少一个也看不出来，
只有真去 `ls` 那个目录才会发现。所以这里把它变成**可判定的测试**。

判据（不看措辞，看代码里有没有对应的调用）
------------------------------------------
对 README 列出的每个产物名，断言 `evidence_pack.py` 里出现该名字；
另外单独断言 `compare_devices.py` 被**以 run(...) 形式调用** —— 因为它最容易退化成
"只出现在字符串里"。
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_PY = os.path.dirname(HERE)          # kit/python
ROOT = os.path.dirname(os.path.dirname(KIT_PY))   # kit/python → kit → 仓库根
KIT_README = os.path.join(ROOT, 'kit', 'README.md')
PACK = os.path.join(ROOT, 'kit', 'scripts', 'evidence_pack.py')


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


class CatalogueIsHonest(unittest.TestCase):

    def test_readme_pack_outputs_appear_in_the_generator(self):
        readme = read(KIT_README)
        # 取 README 里那段 `#  -> work/packs/r37/{a,b,c}` 的花括号列表
        m = re.search(r'work/packs/r\d+/\{([^}]+)\}', readme)
        self.assertIsNotNone(m, 'README 里找不到 pack 产物清单（格式变了？）')
        names = [n.strip() for n in m.group(1).split(',') if n.strip()]
        self.assertGreater(len(names), 3, f'产物清单太短，解析错了: {names}')

        src = read(PACK)
        missing = []
        for n in names:
            # `acceptance.{txt,json}` 这种嵌套花括号先展开
            mm = re.fullmatch(r'([^{]+)\{([^}]+)\}', n)
            parts = ([f'{mm.group(1)}{x.strip()}' for x in mm.group(2).split(',')]
                     if mm else [n])
            for part in parts:
                stem = part.split('.')[0]
                if stem not in src:
                    missing.append(part)
        self.assertEqual(
            missing, [],
            'README 承诺了这些产物，但 evidence_pack.py 里连名字都没出现：'
            f'{missing}\n要么真的生成它，要么把 README 的承诺改掉。',
        )

    def test_device_compare_is_actually_invoked(self):
        """
        `device_compare.md` 是这条规矩的**现行犯**：文档列了它，代码从没生成它。
        所以额外钉一条：必须存在对 `compare_devices.py` 的 run(...) 调用，
        而不是只在注释或 summary 字符串里提一嘴。
        """
        src = read(PACK)
        calls = re.findall(r'run\(\s*f?[\'"][^\'"]*compare_devices\.py[^\'"]*[\'"]', src)
        self.assertTrue(
            calls,
            'evidence_pack.py 里没有对 compare_devices.py 的 run(...) 调用 —— '
            '`--adb-b` 又变回装饰参数了，而 README 仍会承诺 device_compare.md',
        )

    def test_compare_devices_command_line_arguments_exist(self):
        """被调用时用的参数，`compare_devices.py` 必须真的接受。"""
        src = read(PACK)
        m = re.search(r'run\(\s*f?[\'"]python3 \{HERE\}/compare_devices\.py([^\'"]*)[\'"]', src)
        if not m:
            self.skipTest('没有 compare_devices 调用（上一条会报）')
        flags = set(re.findall(r'(--[a-z-]+)', m.group(1)))
        target = read(os.path.join(ROOT, 'kit', 'scripts', 'compare_devices.py'))
        for f in flags:
            self.assertIn(f"'{f}'", target,
                          f'evidence_pack 传了 {f}，但 compare_devices.py 不接受它')


if __name__ == '__main__':
    unittest.main()
