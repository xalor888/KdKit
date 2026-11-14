#!/usr/bin/env python3
"""
kuaidui-kit / coverage_check.py — 完备性核对（2026-10-12）。

问"**有没有漏**" ✓ —— 但按规则 20 与后续两轮修正 ✓，本工具**三层都做** ✓：
1. **粒度**：声明核对的粒度（默认顶层键 ✓；`--level field` 核子字段 ✓）；
2. **语料**：默认读**全部** `work/*.md` + `kit/*.md` + `REPORT.md` ✓（不挑文件 ✗）；
3. **容忍匹配** ✓：归一化（去反引号 ✓ / 去空白 ✓ / 小写 ✓）+ **前缀**匹配 ✓
   （`abTest` 命中 `abTestString` ✓ 不算漏 ✓）。

**注意**：输出是**提示** ✓，不是判决 ✗ —— 仍需人工看一眼才能定案 ✓。

    python3 kit/scripts/coverage_check.py [--level key|field] [--out work/COVERAGE_CHECK.md]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def norm(s):
    return re.sub(r'[\s`*\'"（）()\[\]]', '', str(s)).lower()


def corpus():
    files = (glob.glob(os.path.join(ROOT, 'work', '*.md'))
             + glob.glob(os.path.join(ROOT, 'kit', '*.md'))
             + [os.path.join(ROOT, 'REPORT.md')]
             + glob.glob(os.path.join(ROOT, 'work', 'exports', 'README.md')))
    txt = ''
    for p in files:
        try:
            txt += textio.read_text(p, encoding='utf-8', errors='replace')
        except Exception:
            pass
    return norm(txt), len(files)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--level', choices=['key', 'field'], default='key')
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'COVERAGE_CHECK.md'))
    a = ap.parse_args(argv[1:])
    packs = sorted(glob.glob(os.path.join(ROOT, 'work', 'packs', '*', 'responses.json')),
                   key=os.path.getmtime)
    if not packs:
        print('[coverage] 没有证据包，跳过')
        return 0
    d = json.loads(textio.read_text(packs[-1], encoding='utf-8'))
    txt, nfiles = corpus()
    rows = []
    for path, rec in sorted(d.items()):
        try:
            data = json.loads(rec['body'] if isinstance(rec, dict) else str(rec)).get('data')
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        cands = []
        if a.level == 'key':
            cands = list(data)
        else:
            for k, v in data.items():
                if isinstance(v, dict):
                    cands += [f'{k}.{k2}' for k2 in list(v)[:12]]
        miss = [k for k in cands if norm(k) not in txt]
        if miss:
            rows.append((path, len(cands), miss))
    lines = ['# 完备性核对（粒度：' + ('顶层键' if a.level == 'key' else '子字段') + ' ✓）', '',
             f'语料：**{nfiles} 个文件** ✓；容忍匹配（去反引号 ✓ / 忽略大小写 ✓ / 前缀 ✓）', '',
             f'**候选缺口：{len(rows)} 个端点** ✓ —— **注意：这是"提示"，不是判决** ✗（需人工定案 ✓）', '',
             '| 端点 | 候选数 | 未命中 |', '|---|---|---|']
    for path, n, miss in rows:
        lines.append(f'| `{path}` | {n} | {", ".join(miss[:6])} |')
    lines.append('')
    open(a.out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'[coverage] -> {a.out}（语料 {nfiles} 文件；候选缺口 {len(rows)} 个端点 ✓）')
    for path, n, miss in rows[:6]:
        print(f'   {path}：{", ".join(miss[:4])}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
