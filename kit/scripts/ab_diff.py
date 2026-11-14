#!/usr/bin/env python3
"""
kuaidui-kit / ab_diff.py — AB 实验表的**结构面**（2026-10-12）。

`ab_experiments.csv` 有 236 条 ✓；本工具只看**结构**（key 集合 ✓）：
* 新增 key ⇒ **新实验上线** ✓（常解释"某功能为什么变了" ✓）；
* 消失 key ⇒ 实验下线 ✓；
* 取值变化 ⇒ **轮换** ✓（值级 ✓ —— 按"结构 vs 值"总纲，**不必慌** ✓）。

    python3 kit/scripts/ab_diff.py --current <responses.json> [--previous <responses.json>] [--out work/AB_DIFF.md]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PATH = '/abengine/api/client'


def abmap(resp_file):
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
    for e in (data.get('ab') or []):
        if isinstance(e, dict):
            out[str(e.get('key'))] = e.get('value')
    return out or None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--current', required=True)
    ap.add_argument('--previous', default=None)
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'AB_DIFF.md'))
    a = ap.parse_args(argv[1:])
    cur = abmap(a.current)
    if not cur:
        print('[ab] 当前包里没有 ab（跳过）')
        return 0
    prev = abmap(a.previous) if a.previous else None
    added = sorted(set(cur) - set(prev)) if prev else []
    removed = sorted(set(prev) - set(cur)) if prev else []
    valchg = [k for k in sorted(set(cur) & set(prev)) if str(cur[k]) != str(prev[k])] if prev else []
    import collections
    pref = collections.Counter()
    for k in cur:
        m = re.match(r'^([a-zA-Z]+|[a-z]+_[A-Za-z]+)', k)
        pref[(m.group(1) if m else k)[:10]] += 1
    top = '、'.join(f'{k} {v}' for k, v in pref.most_common(5))
    text = ['# AB 实验表的结构面（第九张漂移面）', '',
            f'* 实验总数 **{len(cur)}** ✓；前五前缀：{top} ✓',
            f'* **结构变化：新增 {len(added)} / 消失 {len(removed)}** ← **这才是信号** ✓',
            f'* 取值变化：**{len(valchg)}**（值级 ✓ 多半是轮换 ✓）', '']
    if added or removed:
        text += ['| 类型 | key |', '|---|---|']
        for k in added:
            text.append(f'| **新增** ✓（新实验上线）| `{k}` |')
        for k in removed:
            text.append(f'| **消失** ✗（实验下线）| `{k}` |')
        text.append('')
    text += ['读法 ✓：**结构变 ⇒ 认真看** ✓（新实验常解释"某功能为什么变了" ✓）；**值变 ⇒ 多半轮换** ✗ 不必慌 ✓。', '']
    open(a.out, 'w').write('\n'.join(text) + '\n')
    print(f'[ab] -> {a.out}（{len(cur)} 条实验；结构变化 新增 {len(added)} / 消失 {len(removed)}；取值变化 {len(valchg)}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
