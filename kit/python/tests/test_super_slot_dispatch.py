#!/usr/bin/env python3
"""
Offline test: ⑥ 号门的第 ③ 层必须是**向上**的（覆写祖先槽位）。

为什么单独一个文件
------------------
2026-10-25 第 26 轮跑 `check_hook_callers.py`，输出 89 个目标全绿，末尾却挂着一行：

    ? kl.a.getBody   (features/host/HttpBodyProbe.kt:142) —— 0 个调用点

门禁是绿的（`NEEDS-REVIEW` 不算失败），所以这行"问号"会一直留在那里。查下去发现
它不是"需要人看一眼"，而是**工具缺一层**：

* `kl.a`（7.7.2 里叫 `ql.a`）直接 `extends Lcom/android/volley/d;`，自己声明 `getBody()[B`；
* 全 APK **没有任何** `invoke-* ->Lkl/a;->getBody` 调用点 ⇒ "直接调用"为 0；
* 旧逻辑随后只做**向下**判定（`subclasses_of` ⇒ `OK(polymorphic)`），
  而 `kl.a` 的子类 `rl.a` 也不调它 ⇒ 掉进 `NEEDS-REVIEW`；
* 真槽位在**祖父类** `com.android.volley.v` 上（`d` 是抽象类但**不声明** `getBody`），
  调用点有两处：`ZybHurlStack.smali:159` 与 `lk/l0.smali:146`，都是
  `invoke-virtual {..}, Lcom/android/volley/v;->getBody()[B`。

所以"只看直接父类"会漏判 —— 必须走整条祖先链。这正是本文件的第一个断言。

三个断言的分工
--------------
1. `test_ancestor_chain_crosses_abstract_intermediate`：`d` 不声明、`v` 才声明。
   证明"只看直接父类"在这里必然失败，不是实现细节。
2. `test_super_slot_classification`：真实 APK 上 `kl.a.getBody` 必须是
   `OK(super-slot)` 并指向 `com.android.volley.v` —— 结论可复跑。
3. `test_negative_control_not_every_target_is_a_slot`：这条最重要。
   新层若过宽（例如"祖先链上任何人声明同名方法就算活"），它会把**真死代码**洗白。
   断言：仍然存在被判 `DEAD` 的目标（`BrushMaskView.onDraw`），且 `OK(super-slot)`
   在 89 个目标里**只**命中 `kl.a.getBody` 这一条 —— 新层窄且准。

离线可重复：需要 `work/apktool_out`（已解码的 APK）。不存在时 skip，不伪装成通过。

Run:

    python3 -m unittest kit/python/tests/test_super_slot_dispatch.py -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCRIPTS = os.path.join(ROOT, 'kit', 'scripts')
MODULE = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit')
APK = os.path.join(ROOT, 'work', 'apktool_out')

sys.path.insert(0, SCRIPTS)


def _have_apk():
    return os.path.isdir(APK)


@unittest.skipUnless(os.path.isdir(SCRIPTS), '找不到 kit/scripts')
class AncestorChain(unittest.TestCase):
    """① 槽位声明在祖父类上，不在直接父类上 —— 这是本层的存在理由。"""

    def setUp(self):
        if not _have_apk():
            self.skipTest('work/apktool_out 不存在（未解码 APK）')
        import check_hook_callers
        self.c = check_hook_callers

    def test_ancestor_chain_crosses_abstract_intermediate(self):
        chain = self.c.ancestors_of(APK, 'kl.a')
        self.assertEqual(chain[:2], ['com.android.volley.d', 'com.android.volley.v'],
                         f'kl.a 的祖先链变了，本条断言需重核: {chain}')
        # 直接父类**不**声明 getBody，祖父类才声明
        self.assertNotIn('getBody', self.c._defined_cached(APK, 'com.android.volley.d'),
                         'com.android.volley.d 现在声明了 getBody —— '
                         '那"必须走整条链"这条理由就不成立了，重核后再改本测试')
        self.assertIn('getBody', self.c._defined_cached(APK, 'com.android.volley.v'),
                      'com.android.volley.v 不再声明 getBody —— 槽位消失了，'
                      'kl.a.getBody 要重新判定是否为死代码')

    def test_slot_really_has_dispatch_callers(self):
        """槽位必须有 `invoke-virtual` 调用点；否则 `OK(super-slot)` 就是空口无凭。"""
        text_hits = []
        for dirpath, _dirs, files in os.walk(APK):
            for f in files:
                if not f.endswith('.smali'):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    with open(p, encoding='utf-8', errors='replace') as fh:
                        t = fh.read()
                except OSError:
                    continue
                if 'Lcom/android/volley/v;->getBody()[B' not in t:
                    continue
                for line in t.splitlines():
                    if 'Lcom/android/volley/v;->getBody()[B' in line and 'invoke-' in line:
                        text_hits.append((os.path.relpath(p, APK), line.strip()))
        self.assertGreaterEqual(
            len(text_hits), 2,
            f'槽位调用点少于 2 处，kl.a.getBody 的活代码结论失去依据: {text_hits}')
        ops = {h[1].split()[0] for h in text_hits}
        self.assertTrue(ops & {'invoke-virtual', 'invoke-interface'},
                        f'槽位没有虚分派调用点（只有 {ops}）⇒ 覆写不会被分派到')


@unittest.skipUnless(os.path.isdir(SCRIPTS), '找不到 kit/scripts')
class SuperSlotClassification(unittest.TestCase):
    """② 真实 APK 上的分类结论。"""

    # 分类结果放**类属性**，不是实例属性。
    #
    # `classify(APK, MODULE)` 单次约 9 秒；第一版把 `self.rows = None` 写在 `setUp` 里，
    # 于是每个测试方法都重算一次 —— 这个类 5 个方法 ⇒ 白跑 4 次（实测该文件 40 秒，
    # 其中 36 秒是重复）。
    #
    # 门禁从 35 秒涨到 146 秒后，人就会开始少跑它。
    # **一道"太慢所以懒得跑"的门禁，等于没有门禁。**
    rows = None
    c = None

    @classmethod
    def setUpClass(cls):
        if not _have_apk():
            raise unittest.SkipTest('work/apktool_out 不存在（未解码 APK）')
        import check_hook_callers
        cls.c = check_hook_callers

    def _rows(self):
        if type(self).rows is None:
            type(self).rows, _index = type(self).c.classify(APK, MODULE)
        return type(self).rows

    def test_super_slot_classification(self):
        rows = {r['class'] + '.' + r['method']: r for r in self._rows()}
        r = rows.get('kl.a.getBody')
        self.assertIsNotNone(r, 'kl.a.getBody 不在目标清单里 —— 钩子被删了？')
        self.assertEqual(r['status'], 'OK(super-slot)',
                         f'kl.a.getBody 应为 OK(super-slot)，实际 {r["status"]}')
        self.assertEqual(r['super_slot'], 'com.android.volley.v',
                         f'槽位应指向祖父类 volley.v，实际 {r.get("super_slot")}')

    def test_negative_control_not_every_target_is_a_slot(self):
        """新层必须窄：它不能把死代码洗白，也不能解释掉所有目标。"""
        rows = self._rows()
        slots = [r for r in rows if r['status'] == 'OK(super-slot)']
        self.assertEqual([f'{r["class"]}.{r["method"]}' for r in slots],
                         ['kl.a.getBody'],
                         'OK(super-slot) 命中了不止 kl.a.getBody —— 判定层可能过宽，'
                         '会把真死代码洗白。逐条核对这些目标是否真是槽位覆写')
        # 对照：BrushMaskView 必须仍是死代码（它在 KNOWN_DEAD 里，故显示 KNOWN-DEAD；
        # 但它的**底层判定**必须是 DEAD，见 test_smali_usage.RealApk）
        self.assertFalse(any(r['class'] == 'com.byazt.nd.BrushMaskView'
                             and r['status'] == 'OK(super-slot)' for r in rows),
                         'BrushMaskView 被判成槽位覆写 —— 新层误伤')

    def test_no_review_leftovers(self):
        """门禁不该在绿的同时挂着"待核查"的问号 —— 那正是本轮修掉的形态。"""
        rows = self._rows()
        review = [f'{r["class"]}.{r["method"]}' for r in rows
                  if r['status'] in ('NEEDS-REVIEW', 'SELF-ONLY', 'NO-CALLER')]
        self.assertEqual(review, [],
                         f'仍有未定性的目标（门禁绿但挂着问号）: {review}。'
                         '每一条都要么给出证据层，要么进 KNOWN_DEAD 并写明理由')


if __name__ == '__main__':
    unittest.main(verbosity=2)
