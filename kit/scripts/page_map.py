#!/usr/bin/env python3
"""
kuaidui-kit / page_map.py — 把 `work/baselines/path_*.json` 合成"页面地图"。

每条基线都是"从冷启开始、走到某个页面"的稳定端点集合。它们互为对照：
**差集就是那个页面引入的接口**。这个脚本把这件事自动化 —— 加一条基线，地图自己长一格。

    python3 kit/scripts/page_map.py [--out work/PAGE_MAP.md]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def label_of(path, data):
    steps = (data.get('steps') or '').strip('"').strip()
    return steps if steps else '冷启 + 首页'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    files = sorted(glob.glob(os.path.join(ROOT, 'work', 'baselines', 'path_*.json')))
    pages = []
    for f in files:
        d = json.loads(textio.read_text(f, encoding='utf-8'))
        pages.append({'file': os.path.basename(f), 'label': label_of(f, d),
                      'eps': set(d.get('endpoints') or []),
                      'cond': set((d.get('conditional') or {}).keys()),
                      'cond_map': d.get('conditional') or {}})
    if not pages:
        print('[map] 没有基线')
        return 2

    core = next((p for p in pages if p['label'].startswith('冷启')), pages[0])
    union = set().union(*(p['eps'] for p in pages))
    all_cond = set().union(*(p['cond'] for p in pages))

    out = ['# 请求面 · 页面地图（自动生成）', '',
           '* 来源：`work/baselines/path_*.json`（每条基线 = 从冷启走到某个页面的稳定端点集合）',
           '* 生成：`python3 kit/scripts/page_map.py`（每个证据包会自动刷新）', '',
           '| 页面 | 端点 | 相对核心面（' + core['label'] + '）的增量 | 基线文件 |',
           '|---|---|---|---|']
    for p in pages:
        inc = sorted(p['eps'] - core['eps'])
        inc_txt = '—（核心面）' if p is core else ('**+0**（无新增）' if not inc else
                                                  '<br>'.join(f'`{x}`' for x in inc))
        out.append(f"| {p['label']} | {len(p['eps'])} | {inc_txt} | `work/baselines/{p['file']}` |")
    out += ['', f'* {len(pages)} 面并集：**{len(union)}** 条端点']
    if all_cond:                      # 条件性调用紧跟并集，别插到"怎么读"后面（读起来顺）
        reasons = {}
        for p in pages:
            reasons.update(p['cond_map'])
        out.append('* 条件性调用（不计入端点集合）：' + str(len(all_cond)) + ' 条')
        for c in sorted(all_cond):
            out.append(f'  * `{c}`：{reasons.get(c, "（未记原因）")}')
    out += ['', '**怎么读**：核心面（冷启+首页）已包含大部分请求；功能页的差集就是它的"特有接口"。',
            '**加一格**：`path_diff.py --adb-a <s> --adb-b <s> --steps "<页面入口文案>" --repeat 2 '
            '--save-baseline work/baselines/path_<名字>.json`，然后跑一次证据包。', '']
    text = '\n'.join(x for x in out if x is not None) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'PAGE_MAP.md')
    textio.write_text(target, text)
    print(f'[map] -> {target}')
    print('\n'.join(out[4:9]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
