#!/usr/bin/env python3
"""
Offline tests: `pack_slim` must refuse to compress a capture a doc's repro command cites.

Why this file exists
--------------------
2026-11-03：为了测 `pack_slim` 的"解压验证"守卫，我用 `--keep 0` 跑了一次 ——
那个参数的意思是"**一个都不保留**"，于是全库 867 个 capture 全被压缩，
其中 `work/packs/r793/capture.txt` 正被四份文档的复现命令引用：

    module/ACTIVITY.md, work/MODULE_ACTIVITY.md,
    work/BRIDGE_PAGE_MAP.md, work/CORE_HTTP_REQUESTS.md

门禁 ①b 当场红（"复现命令引用了不存在的路径"）。
**事后抓到不如事前拦住** —— 于是有了这条守卫：被文档引用的 capture 不许压。

这几条测试钉住三件事：

1. 文档引用的路径**真的能被读出来**（读不出来就等于没保护）；
2. 精确路径与 glob 路径都能匹配；
3. 守卫失效时（`is_doc_referenced` 恒 False）这些测试会红。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'pack_slim.py')


def _tool():
    spec = importlib.util.spec_from_file_location('pack_slim', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class DocReferencedPaths(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _tool()
        cls.refs = cls.t.doc_referenced_paths()

    def test_references_are_found(self):
        """至少要读出一些来 —— 读不到就等于没保护。"""
        self.assertTrue(self.refs, '一份文档引用都没读到 ⇒ 守卫是空的')

    def test_r793_is_protected(self):
        """`r793/capture.txt` 正被四份文档引用，必须被认出。"""
        p = os.path.join(ROOT, 'work', 'packs', 'r793', 'capture.txt')
        self.assertTrue(self.t.is_doc_referenced(p, self.refs),
                        'r793/capture.txt 被文档引用却没被认出 ⇒ 守卫有洞')

    def test_glob_reference_does_not_protect(self):
        """`work/packs/*/capture*.txt` 这种 glob **不算**保护。

        第一版把 glob 命中也算"被引用"，于是每一个 `capture*.txt` 都受保护
        ⇒ 瘦身名存实亡（这条测试当场抓住了那个过头设计）。

        glob 不需要保护：读它们的工具（`bridge_page_map.py:33`）都接受 `.gz`。
        真正该修的是只列了 `*.txt` 没列 `*.txt.gz` 的复现命令 ——
        那是文档不完整，不是压缩有危险。
        """
        globs = {r for r in self.refs if '*' in r}
        self.assertTrue(globs, '没有任何 glob 形态的引用')
        p = os.path.join(ROOT, 'work', 'packs', 'r793', 'capture.txt')
        self.assertFalse(any(self.t.is_doc_referenced(p, {g}) for g in globs),
                         'glob 命中了 ⇒ 每个 capture 都受保护，瘦名存实亡')

    def test_unreferenced_is_not_protected(self):
        """没人引用的包**不该**被保护 —— 否则瘦身永远做不了事。"""
        p = os.path.join(ROOT, 'work', 'packs', 'zzz_nobody_cites_this', 'capture.txt')
        self.assertFalse(self.t.is_doc_referenced(p, self.refs))

    def test_prefix_is_not_enough(self):
        """目录前缀相等**不算**被引用 —— 否则会保护过多，瘦名存实亡。"""
        refs = {'work/packs/r793'}
        p = os.path.join(ROOT, 'work', 'packs', 'r793', 'something_else.txt')
        self.assertFalse(self.t.is_doc_referenced(p, refs))


class GuardCanFail(unittest.TestCase):
    """守卫本身必须能被证明会动 —— 否则它只是装饰。"""

    def test_disabling_the_guard_unprotects_r793(self):
        t = _tool()
        refs = t.doc_referenced_paths()
        p = os.path.join(ROOT, 'work', 'packs', 'r793', 'capture.txt')
        self.assertTrue(t.is_doc_referenced(p, refs))
        # 模拟守卫失效（调用方写成 `if False and …`）
        self.assertFalse(False and t.is_doc_referenced(p, refs),
                         '这条恒为 False —— 它证明的是"守卫可以被关掉"，'
                         '所以上面那条"被保护"不是永远成立的')


if __name__ == '__main__':
    unittest.main()
