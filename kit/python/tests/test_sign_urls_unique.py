"""`capture_schema.sign_urls` 是 `SIGN URL` 提取的**唯一实现**。

2026-11-04 代码审查 P2：三处各写了一遍
`[l.split(' SIGN URL: ', 1)[1].strip() for l in lines if ' SIGN URL: ' in l]`。

那次收敛差点造成一次静默的数据丢失 —— 这个文件钉住三件事：

1. **两种形态都要认**：`SIGN URL: …` 和 `APPSIGN I/Tag: [KdKit] SIGN URL: …`；
2. **截断的 URL 不许进结果**：中继形态会被 `LogSink` 截成 `…(719)`，
   旧写法把它当 URL 用，下游 `urlparse` 照样给出正确的 path ⇒ 拿坏 URL 发请求；
3. **被丢掉的条数要可见**：`sign_urls_truncated()` 单独给出，不许静默。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import capture_schema as cs  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

DIRECT = '10:00:00.001 SIGN URL: https://h.example/x?a=1&sign=abc'
RELAY = ('10:00:00.002 APPSIGN I/VectorLegacyBridge: [KdKit] '
         'SIGN URL: https://h.example/y?b=2&sign=def')
TRUNC = ('10:00:00.003 APPSIGN I/VectorLegacyBridge: [KdKit] '
         'SIGN URL: https://h.example/z?c=3&adid=ec8f47a032495a6 …(719)')


class BothFormsAreRecognised(unittest.TestCase):

    def test_direct_form(self):
        self.assertEqual(cs.sign_urls([DIRECT]), ['https://h.example/x?a=1&sign=abc'])

    def test_relayed_form(self):
        self.assertEqual(cs.sign_urls([RELAY]), ['https://h.example/y?b=2&sign=def'])

    def test_both_together_keep_order(self):
        self.assertEqual(cs.sign_urls([DIRECT, RELAY]),
                         ['https://h.example/x?a=1&sign=abc',
                          'https://h.example/y?b=2&sign=def'])

    def test_non_sign_lines_are_ignored(self):
        self.assertEqual(cs.sign_urls([
            '10:00:00.001 NET GET https://h.example/q',
            '10:00:00.002 APPSIGN I/X: [KdKit] something else',
        ]), [])


class TruncatedOnesAreExcludedButCounted(unittest.TestCase):

    def test_truncated_url_is_not_returned(self):
        """**这就是旧写法的 bug**：它会把 `…(719)` 一起当成 URL。"""
        got = cs.sign_urls([TRUNC])
        self.assertEqual(got, [])
        self.assertEqual(cs.sign_urls_truncated([TRUNC]), 1)

    def test_old_style_would_have_returned_it(self):
        """把旧写法的结果写下来，防止有人"改回去更简单"。"""
        line = TRUNC
        old = line.split(' SIGN URL: ', 1)[1].strip()
        self.assertIn(' …(719)', old)
        self.assertNotIn(old, cs.sign_urls([TRUNC]))

    def test_mixed_input(self):
        self.assertEqual(cs.sign_urls([DIRECT, TRUNC, RELAY]),
                         ['https://h.example/x?a=1&sign=abc',
                          'https://h.example/y?b=2&sign=def'])
        self.assertEqual(cs.sign_urls_truncated([DIRECT, TRUNC, RELAY]), 1)


class OldStylePickedUpFalsePositives(unittest.TestCase):
    """旧写法 `' SIGN URL: ' in l` 会匹配**任何**含这个子串的行 ——
    包括解密后的响应体里回显的 URL 文本。

    实测：1200 份抓取里新旧完全一致，另 9 份差 1 条，
    那 1 条全是 `NET DECRYPT out:` 的 JSON 体里回显的 URL。
    旧写法把它当成"发出去的请求"，新写法按 kind 判，正确地不算。
    """

    ECHOED = ('11:24:37.314 NET DECRYPT out: {"errNo":0,"data":{"u":"'
              'https://h.example/p?a=1"},"note":" SIGN URL: https://h.example/p?a=1"}')

    def test_response_body_echo_is_not_a_request(self):
        self.assertIn(' SIGN URL: ', self.ECHOED)          # 旧判据会命中
        self.assertEqual(cs.sign_urls([self.ECHOED]), [])  # 新判据不命中
        self.assertEqual(cs.parse_line(self.ECHOED).kind, 'NET')


class RealCapturesKeepWorking(unittest.TestCase):
    """真实抓取上：干净 URL 必须全是不带截断标记的；截断数必须能数出来。"""

    PACKS = ('work/packs/api_health/capture.txt', 'work/packs/r71/capture.txt.gz')

    def test_every_returned_url_is_clean(self):
        seen = 0
        for rel in self.PACKS:
            p = os.path.join(ROOT, rel)
            if not os.path.isfile(p):
                continue
            seen += 1
            for u in cs.sign_urls(p):
                self.assertNotIn(' …(', u, f'{rel} 里混进了截断的 URL')
                self.assertNotIn(' ', u, f'{rel} 里混进了带空格的 URL')
        if not seen:
            self.skipTest('没有真实抓取')

    def test_truncation_count_is_reported(self):
        p = os.path.join(ROOT, 'work/packs/api_health/capture.txt')
        if not os.path.isfile(p):
            self.skipTest('没有 api_health 抓取')
        self.assertGreater(cs.sign_urls_truncated(p), 0,
                           '这份抓取里有中继截断的 SIGN URL，必须数得出来')


if __name__ == '__main__':
    unittest.main()
