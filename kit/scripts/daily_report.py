#!/usr/bin/env python3
"""
kuaidui-kit / daily_report.py — roll the per-round evidence packs up into a day view.

Each round leaves `work/packs/<tag>/` with the gate results. Individually they answer "was that
round okay"; together they answer "how has the project been doing" — which gate ever went red, how
the tool count grew, how much evidence accumulated today.

    python3 kit/scripts/daily_report.py [--out work/DAILY-<date>.md]

Reads only files that already exist (no device access), so it is safe to run any time.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PACKS = os.path.join(ROOT, 'work', 'packs')


def pack_rows():
    rows = []
    for tag in sorted(os.listdir(PACKS)):
        d = os.path.join(PACKS, tag)
        if not os.path.isdir(d):
            continue
        row = {'tag': tag, 'when': '', 'acceptance': '', 'reverify': '', 'selftest': '',
               'baseline': '', 'matrix': '', 'capture': ''}
        idx = os.path.join(d, 'index.md')
        if os.path.exists(idx):
            txt = textio.read_text(idx, encoding='utf-8')
            m = re.search(r'生成时间：([\d\- :]+)', txt)
            row['when'] = m.group(1) if m else ''
            for line in txt.splitlines():
                if line.startswith('| `acceptance`'):
                    row['acceptance'] = line.split('|')[2].strip()
                elif line.startswith('| `reverify'):
                    row['reverify'] = line.split('|')[2].strip()
                elif line.startswith('| `selftest'):
                    row['selftest'] = line.split('|')[2].strip()
                elif line.startswith('| `baseline'):
                    row['baseline'] = line.split('|')[2].strip()
                elif line.startswith('| `module/VERIFICATION'):
                    row['matrix'] = line.split('|')[2].strip()
                elif line.startswith('| `capture`'):
                    row['capture'] = line.split('|')[2].strip()
        else:
            # older packs have no index.md — fall back to the acceptance json
            acc = os.path.join(d, 'acceptance.json')
            if os.path.exists(acc):
                try:
                    j = json.loads(textio.read_text(acc))
                    bad = [r['check'] for r in j if not r['ok']]
                    row['acceptance'] = f'{len(j) - len(bad)}/{len(j)}' + (f" (红: {', '.join(bad)})" if bad else '')
                except Exception:
                    pass
        rows.append(row)
    return rows


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rows = pack_rows()
    day = datetime.now().strftime('%Y-%m-%d')
    out = [f'# 每日汇总 — {day}', '',
           f'* 证据包：{len(rows)} 个（`work/packs/`）',
           '* 每一列的取值就是那一轮"门"的结论；**红了也如实列出来**，因为趋势比单点更重要。', '',
           '| 包 | 时间 | 验收 | 跨轮漂移 | 接口面 | 工具自检 | 功能矩阵 | 抓取 |',
           '|---|---|---|---|---|---|---|---|']
    for r in rows:
        out.append(f"| `{r['tag']}` | {r['when'][5:16]} | {r['acceptance'] or '-'} | {r['reverify'] or '-'} | "
                   f"{r['baseline'] or '-'} | {r['selftest'] or '-'} | {r['matrix'] or '-'} | "
                   f"{r['capture'] or '-'} |")

    acc_red = [r['tag'] for r in rows if 'FAIL' in (r['acceptance'] or '')]
    rev_red = [r['tag'] for r in rows if '通过' in (r['reverify'] or '') and not (r['reverify'] or '').startswith(('4/4', '3/3'))]
    st = [r for r in rows if r['selftest']]
    trend = []
    if st:
        first, last = st[0]['selftest'], st[-1]['selftest']
        trend.append(f'工具自检规模：`{first}` → `{last}`（工具在增加，所以项数会涨）')
    def num(v):
        d = re.sub(r'[^0-9]', '', v or '')
        return int(d) if d else 0
    caps = [num(r['capture']) for r in rows if r['capture']]
    if caps:
        trend.append(f'单轮抓取量：{min(caps)} B … {max(caps)} B（中位 {sorted(caps)[len(caps)//2]} B）')

    out += ['', '## 趋势与异常', '',
            f'* 验收出现红过的包：{", ".join(f"`{t}`" for t in acc_red) if acc_red else "无"}',
            f'* 跨轮漂移未满分的包：{", ".join(f"`{t}`" for t in rev_red) if rev_red else "无"}']
    out += [f'* {t}' for t in trend]
    out += ['', '_由 `kit/scripts/daily_report.py` 从证据包本身汇总，不重新跑任何东西。_', '']

    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', f'DAILY-{day}.md')
    textio.write_text(target, text)
    print(f'[daily] -> {target}')
    print('\n'.join(out[5:12]))
    print('...')
    print('\n'.join(out[-6:]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
