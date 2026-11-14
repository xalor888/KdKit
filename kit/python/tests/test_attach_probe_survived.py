#!/usr/bin/env python3
"""
Offline tests: `attach_probe.survived_of` must not claim a conclusion it did not measure.

Why this file exists
--------------------
2026-11-03 代码审查 P1：

> `attach_probe.py:226` `rec['survived'] = died_at is None` 无条件写，
> 与同记录 `verdict="未测到"` 自相矛盾。

实测确认了矛盾：`attach_error` 为真（**frida 根本没插上**）而进程仍在时，
旧实现写 `survived: true`。读起来像"它扛住了反注入"，
而真相是**我们根本没碰它**，它当然活着。

这与今天修掉的其它六个是同一类：**一个字段声称了一个它没测量过的结论。**
`verdict` 字段早就把三种情况分开了（"反注入生效"/"未测到"/"存活"），
是 `survived` 这个布尔没跟上。

为什么提成函数再测：附加失败那条路在真机上很难构造
（需要一个 frida 插不进去的活进程），而这个推导本身必须被证明是对的。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', '..', 'scripts', 'attach_probe.py')


def _tool():
    spec = importlib.util.spec_from_file_location('attach_probe', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class SurvivedOf(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _tool()

    def test_attach_failed_is_never_true(self):
        """没插上 ⇒ 必须是 None（未测），不能是 True。"""
        for died in (None, 1.2, 9.9):
            self.assertIsNone(self.t.survived_of('process not found', died),
                              f'attach_error 为真、died_at={died} 时不能给结论')

    def test_attached_and_alive_is_true(self):
        self.assertIs(self.t.survived_of(None, None), True)

    def test_attached_and_died_is_false(self):
        self.assertIs(self.t.survived_of(None, 3.9), False)

    def test_none_is_distinct_from_false(self):
        """`None`（未测）与 `False`（测了，没活）必须能分开。

        消费者若写 `if not survived:` 会把两者一起当成"没活下来" ——
        那正是旧实现造成的误读。
        """
        unknown = self.t.survived_of('boom', None)
        died = self.t.survived_of(None, 2.0)
        self.assertIsNot(unknown, died)
        self.assertIsNone(unknown)
        self.assertIs(died, False)


if __name__ == '__main__':
    unittest.main()
