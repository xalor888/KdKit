#!/usr/bin/env python3
"""
kuaidui-kit / dpsdk_detect_baseline.py — 把 `libdpsdk.so` 的**检测面**钉成基线，变了就红。

为什么需要
────────────
2026-11-09 的教训：7.9.0→7.10.0 只看到"体积 +43%、导出符号 1956→4"，
差点写成"检测增强"；实际是 **QUIC/TLS 依赖扩张**，检测串只多了 `magisk`/`/sbin/su`。
但另一头也差点漏掉：dpsdk **确实**在读 `/proc/self/maps`（4 处内联引用）——
这是刚被 `work/dpsdk/DELTA-710.md` 纠正出来的事实。

⇒ 需要一个**每次宿主更新都会跑**的判据：检测面的（串, 是否有引用, so 哈希）只要变，
就红，逼人重新评估 —— 而不是等下一个版本再靠肉眼发现。

基线条目（`work/baselines/dpsdk_detect.json`）
  * `sha256`：库身份（变了 ⇒ 整份要重看）
  * `exports`：导出符号名集合（DProtect 壳只该有 init/getTicket/raw_syscall 那几个）
  * `probes`：每个检测串 → `{present, referenced}`（引用用 `adrp page + add #low12` 判）

    python3 kit/scripts/dpsdk_detect_baseline.py --save     # 建/更新基线
    python3 kit/scripts/dpsdk_detect_baseline.py            # 核对（变了返回 1）

覆盖边界：只认内联 `adrp+add`（不是完整 xref 图），也不跟 `blr`/数据表 ——
所以 `referenced=false` **不代表**运行期不用（见 DELTA-710 §3 的反例 `TracerPid`）。
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 2026-11-14：应用宝的 7.10.2 包是 **armeabi-v7a 单 ABI**，解包树里没有 arm64 目录。
# 旧代码写死 arm64 路径 ⇒ 门禁㉲ 从"检测面漂了"退化成"找不到文件"（两种红长得一样，
# 但修法完全不同）。改成按 ABI 依次找，并让报错说清找过哪些路径。
_LIB_ABIS = ('arm64-v8a', 'armeabi-v7a', 'armeabi', 'x86_64', 'x86')
_LIB_CANDIDATES = [os.path.join(ROOT, 'work', 'apktool_out', 'lib', abi, 'libdpsdk.so')
                   for abi in _LIB_ABIS]
LIB = _LIB_CANDIDATES[0]            # 兼容旧引用（报错信息/日志里用）


def find_lib():
    for p in _LIB_CANDIDATES:
        if os.path.exists(p):
            return p
    return None
BASE = os.path.join(ROOT, 'work', 'baselines', 'dpsdk_detect.json')

# 刻意只收"安全语义"的串（`detect`/`root` 这种会在 `loss detection`/`Root CA` 上误命中，
# 那是 A1 第一轮的教训）。加串要写清为什么。
PROBES = [
    '/proc/self/maps', '/proc/%d/maps', 'cat /proc/%d/status',
    '/proc/self/mountinfo', '/proc/self/mounts', '/proc/self/mountstats',
    'rwxp', 'app_onloaded_so', 'TracerPid',
    'magisk', '/sbin/su', '/system/bin/su', '/system/sbin/su', '/data/adb',
    'frida', 'xposed', 'supersu', 'busybox',
]


def _objdump():
    c = sorted(glob.glob(os.path.expanduser(
        '~/Library/Android/sdk/ndk/*/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-objdump')))
    return c[-1] if c else 'llvm-objdump'


def _nm():
    c = sorted(glob.glob(os.path.expanduser(
        '~/Library/Android/sdk/ndk/*/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-nm')))
    return c[-1] if c else 'llvm-nm'


def profile():
    lib = find_lib()
    if lib is None:
        return None
    with open(lib, 'rb') as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()

    nm = subprocess.run([_nm(), '-D', '--defined-only', lib], capture_output=True,
                        text=True, errors='replace', timeout=120)
    exports = sorted({ln.split()[-1] for ln in nm.stdout.splitlines() if ln.strip()})

    od = subprocess.run([_objdump(), '-d', '--no-show-raw-insn', lib], capture_output=True,
                        text=True, errors='replace', timeout=300)
    addrs = collections.defaultdict(list)
    cur = None
    for ln in od.stdout.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+adrp\s+(x\d+),\s+0x([0-9a-f]+)', ln)
        if m:
            cur = (m.group(1), m.group(2), int(m.group(3), 16))
            continue
        if cur:
            reg = cur[1]
            m2 = re.match(r'\s*([0-9a-f]+):\s+add\s+%s,\s+%s,\s+#0x([0-9a-f]+)' % (reg, reg), ln)
            if m2:
                addrs[cur[2] + int(m2.group(2), 16)].append(cur[0])
            cur = None

    probes = {}
    for p in PROBES:
        off = data.find(p.encode())
        probes[p] = {'present': off >= 0,
                     'offset': hex(off) if off >= 0 else None,
                     'referenced': bool(addrs.get(off)) if off >= 0 else False,
                     'refs': addrs.get(off, [])[:4]}
    return {'sha256': sha, 'size': len(data), 'weight': len(addrs),
            'exports': exports, 'probes': probes}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--save', action='store_true', help='建/更新基线')
    a = ap.parse_args(argv[1:])

    cur = profile()
    if cur is None:
        print('[dpsdk] 找不到 libdpsdk.so（先 apktool d 出 lib/）。找过的路径：\n  '
              + '\n  '.join(os.path.relpath(p, ROOT) for p in _LIB_CANDIDATES), file=sys.stderr)
        return 2

    if a.save:
        os.makedirs(os.path.dirname(BASE), exist_ok=True)
        with open(BASE, 'w', encoding='utf-8') as f:
            json.dump(cur, f, ensure_ascii=False, indent=1)
        nref = sum(1 for v in cur['probes'].values() if v['referenced'])
        print(f'[dpsdk] 基线已写入 {os.path.relpath(BASE, ROOT)}'
              f'（sha {cur["sha256"][:12]}，{nref} 条串有内联引用，导出 {len(cur["exports"])} 个）')
        return 0

    if not os.path.exists(BASE):
        print('[dpsdk] 没有基线 ⇒ 先跑 --save（这不是通过，而是"还没建判据")')
        return 2

    with open(BASE, encoding='utf-8') as f:
        old = json.load(f)

    bad = []
    if old.get('sha256') != cur['sha256']:
        bad.append(f'库哈希变了：{old.get("sha256", "")[:12]} → {cur["sha256"][:12]}'
                   '（整份要重看，见 work/dpsdk/DELTA-710.md）')
    o_exp, c_exp = set(old.get('exports') or []), set(cur['exports'])
    for e in sorted(c_exp - o_exp):
        bad.append(f'新增导出符号：{e}')
    for e in sorted(o_exp - c_exp):
        bad.append(f'导出符号消失：{e}')
    for name, ov in (old.get('probes') or {}).items():
        cv = cur['probes'].get(name, {})
        if ov.get('present') != cv.get('present'):
            bad.append(f'串 {"出现" if cv.get("present") else "消失"}：{name}')
        elif ov.get('referenced') != cv.get('referenced'):
            bad.append(f'串的内联引用状态变了：{name} '
                       f'{"无→有（可能是新检测点）" if cv.get("referenced") else "有→无"}')
    for name, cv in cur['probes'].items():
        if name not in (old.get('probes') or {}):
            bad.append(f'新增检测串（未登记）：{name}（存在={cv["present"]}）')

    if bad:
        print('[dpsdk] **检测面变了**：')
        for b in bad:
            print('  ✗', b)
        print('[dpsdk] 处置：读完差异后 `--save` 更新基线，并把结论写进 work/dpsdk/DELTA-<版本>.md')
        return 1
    nref = sum(1 for v in cur['probes'].values() if v['referenced'])
    print(f'[dpsdk] 检测面与基线一致 ✓（{nref} 条串有内联引用，导出 {len(cur["exports"])} 个）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
