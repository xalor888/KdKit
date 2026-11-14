#!/usr/bin/env python3
"""
kuaidui-kit / method_diff.py — 两版之间**逐方法**判定"实现到底变没变"。

为什么需要
────────────
类集合的 diff 只能回答"类在不在"。适配新版本时真正的问题是：
**我钩的那个方法，它的实现还和上一版一样吗？** 一种常见情况是整棵树有成千上万个
文件"内容不同"，但逐方法去调试指令后只剩一条 `const/16`（Robust 的 PatchProxy
方法索引）在平移 —— 这种情况下钩子名字与调用点都没动，模块不需要改。
7.10.0→7.10.2 实测：`const` 平移 +1/+2，没有任何真实逻辑改动被这条判据放过。

判据（三层，从强到弱）
  IDENTICAL   去调试指令后逐行相同
  CONST-SHIFT 差异行只有 `const*` 立即数（值可不同），且行数一致 ⇒ 只有插桩索引/常量在动
  CHANGED     其余一切差异（行数变化、指令变化、寄存器/分支变化）

    python3 kit/scripts/method_diff.py \
        --old work/apktool_out --new work/apktool_out_7102 \
        --targets work/reverse7102_targets.json \
        --json work/reverse7102/method_diff.json

    # 不带 --targets ⇒ 全树逐方法（61k 类，慢，约数分钟）；适配时用 --targets 更实用。
    python3 kit/scripts/method_diff.py --old A --new B --all --json out.json

覆盖边界：只看 `.method` 块；字段、注解、类级指令（`<clinit>` 之外的静态初始化）不参与判据。
`--targets` 读 `check_hook_targets.py --json` 的产物（取 `rows[].class` / `rows[].method`）。
"""
import argparse
import collections
import json
import os
import re
import sys

DBG = re.compile(r'^\s*\.(line|local|end local|param|end param|prologue|restart local)\b')
METHOD = re.compile(r'\s*\.method\s+(.*)$')
END = re.compile(r'\s*\.end method\s*$')
CONST = re.compile(r'^(\s*const(?:/4|/16|/high16|/wide|/wide16|/wide32)?\s+v\d+,\s+)(?:-?0x[0-9a-fA-F]+|-?\d+)(.*)$')
COMMENT = re.compile(r'\s*#.*$')


def smali_files(root):
    out = []
    for d, _, fs in os.walk(root):
        for f in fs:
            if f.endswith('.smali'):
                out.append(os.path.join(d, f))
    return out


def methods_of(path):
    """{签名归一化: [原始行]} —— 签名取 `.method` 行去掉 access flags 前的部分。"""
    out = {}
    sig = None
    buf = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if sig is None:
                m = METHOD.match(ln)
                if m:
                    sig = re.sub(r'\s+', ' ', m.group(1).strip())
                    buf = []
                continue
            if END.match(ln):
                out.setdefault(sig, buf)
                sig = None
                continue
            if DBG.match(ln):
                continue
            buf.append(ln.rstrip('\n'))
    return out


def norm_body(lines):
    """去注释、抹掉 const 立即数 ⇒ 只留指令形状。"""
    out = []
    for ln in lines:
        ln = COMMENT.sub('', ln).rstrip()
        m = CONST.match(ln)
        if m:
            ln = m.group(1) + '@' + m.group(2)
        out.append(ln)
    return out


def const_deltas(a, b):
    """行数一致时，逐行取 const 立即数差；返回 Counter，非 const 差异返回 None。"""
    d = collections.Counter()
    for la, lb in zip(a, b):
        ma, mb = CONST.match(COMMENT.sub('', la).rstrip()), CONST.match(COMMENT.sub('', lb).rstrip())
        if ma and mb:
            va = int(re.split(r',\s*', ma.group(0))[1].split()[0], 0)
            vb = int(re.split(r',\s*', mb.group(0))[1].split()[0], 0)
            d[vb - va] += 1
        elif COMMENT.sub('', la).rstrip() != COMMENT.sub('', lb).rstrip():
            return None
    return d


def split_class(desc):
    """`dj.a` 或 `Ldj/a;` -> `dj/a` 路径片段。"""
    desc = desc.strip()
    if desc.startswith('L') and desc.endswith(';'):
        desc = desc[1:-1]
    return desc.replace('.', '/')


def method_path(root, cls, name):
    """在解包树里找真正含这个类的 smali 文件（smali / smali_classesN）。"""
    rel = split_class(cls)
    base, _, clsname = rel.rpartition('/')
    cand = [os.path.join(root, 'smali', rel + '.smali')]
    for d, _, fs in os.walk(root):
        bn = os.path.basename(d)
        if not bn.startswith('smali'):
            continue
        full = os.path.join(d, rel + '.smali')
        if os.path.exists(full):
            cand.append(full)
    cand = [c for c in cand if os.path.exists(c)]
    if not cand:
        # 外层类不够用时按文件名兜底（内部类场景不在这里处理）
        for d, _, fs in os.walk(root):
            if os.path.basename(d).startswith('smali') and clsname + '.smali' in fs:
                cand.append(os.path.join(d, clsname + '.smali'))
        cand = [c for c in cand if os.path.exists(c)]
    return cand[0] if cand else None


def own_sig(sigs, name):
    """从签名集合里挑出这个名字的方法（可能与多个重载并存）。"""
    hits = [s for s in sigs if re.match(r'^\S*\s*' + re.escape(name) + r'\(', s) or s.split(' ')[-1].startswith(name + '(')]
    return sorted(hits)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', required=True)
    ap.add_argument('--new', required=True)
    ap.add_argument('--targets')
    ap.add_argument('--all', action='store_true', help='全树逐方法（慢）')
    ap.add_argument('--json')
    ap.add_argument('--max-print', type=int, default=40)
    a = ap.parse_args(argv[1:])

    rows = []
    if a.targets:
        t = json.load(open(a.targets, encoding='utf-8'))
        for r in t.get('rows', t if isinstance(t, list) else []):
            rows.append((r.get('class'), r.get('method'), r.get('where')))
    elif a.all:
        for f in smali_files(a.old):
            rel = os.path.relpath(f, a.old)[:-len('.smali')]
            parts = rel.split('/')
            rows.append(('/'.join(parts[1:]), '', rel))
        rows = [(c, '', w) for (c, m, w) in rows]
    else:
        print('need --targets or --all', file=sys.stderr)
        return 2

    counts = collections.Counter()
    detail = []
    cache = {}
    for cls, mname, where in rows:
        if cls is None:
            continue
        key = (cls,)
        if key not in cache:
            p_old = method_path(a.old, cls, mname or '')
            p_new = method_path(a.new, cls, mname or '')
            if not p_old or not p_new:
                cache[key] = (None, None)
            else:
                cache[key] = (methods_of(p_old), methods_of(p_new))
        mo, mn = cache[key]
        if mo is None:
            counts['CLASS-GONE'] += 1
            detail.append({'class': cls, 'method': mname, 'where': where, 'verdict': 'CLASS-GONE'})
            continue
        if mname:
            sigs = own_sig(mo, mname) or own_sig(mn, mname)
        else:
            sigs = sorted(set(mo) | set(mn))
        for sig in sigs:
            if sig not in mn:
                v = 'METHOD-GONE'
            elif sig not in mo:
                v = 'METHOD-NEW'
            else:
                # 判据顺序严格：先"完全相同"，再"只有常量不同"，最后才看逐行常量差。
                # 2026-11-14 的测试（kit/python/tests/test_method_diff.py）抓到过一版 bug：
                # 旧实现在"行数不同"时仍用 zip 逐行取常量差，多余的行被 zip 静默丢掉，
                # 于是"多了一条指令"被判成 CONST-SHIFT（工具永远输出 CHANGED=0）。
                bo, bn = mo[sig], mn[sig]
                d = None
                if bo == bn:
                    v = 'IDENTICAL'
                elif norm_body(bo) == norm_body(bn):
                    v = 'CONST-SHIFT'
                    d = const_deltas(bo, bn)
                elif len(bo) == len(bn) and const_deltas(bo, bn) is not None:
                    v = 'CONST-SHIFT'
                    d = const_deltas(bo, bn)
                else:
                    v = 'CHANGED'
                if v == 'CONST-SHIFT' and d:
                    detail.append({'class': cls, 'method': mname, 'sig': sig, 'where': where,
                                   'verdict': v, 'deltas': d.most_common(4)})
                    counts[v] += 1
                    continue
            detail.append({'class': cls, 'method': mname, 'sig': sig, 'where': where, 'verdict': v})
            counts[v] += 1

    print('[mtdiff] ' + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    shown = 0
    for d in detail:
        if d['verdict'] in ('IDENTICAL', 'CONST-SHIFT'):
            continue
        if shown >= a.max_print:
            print(f'  … 另有 {len([x for x in detail if x["verdict"] not in ("IDENTICAL","CONST-SHIFT")]) - shown} 条')
            break
        print(f"  {d['verdict']:22s} {d['class']}.{d['method']}  {d.get('sig','')[:70]}  ({d['where']})")
        shown += 1
    if a.json:
        os.makedirs(os.path.dirname(a.json) or '.', exist_ok=True)
        json.dump({'counts': dict(counts), 'rows': detail}, open(a.json, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'[mtdiff] json -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
