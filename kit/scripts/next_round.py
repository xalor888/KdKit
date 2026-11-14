#!/usr/bin/env python3
"""
kuaidui-kit / next_round.py — read the current state and rank what to do next.

Written for the long haul: after a few hours of rounds, "what should the next round be" is a
question with a factual answer — what is red, what is stale, what the unsolved list says, and what
the project has already covered. This reads:

  * the newest evidence pack (gate results)        work/packs/*/index.md
  * the health snapshot's age                      work/HEALTH.md
  * the unsolved list                              work/HANDOVER.md §4
  * the round history (what themes are used up)    ROADMAP.md

and prints a ranked list. It never touches the device and never changes anything.

    python3 kit/scripts/next_round.py [--packs-dir work/packs] [--json]
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
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def newest_pack(packs_dir):
    if not os.path.isdir(packs_dir):
        return None, ''
    tags = [t for t in os.listdir(packs_dir) if os.path.isdir(os.path.join(packs_dir, t))]
    tags.sort(key=lambda t: os.path.getmtime(os.path.join(packs_dir, t)))
    if not tags:
        return None, ''
    tag = tags[-1]
    idx = os.path.join(packs_dir, tag, 'index.md')
    return tag, (open(idx, encoding='utf-8').read() if os.path.exists(idx) else '')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--packs-dir', default=os.path.join(ROOT, 'work', 'packs'))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv[1:])

    tag, idx = newest_pack(a.packs_dir)
    gates = []
    for line in idx.splitlines():
        m = re.match(r'\| `(acceptance|reverify \(C1-C4\)|baseline \(接口面\)|selftest \(工具自检\))` \| (.*?) \|', line)
        if m:
            gates.append((m.group(1), m.group(2).strip()))

    red = []
    for name, val in gates:
        if re.search(r'FAIL|✘|failed', val):
            red.append((name, val))
        m = re.match(r'(\d+)/(\d+)', val)
        if m and m.group(1) != m.group(2):
            red.append((name, val))

    # staleness: HEALTH.md should be at least as new as the newest pack
    health = os.path.join(ROOT, 'work', 'HEALTH.md')
    stale = []
    if os.path.exists(health) and tag:
        if os.path.getmtime(health) < os.path.getmtime(os.path.join(a.packs_dir, tag)):
            stale.append('work/HEALTH.md 比最新证据包旧（说明最近一轮没有跑证据包）')
    elif not os.path.exists(health):
        stale.append('work/HEALTH.md 不存在（跑一次证据包会生成）')

    # unsolved list
    unsolved = []
    ho = os.path.join(ROOT, 'work', 'HANDOVER.md')
    if os.path.exists(ho):
        for line in textio.read_lines(ho, encoding='utf-8'):
            m = re.match(r'\|\s*(\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|', line)
            if m:
                unsolved.append((m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()))

    # round themes (to avoid repeating)
    rm = textio.read_text(os.path.join(ROOT, 'ROADMAP.md'), encoding='utf-8')
    rounds = re.findall(r'^### (R\d+)[^\n]*：(.+)$', rm, re.M)

    actions = []
    if red:
        for name, val in red:
            actions.append(('P0', f'先修红门：{name} → {val}',
                            '别的动作都建立在"四道门绿"之上；红门通常意味着环境或结论漂移'))
    if stale:
        for s in stale:
            actions.append(('P1', s, '跑 `evidence_pack.py` 会顺手刷新'))
    for num, title, status, need in unsolved:
        actions.append(('P2', f'未解 #{num}：{title}',
                        f'现状：{status[:80]}；下一步需要：{need[:60]}'))
    actions.append(('P3', '轻量收尾（文档/索引/时间线）',
                    '`report_timeline.py`、`index_evidence.py`、`daily_report.py` 都可由证据包自动刷新'))
    actions.append(('P3', f'已走过 {len(rounds)} 轮 —— 新线先看 REPORT.md §10 与 HANDOVER §5',
                    '避免重复已覆盖的主题；新主题要么补证据强度，要么推进未解项'))

    out = {'pack': tag, 'gates': gates, 'red': red, 'stale': stale, 'actions': actions}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print(f'[next] 最新证据包：`{tag or "（无）"}`；四道门：')
    for name, val in gates:
        print(f'   - {name}: {val}')
    print('\n[next] 建议动作（按优先级）：')
    for pri, what, why in actions:
        print(f'   [{pri}] {what}\n         {why}')
    print(f'\n[next] 生成时间 {datetime.now().strftime("%H:%M:%S")}（只读，不改任何东西）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
