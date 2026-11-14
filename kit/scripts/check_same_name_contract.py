#!/usr/bin/env python3
"""
kuaidui-kit / check_same_name_contract.py — **同名函数的参数顺序必须一致**。

### 为什么需要

2026-11-03 代码审查 P2“同名不同契约”，今天第二次撞上：

* 第一次：`sh()` —— 12 个本地实现里只有 `kit/python/sh.py` 收 **list**。
  合并后 12 个文件全中，acceptance 13 条断言全变成
  `sdk=Android Debug Bridge version 1.0.41`。**那次契约差别还会抛异常。**
* 第二次（本轮）：`decrypt` —— 三个模块都有一个，而参数顺序**不一样**：

      decrypt_strings     decrypt(key, cipher)      ← key 在**前**
      kd_crypto           decrypt(cipher_b64, key)
      device_entry_crypto decrypt(b64, key)

  三者参数都是字符串 ⇒ **调换顺序不会报错**，只会解出一串垃圾。
  **这一次是静默的。**

### 判据

扫 `kit/python/*.py` 与 `kit/scripts/*.py` 的顶层函数。
**同名**且**前两个参数名构成不同的顺序**（`(a, b)` vs `(b, a)`）⇒ 报出来。

这是“调换即静默出错”的充分条件：名字相同、参数可互换、类型还兼容。

### 退出码

0 = 没有这种组合；1 = 有。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import ast
import glob
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'python', '*.py'),
        os.path.join(ROOT, 'kit', 'scripts', '*.py')]


def params(fn):
    return [a.arg for a in fn.args.args if a.arg not in ('self', 'cls')]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    by_name = defaultdict(list)          # name -> [(relpath, lineno, [p1, p2])]
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            try:
                tree = ast.parse(textio.read_text(p, encoding='utf-8', errors='replace'))
            except (SyntaxError, ValueError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.col_offset == 0:
                    ps = params(n)
                    if len(ps) >= 2:
                        by_name[n.name].append((rel, n.lineno, ps[:2]))

    bad = []
    for name, sites in sorted(by_name.items()):
        if len(sites) < 2:
            continue
        orders = {tuple(ps) for _, _, ps in sites}
        # 只要有**两个**site 的前两参是彼此的反序，就是静默可换的
        rev = set()
        for o in orders:
            r = (o[1], o[0])
            if r != o and r in orders:
                rev.add(o)
        if rev:
            bad.append((name, sites))

    print(f'[same-name] 前两参互为反序的同名函数：{len(bad)} 组')
    for name, sites in bad:
        print(f'  ✗   {name}()')
        for rel, ln, ps in sites:
            print(f'         {rel}:{ln}  ({ps[0]}, {ps[1]}, …)')
    if bad:
        print('[same-name]   **参数都是字符串 ⇒ 调换顺序不报错，只会解出垃圾。**')
        print('[same-name]   修法：把参数顺序写进名字（如 `decrypt_with_key(key, cipher)`），'
              '或者统一顺序。')
        print('[same-name]   旧名可以留着，但要**立刻抛 TypeError** —— '
              '宁可让误调当场失败，也不要它静默出错。')
        return 1
    if a.verbose:
        print('[same-name] 没有前两参互为反序的同名函数 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
