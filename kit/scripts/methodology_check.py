#!/usr/bin/env python3
"""
kuaidui-kit / methodology_check.py — 把《方法纪律》里**能静态检查的两条**变成机器检查。

`work/METHODOLOGY.md` 是给人读的；但其中两条属于"今天踩过、明天还会踩"的代码级错误，可以自动查：

  规则 1「没有信号 ≠ 信号是负的」：`subprocess.run([...], shell=True)` —— 列表会被 `sh -c` 当成命令字符串，
      实际执行的是 `sh -c adb …` 之类，把**帮助文本当数据**（2026-10-12 造成过四条检查同时假红）。
  规则 9「超时要"有界"」：`subprocess.run/Popen/check_output` **没有 `timeout=`** —— 卡住时无法与"还在跑"区分。

用 AST 检查（不是正则），所以多行调用、关键字参数都能认。

    python3 kit/scripts/methodology_check.py [--paths kit]
"""
import argparse
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CALLS = {'run', 'Popen', 'call', 'check_call', 'check_output'}
#: `os.popen` / `os.system` 完全绕开 timeout ⇒ 一并纳入（2026-11-02：
#: `composition_flow.py` 就有一个无超时的 `os.popen('adb …')`，旧规则看不见它）。
OS_CALLS = {'popen', 'system'}


def attr_name(node):
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else '')


def _has_bounded_wait(tree):
    """本文件里有没有 `…communicate(timeout=…)` 或 `…wait(timeout=…)`。

    `Popen` 本身不接 `timeout=`（它不阻塞），**有界性写在随后的等待调用上**：
    `communicate(timeout=)` 与 `wait(timeout=)` 都算。第一版只认 `communicate`，
    于是 `hold.wait(timeout=30)` 这种正确写法被报成"没有 timeout"（2026-11-09 实测
    `test_with_lock_reentrant.py` 两条假阳性）—— 假阳性会训练人忽略规则。
    """
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ('communicate', 'wait')
                and any(k.arg == 'timeout' for k in n.keywords)):
            return True
    return False


def bound_names(tree):
    """本文件里所有被绑定的名字（赋值 / import / def / class / 参数 / for 目标）。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Lambda):
            for a in node.args.args + node.args.kwonlyargs:
                out.add(a.arg)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.Import):
            for al in node.names:
                out.add((al.asname or al.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for al in node.names:
                out.add(al.asname or al.name)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            pass                     # 目标已是 Name/Store，上面收过了
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    for n in ast.walk(item.optional_vars):
                        if isinstance(n, ast.Name):
                            out.add(n.id)
        elif isinstance(node, ast.comprehension):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    out.add(n.id)
        elif isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            out.update(node.names)
    return out


def undef_names(tree, known):
    """引用了**本文件从未绑定**、也不是内置的名字。

    2026-11-03 规则 12。真实案例：`inject_test.py` 的 `with_backup()` 调了一个
    根本不存在的 `run_mutate()`，于是它**从来没被执行过** ——
    而它承诺的“注入前后比对”是那个脚本存在的全部理由。

    第一版只查 `except` 分支（理由是“别处的未定义名字 import 时就会炸”）。
    实测那个理由不成立：`run_mutate()` 在 `try` 体内调用，不在 except 里，
    而它同样不会在 import 时炸 —— **只有真的走到那一行才炸**。
    所以查整个文件。

    两类豁免，都会让这条规则变成噪音：
      * `from x import *` —— 名字来源不可知；
      * 动态注入（`globals()[...]` / `exec`）—— 判不了。
    """
    import builtins
    # 模块级 dunder 永远存在，但不是 builtins —— 不豁免就会报 176 条 `__file__`
    DUNDERS = {'__file__', '__name__', '__doc__', '__package__', '__spec__',
               '__loader__', '__builtins__', '__debug__', '__dict__'}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(al.name == '*' for al in node.names):
            return []                      # 名字来源不可知
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ('exec', 'eval', 'globals', 'locals', 'vars'):
            return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in known or hasattr(builtins, node.id) or node.id in DUNDERS:
                continue
            out.append((node.lineno, node.id))
    return out


def check_file(path):
    problems = []
    try:
        tree = ast.parse(open(path, encoding='utf-8').read())
    except SyntaxError as e:
        return [(0, f'语法错误：{e}')]
    # 先学出本文件里 subprocess 的别名（import subprocess / import subprocess as sp）——
    # 否则会把自家定义的 run() 助手也点名（第一版就是这样误报的，规则 4 的同款错误：报警器自己有噪音）。
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for al in node.names:
                if al.name == 'subprocess':
                    aliases.add(al.asname or 'subprocess')
        elif isinstance(node, ast.ImportFrom) and node.module == 'subprocess':
            for al in node.names:
                aliases.add(al.asname or al.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or attr_name(node) not in CALLS:
            continue
        if not isinstance(node.func, ast.Attribute):
            continue          # 形如 run(...) 的本地助手，不是 subprocess
        base = node.func.value
        if not (isinstance(base, ast.Name) and base.id in aliases):
            # `os.popen` / `os.system` 绕开 timeout，单独点名
            if (isinstance(base, ast.Name) and base.id == 'os'
                    and attr_name(node) in OS_CALLS):
                problems.append((node.lineno,
                                 f'os.{attr_name(node)}() 没有超时机制'
                                 '（卡住时无法与"还在跑"区分 —— 规则 9）；'
                                 '改用 kit/python/sh.py 的 sh()'))
            continue          # 不是 subprocess 的调用，跳过
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        # 规则 1：shell=True 且第一个参数是列表字面量
        shell = kw.get('shell')
        if isinstance(shell, ast.Constant) and shell.value is True and node.args:
            if isinstance(node.args[0], ast.List):
                problems.append((node.lineno, 'shell=True 配列表参数（会把列表当命令字符串 —— 规则 1）'))
        # 规则 9a：没有 timeout
        # `Popen(...)` 之后配 `p.communicate(timeout=…)` 是**正确且惯用**的写法
        # （超时作用在 communicate 上，Popen 本身不接 timeout）。
        # 第一版把这种也报出来 ⇒ `kit/python/sh.py` 两条假阳性 —— 而假阳性会训练人忽略规则。
        _popen_then_communicate = (attr_name(node) == 'Popen'
                                   and _has_bounded_wait(tree))
        if 'timeout' not in kw and not _popen_then_communicate:
            problems.append((node.lineno, 'subprocess 调用没有 timeout=（不满足"有界"—— 规则 9）'))
        # 规则 9b：`shell=True` 必须自成进程组，否则超时只杀 shell、
        #         管道里的子进程（`adb`）活着继续挂 ⇒ timeout 是**假**有界。
        #
        # **判据必须认"算出来的 shell=True"，不只认字面量**（2026-11-03 修）。
        # 第一版写 `isinstance(shell, ast.Constant) and shell.value is True`，
        # 于是 `shell=isinstance(cmd, str)` 这种写法**整条漏过去** ——
        # 而全库有 12 处正是这么写的，且都没有 start_new_session。
        # 一道判据比它以为的窄，比没有判据更危险：它给出"查过了"的假象。
        shell_maybe_true = (
            (isinstance(shell, ast.Constant) and shell.value is True)
            or (shell is not None and not (isinstance(shell, ast.Constant)
                                           and shell.value is False))
        )
        if (shell_maybe_true
                and 'start_new_session' not in kw and 'preexec_fn' not in kw):
            problems.append((node.lineno,
                             'shell=True 没有 start_new_session=True'
                             '（超时只杀 shell，子进程会泄漏 —— 规则 9b）'))
    # 规则 12：except 分支里的未定义名字
    known = bound_names(tree)
    for ln, name in undef_names(tree, known):
        problems.append((ln, f'引用了未定义的名字 {name!r}'
                             '（那一行走到才炸 —— 规则 12；'
                             'import 时不炸，所以门禁看不见它）'))
    return problems


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths', nargs='+', default=['kit'])
    a = ap.parse_args(argv[1:])

    total, offenders = 0, 0
    for base in a.paths:
        for root, _d, files in os.walk(os.path.join(ROOT, base)):
            if '__pycache__' in root:
                continue
            for fn in sorted(files):
                if not fn.endswith('.py'):
                    continue
                p = os.path.join(root, fn)
                probs = check_file(p)
                total += 1
                if probs:
                    offenders += 1
                    rel = os.path.relpath(p, ROOT)
                    for lineno, why in probs:
                        print(f'[method] {rel}:{lineno}  {why}')
    print(f'[method] 检查 {total} 个文件；{offenders} 个有不符合项')
    return 1 if offenders else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
