"""`bridge_shape_diff.py` 必须分清"参数被删"与"这轮没走到那条路径"。

A6 的结论（7.10.0 **没有给已有桥动作加新参数**）依赖这条单向判据：
**新侧出现过的 key 是否都曾在旧侧**。如果工具把"旧侧有、新侧无"当成"参数被删"，
报告就会写出一堆假回归；如果它反过来把"新侧多出来的 key"漏掉，模块按形状做的判定
就会静默失效。这组测试钉住四种情形：

  * 同名 action、**新侧多 key** ⇒ 必须报 `top_only_new`
  * 同名 action、旧侧多 key ⇒ 报 `top_only_old`（**不**等于"参数被删"）
  * 只在新侧出现的 action ⇒ `only_new`
  * 只在旧侧的 action ⇒ `only_old`（同样是"覆盖不足"，不是删除）
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
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'bridge_shape_diff.py')

OLD = """\
00:00:01.000 H5BRIDGE core_httpRequest count=3 {"url":"/a","params":{"from":"home","extType":1}}
00:00:02.000 H5BRIDGE sharedAction count=2 {"alpha":1,"beta":2}
00:00:03.000 H5BRIDGE oldOnlyAction count=1 {}
"""

NEW = """\
00:00:01.000 H5BRIDGE core_httpRequest count=1 {"url":"/b","params":{"from":"home","extType":1,"newField":true}}
00:00:02.000 H5BRIDGE sharedAction count=1 {"alpha":1}
00:00:03.000 H5BRIDGE newOnlyAction count=2 {"gamma":3}
"""


class ShapeDiffIsHonest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='kdbsd-')
        self.oldp = os.path.join(self.tmp, 'old.txt')
        self.newp = os.path.join(self.tmp, 'new.txt')
        with open(self.oldp, 'w', encoding='utf-8') as f:
            f.write(OLD)
        with open(self.newp, 'w', encoding='utf-8') as f:
            f.write(NEW)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        j = os.path.join(self.tmp, 'out.json')
        p = subprocess.run([sys.executable, TOOL, '--old', self.oldp, '--new', self.newp,
                            '--json', j],
                           capture_output=True, text=True, timeout=120)
        data = None
        if os.path.exists(j):
            with open(j, encoding='utf-8') as f:
                data = json.load(f)
        return p.returncode, (p.stdout or '') + (p.stderr or ''), data

    def test_new_side_extra_key_is_reported(self):
        rc, out, data = self._run()
        self.assertEqual(rc, 0, out)
        rows = {r['action']: r for r in data['changed']}
        self.assertIn('core_httpRequest', rows, out[-300:])
        # `newField` 只在新侧的 `params` 里 ⇒ 必须出现在 inner_only_new
        self.assertIn('newField', rows['core_httpRequest']['inner_only_new'])

    def test_old_side_extra_key_is_not_a_deletion(self):
        rc, out, data = self._run()
        self.assertEqual(rc, 0, out)
        rows = {r['action']: r for r in data['changed']}
        self.assertIn('sharedAction', rows)
        self.assertIn('beta', rows['sharedAction']['top_only_old'],
                      '"旧侧有、新侧无"必须落在 only_old，读报告的人据此判"覆盖不足"')

    def test_side_only_actions_are_listed_separately(self):
        rc, out, data = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn('newOnlyAction', data['only_new'])
        self.assertIn('oldOnlyAction', data['only_old'])


if __name__ == '__main__':
    unittest.main()
