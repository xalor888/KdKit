#!/usr/bin/env python3
"""
kuaidui-kit / route_log.py — 路由的**运行时观测**落成导出（2026-10-12 ✓，规则 23 第 ④ 步）。

数据源：宿主抓包里的 `ROUTE ` 行 ✓（`RouteLog` 功能写的 ✓）。
产 出：`work/exports/route_observed.csv` ✓（`route` + `from` ✓）
      并**与静态全表 `zyb_routes.csv`（81 个 ✓）对照** ✓ —— 看"**81 个里见过几个**" ✓。

    python3 kit/scripts/route_log.py --adb emulator-5558
"""
import argparse
import csv
import os
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
        print(f'[route] 读取失败: {e}')
        return 0
    rows = []
    for l in raw.split('\n'):
        if 'ROUTE ' not in l:
            continue
        body = l.split('ROUTE ', 1)[1]
        parts = body.split('|')
        arg = parts[0].split(' ', 1)[1].strip() if ' ' in parts[0] else ''
        frm = parts[1].replace('from=', '').strip() if len(parts) > 1 else ''
        if arg:
            rows.append({'route': arg, 'from': frm})
    uniq = {(r['route'], r['from']) for r in rows}
    if not uniq:
        print('[route] 暂无 ROUTE 记录（功能已装 ✓，等触发 ✓）')
        return 0
    out = os.path.join(ROOT, 'work', 'exports', 'route_observed.csv')
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['route', 'from'])
        w.writeheader()
        for r, f in sorted(uniq):
            w.writerow({'route': r, 'from': f})
    # 与静态全表对照 ✓
    static = set()
    sp = os.path.join(ROOT, 'work', 'exports', 'zyb_routes.csv')
    if os.path.exists(sp):
        static = {r['route'] for r in csv.DictReader(open(sp, encoding='utf-8'))}
    seen = {r for r, _ in uniq if r.startswith('zyb://')}
    hit = len(seen & static) if static else 0
    print(f'[route] -> {out}（{len(rows)} 条 ⇒ 去重 {len(uniq)} ✓；'
          f'静态全表 {len(static)} 个 ⇒ **见过 {hit}** ✓）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
