#!/usr/bin/env python3
"""
kuaidui-kit / check_sign_formula_dup.py — **签名公式只许有一处实现**。

### 为什么需要

2026-11-03 代码审查 P2：

> **签名公式 3 份**（`kd_api.py:103`、`read_sign_inputs.py:88`、
> `decode_token_native.py:88`、`find_sign_strings.py:133`）

同一段 md5 链：

    md5( const_a + '[' + md5(x) + ']@' + param )

在四个文件各写一遍。**P0-5（“请求体里 `kakorrhaphiophobia` 重复”）**
正是这一类“有一处没跟着改”造成的 —— 而那一次的后果是
服务端对每个请求都回 errNo 6，而现象与“参数集不对”完全一样。

已收敛到 `kd_api.sign_digest()`，它**有测试**（`test_kd_api_sign.SignFor`）。
这道门禁盯的是“不许再长出一份”。

### 判据

AST 找**签名链**的特征：一个 `md5(...)` 调用的参数里出现了另一个
`md5(x)`，并且整体被 `md5(...)` 包住。
这种嵌套只允许出现在 `kit/python/kd_api.py`。

打印用的 `md5(X)`（诊断行）**不算** —— 那不是公式。

### 退出码

0 = 只有一处；1 = 又复制出去了。
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
ALLOWED = {os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'kd_api.py'), ROOT)}
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import textio
from negctl_fixtures import is_fixture                              # noqa: E402


def is_md5(call):
    return (isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == 'md5')


def nested_md5_sites(tree):
    """`md5(A + '[' + md5(B) + ']@' + C)` 这种**两层嵌套**的调用点。

    单层 `md5(x)` 是诊断打印，不算 —— 那道判据会把四行
    `print(f'… md5(X) = {md5(x)}')` 全报出来，而它们是对的
    （今天已经为"门禁在正确代码上也响"修过 6 处）。
    """
    out = []
    for node in ast.walk(tree):
        if not is_md5(node):
            continue
        for sub in ast.walk(node):
            if sub is node:
                continue
            if is_md5(sub):
                out.append(node.lineno)
                break
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    found = []
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED or is_fixture(p):
                continue
            try:
                tree = ast.parse(textio.read_text(p, encoding='utf-8', errors='replace'))
            except (SyntaxError, ValueError):
                continue
            for ln in nested_md5_sites(tree):
                found.append(f'{rel}:{ln}')

    print(f'[sign-dup] kd_api 之外的嵌套 md5 签名链：{len(found)} 处')
    for x in found:
        print(f'  ✗   {x}')
    if found:
        print('[sign-dup]   修法：`import kd_api` 然后 `kd_api.sign_digest(A, X, param)`。')
        print('[sign-dup]   那一处有测试；复制出去的这份没有，'
              '而它坏掉的症状是服务端对每个请求回 errNo 6'
              '—— 与"参数集不对"完全一样。')
        return 1
    if a.verbose:
        print('[sign-dup] 签名公式只有 kd_api.sign_digest 一处 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
