#!/usr/bin/env python3
"""
kuaidui-kit / so_detect_scan.py — 在 APK 的全部 arm64 库里扫"检测类字符串"，并区分
「串存在」与「串被代码引用」。

为什么需要这两列分开
────────────────────
`libdpsdk.so` 的 `TracerPid` / `magisk` / `xposed` 等串在 `.text` 里**没有内联引用**
（`adrp page` + `add #low12` 搜不到），但 `work/dpsdk/FINDINGS.md` 已实测它有反调试。
⇒ **"串在库里"不等于"这段代码在用"**，而"代码在用"才是检测面。

判据（本脚本输出的两列）
  * `STRING`  — 串是否出现在该库（`observed`，直接搜字节）
  * `REFS`    — 是否有 `adrp xD, page` + `add xD, xD, #low12` 组合指向它（`observed`，
                覆盖内联寻址；寄存器/数据表/解密段不在覆盖内 ⇒ 0 不代表"不存在"）

    python3 kit/scripts/so_detect_scan.py                  # 扫 work/apktool_out/lib/arm64-v8a
    python3 kit/scripts/so_detect_scan.py --lib <dir> --json work/so_detect.json
    python3 kit/scripts/so_detect_scan.py --no-refs        # 只报串存在（快）

覆盖边界（写在这里而不是注释里，因为它是结论的一部分）：
  * 只扫 arm64；其它 ABI 的库不参与
  * 只认 `adrp+add`；`ldr` 字面池、重定位表、运行时寄存器供给都不覆盖
"""
import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_LIB = os.path.join(ROOT, 'work', 'apktool_out', 'lib', 'arm64-v8a')

# 检测面词汇。**刻意限制在"安全检测"语义**，不收 `detect`/`root` 这种会在
# `loss detection`、`Root CA` 上误命中的词（那是 A1 第一轮的教训）。
PATS = [
    rb'magisk', rb'/sbin/su', rb'/system/bin/su', rb'/system/sbin/su',
    rb'TracerPid', rb'/proc/self/status', rb'frida', rb'xposed',
    rb'/data/adb', rb'supersu', rb'busybox',
]


def find_objdump():
    import glob
    cands = sorted(glob.glob(os.path.expanduser(
        '~/Library/Android/sdk/ndk/*/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-objdump')))
    return cands[-1] if cands else 'llvm-objdump'


OD = find_objdump()


def string_offsets(path):
    """一次读入（`with open`，不靠 CPython 引用计数）——门禁 ㉧ 盯的就是循环里的裸 open。"""
    with open(path, 'rb') as f:
        data = f.read()
    out = []
    for pat in PATS:
        for m in re.finditer(pat, data):
            out.append((m.group(0).decode('latin1'), m.start()))
    return out, len(data), hashlib.sha256(data).hexdigest()[:16]


ADRP = re.compile(r'\s*([0-9a-f]+):\s+adrp\s+(x\d+),\s+0x([0-9a-f]+)')
_ADD_CACHE = {}


def add_targets(path):
    """{target_addr: [insn_addr, ...]}，target = adrp page + add imm。"""
    if path in _ADD_CACHE:
        return _ADD_CACHE[path]
    asm = subprocess.run([OD, '-d', '--no-show-raw-insn', path],
                         capture_output=True, text=True, errors='replace',
                         timeout=180).stdout
    res = collections.defaultdict(list)
    cur = None
    for ln in asm.splitlines():
        m = ADRP.match(ln)
        if m:
            cur = (m.group(1), m.group(2), int(m.group(3), 16))
            continue
        if cur:
            reg = cur[1]
            m2 = re.match(r'\s*([0-9a-f]+):\s+add\s+%s,\s+%s,\s+#0x([0-9a-f]+)' % (reg, reg), ln)
            if m2:
                res[cur[2] + int(m2.group(2), 16)].append(cur[0])
                cur = None
                continue
            # 字面池重载：adrp xD, page; ldr xD, [xD, #imm] —— 2026-11-09 补，原实现漏了这一形
            m3 = re.match(r'\s*([0-9a-f]+):\s+ldr\s+%s,\s+\[%s,\s*#0x([0-9a-f]+)\]' % (reg, reg), ln)
            if m3:
                res[cur[2] + int(m3.group(2), 16)].append(cur[0])
                cur = None
                continue
            if re.match(r'\s*[0-9a-f]+:\s+(b|bl|ret)\b', ln):
                cur = None
    _ADD_CACHE[path] = res
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lib', default=DEFAULT_LIB, help='arm64 库目录')
    ap.add_argument('--json', default=None)
    ap.add_argument('--no-refs', action='store_true', help='跳过反汇编（只报串存在）')
    a = ap.parse_args()

    if not os.path.isdir(a.lib):
        print(f'[so] 目录不存在：{a.lib}（先 apktool d 出 lib/）', file=sys.stderr)
        return 2

    rows = []
    for f in sorted(os.listdir(a.lib)):
        if not f.endswith('.so'):
            continue
        p = os.path.join(a.lib, f)
        hits, size, sha = string_offsets(p)
        if not hits:
            continue
        refs = {} if a.no_refs else add_targets(p)
        for s, off in hits:
            rows.append({
                'lib': f, 'size': size, 'sha256_16': sha, 'string': s, 'offset': hex(off),
                'refs': refs.get(off, []),
                'verdict': 'REF' if refs.get(off) else 'STRING-ONLY',
            })

    by_lib = collections.defaultdict(list)
    for r in rows:
        by_lib[r['lib']].append(r)

    print(f'[so] 扫了 {len([x for x in os.listdir(a.lib) if x.endswith(".so")])} 个库，'
          f'{len(by_lib)} 个含检测类串，共 {len(rows)} 条命中')
    for lib, rs in sorted(by_lib.items()):
        nref = sum(1 for r in rs if r['verdict'] == 'REF')
        print(f'\n== {lib}  ({rs[0]["size"]//1024} KB, {nref} 条有引用 / {len(rs)} 条命中)')
        for r in rs:
            mark = 'REF' if r['verdict'] == 'REF' else '   '
            print(f'  {mark} {r["string"]:34s} off={r["offset"]:9s} refs={r["refs"][:3]}')
    if a.json:
        json.dump(rows, open(a.json, 'w'), ensure_ascii=False, indent=1)
        print(f'\n[so] json -> {a.json}')
    print('\n[so] 提醒：REFS 只覆盖内联 `adrp+add`；0 引用 ≠ 不存在（见脚本头部的覆盖边界）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
