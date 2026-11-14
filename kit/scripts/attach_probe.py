#!/usr/bin/env python3
"""
kuaidui-kit / attach_probe.py — anti-instrumentation probe.

Attaches a (possibly empty) Frida agent to 快对 and measures **how long the
process survives**, plus how it died. This is the measurement that decides
whether the anti-instrumentation layer is neutralised: an unpatched install dies
in ~1 s with `VM exiting with result code 0`.

    python3 attach_probe.py --adb emulator-5556 --pkg com.kuaiduizuoye.scan \
        --seconds 20 [--script hook.js] [--out work/dpsdk/probe1.json]

Modes
  * default      attach to the running pid;
  * --relaunch   force-stop + launch first (--settle N waits before attaching);
  * --spawn      let frida-server spawn the app and load the agent *before* any
                 app code runs — the only way to hook a check that fires early.
                 Under spawn the process is stopped until `device.resume()`.

Notes
  * the pid is tracked through `adb shell pidof` — frida's own enumeration is
    unreliable on this image (see kit/README.md §2);
  * `--script` is optional: attaching *with nothing* is the purest probe;
  * logcat is captured around the attach and scanned for the death signature.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
from device import PKG as DEFAULT_PKG
import argparse
import json
import subprocess
import sys
import time

import frida

DEATH_SIGNS = [
    'VM exiting with result code',
    'Fatal signal',
    'libc: Fatal',
    'Exiting immediately',
    'tombstone',
    'exited cleanly',
]


def adb(serial, *args, timeout=30):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout).stdout.strip()


def pidof(serial, pkg):
    out = adb(serial, 'pidof', pkg)
    for tok in out.split():
        if tok.isdigit():
            return int(tok)
    return None


def launch(serial, pkg):
    """Start the app through its resolved launcher component (the manifest has
    11 launcher aliases; only the one resolved here is enabled on this build)."""
    out = adb(serial, 'cmd', 'package', 'resolve-activity', '--brief',
              '-c', 'android.intent.category.LAUNCHER', pkg)
    comp = [l.strip() for l in out.splitlines() if '/' in l]
    if comp:
        adb(serial, 'am', 'start', '-n', comp[-1])
    else:  # fall back to monkey
        adb(serial, 'monkey', '-p', pkg, '-c', 'android.intent.category.LAUNCHER', '1')
    for _ in range(80):
        p = pidof(serial, pkg)
        if p:
            return p
        time.sleep(0.5)
    return None


def get_device(spec):
    """host:port -> a frida-server behind `adb forward`; anything else is a USB id."""
    if ':' in spec:
        return frida.get_device_manager().add_remote_device(spec)
    return frida.get_device(spec, timeout=10)


def stable_pid(serial, pkg, tries=12, interval=1.5):
    """解析一个**稳定的** pid：连续两次读到同一个才算数。

    2026-10-12 实测：应用启动/重启窗口里 `pidof` 会瞬时返回空或旧值，
    导致"附加时找不到进程"，进而被判成"反注入在起作用" —— 这是采样问题，不是行为问题。
    """
    last = None
    for _ in range(tries):
        cur = subprocess.run(['adb', '-s', serial, 'shell', f'pidof {pkg}'],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        if cur and cur == last:
            return cur
        last = cur or None
        time.sleep(interval)
    return None


def ensure_frida_server(serial):
    """重启后 `xdsvc` 不会自己起；附加失败时"进程存活"是**假结论**（没有插桩发生）。
    这里先确保它在跑，并把结果记进输出，避免把"没插上"读成"活下来了"。"""
    pid = subprocess.run(['adb', '-s', serial, 'shell', 'pidof xdsvc'],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    if pid:
        return True
    subprocess.run(['adb', '-s', serial, 'shell',
                    'nohup /data/local/tmp/xdsvc >/dev/null 2>&1 &'], capture_output=True, timeout=60)
    time.sleep(4)
    pid = subprocess.run(['adb', '-s', serial, 'shell', 'pidof xdsvc'],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return bool(pid)


def survived_of(attach_error, died_at):
    """`survived` 只对"真的插上了"有意义。

    旧实现无条件写 `died_at is None`。于是"附加失败、进程仍在"被记成
    `survived: true` —— 读起来像"它扛住了反注入"，而真相是
    **我们根本没碰它**，它当然活着。

    这与"报告成功但不验证"是同一类：一个字段声称了一个它没测量过的结论。
    现在：没插上就给 `None`（未测），消费者必须把 None 当"不知道"，
    而不是当"存活"。（`verdict` 字段早就把三种情况分开了，是 `survived` 没跟上。）

    提成函数是为了**能离线测** —— 附加失败那条路在真机上很难构造
    （需要一个 frida 插不进去的活进程），而这个推导本身必须被证明是对的。
    """
    return None if attach_error else died_at is None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--no-ensure-frida', action='store_true',
                    help='不自动确保 frida-server 在跑（默认会确保，避免把"没插上"读成"活下来"）')
    ap.add_argument('--pkg', default=DEFAULT_PKG)
    ap.add_argument('--device', default='127.0.0.1:31337',
                    help='frida remote device (host:port of the forwarded frida-server)')
    ap.add_argument('--seconds', type=float, default=20.0)
    ap.add_argument('--script', action='append', default=[])
    ap.add_argument('--out', default=None)
    ap.add_argument('--relaunch', action='store_true',
                    help='force-stop + am start the app before attaching')
    ap.add_argument('--spawn', action='store_true',
                    help='let frida spawn the app so the agent predates every app hook')
    ap.add_argument('--settle', type=float, default=0.0,
                    help='seconds to wait after launch before attaching (frida-server '
                         'cannot resolve a pid that appeared moments ago)')
    a = ap.parse_args()

    src = '\n;\n'.join(open(f).read() for f in a.script)
    dev = get_device(a.device)
    rec = {'device': a.device, 'scripts': a.script, 'ts': time.time(), 'spawn': a.spawn}
    events = []
    pid = None

    if a.spawn:
        adb(a.adb, 'am', 'force-stop', a.pkg)
        time.sleep(1)
        adb(a.adb, 'logcat', '-c')
        try:
            pid = dev.spawn([a.pkg])
            print(f'[probe] spawned pid={pid}')
        except Exception as e:
            rec['error'] = f'spawn failed: {e}'
            print(f'[probe] spawn failed: {e}')
            return 3
    else:
        if a.relaunch:
            adb(a.adb, 'am', 'force-stop', a.pkg)
            time.sleep(1)
            launch(a.adb, a.pkg)
        if a.settle:
            time.sleep(a.settle)
        # 用**稳定采样**拿 pid：连读两次一致才算数，避免把"启动窗口"当成"进程不在"（2026-10-12 踩过）
        pid = stable_pid(a.adb, a.pkg)
        if pid is None:
            print('[probe] app not running（稳定采样 12 次仍拿不到 pid）— start it first (or use --relaunch)')
            return 2
        # 附加**前一瞬间**再解析一次，并把两次是否一致记进结果（诊断用）
        pid2 = pidof(a.adb, a.pkg)
        rec['pid_recheck'] = pid2
        if pid2 and pid2 != pid:
            print(f'[probe] pid 在采样与附加之间变了：{pid} -> {pid2}（用新的）')
            pid = pid2
        adb(a.adb, 'logcat', '-c')
    print(f'[probe] target pid={pid}')
    rec['pid'] = pid

    events = []
    if not a.no_ensure_frida:
        alive_server = ensure_frida_server(a.adb)
        rec['frida_server'] = alive_server
        if not alive_server:
            print('[probe] 警告：frida-server 起不来 —— 这次结果只能读成"未测到"')

    t0 = time.time()
    attach_error = None
    try:
        ses = dev.attach(pid)
        rec['attached'] = round(time.time() - t0, 3)
        print(f"[probe] attached in {rec['attached']}s")

        def on_detached(reason, *rest):
            events.append(('detached', str(reason), round(time.time() - t0, 3)))
            print(f"[probe] detached: {reason} @ +{events[-1][2]}s")

        ses.on('detached', on_detached)
        sc = ses.create_script(src)

        def on_message(m, d):
            events.append(('msg', str(m)[:1500], round(time.time() - t0, 3)))
            print(f"[probe] msg +{events[-1][2]}s {str(m)[:600]}")

        sc.on('message', on_message)
        sc.load()
        rec['script_loaded_at'] = round(time.time() - t0, 3)
        print(f"[probe] script loaded @ +{rec['script_loaded_at']}s")
        if a.spawn:
            dev.resume(pid)
            rec['resumed_at'] = round(time.time() - t0, 3)
            print(f"[probe] resumed @ +{rec['resumed_at']}s")
    except Exception as e:  # attach refused
        rec['error'] = str(e)
        attach_error = str(e)
        rec['attach_error'] = attach_error
        print(f'[probe] attach failed: {e}')

    died_at = None
    timeline = [(round(time.time() - t0, 2), pid)]
    while time.time() - t0 < a.seconds:
        cur = pidof(a.adb, a.pkg)
        if cur is None:
            if died_at is None:
                died_at = round(time.time() - t0, 3)
                print(f'[probe] pid gone @ +{died_at}s')
        elif timeline and timeline[-1][1] != cur:
            timeline.append((round(time.time() - t0, 2), cur))
            print(f"[probe] restarted: pid={cur} @ +{timeline[-1][0]}s")
        time.sleep(0.25)

    rec['died_after_s'] = died_at
    rec['survived'] = survived_of(attach_error, died_at)
    # "没插上" ≠ "活下来了"：附加失败时进程当然活着 —— 这是本项目第三次遇到同一类陷阱
    # 附加失败有两种截然不同的含义，必须分开：
    #  (a) 进程**随后消失** → 极可能就是反注入在起效（连接被"掐断"而不是没插上）；
    #  (b) 进程**仍在** → 那才是"未测到"。
    pid_after = (adb(a.adb, 'shell', 'pidof', a.pkg) or '').strip()
    if attach_error:
        # 关键区分：**附加后短时间内进程消失** = 反注入生效（Frida 报"process not found"是死亡的结果，不是"没插上"）。
        # 只有"进程仍在"才是真正的"未测到"。（2026-10-12：一台设备在这个区别上被误读了好几轮。）
        if died_at is not None and died_at <= 6.0:
            rec['verdict'] = f'附加后 {died_at:.1f}s 内消失（反注入生效；Frida 的报错是死亡的结果）'
        elif not pid_after:
            rec['verdict'] = '附加后进程消失，但未测到确切时长（倾向：反注入生效）'
        else:
            rec['verdict'] = '未测到（附加失败，进程仍在）'
    else:
        rec['verdict'] = '存活' if died_at is None else f'附加后 {died_at}s 内消失'
    rec['pid_timeline'] = timeline
    rec['events'] = events
    log = adb(a.adb, 'logcat', '-d', '-t', '4000')
    rec['death_signs'] = [l for l in log.splitlines() if any(s in l for s in DEATH_SIGNS)][-12:]
    rec['app_lines'] = [l for l in log.splitlines()
                        if f' {pid} ' in l and 'IPCThreadState' not in l][-25:]
    rec['log_tail'] = log.splitlines()[-15:]

    # `None` 要说成"未测"，不要打印成一个光秃秃的 `None`；
    # `died_at=None` 也别印成 "Nones"（旧实现就是这么印的）。
    _sv = ('未测（没插上）' if rec['survived'] is None
           else ('是' if rec['survived'] else '否'))
    _da = '未测' if died_at is None else f'{died_at}s'
    print(f"[probe] died_after={_da} survived={_sv} verdict={rec['verdict']}")
    for l in rec['death_signs']:
        print('[probe]   ' + l)
    for l in rec['app_lines'][-8:]:
        print('[probe] app> ' + l)

    if a.out:
        with open(a.out, 'w') as fh:
            json.dump(rec, fh, indent=2)
        print(f'[probe] record -> {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
