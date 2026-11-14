#!/usr/bin/env python3
"""
`check_declared_counts` 必须认得出文档里**每一种**写功能数的形态。

## 为什么需要这份测试

这个检查长期存在，但它只认 `**N/M 个功能是热开关**` 一种写法。于是根
`README.md` 里那句 `**34 个功能**、**32 个热开关**` 从来没被校验过 ——
实际是 33 个热开关，这个数字静静过期了很久，没有任何门禁会说话。

2026-10-25 发现后放宽了正则，把 `**N 个热开关**` 与 `N 个热开关` 也纳进来，
那次一口气抓出 3 处过期数字（32 个热开关 / 28 功能 / 28/28 features）。

**教训**：门禁的正则写窄 = 那一整类声明不受保护，而且**看起来是绿的**。
这份测试把每种形态钉住，谁再收窄就会红。

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))


def _load():
    spec = importlib.util.spec_from_file_location(
        'cfp', os.path.join(ROOT, 'module', 'scripts', 'check_feature_parity.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CFP = _load()


class EverySpellingIsChecked(unittest.TestCase):
    """每种写法都必须被校验；写法错时不报错才是 bug。"""

    TOTAL = 10
    HOT = 7

    def _errors(self, readme_text):
        d = Path(tempfile.mkdtemp())
        (d / 'module').mkdir()
        (d / 'README.md').write_text(readme_text, encoding='utf-8')
        return CFP.check_declared_counts(d / 'module', d, self.TOTAL, self.HOT)

    def test_slash_form(self):
        errs = self._errors('共 **10 个功能**，7/10 个功能是热开关\n')
        self.assertEqual(errs, [])

    def test_slash_form_bold(self):
        errs = self._errors('**7/10 个功能是热开关**\n')
        self.assertEqual(errs, [])

    def test_bare_hot_count_form(self):
        """`**N 个热开关**` —— 根 `README.md` 的写法，长期未被校验。"""
        errs = self._errors('**10 个功能**、**7 个热开关**\n')
        self.assertEqual(errs, [])

    def test_bare_hot_count_without_bold(self):
        errs = self._errors('本模块 7 个热开关\n')
        self.assertEqual(errs, [])

    # ── 第 3 次失效（2026-10-26 第 36 轮）新增的三种形态 ──────────────────
    #
    # 这三种此前**一条都不被校验**，于是三处过期数字同时活着：
    #   README.md:86   `**35 功能**`（无「个」）
    #   README.md:283  `18 个功能逐行给出`
    #   PARADIGM.md    `模块有 34 个功能`（而且这个文件从来没被扫过）

    def test_count_without_the_counter_word(self):
        """`**N 功能**` —— 没有「个」字。根 README 的状态节就是这种写法。"""
        errs = self._errors('**10 功能**（7 个热开关）\n')
        self.assertEqual(errs, [])

    def test_count_without_the_counter_word_wrong(self):
        self.assertTrue(self._errors('**9 功能**\n'))

    def test_line_wise_wording(self):
        """`N 个功能逐行给出` —— VERIFICATION 矩阵行数的声明。"""
        errs = self._errors('10 个功能逐行给出：分类 / 默认 / …\n')
        self.assertEqual(errs, [])

    def test_line_wise_wording_wrong(self):
        # 这正是实际发生的：矩阵有 36 行，README 写 18。
        self.assertTrue(self._errors('18 个功能逐行给出：分类 / 默认 / …\n'))

    def test_module_subject_wording(self):
        """`模块有 N 个功能` —— PARADIGM 的写法，而这个文件此前从未被扫。"""
        errs = self._errors('模块有 10 个功能，各自装钩子。\n')
        self.assertEqual(errs, [])

    def test_module_subject_wording_wrong(self):
        self.assertTrue(self._errors('模块有 34 个功能，各自装钩子。\n'))


class SubsetsAndOrdinalsAreNotTotals(unittest.TestCase):
    """**不许**把"子集/单文件/序数"当成总数 —— 误报会让整条门禁被关掉。

    这四条都是从真仓库里摘的原句，全都**本来就对**。一刀切的"凡是 N 个功能
    都等于总数"会让它们全红，而它们并没有错。
    """

    TOTAL = 36
    HOT = 35

    def _errors(self, text):
        d = Path(tempfile.mkdtemp())
        (d / 'module').mkdir()
        (d / 'README.md').write_text(text, encoding='utf-8')
        return CFP.check_declared_counts(d / 'module', d, self.TOTAL, self.HOT)

    def test_logcat_only_subset(self):
        """ACTIVITY §二：`这 12 个功能改变行为…`（12 是子集，不是总数）。"""
        self.assertEqual(self._errors('这 12 个功能改变行为或只走 `KdLog`\n'), [])

    def test_single_file_subset(self):
        """PARADIGM：`AdFeatures.kt 的 7 个功能`（单个文件内，不是模块总数）。"""
        self.assertEqual(self._errors('`AdFeatures.kt` 的 7 个功能全写 `12/12`\n'), [])

    def test_ordinal_is_not_a_count(self):
        """OPTIMIZATION：`第 29 个功能 watermark_off` —— 序数。"""
        self.assertEqual(self._errors('### 10.1 第 29 个功能 `watermark_off`\n'), [])

    def test_ordinal_in_bold_is_not_a_count(self):
        self.assertEqual(self._errors('这是第 **29** 个功能\n'), [])

    def test_historical_per_round_value(self):
        """OPTIMIZATION 的"当轮值"：`31 个功能一致`（历史记录，不追改）。"""
        self.assertEqual(self._errors('③ 功能表/子选项 31 个功能一致〔当轮值〕\n'), [])


class WrongNumbersAreCaught(unittest.TestCase):

    TOTAL = 10
    HOT = 7

    def _errors(self, readme_text):
        d = Path(tempfile.mkdtemp())
        (d / 'module').mkdir()
        (d / 'README.md').write_text(readme_text, encoding='utf-8')
        return CFP.check_declared_counts(d / 'module', d, self.TOTAL, self.HOT)

    def test_wrong_total(self):
        self.assertTrue(self._errors('共 **8 个功能**\n'))

    def test_wrong_hot_in_bare_form(self):
        # 这正是 2026-10-25 实际发生的：写 32，实际 33。
        self.assertTrue(self._errors('**10 个功能**、**5 个热开关**\n'))

    def test_wrong_slash(self):
        self.assertTrue(self._errors('4/10 个功能是热开关\n'))


class ReadmeTableMustBeContiguousAndUnique(unittest.TestCase):
    """功能表必须是一段**连续的**表格，且每个 id 恰好登记一次。

    2026-10-26 实测到两个同时存在的缺陷，两者都被旧实现（`set` + `header_seen` 状态机）
    变成了"绿色"：

      * README 第 137 行有一个空行，把功能表劈成两半 ⇒ 后半段 6 行的「热」「选项」
        两列**从未被校验**。把 `vip_unlock` 的热列从 `是` 改成 `否`（代码 `hot = true`）
        门禁仍然全绿。
      * 空行之后 `web_picture_watermark` 又登记了一遍 ⇒ 物理 36 行 / 唯一 35 个 id，
        而摘要打印的是 `len(set)` 却标成"行"，读起来正好对得上。

    两条都用**合成 README** 钉住，不依赖真仓库的排版（真仓库已经修好了，
    只测真仓库的话，将来有人重新插入空行时这里不会有任何断言会红）。
    """

    HEAD = (
        '| id | 名称 | 类别 | 默认 | 实现要点 | 热 | 选项 |\n'
        '|---|---|---|---|---|---|---|\n'
    )

    def _row(self, fid, hot='是'):
        return f'| `{fid}` | 名称 | 宿主 | 关 | 要点 | {hot} | — |\n'

    def _errors(self, text, attrs=None):
        d = Path(tempfile.mkdtemp())
        p = d / 'README.md'
        p.write_text(text, encoding='utf-8')
        attrs = attrs if attrs is not None else {
            'aa': {'hot': True, 'options': []},
            'bb': {'hot': True, 'options': []},
        }
        return CFP.check_readme_columns(d, p, attrs)

    def test_blank_line_inside_table_is_caught(self):
        """空行切断表格 ⇒ 必须报"被切开了"，而不是悄悄少校验几行。"""
        text = self.HEAD + self._row('aa') + '\n' + self._row('bb')
        errs = self._errors(text)
        self.assertTrue(any('被切开' in e for e in errs), errs)

    def test_wrong_hot_hidden_behind_blank_line_is_caught(self):
        """这正是修复前漏掉的那个：空行之后的错误热列。"""
        text = self.HEAD + self._row('aa') + '\n' + self._row('bb', hot='否')
        errs = self._errors(text)
        self.assertTrue(any("`bb` 标的热" in e for e in errs), errs)

    def test_duplicate_row_is_caught(self):
        text = self.HEAD + self._row('aa') + self._row('aa') + self._row('bb')
        errs = self._errors(text)
        self.assertTrue(any('登记了两次' in e for e in errs), errs)

    def test_clean_table_has_no_errors(self):
        text = self.HEAD + self._row('aa') + self._row('bb')
        self.assertEqual(self._errors(text), [])

    def test_rows_after_a_heading_are_not_counted_as_table_rows(self):
        """表格之外的 `| \\`id\\` |` 形行不算登记 —— 否则正文里提一句就能骗过门禁。"""
        d = Path(tempfile.mkdtemp())
        p = d / 'README.md'
        p.write_text(self.HEAD + self._row('aa') + '\n## 别处\n' + self._row('zz'),
                     encoding='utf-8')
        self.assertEqual([fid for _n, fid, _l in CFP.readme_feature_rows(p)], ['aa'])
        self.assertEqual([fid for _n, fid in CFP.stray_feature_rows(p)], ['zz'])


class RealReadmeTableIsWellFormed(unittest.TestCase):
    """真仓库的功能表必须连续、无重复、行数等于唯一 id 数。"""

    def test_no_stray_and_no_duplicate(self):
        readme = Path(ROOT) / 'module' / 'README.md'
        self.assertEqual(CFP.stray_feature_rows(readme), [],
                         'README 功能表被切开了（表外还有同形功能行）')
        rows = CFP.readme_feature_rows(readme)
        ids = [fid for _n, fid, _l in rows]
        self.assertEqual(len(ids), len(set(ids)),
                         f'README 功能表有重复登记：{sorted(i for i in set(ids) if ids.count(i) > 1)}')
        # **不写死数字**：写死 35 的话，加第 36 个功能时这条测试会红，
        # 而它红的原因是"测试过期"不是"代码有问题" —— 那种红最浪费时间。
        # 正确做法是拿注册表的真实数量比。
        registry = Path(ROOT) / 'module' / 'app' / 'src' / 'main' / 'java' / \
            'dev' / 'xalor' / 'kdkit' / 'features' / 'FeatureRegistry.kt'
        n_registry = len(CFP.parse_registry_objects(registry))
        self.assertEqual(len(ids), n_registry,
                         f'功能表行数 {len(ids)} 与注册表条目 {n_registry} 不符')


class RealRepoIsConsistent(unittest.TestCase):
    """真实仓库当前必须自洽 —— 有错的话说明又有人改了数字没同步。"""

    def test_repo_passes(self):
        """真仓库必须自洽。

        走 subprocess 而不是 `CFP.main()`：后者读 sys.argv，在测试进程里会炸。
        """
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'module', 'scripts',
                                          'check_feature_parity.py')],
            capture_output=True, text=True, cwd=ROOT,
timeout=300, )
        self.assertEqual(r.returncode, 0,
                         f'功能表校验未通过：\n{r.stdout[-600:]}\n{r.stderr[-300:]}')


class VerificationColumnsAreFoundByName(unittest.TestCase):
    """`真机` 列必须**按表头名定位**，不能靠 `cells[8]` 这种写死下标。

    写死下标的失效方式很隐蔽：有人插一列之后，代码会认真地校验**另一列**，
    而且照样返回空错误列表 —— 门禁变绿，但已经不再看它声称在看的东西。
    这与 `OPTIMIZATION.md` §40"结论依赖于目标在列表里的位置"是同一种病。
    """

    ATTRS = {'aa': {'hot': True, 'options': []}}

    def _errs(self, header, row):
        d = Path(tempfile.mkdtemp()) / 'module'
        d.mkdir()
        (d / 'VERIFICATION.md').write_text(header + row, encoding='utf-8')
        return CFP.check_verification_doc(d, self.ATTRS)

    def test_blank_real_column_is_caught_with_extra_column(self):
        """在 `真机` 之前插一列，空值仍必须被抓住（旧实现会漏）。"""
        header = ('| feature | 标题 | 分类 | 默认 | 当前 | 记录数 | 静态钩子 | 新增列 | 验证等级 | 真机 | 依据 |\n'
                  '|---|---|---|---|---|---|---|---|---|---|---|\n')
        row = '| `aa` | t | HOST | false | ? | 0 | 1/1 | — | **强** |  | x |\n'
        errs = self._errs(header, row)
        self.assertTrue(any('真机' in e and '为空' in e for e in errs), errs)

    def test_filled_real_column_passes_with_extra_column(self):
        header = ('| feature | 标题 | 分类 | 默认 | 当前 | 记录数 | 静态钩子 | 新增列 | 验证等级 | 真机 | 依据 |\n'
                  '|---|---|---|---|---|---|---|---|---|---|---|\n')
        row = '| `aa` | t | HOST | false | ? | 0 | 1/1 | — | **强** | 未验证 | x |\n'
        self.assertEqual(self._errs(header, row), [])

    def test_missing_real_column_header_is_reported(self):
        header = ('| feature | 标题 | 分类 | 默认 | 当前 | 记录数 | 静态钩子 | 验证等级 | 依据 |\n'
                  '|---|---|---|---|---|---|---|---|---|\n')
        errs = self._errs(header, '')
        self.assertTrue(any('真机' in e for e in errs), errs)


class QuotedHistoryIsNotADeclaration(unittest.TestCase):
    """**引用**旧值不算**声称**当前值。

    这条是本轮修 bug 时撞出来的：我把"当时文档写的 34 个功能"写进 PARADIGM 的
    记录表格，门禁立刻把这句话当成新声明报红。文档越诚实地记录历史，
    越容易被自己的门禁误伤 —— 误报累积到一定程度，人就把它关掉了。

    修法：反引号 / 直引号 / 书名号里的内容不参与匹配（替换成等长空白）。
    """

    TOTAL = 36
    HOT = 35

    def _errors(self, text):
        d = Path(tempfile.mkdtemp())
        (d / 'module').mkdir()
        (d / 'README.md').write_text(text, encoding='utf-8')
        return CFP.check_declared_counts(d / 'module', d, self.TOTAL, self.HOT)

    def test_backticked_old_value_is_not_flagged(self):
        self.assertEqual(self._errors('当时它写着 `模块有 34 个功能`。\n'), [])

    def test_straight_quoted_old_value_is_not_flagged(self):
        self.assertEqual(self._errors('本文件里那句"模块有 34 个功能"没有任何门禁会说话。\n'), [])

    def test_cjk_quoted_old_value_is_not_flagged(self):
        self.assertEqual(self._errors('「模块有 34 个功能」是过期的那句。\n'), [])

    def test_genuine_declaration_outside_quotes_is_still_caught(self):
        """反向：引号**外**的真声明必须照旧被抓。否则屏蔽就把门禁弄瞎了。"""
        self.assertTrue(self._errors('模块有 34 个功能，各自装钩子。\n'))

    def test_declaration_next_to_a_quoted_old_value(self):
        """同一行里既有引用又有真声明 ⇒ 只抓真声明。"""
        errs = self._errors('它曾写"模块有 34 个功能"，现在模块有 30 个功能。\n')
        self.assertTrue(errs, '真声明没有被抓到')
        self.assertTrue(any('30' in e for e in errs), errs)

    def test_backticked_command_mentioning_counts_is_not_flagged(self):
        """```代码块里提到数量也不该被判（那是命令/示例，不是声明）。"""
        self.assertEqual(self._errors('```\ngrep "共 **34 个功能**"\n```\n'), [])


if __name__ == '__main__':
    unittest.main()
