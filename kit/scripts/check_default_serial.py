#!/usr/bin/env python3
"""
kuaidui-kit / check_default_serial.py — 默认设备号只许有一个来源。

### 为什么需要

2026-11-03 代码审查 P2：“默认设备号散落 28 个文件”。

那个 28 把 docstring 里的用法示例也算进去了 —— 那些不改行为。
真正会**生效**的硬编码默认值是 5 处（4 个 argparse `default=` +
`after_login.py` 的一个 `os.environ.get(..., 'emulator-5558')`）。

5 处也够危险：换一台设备时要改 5 个地方，漏一个的后果是
某个工具**静默地操作另一台设备** —— 而它看起来跑通了。
（`compare_devices.py` 那种“两边同号”的用法更阴：它会拿一台设备和自己比，
然后报告“没有差异”。）

### 判据

`kit/scripts/*.py` 与 `kit/python/*.py` 里，除了 `device.py` 自己，
**不许**出现写死的 `emulator-5558` 作为 argparse default 或环境变量兜底。
要默认值就走 `device.default_serial()`（它认 `KD_SERIAL` / `SERIAL`，最后才兜底）。

**docstring 里的用法示例不算** —— 它们不改行为，而把它们也算进去
会让这道门禁变成噪音（今天已经为此修过 4 个检查器）。

### 退出码

0 = 只有一处来源；1 = 有新的硬编码默认值。
"""
import argparse
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'scripts', '*.py'),
        os.path.join(ROOT, 'kit', 'python', '*.py')]
ALLOWED = {os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'device.py'), ROOT)}
ALLOWED_PKG = os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'device.py'), ROOT)
#: **也不扫自己**：`SINGLE_SOURCE` 的字面量就在本文件里（今天第二次在同一类
#: 检查器上遇到自指：㉘ 的正则、㉙ 的 `_create_unverified_context`）。
SELF_PATH = os.path.relpath(os.path.abspath(__file__), ROOT)
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
from negctl_fixtures import is_fixture                              # noqa: E402

FALLBACK = 'emulator-5558'

#: 只许出现在 `device.py` 里的常量（2026-11-03 收敛后的预算）。
#: **用 AST 常量判，不数字符串**：注释与 docstring 里的字样不算 ——
#: `server_shape.py:53` 那句“少一个 u 就变成文件不存在”的教训就该留着。
SINGLE_SOURCE = {
    'com.kuaiduizuoye.scan': ('PKG', 1),
    'com.baidu.homework.Preference.LibPreference.xml': ('PREFS', 1),
}


def find_constants(path):
    """AST 找写死的包名 / prefs 文件名常量。"""
    try:
        tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    except (SyntaxError, ValueError):
        return []
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            # **只判"就是这个常量本身"**，不判"字符串里含它"。
            # 第一版用 `lit in value`，于是把 `com.kuaiduizuoye.scan.AliasActivityDefault`
            # （组件名，本来就含包名）、`…-7.7.2-1811-168194.apk`（文件名）、
            # 以及 docstring 里的提及全算成"又写死了一遍" —— 20 处，绝大多数是对的。
            # 一道报 20 条而其中 19 条没错的门禁，等于没有。
            v = n.value.strip()
            for lit, (name, _budget) in SINGLE_SOURCE.items():
                if v == lit or v == f'/data/data/{lit}' \
                        or v.endswith(f'/shared_prefs/com.baidu.homework.Preference.LibPreference.xml'):
                    out.append((n.lineno, name, v[:60]))
    return out


def find_hardcoded(path):
    """AST 找：argparse 的 default=写死 5558，或 `.get(…, '5558')` 的兜底。"""
    try:
        tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    except (SyntaxError, ValueError):
        return []
    out = []
    for n in ast.walk(tree):
        # `add_argument(..., default='emulator-5558')`
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == 'add_argument':
            for kw in n.keywords:
                if kw.arg == 'default' and isinstance(kw.value, ast.Constant) \
                        and kw.value.value == FALLBACK:
                    out.append((n.lineno, 'argparse default 写死设备号'))
        # `os.environ.get('X', 'emulator-5558')`
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == 'get' and len(n.args) >= 2:
            last = n.args[-1]
            if isinstance(last, ast.Constant) and last.value == FALLBACK:
                out.append((n.lineno, '环境变量兜底写死设备号'))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad = []
    n_files = 0
    counts = {name: 0 for _lit, (name, _b) in SINGLE_SOURCE.items()}
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED or is_fixture(p):
                continue
            n_files += 1
            for ln, why in find_hardcoded(p):
                bad.append(f'{rel}:{ln}（{why}）')
                print(f'  ✗   {rel}:{ln}  {why}')
            for ln, name, val in find_constants(p):
                counts[name] += 1
                if rel not in (ALLOWED_PKG, SELF_PATH):
                    bad.append(f'{rel}:{ln}（{name} 又写死了一遍）')
                    print(f'  ✗   {rel}:{ln}  {name} 又写死了一遍：{val}')

    print(f'[serial] 扫了 {n_files} 个文件；硬编码默认设备号 {len(bad)} 处；'
          + '；'.join(f'{k}={v}' for k, v in counts.items()))
    if bad:
        print('[serial] 修法：`from device import default_serial`，'
              '然后 `default=default_serial()` —— 它认 `KD_SERIAL`/`SERIAL`，'
              '最后才兜底。')
        return 1
    print('[serial] 默认设备号只有一个来源（`kit/python/device.py`）✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
