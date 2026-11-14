#!/usr/bin/env python3
"""
kuaidui-kit / negctl_state.py — 负对照"正在跑"的**唯一**标记（跨进程）。

### 为什么需要（2026-11-09 实测）

`run_negative_controls.py` 会把源码临时改成注入态、跑一次门禁、再还原。
所以**同一秒里**问"`kit/python/kd_api.py` 现在是注入态吗？"，
答案取决于另一个进程在哪一步 —— 2026-11-09 02:25 实测：

    kd_api.py          33933 字节，含 `bad = []   # 负对照：故意永不报错`
    kd_api.py.negctl.bak 33958 字节（= 干净版）

那 40 秒里，任何"扫残留"的门禁都会**假红**：看起来像上一轮崩了，
其实只是另一条链正跑到第 3 步。假红是门禁最贵的一种失败 —— 它训练人忽略门禁。

反过来，`SIGTERM`（`timeout`、Ctrl-C）**不会执行 `finally`**，
所以"真的崩了"和"正在跑"在文件系统上长得一模一样：都是一对 `.bak` + 活文件。

### 判据：靠标记 + 进程存活，不靠猜测

* 跑之前写 `work/.negctl.inflight`（pid + 开始时间 + 用例名）；
* 正常退出时 `atexit` 删掉它；
* 被 `SIGKILL` / `SIGTERM` 打断 ⇒ 标记留下 ⇒ **下一个读它的人能区分"崩了"**；
* 标记超过 `STALE_AFTER_S` ⇒ 一律当陈旧（防 pid 复用把死进程看活）。

这个模块只做标记的读写与判定；"红了要怎么办"留给调用方。

### 用法

```python
from negctl_state import write_marker, clear_marker, active_pid
```
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

#: 标记文件。放在 `work/` 里：那是本仓库唯一"可以随时写"的地方。
MARKER = os.path.join(ROOT, 'work', '.negctl.inflight')
#: 超过这个时长仍存在 ⇒ 当陈旧。默认 30 分钟：全量负对照实测 ~730s，
#: 留四倍余量；再长就不可能是"还在跑"，只可能是"倒在中途"。
STALE_AFTER_S = 30 * 60


def pid_alive(pid):
    """进程是否还活着。`PermissionError` 也算活（别人的进程看不见而已）。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def write_marker(cases=(), path=MARKER, pid=None, started=None, paths=()):
    """写标记。先写临时文件再 rename ⇒ 读的一方永远看不到半截 JSON。

    `paths` 是**这次运行会动的源文件**（相对仓库根）。有了它，自愈可以只跳过
    "别人正在注入的那几个文件"，而不是把整棵树的自愈都停掉。
    """
    data = {
        'pid': os.getpid() if pid is None else pid,
        'started': time.time() if started is None else started,
        'cases': list(cases),
        'paths': list(paths),
    }
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    return data


def read_marker(path=MARKER):
    """读标记。不存在 ⇒ None；存在但读不出 ⇒ 带 `corrupt: True` 的占位。

    **不抛异常**：这个函数被门禁调用，门禁不该因为标记损坏而崩
    （那会让"门禁坏了"和"标记坏了"混成同一件事）。
    """
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {'pid': None, 'started': None, 'cases': [], 'paths': [], 'corrupt': True}
    if not isinstance(data, dict):
        return {'pid': None, 'started': None, 'cases': [], 'paths': [], 'corrupt': True}
    out = {
        'pid': data.get('pid'),
        'started': data.get('started'),
        'cases': data.get('cases') or [],
        'paths': data.get('paths') or [],
    }
    if data.get('corrupt'):
        out['corrupt'] = True
    return out


def clear_marker(path=MARKER):
    """删标记；本来就没有也算成功（幂等）。"""
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    return True


def active_pid(path=MARKER, now=None):
    """**正在跑**的负对照 pid；None = 没有活跃运行（不存在 / 陈旧 / 进程已死 / 损坏）。"""
    m = read_marker(path)
    if not m or m.get('corrupt') or not m.get('pid'):
        return None
    started = m.get('started') or 0
    at = time.time() if now is None else now
    if started and at - started > STALE_AFTER_S:
        return None
    return m['pid'] if pid_alive(m['pid']) else None
