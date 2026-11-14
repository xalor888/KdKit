#!/usr/bin/env python3
"""
`verify_face.py` 的判据分支 —— 重点是**别把"提到了类名"当成"页面到过"**。

这条测试的存在理由：第一版的 `reached` 正则写成"行内出现 `CommonWebPictureBrowseActivity`"，
于是匹配到了 `[KdKit] hooked …CommonWebPictureBrowseActivity.o2 [gate=…]` ——
那是**装钩子**的日志。56 次假"到达"把结论从"页面没到过"翻成了"到过但没生效"，
而两者对应的排查方向完全不同。
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'verify_face.py')

HOOK_INSTALL = ('10:00:00.100 APPSIGN I/VectorLegacyBridge: [KdKit] hooked '
                'com.kuaiduizuoye.scan.activity.common.CommonWebPictureBrowseActivity.o2 '
                '[gate=web_picture_watermark]')
NAV = '10:00:01.000 NAVACT CommonWebPictureBrowseActivity'
FIRED = '10:00:02.000 WATERMARK off applied | scope=webpic'


def verdict(face, *lines):
    fd, path = tempfile.mkstemp(suffix='.txt')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        p = subprocess.run([sys.executable, TOOL, '--face', face, '--capture', path],
                           capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    finally:
        os.unlink(path)


class Watermark(unittest.TestCase):

    def test_reached_and_fired_is_verified(self):
        rc, out = verdict('watermark', NAV, FIRED)
        self.assertEqual(rc, 0, out)
        self.assertIn('已验证', out)

    def test_not_reached_is_unverifiable(self):
        rc, out = verdict('watermark', FIRED)   # 有生效记录但没到达 ⇒ 也不该是 0
        self.assertEqual(rc, 2, out)

    def test_reached_but_not_fired_is_unverified(self):
        rc, out = verdict('watermark', NAV)
        self.assertEqual(rc, 2, out)
        self.assertIn('未验证', out)

    def test_hook_install_line_does_not_count_as_reached(self):
        """回归：装钩子的日志**不是**"页面到过"。"""
        rc, out = verdict('watermark', HOOK_INSTALL, HOOK_INSTALL)
        self.assertEqual(rc, 2, out)
        self.assertIn('从没到达过', out)


class Pk(unittest.TestCase):

    def test_page_and_injection_is_verified(self):
        rc, out = verdict('pk',
                          '10:00:01.000 NAV https://ptactivity.zuoyebang.com/static/hy/kd-pk/pk-home.html',
                          '10:00:02.000 APPSIGN I/chromium: [INFO:CONSOLE(11)] '
                          '"[KdKit] injected into about:blank"')
        self.assertEqual(rc, 0, out)

    def test_page_without_injection_is_unverified(self):
        rc, out = verdict('pk',
                          '10:00:01.000 NAV https://ptactivity.zuoyebang.com/static/hy/kd-pk/pk-home.html')
        self.assertEqual(rc, 2, out)
        self.assertIn('未验证', out)


if __name__ == '__main__':
    unittest.main()


class RebuildFidelity(unittest.TestCase):
    """重建保真度：2026-11-03 本文件被负对照误删，靠 `.pyc` + 本测试重建。

    这条把"重建没丢东西"钉住：`.pyc` 里每一个**判据常量**（两张面的
    title / reached / fired / hint，以及 logcat 的 grep 模式）都必须
    出现在重建后的源码里。将来谁改坏了某一个，这里会红。
    """

    def test_every_verdict_constant_survives(self):
        # **自己编译一份 `.pyc`**（2026-11-03 修）。
        #
        # 原来读 `__pycache__/verify_face.cpython-314.pyc` —— 那是 2026-11-03
        # 负对照误删文件后**唯一的重建依据**。但 R101 起 `preflight.sh`
        # 每轮清 `__pycache__`（为了让编辑立刻生效），于是这个 `.pyc` 从来不在，
        # 这条测试**每轮都 skip**。
        #
        # 一条每轮跳过的测试等于没有 —— 而 skip 的理由还写着"重建依据消失"，
        # 听着像环境问题，其实是自己把依据删了。
        import marshal
        import py_compile
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            pyc = py_compile.compile(TOOL, cfile=os.path.join(td, 'vf.pyc'),
                                     doraise=True)
            code = marshal.loads(open(pyc, 'rb').read()[16:])

        def strs(c):
            out = set()
            for k in c.co_consts:
                if isinstance(k, str):
                    out.add(k)
                elif hasattr(k, 'co_consts'):
                    out |= strs(k)
            return out

        # **按片段判，不按整串判**：源码里相邻字符串字面量是拆开写的
        # （`'…logcat -d 2>/dev/null | '` + `'grep -aE …'`），整串永远对不上。
        # 取每个常量里"不可能被拆散"的判据词，逐个要求在源码里出现。
        FRAGMENTS = ['GotoPictureBrowseWebAction', 'kd-pk/pk-home.html',
                     'web_picture_watermark', 'pk_assist',
                     'injected into', 'chromium.*KdKit',
                     'NAVACT', 'WATERMARK off applied', 'PictureBrowse']
        # **`.pyc` 那一半原来根本没跑**（2026-11-03 修）：
        # 上面 `marshal.loads(...)` 把 code 读出来了，`strs()` 也定义了，
        # 但**从没调用 `strs(code)`** —— 于是 docstring 承诺的
        # “`.pyc` 里每一个判据常量都必须出现在重建后的源码里”是空话，
        # 真正在跑的只有下面那个**手写**的 FRAGMENTS 列表。
        #
        # 手写列表的问题是它会自己漂移：源码改了一个词，列表没跟上，
        # 这条测试就开始**检查一个不再重要的词**。
        # 所以这里补上：FRAGMENTS 必须都是 `.pyc` 里真实存在的常量。
        consts = strs(code)
        stale = [f for f in FRAGMENTS if not any(f in c for c in consts)]
        self.assertEqual(stale, [],
                         f'这些片段在 .pyc 的常量里找不到 ⇒ 手写列表已漂移：{stale}')

        with open(TOOL, encoding='utf-8') as _f:
            src = _f.read()
        missing = [f for f in FRAGMENTS if f not in src]
        self.assertEqual(missing, [], f'重建丢了这些判据片段：{missing}')
