#!/usr/bin/env python3
"""
kuaidui-kit / check_fake_tests.py — 抓"看着通过、其实什么都没测"的测试。

## 为什么需要这道检查

本项目已经踩过两次同一类错误（都在 2026-10-25，都由我自己写出）：

1. **断言自我实现**
   ```kotlin
   val desc = "…Popwindow$ListItem;)V"
   assertTrue(desc.endsWith(")V"))     // 测的是字符串字面量，不是代码
   ```
   把被测对象换成任何值测试都不变。删掉它测试照样绿。

2. **静默跳过**
   ```kotlin
   val f = java.io.File("../../../work/apktool_out/…/y.smali")
   if (!f.isFile) return                 // CWD 是 module/app，永远不存在 ⇒ 永远 return
   ```
   测试"通过"了，但它一次都没执行断言。

这两类错误的共同点：**没有 FAIL，所以没人会发现**。它们比红着的测试更危险 ——
红测试会说"我失败了"，假测试会说"一切都好"。

## 检查什么

| 规则 | 抓什么 |
|---|---|
| `literal-assert` | Kotlin/Python 测试里对**纯字面量**做 endsWith/contains/startsWith/matches 断言 |
| `silent-return` | Kotlin 测试方法体里出现 `if (!…) return` 这类**无消息**的提前返回 |
| `skip-without-reason` | `skipTest(...)` / `Assume.assume*` 没有写明原因字符串 |

## 不检查什么

* 带基线的 `assertTrue(message, cond)` —— 消息在前是 JUnit 的正确顺序，不误报；
* Python 的 `self.skipTest('原因')` —— 带字符串原因的跳过是**诚实的降级**，
  不是假测试。只有无原因的跳过才可疑。

## 用法

```bash
python3 kit/scripts/check_fake_tests.py            # 人读
python3 kit/scripts/check_fake_tests.py --strict   # 有任何命中就 exit 1
```

默认不 exit 1：先让它作为**报告**存在一段时间，看清误报率再决定是否拦门禁。
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hook_vocab import read_text  # noqa: E402  —— 唯一读文件入口，避免 ResourceWarning

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

# 对**测试内自赋值的局部变量**做字符串断言。
#
# 第一版只匹配 `assertTrue("字面量".endsWith(...))` —— 太窄，漏掉了真实形态：
# ```kotlin
# val desc = "ei.y.H(…)V"
# assertTrue(desc.endsWith(")V"))     // ← 这才是实际写法
# ```
# 现在的做法：先收集"只被赋过一次字面量、且从未从被测代码取值"的局部变量名，
# 再检查断言里是否对这些名字做 endsWith/contains/startsWith/matches。
LOCAL_LITERAL = re.compile(r'\bval\s+(\w+)\s*=\s*"')
ASSERT_ON_VAR = re.compile(
    r'assert\w*\(\s*(?:[^,()]*,\s*)?(\w+)\s*\.\s*'
    r'(endsWith|contains|startsWith|matches)\s*\(')

# 直接对字面量断言：`assertTrue("abc".contains("a"))`
# 这种形态第一版匹配过、后来换成"变量名"方案时丢了。召回率测试（注入 3 条假测试）
# 抓出来的：假 1（变量）✅ 假 2（静默返回）✅ 假 3（直接字面量）❌ —— 补回来。
ASSERT_ON_LITERAL = re.compile(
    r'assert\w*\(\s*(?:[^,()]*,\s*)?"[^"]{4,}"\s*\.\s*'
    r'(endsWith|contains|startsWith|matches)\s*\(')
LITERAL_ASSERT_PY = re.compile(
    r'assert\w*\(\s*"[^"]{4,}"\s*\.\s*(endswith|startswith|__contains__)', re.I)

# 无消息的提前 return：`if (!f.isFile) return` —— 静默跳过
# 无消息的提前 return —— **四种写法都算**。
#
# 第一版只认 `if (...) return`（单行无花括号），实测漏掉三种：
#   if (x) { return }        ← 花括号同行
#   if (x) {\n return\n }    ← 花括号多行
#   if (x) return@test       ← 带标签的 return（Kotlin 里很常见）
# 这与第 27 轮 `check_declared_counts` 那次是同一类缺陷：
# **正则写窄 = 那一整类形态失去保护，而且看起来是绿的。**
# `return` 后**不能跟表达式** —— `if (x) return 1` 是正常返回值，不是静默跳过。
# 判据：return 之后到行尾只允许出现 `}` 或空白。
_RET = r'return(?:@\w+)?\s*\}?\s*(?:$|\n)'
SILENT_RETURN_KT = re.compile(
    r'\bif\s*\([^)]*\)\s*\{?\s*' + _RET +      # if (…) / if (…) { 后紧跟 return
    r'|\bif\s*\([^)]*\)\s*\{\s*\n\s*' + _RET,  # if (…) {\n return
    re.M)

# 无原因的 skip
SKIP_PY = re.compile(r'skipTest\(\s*\)')

# 测试文件里 `import <本地模块>`，但没把对应目录插进 sys.path。
#
# 症状：单独跑该文件 → `ModuleNotFoundError`（**ERROR 不是 FAIL**，容易被误读成环境问题）；
# 而完整套件里因为别的文件先插了路径，它是绿的 ⇒ 顺序依赖。
# 2026-10-25 实测：`test_parsers_cli.py` 有 5 条测试只在完整套件下通过。
LOCAL_IMPORT = re.compile(
    r'^(?:import|from)\s+(capture_schema|capture_transcript|session_report|'
    r'hook_vocab|smali_usage|redact_capture|api_pid_map)\b', re.M)
PATH_SETUP = re.compile(r'sys\.path\.(insert|append)')

SKIP_PY_REASONED = re.compile(r'skipTest\(\s*[\'"][^\'"]+[\'"]')


# ── 恒真断言与"一条断言都没有"的测试（2026-11-02 补） ───────────────────────
#
# 这两类是最**经典**的假测试，而原来的检测器两条都抓不到：
#
# ```python
# def test_a(self):
#     self.assertTrue(True)      # 恒真
#
# def test_b(self):
#     print(1 + 1)               # 没有任何断言
# ```
#
# 怎么发现的：给门禁做故障注入时，把这两种形状**真的写进测试目录**，
# `check_fake_tests.py --strict` 两次都返回 0 —— 守卫所有测试的那道门，
# 自己对最常见的两种假测试是瞎的。
TAUTOLOGY = [
    re.compile(r'\bassertTrue\(\s*True\s*\)'),
    re.compile(r'\bassertFalse\(\s*False\s*\)'),
    re.compile(r'\bassert\s+(?:True|1\s*==\s*1|not\s+False)\s*(?:#.*)?$', re.M),
    re.compile(r'\bassertEqual\(\s*(\w+)\s*,\s*\1\s*\)'),
    re.compile(r'\bassertIs\(\s*(\w+)\s*,\s*\1\s*\)'),
]

#: 算作"这条测试真的断言了什么"的记号
#: 注意 `skipTest(...)` 也算：**带原因**的跳过是诚实的降级（"没 APK 所以不跑"），
#: 不是"什么都没测"。漏掉它会把诚实降级误报成假测试 —— 误报比漏报更伤门禁。
ASSERT_TOKENS = re.compile(
    r'self\.assert|\bassertEqual|\.fail\(|assertRaises|pytest\.raises|'
    r'assert\s|assertIs|assertIn|subTest|skipTest\(')

DEF_TEST = re.compile(r'^(\s*)def\s+(test_\w+)\s*\(', re.M)


def kt_tests(root):
    base = os.path.join(root, 'module', 'app', 'src', 'test')
    for dirpath, _d, files in os.walk(base):
        for fn in sorted(files):
            if fn.endswith('.kt'):
                yield os.path.join(dirpath, fn)


def py_tests(root):
    base = os.path.join(root, 'kit', 'python', 'tests')
    for fn in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if fn.endswith('.py'):
            yield os.path.join(base, fn)


def scan(root):
    findings = []

    for path in kt_tests(root):
        text = read_text(path)
        rel = os.path.relpath(path, root)
        # 测试里"只由字面量赋值"的局部变量 —— 对它们做字符串断言是自我实现
        literal_vars = set(LOCAL_LITERAL.findall(text))
        for m in ASSERT_ON_LITERAL.finditer(text):
            findings.append(('literal-assert', rel, _line(text, m.start()),
                             '直接对字面量断言，换掉被测对象测试不变'))
        for m in ASSERT_ON_VAR.finditer(text):
            if m.group(1) in literal_vars:
                findings.append(('literal-assert', rel, _line(text, m.start()),
                                 f'对字面量局部变量 `{m.group(1)}` 断言，换掉被测对象测试不变'))
        for m in SILENT_RETURN_KT.finditer(text):
            findings.append(('silent-return', rel, _line(text, m.start()),
                             '无消息的提前 return —— 条件不满足时测试静默通过'))

    for path in py_tests(root):
        text = read_text(path)
        rel = os.path.relpath(path, root)
        # **跳过"测检测器"的文件本身**。
        #
        # 它的测试夹具里必然含有 `skipTest()` 这样的示例代码字符串 ——
        # 那是被检查的素材，不是真的调用。第一版没排除，于是检测器把
        # 自己的测试用例报成语义违规（实测抓到自己 1 处误报）。
        #
        # 这条豁免刻意**按文件名精确匹配**，不用通配：豁免范围越小越好，
        # 免得将来有人把真测试塞进这个文件名里绕过去。
        if os.path.basename(path) == 'test_fake_test_detector.py':
            continue
        for m in LITERAL_ASSERT_PY.finditer(text):
            findings.append(('literal-assert', rel, _line(text, m.start()),
                             '对纯字面量断言'))
        for m in SKIP_PY.finditer(text):
            findings.append(('skip-without-reason', rel, _line(text, m.start()),
                             'skipTest() 没写原因 —— 说不出为什么跳过就没人知道它没跑'))
        for rx in TAUTOLOGY:
            for m in rx.finditer(text):
                findings.append(('tautological-assert', rel, _line(text, m.start()),
                                 '恒真断言（换成任何被测对象都成立）'))
        # "一条断言都没有"的测试：按 `def test_*` 切块，块内找不到任何断言记号
        blocks = list(DEF_TEST.finditer(text))
        for i, m in enumerate(blocks):
            end = blocks[i + 1].start() if i + 1 < len(blocks) else len(text)
            body = text[m.end():end]
            if not ASSERT_TOKENS.search(body):
                findings.append(('no-assert', rel, _line(text, m.start()),
                                 f'`{m.group(2)}` 里没有任何断言 —— 它只会"通过"，不会失败'))
        # 顺序依赖：import 了本地模块却没设 sys.path
        if LOCAL_IMPORT.search(text) and not PATH_SETUP.search(text):
            findings.append(('order-dependent-import', rel, 1,
                             'import 本地模块但没插 sys.path —— 单独运行会 ModuleNotFoundError'))

    return findings


def _line(text, pos):
    return text.count('\n', 0, pos) + 1


def main(argv):
    ap = argparse.ArgumentParser(description='抓"看着通过其实什么都没测"的测试')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--strict', action='store_true',
                    help='有命中就 exit 1（默认只报告）')
    a = ap.parse_args(argv[1:])

    findings = scan(a.root)
    if not findings:
        print('[fake-tests] 没有发现假测试迹象')
        return 0

    by_rule = {}
    for rule, rel, line, why in findings:
        by_rule.setdefault(rule, []).append((rel, line, why))
    for rule, items in sorted(by_rule.items()):
        print(f'## {rule}  ({len(items)})')
        for rel, line, why in items[:10]:
            print(f'   {rel}:{line}  {why}')
        if len(items) > 10:
            print(f'   … 另有 {len(items) - 10} 处')
        print()
    print(f'[fake-tests] 命中 {len(findings)} 处（{len(by_rule)} 类）')
    return 1 if a.strict else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
