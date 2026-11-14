#!/usr/bin/env python3
"""
kuaidui-kit / bridge_shape_diff.py — 桥动作的**参数形状**跨版本对比（名字不变 ≠ 契约不变）。

为什么需要
────────────
`version_diff.py` 只会告诉你"桥动作 231 个，一个没增没减"。但**参数形状会变**：
同一个 `core_httpRequest` 可能加了字段、`app_kdzy_getAbTest` 可能换了 key 名。
模块的 `bridge_action_log` / `bridge_guard` 是按形状做判定的，形状一变就会静默失效。

判据
  * 每份抓取里 `H5BRIDGE <action> count=N <json>` 的 JSON **顶层 key 集合**
    （以及 `params` / `data` 这类容器里的一层 key）
  * 同名 action 在两侧的 key 集合取差：`only_old` / `only_new`
  * 只在一侧出现的 action 单独列出（可能是新增能力面，也可能是这轮没走到）

    python3 kit/scripts/bridge_shape_diff.py \
        --old 'work/packs/*/capture.txt' --new /tmp/cap710.txt \
        --out work/reverse710/BRIDGE-SHAPE.md

覆盖边界：只比"出现过"的动作 —— 没出现在某侧的 action 是 `unknown`（这轮没走到那条路径），
不是"不存在"。抓取是抽样，不是全量菜单。
"""
import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINE = re.compile(r'^\d\d:\d\d:\d\d\.\d+\s+H5BRIDGE\s+(\S+)\s+count=(\d+)\s+(\{.*)$')
CONTAINERS = ('params', 'data', 'body', 'args')


def collect(paths):
    """{action: {top_keys: set, inner_keys: set, n: int}}"""
    out = {}
    for p in paths:
        with open(p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                m = LINE.match(ln)
                if not m:
                    continue
                action, cnt, raw = m.group(1), int(m.group(2)), m.group(3)
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                rec = out.setdefault(action, {'top': set(), 'inner': set(), 'n': 0})
                rec['n'] += cnt
                if isinstance(obj, dict):
                    rec['top'] |= set(obj.keys())
                    for c in CONTAINERS:
                        v = obj.get(c)
                        if isinstance(v, dict):
                            rec['inner'] |= set(v.keys())
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', required=True, help='旧版抓取 glob（如 work/packs/*/capture.txt）')
    ap.add_argument('--new', required=True, help='新版抓取 glob 或单文件')
    ap.add_argument('--out', default=None, help='Markdown 报告路径')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv[1:])

    old_paths = sorted(glob.glob(os.path.join(ROOT, a.old))) if '*' in a.old \
        else sorted(glob.glob(a.old))
    new_paths = sorted(glob.glob(os.path.join(ROOT, a.new))) if '*' in a.new \
        else sorted(glob.glob(a.new))
    if not old_paths or not new_paths:
        print(f'[bridge] 抓取不足：old={len(old_paths)} new={len(new_paths)}', file=sys.stderr)
        return 2

    A = collect(old_paths)
    B = collect(new_paths)
    print(f'[bridge] 旧侧 {len(old_paths)} 份 → {len(A)} 个动作；新侧 {len(new_paths)} 份 → {len(B)} 个动作')

    only_old = sorted(set(A) - set(B))
    only_new = sorted(set(B) - set(A))
    same = sorted(set(A) & set(B))

    rows = []
    for act in same:
        top_o, top_n = A[act]['top'], B[act]['top']
        inn_o, inn_n = A[act]['inner'], B[act]['inner']
        rows.append({
            'action': act,
            'n_old': A[act]['n'], 'n_new': B[act]['n'],
            'top_only_old': sorted(top_o - top_n), 'top_only_new': sorted(top_n - top_o),
            'inner_only_old': sorted(inn_o - inn_n), 'inner_only_new': sorted(inn_n - inn_o),
        })
    changed = [r for r in rows
               if r['top_only_old'] or r['top_only_new'] or r['inner_only_old'] or r['inner_only_new']]

    print(f'[bridge] 同名动作 {len(same)}；形状有差 {len(changed)}；只在旧侧 {len(only_old)}；只在新侧 {len(only_new)}')

    md = ['# 桥动作参数形状对比（A6）', '',
          f'> 旧侧：{len(old_paths)} 份抓取 → **{len(A)}** 个动作；新侧：{len(new_paths)} 份 → **{len(B)}** 个动作',
          '> 口径：`H5BRIDGE <action> count=N <json>` 的顶层 key + `params/data/body/args` 的一层 key',
          '', '## 1. 形状有变化的同名动作', '']
    if changed:
        md += ['| action | 只在旧侧有的 key | 只在新侧有的 key | 调用次数 旧→新 |', '|---|---|---|---|']
        for r in changed:
            md.append(f"| `{r['action']}` | {', '.join(f'`{k}`' for k in r['top_only_old'] + r['inner_only_old']) or '—'} "
                      f"| {', '.join(f'`{k}`' for k in r['top_only_new'] + r['inner_only_new']) or '—'} "
                      f"| {r['n_old']} → {r['n_new']} |")
    else:
        md.append('**同名动作的 key 集合完全一致**（`observed`）—— 模块按形状做的判定不会因升级失效。')
    md += ['', '## 2. 只在一侧出现', '',
           f"* 只在旧侧（{len(only_old)}）：{', '.join(f'`{x}`' for x in only_old) or '—'}",
           f"* 只在新侧（{len(only_new)}）：{', '.join(f'`{x}`' for x in only_new) or '—'}",
           '', '> 只在一侧出现 ⇒ `unknown`：可能是这轮没走到那条路径（抓取是抽样），',
           '> 也可能是真增删。要判定必须看两侧的页面覆盖，不能直接读成"新增能力"。',
           '', '## 3. 复跑命令', '', '```bash',
           "python3 kit/scripts/bridge_shape_diff.py --old 'work/packs/*/capture.txt' \\",
           '    --new /tmp/cap710.txt --out work/reverse710/BRIDGE-SHAPE.md', '```']

    text = '\n'.join(md) + '\n'
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'[bridge] 报告 -> {a.out}')
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'changed': changed, 'only_old': only_old, 'only_new': only_new}, f,
                      ensure_ascii=False, indent=1)
        print(f'[bridge] json -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
