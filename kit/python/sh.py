#!/usr/bin/env python3
"""
kuaidui-kit / sh.py —— 带**进程组**超时的 shell 执行。

### 为什么不能只用 `subprocess.run(..., timeout=…)`

2026-11-02 实测（本地复现，`sleep 300 | cat` + `timeout=2`）：

```
timeout 触发了
泄漏的子进程: ['81619 sleep 300']        ← shell 被杀，孙子进程活着
```

`subprocess.run(shell=True, timeout=N)` 超时时**只杀 shell 本身**，
管道里的子进程（这里是 `adb`）继续活着 —— 于是：

* `timeout` 让**调用方**返回了，看起来"有界"；
* 但那个 `adb` 进程还在跑，可能永远挂着（设备不在线 / 显示管线卡了）；
* 下一轮再跑，又泄漏一个 ⇒ 机器上慢慢堆起一群僵掉的 `adb`。

本仓库已经为这个病加过一次 `timeout 25`（`verify_on_device.sh` 的 screencap），
但那只治了"等多久"，没治"杀干净"。**规则 9「超时要"有界"」的真正含义是两头都有界。**

### 做法

`start_new_session=True` 让子进程自成进程组；超时时 `os.killpg` 整组杀掉。
"""
import os
import re
import signal
import subprocess


def _as_shell(cmd):
    """把命令统一成**一条 shell 字符串**。

    **必须收 list**（2026-11-03 差点因此毁掉 acceptance）：
    那 12 个文件里的本地 `sh(cmd, …)` 一向是
    `subprocess.run(cmd, shell=isinstance(cmd, str), …)` ——
    **传 list 时不过 shell**，直接 exec。而本模块的 `Popen(shell=True)`
    对 list 会把第一个元素当命令串、其余当 `$0/$1…` ⇒ `adb` 收不到参数，
    于是打印自己的版本号，而 13 条真机断言**全部**变成
    `sdk=Android Debug Bridge version 1.0.41`。

    "同名不同契约"正是今天反复修的那一类：**合并实现时先问一遍
    两边各自接受什么、返回什么**，而不只是看函数体像不像。
    """
    if isinstance(cmd, (list, tuple)):
        return ' '.join(_quote(str(c)) for c in cmd)
    return cmd


def _quote(s):
    """按 shell 规则加引号；已经带引号或空串的不动。"""
    if s == '' or (s.startswith('"') and s.endswith('"')) \
            or (s.startswith("'") and s.endswith("'")):
        return s
    if re.fullmatch(r'[A-Za-z0-9_@%+=:,./-]+', s):
        return s                      # 无需引号
    return '"' + s.replace('"', '\\"') + '"'


def sh(cmd, timeout=120, cwd=None):
    """跑一条 shell 命令，超时**连进程组一起杀**，返回合并后的 stdout+stderr。"""
    p = subprocess.Popen(_as_shell(cmd), shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors='replace',
                         cwd=cwd, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
        return out or ''
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return ''


def run(cmd, timeout=120, cwd=None):
    """同 [sh]，但返回 `(returncode, output)`。超时返回 `(124, '')`。"""
    p = subprocess.Popen(_as_shell(cmd), shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors='replace',
                         cwd=cwd, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or ''
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return 124, ''
