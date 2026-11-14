#!/usr/bin/env python3
"""
kuaidui-kit / check_negctl_leftovers.py — 负对照的"注入态"不许留在树上过夜。

### 为什么需要（2026-11-05 → 11-09，三天假通过）

`run_negative_controls.py` 的做法是：把某个源文件原地改成"故意坏"的版本
（例如 `kit/python/kd_api.py` 里的 `bad = []`），跑一遍目标门禁，再从
`<文件>.negctl.bak` 还原。

问题出在"跑完还原"这一步**只在跑负对照时发生**。11-05 有一轮被强杀，
留下了 `kit/python/kd_api.py.negctl.bak`，而 `kd_api.py` 一直是注入态。
于是 P1 校验（"blob 长度对但内容是乱码"）**三天都在假通过** ——
它不是红的，它是**绿得不对**。唯一症状是四条单测红，而那四条与病状不像。

### 这个门禁最难的一处：**"正在跑"与"崩了"在文件系统上长得一样**

两者都是一对 `<x>` + `<x>.negctl.bak`。2026-11-09 02:25 实测撞上过：
另一条链的 ㉖ 正在注入，此时"扫残留"会**假红** 40 秒。

所以判据加一条前提：`kit/python/negctl_state.py` 的**在跑标记**
（`work/.negctl.inflight`，pid + 开始时间）。规则：

| 看到什么 | 结论 |
|---|---|
| 没有标记、有 `.bak` | **红**：上一轮没有善终（被打断 / 崩了 / 忘了还原） |
| 有标记、pid 还活着且未陈旧、有 `.bak` | **等**（最多 `--wait` 秒）—— 另一条链正在跑，`finally` 还没到 |
| 等过 `--wait` 仍在跑 | 退出码 2 = **无法验证**（不算红，也不算绿） |
| 有标记、pid 已死（或陈旧）、有 `.bak` | **红**，并说明"上一次倒在中途，标记也没清" |
| 有标记但读不出 | 退出码 2：标记损坏，无从判定 |

`.bak` 对应的源文件**不存在** ⇒ 单独标出来：那不是"没还原"，是**源文件被吞了**，
比注入态更糟（`work/METHODOLOGY.md` §7「只归档不删证据」）。

`work/archive/` 不扫：那里是归档证据，允许包含历史文件名
（"不删证据"与"活代码树干净"是两件事，别用一个判据混起来）。

### 退出码

0 = 无残留；1 = 有残留（或源文件缺失）；2 = 无法验证（另一条链在跑 / 标记损坏）。

    python3 kit/scripts/check_negctl_leftovers.py
    python3 kit/scripts/check_negctl_leftovers.py --root /tmp/tree --wait 0   # 自测用
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import negctl_state  # noqa: E402  （路径先于导入：kit/python 不在默认 sys.path）

#: 负对照注入器只会动这两棵树（见 run_negative_controls.py 的 `bak()`）。
TREES = ('kit', 'module')
#: 注入不会发生在这些子目录里；`.git` / `__pycache__` 里出现同名文件是噪声不是注入。
SKIP_DIRS = {'.git', '__pycache__'}
SUFFIX = '.negctl.bak'


LOCK = '/tmp/kdkit/run.lock'


def negctl_owns_lock(lock=LOCK):
    """锁现在是**负对照**在持有吗？（判据是 `with_lock` 写的 owner 记录）

    2026-11-09 04:54 实测一次**假红**：另一条链正在注入，`.bak` 在、标记文件却
    正好不可读（读到了不存在 / 空文件）⇒ 本门禁把它读成"上一轮倒在中途" ⇒ rc=1。
    而真相是"另一条链正在跑"。假红比不红贵：它训练人忽略门禁。

    `KD_NEGCTL` 环境变量跨不了进程层，但 `with_lock.py` 的 owner 文件跨得了 ——
    所以用"锁的持有者是谁"来判，而不是再猜一次标记。
    """
    path = lock + '.owner'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            import json
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    cmd = str(rec.get('cmd') or '')
    label = str(rec.get('label') or '')
    if 'run_negative_controls' in cmd or 'negctl' in label:
        try:
            os.kill(int(rec.get('pid')), 0)
            return rec
        except (ProcessLookupError, ValueError, TypeError):
            return None
        except PermissionError:
            return rec
    return None


def scan(root=ROOT):
    """返回残留列表；每项带 `bak` / `live` / `live_exists` 三个字段。

    `live_exists` 为 False 是**更严重的那一类**：备份还在、源文件没了 ——
    此时"还原"这个动作本身也无从谈起。
    """
    hits = []
    for tree in TREES:
        base = os.path.join(root, tree)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if not fn.endswith(SUFFIX):
                    continue
                bak = os.path.join(dirpath, fn)
                live = bak[:-len(SUFFIX)]
                hits.append({
                    'bak': os.path.relpath(bak, root),
                    'live': os.path.relpath(live, root),
                    'live_exists': os.path.exists(live),
                })
    return sorted(hits, key=lambda h: h['bak'])


def wait_for_idle(marker, wait_s, poll_s=2.0):
    """等"另一条链"跑完。返回 True = 已经空闲；False = 仍在跑（超时）。"""
    deadline = time.time() + max(wait_s, 0)
    while True:
        if negctl_state.active_pid(marker) is None:
            return True
        left = deadline - time.time()
        if left <= 0:
            return False
        time.sleep(min(poll_s, left))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='负对照残留（*.negctl.bak）不许留在 kit/ 与 module/ 里')
    ap.add_argument('--root', default=ROOT,
                    help='要扫描的树根（自测时指向临时目录）')
    ap.add_argument('--marker', default=negctl_state.MARKER,
                    help='"正在跑"标记文件（默认 work/.negctl.inflight）')
    ap.add_argument('--wait', type=int, default=120,
                    help='另一条链正在跑时最多等多少秒（默认 120；0 = 不等）')
    ap.add_argument('--quiet', action='store_true', help='干净时不打印结论')
    ap.add_argument('--lock', default=LOCK,
                    help='with_lock 的锁文件（读它的 .owner 判断"谁在跑"；自测用）')
    a = ap.parse_args(argv)

    if not wait_for_idle(a.marker, a.wait):
        owner = negctl_state.active_pid(a.marker)
        print(f'[negctl] 另一条链正在跑负对照（pid={owner}），等 {a.wait}s 仍未结束 '
              '⇒ **本轮无法验证**（不是红；别据此判断代码好坏）', file=sys.stderr)
        return 2

    hits = scan(a.root)
    marker = negctl_state.read_marker(a.marker)
    if marker and marker.get('corrupt'):
        print(f'[negctl] **"正在跑"标记读不出**：{a.marker} ⇒ 无法判定"崩了"还是"正在跑"',
              file=sys.stderr)
        return 2

    # 标记看丢了的空窗：另一条链**确实**在跑负对照（锁的 owner 是它）⇒ 无法验证。
    # 没有这一条时，注入窗口会被读成"残留"⇒ 假红（2026-11-09 04:54 实测一次）。
    owner = negctl_owns_lock(a.lock)
    if owner is not None and scan(a.root):
        print(f'[negctl] 另一条链正在跑负对照（pid={owner.get("pid")}，'
              f'起 {owner.get("since")}）⇒ **无法验证**（不是红；别据此判断代码好坏）',
              file=sys.stderr)
        return 2

    if not hits:
        if marker:
            print('[negctl] 无 *.negctl.bak 残留，但**上一次的标记还在**'
                  f'（{a.marker}）——进程正常退出的路径没清标记，值得查一下')
        if not a.quiet:
            print('[negctl] 无 *.negctl.bak 残留（kit/ + module/）——注入态没有过夜')
        return 0

    print(f'[negctl] **发现 {len(hits)} 个负对照残留** —— 上一轮没有善终：')
    swallowed = 0
    for h in hits:
        if h['live_exists']:
            note = ''
        else:
            note = '  ← **源文件不存在**（注入态把文件吞了）'
            swallowed += 1
        print(f'   {h["bak"]}   （源 {h["live"]}）{note}')
    if marker:
        print('  另外：`work/.negctl.inflight` 还在，但持有它的进程已经死了 —— '
              '**这就是"倒在中途"的形状**（`SIGKILL` 不会执行 `finally`）。')
    print('  修法：先 `cp <bak> <live>` 还原，再删 .bak —— 别把注入态当正常态读。')
    if swallowed:
        print(f'  **其中 {swallowed} 个连源文件都没了**：从 work/archive 或快照恢复，'
              '不要直接删备份。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
