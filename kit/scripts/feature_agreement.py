#!/usr/bin/env python3
"""
kuaidui-kit / feature_agreement.py — "**代码 = 文档**"一致性检查（2026-10-12）。

由来 ✓：本项目有一条**明示不变量** —— **代码 ✓ = `VERIFICATION.md` ✓ = 运行时日志 ✓**。
R389 实测发现 `rc4_probe` **只进了代码、没进文档** ✗ ⇒ 补上 ✓；
本脚本让"**再破坏这条不变量**" ✗ **当场报出来** ✓（同 R362 的 `ascii_lint` 思路 ✓）。

    python3 kit/scripts/feature_agreement.py            # 0 = 一致 ✓；1 = 有差异 ✗
    python3 kit/scripts/feature_agreement.py --verbose
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def code_ids():
    """从功能源码里取 id ✓（覆盖 object 定义与注册表两处 ✓）。"""
    ids = set()
    pats = [os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', '**', '*.kt')]
    for p in pats:
        for f in glob.glob(p, recursive=True):
            try:
                t = textio.read_text(f, encoding='utf-8')
            except Exception:
                continue
            ids |= set(re.findall(r'id\s*=\s*"([a-z][a-z0-9_]+)"', t))
    return ids


def doc_ids(path=None):
    t = textio.read_text(path or os.path.join(ROOT, 'module', 'VERIFICATION.md'), encoding='utf-8')
    return set(re.findall(r'^\|\s*`([a-z][a-z0-9_]+)`', t, flags=re.M))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--doc', default=None, help='改用别的文档做对照（烟测用 ✓）')
    a = ap.parse_args(argv[1:])
    c, d = code_ids(), doc_ids(a.doc)
    only_code, only_doc = sorted(c - d), sorted(d - c)
    if a.verbose:
        print(f'代码 id {len(c)} 个；文档 id {len(d)} 个')
        print(' 代码有、文档缺:', only_code or '无 ✓')
        print(' 文档有、代码缺:', only_doc or '无 ✓')
    if only_code or only_doc:
        print(f'[feature_agreement] **不一致** ✗（代码缺文档 {len(only_doc)} / 文档缺代码 {len(only_code)}）')
        if only_code:
            print('   文档里缺这些功能 ✓（去 module/VERIFICATION.md 补行）:', only_code)
        if only_doc:
            print('   代码里缺这些 id ✓（文档写了但没实现）:', only_doc)
        return 1
    print(f'[feature_agreement] 一致 ✓（代码 {len(c)} = 文档 {len(d)}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
