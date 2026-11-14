#!/usr/bin/env python3
"""
Tests for `kit/scripts/check_fake_tests.py` — the ⑦ gate.

A detector for fake tests is itself a test-shaped thing, so it gets the same
treatment: **prove it catches what it claims**, and prove it does not fire on
the honest patterns (message-first asserts, reasoned skips).

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'scripts'))

import check_fake_tests  # noqa: E402


def scan_snippet(rel, text):
    """把一段代码写进临时仓库结构，跑扫描，返回命中规则名集合。"""
    d = tempfile.mkdtemp()
    parts = rel.split('/')
    p = os.path.join(d, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return {rule for rule, *_ in check_fake_tests.scan(d)}


KT = 'module/app/src/test/java/x/T.kt'
PY = 'kit/python/tests/test_x.py'


class CatchesRealFakes(unittest.TestCase):

    def test_literal_variable_assert(self):
        """真实形态：局部变量只由字面量赋值，再对它做字符串断言。

        检测器第一版只匹配 `"字面量".endsWith(...)`，漏掉了这个 —— 而它才是实际写法。
        """
        code = '''
class T {
    @Test
    fun f() {
        val desc = "ei.y.H(Ljava/lang/String;)V"
        assertTrue(desc.endsWith(")V"))
    }
}
'''
        self.assertIn('literal-assert', scan_snippet(KT, code))

    def test_direct_literal_assert(self):
        """直接对字面量断言。

        这条是**召回率测试**补出来的：注入 3 条假测试时，
        假 1（变量）✅ 假 2（静默返回）✅ 假 3（直接字面量）❌ —— 漏了。
        检测器换用"变量名"方案后丢掉了第一版的直接字面量匹配，这里守住它。
        """
        code = '''
class T {
    @Test
    fun f() {
        assertTrue("the quick brown fox".contains("quick"))
    }
}
'''
        self.assertIn('literal-assert', scan_snippet(KT, code))

    def test_silent_early_return(self):
        code = '''
class T {
    @Test
    fun f() {
        val f = java.io.File("/nope")
        if (!f.isFile) return
        assertEquals(1, 2)
    }
}
'''
        self.assertIn('silent-return', scan_snippet(KT, code))

    def test_all_four_spellings_of_a_silent_return(self):
        """四种写法都必须抓到。

        第一版只认单行无花括号，实测漏掉后三种 —— 与第 27 轮
        `check_declared_counts` 那次同一类缺陷：**正则写窄 = 整类形态失去保护**。
        """
        spellings = {
            'plain':      'if (!f.isFile) return',
            'brace-inline': 'if (!f.isFile) { return }',
            'brace-multiline': 'if (!f.isFile) {\n    return\n}',
            'label':      'if (!f.isFile) return@test',
        }
        for name, fragment in spellings.items():
            with self.subTest(spelling=name):
                code = ('class T {\n    @Test\n    fun f() {\n        '
                        + fragment + '\n        assertEquals(1, 2)\n    }\n}\n')
                self.assertIn('silent-return', scan_snippet(KT, code),
                              f'漏掉了 {name} 形态')

    def test_order_dependent_import(self):
        """import 本地模块却没插 sys.path。

        症状是 `ModuleNotFoundError`（**ERROR 不是 FAIL**，容易被当成环境问题），
        而完整套件里因为别的文件先插了路径它是绿的 ⇒ 顺序依赖。
        2026-10-25 实测 `test_parsers_cli.py` 有 5 条测试只在完整套件下通过。
        """
        code = (
            'import capture_schema\n'
            'class T:\n'
            '    def test_x(self):\n'
            '        assert capture_schema.parse_line("x")\n'
        )
        self.assertIn('order-dependent-import', scan_snippet(PY, code))

    def test_from_import_also_checked(self):
        """`from capture_schema import …` 与 `import capture_schema` 同等对待 ——
        真实文件里两种都有（`test_redact_capture.py` 用的是 from 形式）。"""
        code = (
            'from capture_schema import parse_line\n'
            'class T:\n'
            '    def test_x(self):\n'
            '        assert parse_line("x")\n'
        )
        self.assertIn('order-dependent-import', scan_snippet(PY, code))

    def test_skip_without_reason(self):
        code = 'class T:\n    def test_x(self):\n        self.skipTest()\n'
        self.assertIn('skip-without-reason', scan_snippet(PY, code))

    # ── 2026-11-02 补：这两种最经典的假测试，检测器原本**两条都抓不到** ──────
    #
    # 怎么发现的：给门禁做故障注入，把这两种形状真的写进测试目录，
    # `check_fake_tests.py --strict` 两次都返回 0。守卫所有测试的那道门，
    # 自己对最常见的两种假测试是瞎的 —— 补规则，并把注入形态固化成用例。

    def test_tautological_assert(self):
        code = 'class T:\n    def test_x(self):\n        self.assertTrue(True)\n'
        self.assertIn('tautological-assert', scan_snippet(PY, code))

    def test_tautological_assert_equal_same_name(self):
        code = 'class T:\n    def test_x(self):\n        self.assertEqual(v, v)\n'
        self.assertIn('tautological-assert', scan_snippet(PY, code))

    def test_no_assert_at_all(self):
        code = 'class T:\n    def test_x(self):\n        print(1 + 1)\n'
        self.assertIn('no-assert', scan_snippet(PY, code))


class DoesNotFireOnHonestPatterns(unittest.TestCase):
    def test_real_assert_in_pytest_style_is_fine(self):
        """`assert x == 2` 是真断言，不能因为"只有一行"就报 no-assert。"""
        code = 'class T:\n    def test_x(self):\n        assert add(1, 1) == 2\n'
        self.assertNotIn('no-assert', scan_snippet(PY, code))

    def test_assert_true_with_condition_is_fine(self):
        code = 'class T:\n    def test_x(self):\n        self.assertTrue(is_ok())\n'
        self.assertNotIn('tautological-assert', scan_snippet(PY, code))

    """误报比漏报更危险：一道会误报的门禁会教人忽略门禁。"""

    def test_message_first_assert_is_fine(self):
        """JUnit 是 `assertTrue(message, condition)` —— 消息在前，不是自我实现。"""
        code = '''
class T {
    @Test
    fun f() {
        assertTrue("若 H 不再是 void 就说明拦截语义变了", h.isVoid())
    }
}
'''
        self.assertEqual(scan_snippet(KT, code), set())

    def test_assert_on_a_call_result_is_fine(self):
        code = '''
class T {
    @Test
    fun f() {
        assertEquals("cube", PopwinGate.pidOf(req))
    }
}
'''
        self.assertEqual(scan_snippet(KT, code), set())

    def test_reasoned_skip_is_honest_degradation(self):
        """`skipTest('没有 APK')` 是诚实的降级，不是假测试。"""
        code = (
            'class T:\n'
            '    def test_x(self):\n'
            "        self.skipTest('work/apktool_out 不存在')\n"
        )
        self.assertEqual(scan_snippet(PY, code), set())


class RealRepoIsClean(unittest.TestCase):
    """本仓库当前不该有命中 —— 有的话说明有人写了假测试，或检测器误报了。"""

    def test_no_findings_in_repo(self):
        findings = check_fake_tests.scan(ROOT)
        self.assertEqual(
            [], findings,
            '发现假测试迹象（若确认是误报，请修正检测规则而不是删断言）：'
            + str(findings[:5]),
        )


if __name__ == '__main__':
    unittest.main()
