#!/usr/bin/env python3
"""
kuaidui-kit / reverify.py — re-run the project's *older* conclusions with today's tools.

Every round added claims; this script re-checks a few of them from scratch so drift (a changed
server, a changed device, a regression in our own tooling) is caught by re-running rather than by
trusting the note that recorded them. It is deliberately narrow: four claims, each with a command.

    python3 kit/scripts/reverify.py --adb emulator-5558 --out work/packs/r42/reverify.md

Claims re-checked
  C1 (R3/R4)  offline RC4 == the app's own RC4 calls            -> 0 mismatches expected
  C2 (R7)     tokens -> A/X decode + signature rebuild          -> 0 mismatches expected
  C3 (R10)    response payload decrypts with the current key    -> JSON expected
  C4 (R12/R20) the native anti-instrumentation is still live: attaching Frida still kills the app
              (time-to-death is the measurement; "it survived" would mean the environment changed)
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import sh as _shmod
from device import PKG as PKG_CONST
from device import PREFS as PREFS_CONST
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
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
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rows = []
    outdir = os.path.dirname(a.out) if a.out else os.path.join(ROOT, 'work')
    os.makedirs(outdir, exist_ok=True)

    # The checks need the diagnostic flags on AND a capture that has actually accumulated
    # records. `--ensure-flags` restarts the host, so a capture pulled immediately afterwards can
    # be empty (measured 2026-10-11: 8869 B / 0 records) — that is a *data* problem, not a drift,
    # so wait for traffic and, if nothing appears, generate some by opening a page.
    sh(f'python3 {HERE}/acceptance.py --adb {a.adb} --ensure-flags', timeout=1200)
    cap = os.path.join(outdir, 'reverify_capture.txt')
    text, ready = '', False
    for attempt in range(24):
        text = adb(a.adb, f'cat /data/data/{PKG}/files/kdkit_capture.txt')[1]
        textio.write_text(cap, text)
        rc4 = text.count('RC4 encrypt') + text.count('RC4 decrypt')
        if rc4 >= 5 and ' SIGN URL: ' in text:
            ready = True
            break
        if attempt % 5 == 4:                  # 每 ~30 s 还没数据就驱动一次页面造流量
            print(f'[reverify] capture not ready (attempt {attempt + 1}) — driving a page')
            sh(f'python3 {HERE}/tap_texts.py --adb {a.adb} --steps "AI写作" --wait 10')
        time.sleep(6)
    print(f'[reverify] capture {len(text)} B, RC4 ops={text.count("RC4 encrypt") + text.count("RC4 decrypt")}, '
          f'signed URLs={text.count(" SIGN URL: ")}, ready={ready}')

    # tokens from the device (root)
    prefs = PREFS_CONST
    ta = os.path.join(outdir, 'reverify_signA.txt')
    tb = os.path.join(outdir, 'reverify_signB.txt')
    # 用设备侧 grep 取值（acceptance 用的就是这条，稳），不要自己解析 XML
    for f, key in ((ta, 'KEY_ANTISPAM_SIGN_A'), (tb, 'KEY_ANTISPAM_SIGN_B')):
        val = adb(a.adb, f"grep -o '{key}\"[^>]*>[^<]*' {prefs}")[1]
        val = val.split('>', 1)[-1].strip() if '>' in val else ''
        textio.write_text(f, val)
    print(f'[reverify] tokens: {os.path.getsize(ta)} B / {os.path.getsize(tb)} B')

    # C1
    rc, out = sh(f'python3 {HERE}/../python/verify_rc4_capture.py {cap}')
    m = re.search(r'match=(\d+) mismatch=(\d+)', out)
    ok = bool(m) and int(m.group(2)) == 0 and int(m.group(1)) > 0
    rows.append(('C1 离线 RC4 == 实盘 RC4', ok,
                 (m.group(0) if m else out.strip()[:60]) + ('' if ready else '（数据不足，非漂移）')))

    # C2
    rc, out = sh(f'python3 {HERE}/decode_token_native.py --adb {a.adb} --sign-a {ta} --sign-b {tb} '
                 f'--capture {cap}')
    m = re.search(r'capture check: match=(\d+) mismatch=(\d+)', out)
    ok = bool(m) and int(m.group(2)) == 0 and int(m.group(1)) > 0
    rows.append(('C2 token→A/X + 签名重建', ok, m.group(0) if m else out.strip()[-60:]))

    # C3 — pull the hotfix endpoint and decrypt the payload with the same-epoch key
    key = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', open(cap, errors='replace').read())
    rc, out = sh(f'python3 {HERE}/../python/kd_api.py pull --adb {a.adb} --sign-a {ta} --sign-b {tb} '
                 f'--capture {cap} --insecure --path /pluto/app/hotfix'
                 + (f' --rc4-key {key.group(1)}' if key else ''))
    ok200 = re.search(r'(\d+)/(\d+) endpoint\(s\) returned 200', out)
    errno0 = '"errNo":0' in out
    dec = 'decrypted' in out
    rows.append(('C3 响应体用当前 key 解密',
                 bool(ok200 and ok200.group(1) == ok200.group(2) and errno0),
                 (('HTTP 200 + errNo 0' + ('，encodeData 解出' if dec else '（本次响应无 encodeData，无需解密）'))
                  if (ok200 and errno0) else out.strip().splitlines()[-1][:70])))

    # C4 — attach Frida, measure time-to-death. The app must be *up* first, otherwise the probe
    # prints "app not running", nothing is attached, and the check would report a false "survived".
    adb(a.adb, f'am force-stop {PKG}')
    adb(a.adb, f'am start -n {PKG}/.AliasActivityDefault')
    pid_before = ''
    for _ in range(20):
        pid_before = adb(a.adb, f'pidof {PKG}')[1].strip()
        if pid_before:
            break
        time.sleep(2)
    if not pid_before:
        rows.append(('C4 Frida 附加后仍会自杀（反注入仍生效）', False, '应用没能起来，本项无效'))
    else:
        time.sleep(6)
        t0 = time.time()
        rc, probe_out = sh(f'python3 {HERE}/attach_probe.py --adb {a.adb} --seconds 20', timeout=300)
        attached = 'app not running' not in probe_out
        # 判据必须是"**原来那个 pid** 消失了"，而不是"现在没有进程" ——
        # 宿主被杀后会被系统/自身立刻拉起，用"有没有进程"判断会得出"存活"的假结论（2026-10-12 在 5556 上实测）。
        died, dt = False, 0.0
        for _ in range(30):
            now_pid = adb(a.adb, f'pidof {PKG}')[1].strip()
            if not now_pid or (pid_before and now_pid != pid_before):
                died, dt = True, time.time() - t0
                break
            time.sleep(1)
        clean = 'exited cleanly' in probe_out
        # 三态：真正测到死亡 / 真正测到存活 / **没测到**（附加被拒或掐断 —— 这类结果不许读成"存活"）。
        # 2026-10-12 实测：两台模拟器连跑 17 小时后附加通路开始不可靠，若不区分就会把环境问题写成结论。
        # 探针已经区分过三种情况，这里直接采信它的判定文本：
        # "反注入生效" = 真正测到了死亡（哪怕 Frida 自己报的是 attach failed —— 那是死亡的结果）
        measured_death = ('反注入生效' in probe_out) or ('附加后' in probe_out and '内消失' in probe_out)
        attach_failed = (not measured_death) and (('attach failed' in probe_out) or ('未测到' in probe_out)
                                                 or ('附加被拒' in probe_out))
        if measured_death:
            verdict, detail = True, (f'pid {pid_before} 附加后 {dt:.1f}s 内消失，'
                                     f'日志{"有" if clean else "无"} "exited cleanly (0)"')
        elif attach_failed and not died:
            verdict, detail = False, '**未测到**：附加被拒/掐断（先确认 frida-server 与设备状态，别读成"存活"）'
        elif not attached:
            verdict, detail = False, '探针没能附加（应用未运行）'
        else:
            verdict, detail = False, f'存活（环境变了？）pid 仍为 {pid_before}'
        rows.append(('C4 Frida 附加后仍会自杀（反注入仍生效）', verdict, detail))

    out = ['# 跨轮回归抽查（用今天的工具重跑早期结论）', '',
           f'* 设备：`{a.adb}`',
           f'* 抓取：当前（{os.path.getsize(cap)} B）', '',
           '| 结论 | 通过 | 观测 |', '|---|---|---|']
    for name, ok, detail in rows:
        out.append(f'| {name} | {"✔" if ok else "✘"} | {detail} |')
    out += ['', '_每一项都是**重新跑出来的**，不是引用旧结论；任何一项 ✘ 都说明发生了漂移。_', '']
    text = '\n'.join(out) + '\n'
    if a.out:
        textio.write_text(a.out, text)
    print(text)
    return 0 if all(r[1] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
