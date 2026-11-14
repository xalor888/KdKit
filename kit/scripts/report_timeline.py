#!/usr/bin/env python3
"""
kuaidui-kit / report_timeline.py — keep REPORT.md's timeline section in sync with ROADMAP.md.

The report should answer "how did we get here" without the reader opening a 1200-line journal.
This rewrites the block between `<!-- TIMELINE:START -->` and `<!-- TIMELINE:END -->` with one line
per round (id + theme), newest last.

    python3 kit/scripts/report_timeline.py [--check]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORT = os.path.join(ROOT, 'REPORT.md')
START, END = '<!-- TIMELINE:START -->', '<!-- TIMELINE:END -->'


def build():
    rm = open(os.path.join(ROOT, 'ROADMAP.md'), encoding='utf-8').read()
    rows = []
    for m in re.finditer(r'^### (R\d+)[^\n]*?：(.*)$', rm, re.M):
        rid, theme = m.group(1), m.group(2).strip()
        rows.append((rid, theme))
    lines = ['', f'共 {len(rows)} 轮（细节见 `ROADMAP.md`，每轮都有"做了什么 / 观测到什么 / 产出在哪"）。', '',
             '| 轮次 | 一句话 |', '|---|---|']
    for rid, theme in rows:
        lines.append(f'| **{rid}** | {theme} |')
    lines.append('')
    return '\n'.join(lines)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args(argv[1:])
    txt = open(REPORT, encoding='utf-8').read()
    if START not in txt or END not in txt:
        print('[timeline] REPORT.md 缺少 TIMELINE 标记')
        return 1
    head, rest = txt.split(START, 1)
    _old, tail = rest.split(END, 1)
    new = head + START + build() + END + tail
    if a.check:
        print('[timeline] up to date' if new == txt else '[timeline] STALE')
        return 0 if new == txt else 1
    open(REPORT, 'w').write(new)
    print(f'[timeline] REPORT.md 时间线已刷新（{new.count("| **R")} 轮）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
