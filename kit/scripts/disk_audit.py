#!/usr/bin/env python3
"""
kuaidui-kit / disk_audit.py — 工作区体积审计（带"跟上次比涨了多少"）。

`work` 曾在两轮之间从 1.0 GB 涨回 1.4 GB —— 体积治理是**周期性**的事，不是一次性的。
这个脚本把"谁在占地方、比上次涨了多少、哪些是可再生的"压成一行结论 + 一张表。

    python3 kit/scripts/disk_audit.py [--save] [--out work/AUDIT.md]

* 每次运行都把当前快照写进 `work/audits/disk.json`（历史留存，便于看趋势）；
* 已知**可再生**的大项（可删可重建）在下表里直接标出来，附带重建命令的出处。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AUDITS = os.path.join(ROOT, 'work', 'audits')

# 已知的可再生大项 → 重建说明（写在这里，清理时才不用临时判断）
REGENERABLE = {
    'work/apktool_out': 'apktool 解包产物（分析工作树，天天在用；重建见 kit/README.md）',
    'work/jadx_out': 'jadx 反编译树（可再生；重建见 kit/README.md）',
    'work/frida-server': '推给设备的 frida-server 二进制（保留：env_up.sh 依赖）',
}

# 门禁阈值（2026-11-02 加）。
#:
#: 这个脚本原来**永远返回 0** —— 它算增量、写历史、打印"无显著增长"，
#: 但"显著"两个字只出现在文案里，没有任何判据。**永远绿的门禁比没有门禁更糟**：
#: 它会让人以为"磁盘有人在管"。
#:
#: 现在两条真判据：
#:   ① 单项一轮内增长超过 `--max-grow-mb` ⇒ 这一轮产生了意外的大产物
#:      （2026-11-02 实测：我给错 serial 跑了一次证据包，留下 5 个垃圾目录 ——
#:       若有这道门禁，当时就会红）；
#:   ② 整个仓库超过 `--max-mb` ⇒ 该清理可再生产物了。
#: 阈值都写在命令行参数里，不埋在代码里：不同机器盘大小不同。
MAX_GROW_MB = 500
MAX_TOTAL_MB = 8192


def du_sizes(base):
    out = {}
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        p = os.path.join(base, name)
        r = subprocess.run(['du', '-sk', p], capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and r.stdout:
            out[os.path.relpath(p, ROOT)] = int(r.stdout.split()[0]) // 1024  # MB
    r = subprocess.run(['du', '-sk', ROOT], capture_output=True, text=True, timeout=120)
    out['<整个仓库>'] = int(r.stdout.split()[0]) // 1024 if r.returncode == 0 else 0
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    ap.add_argument('--max-grow-mb', type=int, default=MAX_GROW_MB,
                    help=f'单项一轮内增长上限（默认 {MAX_GROW_MB} MB）')
    ap.add_argument('--max-mb', type=int, default=MAX_TOTAL_MB,
                    help=f'整个仓库体积上限（默认 {MAX_TOTAL_MB} MB）')
    a = ap.parse_args(argv[1:])

    cur = du_sizes(os.path.join(ROOT, 'work'))
    prev = {}
    if os.path.exists(os.path.join(AUDITS, 'last.json')):
        prev = json.load(open(os.path.join(AUDITS, 'last.json'), encoding='utf-8')).get('sizes', {})

    rows = []
    for k, v in sorted(cur.items(), key=lambda kv: -kv[1]):
        if v < 5 and k != '<整个仓库>':
            continue
        d = v - prev.get(k, v)
        rows.append((k, v, d, REGENERABLE.get(k, '')))

    os.makedirs(AUDITS, exist_ok=True)
    json.dump({'ts': datetime.now().isoformat(timespec='seconds'), 'sizes': cur},
              open(os.path.join(AUDITS, 'last.json'), 'w'), ensure_ascii=False, indent=1)
    hist = os.path.join(AUDITS, 'disk_history.jsonl')
    with open(hist, 'a') as f:
        f.write(json.dumps({'ts': datetime.now().isoformat(timespec='seconds'), 'sizes': cur},
                           ensure_ascii=False) + '\n')

    total = cur.get('<整个仓库>', 0)
    work_total = sum(v for k, v in cur.items() if k != '<整个仓库>')
    text = ['# 工作区体积审计', '',
            f'* {datetime.now().strftime("%Y-%m-%d %H:%M")}　`work` 合计 **{work_total} MB**，仓库 **{total} MB**',
            '* 规则：**能便宜重下的留身份不留文件；可再生的删了写清重建命令；其余 gzip 无损归档**', '',
            '| 路径 | 体积 (MB) | 较上次 | 说明 |', '|---|---|---|---|']
    for k, v, d, note in rows:
        text.append(f'| `{k}` | {v} | {d:+d} | {note} |')
    text += ['', f'历史见 `work/audits/disk_history.jsonl`（每次运行追加一行）。', '']
    if a.out:
        open(a.out, 'w').write('\n'.join(text) + '\n')
        print(f'[disk] -> {a.out}')
    top = ', '.join(f'{k}={v}MB' for k, v, _d, _n in rows[:3])
    grown = [f'{k}+{d}' for k, _v, d, _n in rows if d > 5]
    print(f'[disk] work 合计 {work_total} MB；最大三项 {top}' + (f'；本轮增长 {", ".join(grown)}' if grown else '；无显著增长'))

    # ── 判据 ──────────────────────────────────────────────────────────────
    bad = []
    for k, v, d, _note in rows:
        if d > a.max_grow_mb:
            bad.append(f'{k} 一轮内 +{d} MB（上限 {a.max_grow_mb}）')
    total = next((v for k, v, _d, _n in rows if k == '<整个仓库>'), 0)
    if total > a.max_mb:
        bad.append(f'整个仓库 {total} MB（上限 {a.max_mb}）⇒ 清理可再生产物：'
                   + '；'.join(f'{k}' for k in REGENERABLE))
    if bad:
        print(f'[disk] **{len(bad)} 项超限**：')
        for b in bad:
            print(f'  ✗ {b}')
        return 1
    print(f'[disk] 体积在限内 ✓（单项增长 ≤{a.max_grow_mb} MB，总计 ≤{a.max_mb} MB）')
    return 0
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
