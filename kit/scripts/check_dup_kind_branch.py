#!/usr/bin/env python3
"""
kuaidui-kit / check_dup_kind_branch.py — 同一个函数里不许有两个 `if kind == '<同一个值>'`。

### 为什么需要

2026-11-04 代码审查 P2：`capture_transcript.one_line()` 里有**两个**
`if kind == 'POPWIN':`，在同一个函数里，前一个先 `return`
⇒ **后一个（更详细、唯一区分 BLOCK/OBSERVE/PASS 的那个）是死代码，一行都没跑过。**

死掉的那个恰好写着：

    OBSERVE —— 命中拦截清单但 observe_only 开着 ⇒ 只记录、未拦截
    PASS    —— 不在清单里 ⇒ 放行

活着的那个把 `OBSERVE` 写成"已记录（放行）" —— **把两件事糊成一件**，
于是"只观测"模式在报告里看不出它生效了。

这类错误的特点：**代码能跑、测试能过、输出看着正常**，
只是有一个分支永远不执行。它不会报错，只会让人纳闷"为什么我加的那段没生效"。

### 判据（口径写死，避免误报）

只看**语句级**的 `ast.If`，其 `test` 恰好是：

    Compare(left=Name('kind'), ops=[Eq()], comparators=[Constant(str)])

即 `if kind == '<字面量>':`。**不看**三元表达式（`X if kind == 'Y' else Z`）、
不看 `kind in (...)`、不看 `kind == 变量`。

第一版把范围内所有 `Compare` 都算进去 ⇒
`side = '写侧' if kind == 'PCTRLW' else '读侧'` 被误报成重复分支。
**判据的范围比它以为的宽，是本项目今天第 11 次遇到的同一类错。**

### 退出码

0 = 没有重复；1 = 有。
"""
import argparse
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = ('kit/**/*.py',)


def kind_branches(tree):
    """函数名 → {kind 值: [行号, ...]}（只收语句级的 `if kind == '<常量>'`）。"""
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        seen = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            t = node.test
            if not (isinstance(t, ast.Compare) and len(t.ops) == 1
                    and isinstance(t.ops[0], ast.Eq)):
                continue
            if not (isinstance(t.left, ast.Name) and t.left.id == 'kind'):
                continue
            val = t.comparators[0]
            if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
                continue
            seen.setdefault(val.value, []).append(node.lineno)
        if seen:
            out[fn.name] = seen
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad = []
    for pat in SCAN:
        for p in glob.glob(os.path.join(ROOT, pat), recursive=True):
            rel = os.path.relpath(p, ROOT)
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    tree = ast.parse(f.read())
            except (OSError, SyntaxError, ValueError):
                continue
            for fn, seen in kind_branches(tree).items():
                for val, lines in seen.items():
                    if len(lines) > 1:
                        bad.append(f'{rel}:{lines[0]}  {fn}() 里 `kind == {val!r}` '
                                   f'出现 {len(lines)} 次（行 {lines}）')

    print(f'[dupkind] 重复的 `kind == <字面量>` 分支：{len(bad)} 处')
    for b in bad:
        print(f'  ✗   {b}')
    if bad:
        print('[dupkind]   同一个函数里前一个先 return ⇒ 后面那个**永远不执行**。')
        print('[dupkind]   症状：代码能跑、测试能过、输出看着正常，'
              '只是"我加的那段没生效"。')
        print('[dupkind]   修法：把两份合并成一份（留下更详细的那个），或者给它们不同的 kind 值。')
        return 1
    if a.verbose:
        print('[dupkind] 没有重复的 kind 分支 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
