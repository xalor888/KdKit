#!/usr/bin/env python3
"""
kuaidui-kit / device_health.py — 30 秒内回答"这台设备还能用吗"。

动机（2026-10-11 实测）：设备显示管线卡死时，`screencap` 会**无限挂**，一个后台证据包因此卡了 20 分钟才被发现；
症状是 SystemUI 不见、logcat 有 binder ENOSPC。把它做成**有界的前置检查**：先问健康，再跑贵的东西。

检查项：设备在线 / `/data` 剩余空间 / SystemUI 进程 / SystemUI 与启动器之外的关键进程 /
**限时 screencap 探针** / 模块是否注入过（只看日志最后一条 HookCore）。

    python3 kit/scripts/device_health.py --adb emulator-5558        # 人读
    python3 kit/scripts/device_health.py --adb emulator-5558 --quiet # 只给退出码（0 健康 / 2 警告 / 1 不可用）
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def sh(cmd, timeout=120):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=120):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def framework_alive(serial, timeout=20):
    """2026-10-13 新加：**框架层**是否活着 ✓。

    起因：第三次设备故障时 adbd 还活着（所以 `adb shell echo` 正常 ✗），
    但 `am start` 报 `Can't find service: activity` ✗ —— 而旧的健康检查只看 adbd 层 ⇒ **没抓到** ✗。
    判据：`pidof system_server` 有值 且 `cmd activity` 能回答 ✓。
    """
    try:
        r = subprocess.run(['adb', '-s', serial, 'shell',
                            'printf "%s|%s" "$(pidof system_server)" "$(cmd activity 2>&1 | head -1 | cut -c1-12)"'],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, 'framework probe timeout'
    out = (r.stdout or '').strip()
    pid, _, act = out.partition('|')
    if not pid.strip():
        return False, 'system_server 不在（框架已死 ✗）'
    if 'Activity man' not in act and 'ActivityManager' not in act:
        return False, f'cmd activity 无响应（{act.strip()[:30]} ✗）'
    return True, f'system_server={pid.strip()} ✓'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--screencap-timeout', type=int, default=20)
    a = ap.parse_args(argv[1:])

    problems, notes = [], []

    rc, st = sh(f'adb -s {a.adb} get-state')
    # get-state 成功时只输出一行 "device"/"offline"/"bootloader"；失败时是错误文本，
    # 所以必须**精确比对**，不能用 `'device' in st`（"not found" 里也含 device ✗）
    if st.strip() != 'device':
        print(f'[health] 设备不可用：{st.strip().splitlines()[0][:80] if st.strip() else "无输出"}')
        return 1

    # 2026-10-13 新加：**框架层**检查 —— adbd 活着不等于系统活着 ✗（第三次故障就是这样漏掉的）
    fw_ok, fw_msg = framework_alive(a.adb)
    if not fw_ok:
        print(f'[health] 框架层不健康：{fw_msg}')
        print('[health] ⇒ 按 ONBOARDING 的三步恢复：杀 qemu → 清 AVD 锁 → 带 magisk ramdisk 重启')
        return 2
    notes.append('设备在线')

    boot = adb(a.adb, 'getprop sys.boot_completed')[1].strip()
    if boot != '1':
        problems.append(f'尚未完成启动（sys.boot_completed={boot or "空"}）')

    free = adb(a.adb, "df -h /data | tail -1")[1].strip()
    m = re.search(r'(\d+)%', free)
    if m and int(m.group(1)) >= 90:
        problems.append(f'/data 快满（{free}）')
    notes.append(f'/data: {free[:60]}')

    sui = adb(a.adb, 'pidof com.android.systemui')[1].strip()
    if not sui:
        problems.append('SystemUI 不在（显示管线可能已卡 → adb reboot）')
    else:
        notes.append(f'SystemUI pid={sui}')

    # 有限时探针：卡住时这段会在 N 秒后放弃，而不是无限等
    probe = os.path.join(ROOT, 'work', '_health_probe.png')
    shot_ok = True
    try:
        # 同上：不用 bash 中间层（超时能真正杀掉 adb ✓）
        subprocess.run(['adb', '-s', a.adb, 'exec-out', 'screencap', '-p'], stdout=open(probe, 'wb'),
                       stderr=subprocess.DEVNULL,
                       timeout=a.screencap_timeout)
    except subprocess.TimeoutExpired:
        shot_ok = False
    if shot_ok and os.path.exists(probe) and os.path.getsize(probe) > 1000:
        notes.append(f'screencap ok（{os.path.getsize(probe)} B）')
    else:
        problems.append(f'screencap 异常（超时 {a.screencap_timeout}s 或输出过小）→ 设备显示管线卡了，adb reboot 后重跑 env_up.sh')
    try:
        os.remove(probe)
    except OSError:
        pass

    # Frida 通路：C4（反注入）依赖它。2026-10-12 实测 5556 上 system 半死时
    # `frida-ps` 报 DeadSystemRuntimeException，而 SystemUI/screencap 都是好的 —— 所以必须单独探。
    fr_pid = adb(a.adb, 'pidof xdsvc')[1].strip()
    if not fr_pid:
        notes.append('frida-server 未运行（设计如此也可以 —— 模块路线不依赖它）')
    else:
        # 先确保端口转发（转发是**按设备**记的；缺了它，健康设备也会被判成"通路不通" —— 实测踩过）
        sh(f'adb -s {a.adb} forward tcp:31337 tcp:31337')
        rc, fr = sh('frida-ps -H 127.0.0.1:31337 2>&1 | head -2', timeout=45)
        if 'DeadSystem' in fr or 'Failed to enumerate' in fr or 'unable to connect' in fr.lower():
            problems.append('frida 通路不通（' + fr.strip().splitlines()[-1][:60] + '）→ '
                            'C4/附加类实验在这台设备上无意义，先 adb reboot')
        else:
            notes.append('frida 通路正常')

    logs = adb(a.adb, 'ls -t /data/adb/lspd/log/modules_*.log 2>/dev/null | head -1')[1].strip()
    if logs:
        last = adb(a.adb, f'grep -ah "HookCore ready" {logs} | tail -1')[1]
        mm = re.search(r'HookCore ready \((\d+) features\)', last)
        notes.append(f'模块注入过：{mm.group(1)} 功能' if mm else '模块日志里没有 HookCore 记录')
    else:
        notes.append('没有模块日志（模块可能从未注入过）')

    if not a.quiet:
        print('[health] ' + ('；'.join(notes)))
        for p in problems:
            print('[health] 警告: ' + p)
    if not problems:
        return 0
    return 2 if (shot_ok and boot == '1') else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
