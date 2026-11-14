#!/usr/bin/env python3
"""
kuaidui-kit / check_capture_open.py — **不许直接 `open()` 一个 `--capture` 参数**。

### 为什么需要

2026-11-03 连续第四次撞上同一类：`--capture` 可以给 `.txt.gz`
（`pack_slim` 会把旧包压掉），而直接 `open()` 会读到 gzip 的二进制 ——
**每一行都解析失败**。

今天已修的四处：

| 位置 | 症状 |
|---|---|
| `capture_schema.iter_records` | 891 份压缩抓取整份 UNKNOWN |
| `extract_config.py` | 传 `.gz` ⇒ 报告**空白**，看起来像“这个包里没有配置接口” |
| `extract_samples.py` | 同上 |
| `probe_paths.py` | 同上 |

空报告比报错更难查：它不说“我没读到”，它说“这里什么都没有”。

### 判据

AST 找 `open(X)`，其中 `X` 是 `a.capture` / `args.capture` /
`a.capture` 形式的属性访问，且**不在** `textio.py` 里。

### 退出码

0 = 没有直接 open；1 = 有。
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'python', '*.py'),
        os.path.join(ROOT, 'kit', 'scripts', '*.py')]
ALLOWED = {os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'textio.py'), ROOT),
           os.path.relpath(os.path.abspath(__file__), ROOT)}


def is_capture_arg(node):
    """`a.capture` / `args.capture` / `opts.capture`。"""
    return (isinstance(node, ast.Attribute) and node.attr == 'capture'
            and isinstance(node.value, ast.Name))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad = []
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED:
                continue
            try:
                tree = ast.parse(textio.read_text(p, encoding='utf-8', errors='replace'))
            except (SyntaxError, ValueError):
                continue
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == 'open' and n.args and is_capture_arg(n.args[0])):
                    bad.append(f'{rel}:{n.lineno}')

    print(f'[capopen] 直接 open(`--capture` 参数) 的地方：{len(bad)} 处')
    for b in bad:
        print(f'  ✗   {b}')
    if bad:
        print('[capopen]   修法：`import textio` 然后 `textio.read_lines(a.capture)`。')
        print('[capopen]   **必须写 `textio.` 而不是裸 `read_lines`** —— '
              '那四个文件里都有同名函数，裸调用会无限递归。')
        print('[capopen]   传 `.txt.gz` 时的症状不是报错，是**报告空白** —— '
              '它看起来像“这个包里没有这类行”。')
        return 1
    if a.verbose:
        print('[capopen] 没有直接 open(--capture) ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
