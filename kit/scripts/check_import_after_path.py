#!/usr/bin/env python3
"""
kuaidui-kit / check_import_after_path.py — `from kit.python import …` 必须排在 `sys.path.insert` 之后。

### 为什么需要

今天**第三次**在同一处栽倒：

| 轮次 | 症状 |
|---|---|
| R78 | `pageapi.py` 等六个文件插 `import net` 时插到了 `sys.path.insert` 之前 ⇒ ModuleNotFoundError |
| R85 | `nav_log.py` 等四个文件同样的问题，四个工具 `--help` 全 FAIL |
| R86 | `acceptance.py` / `compare_devices.py` / `reverify.py` 第三次 |

症状都一样：文件**能 parse**（`ast.parse` 通过），但**一 import 就炸**。
而 `methodology_check` 只查 AST 层面的纪律，抓不到这个；
`verify.sh` 的 ① 单元测试也不会 import 这些工具。

于是**四个命令行工具全坏，而所有门禁都是绿的** —— 直到有人真的去跑它们。

### 判据

对每个 `kit/scripts/*.py` / `kit/python/*.py`：

* 若文件里有 `from <name> import …`，而 `<name>` 不是标准库、也不是本目录的模块
  （即它要靠 `sys.path.insert(…, 'kit/python')` 才找得到）；
* 那么这条 `from` 必须出现在该文件**第一个 `sys.path.insert` 之后**。

判据用“能否 import”做终审：每个文件都真的 `import` 一遍（在子进程里），
任何 `ModuleNotFoundError` 直接红。

### 退出码

0 = 都能 import；1 = 有文件 import 失败 / 顺序不对。
"""
import argparse
import ast
import glob
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio  # noqa: E402  （句柄安全的读文本；2026-11-03）

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'scripts', '*.py'),
        os.path.join(ROOT, 'kit', 'python', '*.py')]
SELF = os.path.abspath(__file__)

#: `kit/python/` 里的模块名 —— 这些名字要靠 sys.path.insert 才找得到
LOCAL_MODULES = set()
for p in glob.glob(os.path.join(ROOT, 'kit', 'python', '*.py')):
    LOCAL_MODULES.add(os.path.basename(p)[:-3])
for p in glob.glob(os.path.join(ROOT, 'kit', 'python', 'tests', '*.py')):
    LOCAL_MODULES.add(os.path.basename(p)[:-3])

#: **必须把模块注册进 `sys.modules`** 再 exec。
#: 第一版用 `spec_from_file_location('_probe_xxx', p)` 却不注册，
#: 于是 `capture_schema.py` 的 `@dataclass` 在 `sys.modules[cls.__module__]`
#: 拿到 None ⇒ `AttributeError: 'NoneType' object has no attribute '__dict__'`。
#: 那不是被测文件的错，是探针自己的错 —— 报出来会让这道门禁永远红。
PROBE = r'''
import importlib.util, sys, os
p = sys.argv[1]
sys.path.insert(0, os.path.join(%r, 'kit', 'python'))
sys.path.insert(0, os.path.join(%r, 'kit', 'scripts'))
name = '_probe_' + os.path.basename(p)[:-3]
spec = importlib.util.spec_from_file_location(name, p)
m = importlib.util.module_from_spec(spec)
sys.modules[name] = m
spec.loader.exec_module(m)
'''


def local_imports(path):
    """文件里 `from <本地模块> import …` 的行号。"""
    try:
        tree = ast.parse(textio.read_text(path, encoding='utf-8', errors='replace'))
    except (SyntaxError, ValueError):
        return []
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in LOCAL_MODULES:
            # **只查模块级**：函数里的延迟导入在调用时才执行，
            # 那时模块级的 sys.path 早就设好了（`kd_api.py:420` 就是这种）。
            # 第一版把函数内的也算上 ⇒ 一个正确写法被报成错。
            if not _is_module_level(tree, n):
                continue
            out.append(n.lineno)
    return out


def _is_module_level(tree, target):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for sub in ast.walk(n):
                if sub is target:
                    return False
    return True


def first_path_insert(path):
    src = textio.read_text(path, encoding='utf-8', errors='replace')
    return src.find('sys.path.insert')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--no-import', action='store_true',
                    help='只查静态顺序，不真的 import（快，但漏掉顺序之外的错）')
    a = ap.parse_args(argv[1:])

    order_bad, import_bad = [], []
    files = []
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            if os.path.abspath(p) == SELF:
                continue
            files.append(p)
            # **`kit/python/` 里的文件不需要 sys.path**：它们与 `device.py` /
            # `textio.py` 同目录，直接就能 import。
            # 第一版不区分目录 ⇒ `captures.py` 的 `from textio import …`
            # 被报成"顺序不对"，而它是对的（今天第 7 次同一类误报）。
            if os.path.dirname(os.path.abspath(p)) == os.path.join(ROOT, 'kit', 'python'):
                continue
            hits = local_imports(p)
            if not hits:
                continue
            at = first_path_insert(p)
            for ln in hits:
                # 行号转成字符偏移
                lines = textio.read_text(p, encoding='utf-8', errors='replace').split('\n')
                off = sum(len(x) + 1 for x in lines[:ln - 1])
                if at < 0 or off < at:
                    order_bad.append(f'{os.path.relpath(p, ROOT)}:{ln}')

    print(f'[imporder] 扫了 {len(files)} 个文件；顺序不对 {len(order_bad)} 处')
    for x in order_bad:
        print(f'  ✗   {x}  `from <本地模块> import` 排在 sys.path.insert 之前')

    if a.no_import:
        return 1 if order_bad else 0

    # **终审：真的 import 一遍**。顺序对也可能因为别的原因 import 失败。
    with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
        f.write(PROBE % (ROOT, ROOT))
        probe = f.name
    try:
        for p in files:
            rel = os.path.relpath(p, ROOT)
            r = subprocess.run([sys.executable, probe, p],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                err = ((r.stderr or '').strip().split('\n') or ['?'])[-1]
                import_bad.append(f'{rel}  {err[:90]}')
                print(f'  ✗   {rel}  import 失败：{err[:90]}')
    finally:
        os.unlink(probe)

    print(f'[imporder] import 失败 {len(import_bad)} 个')
    if order_bad or import_bad:
        print('[imporder]   修法：把 `from <模块> import …` 移到'
              ' `sys.path.insert(0, …/kit/python)` **之后**。')
        return 1
    print('[imporder] 所有文件的本地导入都排在 sys.path 之后，且都能 import ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
