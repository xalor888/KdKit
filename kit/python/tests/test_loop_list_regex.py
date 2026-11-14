#!/usr/bin/env python3
"""
`LOOP_LIST_RE` 的括号嵌套 —— 同一类缺陷的第三个实例。

## 背景

`for (x in listOf("a", "b")) { Xp.hook(x, …) }` 这种写法让门禁能追踪循环里的钩子。
识别它的正则是 `for\\s*\\(\\s*(\\w+)\\s+in\\s+listOf\\(([^)]*)\\)\\s*\\)`，
而 `[^)]*` 会在**第一个右括号**停下。

换成 `listOf(clazzOrNull("x.Y").name, "d.e.F")` 时整个 for 循环不被识别
⇒ 循环里的钩子对门禁**完全不可见**，而门禁是绿的。

## 这是同类缺陷的第三个实例

1. `feature_matrix.py` 的 `SwitchFeature(...)` —— `summary` 里写了 `钩 dj.e.f()`，
   第 37 个功能从 `VERIFICATION.md` 消失；
2. `check_declared_counts` 只认分数形式 —— 3 处数字过期数月；
3. 本条 `LOOP_LIST_RE`。

## 现状

当前源码里**没有**嵌套 `listOf` 的真实用法（都是纯字符串列表），
所以这条加固**不改变任何现有解析结果**（A/B 实测：新旧正则都得到 123 个目标）。
它防的是"以后有人这么写"。

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'scripts'))

import check_hook_targets as ht  # noqa: E402
import check_hook_signatures as hs  # noqa: E402


class MatchesBothShapes(unittest.TestCase):

    def test_plain_string_list(self):
        """最常见的形态：纯字符串列表。"""
        m = ht.LOOP_LIST_RE.search('for (m in listOf("d", "f", "h")) {')
        self.assertIsNotNone(m, '简单 listOf 都匹配不上 —— 破坏面太大')
        self.assertEqual(m.group(2), '"d", "f", "h"')

    def test_nested_parens_in_arguments(self):
        """参数里有括号嵌套时也必须匹配。

        旧正则 `[^)]*` 在这里整段失配 —— 循环里的钩子对门禁隐形。
        """
        code = 'for (c in listOf(clazzOrNull("x.Y").name, "d.e.F")) {'
        m = ht.LOOP_LIST_RE.search(code)
        self.assertIsNotNone(m, '嵌套括号的 listOf 没被识别 —— 循环里的钩子会隐形')
        self.assertIn('clazzOrNull', m.group(2))

    def test_two_copies_are_identical(self):
        """两个文件各有一份 `LOOP_LIST_RE`，必须一致。

        分开实现会漂移：一处加固、另一处没加固，于是两道门对同一份源码
        得出不同的钩子集合 —— 那种不一致极难查。
        """
        self.assertEqual(ht.LOOP_LIST_RE.pattern, hs.LOOP_LIST_RE.pattern,
                         'check_hook_targets 与 check_hook_signatures 的 LOOP_LIST_RE 已漂移')


if __name__ == '__main__':
    unittest.main()
