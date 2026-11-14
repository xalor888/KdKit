#!/usr/bin/env python3
"""
kuaidui-kit / check_dup_gz_reader.py — **不许再出现逐字相同的 `.gz` 读取器**。

### 为什么需要

2026-11-03 代码审查 P2：

> **`.gz` 感知读取器 4 份逐字相同**（`core_http_paths` / `bridge_urls` /
> `api_login_map` / `bridge_page_map`）

四份一模一样的 5 行，已收敛到 `kit/python/textio.py`。

但"收敛过一次"不等于"不会再长出来" —— 下一个人写新工具时会照抄旁边那份。
所以这道门禁盯的是：**那段特征代码只许出现一次**。

### 判据

统计 `gzip.open(path, 'rt'` 的出现次数（AST 属性访问，不看注释）。
超过 1 处 ⇒ 报出来，并指名。允许的那一处在 `kit/python/textio.py`。

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
ALLOWED = {os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'textio.py'), ROOT),
          os.path.relpath(os.path.abspath(__file__), ROOT)}   # **不扫自己**：正则在字面量里
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
from negctl_fixtures import is_fixture                              # noqa: E402


def hits(path):
    """AST 里 `gzip.open(..., 'rt', ...)` 的调用点行号。

    **只认文本读**（第二个位置参数是 `'rt'`）：`pack_slim.py` 那两处是
    二进制读写（`'rb'` / `'wb'`），与"读抓取文本"不是一回事。
    第一版不挑模式 ⇒ 把 `pack_slim` 也报出来 —— 而它是对的。
    **一道在正确代码上也响的门禁等于没有**（今天为此修过 5 处）。
    """
    try:
        tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    except (SyntaxError, ValueError):
        return []
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'open'
                and isinstance(n.func.value, ast.Name) and n.func.value.id == 'gzip'):
            continue
        mode = None
        if len(n.args) >= 2 and isinstance(n.args[1], ast.Constant):
            mode = n.args[1].value
        for kw in n.keywords:
            if kw.arg == 'mode' and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if isinstance(mode, str) and mode.startswith('r') and 't' in mode:
            out.append(n.lineno)
    return out


def memread_sites(path):
    """AST 里写着 `dd if=/proc/.../mem` 的**字符串常量**。

    2026-11-03 加：代码审查 P2 的"root 读内存 3 份 3 种引号写法"。
    三份不只是写法不同 —— **只有一份有 `base64 -w0` 的兜底**，
    另外两份换台 busybox 设备就静默返回 `b''`。已收敛到 `memread.py`。

    **用 AST 而不是文本匹配**：第一版按行找，把 docstring 里
    为了说明问题而提到的那句也报了出来（`find_sign_strings.py:14`），
    还有检查器自己的（`check_dup_gz_reader.py:81`）——
    今天第四次在同一类检查器上遇到自指/注释误报。
    """
    try:
        tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    except (SyntaxError, ValueError):
        return []
    # 先收出所有 docstring 的节点 —— 它们**不算代码**。
    # （第一版把 `find_sign_strings.py` 的模块 docstring 也报了出来。）
    docstrings = set()
    for n in ast.walk(tree):
        body = getattr(n, 'body', None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            docstrings.add(id(body[0].value))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if id(n) in docstrings:
                continue
            if 'dd if=/proc/' in n.value and '/mem' in n.value:
                out.append(n.lineno)
    return out


def capture_glob_missing_gz(path):
    """`--captures` 的 argparse 默认值里**有 .txt 没有 .txt.gz**。

    2026-11-03 加：`pack_slim` 会把 `--keep` 之外的旧包压成 `.txt.gz`。
    一个工具的 `--captures` 默认值只列 `.txt` 时，不带参数跑就
    **静默漏掉所有压缩包** —— 而报告里只会显示"路径变少了"。
    已修：`api_login_map` / `bridge_page_map` / `core_http_paths` 三处。

    **判据是"这一份默认值整体"**，不是单个字面量：
    第一版逐个常量判，于是同一个列表里已经有 `.gz` 的那一项也被报
    （今天第 9 次同一类误报：判据的粒度比它以为的细）。
    """
    try:
        tree = ast.parse(open(path, encoding='utf-8', errors='replace').read())
    except (SyntaxError, ValueError):
        return []

    def pats(node):
        """把一个默认值里所有"看起来像 capture glob"的字符串收出来。"""
        out = []

        def one(x):
            # **`.txt.gz` 也要收**：它不以 `.txt` 结尾，却是同一个 glob 家族的一员。
            # 第一版只收 `.txt`，于是列表里明明有 `.gz` 也被判"漏了"
            # （今天第 10 次同一类误报）。
            if isinstance(x, ast.Constant) and isinstance(x.value, str) \
                    and 'capture' in x.value \
                    and x.value.endswith(('.txt', '.txt.gz')):
                out.append(x.value)
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) \
                    and x.func.attr == 'join':
                for a in x.args:
                    one(a)

        if isinstance(node, (ast.List, ast.Tuple)):
            for el in node.elts:
                one(el)
        else:
            one(node)
        return out

    bad = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == 'add_argument'):
            continue
        names = [a.value for a in n.args if isinstance(a, ast.Constant)]
        if '--captures' not in names:
            continue
        for kw in n.keywords:
            if kw.arg != 'default':
                continue
            got = pats(kw.value)
            if any(p.endswith('capture*.txt') for p in got) \
                    and not any(p.endswith('capture*.txt.gz') for p in got):
                bad.append(n.lineno)
    return bad


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    found = []
    mem_allowed = {os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'memread.py'), ROOT)}
    CAPTURES_REL = os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'captures.py'), ROOT)
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED or rel in mem_allowed or is_fixture(p):
                continue
            for ln in hits(p):
                found.append(f'{rel}:{ln}')
            for ln in memread_sites(p):
                found.append(f'{rel}:{ln}（root 读内存）')
            if rel != CAPTURES_REL:
                for ln in capture_glob_missing_gz(p):
                    found.append(f'{rel}:{ln}（抓取 glob 漏了 .gz）')

    print(f'[gz-dup] textio 之外的 gzip.open 调用点：{len(found)} 处')
    for x in found:
        print(f'  ✗   {x}')
    if found:
        print('[gz-dup]   修法：`import textio` 然后用 `textio.read_lines(path)`。')
        print('[gz-dup]   root 读内存：`import memread` 然后 '
              '`memread.read_mem(serial, pid, addr, len)` —— '
              '它带 `base64 -w0` 的兜底，另外两份原来没有。')
        print('[gz-dup]   抓取 glob：`import captures` 然后 '
              '`captures.iter_captures()` —— 两种形态都认。')
        print('[gz-dup]   **必须写 `textio.` 而不是裸 `read_lines`** —— '
              '那四个文件里都有同名函数，裸调用会无限递归。')
        return 1
    if a.verbose:
        print('[gz-dup] 只有 textio 一处 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
