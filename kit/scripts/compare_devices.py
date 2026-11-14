#!/usr/bin/env python3
"""
kuaidui-kit / compare_devices.py — the same kit, two devices, side by side.

Answers "what is per-device and what is per-app" with data instead of intuition: token material,
payload key, capture volume, module state. Used on 2026-10-11 to show that the server issues
token material **deterministically per device** (stable across reinstalls), which is the same
binding that makes repacking pointless.

    python3 kit/scripts/compare_devices.py --adb-a emulator-5558 --adb-b emulator-5556 \
        --out work/dpsdk/device_compare.md
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
from device import PKG as PKG_CONST
from device import PREFS as PREFS_CONST
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
def sh(cmd, timeout=240):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=240):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def probe(serial):
    d = {'serial': serial}
    d['abi'] = adb(serial, 'getprop ro.product.cpu.abi')[1].strip()
    d['pid'] = adb(serial, f'pidof {PKG}')[1].strip()
    log = adb(serial, 'grep -a "HookCore ready" /data/adb/lspd/log/modules_*.log | tail -1')[1]
    m = re.search(r'HookCore ready \((\d+) features\)', log)
    d['features'] = m.group(1) if m else '-'
    cap = adb(serial, f'cat /data/data/{PKG}/files/kdkit_capture.txt')[1]
    d['cap_bytes'] = len(cap)
    d['signed_urls'] = cap.count(' SIGN URL: ')
    d['bridge'] = cap.count('H5BRIDGE ')
    d['guard'] = cap.count('GUARD blocked=')
    d['plain'] = len(re.findall(r' H5 \w+ out: ', cap))
    k = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', cap)
    d['key_head'] = k.group(1)[:16] if k else '-'
    # tokens -> X via the on-device oracle
    prefs = PREFS_CONST
    body = adb(serial, f'cat {prefs}')[1]
    a = re.search(r'KEY_ANTISPAM_SIGN_A"[^>]*>([^<]+)<', body)
    b = re.search(r'KEY_ANTISPAM_SIGN_B"[^>]*>([^<]+)<', body)
    d['has_tokens'] = bool(a and b)
    d['x'] = '-'
    if a and b:
        tmp_a, tmp_b = '/tmp/_cmpA.txt', '/tmp/_cmpB.txt'
        open(tmp_a, 'w').write(a.group(1))
        open(tmp_b, 'w').write(b.group(1))
        rc, out = sh(f'python3 {HERE}/decode_token_native.py --adb {serial} '
                     f'--sign-a {tmp_a} --sign-b {tmp_b} --capture /dev/null')
        mx = re.search(r'X\s*=\s*(\S+)', out)
        if not mx:                      # decode_token_native wants a capture; fall back to raw adb
            rc2, out2 = sh(['adb', '-s', serial, 'shell',
                            f"/data/local/tmp/decode_token /data/local/tmp/libbaseutil.so "
                            f"'{a.group(1)}' '@fG2SuLA'"])
            m1 = re.search(r'hex: ([0-9a-f]+)', out2)
            if m1:
                blob_a = bytes.fromhex(m1.group(1))
                key2 = blob_a[7:12].decode('latin1') + '#G4'
                rc3, out3 = sh(['adb', '-s', serial, 'shell',
                                f"/data/local/tmp/decode_token /data/local/tmp/libbaseutil.so "
                                f"'{b.group(1)}' '{key2}'"])
                m2 = re.search(r'hex: ([0-9a-f]+)', out3)
                if m2:
                    d['x'] = bytes.fromhex(m2.group(1))[0x0c:0x16].decode('latin1')
        else:
            d['x'] = mx.group(1)
    return d


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb-a', required=True)
    ap.add_argument('--adb-b', required=True)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rows = [probe(a.adb_a), probe(a.adb_b)]
    cols = [('serial', '设备'), ('abi', 'ABI'), ('features', '模块功能数'), ('pid', '宿主 pid'),
            ('x', 'token 派生 X'), ('key_head', '负载 key 头 16 位'), ('cap_bytes', '抓取字节'),
            ('signed_urls', '签名 URL'), ('bridge', '桥调用'), ('guard', '守卫拦截'),
            ('plain', '解密明文')]
    out = ['# 两台设备的同一套 kit 对照', '',
           '同一份工具、同一个 APK、同一个模块；下表回答"什么是跟设备走的、什么是跟应用走的"。', '',
           '| 项 | ' + ' | '.join(r['serial'] for r in rows) + ' | 是否随设备变化 |',
           '|---|---|---|' + '---|']
    varying = {'x', 'key_head', 'serial', 'pid', 'cap_bytes', 'signed_urls', 'bridge', 'guard', 'plain'}
    for key, label in cols:
        vals = [str(r.get(key, '-')) for r in rows]
        same = vals[0] == vals[1]
        verdict = '否（两端一致）' if same else ('**是**' if key in varying else '是')
        out.append(f"| {label} | " + ' | '.join(f'`{v}`' for v in vals) + f' | {verdict} |')
    out += ['', '## 读法', '',
            '* **跟设备走的**：`token 派生 X`、`负载 key`、`pid`、抓取体量 —— 前两者由服务端按设备侧材料'
            '确定性签发，**清数据重装后不变**（5556 两次 `pm clear` 后 `X` 仍是同一个），换设备则完全不同；',
            '* **跟应用/模块走的**：模块功能数、钩子目标、配置通道行为 —— 两端一致，说明交付物本身不依赖设备；',
            '* 这同一根"设备绑定"链条，也是**改包重签必然失败**的原因（见 README 的已知限制）。', '']
    text = '\n'.join(out) + '\n'
    print(text)
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[compare] -> {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
