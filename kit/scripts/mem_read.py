#!/usr/bin/env python3
"""
kuaidui-kit / mem_read.py — read a live process's memory through root, from the host.

The KdKit `native_probe` feature logs the two addresses this needs
(`libbaseutil.so base=0x… G=0x…`), but an app-domain read of `/proc/self/mem` is
refused (SELinux), so the actual bytes are read from the host as root. That keeps the
in-app module simple and works for any address we can compute.

    python3 mem_read.py --adb emulator-5558 --pid 12345 --addr 0x72cc26c238 --len 384
    python3 mem_read.py ... --out work/dpsdk/gstruct.bin      # raw bytes for scripts

Prints hex + ASCII, decodes every 8-byte little-endian value that looks like a pointer
(0x1000 .. 0x8000000000) and, with `--follow`, tries to read a NUL-terminated string at
each of those addresses (one level deep).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import memread
import argparse
import base64
import sys


def read_mem(serial, pid, addr, length):
    return memread.read_mem(serial, pid, addr, length)   # 2026-11-03：三份收敛成一处


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--pid', required=True)
    ap.add_argument('--addr', required=True, help='start address (0x…)')
    ap.add_argument('--len', type=int, default=256)
    ap.add_argument('--out')
    ap.add_argument('--follow', type=int, default=1, help='follow N levels of pointers')
    ap.add_argument('--string-len', type=int, default=160)
    a = ap.parse_args(argv[1:])

    addr = int(a.addr, 0)
    data = read_mem(a.adb, a.pid, addr, a.len)
    print(f'[mem] pid={a.pid} addr=0x{addr:x} len={len(data)}')
    if not data:
        print('[mem] read returned 0 bytes (SELinux? wrong pid? unmapped?)')
        return 1

    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexs = ' '.join(f'{b:02x}' for b in chunk)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        print(f'  {addr + off:012x}  {hexs:<47}  {asc}')

    if a.out:
        open(a.out, 'wb').write(data)
        print(f'[mem] raw -> {a.out}')

    if a.follow:
        seen = set()
        for off in range(0, len(data) - 7, 8):
            p = int.from_bytes(data[off:off + 8], 'little')
            if not (0x1000 < p < 0x8000000000) or p in seen:
                continue
            seen.add(p)
            s = read_mem(a.adb, a.pid, p, a.string_len)
            nul = s.find(b'\x00')
            txt = s[:nul] if 0 < nul <= 120 else s[:60]
            printable = all(32 <= b < 127 or b > 0x7f for b in txt) if txt else False
            label = repr(txt.decode('utf-8', 'replace')) if printable and txt else f'<{s[:16].hex()}…>'
            print(f'  [ptr] +0x{off:03x} -> 0x{p:x}: {label}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
