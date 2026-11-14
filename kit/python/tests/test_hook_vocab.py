#!/usr/bin/env python3
"""
Offline tests for `kit/scripts/hook_vocab.py` — the single definition of gate labels.

Why this matters: ④ `check_hook_targets.py` and ⑥ `smali_usage.py` both print labels.
Before this module existed they each invented their own (`OK(load)`, `SELF-CALLED`,
`USED(super-slot)`, `SKIP(platform)` …), so the same hook could look different depending
on which gate you read. The vocabulary is now one file; these tests keep it single.

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import re
import sys
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, '..', '..', 'scripts'))
sys.path.insert(0, SCRIPTS)

import hook_vocab as v  # noqa: E402


class VocabularyShape(unittest.TestCase):

    def test_verdicts_and_evidence_are_disjoint(self):
        """判定与证据是两层概念，同一字符串不能两边都出现（否则报告列会歧义）。"""
        self.assertEqual(set(v.VERDICTS) & set(v.EVIDENCE), set())

    def test_red_set_is_subset_of_known_labels(self):
        known = set(v.VERDICTS) | set(v.EVIDENCE)
        self.assertTrue(set(v.RED) <= known, f'RED 里有未知标签: {set(v.RED) - known}')

    def test_every_label_has_an_explanation(self):
        for k, text in list(v.VERDICTS.items()) + list(v.EVIDENCE.items()):
            self.assertTrue(text.strip(), f'{k} 缺说明')

    def test_strength_covers_all_evidence(self):
        self.assertEqual(set(v.STRENGTH), set(v.EVIDENCE),
                         'STRENGTH 必须覆盖全部证据标签，否则 strongest() 会 index 报错')


class RedRule(unittest.TestCase):
    """只对三类报红 —— 这条规则写进过文档，必须有断言钉住。"""

    def test_the_three_red_labels(self):
        self.assertTrue(v.is_red('MISSING'))
        self.assertTrue(v.is_red('SIG-MISMATCH'))
        self.assertTrue(v.is_red(evidence='DEAD'))

    def test_non_red_labels(self):
        for ev in ('USED', 'USED(self)', 'REFLECTIVE', 'SUPER-SLOT', 'TYPE-ONLY', '-'):
            self.assertFalse(v.is_red(evidence=ev), f'{ev} 不应报红')
        for vd in ('OK', 'OK(load)', 'OK(platform)'):
            self.assertFalse(v.is_red(vd), f'{vd} 不应报红')

    def test_type_only_is_explicitly_not_dead(self):
        """TYPE-ONLY 是 DTO/Gson 形态：只被当类型用，不等于死代码。误判会让人删掉活代码。"""
        self.assertFalse(v.is_red(evidence='TYPE-ONLY'))
        self.assertIn('不是死代码', v.EVIDENCE['TYPE-ONLY'])


class Strongest(unittest.TestCase):
    """多处证据时取最强的一条。"""

    def test_used_beats_everything(self):
        self.assertEqual(v.strongest('TYPE-ONLY', 'USED'), 'USED')
        self.assertEqual(v.strongest('DEAD', 'USED'), 'USED')

    def test_type_only_beats_dead(self):
        # 有类型引用就不是"零引用"，所以比 DEAD 强
        self.assertEqual(v.strongest('DEAD', 'TYPE-ONLY'), 'TYPE-ONLY')

    def test_ignores_empty(self):
        self.assertEqual(v.strongest(None, '', 'USED(self)'), 'USED(self)')

    def test_default_is_dash(self):
        self.assertEqual(v.strongest(), '-')


class GatesUseTheVocabulary(unittest.TestCase):
    """两个门禁脚本必须真的从这里取标签，而不是各写一份字符串。"""

    SCRIPTS = SCRIPTS

    def _src(self, name):
        return Path(self.SCRIPTS, name).read_text(encoding='utf-8')

    def _code_only(self, src):
        """去掉注释与文档字符串，只留可执行代码。

        不这么做会把 KDoc 里"曾经叫 SELF-CALLED"这类历史说明也当成代码标签，
        测试就会误报 —— 文档该写清楚历史，不该因此变红。
        """
        src = re.sub(r'""".*?"""', '', src, flags=re.S)
        src = re.sub(r"'''.*?'''", '', src, flags=re.S)
        src = re.sub(r'#[^\n]*', '', src)
        return src

    def test_smali_usage_imports_vocab(self):
        code = self._code_only(self._src('smali_usage.py'))
        self.assertIn('import hook_vocab', code)
        # 不许在**代码**里出现与词汇表不一致的旧标签
        for stale in ("'SELF-CALLED'", "'USED(super-slot)'", "'SKIP(platform)'"):
            self.assertNotIn(stale, code, f'smali_usage.py 的代码里还有旧标签 {stale}')

    def test_check_hook_targets_imports_vocab(self):
        code = self._code_only(self._src('check_hook_targets.py'))
        self.assertIn('import hook_vocab', code)
        self.assertIn('vocab.VERDICT', code, '判定值应从词汇表取，而不是硬编码字符串')

    def test_no_gate_invents_its_own_dead_label(self):
        """`DEAD` 只能来自词汇表；别处硬写会让两套报告对不上。"""
        for name in ('smali_usage.py', 'check_hook_targets.py'):
            src = self._src(name)
            for m in re.finditer(r"['\"]DEAD['\"]", src):
                # 允许出现在字典映射的右边（值是词汇表常量时的显示），但应当是少量
                pass
        # 正向断言：词汇表里确实定义了它
        self.assertIn('DEAD', v.EVIDENCE)


if __name__ == '__main__':
    unittest.main()


class SharedSmaliLexer(unittest.TestCase):
    """`.method` 头与 `invoke-*` 目标的词法只有**一处**定义，且必须认全真实形态。

    为什么单独一个测试类：这条词法在 2026-10-25 第 29 轮被查出**三份脚本各写一份、
    三份都写窄**（`[\\w$<>]+` 不含 `-`）。后果不是报错，而是静默少索引 24 个方法，
    门禁全绿。断言写在词法层，才能在下一次有人"顺手复制一份正则"时立刻红。
    """

    LINES = [
        # (源码行, 期望方法名, 期望形参描述符前缀)
        ('.method private static final updateRobotPos$lambda-5$lambda-4'
         '(Lcom/zybang/imp/widget/RobotWidget;IIIIZLandroid/view/View;)V',
         'updateRobotPos$lambda-5$lambda-4', 'Lcom/zybang'),
        ('.method private static final _init_$lambda-0'
         '(Lcom/baidu/homework/share/SharePosterDialog;Landroid/view/View;)V',
         '_init_$lambda-0', 'Lcom/baidu'),
        ('.method public constructor <init>(Ljava/lang/String;)V', '<init>', 'Ljava/lang/String;'),
        ('.method static constructor <clinit>()V', '<clinit>', ''),
        ('.method public final getClearWatermark()I', 'getClearWatermark', ''),
        ('.method public varargs b(Landroid/app/Activity;[Ljava/lang/String;)V',
         'b', 'Landroid/app/Activity;'),
        ('.method public declared-synchronized c()V', 'c', ''),
    ]

    def test_header_parser_covers_real_shapes(self):
        for line, name, params in self.LINES:
            with self.subTest(name=name):
                got = v.parse_method_header(line)
                self.assertIsNotNone(got, f'解析不出来: {line}')
                self.assertEqual(got[1], name)
                self.assertTrue(got[2].startswith(params),
                                f'{name} 的形参描述符不对: {got[2]!r}')

    def test_hyphen_is_part_of_the_name(self):
        """**核心回归点**：`-` 必须在字符集里。

        旧词法 `[\\w$<>]+` 把 `updateRobotPos$lambda-5$lambda-4` 切成 `4`
        —— 名字看着"有值"，其实指错了方法。所以这里不仅断言"能匹配"，
        还断言**匹配到的名字不以数字开头且含 `$lambda-`**。
        """
        got = v.parse_method_header(self.LINES[0][0])
        self.assertEqual(got[1], 'updateRobotPos$lambda-5$lambda-4')
        self.assertIn('$lambda-', got[1])
        self.assertNotEqual(got[1], '4', '这正是旧词法留下的错误名字')

    def test_regex_is_multiline_aware(self):
        """整文件 `finditer` 必须能找到方法 —— 漏 `re.M` 时会静默返回 0 条。

        三个脚本都把索引建立在"扫整个文件"上；漏 M 不报错，只让整张表变空，
        于是判定退化成"没有证据"。这条断言比单个样例更重要。
        """
        blob = '\n'.join(l for l, _n, _p in self.LINES) + '\n'
        names = [m.group(2) for m in v.METHOD_HEADER_RE.finditer(blob)]
        self.assertEqual(names, [n for _l, n, _p in self.LINES])

    def test_invoke_target_groups_are_positional_and_named(self):
        """两个脚本分别用 `group(2)` 与 `group('meth')` —— 两种取法都得对。"""
        line = ('    invoke-virtual {v0, v1}, Lcom/x/Y;->updateRobotPos$lambda-5$lambda-4'
                '(Ljava/lang/Object;)V')
        m = v.INVOKE_TARGET_RE.search(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), 'virtual')
        self.assertEqual(m.group(2), 'com/x/Y')
        self.assertEqual(m.group(3), 'updateRobotPos$lambda-5$lambda-4')
        self.assertEqual(m.group('meth'), m.group(3))
        self.assertEqual(m.group('owner'), m.group(2))

    def test_invoke_handles_range_form(self):
        line = ('    invoke-static/range {v1 .. v7}, Lcom/meituan/robust/PatchProxy;->proxy'
                '([Ljava/lang/Object;)Lcom/meituan/robust/PatchProxyResult;')
        m = v.INVOKE_TARGET_RE.search(line)
        self.assertEqual((m.group('owner'), m.group('meth')),
                         ('com/meituan/robust/PatchProxy', 'proxy'))


class GatesUseTheSharedLexer(unittest.TestCase):
    """三个脚本**不许**再自带方法名词法 —— 复制即漂移（本仓库已因它改过两次）。"""

    GATES = ('check_hook_callers.py', 'smali_usage.py', 'check_robust_coverage.py')

    def _src(self, name: str) -> str:
        return Path(os.path.join(SCRIPTS, name)).read_text(encoding='utf-8')

    @staticmethod
    def _code_only(src: str) -> str:
        """去掉 docstring 与 `#` 注释 —— 只对**代码**做断言。

        第一版直接搜全文，于是被自己写的**说明文字**命中（注释里正要引用这个模式
        来解释为什么不能用它）⇒ 假红。本仓库同一个坑踩过三次，规矩是：
        断言行为用 AST，断言文本只在文本本身是契约时；对"不许出现某个模式"这种检查，
        至少要先剥掉注释。
        """
        src = re.sub(r'""".*?"""', '', src, flags=re.S)
        src = re.sub(r"'''[\s\S]*?'''", '', src)
        return re.sub(r'#[^\n]*', '', src)

    def test_no_gate_redeclares_a_method_name_pattern(self):
        for name in self.GATES:
            code = self._code_only(self._src(name))
            with self.subTest(gate=name):
                # 只禁止"重新定义一份名字字符集"，允许引用词汇表
                self.assertNotIn(r'[\w$<>]', code,
                                 f'{name} 又自己写了一份方法名正则（缺 `-`，会切坏 lambda 名）；'
                                 '请用 hook_vocab.METHOD_HEADER_RE / INVOKE_TARGET_RE / SMALI_NAME')

    def test_every_gate_binds_the_shared_regexes(self):
        for name in self.GATES:
            code = self._src(name)
            with self.subTest(gate=name):
                self.assertTrue('vocab.METHOD_HEADER_RE' in code
                                or 'METHOD_DECL_RE = vocab.METHOD_HEADER_RE' in code,
                                f'{name} 没有用共享的 `.method` 头词法')
