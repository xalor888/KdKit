#!/usr/bin/env python3
"""
kuaidui-kit / switch_diff.py — 特性开关的**漂移面**（2026-10-12）。

`/codesearch/init/checkappconfig` 的 `switches`（45 个 flag ✓）是"**功能有没有上线**"的直接信号 ✓：
某天某个 flag 从 0 变 1 ⇒ **功能上线了** ✓（而它往往正好解释"为什么某条路以前不通" ✓）。

    python3 kit/scripts/switch_diff.py --current <responses.json> [--previous <responses.json>] [--out work/SWITCH_DIFF.md]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PATH = '/codesearch/init/checkappconfig'


def switches(resp_file):
    try:
        doc = json.load(open(resp_file, encoding='utf-8'))
    except Exception:
        return None
    rec = doc.get(PATH)
    if not rec:
        return None
    try:
        data = json.loads(rec['body'] if isinstance(rec, dict) else str(rec))['data']
    except Exception:
        return None
    out = {}
    for s in (data.get('switches') or []):
        if isinstance(s, dict):
            out[str(s.get('flag'))] = s.get('sw')
    return out or None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--current', required=True)
    ap.add_argument('--previous', default=None)
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'SWITCH_DIFF.md'))
    a = ap.parse_args(argv[1:])

    cur = switches(a.current)
    if not cur:
        print('[switch] 当前包里没有 switches（跳过）')
        return 0
    prev = switches(a.previous) if a.previous else None
    on = [k for k, v in cur.items() if str(v) == '1']
    changed = []
    added = sorted(set(cur) - set(prev)) if prev else []
    removed = sorted(set(prev) - set(cur)) if prev else []
    if prev:
        for k in sorted(set(cur) & set(prev)):
            if prev.get(k) != cur.get(k):
                changed.append((k, prev.get(k), cur.get(k)))
    text = ['# 特性开关（漂移面）', '',
            f'* 开关总数 **{len(cur)}**：开 **{len(on)}** ✓ / 关 **{len(cur)-len(on)}** ✗',
            f'* **结构变化：新增 {len(added)} / 消失 {len(removed)}** ← 这才是"功能上线/下线"的**结构信号** ✓',
            f'* 取值变化：**{len(changed)}**（翻转 ✓，值级信号 ✓）', '']
    if added or removed:
        text += ['| 类型 | flag |', '|---|---|']
        for k in added:
            text.append(f'| **新增** ✓（可能=功能上线）| `{k}` |')
        for k in removed:
            text.append(f'| **消失** ✗（可能=功能下线）| `{k}` |')
        text.append('')
    if changed:
        text += ['| flag | 上次 | 现在 | 含义 |', '|---|---|---|---|']
        for k, o, n in changed:
            hint = '**功能上线** ✓' if str(n) == '1' else '**功能下线** ✗'
            text.append(f'| `{k}` | {o} | **{n}** | {hint} |')
        text.append('')
    text += ['**关着的**（当前未启用 ✓）：' + '、'.join(f'`{k}`' for k, v in sorted(cur.items()) if str(v) == '0'), '',
             '读法：**开关变化 = 功能上下线** ✓ —— 它常能解释"为什么某条路以前不通 / 现在通了" ✓'
             '（见 `work/DISABLED_FEATURES.md` ✓）。', '']
    open(a.out, 'w').write('\n'.join(text) + '\n')
    print(f'[switch] -> {a.out}（{len(cur)} 个开关：开 {len(on)} / 关 {len(cur)-len(on)}；'
          f'取值变化 {len(changed)}；结构变化 新增 {len(added)} / 消失 {len(removed)}）')
    for k, o, n in changed[:6]:
        print(f'   ★ {k}: {o} -> {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
