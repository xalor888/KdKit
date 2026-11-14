#!/usr/bin/env python3
"""
kuaidui-kit / decode_token_native.py — fully offline sign reproduction from the two stored
tokens alone (no instrumentation, no root read of process memory).

The chain (established from the disassembly of `nativeSetToken`, see
work/native_reversal.md §5.1/§5.2, and verified here):

    blobA = xform(expand(KEY_ANTISPAM_SIGN_A), "@fG2SuLA", lenA/4)
      A   = blobA[0:5]                     # the per-build sign constant ("8&%d*")
      k1  = blobA[7:12]                    # 5 chars
      key2= k1 + "#G4"                     # 8-char key for the second pass
      # anti-tamper checks the library performs on blobA:
      #   len(blobA[7:17]) == 10, len(blobA[0x13:0x33]) == 32 (== md5hex(cert-derived)),
      #   blobA[0x35:] == cuid
    blobB = xform(expand(KEY_ANTISPAM_SIGN_B), key2, lenB/4)
      X   = blobB[0x0c:0x16]               # the 10-char per-install sign input

    sign = md5( A + "[" + md5hex(X) + "]@" + param )

`expand`/`xform` are internal functions of libbaseutil.so; they are called by the small native
oracle `kit/harness/native/decode_token` (built with build.sh) running on the device — that is
why this wrapper needs `--adb`.

Usage
    # print A / X / md5(X) for one install (tokens can be read from the app's prefs as root)
    python3 decode_token_native.py --adb emulator-5558 --sign-a a.txt --sign-b b.txt

    # ... and check a KdKit capture against them
    python3 decode_token_native.py --adb emulator-5558 --sign-a a.txt --sign-b b.txt \
        --capture work/cap.txt
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import kd_api
import argparse
import hashlib
import re
import subprocess
import sys

ORACLE = '/data/local/tmp/decode_token'
LIB = '/data/local/tmp/libbaseutil.so'


def adb(serial, *args, timeout=120):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout)


def decode(serial, token, key):
    out = adb(serial, f"{ORACLE} {LIB} '{token}' '{key}'")
    m = re.search(r'blob .*?\n  hex: ([0-9a-f]+)', out.stdout, re.S)
    if not m:
        raise RuntimeError(f'oracle failed for key={key!r}:\n{out.stdout}\n{out.stderr}')
    return bytes.fromhex(m.group(1))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--sign-a', required=True, help='file with the stored KEY_ANTISPAM_SIGN_A')
    ap.add_argument('--sign-b', required=True)
    ap.add_argument('--capture', default=None, help='KdKit capture to validate')
    a = ap.parse_args(argv[1:])

    tok_a = open(a.sign_a).read().strip()
    tok_b = open(a.sign_b).read().strip()

    blob_a = decode(a.adb, tok_a, '@fG2SuLA')
    sign_const = blob_a[0:5].decode('latin1')
    k1 = blob_a[7:12].decode('latin1')
    key2 = k1 + '#G4'

    blob_b = decode(a.adb, tok_b, key2)
    x = blob_b[0x0c:0x16].decode('latin1')

    print(f'[token] blobA   = {blob_a.split(bytes([0]), 1)[0]!r}')
    print(f'[token] blobB   = {blob_b.split(bytes([0]), 1)[0]!r}')
    print(f'[token] A       = {sign_const!r}   (blobA[0:5])')
    print(f'[token] k1      = {k1!r}   -> key2 = {key2!r}')
    print(f'[token] X       = {x!r}   (blobB[0x0c:0x16])')
    print(f'[token] md5(X)  = {hashlib.md5(x.encode()).hexdigest()}')
    print('[token] sign = md5( A + "[" + md5(X) + "]@" + param )')

    if a.capture:
        text = textio.read_text(a.capture)   # 2026-11-03：--capture 可给 .txt.gz
        pairs = re.findall(r'SIGNPARAM param=(\S+) sign=([0-9a-f]{32})', text)
        ok = bad = 0
        for param, sign in pairs:
            got = kd_api.sign_digest(sign_const, x, param)   # 2026-11-03：公式收敛到 kd_api
            ok, bad = (ok + 1, bad) if got == sign else (ok, bad + 1)
        print(f'[token] capture check: match={ok} mismatch={bad} (of {len(pairs)})')
        return 0 if bad == 0 else 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
