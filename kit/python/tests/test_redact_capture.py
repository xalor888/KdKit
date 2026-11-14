#!/usr/bin/env python3
"""
Offline tests: 抓取脱敏不能**为了安全把样本弄坏**。

背景（2026-10-25 第 17 轮）：`work/activity_inputs/` 里同一条登录 token 出现 1418 次，
连同 `cuid`/`adid`/`did` 一起进了仓库。脱敏是必须的，但样本的价值在于**结构**：
`ACTIVITY.md` 的统计、签名链复现都依赖 `_t_`/`abis`/`vc` 这些键与分隔符原样保留。

所以这里的断言分两类：
  1. 凭证真的没了（`redact_line` 之后 `residual()` 为空）；
  2. 结构真的还在（键名、分隔符、其它值一字不改；空值仍是空）。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))          # kit/python/tests -> kit
sys.path.insert(0, os.path.join(KIT, 'python'))

import redact_capture as rc  # noqa: E402
from capture_schema import parse_line  # noqa: E402


SIGN_LINE = (
    '07:58:17.220 SIGN params: _t_=1791849497 | abis=1 | adid=ec8f47a032495a694829dca396bcdf6400531e0e '
    '| appBit=64 | cuid=00000000000000000000000000000000|0 | did= | idfa= '
    '| identityIdV2=0 | os=android | token=1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM | vc=1811 | vcname=7.7.2'
)
URL_LINE = ('07:58:17.220 SIGN URL: https://www.kuaiduizuoye.com/kdapi/x?&token=1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM'
            '&sign=c41a117bc0e6fc46afefbb0789f02dac&_t_=1791849497')


class CredentialsAreGone(unittest.TestCase):
    def test_token_is_removed(self):
        out, n = rc.redact_line(SIGN_LINE)
        # 这一行有 3 个敏感值：token / adid / cuid。
        # 早期这里写死 1 —— 是照着"只想到 token"的直觉写的；测试跑出来 3 才对，
        # 说明**常量期望值本身**是漏写。改成按实际敏感键集合断言，避免再漏。
        self.assertEqual(n, 3, f'应脱敏 3 处（token/adid/cuid），实际 {n}')
        self.assertNotIn('1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM', out)
        self.assertNotIn('ec8f47a032495a694829dca396bcdf6400531e0e', out)
        self.assertNotIn('00000000000000000000000000000000', out)
        self.assertIn('token=REDACTED', out)

    def test_url_token_and_sign_are_both_removed(self):
        out, n = rc.redact_line(URL_LINE)
        self.assertEqual(n, 2)
        self.assertNotIn('1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM', out)
        self.assertNotIn('c41a117bc0e6fc46afefbb0789f02dac', out)
        self.assertIn('token=REDACTED', out)
        self.assertIn('sign=REDACTED', out)

    def test_residual_reports_everything_left(self):
        self.assertTrue(rc.residual(SIGN_LINE))
        out, _ = rc.redact_line(SIGN_LINE)
        self.assertEqual(rc.residual(out), [])


class StructureSurvives(unittest.TestCase):
    """脱敏**只**动值。这是"样本还能用"的全部前提。"""

    def test_keys_and_other_values_are_byte_identical(self):
        out, _ = rc.redact_line(SIGN_LINE)
        # 逐个非敏感键原样保留（含分隔符 ` | `）
        for keep in ('_t_=1791849497', 'abis=1', 'appBit=64', 'identityIdV2=0',
                     'os=android', 'vc=1811', 'vcname=7.7.2', ' | '):
            with self.subTest(keep=keep):
                self.assertIn(keep, out)

    def test_empty_value_stays_empty(self):
        """`did=` 不能变成 `did=REDACTED`。

        变了会把"没有这个字段"偽装成"有这个字段但被脱敏"，而 `SIGN params` 的
        **键集合**正是 `ACTIVITY.md` 的统计输入之一 —— 会凭空多出一个字段。
        """
        out, _ = rc.redact_line(SIGN_LINE)
        self.assertIn('did= ', out)
        # 用词边界断言：`assertNotIn('did=REDACTED')` 会误命中 `adid=REDACTED`
        # 里的一段子串 —— 子串断言在"前缀互相包含"的键名上必然出错。
        self.assertNotRegex(out, r'(?<!a)did=REDACTED')
        self.assertIn('idfa= ', out)

    def test_pipe_inside_value_does_not_swallow_next_key(self):
        """`cuid=69C875…|0` 的值里含竖线 —— 不能把 `|0` 之后的 ` os=android` 吃掉。"""
        out, _ = rc.redact_line(SIGN_LINE)
        self.assertIn('cuid=REDACTED|0', out)
        self.assertIn('os=android', out)

    def test_non_credential_lines_untouched(self):
        for line in ('07:50:52.153 H5 n out: 暑假作业',
                     '07:58:19.958 H5BRIDGE zybTrackerStatisticsAction count=8 {}',
                     'ADSLOT ret  aj.a.d(7) -> null'):
            with self.subTest(line=line):
                out, n = rc.redact_line(line)
                self.assertEqual((out, n), (line, 0))


class Idempotent(unittest.TestCase):
    """跑两次必须一样 —— 否则"离线可重复"不成立。"""

    def test_second_pass_is_a_noop(self):
        once, _ = rc.redact_line(SIGN_LINE)
        twice, n = rc.redact_line(once)
        self.assertEqual(twice, once)
        self.assertEqual(n, 0)

    def test_text_level_is_stable(self):
        text = SIGN_LINE + '\n' + URL_LINE + '\n'
        a, _ = rc.redact_text(text)
        b, _ = rc.redact_text(a)
        self.assertEqual(a, b)


class SchemaStillParses(unittest.TestCase):
    """脱敏后的行必须**仍被 capture_schema 认出**且 feature 归属不变。

    如果脱敏把行格式弄坏，抓取统计会静默归零 —— 那是比泄漏更隐蔽的失效：
    文档会显示"该功能 0 条"，看起来像功能没生效。
    """

    def test_sign_lines_keep_their_feature(self):
        for raw in (SIGN_LINE, URL_LINE):
            before = parse_line(raw)
            red, _ = rc.redact_line(raw)
            after = parse_line(red)
            with self.subTest(raw=raw[:40]):
                self.assertIsNotNone(before, '脱敏前就没解析出来，样本本身有问题')
                self.assertIsNotNone(after, f'脱敏后解析失败：{red[:80]}')
                self.assertEqual(after.kind, before.kind)
                self.assertEqual(after.feature, before.feature)


class RealCapturesAreRedacted(unittest.TestCase):
    """仓库里的样本必须**当前**就是干净的。

    这条是门禁，不是演示：新增一份没脱敏的抓取进来，它会立刻红。
    没有目录时跳过（CI 里可能只带代码）。
    """

    INPUTS = os.path.join(os.path.dirname(KIT), 'work', 'activity_inputs')

    def test_no_residual_credentials(self):
        if not os.path.isdir(self.INPUTS):
            self.skipTest('没有 work/activity_inputs')
        caps = sorted(os.path.join(self.INPUTS, f) for f in os.listdir(self.INPUTS)
                      if f.endswith('.txt'))
        if not caps:
            self.skipTest('work/activity_inputs 里没有 .txt')
        bad = {}
        for p in caps:
            left = rc.residual(rc.read_text(p))
            if left:
                bad[os.path.basename(p)] = left[:3]
        self.assertEqual(bad, {}, f'这些抓取里还有未脱敏凭证：{bad}')


if __name__ == '__main__':
    unittest.main()
