#!/usr/bin/env python3
"""
kuaidui-kit / anchors.py — **锚点检查**（2026-10-12）。

由来：本会话"**锚点/标签按猜的写**" ✗ 已发生 **7 次**（R270/R293/R297/R298/R304/R313/R324 ✓）。
⇒ 打补丁前**先列出真实锚点** ✓，就没机会猜 ✗。

    python3 kit/scripts/anchors.py REPORT.md                 # 列出标题（锚点候选 ✓）
    python3 kit/scripts/anchors.py REPORT.md --check "## 1 目标画像"   # 检查某锚点是否存在 ✓
    python3 kit/scripts/anchors.py REPORT.md --grep 接手       # 按关键词找锚点 ✓
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--check', default=None, help='检查这个锚点是否存在 ✓')
    ap.add_argument('--grep', default=None, help='按关键词筛选锚点 ✓')
    ap.add_argument('--limit', type=int, default=60)
    a = ap.parse_args(argv[1:])
    path = a.file if os.path.isabs(a.file) else os.path.join(ROOT, a.file)
    if not os.path.exists(path):
        print(f'[anchors] ✗ 文件不存在：{a.file}')
        return 2
    txt = open(path, encoding='utf-8', errors='replace').read()
    heads = [ln.rstrip() for ln in txt.split('\n') if re.match(r'^#{1,4} ', ln)]
    if a.check is not None:
        hit = a.check in txt
        print(f'[anchors] {"✓ 命中" if hit else "✗ 不存在"}：{a.check[:80]}')
        if not hit:
            near = [h for h in heads if a.check.strip('# ').split()[0][:6] in h] if a.check.strip('# ') else []
            if near:
                print('   相近的锚点：')
                for h in near[:6]:
                    print('     ', h[:90])
        return 0 if hit else 1
    if a.grep:
        heads = [h for h in heads if a.grep in h]
    print(f'[anchors] {a.file} 共 {len(heads)} 个锚点' + (f'（筛选「{a.grep}」✓）' if a.grep else ' ✓'))
    for h in heads[:a.limit]:
        print('   ', h[:100])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
