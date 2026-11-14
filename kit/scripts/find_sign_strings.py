#!/usr/bin/env python3
"""
kuaidui-kit / find_sign_strings.py — close the last unknown of `libbaseutil.so nativeGetSign`.

Static disassembly (work/native_reversal.md §5) gives the shape:

    x0  = [G+0x10]            (post-index load: x22 becomes G+0x20)
    B2  = md5_hex(x0)
    out = asprintf("%s[%s]@%s", x22, B2, param)
    sign = md5_hex(out)                          G = libbaseutil base + 0xa238

but the two runtime strings inside that composition are heap objects the process
creates at init, so they cannot be read from outside — except through root:
this script reads the **live process memory** (`dd if=/proc/<pid>/mem` via `su`),
harvests every candidate string reachable from the `G` struct, and then brute-forces
which ordered pair reproduces a captured `(param, sign)` pair exactly.

Inputs: one `NativeProbe SIGNPARAM param=… sign=…` line from the KdKit capture
(`/data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt`), and the `NativeProbe:
libbaseutil.so base=0x…` line for **the same pid**.

    python3 find_sign_strings.py --adb emulator-5558 --pid 1234 --base 0x72cc262000 \
        --capture cap.txt [--json out.json]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import memread
import kd_api
import argparse
import base64
import hashlib
import re
import sys


def read_mem(serial, pid, addr, length):
    return memread.read_mem(serial, pid, addr, length)   # 2026-11-03：三份收敛成一处
    # **这一份原来没有 `-w0` 的兜底** ⇒ 同上。


def md5hex(b):
    return hashlib.md5(b).hexdigest()


def cstr(blob):
    nul = blob.find(b'\x00')
    raw = blob[:nul] if nul > 0 else blob
    if not raw or len(raw) > 200:
        return None
    try:
        s = raw.decode('utf-8')
    except UnicodeDecodeError:
        return None
    if any(ord(c) < 0x20 for c in s):
        return None
    return s


def inline_runs(blob, minlen=4):
    out, cur = [], bytearray()
    for b in blob:
        if 0x20 <= b < 0x7f or b > 0x7f:
            cur.append(b)
        else:
            if len(cur) >= minlen:
                out.append(cur.decode('utf-8', 'replace'))
            cur = bytearray()
    if len(cur) >= minlen:
        out.append(cur.decode('utf-8', 'replace'))
    return out


def harvest(serial, pid, start, depth=2, span=0x100, seen=None):
    """Collect candidate strings reachable from [start, start+span)."""
    seen = seen if seen is not None else set()
    blob = read_mem(serial, pid, start, span)
    cands = set(inline_runs(blob))
    if depth <= 0 or not blob:
        return cands
    for off in range(0, len(blob) - 7, 8):
        v = int.from_bytes(blob[off:off + 8], 'little')
        for p in (v, v & 0x00FFFFFFFFFFFFFF):     # raw and top-byte-ignored
            if not (0x1000 < p < 0x800000000000) or p in seen:
                continue
            seen.add(p)
            s = cstr(read_mem(serial, pid, p, 200))
            if s:
                cands.add(s)
            cands |= harvest(serial, pid, p, depth - 1, 0x80, seen)
    return cands


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--pid', required=True)
    ap.add_argument('--base', required=True, help='libbaseutil base (0x…) — use the run that was captured')
    ap.add_argument('--capture', required=True)
    ap.add_argument('--json')
    a = ap.parse_args(argv[1:])

    text = textio.read_text(a.capture)       # 2026-11-03：--capture 可给 .txt.gz
    m = re.search(r'SIGNPARAM param=(\S+) sign=([0-9a-f]{32})', text)
    if not m:
        print('[find] no "NativeProbe SIGNPARAM param=… sign=…" line in the capture')
        return 2
    param, sign = m.group(1), m.group(2)
    print(f'[find] param={len(param)} chars  sign={sign}')

    g = int(a.base, 0) + 0xa238
    print(f'[find] G=0x{g:x}')
    blob = read_mem(a.adb, a.pid, g, 0x100)
    if not blob:
        print('[find] cannot read G (wrong pid/base?)')
        return 3
    for off in range(0, len(blob), 16):
        print(f'  {g + off:012x}  ' + ' '.join(f'{b:02x}' for b in blob[off:off + 16]))

    cands = harvest(a.adb, a.pid, g, depth=2)
    cands = sorted(c for c in cands if c and len(c) <= 200)
    print(f'[find] {len(cands)} candidate string(s):')
    for c in cands:
        print(f'    {c!r}')

    hits = []
    for x in cands:
        for at in cands:
            # 2026-11-03：公式收敛到 `kd_api.sign_digest`（代码审查 P2：
            # 同一段 md5 链在四个文件各写一遍，P0-5 正是"有一处没跟着改"造成的）。
            if kd_api.sign_digest(at, x, param) == sign:
                hits.append((at, x))
                print(f'[find] *** MATCH *** A={at!r}  X={x!r}')
                print(f'[find]     sign = md5( A + "[" + md5(X) + "]@" + param )')
    if not hits:
        print('[find] no ordered pair reproduced the sign — widen --depth or check the pid/base pairing')
        return 1
    if a.json:
        import json
        json.dump({'param': param, 'sign': sign, 'pairs': hits}, open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'[find] result -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
