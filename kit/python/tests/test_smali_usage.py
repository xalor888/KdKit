#!/usr/bin/env python3
"""
Offline tests for `kit/scripts/smali_usage.py` — the "will this hook ever run?" judge.

Why this file exists: this project's worst failure mode is a hook that installs
successfully (`Xp.hook` returns true, the boot log says `ok`) and then never fires,
because the target is dead code. `check_hook_targets.py` cannot see that (the class and
method exist) and neither can `check_hook_signatures.py` (the signature matches).
`smali_usage` is the layer that answers it, so it needs its own tests.

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, '..', '..', 'scripts'))
sys.path.insert(0, SCRIPTS)

import smali_usage as su  # noqa: E402
from hook_vocab import read_text  # noqa: E402


def write_smali(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)
    return path


def cls_smali(desc, extra='', super_desc='Ljava/lang/Object;'):
    return ('.class public %s\n.super %s\n\n%s\n' % (desc, super_desc, extra))


class Verdicts(unittest.TestCase):
    """One fixture per verdict — the four layers plus the two "no evidence" states."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='kdkit_smali_')

        # ① LIVE: 别的类 invoke-virtual 它
        write_smali(cls.tmp, 'smali/a/Live.smali', cls_smali('La/Live;',
                   '.method public run()V\n    return-void\n.end method'))
        write_smali(cls.tmp, 'smali/a/Caller.smali', cls_smali('La/Caller;',
                   '.method public go()V\n'
                   '    invoke-virtual {v0}, La/Live;->run()V\n'
                   '    return-void\n.end method'))

        # ② SELF-CALLED: 只有本类别的方法在调它
        write_smali(cls.tmp, 'smali/a/Selfish.smali', cls_smali('La/Selfish;',
                   '.method public inner()V\n    return-void\n.end method\n\n'
                   '.method public outer()V\n'
                   '    invoke-virtual {v0}, La/Selfish;->inner()V\n'
                   '    return-void\n.end method'))

        # ③ DEAD: 全 APK 零引用（BrushMaskView 那种）
        write_smali(cls.tmp, 'smali/a/Dead.smali', cls_smali('La/Dead;',
                   '.method public onDraw()V\n    return-void\n.end method'))

        # ④ TYPE-ONLY: 只作为类型被引用（Gson/DTO 形态）
        write_smali(cls.tmp, 'smali/a/Model.smali', cls_smali('La/Model;',
                   '.method public get()V\n    return-void\n.end method'))
        write_smali(cls.tmp, 'smali/a/Holder.smali', cls_smali('La/Holder;',
                   '.field public m:La/Model;\n'
                   '.method public keep()V\n    return-void\n.end method'))

        cls.rows = {r.target: r for r in su.analyse(cls.tmp, [
            ('a.Live', 'run'), ('a.Selfish', 'inner'), ('a.Dead', 'onDraw'),
            ('a.Model', 'get'), ('a.Nonexistent', 'x'),
        ])}

    def test_live(self):
        r = self.rows['a.Live']
        self.assertEqual(r.verdict, su.V_USED)
        self.assertEqual(r.direct, 1)
        # samples 的格式是 "<文件名>:<行号>"，用文件名判即可（不绑定完整路径）
        self.assertTrue(any('Caller' in x for x in r.samples), r.samples)

    def test_self_called(self):
        r = self.rows['a.Selfish']
        self.assertIn(r.verdict, (su.V_USED, su.V_SELF))
        self.assertEqual(r.direct, 0)
        self.assertGreater(r.self_calls, 0)

    def test_dead(self):
        """零引用的类必须判 DEAD —— 这是整个门禁存在的理由。"""
        r = self.rows['a.Dead']
        self.assertEqual(r.verdict, su.V_DEAD)
        self.assertEqual(r.direct, 0)
        self.assertEqual(r.class_refs, 0)

    def test_type_only_is_not_dead(self):
        """只被当类型用（DTO/Gson）不等于死代码 —— 误判 DEAD 会让人删掉活功能。"""
        r = self.rows['a.Model']
        self.assertEqual(r.verdict, su.V_TYPE)
        self.assertGreater(r.class_refs, 0)

    def test_missing_is_not_evidence(self):
        """类不在解码目录 ⇒ MISSING，**不能**算成"有使用证据"（曾有过这个 bug）。"""
        r = self.rows['a.Nonexistent']
        self.assertEqual(r.verdict, su.V_MISSING)


class ReadBudgetIsNotEvidence(unittest.TestCase):
    """读预算截断**不得**改变结论 —— 这是 2026-10-26 门禁 ④ 抖动的根因回归测试。

    实测症状：同一份静态输入，`check_hook_targets.py` 的 resolved 数在
    96 / 107 / 112 / 116 / 118 之间跳，`DEAD-TARGET` 与 `OK` 来回翻转。

    两个原因叠在一起，缺一个都不会出这个症状：
      1. `grep_files()` 用 `rg -l`，多线程遍历 ⇒ **返回顺序逐次不同**；
      2. 读预算是逐个累加的，顺序一变，被挡在门外的文件就变 ⇒ 证据集变了。

    修法：① 排序，让同样输入必得同样文件集；② 万一仍被截断，
    "零引用"是**没看完**而非**不存在** ⇒ 降级 `INCOMPLETE`，绝不判 `DEAD`。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='kdkit_budget_')
        # 三个目标类各自一个文件，再加 4 个互不相干的引用者 —— 命中文件数远多于
        # 小预算能读完的数量，于是"谁被读到"完全取决于遍历顺序。
        for i, (name, desc) in enumerate([('One', 'La/One;'), ('Two', 'La/Two;'),
                                          ('Three', 'La/Three;')]):
            write_smali(self.tmp, f'smali/a/{name}.smali', cls_smali(desc))
            for j in range(4):
                write_smali(self.tmp, f'smali/p{i}_{j}/Ref{j}.smali', cls_smali(
                    f'Lp{i}_{j}/Ref{j};',
                    f'.method public go()V\n'
                    f'    new-instance v0, {desc}\n'
                    f'    return-void\n.end method'))
        # 一个真正零引用的类：任何顺序下它都不在任何**别的**文件里出现。
        write_smali(self.tmp, 'smali/dead/Orphan.smali', cls_smali('Ldead/Orphan;'))

    def test_same_verdicts_regardless_of_grep_order(self):
        """把命中文件顺序反过来，每个目标的结论必须逐字相同。"""
        targets = [('a.One', None), ('a.Two', None), ('a.Three', None), ('dead.Orphan', None)]
        fwd = su.analyse(self.tmp, targets)

        real_grep = su.grep_files
        # 每次调用都反过来 —— 模拟 `rg -l` 的遍历顺序抖动
        su.grep_files = lambda root, pat: list(reversed(sorted(real_grep(root, pat))))
        try:
            rev = su.analyse(self.tmp, targets)
        finally:
            su.grep_files = real_grep

        self.assertEqual([r.verdict for r in fwd], [r.verdict for r in rev],
                         '命中文件顺序改变后结论变了 ⇒ 判定依赖遍历顺序，不可复现')

    def test_truncated_evidence_is_incomplete_not_dead(self):
        """预算小到只够读一个文件时，被截断的目标必须是 INCOMPLETE，不是 DEAD。"""
        rows = su.analyse(self.tmp, [('a.One', None), ('a.Two', None)],
                          read_budget=1)
        for r in rows:
            self.assertEqual(r.verdict, su.V_INCOMPLETE,
                             f'{r.target} 在证据被截断时给出了 {r.verdict}，'
                             '把"没看完"当成了"不存在"')

    def test_incomplete_is_not_a_failure(self):
        """`INCOMPLETE` 不能计成 DEAD：否则一次内存抖动会让门禁红，教人忽略门禁。"""
        rows = su.analyse(self.tmp, [('a.One', None)], read_budget=1)
        self.assertTrue(rows[0].ok, 'INCOMPLETE 被当成失败结论')
        self.assertIn('读预算', rows[0].note)

    def test_generous_budget_proves_death(self):
        """预算足够时，真死代码必须坚定判 DEAD —— 降级逻辑不能把门禁变成永远不判死。"""
        rows = su.analyse(self.tmp, [('dead.Orphan', None)], read_budget=64 * 1024 * 1024)
        self.assertEqual(rows[0].verdict, su.V_DEAD)
        self.assertEqual(rows[0].class_refs, 0)


class Platform(unittest.TestCase):
    def test_platform_class_is_skipped(self):
        """android.* 不在解码目录是正常的，不能报 DEAD。"""
        tmp = tempfile.mkdtemp(prefix='kdkit_plat_')
        write_smali(tmp, 'smali/a/X.smali', cls_smali('La/X;'))
        rows = su.analyse(tmp, [('android.os.Debug', 'isDebuggerConnected')])
        self.assertEqual(rows[0].verdict, su.V_PLATFORM)


class RealApk(unittest.TestCase):
    """对真实解码结果跑一次 —— 只有 work/apktool_out 存在时才执行。"""

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))

    def setUp(self):
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在（未解码 APK）')

    def test_brush_mask_view_is_dead(self):
        """加固壳里的残留 View：侦察结论"钩它无效"，这里把它变成可复跑的断言。"""
        rows = su.analyse(self.ROOT, [('com.byazt.nd.BrushMaskView', 'onDraw')])
        self.assertEqual(rows[0].verdict, su.V_DEAD,
                         'BrushMaskView.onDraw 应当仍判 DEAD；若变成别的结论，说明侦察结论要更新')

    def test_vip_getter_is_live(self):
        """aj.a.p()（7.7.2 里叫 bk.a）有 17 处直接调用（含 VipCurrentStatusWebAction）。"""
        rows = su.analyse(self.ROOT, [('aj.a', 'p')])
        self.assertEqual(rows[0].verdict, su.V_USED)
        self.assertGreater(rows[0].direct, 0)




class SignatureCrossCheck(unittest.TestCase):
    """钩子签名与 APK 真实签名的一致性 —— 针对"代码用反射推导形参"的那类钩子。

    背景：`WatermarkOff` 钩 `ov.l` 的 14 参构造器，但代码是用 `cls.declaredConstructors`
    逐个比对参数表找出来的（这样宿主换版增删参数会**主动不钩**而不是钩错重载）。
    代价是静态门禁只能标 `UNKNOWN(signature not statically resolvable)` —— 没人校验
    那份硬编码的期望签名是否与 APK 一致。这个测试补上。
    """

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))
    MODULE = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'module', 'app', 'src', 'main',
                                         'java', 'dev', 'xalor', 'kdkit'))

    def setUp(self):
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在')

    def _resolve_smali(self, smali_rel):
        """把 `smali_classesN/a/b.smali` 解析成真实文件，**跨 dex 目录**找。

        为什么不能直接 `os.path.join(ROOT, smali_rel)`：R8 重排会把类在
        `smali/` 与 `smali_classesN/` 之间搬来搬去（`cu/l` → `ov/l` 就换过），
        写死目录的后果不是报错而是 `skipTest` —— 一个测试静默消失，比红还糟。
        目录存在而类找不到 ⇒ 直接 fail（那是漂移）。
        """
        # 只有当第一段**看起来像 dex 目录**时才剥掉它；`ov/l.smali` 的第一段是包名。
        head, _, tail = smali_rel.partition('/')
        pkg_rel = tail if (tail and (head == 'smali' or head.startswith('smali_classes'))) else smali_rel
        for d in self._smali_dirs():
            cand = os.path.join(self.ROOT, d, pkg_rel)
            if os.path.isfile(cand):
                return cand
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在（未解码 APK）')
        self.fail(f'解码目录存在，但在任何 smali 目录里都找不到 `{pkg_rel}` —— '
                  f'类名漂移，不是"没解码"。检查 kit/python/tests/test_smali_usage.py 里的路径。')

    def _smali_dirs(self):
        import re as _re
        return sorted(d for d in os.listdir(self.ROOT)
                      if d == 'smali' or _re.fullmatch(r'smali_classes\d+', d))

    def _ctor_params(self, smali_rel, arity):
        path = self._resolve_smali(smali_rel)
        text = read_text(path)
        best = None
        for m in re.finditer(r'^\.method public constructor <init>\(([^)]*)\)V', text, re.M):
            desc = m.group(1)
            params, i = [], 0
            while i < len(desc):
                if desc[i] == 'L':
                    j = desc.index(';', i)
                    params.append('L'); i = j + 1
                elif desc[i] == '[':
                    params.append('['); i += 1
                else:
                    params.append(desc[i]); i += 1
            if len(params) == arity:
                best = params
        return best

    def test_watermark_ctor_matches_apk(self):
        """`ov.l` 的 14 参构造器：APK 的 I/Z/F 顺序必须与代码里硬编码的期望一致。

        如果不一致，`ctorTypes()` 会找不到构造器 ⇒ 功能静默不装（钩子数 0），
        而表面上"功能已启用"。
        """
        apk = self._ctor_params('ov/l.smali', 14)   # 7.7.2 里叫 cu/l
        self.assertIsNotNone(apk, 'ov.l 应有 14 参构造器')

        src = read_text(os.path.join(self.MODULE, 'features', 'host', 'WatermarkOff.kt'))
        block = src[src.index('val wanted'):src.index(']', src.index('String::class.java', src.index('val wanted')))]
        tokens = re.findall(r'(String|Int|Float|Boolean)::class\.java(?:PrimitiveType)?', block)
        table = {'String': 'L', 'Int': 'I', 'Float': 'F', 'Boolean': 'Z'}
        want = [table[t] for t in tokens]

        self.assertEqual(len(want), 14, f'代码里期望 14 个参数，实际 {len(want)}: {tokens}')
        self.assertEqual(want, apk,
                         '硬编码的期望签名与 APK 不一致 ⇒ ctorTypes() 会找不到构造器、功能静默不装')




class DynamicParamCrossCheck(unittest.TestCase):
    """代码用 `clazzOrNull(...)` 动态取形参类型时，静态门禁只能标 UNKNOWN ——
    这里把"那份期望类名是否与 APK 一致"变成可复跑的断言。

    这类钩子的失效方式最隐蔽：类名写错（或宿主换版改了混淆名）时
    `clazzOrNull` 返回 null ⇒ 钩子根本不装 ⇒ 日志里只是少了几个 hook，
    功能表面上仍然"已启用"。
    """

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))
    MODULE = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'module', 'app', 'src', 'main',
                                         'java', 'dev', 'xalor', 'kdkit'))

    def setUp(self):
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在')

    def _find(self, dotted):
        for d in sorted(os.listdir(self.ROOT)):
            if not (d == 'smali' or re.fullmatch(r'smali_classes\d+', d)):
                continue
            p = os.path.join(self.ROOT, d, dotted.replace('.', os.sep) + '.smali')
            if os.path.exists(p):
                return p
        return None

    def _arg_const(self):
        """读出 `BlockAdSdk` 里的 `ARG` 常量实际值（而不是在测试里硬写 "xc.a"）。

        关键：测试必须读**代码里的值**再和 APK 比对。只断言 "xc.a 存在于 APK" 是
        测不出的 —— 代码里写成别的东西，测试照样绿。
        """
        src = read_text(os.path.join(self.MODULE, 'features', 'host', 'HostFeatures.kt'))
        m = re.search(r'private const val ARG\s*=\s*"([^"]+)"', src)
        self.assertIsNotNone(m, 'BlockAdSdk 应有 ARG 常量')
        return m.group(1)

    def test_arg_class_exists_in_apk(self):
        """`BlockAdSdk` 的 ARG 指向的类必须在 APK 里。类不在 ⇒ 4 个钩子全因 clazzOrNull=null 跳过。"""
        arg = self._arg_const()
        self.assertIsNotNone(self._find(arg),
                             f'ARG="{arg}" 在 APK 里不存在：BlockAdSdk 的 4 个钩子会全部跳过')

    def test_sdk_init_signatures_take_the_arg_class(self):
        """四个 init 的真实形参必须就是代码 ARG 指向的那个类。"""
        arg = self._arg_const()
        expected = '(L' + arg.replace('.', '/') + ';)V'
        for cls, meth in (
            ('com.fastad.csj.FastAdCsjManager', 'initCsjSDK'),
            ('com.fastad.ylh.FastAdYlhManager', 'initYlhSDK'),
            ('com.fastad.ks.FastAdKsManager', 'initKsSdk'),
            ('com.fastad.baidu.FastAdBDManager', 'initBaiduSDK'),
        ):
            path = self._find(cls)
            self.assertIsNotNone(path, f'{cls} 不存在')
            text = read_text(path)
            hits = re.findall(r'^\.method public static final ' + meth + r'(\([^)]*\)V)', text, re.M)
            self.assertIn(expected, hits,
                          f'{cls}.{meth} 的真实签名 {hits} 里没有 {expected} ⇒ 代码传的 xc.a 对不上')

    def test_watermark_ctor_count_is_unambiguous(self):
        """`ov.l` 有 1 参和 14 参两个构造器；代码的筛选只认 14 参，不能误钩 1 参那个。"""
        path = self._find('ov.l')
        self.assertIsNotNone(path)
        text = read_text(path)
        ctors = re.findall(r'^\.method public constructor <init>\(([^)]*)\)V', text, re.M)
        # 参数个数 = 描述符里的类型项数（L...; 算一项）
        def arity(desc):
            n, i = 0, 0
            while i < len(desc):
                if desc[i] == 'L':
                    i = desc.index(';', i) + 1
                else:
                    i += 1
                n += 1
            return n
        arities = sorted(arity(c) for c in ctors)
        self.assertIn(1, arities, f'应有 1 参构造器，实际参数个数 {arities}')
        self.assertIn(14, arities, f'应有 14 参构造器，实际参数个数 {arities}')
        self.assertGreaterEqual(len(ctors), 2, f'构造器应不止一个，实际 {ctors}')



class AllRuntimeResolvedClassesExist(unittest.TestCase):
    """**通用**检查：每一个 `Xp.clazzOrNull("X")` 里的字面量类名都必须在 APK 里存在。

    为什么要这一条：这些是"运行时才解析"的类名，静态签名门禁看不到它们，
    写错（或宿主换版改了混淆名）时 `clazzOrNull` 返回 null ⇒ 钩子不装 ⇒
    功能表面上"已启用"、日志里只是少几个 hook。这是最静默的失效形态。

    实测过的真实案例：`ARG = "xc.a"` 是 4 个广告 SDK init 钩子的共同形参类型，
    写成别的值会让这 4 个钩子**全部**跳过。
    """

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))
    MODULE = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'module', 'app', 'src', 'main',
                                         'java', 'dev', 'xalor', 'kdkit'))
    # 平台类不在解码目录里，跳过
    PLATFORM = ('android.', 'androidx.', 'java.', 'javax.', 'kotlin.', 'dalvik.')

    def setUp(self):
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在')

    def _available(self):
        out = set()
        for d in os.listdir(self.ROOT):
            if not (d == 'smali' or re.fullmatch(r'smali_classes\d+', d)):
                continue
            for base, _x, files in os.walk(os.path.join(self.ROOT, d)):
                for f in files:
                    if f.endswith('.smali'):
                        rel = os.path.relpath(os.path.join(base, f), os.path.join(self.ROOT, d))
                        out.add(rel[:-len('.smali')].replace(os.sep, '.'))
        return out

    def test_every_clazz_or_null_literal_exists(self):
        pkgs = {}
        for f in Path(self.MODULE).rglob('*.kt'):
            t = f.read_text(encoding='utf-8')
            m = re.search(r'const val PKG\s*=\s*"([^"]+)"', t)
            if m:
                pkgs[f.name] = m.group(1)
            m = re.search(r'const val MODEL\s*=\s*"([^"]+)"', t)
            if m:
                pkgs[f.name] = m.group(1)

        available = self._available()
        bad = []
        for f in Path(self.MODULE).rglob('*.kt'):
            t = f.read_text(encoding='utf-8')
            consts = dict(re.findall(r'const val (\w+)\s*=\s*"([^"]*)"', t))
            # 两种实参形态都要收：`clazzOrNull("a.b.C")` 与 `clazzOrNull(CONST_NAME)`。
            # 后者此前**整条逃过检查**：正则只认引号，于是
            #     private const val LIST_ITEM = "…Popwindow\$ListItem"
            #     Xp.clazzOrNull(LIST_ITEM)
            # 里的类名从没被验证过。把常量值改错也照样绿 —— 第 21 轮反向验证时发现。
            for m in re.finditer(r'clazzOrNull\(\s*(?:"([^"]+)"|(\w+))\s*\)', t):
                raw = m.group(1) or m.group(2)
                # 跳过 KDoc/行注释里的示例（否则文档里写 clazzOrNull("…") 会被当成真实调用）
                line_start = t.rfind('\n', 0, m.start()) + 1
                line_text = t[line_start:t.find('\n', m.start())]
                if line_text.lstrip().startswith(('*', '//', '/*')):
                    continue
                if '…' in raw or raw.strip() == '':
                    continue
                # 裸标识符 ⇒ 直接换成它声明的值（源码里就是字面量，与 Kotlin 的
                # `const val` 语义一致：编译期已内联，不存在运行时才求值的情况）。
                name = consts.get(raw, raw) if m.group(1) is None else raw
                for _ in range(3):
                    name = re.sub(r'\$\{?(\w+)\}?', lambda x: consts.get(x.group(1), x.group(0)), name)
                # 先按 Kotlin 规则反转义 `\$`（字符串里写 `Popwindow\$ListItem` 表示
                # 字面 `Popwindow$ListItem`）。**反转义之后**再判断是否还有未解析的模板。
                #
                # 判定不能用"有 $ 就跳过"：那会放过**每一个内部类**（`A$B` 形态，
                # `Popwindow$ListItem` / `HybridWebView$ReturnCallback` 都在内）——
                # 旧代码就是这样，于是这些运行时类名从没被校验过（2026-10-25 反向验证发现）。
                #
                # 也不算"$ident 不在 consts 里就是模板"：内部类的 `ListItem` 同样不在
                # consts 里，会被误判成模板再跳过 —— 第一次修就是这样，仍然抓不到 typo。
                #
                # 可靠判据：模板只可能来自**本文件声明的常量**。所以先把所有已知常量名
                # 替换掉；若替换后**仍有** `$ident`，且该 ident 确实是某个 const 的**名字**
                # （说明它没被替换成功），才算未解析。其余含 `$` 的一律当字面内部类去查表。
                name = name.replace('\\$', '$')
                if '${' in name:
                    continue
                leftover = set(re.findall(r'\$(\w+)', name))
                if leftover & set(consts):
                    continue
                if name.startswith(self.PLATFORM):
                    continue
                if name not in available:
                    line = t[:m.start()].count('\n') + 1
                    bad.append(f'{f.name}:{line}  clazzOrNull({raw!r}) -> "{name}" 不在 APK 里')
        self.assertEqual(bad, [], '这些运行时解析的类名在 APK 里不存在，对应钩子会静默不装:\n  '
                         + '\n  '.join(bad))

class TargetCollection(unittest.TestCase):
    """`check_hook_targets.collect_targets` 必须找到**每一个**声明的钩子目标。

    这一层此前是隐形漏洞（2026-10-25 第 3 轮发现）：模块里 10 个目标从未被任何门禁校验过。
    两个独立成因，都必须有测试锁住：

      1. `Xp.hookCtor(...)` 根本没被识别 —— 它没有方法名字面量，`CALL_RE` 匹配不到。
         `watermark_off` 的**主钩点**（`ov.l` 14 参构造器）因此完全没进过 ④⑤⑥。
      2. 收集器逐行扫。真实调用常常跨行：

             val ok = Xp.hookCtor(
                 "ov.l",
                 …

        第一行只有 `Xp.hookCtor(`，类名在下一行 —— 即便榜 1 修了，逐行扫仍然漏。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, SCRIPTS)
        import check_hook_targets
        cls.cht = check_hook_targets
        # 绝对路径：测试可能从任意 cwd 跑（门禁从 module/ 调用 verify.sh），
        # 相对路径在那种场景下会静默指向错误目录、或者 FileNotFound。
        cls.MODULE = str(Path(HERE).resolve().parents[2]
                         / 'module' / 'app' / 'src' / 'main' / 'java' / 'dev' / 'xalor' / 'kdkit')

    def test_ctor_hook_is_collected(self):
        """`Xp.hookCtor("a.b.C", …)` -> `('a.b.C', '<init>')`。"""
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'F.kt').write_text(
                'object F {\n'
                '    fun install() {\n'
                '        Xp.hookCtor("aa.bb.Ctor", String::class.java, gate = "x")\n'
                '    }\n'
                '}\n', encoding='utf-8')
            got = {(c, m) for c, m, _w in self.cht.collect_targets(d)}
        self.assertIn(('aa.bb.Ctor', '<init>'), got)

    def test_multiline_call_is_collected(self):
        """跨行调用必须被收集 —— 逐行扫会漏掉类名在下一行的那种写法。"""
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'F.kt').write_text(
                'object F {\n'
                '    fun install() {\n'
                '        val ok = Xp.hookCtor(\n'
                '            "cc.dd.Multi",\n'
                '            *types(cls),\n'
                '            gate = id,\n'
                '        )\n'
                '        Xp.hook(\n'
                '            "cc.dd.Multi",\n'
                '            "go",\n'
                '            gate = id)\n'
                '    }\n'
                '}\n', encoding='utf-8')
            got = {(c, m) for c, m, _w in self.cht.collect_targets(d)}
        self.assertIn(('cc.dd.Multi', '<init>'), got, '跨行 hookCtor 漏了')
        self.assertIn(('cc.dd.Multi', 'go'), got, '跨行 hook 漏了')

    def test_real_module_collects_ctor_targets(self):
        """真实模块里这两个构造器钩必须在清单里，否则 watermark/RC4 的主钩点无人校验。"""
        got = {(c, m) for c, m, _w in self.cht.collect_targets(self.MODULE)}
        for want in (('ov.l', '<init>'), ('com.baidu.android.common.security.RC4', '<init>')):
            with self.subTest(target=want):
                self.assertIn(want, got, f'{want} 没被收集 ⇒ 这个钩子目标永远不进 ④⑤⑥')

    def test_real_module_target_count_floor(self):
        """目标总数的下限 —— 用来发现"某个写法突然整体不被识别"。

        48 是加 hookCtor 之前的真实值；跨行修复后是 60。这里只断言"不少于 60"，
        因为新增目标应该让数字变大，而**变小**正是漏掉一整类写法的信号。
        """
        got = self.cht.collect_targets(self.MODULE)
        self.assertGreaterEqual(len(got), 60,
                                f'只收集到 {len(got)} 个目标；此前实测 60 —— '
                                f'少说明有调用形态没被识别')




class WrapperHookSignatures(unittest.TestCase):
    """`SignObserver` 用本地包装器 `hook("类","方法")` 挂钩，形参由包装器内部决定 ——
    签名门禁只能标 `OK(hookAll)`（无需判定形参）。

    但"无需判定形参"不等于"没有该验的东西"。这 8 个目标的**真实签名**值得钉住：

    * 宿主换版把它们改成不同形参 ⇒ 回调里的 `p.args.firstOrNull()` 拿到的东西变了，
      记录出来的 `NET DECRYPT in` 会变成别的对象，**日志仍然有、内容已经错了**；
    * 某个方法消失 ⇒ 钩子静默不装（`HookAudit` 只少一条 ok）。

    签名门禁看不见这两种情况（它按"包装器内部决定"跳过比对），所以单独立这条。
    """

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))

    # (类, 方法) -> (参数描述符, 返回描述符)。2026-10-25 从 APK 读出。
    EXPECTED = {
        ('com.baidu.homework.common.net.Net', 'appendSign'):
            ('Lcom/baidu/homework/common/net/model/v1/common/InputBase;', 'Ljava/lang/String;'),
        ('com.zuoyebang.baseutil.a', 'b'): ('Ljava/lang/String;', 'Ljava/lang/String;'),
        ('com.zuoyebang.baseutil.a', 'd'): ('Ljava/util/List;', 'Ljava/lang/String;'),
        # 7.9.0：RC4Helper 从 yl.f 搬到 vm.g，且方法名整体后移一位（新插入了一个方法）。
        ('vm.g', 'h'): ('Ljava/lang/String;', 'Ljava/lang/String;'),
        ('vm.g', 'i'): ('Ljava/lang/String;', 'Ljava/lang/String;'),
        # z()V —— 无参无返回。SignObserver 把它当"加解密原语"记录 in/out，
        # 但 in 恒为 null、out 恒为 null；本轮核对确认就是这么写的（见下方单独断言）。
        ('vm.g', 'z'): ('', 'V'),
        ('vm.g', 'k'): ('Ljava/lang/Object;', 'Ljava/lang/Object;'),
        ('vm.g', 't'): ('Ljava/lang/Object;Z', 'Ljava/lang/Object;'),
    }

    def setUp(self):
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在')

    def _sig(self, dotted, meth):
        for d in os.listdir(self.ROOT):
            if not (d == 'smali' or re.fullmatch(r'smali_classes\d+', d)):
                continue
            path = os.path.join(self.ROOT, d, dotted.replace('.', os.sep) + '.smali')
            if not os.path.exists(path):
                continue
            text = read_text(path)
            hits = re.findall(
                r'^\.method [\w\s-]*?' + re.escape(meth) + r'\(([^)]*)\)([^\s]+)', text, re.M)
            return hits
        return None

    def test_real_signatures_match(self):
        bad = []
        for (cls, meth), (want_p, want_r) in sorted(self.EXPECTED.items()):
            got = self._sig(cls, meth)
            if got is None:
                bad.append(f'{cls}.{meth}: 类不存在')
            elif not got:
                bad.append(f'{cls}.{meth}: 方法不存在')
            elif (want_p, want_r) not in got:
                bad.append(f'{cls}.{meth}: 期望 ({want_p}){want_r}，实际 {got}')
        self.assertEqual(bad, [],
                         'SignObserver 的包装器钩子真实签名变了（日志内容会静默出错）：\n  '
                         + '\n  '.join(bad))

    def test_noarg_primitive_is_flagged(self):
        """`vm.g.z()`（7.7.2 里叫 `yl.f.y()`）无参 —— `SignObserver` 却按"有输入输出"记录它。

        这不是 bug（它就是调一次、看有没有异常），但值得显式记下来：
        如果哪天有人以为 `NET DECRYPT in` 对 y 有意义，这里会提醒他 in 恒为 null。
        """
        got = self._sig('vm.g', 'z')
        self.assertIsNotNone(got)
        self.assertIn(('', 'V'), got,
                      f'vm.g.z 的签名变了：{got}。若它开始带参数，SignObserver 的记录含义要重看')



class PopwinDispatchIsVoid(unittest.TestCase):
    """`PopwinGate` 的拦截依赖 `H(String,ListItem)V` 是 **void** 方法。

    为什么这条断言属于 Python 侧而不是 Kotlin 单测：

    * JVM 单测的 CWD 是 `module/app`，读不到仓库根的 `work/apktool_out`；
      在 Kotlin 里写"读 smali 文件"会静默 `return`（我第一版就是这样，删掉测试照样绿）。
    * 这里本来就在仓库根跑，且已有 smali 解析工具。

    契约内容：**void 方法的 before hook 里给 `result` 赋值会让原方法体被跳过**。
    若 `H` 变成有返回值的方法，`result = null` 会让调用方拿到 null —— 那是另一回事，
    拦截写法必须重新评估。同形先例（void + 同样写法，已在生产）：
    `MainAdvertiseImageView.show(...)V`、`lk.a.j(Activity)`。
    """

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))

    # 候选路径而不是单一写死的路径。
    #
    # **这一条曾经静默关掉 3 个测试**：`SMALI` 写的是 7.7.2 的 `ei/y.smali`，
    # 7.9.0 的 R8 重排把类挪到 `hh/y.smali`，于是 `os.path.isfile` 为假 ⇒
    # `skipTest('work/apktool_out 不存在')` —— 而那个目录**明明存在**。
    # 跳过理由写错了，导致"这个门禁已经不在跑了"这件事两年没人发现。
    #
    # 现在：路径候选 + **目录在而类不在 ⇒ 直接 fail**（那是漂移，不是"没解码"）。
    # 不要猜 `smali_classes5` —— 这个类实际落在**默认的 `smali/`** 里。
    # 用"所有 smali* 目录 × 已知类名"的组合，类换 dex 也不会失效。
    _SMALI_DIRS = ('smali', 'smali_classes5')
    _CLASS_PATHS = ('hh/y.smali', 'ei/y.smali')

    @property
    def SMALI_CANDIDATES(self):
        return [os.path.join(self.ROOT, d, c) for c in self._CLASS_PATHS for d in self._SMALI_DIRS]

    def _smali_path(self):
        for p in self.SMALI_CANDIDATES:
            if os.path.isfile(p):
                return p
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在（未解码 APK）—— 这是唯一合法的跳过理由')
        self.fail(
            '解码目录**存在**，但下面这些都不是文件 ⇒ 类名漂移，不是"没解码"：\n  '
            + '\n  '.join(os.path.relpath(p, self.ROOT) for p in self.SMALI_CANDIDATES)
            + '\n类名又挪了？更新候选并重新核对 PopwinGate 的钩点。',
        )

    def _decl(self):
        path = self._smali_path()
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if line.startswith('.method private H(Ljava/lang/String;'):
                    return line.strip()
        return None

    def test_dispatch_method_exists(self):
        self.assertIsNotNone(self._decl(), 'ei/y.smali 里找不到 H —— PopwinGate 的钩点可能变了')

    def test_dispatch_method_returns_void(self):
        decl = self._decl()
        self.assertTrue(
            decl.endswith(')V'),
            f'H 不再是 void，`p.result = null` 的语义不再是"跳过方法体"，'
            f'拦截写法必须重新评估：{decl}',
        )

    def test_the_eight_named_types_plus_two_prefix_types_exist(self):
        """`KNOWN_TYPES` 的 10 个字符串必须都在 `H` 的方法体里。

        2026-10-25 修正过：原列表只有 8 个，漏了 `winActivity` / `winBottom`
        （它们在 `sparse-switch` 之前，只数分支体会漏）。
        """
        with open(self._smali_path(), encoding='utf-8', errors='replace') as fh:
            text = fh.read()
        start = text.find('.method private H(Ljava/lang/String;')
        self.assertGreater(start, 0)
        end = text.find('.end method', start)
        body = text[start:end]
        for t in ('winActivity', 'winBottom', 'winUp', 'winAd', 'winImp', 'winVIPBottom',
                  'winBook', 'winFlow', 'winGradeSelect', 'winGradeUp'):
            self.assertIn(f'"{t}"', body, f'H 方法体里找不到类型 {t!r}')


class DeadUiDiscovery(unittest.TestCase):
    """`find_dead_ui_classes` —— 把 BrushMaskView 那类死代码**自动找出来**。

    为什么需要这一层：`analyse()` 判定很准，但它要求**先有人给出目标**。
    `BrushMaskView` 出事的真正原因不是判定错，是没人想到该把它列为目标 ——
    它看着像水印类，于是被钩了，然后永远不执行。这一层做反向枚举：
    扫出"类存在、零外部引用、没被布局引用、而且是 UI 子类"的类
    ⇒ 没有任何路径能实例化它 ⇒ 可证明的死代码。

    判据必须四条同时成立，缺一条就会把活代码报死：
    * 是 UI 子类（正常入口是 inflate / startActivity，不是 invoke）——
      DTO/回调类零引用可能是反射建的，不能一概而论；
    * 零**外部**引用（自己文件里的字段/方法声明不算）；
    * `res/` 布局里也没有它（自定义 View 通常靠布局全名引用）。
    """

    def test_finds_dead_view_and_ignores_live_one(self):
        """合成夹具：一个零引用的 View 必须被找出；一个被布局引用的**不能**。"""
        tmp = tempfile.mkdtemp(prefix='kdkit_deadui_')
        # 死：View 子类，全 APK 没人提它
        write_smali(tmp, 'smali/p/DeadView.smali',
                    cls_smali('Lp/DeadView;', '.method public onDraw()V\n return-void\n.end method',
                              super_desc='Landroid/view/View;'))
        # 活：同样是 View 子类，但布局里有它
        write_smali(tmp, 'smali/p/LiveView.smali',
                    cls_smali('Lp/LiveView;', '.method public onDraw()V\n return-void\n.end method',
                              super_desc='Landroid/view/View;'))
        os.makedirs(os.path.join(tmp, 'res', 'layout'))
        with open(os.path.join(tmp, 'res', 'layout', 'main.xml'), 'w', encoding='utf-8') as fh:
            fh.write('<p.LiveView android:id="@+id/x"/>\n')
        # 活：非 UI 类零引用 —— 不报（可能是反射/DTO）
        write_smali(tmp, 'smali/p/Plain.smali',
                    cls_smali('Lp/Plain;', '.method public get()V\n return-void\n.end method'))
        # 活：被代码 invoke 的 View
        write_smali(tmp, 'smali/p/UsedView.smali',
                    cls_smali('Lp/UsedView;', '.method public show()V\n return-void\n.end method',
                              super_desc='Landroid/view/View;'))
        write_smali(tmp, 'smali/p/Caller.smali',
                    cls_smali('Lp/Caller;', '.method public go()V\n'
                              ' invoke-virtual {v0}, Lp/UsedView;->show()V\n'
                              ' return-void\n.end method'))

        found = {r['class'] for r in su.find_dead_ui_classes(tmp)}
        self.assertIn('p.DeadView', found, '零引用的 View 子类没有被找出来')
        self.assertNotIn('p.LiveView', found, '被布局引用的 View 被误报成死代码')
        self.assertNotIn('p.UsedView', found, '被代码调用的 View 被误报成死代码')
        self.assertNotIn('p.Plain', found, '非 UI 类的零引用不能被报死（可能是反射入口）')

    ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'work', 'apktool_out'))

    def test_real_apk_finds_brush_mask_view(self):
        """真实 APK：`BrushMaskView` 必须被**自动**发现，而不是靠 KNOWN_DEAD 白名单。

        这是本层存在的全部理由 —— 2026-10-25 侦察时它是靠人眼看出来的。
        限定在 `com/byazt`（加固壳）里扫，全量扫要几分钟。

        **默认跳过**：这一条要 77 秒（7416 个类的单遍扫描），放进 ①b 会让门禁
        每次多等一分钟，而门禁的价值在于"改完立刻知道"。设
        `KDKIT_SLOW_TESTS=1` 才跑。合成夹具那条（1 秒）已经覆盖了同一套判据，
        这一条补的是"真实 APK 上判据仍然成立"，适合按需/发布前跑。
        """
        if not os.environ.get('KDKIT_SLOW_TESTS'):
            self.skipTest('慢测试（77s）：设 KDKIT_SLOW_TESTS=1 才跑')
        if not os.path.isdir(self.ROOT):
            self.skipTest('work/apktool_out 不存在（未解码 APK）')
        rows = su.find_dead_ui_classes(self.ROOT, limit=500, roots_filter=['com/byazt'])
        classes = {r['class'] for r in rows}
        self.assertIn('com.byazt.nd.BrushMaskView', classes,
                      '自动发现没有找出 BrushMaskView —— 判据退化了')
        # 同一批里必然还有它的兄弟（否则说明只特判了一个类）
        self.assertIn('com.byazt.nd.ShadowImageView', classes,
                      '只找到 BrushMaskView 而没找到它的兄弟类 ⇒ 判据可能被特判了')
        self.assertGreaterEqual(len(classes), 5,
                                f'只找到 {len(classes)} 个，判据可能过严: {sorted(classes)}')


if __name__ == '__main__':
    unittest.main()
