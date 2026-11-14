#!/usr/bin/env python3
"""
kuaidui-kit / check_version_delta_documented.py — 版本差异必须**被写进文档**，否则不算适配完成。

为什么需要
────────────
`work/dex_delta_*.json` 只说"哪些类在这两版之间增删了"，它不会告诉你**它们是谁**。
7.9.0→7.10.0 的实测：116 个"新增"里 91 个只是换 dex 分包（`classes3/4/6 → classes7`），
真新增只有 15 个（`work/reverse710/NEW-CLASSES.md`）。**不做这一步的后果是**：
下一次适配的人会照着 diff 的数字去找 116 个新类，找完发现 91 个是幻觉。

判据（硬、可测、不需要人读）
  * 对 `rename_match.json` 里每一条 `NEW` / `GONE`，取它的**路径形式**（`pkg/Class`）
    与**点分全名**（`pkg.Class`）；
  * 这两个形式至少有一个出现在 `module/MIGRATION-*.md` 或 `work/reverse*/**/*.md` 里；
  * 少一条 ⇒ 红，并点名缺哪几条。

覆盖边界：只查"真增删"（`NEW`/`GONE`）。`RENAME` 有 81 条，逐条写进文档没有价值 ——
它们由 `class_rename_match.py` 的 JSON 覆盖，文档只需说明"其余是改名"。

    python3 kit/scripts/check_version_delta_documented.py
    python3 kit/scripts/check_version_delta_documented.py --json work/reverse710/rename_match.json
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOC_PATTERNS = (
    os.path.join(ROOT, 'module', 'MIGRATION-*.md'),
    os.path.join(ROOT, 'work', 'reverse*', '**', '*.md'),
)


def load_docs():
    text = []
    for pat in DOC_PATTERNS:
        for f in glob.glob(pat, recursive=True):
            with open(f, encoding='utf-8', errors='replace') as fh:
                text.append(fh.read())
    return '\n'.join(text)


def forms(relpath_or_desc, desc=None):
    """返回该类的两种可搜形式：`pkg/Class`（路径）与 `pkg.Class`（点分）。"""
    d = desc or relpath_or_desc
    if not d.startswith('L'):
        # 从 smali 路径推描述符：smali_classesN/com/foo/Bar.smali -> Lcom/foo/Bar;
        d = 'L' + relpath_or_desc.split('/', 1)[1][:-len('.smali')] + ';'
    inner = d[1:-1]
    return [inner, inner.replace('/', '.')]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', nargs='*', default=None,
                    help='rename_match.json 路径（默认自动找 work/reverse*/*.json）')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv[1:])

    files = a.json or sorted(glob.glob(os.path.join(ROOT, 'work', 'reverse*', 'rename_match*.json'),
                                       recursive=True))
    if not files:
        print('[vdoc] 没有 rename_match.json ⇒ 无法验证（不算通过，也不算失败）')
        return 2

    docs = load_docs()
    if not docs.strip():
        print('[vdoc] 没有任何 MIGRATION-*.md / work/reverse*/**/*.md 可查')
        return 1

    missing = []
    checked = 0
    for f in files:
        with open(f, encoding='utf-8') as fh:   # ㉧：循环里不许裸 open
            rows = json.load(fh)
        for r in rows:
            if r['verdict'] not in ('NEW', 'GONE'):
                continue
            checked += 1
            side = r.get('new') or r.get('old')
            desc = r.get('new_desc') or r.get('old_desc')
            cand = forms(side, desc)
            if not any(c in docs for c in cand):
                missing.append((r['verdict'], side))

    print(f'[vdoc] 检查 {checked} 条真增删（NEW/GONE），文档来源 '
          f'{len([p for pat in DOC_PATTERNS for p in glob.glob(pat, recursive=True)])} 份')
    if missing:
        print(f'[vdoc] **{len(missing)} 条没被写进文档**：')
        for v, side in missing[:20]:
            print(f'   ✗ {v:5s} {side}')
        print('[vdoc] 修法：把这几条写进 module/MIGRATION-<版本>.md 或 work/reverse<版本>/*.md')
        print('[vdoc]   理由：下一次适配的人会照着 delta 的数字去找它们；没写清楚就等于让他们找幻觉')
        return 1
    if not a.quiet:
        print('[vdoc] 真增删全部有出处 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
