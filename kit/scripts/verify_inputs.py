#!/usr/bin/env python3
"""
kuaidui-kit / verify_inputs.py — 把"结论所依赖的输入"钉上哈希。

每个结论都寄生在输入上：换个 APK、换份解出来的 .so、换次 harness 构建，结论就不再成立。
这个脚本记录并核对这些输入的身份（`--save` 建基线，默认核对）：

  * 目标 APK 样本（`*.apk` 顶层）
  * 从 APK 解出来的 native 库（`work/native/*.so`）—— 并与 APK 内 `lib/arm64-v8a/*` **逐一对账**
  * harness 产物（`kit/harness/native/decode_token`）—— 记录构建脚本修订号，便于重建
  * 模块产物（`module/app/build/outputs/apk/debug/app-debug.apk`）

    python3 kit/scripts/verify_inputs.py --save      # 建/更新基线
    python3 kit/scripts/verify_inputs.py            # 核对（漂了返回 1）
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BASE = os.path.join(ROOT, 'work', 'baselines', 'input_hashes.json')


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
            if limit and f.tell() > limit:
                break
    return h.hexdigest()


def collect(adb=''):
    inv = {}
    for fn in sorted(os.listdir(ROOT)):
        if fn.endswith('.apk') and not fn.startswith('Magisk'):
            inv[f'apk:{fn}'] = {'sha256': sha256(os.path.join(ROOT, fn)),
                               'bytes': os.path.getsize(os.path.join(ROOT, fn))}
    nd = os.path.join(ROOT, 'work', 'native')
    if os.path.isdir(nd):
        for fn in sorted(os.listdir(nd)):
            if fn.endswith('.so'):
                inv[f'extracted:{fn}'] = {'sha256': sha256(os.path.join(nd, fn)),
                                          'bytes': os.path.getsize(os.path.join(nd, fn))}
    # 设备上**目标应用**的安装包身份：它若变化（被升级/重装），所有针对该版本的结论都需要重估。
    # 2026-10-12 加：这是"输入身份"里最容易悄悄变的一个，而它不在本地磁盘上。
    # **设备号不写死**（2026-11-04 修，代码审查 P1）：加 `--adb SERIAL`，
    # 不传时再回落到那两个 —— 否则换设备后"输入身份"永远查的是别人的机器。
    import subprocess as _sp
    
    serial_list = [adb] if adb else ("emulator-5558", "emulator-5556")
    for serial in serial_list:
        try:
            pth = _sp.run(['adb', '-s', serial, 'shell', 'pm path com.kuaiduizuoye.scan'],
                          capture_output=True, text=True, timeout=60).stdout.strip()
            apk = pth.split('package:', 1)[1].split('\n')[0].strip() if 'package:' in pth else ''
            if apk:
                h = _sp.run(['adb', '-s', serial, 'shell', f'sha256sum {apk}'],
                            capture_output=True, text=True, timeout=120).stdout.strip().split()[0]
                inv[f'device-apk:{serial}'] = {'sha256': h, 'path': apk}
        except Exception:
            pass

    for rel in ('kit/harness/native/decode_token',
                'module/app/build/outputs/apk/debug/app-debug.apk'):
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            inv[f'built:{rel}'] = {'sha256': sha256(p), 'bytes': os.path.getsize(p)}
    return inv


def check_extracted_against_apk():
    """解出来的 .so 必须和 APK 里那一份逐字节一致（否则"我们分析的库"就不是目标里的库）。"""
    apks = [fn for fn in os.listdir(ROOT) if fn.endswith('.apk') and not fn.startswith('Magisk')]
    if not apks:
        return []
    z = zipfile.ZipFile(os.path.join(ROOT, apks[0]))
    inside = {os.path.basename(n): n for n in z.namelist()
              if re.match(r'lib/arm64-v8a/[^/]+\.so$', n)}
    rows = []
    nd = os.path.join(ROOT, 'work', 'native')
    for fn, member in sorted(inside.items()):
        local = os.path.join(nd, fn)
        if not os.path.exists(local):
            rows.append((fn, 'missing', ''))
            continue
        h_local = sha256(local)
        h_zip = hashlib.sha256(z.read(member)).hexdigest()
        rows.append((fn, 'ok' if h_local == h_zip else 'MISMATCH', h_local[:16]))
    return rows


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--save', action='store_true')
    ap.add_argument('--adb', default='',
                    help='目标设备号；不给则回落到 emulator-5558/5556（兼容旧行为）')
    a = ap.parse_args(argv[1:])

    inv = collect(a.adb)
    os.makedirs(os.path.dirname(BASE), exist_ok=True)

    if a.save:
        json.dump(inv, open(BASE, 'w'), indent=1, ensure_ascii=False)
        print(f'[inputs] 基线已写入 {os.path.relpath(BASE, ROOT)}（{len(inv)} 项）')
    else:
        old = json.load(open(BASE)) if os.path.exists(BASE) else {}
        drift = [k for k in set(old) | set(inv) if old.get(k, {}).get('sha256') != inv.get(k, {}).get('sha256')]
        for k in drift:
            print(f'[inputs] 变化: {k}\n          旧 {old.get(k, {}).get("sha256", "（无）")[:16]}'
                  f' → 新 {inv.get(k, {}).get("sha256", "（缺失）")[:16]}')
        if not drift:
            print(f'[inputs] {len(inv)} 项输入哈希与基线一致')

    rows = check_extracted_against_apk()
    bad = [r for r in rows if r[1] != 'ok']
    print(f'[inputs] 解出库 vs APK 内库：{len(rows) - len(bad)}/{len(rows)} 一致'
          + (f'；异常：{bad[:3]}' if bad else ''))
    return 1 if (rows and bad) or (not a.save and 'drift' in dir() and drift) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
