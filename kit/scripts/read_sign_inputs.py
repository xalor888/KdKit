#!/usr/bin/env python3
"""
kuaidui-kit / read_sign_inputs.py — read the two runtime sign inputs straight out of a
live `libbaseutil.so`, with no instrumentation of the app at all.

Closes `work/native_reversal.md` §5: the sign composition is

    sign = md5( A + "[" + md5hex(X) + "]@" + param )

    A = the 5 bytes the library keeps inline at  G + 0x10   ("8&%d*" on 7.7.2)
    X = the C string the pointer at                G + 0x00   points to
    G = <libbaseutil.so load base> + 0xa238                 (paddr == vaddr in this ELF)

Both live in the library's .bss, filled at init from the server-issued token; they are
per-install data, not constants, so they cannot be hard-coded. This script finds the
base in `/proc/<pid>/maps` and reads the two values through root.

    python3 read_sign_inputs.py --adb emulator-5558 --pid 10807
    python3 read_sign_inputs.py --adb emulator-5558 --pid 10807 \
        --capture cap.txt          # also re-compute a captured sign as a self-check
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
import subprocess
import sys

G_OFF = 0xa238


def adb(serial, *args, timeout=90):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout)


def read_mem(serial, pid, addr, length):
    return memread.read_mem(serial, pid, addr, length)   # 2026-11-03：三份收敛成一处
    # **这一份原来没有 `-w0` 的兜底** ⇒ 换台 base64 不支持 -w 的设备
    # 就静默返回 b''，而 b'' 与“那个地址没有字节”长得一样。


def lib_base(serial, pid, name='libbaseutil.so'):
    maps = adb(serial, 'cat', f'/proc/{pid}/maps').stdout
    for line in maps.splitlines():
        if line.endswith('/' + name):
            return int(line.split('-')[0], 16)
    return None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--pid', required=True)
    ap.add_argument('--capture', default=None)
    a = ap.parse_args(argv[1:])

    base = lib_base(a.adb, a.pid)
    if base is None:
        print('[sign] libbaseutil.so is not mapped in this pid — wrong process?')
        return 2
    g = base + G_OFF
    d = read_mem(a.adb, a.pid, g, 0x30)
    if len(d) < 0x30:
        print(f'[sign] cannot read G (0x{g:x}) — root? SELinux permissive?')
        return 3

    x_ptr = int.from_bytes(d[0:8], 'little') & 0x00FFFFFFFFFFFFFF
    x_raw = read_mem(a.adb, a.pid, x_ptr, 64)
    x = x_raw.split(b'\x00')[0].decode('utf-8', 'replace')
    a_str = d[0x10:0x30].split(b'\x00')[0].decode('utf-8', 'replace')

    print(f'[sign] libbaseutil base = 0x{base:x}   G = 0x{g:x}')
    print(f'[sign] A (inline @G+0x10) = {a_str!r}')
    print(f'[sign] X (ptr    @G+0x00) = {x!r}')
    print(f'[sign] md5(X)             = {hashlib.md5(x.encode()).hexdigest()}')
    print('[sign] sign = md5( A + "[" + md5(X) + "]@" + param )')

    if a.capture:
        text = textio.read_text(a.capture)   # 2026-11-03：--capture 可给 .txt.gz
        pairs = re.findall(r'SIGNPARAM param=(\S+) sign=([0-9a-f]{32})', text)
        if not pairs:
            print('[sign] capture has no SIGNPARAM line to check against')
            return 0
        ok = bad = 0
        for param, sign in pairs:
            got = kd_api.sign_digest(a_str, x, param)   # 2026-11-03：公式收敛到 kd_api
            same = got == sign
            ok, bad = (ok + 1, bad) if same else (ok, bad + 1)
            print(f'[sign] check param({len(param)}) -> {"MATCH" if same else "MISMATCH"} ({got})')
        print(f'[sign] match={ok} mismatch={bad}')
        return 0 if bad == 0 else 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
