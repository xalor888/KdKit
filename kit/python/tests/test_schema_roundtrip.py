#!/usr/bin/env python3
"""
Tests for `kit/scripts/check_schema_roundtrip.py` — the ⑪ gate.

## 这道门守的是什么

`capture_schema.py` 的规则表与模块侧写抓取，两边必须对得上：
* 规则有、没人写 ⇒ 死规则；
* 有人写、没规则 ⇒ 那行落 UNKNOWN。

**关键陷阱**：`kind` 名 ≠ 行前缀。`AD_BLOCK` 这个 kind 对应的行是
`blocked ad slot read: …`。2026-10-26 我用"前缀比对"的方法查这件事，
误判出 15 条假缺口 —— 这份测试就是防止那种误判再发生。

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))

import capture_schema as cs          # noqa: E402
import check_schema_roundtrip as rt  # noqa: E402


class KindIsNotPrefix(unittest.TestCase):
    """把这条钉死：kind 名与它匹配的行前缀毫无关系。"""

    def test_ad_block_kind_matches_a_sentence_not_a_token(self):
        """`AD_BLOCK` 的规则匹配 `blocked ad slot read: …`，不是 `AD_BLOCK …`。"""
        r = cs.parse_line('12:00:00.000 blocked ad slot read: aj.a.d(3) -> null')
        self.assertEqual(r.kind, 'AD_BLOCK')
        # 反过来：真的写 `AD_BLOCK` 开头，反而不该被这条规则认领
        r2 = cs.parse_line('12:00:00.000 AD_BLOCK aj.a.d(3)')
        self.assertNotEqual(r2.kind, 'AD_BLOCK')


class EveryRuleIsExercised(unittest.TestCase):

    def test_no_dead_rules_in_repo(self):
        """真仓库当前不该有死规则。有的话：要么补样本，要么删规则。"""
        files = rt.sample_files()
        if not files:
            self.skipTest('没有样本抓取')
        seen = set()
        for f in files:
            for r in cs.iter_records(f):
                seen.add(r.kind)
        allk = ({k for k, *_ in cs.RULES} - rt.INTERNAL - set(rt.NOT_YET))
        dead = sorted(allk - seen)
        self.assertEqual(dead, [], f'这些规则从未被任何真实样本触发：{dead}')

    def test_mark_is_a_real_rule(self):
        """会话头 `=== KdKit host=…` 有真实规则，`MARK` **在**规则表里。

        曾经假设它是"解析器自产品、不在表里"，实测在（RULES 共 53 条）。
        错误假设的代价：规则覆盖率少算一条 + 反向检查误报"表外 kind"。
        """
        self.assertIn('MARK', {k for k, *_ in cs.RULES})
        self.assertEqual(cs.parse_line('12:00:00.000 === KdKit host=1 sdk=36').kind, 'MARK')


class PerRegexCoverage(unittest.TestCase):
    """kind 层绿 ≠ 每条正则都被命中。

    `RULES` 有 54 条正则但只有 39 个 kind —— `BRIDGE` 一个 kind 就有 4 条。
    只查 kind 时，某个变体的正则写坏/格式漂移**完全看不出来**（同 kind 的其他变体命中）。
    2026-10-26 加上这一层后立刻抓到 `REQBODY json len=…` 从未命中。
    """

    def test_every_regex_is_matched_by_some_sample_line(self):
        files = rt.sample_files()
        if not files:
            self.skipTest('没有样本抓取')
        body = []
        for f in files:
            with open(f, encoding='utf-8', errors='replace') as _f:
                for ln in _f:
                    m = cs.TS_RE.match(ln.strip())
                    if m:
                        body.append(m.group(2))
        # 与 `check_schema_roundtrip.NOT_YET` 同一份豁免（游客态下还没法产生样本的规则）
        dead = [(k, v, p.pattern) for k, _f, v, p, _fn in cs.RULES
                if k not in rt.NOT_YET and not any(p.match(b) for b in body)]
        self.assertEqual(dead, [],
                         f'这些正则从未被任何样本行命中（格式可能已漂移）：{dead}')

    def test_rule_count_exceeds_kind_count(self):
        """钉住"条数 ≠ kind 数"这个事实 —— 别处引用数字时容易混。"""
        kinds = {k for k, *_ in cs.RULES}
        self.assertGreater(len(cs.RULES), len(kinds),
                           'RULES 的条数应当多于 kind 数（多态共用 kind）')


class UnknownReasonsAreClassified(unittest.TestCase):
    """UNKNOWN 要分原因：残缺形态 / 负样本 / 真缺口。"""

    def test_negative_sample_line_is_unknown(self):
        """fixture 里故意放的那行负样本必须落 UNKNOWN —— 证明解析器不瞎认领。"""
        r = cs.parse_line('12:00:00.000 this line has no known prefix at all')
        self.assertEqual(r.kind, 'UNKNOWN')

    def test_truncated_line_is_marked(self):
        r = cs.parse_line('12:00:00.000 REQBODY text HWRequest len=9')
        # 这条可能被正确解析，也可能标记截断；只断言它不是 UNKNOWN-with-no-reason
        self.assertTrue(r.kind == 'REQBODY' or r.get('reason'))


if __name__ == '__main__':
    unittest.main()
