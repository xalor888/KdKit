#!/usr/bin/env python3
"""
kuaidui-kit / memread.py — **通过 root 读一个活进程的内存**（`dd if=/proc/<pid>/mem`）。

### 为什么需要

2026-11-03 代码审查 P2：

> **root 读内存 3 份 3 种引号写法**（`mem_read:28` / `read_sign_inputs:37` / `find_sign_strings:38`）

三份不只是"写法不同"—— **其中只有一份有 `-w0` 的兜底**：

* `mem_read.py`：`base64 -w0` 失败时退回去试不带 `-w` 的 `base64`；
* `read_sign_inputs.py` / `find_sign_strings.py`：没有兜底。

于是换一台 `base64` 不支持 `-w`（某些 busybox）的设备时，
后两个脚本的 `read_mem` 会**静默返回 `b''`** ——
而 `b''` 与"那个地址确实没有字节"长得一模一样。
**调用方只会看到"没找到字符串"，查不到是环境问题。**

### 用法

```python
from memread import read_mem
data = read_mem(serial, pid, 0x72cc26c238, 384)
```

`read_mem` 返回 `b''` 只有一种含义：**两次尝试都没读出东西**。
想知道是哪一种失败，用 `read_mem_verbose()`，它把两次的 stderr 都带回来。
"""
import base64
import subprocess


def adb(serial, *args, timeout=90):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout)


def read_mem_verbose(serial, pid, addr, length):
    """返回 `(bytes, 说明)`。`说明` 为空表示顺利；否则解释为什么空。

    **两次尝试都要试**（2026-11-03 收敛时保留下来的行为）：
    `base64 -w0` 在 GNU coreutils 里有，某些 busybox 没有。
    只试一遍的版本在那种设备上会静默返回空。
    """
    def cmd(tool):
        return (f'dd if=/proc/{pid}/mem bs=1 skip={int(addr)} count={length} '
                f'2>/dev/null | {tool}')

    attempts = [
        ('base64 -w0', cmd('base64 -w0')),
        ('base64', cmd('base64')),          # 兜底：没有 -w 的实现
    ]
    last_err = ''
    for name, c in attempts:
        out = adb(serial, 'su', '-c', f'"{c}"')
        b64 = ''.join(out.stdout.split())
        if b64:
            try:
                return base64.b64decode(b64 + '=' * (-len(b64) % 4)), ''
            except Exception as e:                          # noqa: BLE001
                last_err = f'{name} 解出来不是 base64：{type(e).__name__}'
                continue
        last_err = f'{name} 无输出（stderr: {(out.stderr or "").strip()[:80]}）'
    return b'', last_err


def read_mem(serial, pid, addr, length):
    """读内存；`b''` 表示两次尝试都没读出东西（要看原因用 `read_mem_verbose`）。"""
    data, _why = read_mem_verbose(serial, pid, addr, length)
    return data
