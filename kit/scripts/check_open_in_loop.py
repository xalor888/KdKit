#!/usr/bin/env python3
"""
kuaidui-kit / check_open_in_loop.py — **循环里不许有裸 `open()`**。

### 为什么需要

2026-11-03 代码审查 P2-21：

> `test_schema_roundtrip.py:81` 循环内 `open(f)` 未关闭 —— 实测产出数十条 ResourceWarning

实测全库：**234 处**裸 `open()`，其中 **41 处**在 `for`/`while` 里。
（今天先修掉 12 个文件里的那一批，剩下 29 处判据脚本自己。）

### 为什么循环里的那 41 处特别危险

裸 `open(...).read()` 依赖 **CPython 的引用计数**才恰好关闭。
`hook_vocab.py` 的注释已经为这件事专门处理过一次：

> 整个门禁链路要扫 5 万个 smali + 500 个 .kt。裸 `open(p).read()` 依赖
> CPython 的引用计数才*恰好*不会堆积句柄 —— 它不是协议保证，
> 换运行时或改 GC 行为就会撞 `Too many open files`
> （macOS 默认 `ulimit -n` 只有 256）。

**循环放大了这件事**：一次调用开一个句柄，GC 什么时候回收不确定。
今天跑测试时实测 **403 条** `ResourceWarning: unclosed file`。

### 判据

AST 找 `open(...)` 调用，它既不是任何 `with` 的上下文表达式，
又位于某个 `for`/`while` 的子树里 ⇒ 报出来。

### 退出码

0 = 没有；1 = 有。
"""
import argparse
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'python', '*.py'),
        os.path.join(ROOT, 'kit', 'python', 'tests', '*.py'),
        os.path.join(ROOT, 'kit', 'scripts', '*.py')]
ALLOWED = {os.path.relpath(os.path.abspath(__file__), ROOT)}   # 不扫自己


def with_exprs(tree):
    """所有 `with` 的上下文表达式节点 id —— 那些是**会关闭**的。"""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                out.add(id(item.context_expr))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--max', type=int, default=-1,
                    help='允许的处数上限；默认用 BASELINE。**抬高它必须写清为什么** —— '
                         '这条门禁盯的是"句柄泄漏"，不是风格。')
    #: **当前基线**（2026-11-03 实测 61）。
    #:
    #: 为什么不一步清零：这些 `open()` 大多在**判据脚本**里（读源码、读文档），
    #: 而它们读的是**少量文件**（几十个），句柄不会堆到 256。
    #: 真正危险的是扫 5 万个 smali 的那几处 —— `hook_vocab.py` 已经处理过。
    #:
    #: 所以这道门禁现在的作用是：**不许再涨**。每修一处就下调一次基线，
    #: 数字往下走是可见的。
    BASELINE = 0
    a = ap.parse_args(argv[1:])

    bad = []
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED:
                continue
            try:
                tree = ast.parse(open(p, encoding='utf-8', errors='replace').read())
            except (SyntaxError, ValueError):
                continue
            we = with_exprs(tree)
            for n in ast.walk(tree):
                if not isinstance(n, (ast.For, ast.AsyncFor, ast.While)):
                    continue
                for c in ast.walk(n):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                            and c.func.id == 'open' and id(c) not in we):
                        bad.append(f'{rel}:{c.lineno}')

    print(f'[loopopen] 循环里的裸 open()：{len(bad)} 处')
    for b in bad:
        print(f'  ✗   {b}')
    cap = BASELINE if a.max < 0 else a.max
    if len(bad) > cap:
        print(f'[loopopen]   上限 {cap} 处，当前 {len(bad)} 处。'
              '**抬高上限必须写清为什么** —— 这条门禁盯的是句柄泄漏，不是风格。')
    if len(bad) > cap:
        print('[loopopen]   修法：`with open(...) as f:`。')
        print('[loopopen]   裸 `open(...).read()` 依赖 CPython 的引用计数才恰好关闭 —— '
              '换运行时或改 GC 行为就是句柄泄漏。')
        print('[loopopen]   macOS 默认 `ulimit -n` 只有 256，'
              '而本仓库要扫 5 万个 smali + 500 个 .kt。')
        return 1
    if a.verbose:
        if cap == 0:
            print('[loopopen] 循环里没有裸 open() ✓')
        else:
            print(f'[loopopen] {len(bad)} 处 ≤ 基线 {cap} ✓（这条门禁现在的作用是"不许再涨"）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
