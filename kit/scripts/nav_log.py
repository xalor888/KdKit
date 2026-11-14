#!/usr/bin/env python3
"""
kuaidui-kit / nav_log.py — H5 页面导航的**运行时观测**落成导出（2026-10-12 ✓，规则 23 第 ④ 步）。

数据源：宿主抓包里的 `NAV ` 行 ✓（`NavLog` 功能写的 ✓）。
产 出：`work/exports/h5_pages_observed.csv` ✓（`page` + `url` ✓）
      并**与 H5 族的 56 个路由对照** ✓ ⇒ "**观测到几个 / 还差几个**" ✓。

    python3 kit/scripts/nav_log.py --adb emulator-5558
"""
import argparse
import csv
import os
import re
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
from device import default_serial


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAP = '/data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=default_serial())
    a = ap.parse_args(argv[1:])
    adb = os.path.join(os.path.expanduser('~'), 'Library', 'Android', 'sdk', 'platform-tools', 'adb')
    if not os.path.exists(adb):
        adb = 'adb'
    try:
        p = subprocess.run([adb, '-s', a.adb, 'shell', f'su -c "cat {CAP}"'],
                           capture_output=True, text=True, timeout=180)
        raw = p.stdout.replace('\r', '')
    except Exception as e:
        print(f'[nav] 读取失败: {e}')
        return 0
    rows = {}
    # 原生侧 ✓（`NAVACT ` 行 ✓ —— R418 加 ✓）
    native = {}
    for l in raw.split('\n'):
        if 'NAVACT ' in l:
            native.setdefault(l.split('NAVACT ', 1)[1].strip(), True)
    for l in raw.split('\n'):
        if 'NAV ' not in l:
            continue
        body = l.split('NAV ', 1)[1]
        parts = body.split('|')
        page = parts[0].strip()
        url = parts[1].strip() if len(parts) > 1 else ''
        if page:
            rows.setdefault(page, url)
    if not rows:
        print('[nav] 暂无 NAV 记录（功能已装 ✓，等页面加载 ✓）')
        return 0
    out = os.path.join(ROOT, 'work', 'exports', 'h5_pages_observed.csv')
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['side', 'page', 'url'])
        w.writeheader()
        for k in sorted(native):
            w.writerow({'side': 'native', 'page': k, 'url': ''})
        for k in sorted(rows):
            w.writerow({'side': 'h5', 'page': k, 'url': rows[k]})
    # 与 H5 族 56 个对照 ✓
    h5 = []
    zp = os.path.join(ROOT, 'work', 'exports', 'zyb_routes.csv')
    if os.path.exists(zp):
        h5 = [r['route'] for r in csv.DictReader(open(zp, encoding='utf-8'))
              if '/page/' in r['route'] and ('app-vue' in r['route'] or 'kd-' in r['route'])]
    hit = 0
    for r in h5:
        nm = r.split('/')[-1]
        if any(nm in pg or pg.split('-')[0] in nm for pg in rows):
            hit += 1
    print(f'[nav] -> {out}（H5 {len(rows)} 个 ✓ + 原生 {len(native)} 个 ✓；H5 族 {len(h5)} 个 ⇒ **对上 {hit}** ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
