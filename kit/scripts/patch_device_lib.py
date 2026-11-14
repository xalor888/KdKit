#!/usr/bin/env python3
"""
kuaidui-kit / patch_device_lib.py — byte-level, in-place patch of a `.so` that a
target app loads from its own extracted native library directory.

Why this instead of a repack: `com.kuaiduizuoye.scan` binds its request-signing
key material to the **APK signing certificate** (`libbaseutil.so` reads
`signatures[0]`), so re-signing the APK silently breaks every signed request.
The arm64 libs are extracted on install (`android:extractNativeLibs="true"`), so
a root-only edit of the on-disk file changes what the loader maps — the APK never
changes and its signature stays valid.

The patch is applied with `dd` through root. **Expectations are checked before
writing**, so an offset taken from a different build is refused instead of
corrupting the file:

    VADDR:NEW             只写，不校验原文（旧行为）
    VADDR:OLD>NEW         先读原文，不等于 OLD 就**拒绝写入**

    python3 patch_device_lib.py --adb emulator-5556 \
        --lib /data/app/~~xxx==/com.kuaiduizuoye.scan-yyy==/lib/arm64/libdpsdk.so \
        --patch 0x170978:TracerPid>TracerP!d \
        --backup /data/local/tmp/libdpsdk.orig.so

Every run prints, for each patch: the bytes read before, the expectation (if
any), the bytes read back after writing, and a SHA-256 of the file before/after.

**2026-11-03 修**：文档原来承诺"校验期望字节、不符则拒绝"，而 `--patch` 只有
`VADDR:ASCII` 一个入参 —— 那个承诺**从来没有被执行过**。一个写文件的工具
承诺了自己没做的事，比不承诺更糟：调用方会以为偏移是验过的。
"""
import argparse
import subprocess
import sys


def adb(serial, *args, timeout=60):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout)


def root_cmd(serial, cmd):
    """Run a shell command as root (adb root image or Magisk su)."""
    out = adb(serial, 'id')
    if 'uid=0' in out.stdout:
        return adb(serial, cmd)
    return adb(serial, 'su', '-c', cmd)


def read_bytes(serial, path, offset, length):
    r = root_cmd(serial, f'dd if="{path}" bs=1 skip={offset} count={length} 2>/dev/null | xxd -p')
    return r.stdout.strip().replace('\n', '')


def sha256(serial, path):
    """文件不存在时给空串，**不要抛 IndexError**（2026-11-03 修）。

    旧实现 `…stdout.split()[0]`：`sha256sum` 对不存在的文件只往 stderr 写一句，
    stdout 为空 ⇒ `[][0]` ⇒ IndexError。于是一个"文件不在"的输入
    表现出来的是一次**崩溃**，而不是一句"文件不存在"。
    """
    out = root_cmd(serial, f'sha256sum "{path}"').stdout.split()
    return out[0] if out else ''


def write_ascii(serial, path, offset, data):
    """Write ASCII bytes at an absolute file offset, in place, through root."""
    hexs = data.encode().hex()
    # build the byte stream with printf so no file has to be pushed
    printf_arg = ''.join('\\\\x%02x' % b for b in data.encode())
    cmd = (f'printf "{printf_arg}" | dd of="{path}" bs=1 seek={offset} conv=notrunc 2>&1 | tail -1')
    return root_cmd(serial, cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--lib', required=True, help='absolute path of the .so on the device')
    ap.add_argument('--patch', action='append', required=True,
                    help='VADDR:NEW（只写）或 VADDR:OLD>NEW（先校验原文，不符则拒绝）'
                         ' — e.g. 0x170978:TracerPid>TracerP!d')
    ap.add_argument('--backup', default=None, help='copy the original file here first')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    before = sha256(a.adb, a.lib)
    if not before:
        print(f'[patch] **读不到 {a.lib}**（文件不存在？路径写错了？设备不在线？）')
        return 2
    print(f'[patch] {a.lib}')
    print(f'[patch] sha256 before: {before}')

    if a.backup and not a.dry_run:
        r = root_cmd(a.adb, f'cp -f "{a.lib}" "{a.backup}" && ls -la "{a.backup}"')
        print('[patch] backup: ' + r.stdout.strip().replace('\n', ' | '))

    for spec in a.patch:
        off_s, _, rest = spec.partition(':')
        off = int(off_s, 0)
        # `OLD>NEW`：给了期望原文就在**写之前**校验；只给 `NEW` 则维持旧行为
        # （不校验），但日志里要写明"未校验"，不能让调用方误以为验过。
        expect = None
        if '>' in rest:
            expect, _, text = rest.partition('>')
        else:
            text = rest
        cur = read_bytes(a.adb, a.lib, off, len(text))
        if not cur:
            print(f'[patch] **@{off_s} 读不到 {len(text)} 字节**（偏移超出文件？设备不在线？）')
            return 2
        cur_txt = bytes.fromhex(cur).decode('latin1')
        print(f'[patch] @{off_s}: current={cur_txt!r} -> new={text!r}')
        if expect is not None:
            # **先解码再比**：`cur` 是 `xxd -p` 的**十六进制串**，
            # `expect.encode()` 是**字节**。第一版直接 `cur != expect.encode()`
            # ⇒ 两者永远不相等 ⇒ 期望相符时也判"不匹配"（实测：期望 'AAAA' 实际 'AAAA' 却说 mismatch）。
            if bytes.fromhex(cur) != expect.encode():
                print(f'[patch]   **期望原文不匹配**：期望 {expect!r}，实际 {cur_txt!r}')
                print('[patch]   拒绝写入 —— 这个偏移多半来自另一个构建，写下去会毁文件')
                return 1
            print(f'[patch]   expectation OK ({expect!r})')
        else:
            print('[patch]   （未给期望原文 ⇒ 这一处**没有**校验，偏移对错无从判断）')
        if cur and bytes.fromhex(cur) == text.encode():
            print('[patch]   already patched, skipping')
            continue
        if a.dry_run:
            continue
        r = write_ascii(a.adb, a.lib, off, text)
        print('[patch]   dd: ' + r.stdout.strip()[:120])
        back = read_bytes(a.adb, a.lib, off, len(text))
        ok = bytes.fromhex(back) == text.encode() if back else False
        print(f'[patch]   verify: {bytes.fromhex(back).decode("latin1")!r} {"OK" if ok else "MISMATCH"}')
        if not ok:
            print('[patch] FAILED — file left in an unknown state')
            return 1

    if not a.dry_run:
        print(f'[patch] sha256 after:  {sha256(a.adb, a.lib)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
