#!/usr/bin/env python3
"""
kuaidui-kit / rc4_plaintexts.py — 把模块抓到的 RC4 明文落成导出（2026-10-12）。

数据源：宿主私有目录里的 `files/kdkit_capture.txt` ✓（`RC4Probe` 功能写的 ✓）。
产 出：`work/exports/rc4_plaintexts.csv` ✓（每轮自动刷新 ✓）+ 一行统计 ✓。

    python3 kit/scripts/rc4_plaintexts.py --adb emulator-5558 [--out work/exports/rc4_plaintexts.csv]
"""
import argparse
import csv
import os
import re
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
from device import PKG as PKG_CONST
from device import default_serial


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
CAP = f'/data/data/{PKG}/files/kdkit_capture.txt'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=default_serial())
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'exports', 'rc4_plaintexts.csv'))
    a = ap.parse_args(argv[1:])
    adb = os.path.join(os.path.expanduser('~'), 'Library', 'Android', 'sdk', 'platform-tools', 'adb')
    if not os.path.exists(adb):
        adb = 'adb'
    try:
        p = subprocess.run([adb, '-s', a.adb, 'shell', f'su -c "cat {CAP}"'],
                           capture_output=True, text=True, timeout=180)
        raw = p.stdout.replace('\r', '')
    except Exception as e:
        print(f'[rc4] 读取失败: {e}')
        return 0
    pt = [l.split('RC4PT ', 1)[1].strip() for l in raw.split('\n') if 'RC4PT ' in l]
    keys = sorted(set(l.split('RC4KEYSTR ', 1)[1].split(' |')[0] for l in raw.split('\n') if 'RC4KEYSTR ' in l))
    uniq = sorted(set(pt))
    if not uniq:
        print('[rc4] 暂无 RC4PT 记录（功能未触发或刚重启）')
        return 0
    with open(a.out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['plaintext'])
        for s in uniq:
            w.writerow([s])
    print(f'[rc4] -> {a.out}（{len(pt)} 条 ⇒ 去重 {len(uniq)} ✓；密钥 {len(keys)} 把 ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
