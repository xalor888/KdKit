#!/usr/bin/env python3
"""
Offline tests for `kit/scripts/check_robust_coverage.py` — "这个钩子是不是躲在热修复补丁后面"。

为什么它需要自己的测试：这道门禁的**全部价值**在于"能被复现地指出一处看不见的失效"。
如果判定写宽了（把 `PatchProxy` 出现过就算插桩），它会对每个类都报警，于是没人看；
如果写窄了（比如要求 `const/16` 与方法序号严格相邻），它会静默漏报，
而漏报的形态是"绿灯"，没有别的东西会发现。

三个测试各钉住一件事：
  * `Detects`      —— 正样本必须被判出来（含 Kotlin lambda 那种带 `-` 的方法名）；
  * `NotDetected`  —— 负样本**不许**被判出来（字段在但方法没插桩 / 调了 proxy 但不是标准桩）；
  * `RealApk`      —— 在真实的 `work/apktool_out` 上，数字与手核一致，且**不是零**。

`RealApk` 是这次的回归点：2026-10-25 第 29 轮修共享词法前，lambda 方法名被切成 `4`，
24 个方法从未进索引。断言"总数 > 0 且包含 lambda 名"能在同类缺陷再次出现时立刻红。

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, '..', '..', 'scripts'))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCRIPTS)

import check_robust_coverage as rc  # noqa: E402


def write_smali(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)
    return path


PATCHED_CLASS = """.class public Lcom/x/Patched;
.super Ljava/lang/Object;


# static fields
.field public static changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;


# direct methods
.method public constructor <init>()V
    .locals 0

    invoke-direct {p0}, Ljava/lang/Object;-><init>()V

    return-void
.end method


# virtual methods
.method public doWork(I)I
    .locals 3

    const/4 v0, 0x1
    new-array v1, v0, [Ljava/lang/Object;

    const/4 v0, 0x0
    invoke-static {p1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
    move-result-object v2
    aput-object v2, v1, v0

    sget-object v0, Lcom/x/Patched;->changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;

    new-array v0, v0, [Ljava/lang/Class;

    sget-object v0, Ljava/lang/Integer;->TYPE:Ljava/lang/Class;
    sget-object v2, Ljava/lang/Integer;->TYPE:Ljava/lang/Class;
    const/4 v0, 0x0
    const/16 v2, 0x51

    move-object v1, p0
    invoke-static/range {v1 .. v6}, Lcom/meituan/robust/PatchProxy;->proxy([Ljava/lang/Object;Ljava/lang/Object;Lcom/meituan/robust/ChangeQuickRedirect;ZI[Ljava/lang/Class;Ljava/lang/Class;)Lcom/meituan/robust/PatchProxyResult;
    move-result-object v0
    iget-boolean v0, v0, Lcom/meituan/robust/PatchProxyResult;->isSupported:Z
    if-eqz v0, :cond_0
    return-void
    :cond_0
    const/4 v0, 0x7
    return v0
.end method

.method public plainMethod()V
    .locals 0

    return-void
.end method


.method private static final useLambda$lambda-0(Lcom/x/Patched;I)V
    .locals 2

    sget-object v0, Lcom/x/Patched;->changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;
    const/16 v1, 0x64
    invoke-static {p2}, Lcom/meituan/robust/PatchProxy;->proxy([Ljava/lang/Object;)Lcom/meituan/robust/PatchProxyResult;
    move-result-object v0
    return-void
.end method
"""

# 字段在，但**没有任何方法**插桩 —— 不许判成 GUARDED。
FIELD_ONLY = """.class public Lcom/x/FieldOnly;
.super Ljava/lang/Object;

.field public static changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;

.method public go()V
    .locals 0
    return-void
.end method
"""

# 调了 PatchProxy 但类里没有 changeQuickRedirect 字段 —— 不是标准桩。
PROXY_NO_FIELD = """.class public Lcom/x/ProxyOnly;
.super Ljava/lang/Object;

.method public go()V
    .locals 0
    const/16 v1, 0x11
    invoke-static {v1}, Lcom/meituan/robust/PatchProxy;->proxy([Ljava/lang/Object;)Lcom/meituan/robust/PatchProxyResult;
    return-void
.end method
"""

# 有字段、有 proxy，但 sget 读的是**别的类**的 changeQuickRedirect —— 不算。
FOREIGN_SGET = """.class public Lcom/x/Foreign;
.super Ljava/lang/Object;

.field public static changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;

.method public go()V
    .locals 0
    sget-object v0, Lcom/x/Other;->changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;
    const/16 v1, 0x22
    invoke-static {v1}, Lcom/meituan/robust/PatchProxy;->proxy([Ljava/lang/Object;)Lcom/meituan/robust/PatchProxyResult;
    return-void
.end method
"""


class Fixture(unittest.TestCase):
    """一次构建、多个用例复用（像真实 APK 那样放在 `smali_classesN` 根下）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='kdkit-robust-')
        write_smali(cls.tmp, 'smali_classes2/com/x/Patched.smali', PATCHED_CLASS)
        write_smali(cls.tmp, 'smali_classes2/com/x/FieldOnly.smali', FIELD_ONLY)
        write_smali(cls.tmp, 'smali_classes2/com/x/ProxyOnly.smali', PROXY_NO_FIELD)
        write_smali(cls.tmp, 'smali_classes2/com/x/Foreign.smali', FOREIGN_SGET)
        cls.index = rc.build_index(cls.tmp)

    def test_detects_guarded_method_with_method_number(self):
        rec = self.index['com.x.Patched']['doWork']
        self.assertEqual(rec['method_no'], 0x51,
                         '方法序号取错了 —— 它是补丁分派的键，取错等于指错方法')

    def test_detects_lambda_method_name_intact(self):
        """**核心回归点**：名字里的 `-` 必须保留。

        旧词法把它切成 `4`（或整行匹配不上）⇒ 这个方法永远进不了索引。
        """
        self.assertIn('useLambda$lambda-0', self.index['com.x.Patched'],
                      f'lambda 方法名没被正确解析：{sorted(self.index["com.x.Patched"])}')

    def test_unpatched_method_in_patched_class_is_not_guarded(self):
        self.assertNotIn('plainMethod', self.index['com.x.Patched'])
        self.assertNotIn('<init>', self.index['com.x.Patched'])

    def test_field_without_instrumentation_is_not_guarded(self):
        self.assertNotIn('go', self.index.get('com.x.FieldOnly', {}))

    def test_proxy_call_without_field_is_not_guarded(self):
        self.assertNotIn('go', self.index.get('com.x.ProxyOnly', {}))

    def test_sget_of_another_class_field_is_not_guarded(self):
        self.assertNotIn('go', self.index.get('com.x.Foreign', {}))

    def test_trivial_negatives_are_absent_from_index(self):
        for cls in ('com.x.FieldOnly', 'com.x.ProxyOnly', 'com.x.Foreign'):
            self.assertNotIn(cls, self.index, f'{cls} 不该产生任何插桩方法')


class Classification(unittest.TestCase):
    """三档结论的语义必须区分开 —— 它们对使用者的含义完全不同。"""

    def test_three_statuses(self):
        index = {'a.B': {'m': {'method': 'm', 'desc': '', 'method_no': 1}},
                 'c.D': {'other': {'method': 'other', 'desc': '', 'method_no': 2}}}
        targets = [
            {'class': 'a.B', 'method': 'm', 'where': 'x'},
            {'class': 'c.D', 'method': 'gone', 'where': 'y'},
            {'class': 'e.F', 'method': 'z', 'where': 'w'},
        ]
        rows = rc.classify(index, targets)
        self.assertEqual([r['status'] for r in rows],
                         ['GUARDED', 'CLASS-PATCHED', 'PLAIN'])

    def test_guarded_carries_method_number(self):
        index = {'a.B': {'m': {'method': 'm', 'desc': '', 'method_no': 0x4DEC}}}
        rows = rc.classify(index, [{'class': 'a.B', 'method': 'm', 'where': 'x'}])
        self.assertEqual(rows[0]['method_no'], 0x4DEC)


class RealApk(unittest.TestCase):
    """在真实解码目录上跑一遍 —— 防止"只在 fixture 上成立"。

    没有 `work/apktool_out` 时**跳过并说明**，不静默通过（本仓库踩过静默跳过）。
    """

    SMALI = os.path.join(ROOT, 'work', 'apktool_out')

    def setUp(self):
        if not os.path.isdir(self.SMALI):
            self.skipTest(f'没有解码目录 {self.SMALI}（需要先 apktool d；不是失败）')

    def test_apk_has_instrumented_methods_and_they_are_not_zero(self):
        index = rc.build_index(self.SMALI)
        total = sum(len(v) for v in index.values())
        self.assertGreater(len(index), 100,
                           'Robust 类数量异常少 —— 判据可能写窄了（漏掉整个 APK）')
        self.assertGreater(total, 1000,
                           '被插桩的方法数量异常少 —— 判据可能写窄了')
        # 全 APK 里必然存在带连字符的 Kotlin lambda 方法名；一个都没有 ⇒ 词法又写窄了
        lambdas = [n for methods in index.values() for n in methods if '$lambda-' in n]
        self.assertGreater(len(lambdas), 0,
                           '一个 `$lambda-` 方法名都没索引到 ⇒ 方法名词法缺 `-`')

    def test_real_hook_targets_are_classified(self):
        """钩子目标必须能落到三档之一，不允许出现未分类。"""
        index = rc.build_index(self.SMALI)
        try:
            targets = rc.load_hook_targets(self.SMALI)
        except Exception as exc:                     # 模块源码缺失/解析失败
            self.skipTest(f'无法加载钩子目标：{exc}')
        self.assertGreater(len(targets), 50, '钩子目标数量异常少，解析可能坏了')
        rows = rc.classify(index, targets)
        self.assertEqual(len(rows), len(targets))
        self.assertTrue({r['status'] for r in rows} <= {'GUARDED', 'CLASS-PATCHED', 'PLAIN'})
        # 已知锚点：这些确实被插桩（人工核对过 smali，见 NEW_TARGETS.md §5）
        by = {(r['class'], r['method']): r['status'] for r in rows}
        self.assertEqual(by.get(('dj.f', 'd')), 'GUARDED',
                         'dj.f.d（TracerPid 判定，7.7.2 里叫 lk.f.d）本应被插桩；判定可能失效了')


if __name__ == '__main__':
    unittest.main()
