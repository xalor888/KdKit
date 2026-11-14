#!/usr/bin/env python3
"""
kuaidui-kit / surface_trends.py —— **八张面的历史趋势**（2026-10-12）。

`trend_report.py` 管"门与体积" ✓；本工具管**八张面各自的数字** ✓：
从每个包的 `index.md` 里抽关键数字 ✓，按轮次排开 ✓ ⇒ "**某张面从哪一轮起开始动**" 一眼可见 ✓。

    python3 kit/scripts/surface_trends.py [--last 12] [--out work/SURFACE_TRENDS.md]
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PACKS = os.path.join(ROOT, 'work', 'packs')

# 面 → 从 index.md 里抽数字的正则（能抽到就算"这一面有值" ✓）
PATTERNS = [
    ('① 请求面（离线复现率）', r'离线复现率`\s*\|\s*\*\*(\d+)/(\d+)\*\*', 'r'),
    ('② 服务端形状', r'server_shape（服务端形状）`\s*\|\s*变化\s*(\d+)', 'n'),
    ('③ 输入身份（监控自检）', r'监控自检（注入）`\s*\|\s*([^\n|]{0,26})', 's'),
    ('④ 应用版本', r'应用版本守卫`\s*\|\s*([^\n|]{0,26})', 's'),
    ('⑤ 页面内部结构', r'页面内部结构（Vue 方法表）`\s*\|\s*([^\n|]{0,26})', 's'),
    ('⑥ 服务端内容（稳定集合）', r'稳定集合变化\s*\*\*(\d+)\*\*', 'n'),
    ('⑥b 结构形态变化', r'结构形态变化\s*[:：]?\s*(\d+)', 'n'),
    ('⑦ 特性开关（开/关）', r'特性开关`\s*\|\s*开\s*(\d+)\s*/\s*关\s*(\d+)', 'r'),
    ('⑧ 模块触发面（未触发）', r'未触发\s*(\d+)', 'n'),
    ('⑨ AB 表结构', r'AB 实验表`\s*\|\s*(\d+ 条[^|]{0,40})', 's'),
]


def read_one(path):
    txt = open(path, encoding='utf-8', errors='replace').read()
    out = {}
    for name, pat, kind in PATTERNS:
        m = re.search(pat, txt)
        if not m:
            continue
        out[name] = '/'.join(m.groups()) if kind == 'r' else (m.group(1) if kind == 'n' else m.group(1).strip())
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--last', type=int, default=12)
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'SURFACE_TRENDS.md'))
    a = ap.parse_args(argv[1:])
    files = sorted(glob.glob(os.path.join(PACKS, '*', 'index.md')), key=os.path.getmtime)[-a.last:]
    rows = [(f.split('/')[-2], read_one(f)) for f in files]
    names = [n for n, _p, _k in PATTERNS]
    lines = ['# 八张面的历史趋势', '', f'最近 **{len(rows)}** 个包 ✓（每列一个包 ✓，从旧到新 ✓）', '']
    for n in names:
        vals = [r.get(n, '—') for _t, r in rows]
        if all(v == '—' for v in vals):
            lines.append(f'* **{n}**：本窗口内无数据（该面是后加的 ✓）')
            continue
        lines.append(f'* **{n}**：`' + '` → `'.join(vals) + '`')
    lines += ['', '读法 ✓：**"→"左边越靠前 = 越早的包** ✓；某面数字**从某轮起变化** ⇒ 那一轮发生了什么 ✓'
              '（对照 `ROADMAP.md` 同轮日志 ✓）。', '']
    open(a.out, 'w').write('\n'.join(lines) + '\n')
    print(f'[surfaces] -> {a.out}（{len(rows)} 个包 × {len(names)} 张面）')
    for n in names[:3]:
        vals = [r.get(n, '—') for _t, r in rows][-4:]
        print(f'   {n}: {vals}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
