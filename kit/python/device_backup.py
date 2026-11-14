#!/usr/bin/env python3
"""
kuaidui-kit / device_backup.py — **删设备上的抓取之前，先拉一份到本地**。

### 为什么需要

2026-11-03 代码审查 P1：

> 破坏性：`coldstart_snapshot.py:50` / `path_diff.py:49` `rm -f` 设备上的累积抓取（不备份）

两个脚本都要"只看这一次冷启动写了什么"，于是 `rm -f` 掉设备上的
`kdkit_capture.txt`。用意没错，但那个文件是**不可再生的证据** ——
它是几轮乃至几天积累下来的抓取行，删了就没了。

模块自己只保留一代轮转（`.prev.txt`），所以 `rm -f` 之后最近一代还在，
但**当前累积的那一份彻底消失**。如果某一轮先跑了 `path_diff` 而没跑
`evidence_pack`，那一段证据就永久丢了。

### 用法

```python
from device_backup import backup_capture
backup_capture('emulator-5558')          # 拉一份，返回本地路径（或 None）
```

落点：`work/device_backups/<serial>/<UTC 时间戳>/kdkit_capture.txt`。
**不覆盖、不清理** —— 由 `disk_audit.py` 盯着体积（门禁 ㉓），
不在这里偷偷做保留策略。

幂等：重复调用会各自生成一个带时间戳的目录，不会互相覆盖。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
from device import PKG as PKG_CONST
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
CAP = f'/data/data/{PKG}/files/kdkit_capture.txt'
PREV = CAP[:-4] + '.prev.txt'
BACKUP_ROOT = os.path.join(ROOT, 'work', 'device_backups')


def _sh(argv, timeout=180):
    import subprocess
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except Exception as e:                                  # noqa: BLE001
        return 124, f'{type(e).__name__}: {e}'


def pull(serial, device_path):
    """把设备上的一个文件读成字符串（读不到给空串）。"""
    rc, out = _sh(['adb', '-s', serial, 'shell', f'cat {device_path} 2>/dev/null'])
    return out if rc == 0 else ''


def backup_capture(serial, verbose=True):
    """拉一份当前抓取（含 `.prev.txt`）到本地，返回目录；什么都没有给 None。

    **两代都拉**：模块轮转时把当前累积挪去 `.prev.txt`，只拉当前那一份会漏掉
    边界两侧的行 —— 与 `verify_membership.pull_capture` 同一个理由。
    """
    cur, prev = pull(serial, CAP), pull(serial, PREV)
    if not cur.strip() and not prev.strip():
        if verbose:
            print(f'[backup] 设备 {serial} 上没有抓取可备份（本来就没写过？）')
        return None
    # **目录必须唯一**（2026-11-03 修）：第一版用秒级时间戳 + `exist_ok=True`，
    # 同一秒内调两次就落进同一个目录、**静默覆盖上一份**。
    # 一个会覆盖的备份比没有备份更糟 —— 它给人"已经留底了"的错觉。
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    outdir = os.path.join(BACKUP_ROOT, serial, stamp)
    n = 2
    while os.path.isdir(outdir):
        outdir = os.path.join(BACKUP_ROOT, serial, f'{stamp}_{n}')
        n += 1
    os.makedirs(outdir)
    lines = 0
    for name, body in (('kdkit_capture.txt', cur), ('kdkit_capture.prev.txt', prev)):
        if body.strip():
            with open(os.path.join(outdir, name), 'w', encoding='utf-8') as f:
                f.write(body)
            lines += body.count('\n')
    if verbose:
        print(f'[backup] {serial} 的抓取已备份到 {os.path.relpath(outdir, ROOT)}'
              f'（{lines} 行）—— 现在可以安全 rm -f 了')
    return outdir


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: device_backup.py <serial>')
        sys.exit(2)
    sys.exit(0 if backup_capture(sys.argv[1]) is not None or True else 1)
