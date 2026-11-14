#!/usr/bin/env python3
"""
kuaidui-kit / check_sign_body_assembly.py — 签名请求体的组装逻辑，六处必须长得一样。

### 为什么需要

2026-11-03 代码审查 P1：

> `probe_paths.py:142-143` 请求体里 `kakorrhaphiophobia` 出现两次（其余 5 处调用点都排除了两者）

同一个约定在 **6 个文件、7 处**重复：`_t_` 与 `kakorrhaphiophobia`
要**跟在 `sign` 之后**放进请求体，不能混在签名参数那段里。
服务端对这两种错法都给同一个错：`antispam sign error`（errNo 6）。

而 `probe_paths.py` 只排了 `_t_`，于是 `kakorrhaphiophobia` 在 body 里出现两次 ——
症状与"漏掉"完全一样，都是 errNo 6。

**这类 bug 的特征是：它不在任何一道门禁的射程内**，因为每处单独看都像对的。
只有把六处**并排**看，才能看出哪一处与其它不一致。

### 判据

用 **AST** 而不是正则：找出所有 `startswith(...)` 调用，取其第一个参数；
若它是字符串常量元组，收集这些常量。所有文件的集合必须相同。
不同 ⇒ 报出来，并指出谁与多数不一致。

为什么用 AST：第一版用正则，而"去掉注释与字符串"的涂白会把
`('_t_', 'kakorrhaphiophobia')` **本身**涂掉 —— 它恰恰是字符串字面量。
于是判据在自己的目标上失效（"一处都没找到"）。

### 退出码

0 = 一致；1 = 有文件的排除集合与其它不同。
"""
import argparse
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'python', '*.py'),
        os.path.join(ROOT, 'kit', 'scripts', '*.py')]

sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
from negctl_fixtures import is_fixture                              # noqa: E402

#: 只关心涉及这两个键的那些调用
INTERESTING = {'_t_', 'kakorrhaphiophobia'}


def collect(path):
    """返回该文件里所有 `startswith(<字符串元组>)` 的 (行号, frozenset(键))。"""
    try:
        tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    except (SyntaxError, ValueError):
        return []
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'startswith'):
            continue
        if not n.args:
            continue
        a = n.args[0]
        if isinstance(a, ast.Tuple):
            keys = {e.value for e in a.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        elif isinstance(a, ast.Constant) and isinstance(a.value, str):
            keys = {a.value}
        else:
            continue
        if keys & INTERESTING:
            out.append((n.lineno, frozenset(keys)))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    groups = {}
    files = []
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            if is_fixture(p):
                continue
            files.append(p)
            for ln, keys in collect(p):
                groups.setdefault(keys, []).append(f'{os.path.relpath(p, ROOT)}:{ln}')

    n_hits = sum(len(v) for v in groups.values())
    if not groups:
        print('[signbody] 一处都没找到 —— 判据本身失效了（代码结构变了？）')
        return 1

    print(f'[signbody] 扫了 {len(files)} 个文件；{n_hits} 处排除逻辑，'
          f'{len(groups)} 种不同写法')
    for keys, where in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f'  {len(where):2d} 处  {sorted(keys)}')
        if a.verbose:
            for w in where:
                print(f'        {w}')

    if len(groups) == 1:
        print('[signbody] 六处一致 ✓')
        return 0

    majority = max(groups, key=lambda k: len(groups[k]))
    print(f'[signbody] **写法不一致**：多数（{len(groups[majority])} 处）排除 '
          f'{sorted(majority)}，而下面这些不是：')
    for keys, where in groups.items():
        if keys == majority:
            continue
        for w in where:
            print(f'   {w}  ⇒  {sorted(keys)}')
    print('[signbody]   症状：请求体里 `_t_`/`kakorrhaphiophobia` 少排一个 ⇒ '
          '服务端判 antispam sign error（errNo 6），与"漏掉"无法区分')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
