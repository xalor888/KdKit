#!/usr/bin/env python3
"""
`kit/scripts/method_diff.py` 的判据测试 —— 三条 verdict 必须能被区分开。

为什么需要（2026-11-14 加）
────────────────────────────
7.10.2 适配时第一次用它，得到 `CHANGED = 0`。"0" 这个数字很有说服力，
但一条**只会输出 0 的工具**同样会输出 0 —— 所以这里把它放在三份**已知答案**的
假树上：一份只差常量、一份差一条真指令、一份完全一样。
如果 CONST-SHIFT 与 CHANGED 的判据混了，测试会立刻红。
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCRIPT = os.path.join(ROOT, 'kit', 'scripts', 'method_diff.py')


def load():
    spec = importlib.util.spec_from_file_location('_method_diff', SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


HEADER = ('# virtual methods\n.method public static a(I)I\n    .locals 1\n')


def body(kind):
    if kind == 'same':
        return ('    .line 1\n    const/16 v0, 0x10\n\n'
                '    .line 2\n    invoke-static {v0}, Lx/Y;->z(I)I\n\n'
                '    .line 3\n    move-result v0\n\n    return v0\n.end method\n')
    if kind == 'const':
        return ('    .line 1\n    const/16 v0, 0x12\n\n'
                '    .line 2\n    invoke-static {v0}, Lx/Y;->z(I)I\n\n'
                '    .line 3\n    move-result v0\n\n    return v0\n.end method\n')
    if kind == 'changed':
        return ('    .line 1\n    const/16 v0, 0x12\n\n'
                '    .line 2\n    invoke-static {v0}, Lx/Y;->z(I)I\n\n'
                '    .line 3\n    move-result v0\n\n    return v0\n\n'
                '    .line 4\n    add-int/lit8 v0, v0, 0x1\n\n    return v0\n.end method\n')
    raise ValueError(kind)


class Verdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='mtdiff-')
        self.old = os.path.join(self.tmp, 'old')
        self.new = os.path.join(self.tmp, 'new')
        for root, kind in ((self.old, 'same'), (self.new, 'const')):
            d = os.path.join(root, 'smali', 'pkg')
            os.makedirs(d)
            with open(os.path.join(d, 'A.smali'), 'w', encoding='utf-8') as f:
                f.write(HEADER + body(kind))
        self.targets = os.path.join(self.tmp, 'targets.json')
        with open(self.targets, 'w', encoding='utf-8') as f:
            json.dump({'rows': [{'class': 'pkg.A', 'method': 'a', 'where': 'test'}]}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_diff(self, new_kind):
        d = os.path.join(self.new, 'smali', 'pkg')
        with open(os.path.join(d, 'A.smali'), 'w', encoding='utf-8') as f:
            f.write(HEADER + body(new_kind))
        m = load()
        out = os.path.join(self.tmp, 'out.json')
        rc = m.main(['x', '--old', self.old, '--new', self.new,
                     '--targets', self.targets, '--json', out])
        self.assertEqual(rc, 0)
        return json.load(open(out, encoding='utf-8'))

    def test_identical(self):
        r = self.run_diff('same')
        self.assertEqual(r['counts'].get('IDENTICAL'), 1, r['counts'])
        self.assertNotIn('CHANGED', r['counts'])

    def test_const_shift_is_not_changed(self):
        """只差一个立即数 ⇒ 必须是 CONST-SHIFT，不能升级成 CHANGED。"""
        r = self.run_diff('const')
        self.assertEqual(r['counts'].get('CONST-SHIFT'), 1, r['counts'])
        self.assertNotIn('CHANGED', r['counts'])
        row = [x for x in r['rows'] if x['verdict'].startswith('CONST-SHIFT')][0]
        self.assertEqual(row['deltas'], [[2, 1]], row)      # 0x10 → 0x12

    def test_real_change_is_changed(self):
        """多一条指令 ⇒ 必须是 CHANGED（否则这个工具会永远输出 0）。"""
        r = self.run_diff('changed')
        self.assertIn('CHANGED', r['counts'], r['counts'])


if __name__ == '__main__':
    unittest.main()
