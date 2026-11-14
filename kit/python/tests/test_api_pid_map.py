#!/usr/bin/env python3
"""
Offline tests for `kit/scripts/api_pid_map.py` and the `pid` enrichment it feeds.

Why this exists: `__pid` is a **business-domain tag** each request class hard-codes
next to its URL (`saas-passport` / `cube` / `vip` / … or empty). Replay tools
(`SIGNED_SURFACE.md`) historically ignored it, so a replay could fail because the
wrong pid was sent and we would blame the signature instead.

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))

import api_pid_map  # noqa: E402

APK = os.path.join(ROOT, 'work', 'apktool_out')


class Parser(unittest.TestCase):
    """纯解析逻辑，不依赖 APK。"""

    def test_format_does_not_collide_with_regex_quantifiers(self):
        """`_CONST_THEN_IPUT % (...)` 必须是 % 格式化。

        用 `str.format` 会把正则里的 `{0,3}` 当占位符，直接 KeyError: '0,3'
        —— 本文件第一版就踩了这个，整个工具起不来。
        """
        rx = api_pid_map._field_re('Lcom/x/Y;', 'url')
        self.assertIsNotNone(rx.search(
            'const-string v0, "/a/b"\n'
            'iput-object v0, p0, Lcom/x/Y;->__url:Ljava/lang/String;'))

    def test_matches_across_inserted_lines(self):
        """Robust 的 PatchProxy 常插在 const 与 iput 之间，允许跨行匹配。"""
        rx = api_pid_map._field_re('Lcom/x/Y;', 'pid')
        self.assertIsNotNone(rx.search(
            'const-string v0, "cube"\n'
            '    .line 12\n'
            '    sget-object v1, Lcom/meituan/robust/PatchProxy;->x\n'
            '    iput-object v0, p0, Lcom/x/Y;->__pid:Ljava/lang/String;'))

    def test_empty_pid_is_a_value_not_a_miss(self):
        """`""` 是**合法取值**（空业务域），不能和"没写 pid"混为一谈。"""
        rx = api_pid_map._field_re('Lcom/x/Y;', 'pid')
        m = rx.search('const-string v0, ""\n'
                      'iput-object v0, p0, Lcom/x/Y;->__pid:Ljava/lang/String;')
        self.assertIsNotNone(m)
        self.assertEqual(m.group(2), '')


class RealApk(unittest.TestCase):
    """对着真 APK 断言 —— 这些数字变了说明宿主换了 API 面。"""

    def setUp(self):
        if not os.path.isdir(APK):
            self.skipTest('work/apktool_out 不存在')
        self.rows = api_pid_map.scan(APK)

    def test_scan_finds_the_known_request_classes(self):
        self.assertGreater(len(self.rows), 200,
                           f'只解析出 {len(self.rows)} 条 (类,路径)，映射可能失效')

    def test_gradeupgrade_has_empty_pid(self):
        """`/kdapi/popup/gradeupgrade` 的 pid 是空串。

        这条是 `SIGNED_SURFACE.md` 里 `906003` 悬案的一部分证据：
        该请求**没有业务参数**、pid 也是空的 ⇒ 重放失败不该归因于"业务参数带错"。
        """
        hits = api_pid_map.lookup(self.rows, '/kdapi/popup/gradeupgrade')
        self.assertTrue(hits, '找不到 gradeupgrade 的 Input 类')
        self.assertEqual([h['pid'] for h in hits], [''],
                         f'gradeupgrade 的 pid 变了：{hits}')

    def test_a_named_pid_exists(self):
        """至少要有非空 pid，否则"业务域"这个说法就没有证据。"""
        named = {r['pid'] for r in self.rows if r['pid']}
        self.assertGreater(len(named), 3, f'非空 pid 太少：{named}')

    def test_lookup_returns_all_declarations(self):
        """同一路径被多个类声明时**全保留**，不合并 —— 合并会让重放随机挑一个。"""
        from collections import Counter
        c = Counter(r['url'] for r in self.rows)
        dup = [u for u, n in c.items() if n > 1]
        if not dup:
            self.skipTest('当前 APK 没有重复声明的路径')
        u = dup[0]
        self.assertEqual(len(api_pid_map.lookup(self.rows, u)), c[u])


class SchemaEnrichment(unittest.TestCase):
    """`capture_schema` 的 WEBREQ 解析要带上 pid，且不依赖 APK 可用。"""

    def test_webreq_carries_pid(self):
        import capture_schema as cs
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, 't.txt')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('20:01:01.100 WEBREQ https://h/kdapi/popup/gradeupgrade\n')
            fh.write('20:01:01.101 WEBREQ https://h/cube/api/checkorder\n')
        recs = {r.fields['url']: r.fields for r in cs.iter_records(p)}
        if not os.path.isdir(APK):
            self.skipTest('work/apktool_out 不存在')
        self.assertEqual(recs['https://h/kdapi/popup/gradeupgrade'].get('pid'), '(空)')
        self.assertEqual(recs['https://h/cube/api/checkorder'].get('pid'), 'cube')

    def test_unknown_path_has_no_pid_key(self):
        """查不到就不写这个键 —— 写 `None` 会让下游以为"有 pid 但是空"。"""
        import capture_schema as cs
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, 't.txt')
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write('20:01:01.100 WEBREQ https://h/definitely/not/declared/anywhere\n')
        (rec,) = list(cs.iter_records(p))
        self.assertNotIn('pid', rec.fields)


if __name__ == '__main__':
    unittest.main()
