#!/usr/bin/env python3
"""
kuaidui-kit / coldstart_snapshot.py — one page describing what the app does in its first N seconds.

A behavioural baseline: cold-start the app, watch for N seconds, and record the shape of that
window — how many requests it made, which bridge actions ran, how many ad slots it tried to read,
what the foreground activity was, and a screenshot. Run it again later and diff: that is how "the
app changed something at startup" becomes visible without re-deriving it.

    python3 kit/scripts/coldstart_snapshot.py --adb emulator-5558 [--seconds 30] [--out work/COLDSTART.md]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import capture_schema
import sh as _shmod
from device import PKG as PKG_CONST
import argparse
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
CAP = f'/data/data/{PKG}/files/kdkit_capture.txt'


def sh(cmd, timeout=900):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=900):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--seconds', type=int, default=30)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    outdir = os.path.join(ROOT, 'work', 'packs', 'coldstart_' + datetime.now().strftime('%H%M%S'))
    os.makedirs(outdir, exist_ok=True)

    # 清抓取文件（只看这一次冷启动写了什么）
    # **删之前先备份**（2026-11-03 修）：设备上的抓取是不可再生证据，
    # `rm -f` 一删就没了。代码审查 P1 点名了这两处。
    sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
    from device_backup import backup_capture
    backup_capture(a.adb)
    adb(a.adb, f'am force-stop {PKG}')
    adb(a.adb, f'rm -f {CAP}')
    t0 = time.time()
    adb(a.adb, f'am start -n {PKG}/.AliasActivityDefault')
    first_act = ''
    for _ in range(20):
        act = adb(a.adb, 'dumpsys activity activities | grep -m1 -o "u0 [a-zA-Z0-9._/]*"')[1].strip()
        if act:
            first_act = act
            break
        time.sleep(0.5)
    time.sleep(a.seconds)
    last_act = adb(a.adb, 'dumpsys activity activities | grep -m1 -o "u0 [a-zA-Z0-9._/]*"')[1].strip()
    cap = adb(a.adb, f'cat {CAP}')[1]
    open(os.path.join(outdir, 'capture.txt'), 'w').write(cap)
    shot = os.path.join(outdir, 'screen.png')
    shot_ok = True
    try:
        # 有界：设备显示管线卡住时 screencap 会无限挂（2026-10-11 实测），
        # 所以限 30 秒，且失败只记一笔，不让整包失败。
        # 2026-10-13 修：原来走 `bash -c '… > file'` ⇒ 超时只杀 bash ✗，adb 活着握住管道 ⇒ 上层永久阻塞 ✗
        with open(shot, 'wb') as _f:
            subprocess.run(['adb', '-s', a.adb, 'exec-out', 'screencap', '-p'],
                           stdout=_f, stderr=subprocess.DEVNULL, timeout=30)
    except subprocess.TimeoutExpired:
        shot_ok = False
        print('[cold] screencap 超时（设备显示管线可能卡了：systemui 不在 / logcat 有 binder ENOSPC）')
    logs = adb(a.adb, 'ls -t /data/adb/lspd/log/modules_*.log | head -1')[1].strip()
    modlog = adb(a.adb, f'tail -400 {logs}')[1]
    # "启用了什么"要看**最近一次启动**块里的 feature 行（日志是跨多次启动累积的）
    feat_lines = adb(a.adb, f"grep -a 'feature on:' {logs} | tail -18")[1]
    modlog += '\n# ---- last-start feature lines ----\n' + feat_lines
    open(os.path.join(outdir, 'module_log_tail.txt'), 'w').write(modlog)

    urls = capture_schema.sign_urls(cap.splitlines())
    hosts = Counter(urllib.parse.urlparse(u).netloc for u in urls if '://' in u)
    bridge = Counter(m.group(1) for m in re.finditer(r'H5BRIDGE (\S+) count=', cap))
    slot_reads = len(re.findall(r'blocked ad slot read', modlog)) + len(re.findall(r'ADSLOT call', cap))
    feats = sorted(set(re.findall(r'feature on: (\S+)', feat_lines)))

    out = [f'# 冷启动行为快照（{a.seconds} 秒窗口）', '',
           f'* 设备 `{a.adb}`；生成 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
           f'* 起始 Activity：`{first_act or "-"}`', f'* 结束时前台：`{last_act or "-"}`', '',
           '| 指标 | 值 |', '|---|---|',
           f'| 该窗口请求数（签名 URL） | {len(urls)} |',
           f'| 请求到的 host | ' + (', '.join(f'`{h}`×{n}' for h, n in hosts.most_common(5)) or '-') + ' |',
           f'| H5 桥调用 | {sum(bridge.values())} 次 / {len(bridge)} 个 action |',
           f'| 广告位读取（拦截 + 观测） | {slot_reads} |',
           f'| 日志中启用的功能 | {len(feats)} 个 |',
           f'| 截图 | ' + (f'`{os.path.relpath(shot, ROOT)}`' if shot_ok else '**取不到（screencap 超时）**') + ' |', '',
           '## 桥 action 明细', '']
    for act, n in bridge.most_common(12):
        out.append(f'* `{act}` × {n}')
    out += ['', '**用法**：过一段时间再跑一次，对比"请求数/host/桥 action/广告位读取"这几行 —— '
            'App 改版或服务端改行为时，这张表会先变。', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'COLDSTART.md')
    open(target, 'w').write(text)
    print(f'[cold] {outdir}')
    print('\n'.join(out[5:16]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
