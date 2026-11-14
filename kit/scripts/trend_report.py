#!/usr/bin/env python3
"""
kuaidui-kit / trend_report.py — 把"每轮的门"与"体积审计"的时间序列汇成一页趋势。

单看一轮只能说"今天行不行"；把 200+ 个证据包排起来，才能回答"**变好了还是变差了**"，
并且**自动标出回退**（曾经绿、后来红的那一格）。

    python3 kit/scripts/trend_report.py [--last 40] [--out work/TRENDS.md]
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
PACKS = os.path.join(ROOT, 'work', 'packs')
GATES = ['acceptance', 'reverify', 'baseline 首页', 'baseline AI写作', 'monitoring',
         'selftest', 'app version guard', 'page internals']


#: 明确的失败标记。**必须先查它** —— 2026-11-03 代码审查发现旧实现把
#: `FAIL 目标 App 版本不一致` 判成 **PASS**：因为 `不一致` 里含 `一致`，
#: 而旧的"通过"分支排在失败分支之前，于是一次显式的 FAIL 从来没走到判据那里。
BAD_MARKERS = ('FAIL', '未通过', '不一致', '✗', 'failed', '失败')

#: `变化 N 条` —— N 是**数量**，方向由 N 决定：0 条 = 没有漂移 = 好的。
RE_CHANGES = re.compile(r'变化\s*(\d+)\s*条')


def norm(key, val):
    """只用**证据包自己写的标记**判定，不对数字做猜。

    三种结局，与门禁同一套词汇：PASS / FAIL / SKIP（该轮没跑）。

    顺序很重要：**明确的失败标记优先**。旧实现先看"通过"分支，
    于是 `FAIL 目标 App 版本不一致` 因为含 `一致` 两个字被判 PASS ——
    一个写着 FAIL 的门值在趋势表里显示成 ✔。
    """
    v = (val or '').strip()
    if not v or v in ('-', '—'):
        return 'SKIP'
    if any(b in v for b in BAD_MARKERS):
        return 'FAIL'
    m = RE_CHANGES.search(v)
    if m:
        # `变化 0 条` = 服务端形状没有漂移 = **好的**。旧实现只要出现"变化"
        # 两个字就判 FAIL，于是每一轮正常的 `变化 0 条` 在趋势表里都是 ✘。
        return 'FAIL' if int(m.group(1)) > 0 else 'PASS'
    return 'PASS'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--last', type=int, default=40)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rows = []
    for tag in os.listdir(PACKS):
        d = os.path.join(PACKS, tag)
        if not os.path.isdir(d):
            continue
        idx = os.path.join(d, 'index.md')
        if not os.path.exists(idx):
            continue
        txt = textio.read_text(idx, encoding='utf-8', errors='replace')
        ts = re.search(r'生成时间：([\d\- :]+)', txt)
        gates = {}
        # 包里每一行是 `| \`名字\` | 值 |`
        for m in re.finditer(r'^\|\s*`([^`]+)`\s*\|\s*([^|]*)\|', txt, re.M):
            gates[m.group(1).strip()] = m.group(2).strip()
        rows.append({'tag': tag, 'ts': ts.group(1) if ts else '', 'gates': gates})
    rows.sort(key=lambda r: r['ts'] or r['tag'])
    recent = rows[-a.last:]

    hist = []
    p = os.path.join(ROOT, 'work', 'audits', 'disk_history.jsonl')
    if os.path.exists(p):
        for ln in textio.read_lines(p, encoding='utf-8'):
            try:
                d = json.loads(ln)
            except Exception:
                continue
            hist.append((d.get('ts', '')[:16], d.get('sizes', {}).get('<整个仓库>')))
    sizes = [v for _t, v in hist if v]
    growth = (sizes[-1] - sizes[0]) if len(sizes) > 1 else 0

    # 门的历史（按包的时间顺序，取最近 N 个里每个门的状态序列）
    keys = sorted({k for r in recent for k in r['gates']})
    seq = {k: [norm(k, r['gates'].get(k, '')) for r in recent] for k in keys}
    regressions = []
    for k, s in seq.items():
        for i in range(1, len(s)):
            if s[i - 1] == 'PASS' and s[i] == 'FAIL':
                regressions.append((k, recent[i]['tag']))
                break

    out = ['# 趋势（每轮的门 + 体积）', '',
           f'* {datetime.now().strftime("%Y-%m-%d %H:%M")}　证据包共 **{len(rows)}** 个；本页看最近 **{len(recent)}** 个',
           '* 读法：`✔` 绿、`✘` 红、`·` 该轮没跑；**回退**（曾经绿后来红）单独列出', '',
           '| 门 | 最近状态序列（左旧右新） |', '|---|---|']
    for k in keys:
        s = seq[k]
        line = ''.join({'PASS': '✔', 'FAIL': '✘', 'SKIP': '·'}[x] for x in s)
        out.append(f'| `{k}` | `{line}` |')
    out += ['', '## 回退（曾经绿、后来红）', '',
            '* 每条给出：**变红那一轮的门值原样**（便于当场判断是"真漂移"还是"人为改动/故意注入"）', '']
    # 2026-10-13 补 ✓（**规则 11 的第一次应用** ✓ —— 也是**规则 18**"安静必须被验证" ✓）：
    # 原先为空时**一个字都没有** ✗ ⇒ **分不清"没有回退"与"提取坏了"** ✗✓。
    # ⇒ **显式写"无"** ✓，并**带上"看的是哪几轮"** ✓。
    if not regressions:
        out += [f'* **本轮无回退** ✓（看了 {len(rows)} 轮 ✓：' +
                (rows[-1].get('tag', '?') if rows else '?') + ' 及之前 ✓）', '']
    if regressions:
        by_tag = {r['tag']: r for r in rows}
        for k, tag in regressions:
            val = by_tag.get(tag, {}).get('gates', {}).get(k, '（该轮无此门）')
            i = [r['tag'] for r in rows].index(tag)
            prev_tag = rows[i - 1]['tag'] if i > 0 else '（首轮）'
            prev_val = by_tag.get(prev_tag, {}).get('gates', {}).get(k, '')
            out += [f'* **`{k}`**：`{prev_tag}` 时 `{prev_val[:60]}` → `{tag}` 时 `{val[:110]}`']
    else:
        out.append('* 无 ✓')
    out += ['', '## 体积趋势', '',
            f'* 记录点数 {len(hist)}；首次 {sizes[0] if sizes else "?"} MB → 最新 {sizes[-1] if sizes else "?"} MB'
            f'（净 {growth:+d} MB）' if sizes else '* 暂无体积历史（跑一次 `disk_audit.py` 即有）', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'TRENDS.md')
    textio.write_text(target, text)
    print(f'[trend] -> {target}（{len(rows)} 个包，最近 {len(recent)}）')
    for k in keys[:6]:
        print(f'   {k:22s} ' + ''.join({'PASS': '✔', 'FAIL': '✘', 'SKIP': '·'}[x] for x in seq[k][-24:]))
    print(f'   回退 {len(regressions)} 处；体积 {sizes[0] if sizes else "?"}→{sizes[-1] if sizes else "?"} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
