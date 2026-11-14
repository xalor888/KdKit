#!/usr/bin/env python3
"""
kuaidui-kit / check_unclosed_files.py — **跑测试时不许有 ResourceWarning**。

### 为什么需要

2026-11-03 代码审查 P2-21：

> `test_schema_roundtrip.py:81` 循环内 `open(f)` 未关闭 —— 实测产出数十条 ResourceWarning

今天在门禁 ①b 的输出里又看见它：

```
test_schema_roundtrip.py:81: ResourceWarning: unclosed file <_io.TextIOWrapper …>
test_trend_norm.py:86:        ResourceWarning: unclosed file …
test_zygote_stealth_write.py:89: ResourceWarning: unclosed file …
```

### 为什么这不只是"吵"

`ResourceWarning` 是 CPython 在**文件对象被 GC 时仍未关闭**才发的。
本仓库要在 macOS 上扫 5 万个 smali + 500 个 .kt ——
`hook_vocab.py` 的注释已经为这件事专门处理过一次（句柄泄漏 ⇒
`Too many open files`，macOS 默认 `ulimit -n` 只有 256）。

一条 ResourceWarning 意味着：**那段代码依赖引用计数才恰好没出问题。**
换运行时、改 GC 行为、或者把循环体改异步，就会变成真故障。

### 判据

用 `-W error::ResourceWarning` 跑一遍测试发现，**零告警**才算过。
（`unittest discover` 默认不把 warning 当错误，所以平时看不见。）

### 退出码

0 = 零告警；1 = 有。
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    p = subprocess.run(
        [sys.executable, '-W', 'error::ResourceWarning', '-m', 'unittest',
         'discover', '-s', os.path.join(ROOT, 'kit', 'python', 'tests'), '-q'],
        capture_output=True, text=True, timeout=1200, cwd=ROOT)
    err = (p.stderr or '') + (p.stdout or '')
    hits = [l for l in err.splitlines() if 'ResourceWarning' in l]
    print(f'[unclosed] ResourceWarning：{len(hits)} 条')
    for h in hits[:8]:
        print(f'  ✗   {h.strip()[:110]}')
    if hits:
        print('[unclosed]   修法：`with open(...) as f:`。裸 `open(...).read()` '
              '依赖引用计数才恰好关闭 —— 换运行时就是句柄泄漏。')
        print('[unclosed]   macOS 默认 `ulimit -n` 只有 256，而本仓库要扫 5 万个文件。')
        return 1
    if p.returncode != 0:
        print(f'[unclosed] 测试本身失败了（rc={p.returncode}）—— 那不是本门禁的判据，'
              '但也不该绿')
        return 1
    if a.verbose:
        print('[unclosed] 零 ResourceWarning ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
