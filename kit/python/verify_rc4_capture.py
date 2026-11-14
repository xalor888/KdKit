#!/usr/bin/env python3
"""
kuaidui-kit / verify_rc4_capture.py — prove the offline RC4 reimplementation matches
the app's own live crypto, byte for byte.

`KdKit · SignObserver` hooks `com.baidu.android.common.security.RC4.encrypt/decrypt([B)[B`
and writes each call as

    HH:MM:SS.mmm RC4 <encrypt|decrypt> key=b64[128]<b64 key> in=b64[<n>]<b64 input>: b64[<n>]<b64 output>

This script feeds every triple through `kit/python/kd_crypto.py`'s RC4 and reports
match/mismatch — i.e. it is the regression test for "we really did reverse the
payload crypto", independent of any sign / H5 code path.

The `RC4KEY` lines are also reported, because a key mismatch is the *first* thing to check
when a triple mismatches: `RC4KEY b(<versionCode>): <hex>` comes from `nativeGetKey`, and
the same key also appears as `RC4KEYSTR <ascii>` (rc4_probe's constructor hook) or
`RC4KEY <hex> | len=<n>` (rc4_probe's `setKey(byte[])` hook). If those disagree, the
capture is internally inconsistent and no conclusion about the algorithm is allowed.

    adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
    python3 verify_rc4_capture.py cap.txt
"""
import base64
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from capture_schema import iter_records  # noqa: E402
from kd_crypto import rc4  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    triples, keys = [], {}
    for rec in iter_records(argv[1]):
        if rec.kind == 'RC4':
            triples.append(rec)
        elif rec.kind in ('RC4KEY', 'RC4KEYSTR'):
            k = rec.get('key')
            if k:
                keys.setdefault(rec.kind, []).append(k)

    print(f'[verify] {len(triples)} RC4 triple(s) in {argv[1]}')
    for kind, vals in keys.items():
        uniq = sorted(set(vals))
        print(f'[verify] {kind}: {len(uniq)} distinct key(s)'
              + (f' -> {", ".join(v[:16] + "…" for v in uniq)}' if uniq else ''))

    ok = bad = skipped = 0
    for i, rec in enumerate(triples, 1):
        try:
            key = base64.b64decode(rec.get('key_b64') or '')
            data = base64.b64decode(rec.get('in_b64') or '')
            want = base64.b64decode(rec.get('out_b64') or '')
        except Exception:
            skipped += 1
            print(f'  [{i}] {rec.get("op"):7s} SKIP (line truncated mid-write)')
            continue
        got = rc4(key, data)
        same = got == want
        ok, bad = (ok + 1, bad) if same else (ok, bad + 1)
        print(f'  [{i}] {rec.get("op"):7s} key={key[:20].decode("latin1")}… ({len(key)} B) '
              f'in={len(data)} B out={len(want)} B -> {"MATCH" if same else "MISMATCH"}')
        if same:
            try:
                print(f'      plaintext: {want.decode("utf-8")[:200]}')
            except UnicodeDecodeError:
                print(f'      plaintext: <binary> {want[:32].hex()}')
    print(f'[verify] match={ok} mismatch={bad} skipped={skipped}')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
