#!/usr/bin/env python3
"""
kuaidui-kit / day_summary.py — 把一段轮次按"产出类型"归类，回答"时间花在哪、还缺什么"。

每轮标题里通常就写着它属于哪一类（工具/文档/实验/修复/监控/验证…）。这个脚本按关键词归类，
统计每类几轮、并列出该类的轮次与它们的一句话结论 —— 让"接下来该往哪走"有依据。

    python3 kit/scripts/day_summary.py --from R80 --to R111 [--out work/DAY2_SUMMARY.md]
"""
import argparse
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# 类别 → 关键词（命中即归类；一轮可以命中多类）
CATS = [
    ('工具/自动化', ('新工具', '脚本', '自动化', '检查', '自检', '页面地图', '漂移', '基线')),
    ('实验/新知识', ('实测', '走查', '实验', '假设', '判决', '负结论', '结论', '收口')),
    ('修复/纠错', ('自纠', '修复', '修掉', '撤回', '踩坑', '抓住', '抓到', '减少')),
    ('监控/防守', ('监控', '注入', '竞态', '健康', '漂移门', '报警')),
    ('文档/交接', ('报告', '交接', '清单', '说明', '纪律', '决策', '快照', '小结')),
]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='start', default='R1')
    ap.add_argument('--to', dest='end', default='R9999')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rm = open(os.path.join(ROOT, 'ROADMAP.md'), encoding='utf-8').read()
    secs = re.split(r'^### ', rm, flags=re.M)[1:]
    def num(rid):
        m = re.search(r'\d+', rid)
        return int(m.group()) if m else 0
    lo, hi = num(a.start), num(a.end)

    rows, cats = [], defaultdict(list)
    for sec in secs:
        head, _, body = sec.partition('\n')
        m = re.match(r'(R\d+)', head.strip())
        if not m:
            continue
        rid = m.group(1)
        if not (lo <= num(rid) <= hi):
            continue
        title = head.split('：', 1)[-1].strip()[:60]
        concl = ''
        mm = re.search(r'\*\*结论\*\*[：:]\s*(.+?)(?:\n\n|\Z)', body, re.S)
        if mm:
            concl = re.sub(r'\s+', ' ', mm.group(1)).strip()[:110]
        rows.append((rid, title, concl))
        for name, keys in CATS:
            if any(k in head or k in concl for k in keys):
                cats[name].append((rid, title))

    out = [f'# 阶段小结（{a.start}–{a.end}）', '',
           f'* 覆盖 **{len(rows)}** 轮（来源：`ROADMAP.md`；分类由关键词命中，一轮可属多类）', '',
           '| 类别 | 轮数 | 轮次 |', '|---|---|---|']
    for name, _k in CATS:
        rs = cats.get(name, [])
        out.append(f"| {name} | {len(rs)} | {'、'.join(r for r, _t in rs[:12])}"
                   + ('…' if len(rs) > 12 else '') + ' |')
    out += ['', '## 逐轮一句话', '', '| 轮次 | 主题 | 结论 |', '|---|---|---|']
    for rid, title, concl in rows:
        out.append(f'| **{rid}** | {title} | {concl} |')
    out += ['', '**怎么用**：哪一类偏少，通常就是接下来该补的方向；'
            '某类集中在少数几轮、但反复出现在"结论"里，说明它影响力大。', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'PHASE_SUMMARY.md')
    open(target, 'w').write(text)
    print(f'[day] -> {target}（{len(rows)} 轮）')
    for name, _k in CATS:
        print(f'  {name}: {len(cats.get(name, []))} 轮')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
