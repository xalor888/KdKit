"""`class_rename_match.py` 必须分清 **改名/搬包** 与 **真增删**。

A3 的结论（7.10.0 真新增只有 15 个、`GONE=0`）全靠这个工具；如果它把"换了 dex 分包"
判成"新增"，报告里的"新功能面"就会多出 91 个幻觉。所以这里用最小 smali 树钉住四种判定：

  * `RENAME`   —— 同名同签名同代码，只是路径变了（`smali_classes3/x` → `smali_classes7/x`）
  * `CHANGED`  —— 签名相同、代码不同（还换了路径）
  * `NEW`      —— 新侧有、旧侧找不到对手
  * `GONE`     —— 旧侧有、新侧找不到对手

跑法：`--old/--new` 指向临时树，`--delta` 指向临时 JSON。
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
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'class_rename_match.py')

SMALI = """.class public Lpkg/{name};
.super Ljava/lang/Object;

.method public constructor <init>()V
    .locals 0
    invoke-direct {{p0}}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public run()V
{body}
.end method

.method public {sig}()V
{body}
.end method
"""


class RenameVsRealDelta(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='kdren-')
        self.old = os.path.join(self.tmp, 'old')
        self.new = os.path.join(self.tmp, 'new')
        os.makedirs(os.path.join(self.old, 'smali_classes3', 'pkg'))
        os.makedirs(os.path.join(self.new, 'smali_classes7', 'pkg'))

        # 1) 改名/搬包：同名同签名同代码，只是目录前缀变了
        self._write(os.path.join(self.old, 'smali_classes3', 'pkg', 'Moved.smali'),
                    SMALI.format(name='Moved', sig='movedOnly', body='    return-void'))
        self._write(os.path.join(self.new, 'smali_classes7', 'pkg', 'Moved.smali'),
                    SMALI.format(name='Moved', sig='movedOnly', body='    return-void'))
        # 2) CHANGED：签名相同、代码不同
        self._write(os.path.join(self.old, 'smali_classes3', 'pkg', 'Tweaked.smali'),
                    SMALI.format(name='Tweaked', sig='tweakedOnly', body='    return-void'))
        self._write(os.path.join(self.new, 'smali_classes7', 'pkg', 'Tweaked.smali'),
                    SMALI.format(name='Tweaked', sig='tweakedOnly', body='    nop\n    return-void'))
        # 3) NEW：只有新侧
        self._write(os.path.join(self.new, 'smali_classes7', 'pkg', 'BrandNew.smali'),
                    SMALI.format(name='BrandNew', sig='brandNewOnly', body='    return-void'))
        # 4) GONE：只有旧侧
        self._write(os.path.join(self.old, 'smali_classes3', 'pkg', 'Removed.smali'),
                    SMALI.format(name='Removed', sig='removedOnly', body='    return-void'))

        self.delta = os.path.join(self.tmp, 'delta.json')
        with open(self.delta, 'w', encoding='utf-8') as f:
            json.dump({'only790': ['smali_classes3/pkg/Moved.smali',
                                   'smali_classes3/pkg/Tweaked.smali',
                                   'smali_classes3/pkg/Removed.smali'],
                       'only710': ['smali_classes7/pkg/Moved.smali',
                                   'smali_classes7/pkg/Tweaked.smali',
                                   'smali_classes7/pkg/BrandNew.smali']}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, text):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def _run(self, json_out=None):
        cmd = [sys.executable, TOOL, '--old', self.old, '--new', self.new, '--delta', self.delta]
        if json_out:
            cmd += ['--json', json_out]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout or '') + (p.stderr or '')

    def test_four_verdicts(self):
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn('RENAME=1', out, f'搬包应判 RENAME：{out[-400:]}')
        self.assertIn('CHANGED=1', out)
        self.assertIn('NEW=1', out)
        self.assertIn('GONE=1', out)

    def test_moved_class_pointing_to_the_right_side(self):
        """RENAME 必须指对目标 —— 指错了就等于"报告里多一个幻觉新类"。

        用 `--json` 断言，而不是 stdout：工具**故意只打印** NEW/GONE/CHANGED/ambiguous 明细
        （纯 RENAME 有 81 条，刷屏没价值），所以 stdout 里找不到 RENAME 行是正常的。
        """
        j = os.path.join(self.tmp, 'out.json')
        rc, out = self._run(json_out=j)
        self.assertEqual(rc, 0, out)
        with open(j, encoding='utf-8') as f:
            rows = json.load(f)
        renames = [r for r in rows if r['verdict'] == 'RENAME']
        self.assertEqual(len(renames), 1, f'应有一条 RENAME：{[r["verdict"] for r in rows]}')
        self.assertEqual(renames[0]['old'], 'smali_classes3/pkg/Moved.smali')
        self.assertEqual(renames[0]['new'], 'smali_classes7/pkg/Moved.smali')


if __name__ == '__main__':
    unittest.main()
