#!/usr/bin/env python3
"""
Offline test: 浏览页水印是**两条独立链路**，`watermark_off` 盖不到第二条。

为什么需要这个文件
------------------
`watermark_off` 的文档（`WatermarkOff.kt` 的 KDoc、`NEW_TARGETS.md` §2）一直把"去水印"
讲成**一条**链路：`cu.l` 构造器 → 字段 `r` → `ext="2"` 随 `/kdapi/image/combine` 上传。
那确实存在。但本文件测的是**另一条**：

    GotoPictureBrowseWebAction   needWatermark (JSON)   → createIntent(…, Z)
    CommonWebPictureBrowseActivity  q0 ← INPUT_NEED_WATER
      h2()  :1711  if (q0) → :1735  c2(Bitmap)          ← Canvas 把水印画进位图
      j2()  :1963  if (watermark) setVisibility(0)     ← 同一页还有一个水印 View

这条链路**不经过 `cu.l`、不经过服务端**，纯本地绘制。静态证据在
`work/apktool_out/smali_classes5/…/CommonWebPictureBrowseActivity.smali`。

断言的四件事（都能离线复跑）
----------------------------
1. `o2` 真的把水印位图画进位图（`decodeResource` + 两次 `drawBitmap` + `Math.random`）；
2. `o2` 由 `q0` 门控 —— 证明"跳过合成"是页面自己的合法状态，不是我们发明的；
3. `q0` 来自 `INPUT_NEED_WATER` intent extra —— 把 H5 `needWatermark` 与本地绘制连起来；
4. 两个目标都**不是死代码**（`smali_usage` 判 `USED(self)`）—— 按 PARADIGM §7.6 第 6 条，
   先证明不是死代码，再写功能。

未验证：真机上大图是否真无水印（本轮无设备）。本文件只证明静态链条存在且钩点活着。

Run:

    python3 -m unittest kit/python/tests/test_web_picture_watermark.py -v
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCRIPTS = os.path.join(ROOT, 'kit', 'scripts')
APK = os.path.join(ROOT, 'work', 'apktool_out')
ACT = os.path.join(APK, 'smali_classes5', 'com', 'kuaiduizuoye', 'scan', 'activity',
                   'common', 'CommonWebPictureBrowseActivity.smali')
MODULE = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit')
FEATURE = os.path.join(MODULE, 'features', 'host', 'WebPictureWatermark.kt')

sys.path.insert(0, SCRIPTS)


def _body(text, method_sig):
    """取出一个 `.method …` 到它的 `.end method` 之间的正文（含行号）。"""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith('.method') and method_sig in ln:
            start = i
            break
    if start is None:
        return None, 0
    for j in range(start, len(lines)):
        if lines[j].startswith('.end method'):
            return lines[start:j + 1], start + 1
    return None, start + 1


@unittest.skipUnless(os.path.isdir(APK), 'work/apktool_out 不存在（未解码 APK）')
class WatermarkIsDrawnLocally(unittest.TestCase):
    """① `o2` 的正文必须真的在合成水印位图。"""

    def setUp(self):
        if not os.path.exists(ACT):
            self.skipTest(f'找不到 {ACT}')
        with open(ACT, encoding='utf-8', errors='replace') as fh:
            self.text = fh.read()

    def test_c2_composites_a_bitmap_on_top(self):
        body, line0 = _body(self.text, 'o2(Landroid/graphics/Bitmap;)Landroid/graphics/Bitmap;')
        self.assertIsNotNone(body, 'o2(Bitmap) 方法不见了 —— 钩点失效，功能要重新找点')
        joined = '\n'.join(body)
        # 水印位图来自资源（不是服务端下发的图片本身）
        self.assertRegex(joined, r'const v\d+, 0x7f[0-9a-f]+',
                         'o2 里没有 decodeResource 的资源 id —— 可能不再是本地水印合成')
        self.assertIn('BitmapFactory;->decodeResource', joined,
                      'o2 不再 decodeResource 水印位图')
        self.assertIn('createScaledBitmap', joined, 'o2 不再缩放水印位图')
        # 两次 drawBitmap：先画原图，再画水印
        self.assertGreaterEqual(joined.count('Canvas;->drawBitmap'), 2,
                                'o2 的 drawBitmap 少于 2 次 —— 不再"原图 + 水印"两层')
        # 随机位置：所以不能靠"擦掉固定区域"去掉
        self.assertGreaterEqual(joined.count('Math;->random'), 2,
                                'o2 的随机定位消失了 —— KDoc 里"位置随机"这条理由要更新')

    def test_c2_is_gated_by_q0(self):
        """② 调用点必须受 `q0` 门控（页面自己有"无水印"状态）。"""
        body, _ = _body(self.text, 't2(Ljava/io/File;Lcom/kuaiduizuoye/scan/widget/core/TouchImageView;)V')
        self.assertIsNotNone(body, 't2(File, TouchImageView) 不见了 —— o2 的调用方改了')
        joined = '\n'.join(body)
        self.assertIn('->q0:Z', joined, 't2 里没有读 q0 —— 门控字段改名了？')
        self.assertIn('->o2(Landroid/graphics/Bitmap;)', joined,
                      't2 不再调用 o2 —— 主钩点可能已经不在路径上')
        # q0 的读取出现在 c2 调用**之前**
        iq = joined.index('->q0:Z')
        ic = joined.index('->o2(Landroid/graphics/Bitmap;)')
        self.assertLess(iq, ic, 'q0 的读取在 o2 调用之后 —— 门控关系不成立')

    def test_q0_comes_from_the_intent_extra(self):
        """③ H5 的 `needWatermark` 落到 `q0` 的链路。

        注意 `INPUT_NEED_WATER` 在文件里出现**两次**：`:909` 是 `createIntent` 里的
        **写**（putExtra），`:1292` 才是 `onCreate` 里的**读**（getBooleanExtra → q0）。
        第一版断言用了 `re.search` 取**第一处**，于是抓到了写方向、报"不再走
        getBooleanExtra" —— 是测试看错了位置，不是代码坏了。
        所以这里显式要求"读到的那一处"后面紧跟 getBooleanExtra。
        """
        self.assertEqual(self.text.count('"INPUT_NEED_WATER"'), 2,
                         'INPUT_NEED_WATER 的出现次数变了（预期写/读各一处），逐行重核')
        self.assertIn('putExtra(Ljava/lang/String;Z)', self.text,
                      '写方向（putExtra）不见了 —— createIntent 不再传这个 extra')

        # 读方向：找到**紧跟 getBooleanExtra** 的那一处
        reads = [m for m in re.finditer(r'const-string ([vp]\d+), "INPUT_NEED_WATER"',
                                        self.text)
                 if 'getBooleanExtra' in self.text[m.start():m.start() + 1200]]
        self.assertEqual(len(reads), 1,
                         f'预期恰好一处"读"（后接 getBooleanExtra），实际 {len(reads)} 处')
        tail = self.text[reads[0].start():reads[0].start() + 1200]
        self.assertIn('getBooleanExtra', tail, 'INPUT_NEED_WATER 不再走 getBooleanExtra')
        self.assertIn('->q0:Z', tail, 'INPUT_NEED_WATER 不再写入 q0 —— 门控链断了')

    def test_j2_toggles_the_watermark_view(self):
        """同一页还有一个水印 View：`v2` 用布尔控制 setVisibility(0)/setVisibility(8)。"""
        body, _ = _body(self.text, 'v2(ZLandroid/widget/RelativeLayout;)V')
        self.assertIsNotNone(body, 'v2(boolean, RelativeLayout) 不见了 —— 次钩点失效')
        joined = '\n'.join(body)
        self.assertGreaterEqual(joined.count('setVisibility'), 2,
                                'v2 里 setVisibility 少于 2 处 —— 不再是"显示/隐藏"二选一')
        self.assertIn('RelativeLayout', joined, 'v2 不再操作 RelativeLayout')


@unittest.skipUnless(os.path.isdir(APK), 'work/apktool_out 不存在（未解码 APK）')
class TargetsAreAlive(unittest.TestCase):
    """④ 按 PARADIGM §7.6 第 6 条：先证明不是死代码，再写功能。"""

    def setUp(self):
        import smali_usage as su
        self.su = su

    def test_both_hook_points_are_used(self):
        rows = self.su.analyse(APK, [
            ('com.kuaiduizuoye.scan.activity.common.CommonWebPictureBrowseActivity', 'c2'),
            ('com.kuaiduizuoye.scan.activity.common.CommonWebPictureBrowseActivity', 'j2'),
        ])
        for r in rows:
            with self.subTest(target=r.target):
                self.assertNotEqual(
                    r.verdict, self.su.V_DEAD,
                    f'{r.target} 变成死代码了 —— 功能会空转，必须换钩点')


class ModuleDeclaresBothHooks(unittest.TestCase):
    """⑤ 模块侧必须**字面量**写两个钩点，否则 ④⑤⑥ 看不见它（PARADIGM §7.6.1）。"""

    def setUp(self):
        if not os.path.exists(FEATURE):
            self.skipTest('WebPictureWatermark.kt 不存在')
        with open(FEATURE, encoding='utf-8') as fh:
            self.src = fh.read()

    def test_method_names_are_literals(self):
        for m in ('"o2"', '"v2"'):
            with self.subTest(method=m):
                self.assertIn(m, self.src,
                              f'钩点 {m} 不是字面量 —— 门禁按字面量解析，会看不见这条钩子')

    def test_gate_id_matches_feature_id(self):
        self.assertIn('id = "web_picture_watermark"', self.src)
        self.assertRegex(self.src, r'gate = id\b',
                         '钩子没用 gate = id —— 热开关不会生效')

    def test_claims_unverified_in_doc(self):
        """文档必须写明"未验证"—— 不许把静态结论写成已验证。"""
        self.assertIn('未验证', self.src,
                      'KDoc 没有写"未验证" —— 本轮无设备，静态结论不能当已验证')


if __name__ == '__main__':
    unittest.main(verbosity=2)
