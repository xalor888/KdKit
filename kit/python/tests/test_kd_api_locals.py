#!/usr/bin/env python3
"""
`kd_api.py` 的两个「静默死分支」—— 都用**结构断言**钉住，因为它们原本都被
`except Exception` 吞掉了，功能级测试看不出来。

缺陷回顾（2026-11-01 代码审查 P0-4）
------------------------------------
1. `main()` 里有一句 `import json`（在 `pull` 分支内）。Python 的作用域规则让 `json`
   **在整个 `main()` 里都成为局部名**，于是 `pull` 分支更早执行的 `json.loads(raw)`
   抛 `UnboundLocalError` —— 被下面的 `except Exception` 吞掉，
   结果是 `errstr` 恒空、`encodeData` 永不解密、payload 列退化成原始前 60 字节，
   **而退出码仍然是 0**。
2. `call --rc4-key` 分支写的是 `_json.loads(body)`，而 `_json` 全文件从未绑定 ⇒
   `NameError` 被吞 ⇒ `MANUAL.md` 宣称的解密入口从来没工作过。

判据
----
* `json` 不能是 `main()` 的局部名（用 `symtable` 查，不是 grep）；
* 源码里不能出现 `_json`（未绑定名）；
* 这两条一旦回退，`pull`/`--rc4-key` 会再次"静默无输出但退出码 0"。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import os
import re
import symtable
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_PY = os.path.dirname(HERE)

if KIT_PY not in sys.path:
    sys.path.insert(0, KIT_PY)

SRC_PATH = os.path.join(KIT_PY, 'kd_api.py')


def _src():
    with open(SRC_PATH, encoding='utf-8') as _f:
        return _f.read()


def _main_frame():
    table = symtable.symtable(_src(), 'kd_api.py', 'exec')
    frames = [c for c in table.get_children() if c.get_name() == 'main']
    if not frames:
        raise AssertionError('kd_api.py 里找不到 main()')
    return frames[0]


class JsonIsNotShadowed(unittest.TestCase):
    """第 1 条：`import json` 不能出现在函数内，否则同函数前半段用不了它。"""

    def test_json_is_not_a_local_of_main(self):
        frame = _main_frame()
        syms = {s.get_name(): s for s in frame.get_symbols()}
        self.assertIn('json', syms, 'main() 里提到了 json？连提都没提就更不对了')
        self.assertFalse(
            syms['json'].is_local(),
            '`json` 成了 main() 的局部名 —— 说明函数里又写了 `import json`，'
            '那么更早执行的 json.loads() 会抛 UnboundLocalError 并被 except 吞掉',
        )

    def test_json_imported_at_module_level(self):
        table = symtable.symtable(_src(), 'kd_api.py', 'exec')
        syms = {s.get_name(): s for s in table.get_symbols()}
        self.assertTrue(syms.get('json') and syms['json'].is_imported(),
                        'json 必须在模块顶部 import')

    def test_pull_branch_uses_the_module_level_name(self):
        src = _src()
        # `pull` 分支里的那次解析必须直接写 json.loads(raw)
        self.assertRegex(src, r'doc\s*=\s*json\.loads\(raw\)',
                         'pull 分支的响应解析不见了或换了写法，请重新核对')


class NoUnboundPrivateAlias(unittest.TestCase):
    """第 2 条：`_json` 从未绑定过，出现即 bug。"""

    def test_no_underscore_json_alias(self):
        src = _src()
        hits = [m.start() for m in re.finditer(r'\b_json\b', src)]
        self.assertEqual(
            hits, [],
            '源码里又出现 `_json`（未绑定名）。正确写法是 `json.loads(...)`'
            + (f'（位置 {hits}）' if hits else ''),
        )

    def test_no_function_local_json_alias_shadowing(self):
        """`import json as _j` 在函数内是安全的（不同名），但不能再有 `import json`。"""
        src = _src()
        body = src.split('def main(', 1)[1] if 'def main(' in src else ''
        self.assertNotRegex(
            body, r'^\s*import json\s*$',
            'main() 里又出现裸 `import json` —— 会把 json 变成局部名',
        )


class SignMathIsStable(unittest.TestCase):
    """顺手钉住签名公式本身（这条不依赖网络、不依赖设备）。"""

    def test_sign_for_is_deterministic(self):
        import kd_api
        a = kd_api.sign_for('CONST_A', 'XSECRET', ['a=1', 'b=2'])
        b = kd_api.sign_for('CONST_A', 'XSECRET', ['b=2', 'a=1'])
        self.assertEqual(a[0], b[0], '参数顺序变了签名就该不变（进公式前必须 sort）')
        self.assertEqual(len(a[0]), 32, 'MD5 hex 应为 32 字符')

    def test_param_keeps_base64_padding(self):
        """
        `Base64.NO_WRAP` **保留 padding**，而 padding 是被签进去的字节之一。
        去掉它会让"字节长度不是 3 的倍数"的请求全部签名不符（实测 54/80）。
        """
        import kd_api
        _, param = kd_api.sign_for('A', 'X', ['a=1'])
        # 'a=1' 是 3 字节 → 无 padding；换成 4 字节必须有 '='
        _, param2 = kd_api.sign_for('A', 'X', ['ab=1'])
        self.assertEqual(param, 'YT0x')
        self.assertTrue(param2.endswith('='), f'4 字节输入应带 padding，实际 {param2!r}')

    def test_sign_from_url_matches_manual_build(self):
        import kd_api
        url = 'https://h.example/p?a=1&b=2&sign=deadbeef&_t_=1&kakorrhaphiophobia=9'
        # 注意：`_t_` 与 `kakorrhaphiophobia` **也在**签名输入里（App 就是这么拼的），
        # `sign_from_url` 只排除 `sign` 本身。
        want, _ = kd_api.sign_for('A', 'X', ['a=1', 'b=2', '_t_=1', 'kakorrhaphiophobia=9'])
        self.assertEqual(kd_api.sign_from_url('A', 'X', url), want)


class PairsOfTiesParamsToUrls(unittest.TestCase):
    """
    `pairs_of()` 把 `SIGN params` 与 `SIGN URL` 配成对。
    抓取是多线程写的，"上一行"不可靠，所以它用签名块身份 `(_t_, kakorrhaphiophobia)` 配。
    """

    def _capture(self, lines):
        import tempfile
        f = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8')
        f.write('\n'.join(lines) + '\n')
        f.close()
        self.addCleanup(lambda: os.unlink(f.name))
        return f.name

    def test_identity_beats_adjacency(self):
        import kd_api
        cap = self._capture([
            '10:00:00.001 SIGN params: _t_=2 | b=2 | kakorrhaphiophobia=22',
            '10:00:00.002 SIGN params: _t_=1 | a=1 | kakorrhaphiophobia=11',
            '10:00:00.003 SIGN URL: https://h.example/p?a=1&sign=x&_t_=1&kakorrhaphiophobia=11',
            '10:00:00.004 SIGN URL: https://h.example/p?b=2&sign=y&_t_=2&kakorrhaphiophobia=22',
        ])
        pairs = kd_api.pairs_of(cap)
        self.assertEqual(len(pairs), 2)
        by_url = {u.split('?')[1].split('&')[0]: plist for plist, u in pairs}
        self.assertIn('_t_=1', ' | '.join(by_url['a=1']),
                      'URL a=1 应该配到 _t_=1 的 params（上一行是 _t_=2，说明用了邻接而不是身份）')
        self.assertIn('_t_=2', ' | '.join(by_url['b=2']))


if __name__ == '__main__':
    unittest.main()
