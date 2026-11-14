#!/usr/bin/env python3
"""
kuaidui-kit / artifact_lifecycle.py — 产物生命周期（2026-10-12）。

回答交接必问的问题：**这么多文件，哪些是"活的"**（每轮刷新 ✓）、**哪些是"沉淀"**（手工/低频 ✓）。

    python3 kit/scripts/artifact_lifecycle.py [--out work/ARTIFACT_LIFECYCLE.md]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKS = os.path.join(ROOT, 'work', 'packs')
OUT = os.path.join(ROOT, 'work', 'ARTIFACT_LIFECYCLE.md')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--window', type=float, default=5.0, help='与最近包相差多少分钟内算"随包刷新"')
    a = ap.parse_args(argv[1:])
    packs = sorted(glob.glob(os.path.join(PACKS, '*')), key=os.path.getmtime)
    if not packs:
        print('[lifecycle] 没有证据包，跳过')
        return 0
    last = os.path.getmtime(packs[-1])
    files = [f for f in sorted(glob.glob(os.path.join(ROOT, 'work', '*.md'))
                              + glob.glob(os.path.join(ROOT, 'work', '*.json'))
                              + glob.glob(os.path.join(ROOT, 'work', 'exports', '*')))
             if os.path.isfile(f)]
    auto, manual = [], []
    for f in files:
        (auto if abs(os.path.getmtime(f) - last) / 60 < a.window else manual).append(
            (os.path.basename(f), os.path.getsize(f)))
    lines = ['# 产物生命周期（哪些是"活的"）', '',
             f'`work/` 下共 **{len(files)}** 个文件 ✓ —— 与**最近一个证据包**（`{os.path.basename(packs[-1])}` ✓）的 mtime 比对 ✓：', '',
             f'## ① **每轮随包刷新**（{len(auto)} 个 ✓）—— "现在是什么样" ✓', '',
             '| 文件 | 大小 |', '|---|---|']
    for n, s in sorted(auto):
        lines.append(f'| `{n}` | {s} B |')
    # 机制接线（2026-10-12 并入 ✓）：与"哪些文件是活的"同属"什么在用"这一类问题 ✓
    mech = ['safe_io', 'tool_sanity', 'checkup', 'anchors', 'session_time',
            'artifact_lifecycle', 'assert_test', 'surface_trends', 'module_activity', 'ab_diff']
    callers = {
        '证据包': os.path.join(ROOT, 'kit', 'scripts', 'evidence_pack.py'),
        '体检': os.path.join(ROOT, 'kit', 'scripts', 'checkup.sh'),
        '烟测': os.path.join(ROOT, 'kit', 'scripts', 'tool_sanity.sh'),
        '排查表': os.path.join(ROOT, 'kit', 'ONBOARDING.md'),
        '交接': os.path.join(ROOT, 'work', 'HANDOVER.md'),
        '报告': os.path.join(ROOT, 'REPORT.md'),
    }
    texts = {}
    for _k, _f in callers.items():
        try:
            texts[_k] = textio.read_text(_f, encoding='utf-8', errors='replace')
        except Exception:
            texts[_k] = ''
    lines += ['', '## ③ 机制接线（建了，用了吗 ✓）', '',
              '| 机制 | ' + ' | '.join(callers) + ' |',
              '|---|' + '---|' * len(callers)]
    for _m in mech:
        lines.append('| `' + _m + '` | ' + ' | '.join('✓' if _m in _t else '·' for _t in texts.values()) + ' |')
    lines += ['', '读法 ✓：✓ = 接到该处 ✓；· = 未接（未必是问题 ✗ —— 有些机制本就不该到处出现 ✓）。', '']
    lines += ['', f'## ② **手工/低频**（{len(manual)} 个 ✓）—— "为什么是这样" ✓', '',
              '文档与基线（报告 ✓ / 交接说明 ✓ / 各专题 ✓ / `baselines/` ✓）—— 随轮次手工更新 ✓ 或按需更新 ✓。', '',
              '## 用法', '',
              '* **① 类看"现在"** ✓（`checkup.sh` 已把它们串成一条命令 ✓）；',
              '* **② 类看"原因"** ✓（`REPORT.md` ✓ / `work/*.md` ✓）；',
              '* 本表**每轮自动刷新** ✓（由本脚本 ✓）。', '']
    open(a.out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'[lifecycle] -> {a.out}（自动 {len(auto)} / 手工 {len(manual)}；共 {len(files)}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
