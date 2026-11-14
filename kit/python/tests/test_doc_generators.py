#!/usr/bin/env python3
"""
Offline tests: the two **document generators** must not lie about their own inputs.

Why this file exists
--------------------
`module/ACTIVITY.md` and `module/VERIFICATION.md` both say "自动生成" and both say how to
regenerate themselves. On 2026-10-25 two separate ways that promise was broken were found,
and neither was caught by the seven gates:

  1. **`ACTIVITY.md` 的复现命令跑不起来。** 它拼的是前 3 个 `--capture <路径>`，
     其中 `capture_kd1_r11.txt` 早就不存在了 ⇒ 照抄就 `FileNotFoundError`。
     一份"可复现"的文档给出跑不通的命令，比不给更糟：下一个人会以为数据是手编的。

  2. **重跑会抹掉手工附录。** `ACTIVITY.md` 的 `## 七、功能 ↔ 抓取前缀对照表` 是手写的，
     同时是 ③ 门禁的输入（`check_activity_doc` 要求每个 feature id 出现在本文件里）。
     生成器把整个文件当自己的领地 ⇒ "照文档说的重跑"直接把门禁打红。
     2026-10-25 的后台轮次真的丢过这张表。

  3. **`VERIFICATION.md` 的「静态钩子」列是按文件计的。** `AdFeatures.kt` 里 7 个功能、
     12 个钩子，7 行全都写 `12/12` —— `rm_feed_ad`（2 个钩子）和 `rm_splash`（3 个）
     看起来一模一样；`page_js` 一个钩子都没有也写 `4/4`。这一列本应回答
     "**这个功能**的钩子解析成功几个"。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# tests -> python -> kit -> 仓库根（三层）
KIT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCRIPTS = os.path.join(KIT, 'kit', 'scripts')
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(KIT, 'kit', 'python'))

from hook_vocab import read_text  # noqa: E402  (必须在 sys.path 设置之后)

ACTIVITY = os.path.join(KIT, 'module', 'ACTIVITY.md')
VERIFICATION = os.path.join(KIT, 'module', 'VERIFICATION.md')
INPUT_DIR = os.path.join(KIT, 'work', 'activity_inputs')


def py(script, *args):
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script), *args],
                       capture_output=True, text=True, cwd=KIT, timeout=300)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


class ActivityReproCommand(unittest.TestCase):
    """`ACTIVITY.md` 里写的那条命令必须**真的能跑**，且产出同样的数字。"""

    def repro_line(self):
        text = read_text(ACTIVITY)
        m = re.search(r'^\* 复现：`([^`]+)`', text, re.M)
        self.assertIsNotNone(m, 'ACTIVITY.md 没有「复现：`…`」这一行')
        return m.group(1)

    def test_repro_paths_all_exist(self):
        """命令里提到的每个路径都要存在 —— 旧版写了一个已删除的抓取文件。"""
        cmd = self.repro_line()
        paths = re.findall(r'(?:--dir|--capture|--out)\s+(\S+)', cmd)
        self.assertTrue(paths, f'复现命令里没有可识别的路径：{cmd}')
        for p in paths:
            with self.subTest(path=p):
                full = os.path.join(KIT, p)
                # `--out` 是产物，允许尚不存在；其余是输入，必须存在。
                if '--out' in cmd and cmd.split('--out')[1].strip() == p:
                    continue
                self.assertTrue(os.path.exists(full), f'复现命令引用了不存在的路径：{p}')

    def test_repro_reproduces_the_same_numbers(self):
        """真的照它跑一遍，对比第一张表的每一行 —— 数字必须逐个相同。"""
        cmd = self.repro_line()
        args = cmd.split()
        args[0:2] = []                        # 去掉 `python3 kit/scripts/module_activity.py`
        out = os.path.join(tempfile.mkdtemp(), 'ACT.md')
        if '--out' in args:
            args[args.index('--out') + 1] = out
        else:
            args += ['--out', out]
        rc, log = py('module_activity.py', *args)
        self.assertEqual(rc, 0, log)

        def table(path):
            rows = {}
            with open(path, encoding='utf-8') as fh:
                lines = fh.readlines()
            for ln in lines:
                m = re.match(r'^\| `([a-z0-9_]+)` \| (\d+) \| (\d+)/(\d+) \|', ln)
                if m:
                    rows[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
            return rows

        self.assertEqual(table(out), table(ACTIVITY),
                         '照 ACTIVITY.md 的复现命令重跑，得到的数字与文档不一致')


class CountsDerivedNotTyped(unittest.TestCase):
    """生成物里的数字必须**从数据推出**，不能手写。

    2026-10-25 第 28 轮实测到两处，都是"文档自己和自己矛盾，而门禁全绿"：

      * `module_activity.py` 写着"这 **11** 个功能…只走 KdLog"，而紧随其后的表
        由 `FEATURES_LOGCAT_ONLY` 生成、已是 **12** 行；
      * `ACTIVITY.md` §七之二 手工附录写着"下面 **9** 个功能钩的是广告视图"，
        而那张表有 **10** 行。

    两处都不是新退化：功能数从 11→12、9→10 时，没人注意到同一个屏上的两个数字。
    这类失效**没有任何 FAIL**（文档生成成功、表格渲染正常），所以只能靠断言抓。

    判据不是"数字等于某个常量"——那会在加功能时变成又一个要手改的数字。
    判据是"文档里声称的 N == 实际行数"。
    """

    def test_logcat_only_claim_matches_table_rows(self):
        text = read_text(ACTIVITY)
        m = re.search(r'\*\*只写 logcat 的功能 (\d+) 个\*\*', text)
        self.assertIsNotNone(m, 'ACTIVITY.md 判据节丢了「只写 logcat 的功能 N 个」')
        claimed = int(m.group(1))

        # §二 的表体行数 = 真正的行数
        sec = text.split('## 二、')[1].split('## 三、')[0]
        rows = [ln for ln in sec.splitlines() if ln.startswith('| `')]

        # 同一节里那句"这 N 个功能…不写抓取文件"也必须一致
        m2 = re.search(r'这 (\d+) 个功能改变行为或只走 `KdLog`', sec)
        self.assertIsNotNone(m2, '§二 丢了「这 N 个功能…」那句')

        self.assertEqual(int(m2.group(1)), len(rows),
                         f'§二 正文说 {m2.group(1)} 个，表里是 {len(rows)} 行')
        self.assertEqual(claimed, len(rows),
                         f'判据节说 {claimed} 个，§二 表里是 {len(rows)} 行')

    def test_appendix_claim_matches_table_rows(self):
        text = read_text(ACTIVITY)
        m = re.search(r'下面 (\d+) 个功能钩的是广告视图', text)
        self.assertIsNotNone(m, '§七之二 丢了「下面 N 个功能钩的是广告视图」')
        claimed = int(m.group(1))
        sec = text.split('### 七之二')[1].split('**这条表也是门禁**')[0]
        rows = [ln for ln in sec.splitlines() if ln.startswith('| `')]
        self.assertEqual(claimed, len(rows),
                         f'§七之二 正文说 {claimed} 个，表里是 {len(rows)} 行')

    def test_generator_has_no_hardcoded_logcat_count(self):
        """生成器里不许出现"这 N 个"的字面量 —— 必须走 `len(...)`。"""
        src = read_text(os.path.join(KIT, 'kit/scripts/module_activity.py'))
        bad = re.findall(r"w\('这 (\d+) 个功能", src)
        self.assertEqual(bad, [], f'生成器手写了 logcat 功能数 {bad}，应改成 len(FEATURES_LOGCAT_ONLY)')


class OwnerlessPrefixesAreNotSilentlyDropped(unittest.TestCase):
    """没有任何归属功能的前缀（`MARK`）不许被**静默**排除。

    ## 为什么单独一条

    `module_activity.py` 里曾经写的是：

        no_sample = [k for k in PREFIX_FEATURE if k not in ('MARK',) and kinds.get(k, 0) == 0]

    `MARK`（`=== KdKit host=…` / `=== HookCore start …`）在 5 份冻结抓取里是
    **0 行**，而这一行硬编码把它从"没有样本"的表里剔掉了 —— 既不说原因，
    也不在输出里提一句。于是"这批抓取连一行启动标记都没有"这个事实，
    在 `ACTIVITY.md` 里完全没有痕迹。

    这跟本项目此前修的几次是同一类：**不是判错了，而是根本没让它进入判定**。

    修法：从 `PREFIX_FEATURE` 派生（`is None` ⇒ 无主），而不是写死名字；
    并且把结论写进 §四之二。新加一个无主前缀会自动落到那里，不需要改代码。
    """

    def test_mark_is_the_only_ownerless_kind_today(self):
        """前提断言：现在确实只有 `MARK` 没有归属功能。变了就该重看这段。"""
        import capture_schema as cs
        ownerless = sorted(k for k, v in cs.PREFIX_FEATURE.items() if v is None)
        self.assertEqual(ownerless, ['MARK'],
                         f'无主前缀集合变了：{ownerless} —— '
                         f'ACTIVITY §四之二 的说明文字要跟着改')

    def test_generator_derives_ownerless_instead_of_hardcoding_a_name(self):
        """生成器不许再写死 `'MARK'` 这种具名排除。

        注意：注释里**提到**旧写法是允许的（那段注释解释了为什么改），
        所以这里只扫**能执行的代码行** —— 否则"解释这个 bug"反而会让测试红。
        """
        src = read_text(os.path.join(KIT, 'kit/scripts/module_activity.py'))
        code = [ln.split('#', 1)[0] for ln in src.splitlines()]
        joincode = '\n'.join(code)
        self.assertNotIn("k not in ('MARK',)", joincode,
                         '生成器的代码里又写死了 MARK —— 应改成 PREFIX_FEATURE[k] is None')
        self.assertIn('PREFIX_FEATURE[k] is None', joincode,
                      '生成器没有从 PREFIX_FEATURE 派生无主前缀')

    @staticmethod
    def _mark_rows_in_doc(text):
        """从文档自己的 §五 分布表里读 `MARK` 的行数（读不到返回 None）。

        **判据必须跟着文档自己的输入走**：`ACTIVITY.md` 由哪份抓取生成，
        `MARK` 就可能是有行也可能是 0 行。旧实现直接断言"§四之二 必须存在"，
        于是换一份有 MARK 的抓取就红 —— 那不是文档错了，是测试把
        "某个输入下的结论"当成了永久要求。
        """
        m = re.search(r'^\|\s*`MARK`\s*\|\s*(\d+)\s*\|$', text, re.M)
        return int(m.group(1)) if m else None

    def test_ownerless_zero_row_prefix_is_documented(self):
        """无主前缀 0 行时必须有显式小节，不许让它消失。"""
        text = read_text(ACTIVITY)
        n = self._mark_rows_in_doc(text)
        if n is None or n > 0:
            self.skipTest(f'本份 ACTIVITY.md 的输入里 MARK 有 {n} 行 ⇒ 不适用 0 行那条结论')
        self.assertIn('四之二、基础设施前缀', text,
                      'ACTIVITY.md 缺少「无主前缀 0 行」小节 ⇒ MARK 又被静默丢了')
        sec = text.split('四之二')[1].split('## 五、')[0]
        self.assertIn('`MARK`', sec, '§四之二 里没有列出 `MARK`')
        self.assertIn('未验证', sec,
                      '§四之二 必须写明"为什么 0 行"是未验证的，不能给出结论')

    def test_ownerless_section_claims_zero_honestly(self):
        """§四之二 里标 `MARK` 为 0 行时，实际解析结果也必须是 0 —— 不许写反。"""
        text = read_text(ACTIVITY)
        n = self._mark_rows_in_doc(text)
        if n is None or n > 0:
            self.skipTest(f'本份 ACTIVITY.md 的输入里 MARK 有 {n} 行 ⇒ 不适用 0 行那条结论')
        self.assertIn('本轮标**未验证**', text)


class ActivityAppendixSurvives(unittest.TestCase):
    """手工附录跨重写存活 —— 它同时是 ③ 门禁的输入。"""

    def test_regenerating_keeps_handwritten_section(self):
        import shutil
        tmp = os.path.join(tempfile.mkdtemp(), 'ACT.md')
        shutil.copy(ACTIVITY, tmp)
        rc, log = py('module_activity.py', '--dir', 'work/activity_inputs', '--out', tmp)
        self.assertEqual(rc, 0, log)
        text = read_text(tmp)
        self.assertIn('## 七、功能 ↔ 抓取前缀对照表', text,
                      '重写把手工附录抹掉了（③ 会因为缺 feature id 报红）')
        # 附录里必须仍有全部 feature id —— 抄一遍 ③ 的判据
        from capture_schema import FEATURE_IDS
        missing = [f for f in FEATURE_IDS if f'`{f}`' not in text]
        self.assertEqual(missing, [], f'重写后 APPENDIX 丢了这些 feature：{missing}')


class ActivityCoverageGateIsStrict(unittest.TestCase):
    """③ 的 `check_activity_doc` 必须要求"出现在 §七 表格行里"，不是"全文提到过"。

    旧判据 `f'`{fid}`' in text` 让任何一次偶然提及都算通过 —— 而 §一「计数为 0」表
    是**生成器自动产出**的（来自 `FEATURES_WITH_CAPTURE`），不需要人维护。
    于是"新增功能忘了写进操作者需要维护的对照表"这件事，门禁永远发现不了。
    2026-10-25 收紧后当场查出 9 个功能从未在 §七 出现过。
    """

    def setUp(self):
        import importlib
        spec = os.path.join(KIT, 'module', 'scripts')
        sys.path.insert(0, spec)
        self.parity = importlib.import_module('check_feature_parity')

    def _attrs(self):
        import re as _re
        src = {}
        base = os.path.join(KIT, 'module', 'app', 'src', 'main', 'java')
        for root, _d, files in os.walk(base):
            for f in files:
                if f.endswith('.kt'):
                    p = os.path.join(root, f)
                    with open(p, encoding='utf-8') as fh:
                        src[p] = fh.read()
        return self.parity.feature_attrs(src)

    def test_current_doc_passes(self):
        errs = self.parity.check_activity_doc(
            __import__('pathlib').Path(os.path.join(KIT, 'module')), self._attrs())
        self.assertEqual(errs, [], f'ACTIVITY.md 现在过不了自己的门禁：{errs}')

    def test_mentioning_an_id_in_prose_is_not_enough(self):
        """反证：把某个 id 从 §七 的表格行删掉，只在正文里留一句提及 ⇒ 必须报红。

        用 `anti_detect`：它在 §二「只写 logcat」表里也有一行（那张表是生成器产的、
        不需要人维护），删掉 §七 的行之后正文里仍有提及。
        **删除必须限定在 §七 之内** —— 全局删会把 §二 的行也一起删掉，
        那样测的就是"完全没提到"，是更弱的情形。
        """
        import pathlib
        import shutil
        tmp = pathlib.Path(tempfile.mkdtemp())
        doc = tmp / 'ACTIVITY.md'
        shutil.copy(ACTIVITY, doc)
        text = doc.read_text(encoding='utf-8')
        idx = text.find('\n## 七、')
        self.assertGreater(idx, 0, '前提：ACTIVITY.md 有 §七')
        head, section = text[:idx], text[idx:]
        kept_section = '\n'.join(
            ln for ln in section.splitlines()
            if not re.match(r'^\|\s*`anti_detect`\s*\|', ln))
        doc.write_text(head + kept_section + '\n', encoding='utf-8')
        self.assertIn('`anti_detect`', doc.read_text(encoding='utf-8'),
                      '前提：§七 之外仍有提及（否则测的是"完全没提到"）')
        errs = self.parity.check_activity_doc(tmp, self._attrs())
        self.assertTrue(errs, '只在正文提及、§七 没有表格行，却通过了门禁')
        self.assertIn('anti_detect', ' '.join(errs))

    def test_missing_section_is_itself_an_error(self):
        import pathlib
        import shutil
        tmp = pathlib.Path(tempfile.mkdtemp())
        doc = tmp / 'ACTIVITY.md'
        shutil.copy(ACTIVITY, doc)
        text = doc.read_text(encoding='utf-8')
        doc.write_text(text.split('\n## 七、')[0], encoding='utf-8')
        errs = self.parity.check_activity_doc(tmp, self._attrs())
        self.assertTrue(errs, '整个 §七 都没了，门禁却通过')


class GateScriptsAreCwdIndependent(unittest.TestCase):
    """门禁脚本的默认路径不能依赖**调用者的当前目录**。

    2026-10-25 的真缺陷：④⑤⑥ 与 `smali_usage` 的 `--smali` 默认值是相对路径
    `'work/apktool_out'`。命令行一直没问题（`verify.sh` 用 `cd $ROOT` 兜住了），
    但 `feature_matrix.static_hook_evidence()` 是**从 Python 里**调
    `check_hook_signatures.py` 的，继承的是自己的 cwd ⇒ `listdir` 抛
    `FileNotFoundError` ⇒ 门禁返回空 ⇒ `VERIFICATION.md` 的「静态钩子」整列变 `-`。

    这个失效不报错，只让文档看起来"这些功能没有静态证据"。为此 ①b 的 13 个断言
    集体失败才被发现 —— 但那已经是**下游**了。这里直接钉住上游性质：
    从任意 cwd 跑，默认值都必须指向仓库里真实存在的目录。
    """

    def test_default_paths_are_absolute_and_exist(self):
        import hook_vocab
        for rel in ('work/apktool_out',
                    'module/app/src/main/java/dev/xalor/kdkit'):
            with self.subTest(rel=rel):
                got = hook_vocab.repo_path(rel)
                self.assertTrue(os.path.isabs(got), f'{rel} 解析成了相对路径：{got}')
                self.assertTrue(os.path.exists(got), f'{rel} 解析后不存在：{got}')

    def test_defaults_come_from_script_location_not_cwd(self):
        """把 cwd 换到别处，解析结果必须**逐字符相同**。"""
        import hook_vocab
        want = hook_vocab.repo_path('work/apktool_out')
        old = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            self.assertEqual(hook_vocab.repo_path('work/apktool_out'), want)
        finally:
            os.chdir(old)

    def test_gate_scripts_do_not_hardcode_relative_defaults(self):
        """反向验证的守卫：哪个脚本再写回 `default='work/apktool_out'` 就红。

        没有这条，上面两条只在 hook_vocab 层面成立 —— 脚本里照旧写相对路径，
        测试仍然全绿。这正是上一轮"断言常量而不是行为"的同类错误。
        """
        offenders = []
        for fn in ('check_hook_targets.py', 'check_hook_signatures.py',
                   'check_hook_callers.py', 'smali_usage.py'):
            path = os.path.join(SCRIPTS, fn)
            if not os.path.exists(path):
                continue
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            if re.search(r"default=['\"]work/apktool_out['\"]", text):
                offenders.append(fn)
        self.assertEqual(offenders, [],
                         '这些门禁又用上了相对默认路径（从别处调用会静默返回空）：'
                         + str(offenders))


class StaticEvidenceUsesPrivateTempFile(unittest.TestCase):
    """`static_hook_evidence()` 的输出文件必须**每次唯一**，且失败时不回落旧文件。

    两个真缺陷（2026-10-25 抓到）：
      1. 固定名 `/tmp/kdkit_sig_matrix.json` ⇒ 并发写同一个文件，读到半个 JSON，
         门禁①b 偶发红（4 路并发可稳定复现）；
      2. 旧代码 `if rc != 0 and not os.path.exists(out): return {}` —— 门禁**失败**时
         只要旧文件还在就继续读，等于用上一轮的证据冒充这一轮。这是"结论比事实乐观"，
         比失败本身更危险。
    """

    def test_no_fixed_temp_path_in_source(self):
        text = read_text(os.path.join(SCRIPTS, 'feature_matrix.py'))
        bad = re.findall(r"gettempdir\(\)[^\n]*kdkit_sig_matrix", text)
        self.assertEqual(bad, [], f'又回到固定临时路径了：{bad}')

    def test_gate_failure_returns_empty_by_control_flow(self):
        """用 AST 看**控制流**，而不是 grep 源码字符串。

        第一版这个测试用 `assertNotIn('rc != 0 and not os.path.exists', text)`，
        结果因为**注释里**描述了这条旧 bug 而误报红 —— 断言的是文本，不是行为。
        这里改成解析 `static_hook_evidence` 的语法树：`if rc != 0:` 的整个 body
        必须只有 `return {}`（可以带一条 docstring），不允许出现任何读取旧文件的动作。
        """
        import ast
        src = read_text(os.path.join(SCRIPTS, 'feature_matrix.py'))
        tree = ast.parse(src)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == 'static_hook_evidence'), None)
        self.assertIsNotNone(fn, '找不到 static_hook_evidence')

        guards = [n for n in ast.walk(fn)
                  if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Compare)
                  and isinstance(n.test.left, ast.Name)
                  and n.test.left.id == 'rc']
        self.assertTrue(guards, '没有 `if rc != 0:` 失败分支')
        for g in guards:
            body = [b for b in g.body if not (isinstance(b, ast.Expr)
                                              and isinstance(b.value, ast.Constant))]
            self.assertEqual(len(body), 1, '失败分支不该做别的事')
            self.assertIsInstance(body[0], ast.Return, '失败分支必须是 return')
            self.assertIsInstance(body[0].value, ast.Dict, '失败分支必须返回空字典')
            self.assertEqual(body[0].value.keys, [], '失败分支必须返回 {}')


class SampleDateComesFromDataNotFilesystem(unittest.TestCase):
    """「最晚一份抓取的日期」必须来自**登记表**，不能来自文件 mtime。

    2026-10-25 抓到：脱敏脚本就地改写了 5 份抓取 ⇒ mtime 全变"今天" ⇒ 这一行会写成
    "最晚一份是今天"。而真正的采样日是 2026-10-18。

    后果不是措辞问题，而是**结论方向反了**：`skip_update` / `vip_unlock` /
    `bridge_action_log` 在这批样本里必然 0 行，正确读法是"样本早于功能"；
    mtime 一漂，就变成"功能失效"。这正是 `ACTIVITY.md` 第四节存在的全部理由，
    借文件系统的时间会把它整节作废。
    """

    def test_readme_is_the_source_of_truth(self):
        readme = os.path.join(INPUT_DIR, 'README.md')
        if not os.path.exists(readme):
            self.skipTest('没有 work/activity_inputs/README.md')
        import sys as _sys
        _sys.path.insert(0, SCRIPTS)
        import module_activity as ma
        caps = sorted(os.path.join(INPUT_DIR, f) for f in os.listdir(INPUT_DIR)
                      if f.endswith('.txt'))
        self.assertTrue(caps, '没有抓取文件')
        for p in caps:
            with self.subTest(cap=os.path.basename(p)):
                got = ma._registered_sample_date(p)
                self.assertIsNotNone(
                    got, f'{os.path.basename(p)} 在 README 登记表里查不到采样日期')

    def test_generator_does_not_use_mtime(self):
        """反向守卫：源码里不许再用 `os.path.getmtime` **调用**决定采样日期。

        用 AST 找真实调用，不 grep 文本 —— 注释里解释"为什么不能用 getmtime"
        会让文本断言误报（同一个坑本文件里已踩过两次）。
        """
        import ast
        src = read_text(os.path.join(SCRIPTS, 'module_activity.py'))
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ('getmtime', 'getctime', 'getatime')]
        self.assertEqual(calls, [],
                         '采样日期又去借文件时间戳了 —— 改写抓取会让文档谎报日期')

    def test_unknown_date_is_question_mark_not_a_guess(self):
        import sys as _sys
        _sys.path.insert(0, SCRIPTS)
        import module_activity as ma
        got = ma._registered_sample_date('/nonexistent/dir/zzz_nope.txt')
        self.assertIsNone(got, '查不到时必须是 None（文档写 ?），不能返回一个猜的日期')


class StaticHookColumnIsPerFeature(unittest.TestCase):
    """「静态钩子」必须按**功能**归属，不是按文件。"""

    def setUp(self):
        import feature_matrix
        self.fm = feature_matrix
        self.static = self.fm.static_hook_evidence()

    def test_attribution_uses_feature_objects(self):
        """返回值必须按 object 名作键，不能是 `.kt` 文件名。"""
        self.assertTrue(self.static, '静态钩子解析为空（check_hook_signatures 失败？）')
        kt = [k for k in self.static if k.endswith('.kt')]
        self.assertEqual(kt, [], f'仍按文件归属：{kt}')

    def test_same_file_features_get_different_numbers(self):
        """`AdFeatures.kt` 的 7 个功能不能共享一个数字（旧版全是 12/12）。"""
        ad = {f['id']: self.static.get(f['cls'])
              for f in self.fm.features() if f['file'].endswith('AdFeatures.kt')}
        self.assertGreaterEqual(len(ad), 5, f'AdFeatures.kt 只解析出 {ad}')
        distinct = {v for v in ad.values() if v}
        self.assertGreater(len(distinct), 1,
                           f'同一文件里的功能拿到了相同的钩子数：{ad}')

    def test_feature_without_hooks_is_zero_not_borrowed(self):
        """`page_js` / `h5_debug` 自己没有钩子，不许借用同文件里 `ReqHeaders` 的 4 个。"""
        for f in self.fm.features():
            if f['id'] in ('page_js', 'h5_debug', 'pk_assist', 'native_exit_guard'):
                with self.subTest(feature=f['id']):
                    self.assertFalse(self.static.get(f['cls']),
                                     f'{f["id"]} 不该有钩子，却拿到 {self.static.get(f["cls"])}')

    def test_live_hooks_are_actually_counted(self):
        """反向验证：真有钩子的功能必须数得到，否则"修复"会以全 0 收场。"""
        # 只登记**签名门禁能静态看到**的钩子。下面这些功能用的是循环变量/反射式钩法，
        # ⑤ 里一条记录都没有 ⇒ 这一列必须是 None，而不是硬编一个数字：
        #   * `LogSink`：`for (m in listOf("v","d","i","w","e","wtf")) Xp.hookAll("android.util.Log", m, …)`
        #   * `WebRequestLog` / `ReqHeaders`：`XposedHelpers.findAndHookMethod(…)` 直接调
        # 之前这份期望表写的是 `req_headers:(4,4)` / `web_request_log:(4,4)`，
        # 与实际不符 —— 那不是"改坏了"，是从一开始就抄了文档里的数字。
        want = {
            'rm_splash': (3, 3),
            'rm_tab_ad': (4, 4),
            'rm_feed_ad': (2, 2),
            'req_headers': (3, 3),   # 实际值；它 3 条走 hookStatic/PerRequest/Volley
            'block_ad_sdk': (4, 4),
            'sign_observer': (8, 8),
            'vip_unlock': (3, 3),
            'vip_limit_probe': (1, 1),
            # `HttpBodyProbe` 本轮加了 `volley.v.getParams` 钩子 → 4 → 5。
            # 加这条的原因：`__jsonBody` 全 APK 只有两处写入（`InputBase` 写死 "{}"、
            # `JsonInput` 只被 new 一次），绝大多数请求的 body 在 `getParams` 里。
            'http_body_probe': (5, 5),
            # `net_error_probe` 钩构造器，形参是混淆类 `ErrorCode`。
            #
            # 2026-10-26 变更：⑤ 原先遇到"某个形参静态不定"就**整条丢弃**（`ok=False; break`），
            # 于是这里一直是 `(0, 1)` —— 有钩子，但一个形参都没校验。
            # 改成用 `*` 通配占位后，**已知形参仍受检**（`(*Ljava/lang/String;)`），
            # 所以现在是 `(1, 1)`：这条钩子的签名真的被校验了。
            'net_error_probe': (1, 1),
            # LogSink 走 `for (m in listOf("v","d","i","w","e","wtf"))` + `Xp.hookAll`，
            # 而 ④ 的 LOOP_LIST_RE 会把这个循环展开成 6 个字面量方法名 ⇒ ⑤ 逐条看得到。
            # 2026-10-25 把 v/wtf 补进分级清单后，这里从 None 变成 (6,6)。
            'log_sink': (6, 6),
            # `bridge_action_log` 本轮加了第 4 个钩点 `DecodeHttpRequestWebAction.onAction`
            # （页面借宿主签名手代发请求）⇒ 3 → 4。
            # 写死这个数字是有意的：钩点数变化说明"这个功能观测的链路变了"，
            # 而那件事必须同时反映到 ACTIVITY.md §七 的前缀对照表里。
            'bridge_action_log': (4, 4),
        }
        # 这些功能**结构上**不可能有静态签名证据（循环变量 / 反射调用），
        # 断言它们恒为 None —— 哪天有人给它们写成字面量，这条会提醒去更新上面。
        # `web_request_log` 用 `XposedHelpers.findAndHookMethod(…)` 直接调（不经 Xp），
        # ④⑤ 都识别不到 ⇒ 恒为 None。
        blind_by_construction = ('web_request_log',)
        got = {f['id']: self.static.get(f['cls']) for f in self.fm.features()}
        for fid, expect in want.items():
            with self.subTest(feature=fid):
                self.assertEqual(got.get(fid), expect,
                                 f'{fid} 的钩子数应为 {expect}，实际 {got.get(fid)}')
        for fid in blind_by_construction:
            with self.subTest(feature=fid):
                self.assertIsNone(
                    got.get(fid),
                    f'{fid} 现在有静态签名证据了（{got.get(fid)}）—— 说明它的钩法从'
                    f'循环/反射改成了字面量，请把它移到 want 里')


class VerificationDocMatchesItsGenerator(unittest.TestCase):
    """committed 的 `VERIFICATION.md` 必须等于生成器的输出（否则它又变成手写文档）。"""

    def test_committed_file_is_what_the_generator_produces(self):
        out = os.path.join(tempfile.mkdtemp(), 'VER.md')
        rc, log = py('feature_matrix.py', '--offline', '--out', out)
        self.assertEqual(rc, 0, log)
        want = read_text(out)
        got = read_text(VERIFICATION)
        if want != got:
            # 只报第一处差异，避免几万字表格刷屏
            wl, gl = want.splitlines(), got.splitlines()
            diff = next(((i, a, b) for i, (a, b) in enumerate(zip(wl, gl)) if a != b), None)
            if diff:
                i, a, b = diff
                self.fail(f'VERIFICATION.md 与生成器输出不一致（第 {i + 1} 行）\n'
                          f'  生成器: {a[:160]}\n  文件  : {b[:160]}')
            self.fail(f'VERIFICATION.md 与生成器输出行数不同：'
                      f'{len(wl)} vs {len(gl)}')


class RoundCitationPicksTheBuildRound(unittest.TestCase):
    """`VERIFICATION.md` 的「依据」列必须引用**建这个功能的那一轮**，不是最近提到它的那一轮。

    ## 抓到的真问题（2026-10-26 第 36 轮）

    旧实现取 `subject[-1]` = "最后一个主题命中的轮次"。关键词是**子串**匹配，
    所以后来一轮只要主题里碰巧出现同一个词，就会把真正的实测轮次顶掉：

    | 功能 | 旧引用 | 那一轮实际在讲 | 真正建功能的是 |
    |---|---|---|---|
    | `skip_onboarding` | R501 | 「把"七步的**可跳过性**"统计出来」（方法论） | R11「模块新功能 —— 跳过首次启动引导（含对照验收）」 |
    | `pk_assist` | R28 | 「接口探测 —— 候选来自 A**PK** 字符串表」 | R3「PK 自动作答实机复核」 |
    | `web_request_log` | R134 | 「页面地图补上"页面自有请求"」 | R119「给模块加第 19 个功能」 |

    「依据」列是读者判断"这个功能被证明到什么程度"的唯一入口。
    把它指向一轮**方法论讨论**，等于给一个从没做过实验的功能背书。

    两条修法各自钉住：
      1. `_rank()`：优先"建功能"措辞的轮次，其次取**最早**一轮（建功能总在引用之前）。
      2. `match_keyword()`：ASCII 关键词按词边界 + 大小写匹配，`APK` 不再命中 `PK`。
    """

    def test_ascii_keyword_does_not_match_inside_a_longer_word(self):
        """`PK` 不许命中 `APK` —— 这是那个假阳性的最小复现。"""
        import feature_matrix as fm
        self.assertFalse(fm.match_keyword('PK', '接口探测 —— 候选来自 APK 字符串表'))
        self.assertTrue(fm.match_keyword('PK', 'PK 自动作答实机复核'))

    def test_ascii_keyword_is_case_sensitive(self):
        import feature_matrix as fm
        self.assertFalse(fm.match_keyword('PK', 'pk 自动作答'),
                         '小写 pk 不该匹配大写 PK')
        self.assertTrue(fm.match_keyword('WEBREQ', '记录 WEBREQ 行'))

    def test_cjk_keyword_still_substring(self):
        """中文没有词边界，只能保留子串匹配 —— 这条钉住"别把中文也改坏"。"""
        import feature_matrix as fm
        self.assertTrue(fm.match_keyword('跳过', '模块新功能 —— 跳过首次启动引导'))

    def test_citation_is_the_build_round_not_the_latest_mention(self):
        """真文件里这三条的「依据」必须指向建功能的那一轮。"""
        text = read_text(VERIFICATION)
        want = {
            'skip_onboarding': 'R11',
            'pk_assist': 'R3',
            'web_request_log': 'R119',
        }
        for fid, rid in want.items():
            row = next((ln for ln in text.splitlines()
                        if ln.startswith(f'| `{fid}` |')), None)
            self.assertIsNotNone(row, f'VERIFICATION.md 缺 `{fid}` 行')
            self.assertIn(f'{rid} 以它为主题', row,
                          f'`{fid}` 的依据应指向 {rid}（建功能那一轮），实际：{row[:160]}')

    def test_pk_assist_is_not_credited_to_the_apk_string_table_round(self):
        """反向：R28 是"接口探测"，绝不能成为 `pk_assist` 的依据。"""
        text = read_text(VERIFICATION)
        row = next(ln for ln in text.splitlines() if ln.startswith('| `pk_assist` |'))
        self.assertNotIn('R28 以它为主题', row)


class StrongZeroIsExplainedNotSilent(unittest.TestCase):
    """`等级 强 + 记录数 0` 这种行必须在文档里被**解释**，否则一定被误读。

    两列回答不同问题：
      * `强`   = ROADMAP 里有一轮以它为主题、且留了证据文件（**历史做过实验**）
      * `0` 条 = 这 5 份冻结抓取里没有它写的行（**本批样本没覆盖**）

    不解释就会出现两种相反的错读：
      * "强 ⇒ 已验证" —— 把静态/历史结论当成运行时结论；
      * "0 条 ⇒ 功能坏了" —— 把样本年龄当成失效。

    这两种都在本仓库历史上写出过。所以这里钉两件事：解释段落存在，且
    **真机列不许有一行不是「未验证」**（离线模式下没有任何功能真的上过设备）。
    """

    def test_explanation_section_exists_when_there_are_strong_zero_rows(self):
        text = read_text(VERIFICATION)
        rows = [ln for ln in text.splitlines() if ln.startswith('| `')]
        strong_zero = [r for r in rows
                       if '**强**' in r and re.split(r'\|', r)[6].strip() == '0']
        if not strong_zero:
            self.skipTest('当前没有 强+0 的行')
        self.assertIn('为什么有"等级 `强`、记录数 `0`"的行', text,
                      'VERIFICATION.md 缺「强 + 0」解释段 ⇒ 读者会把历史实验读成已验证')

    def test_explanation_states_no_row_is_device_verified(self):
        text = read_text(VERIFICATION)
        if '为什么有"等级 `强`、记录数 `0`"的行' not in text:
            self.skipTest('没有该段')
        self.assertIn('它不表示"已在真机上验证通过"', text)

    def test_every_real_device_cell_is_unverified_in_offline_mode(self):
        """离线生成的矩阵里，`真机` 列**每一行**都必须是 `未验证`。

        一旦有人手改成 `已验证`，这条会红 —— 这是"不许把静态结论写成已验证"的机器守卫。
        """
        text = read_text(VERIFICATION)
        rows = [ln for ln in text.splitlines() if ln.startswith('| `')]
        self.assertTrue(rows, 'VERIFICATION.md 没有数据行')
        bad = []
        for r in rows:
            cells = [c.strip() for c in r.strip().strip('|').split('|')]
            if len(cells) > 9 and cells[8] != '未验证':
                bad.append((cells[0], cells[8]))
        self.assertEqual(bad, [],
                         f'这些行的 `真机` 列不是「未验证」：{bad} —— '
                         f'没有设备跑过的功能不许标成已验证')


if __name__ == '__main__':
    unittest.main()
