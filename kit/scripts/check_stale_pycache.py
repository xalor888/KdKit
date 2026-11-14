#!/usr/bin/env python3
"""
kuaidui-kit / check_stale_pycache.py — **过期的 `.pyc` 会让判据指向错误的对象**。

### 为什么需要（2026-11-03 真实事故）

修 `device_entry_crypto.b64d` 的 padding bug 时，负对照跑出来是**绿的**：

```
[negctl] 改回旧公式 ⇒ 测试仍然 OK
```

我第一反应是“Python 的 `b64decode` 太宽容，这个 bug 从外面看不出来”。
但用 spy 看到 `b64decode` 收到的串是 `'+Pj4+Pj4+A===='`（旧行为），
而 `inspect.getsource` 显示源码是**新的** —— 两者对不上。

根因：`kit/python/__pycache__/device_entry_crypto.cpython-314.pyc`
比源码**旧**，但 Python 仍在使用它。清掉 `__pycache__` 后行为立刻变了。

**一个过期的 `.pyc` 会让“改过的代码看起来没改”** ——
那比没有判据更糟：你会得出“这个 bug 测不出来”的错误结论，
而我差一点就把那个结论写进 STATE。

### 判据

对每个 `.pyc`：比较它与对应 `.py` 的 mtime。
源码更新 ⇒ `.pyc` 过期 ⇒ 报出来。

**不清除它们**：`__pycache__` 在这个仓库里是**有用的** ——
R81 重建 `verify_face.py` 时，唯一的恢复源就是它的 `.pyc`。
所以这道门禁只**报告**，不动手。

### 退出码

0 = 没有过期的 `.pyc`；1 = 有。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'python'),
        os.path.join(ROOT, 'kit', 'scripts'),
        os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java')]


def stale(base):
    out = []
    for dirpath, _dirs, files in os.walk(base):
        if '__pycache__' not in dirpath:
            continue
        for fn in files:
            if not fn.endswith('.pyc'):
                continue
            pyc = os.path.join(dirpath, fn)
            # `foo.cpython-314.pyc` → `foo.py`，在上一级目录
            stem = fn.split('.')[0]
            src = os.path.join(os.path.dirname(dirpath), stem + '.py')
            if not os.path.isfile(src):
                continue                       # 源码没了（比如被删的模块）——另一回事
            if os.path.getmtime(src) > os.path.getmtime(pyc):
                out.append((os.path.relpath(src, ROOT),
                            os.path.getmtime(src) - os.path.getmtime(pyc)))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad = []
    for base in SCAN:
        if os.path.isdir(base):
            bad += stale(base)

    print(f'[pyc] 过期的 .pyc：{len(bad)} 个')
    for rel, dt in bad:
        print(f'  ✗   {rel}  源码比 .pyc 新 {dt:.0f} 秒')
    if bad:
        print('[pyc]   后果：改过的代码看起来没改 —— 判据会指向错误的对象。')
        print('[pyc]   修法：`find . -name __pycache__ -type d -exec rm -rf {} +`')
        print('[pyc]   （不清除是有意的：`.pyc` 在这个仓库里是恢复源之一，'
              'R81 就是靠它重建了被误删的 verify_face.py）')
        return 1
    if a.verbose:
        print('[pyc] 没有过期的 .pyc ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
