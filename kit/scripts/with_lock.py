#!/usr/bin/env python3
"""
kuaidui-kit / with_lock.py — 给"会改仓库或碰设备"的命令套一把跨进程互斥锁。

为什么需要（2026-11-09 实测）
────────────────────────
同一秒里可能有两条链在跑：人工会话的 `verify.sh`、自动任务的
`run_negative_controls.py`（它**会临时改源码**来证明门禁能红）、以及 `acceptance.py`（碰设备）。
后两者与门禁交错时，门禁会读到**注入态**并假红 —— 实测一次性让
①b / ㉨ / ㉩ / ㉪ / ㉫ / ㉬ 六道门同时变红，看起来像"代码坏了"，其实是**两个进程在互相踩**。

而且这是"假红"里最贵的一种：它训练人忽略门禁。

**macOS 没有 `flock`**（那是 util-linux）—— 所以这里用 `fcntl.flock`，一条命令跨平台。

判据（纪律）
  * 会 `git`/改源码/注入负对照/跑门禁/装设备/跑验收 ⇒ **必须**套锁
  * 只读（读 STATE、静态分析、算哈希）⇒ 不必

    python3 kit/scripts/with_lock.py -- bash module/scripts/verify.sh
    python3 kit/scripts/with_lock.py --timeout 300 -- python3 kit/scripts/acceptance.py --adb emulator-5558 --live
    python3 kit/scripts/with_lock.py --wait 0 -- <cmd>     # 拿不到就立刻退 3（只读降级用）
    python3 kit/scripts/with_lock.py --status               # 谁在持有锁（诊断用）

退出码：命令自己的 rc；拿不到锁 ⇒ **3**（调用方据此写"因锁未执行"）。

重入（2026-11-09 04:0x 修 —— 这是一次**真死锁**，不是理论风险）
────────────────────────
事故现场：`with_lock --label r3-nd2 -- bash verify.sh` 拿到锁后，`verify.sh` 自己也
"自锁"（`exec with_lock … -- bash verify.sh`）⇒ **子进程等父进程的锁，永远等不到**。
实测两条链都这样卡住：`work/program/verify_r3.log` 只有一行
`[lock] 持有 …：r3-final2`，**一道门都没跑**，于是"最终验证"其实从未发生。

所以锁必须**可重入**：持锁进程把 `KD_LOCK_HELD=<锁的 realpath>` 传进子进程环境，
同一条链里再套一次 `with_lock`（或 `verify.sh` / `run_negative_controls.py` 自锁）时
**直接继承、不再获取**。跨链仍互斥（不同进程树的 `KD_LOCK_HELD` 不同）。

同时写 `<锁>.owner`（pid/label/起跑时间/命令），让"等锁"的一方能看到**谁**在跑，
而不是盲等 30 分钟后只能写一句"因锁未执行"。
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time

DEFAULT_LOCK = '/tmp/kdkit/run.lock'


def _owner_path(lock):
    return lock + '.owner'


def _pid_alive(pid):
    """owner 文件里可能是**已被 kill 的进程**（2026-11-09 04:13 实测：
    持锁进程被外部 SIGTERM 掉，`finally` 没跑 ⇒ owner 残留、锁已释放）。
    诊断输出必须能区分"现在有人在跑"与"这是具尸体"，否则 `--status` 会骗人。"""
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:          # 进程存在但属于别人 ⇒ 活着
        return True


def _read_owner(lock):
    try:
        with open(_owner_path(lock), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_owner(lock, label, cmd):
    rec = {'pid': os.getpid(), 'label': label,
           'since': time.strftime('%Y-%m-%d %H:%M:%S'),
           'cmd': ' '.join(cmd)[:400]}
    try:
        with open(_owner_path(lock), 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False)
    except OSError as e:
        # 诊断文件写不进去不能挡住正事，但要出声（㉬ 的口径：不许静默）
        print(f'[lock] 写 owner 失败：{e}', file=sys.stderr)
    return rec


def _clear_owner(lock, pid):
    """只清自己写的那份，别把下一个持锁者的 owner 删了。"""
    cur = _read_owner(lock)
    if cur and cur.get('pid') == pid:
        try:
            os.unlink(_owner_path(lock))
        except OSError as e:
            print(f'[lock] 清 owner 失败：{e}', file=sys.stderr)


def _run(cmd, run_timeout):
    try:
        return subprocess.run(cmd, timeout=run_timeout).returncode
    except subprocess.TimeoutExpired:
        print(f'[lock] 命令超 {run_timeout}s 仍未结束 ⇒ 中止（子系统卡死？）',
              file=sys.stderr)
        return 124


def main(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--lock', default=DEFAULT_LOCK)
    ap.add_argument('--timeout', type=int, default=1800, help='等锁秒数，默认 1800')
    ap.add_argument('--label', default='', help='日志里显示是谁在跑')
    # **被子命令也必须有界**（2026-11-09 修 ㉒）：
    # 这把锁包住的命令可能是 `verify.sh`（实测 ~1050s），但"慢"与"卡死"
    # 之间必须有一个人为上限，否则"还在跑"永远无法与"僵尸"区分（方法纪律 9）。
    # 2 小时 = 全量 verify 的 ~7 倍余量；超过就不是在跑。
    ap.add_argument('--run-timeout', type=int, default=7200,
                    help='被包住命令的墙钟上限秒数（默认 7200）')
    ap.add_argument('--status', action='store_true',
                    help='只打印当前 owner 并以 0 退出（不获取锁）')
    ap.add_argument('cmd', nargs=argparse.REMAINDER)
    a = ap.parse_args(argv[1:])

    if a.status:
        cur = _read_owner(a.lock)
        held = True
        try:
            fh = open(a.lock, 'a+')
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                held = False
            finally:
                fh.close()
        except OSError:
            held = True
        alive = _pid_alive(cur['pid']) if cur else None
        print(json.dumps({'lock': a.lock, 'held': held, 'owner': cur,
                          'owner_alive': alive}, ensure_ascii=False))
        if cur and not alive:
            print(f'[lock] owner 是残留（pid {cur["pid"]} 已不存在）'
                  f'；锁本身 {"仍被持有" if held else "空闲"}', file=sys.stderr)
        return 0

    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == '--' else a.cmd
    if not cmd:
        print('usage: with_lock.py [--lock P] [--timeout S] -- <cmd ...>', file=sys.stderr)
        return 2

    real = os.path.realpath(a.lock)

    # ── 重入：父进程（同一条链）已经持有这把锁 ⇒ 直接跑，不再获取 ──────────
    held_by_ancestor = os.environ.get('KD_LOCK_HELD')
    if held_by_ancestor and os.path.realpath(held_by_ancestor) == real:
        print(f'[lock] 继承同链的锁（不再重复获取）：{a.lock}', file=sys.stderr)
        return _run(cmd, a.run_timeout)

    os.makedirs(os.path.dirname(a.lock), exist_ok=True)
    fh = open(a.lock, 'a+')
    deadline = time.time() + max(a.timeout, 0)
    got = False
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
            break
        except OSError:
            if time.time() >= deadline:
                break
            time.sleep(1)
    if not got:
        cur = _read_owner(a.lock)
        if cur and _pid_alive(cur.get('pid')):
            who = (f"{cur.get('label')}（pid {cur.get('pid')}，起 {cur.get('since')}）")
        elif cur:
            who = (f"owner 文件残留（pid {cur.get('pid')} 已不存在 ⇒ 可能是刚被 kill 的链）")
        else:
            who = 'owner 未知（可能是旧版 with_lock 或刚启动）'
        print(f'[lock] 等锁 {a.timeout}s 未拿到：{a.lock}；当前持有者：{who}',
              file=sys.stderr)
        fh.close()
        return 3

    label = a.label or ' '.join(cmd[:3])
    print(f'[lock] 持有 {a.lock}：{label}', file=sys.stderr)
    _write_owner(a.lock, label, cmd)
    env = dict(os.environ)
    env['KD_LOCK_HELD'] = real          # ← 子进程据此知道"锁已在手"，避免自锁死锁
    env['KD_LOCK_LABEL'] = label
    try:
        try:
            return subprocess.run(cmd, timeout=a.run_timeout, env=env).returncode
        except subprocess.TimeoutExpired:
            print(f'[lock] 命令超 {a.run_timeout}s 仍未结束 ⇒ 中止（子系统卡死？）',
                  file=sys.stderr)
            return 124
    finally:
        _clear_owner(a.lock, os.getpid())
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
