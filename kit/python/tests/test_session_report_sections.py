"""`session_report.py` 的 docstring 章节表必须与代码实际输出的章节一一对应。

2026-11-04 代码审查 P2：docstring 写的是 **1..9**，代码的章节是 **0..9**。
docstring 少算了"0 宿主版本"，于是从第 1 项起**每个名字都对到了下一节的内容上**。

这种错误比"整段写错"更难发现 —— **每一条单独看都像个合理的描述**，
只有把两份列表并排放才看得出来。所以这里把两份列表并排放。
"""
import ast
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', 'session_report.py')


def code_sections():
    """代码里 `w(f'## N. …')` 出现的全部章节号。"""
    src = open(TOOL, encoding='utf-8').read()
    return sorted({int(m) for m in re.findall(r"w\(f?'## (\d+)\.", src)})


def doc_sections():
    """docstring 里 `编号  名字` 形式的章节号。"""
    tree = ast.parse(open(TOOL, encoding='utf-8').read())
    doc = ast.get_docstring(tree) or ''
    return sorted({int(m) for m in re.findall(r'^\s{2}(\d+)\s{2,}\S', doc, re.M)})


class DocMatchesCode(unittest.TestCase):

    def test_numbers_are_identical(self):
        self.assertEqual(doc_sections(), code_sections(),
                         'docstring 的章节号与代码里 `## N.` 的不一致')

    def test_no_gaps_in_code(self):
        nums = code_sections()
        self.assertEqual(nums, list(range(min(nums), max(nums) + 1)),
                         f'代码章节号有跳号：{nums}')

    def test_starts_at_zero(self):
        """这份报告是 0 基数的。docstring 若从 1 开始，整份就偏移一位。"""
        self.assertEqual(code_sections()[0], 0)
        self.assertEqual(doc_sections()[0], 0)

    def test_every_doc_row_has_a_name(self):
        tree = ast.parse(open(TOOL, encoding='utf-8').read())
        doc = ast.get_docstring(tree) or ''
        rows = re.findall(r'^\s{2}(\d+)\s{2,}(\S.*)$', doc, re.M)
        self.assertTrue(rows)
        for num, name in rows:
            self.assertTrue(name.strip(), f'第 {num} 节没有名字')


if __name__ == '__main__':
    unittest.main()
