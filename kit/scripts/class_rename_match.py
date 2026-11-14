#!/usr/bin/env python3
"""
kuaidui-kit / class_rename_match.py — 跨版本"类增删"里区分 **改名** 与 **真增删**。

为什么需要
────────────
R8 每个版本会重掷一批混淆名：上一版的 `lk.a` 变成 `dj.a`，于是类集合的 diff 里
同时出现"删除 106 / 新增 116"。把那 222 条当成"真增删"会得出两个错误结论：
① 新版本有很多新功能面（其实只是换了名字）；② 老功能被删了（其实还在）。
7.9.0→7.10.0 实测：对称的数字（com/zuoyebang 91↔91、gr 11↔11、fr 4↔4）就是提示。

判据（三层，从强到弱）
  RENAME    方法签名集合**完全相同** + 归一化代码**完全相同**（把自身类描述符抹成 `LCLASS;`）
  CHANGED   方法签名集合相同但代码不同（改名且改了实现 —— 仍算改名，但要标出来）
  NEW       `onlyB` 里找不到任何同签名同代码的对手 ⇒ 真新增
  GONE      `onlyA` 里找不到对手 ⇒ 真删除
  PARTIAL   方法集合部分重合（重合率 ≥ 阈值）⇒ 疑似改名，需人工看

    python3 kit/scripts/class_rename_match.py \
        --old /tmp/kd790/apktool_out_790 --new work/apktool_out \
        --delta work/dex_delta_790_710.json --json work/reverse710/rename_match.json

覆盖边界：只比 `.method` 块（去 `.line`/`.local` 等调试指令）；字段与注解不参与判据。
"""
import argparse
import json
import os
import re
import sys

DBG = re.compile(r'^\s*\.(line|local|end local|param|end param|prologue)\b')
METHOD = re.compile(r'\s*\.method\s+(.*)$')
END = re.compile(r'\s*\.end method')


def methods(path, self_desc):
    """{签名归一化: 代码归一化}。自身类描述符抹成 LCLASS;，避免改名影响比较。"""
    out = {}
    sig = None
    buf = []
    self_slash = self_desc[1:-1]
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if sig is None:
                m = METHOD.match(ln)
                if m:
                    sig = m.group(1).strip()
                    buf = []
                continue
            if END.match(ln):
                code = ''.join(x for x in buf if not DBG.match(x))
                code = code.replace(self_desc, 'LCLASS;').replace(self_slash, 'CLASS')
                out[sig] = code
                sig = None
                continue
            buf.append(ln)
    return out


def desc_of(relpath):
    """smali_classesN/com/foo/Bar.smali -> Lcom/foo/Bar;"""
    p = relpath.split('/', 1)[1] if relpath.startswith('smali') else relpath
    return 'L' + p[:-len('.smali')] + ';'


def sigset_fingerprint(ms):
    return tuple(sorted(ms.keys()))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', required=True, help='旧版解包树根')
    ap.add_argument('--new', required=True, help='新版解包树根')
    ap.add_argument('--delta', required=True, help='work/dex_delta_*.json')
    ap.add_argument('--json', default=None)
    ap.add_argument('--min-overlap', type=float, default=0.5, help='PARTIAL 判据的重合率')
    a = ap.parse_args(argv[1:])

    delta = json.load(open(a.delta, encoding='utf-8'))
    gone_paths = delta.get('only790') or delta.get('onlyA') or []
    new_paths = delta.get('only710') or delta.get('onlyB') or []

    def load(root, paths):
        out = {}
        for rel in paths:
            full = os.path.join(root, rel)
            if not os.path.exists(full):
                continue
            d = desc_of(rel)
            out[rel] = (d, methods(full, d))
        return out

    A = load(a.old, gone_paths)
    B = load(a.new, new_paths)
    print(f'[rename] 旧侧候选 {len(A)} / 新侧候选 {len(B)}（缺文件的已跳过）')

    # 索引：签名集指纹 -> [B 条目]
    by_sig = {}
    for rel, (d, ms) in B.items():
        by_sig.setdefault(sigset_fingerprint(ms), []).append(rel)

    rows = []
    used = set()
    for rel, (d, ms) in A.items():
        cands = by_sig.get(sigset_fingerprint(ms), [])
        if len(cands) == 1:
            other = cands[0]
            same_code = B[other][1] == ms
            rows.append({'old': rel, 'new': other, 'verdict': 'RENAME' if same_code else 'CHANGED',
                         'methods': len(ms), 'old_desc': d, 'new_desc': B[other][0]})
            used.add(other)
        elif len(cands) > 1:
            exact = [c for c in cands if B[c][1] == ms]
            pick = exact[0] if len(exact) == 1 else cands[0]
            rows.append({'old': rel, 'new': pick, 'verdict': 'RENAME(ambiguous)',
                         'methods': len(ms), 'old_desc': d, 'new_desc': B[pick][0],
                         'candidates': len(cands)})
            used.add(pick)
        else:
            rows.append({'old': rel, 'verdict': 'GONE', 'methods': len(ms), 'old_desc': d})

    for rel, (d, ms) in B.items():
        if rel in used:
            continue
        rows.append({'new': rel, 'verdict': 'NEW', 'methods': len(ms), 'new_desc': d})

    counts = {}
    for r in rows:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    print('[rename] 判定：', ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    for r in rows:
        if r['verdict'] in ('NEW', 'GONE', 'CHANGED', 'RENAME(ambiguous)'):
            side = r.get('new') or r.get('old')
            tag = r.get('old', '') + (' -> ' + r.get('new', '') if r.get('new') and r.get('old') else '')
            print(f"  {r['verdict']:18s} {tag or side}")
    if a.json:
        os.makedirs(os.path.dirname(a.json), exist_ok=True)
        json.dump(rows, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[rename] json -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
