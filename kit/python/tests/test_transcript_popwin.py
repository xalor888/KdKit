"""`POPWIN` 的三种 action 必须在报告里**分得开**。

2026-11-04 代码审查 P2：`capture_transcript.one_line()` 里有**两个**
`if kind == 'POPWIN':` 分支，在同一个函数里，前一个先 return
⇒ **后一个（更详细的那个）是死代码，一行都没跑过**。

死掉的那个恰好是唯一区分这三件事的：

    BLOCK   —— 服务端弹窗未展示
    OBSERVE —— 命中拦截清单但 `observe_only` 开着 ⇒ 只记录、未拦截
    PASS    —— 不在清单里 ⇒ 放行

活着的那个把 `OBSERVE` 写成"已记录（放行）"，把两件事糊成一件 ——
于是**"只观测"模式在报告里看不出来它生效了**。

这个文件钉住：三种 action 各有各的措辞，且 `OBSERVE` 必须自己是一档。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import capture_schema as cs  # noqa: E402
import capture_transcript as ct  # noqa: E402

LINE = '20:32:23.030 POPWIN seen type={t} block={b} action={a}'


def row(t, b, a):
    return ct.one_line(cs.parse_line(LINE.format(t=t, b=b, a=a)))


class ThreeActionsReadDifferently(unittest.TestCase):

    def test_block_says_blocked(self):
        self.assertIn('POPWIN 拦截', row('winAd', 'true', 'BLOCK'))

    def test_observe_says_observed_not_blocked(self):
        got = row('winAd', 'true', 'OBSERVE')
        self.assertIn('POPWIN 观测', got)
        self.assertNotIn('拦截 type', got)          # 不许说成"拦截"

    def test_observe_mentions_the_switch_that_made_it_observe(self):
        """`OBSERVE` 的成因必须写出来 —— 否则读者不知道为什么清单命中了却没拦。"""
        self.assertIn('observe_only', row('winAd', 'true', 'OBSERVE'))

    def test_pass_says_passed(self):
        self.assertIn('POPWIN 放行', row('winGradeUp', 'false', 'PASS'))

    def test_the_three_are_not_the_same_string(self):
        got = {row('winAd', 'true', 'BLOCK'),
               row('winAd', 'true', 'OBSERVE'),
               row('winAd', 'false', 'PASS')}
        self.assertEqual(len(got), 3, got)

    def test_type_is_kept(self):
        for a in ('BLOCK', 'OBSERVE', 'PASS'):
            self.assertIn('`winActivity_7`', row('winActivity_7', 'true', a))


class NoDuplicateKindBranch(unittest.TestCase):
    """同一个函数里不许有两个 `if kind == '<同一个值>'：` —— 后一个是死代码。"""

    def test_one_line_has_no_duplicate_kind_branch(self):
        """只看**语句级**的 `if kind == '<常量>':`。

        第一版把这个范围内的所有 `Compare` 都算了进去，于是
        `side = '写侧' if kind == 'PCTRLW' else '读侧'`（三元表达式）
        也被当成"分支" ⇒ 误报。**判据的范围比它以为的宽** ——
        今天第 11 次遇到这一类，所以这里把口径写死在测试里。
        """
        import ast
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'capture_transcript.py')
        tree = ast.parse(open(path, encoding='utf-8').read())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            seen = {}
            for node in ast.walk(fn):
                if not isinstance(node, ast.If):
                    continue
                t = node.test
                if not (isinstance(t, ast.Compare) and len(t.ops) == 1
                        and isinstance(t.ops[0], ast.Eq)):
                    continue
                if not (isinstance(t.left, ast.Name) and t.left.id == 'kind'):
                    continue
                val = t.comparators[0]
                if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
                    continue
                seen.setdefault(val.value, []).append(node.lineno)
            dup = {k: v for k, v in seen.items() if len(v) > 1}
            self.assertEqual(dup, {}, f'{fn.name} 里有重复的 kind 分支：{dup}')


if __name__ == '__main__':
    unittest.main()
