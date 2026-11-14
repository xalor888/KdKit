#!/usr/bin/env python3
"""
kuaidui-kit / work_prune.py — `work/` 超阈值时**自动归档**（默认只预演，`--apply` 才动手）。

为什么需要
────────────
2026-11-09 实测一次满盘：`/System/Volumes/Data` 460 GB 用到 435 GB、只剩 **126 MiB**，
模拟器直接 `FATAL: not enough disk space to run avd` —— 整条链（门禁/验收/负对照）全红。
`work/` 自身也长到 **2.5 GB**（`packs` 1.0 GB + `apktool_out` 711 MB + 归档 196 MB）。

`disk_audit.py`（门禁 ㉓）只在"单项增长 ≤500 MB / 总 ≤8 GB"上报警 —— **报警不会腾地方**。
这个脚本补上"报警之后的动作"。

判据（可复跑）
  * 目标：`work/` 总体积 ≤ 阈值（默认 **2048 MB**）
  * 手段：按 **mtime 从旧到新**，把 `work/packs/<pack>/` 整目录压成
    `work/archive/packs/<pack>.tar.gz`（可复现的抓取证据体积最大、价值随时间衰减最快）
  * 每一步都写 `work/archive/MANIFEST-<ts>.json`：原路径 → tar 内成员数 / 字节数 / 原因
  * 归档后重跑 `index_evidence.py`（否则 ㉤「证据索引新鲜」会因为路径消失而红）

    python3 kit/scripts/work_prune.py                 # 预演（打印会归档哪些）
    python3 kit/scripts/work_prune.py --apply         # 真归档
    python3 kit/scripts/work_prune.py --target-mb 1500 --apply

覆盖边界：只动 `work/packs/*`（抓取证据）。`work/apktool_out`（当前解码树）与
`work/baselines`（判据基线）**永不动** —— 前者删了所有静态门禁都没法跑，后者是判据本身。
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NEVER = ('apktool_out', 'baselines', 'archive', 'program')

ROOT = DEFAULT_ROOT          # 运行时由 --root 覆盖（单测用临时目录，绝不碰真仓库）
WORK = os.path.join(ROOT, 'work')
ARCHIVE = os.path.join(WORK, 'archive', 'packs')


def dir_size(path):
    total = 0
    for dp, _dn, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def work_size():
    total = 0
    for name in os.listdir(WORK):
        p = os.path.join(WORK, name)
        if os.path.isdir(p):
            total += dir_size(p)
        else:
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


def candidates():
    """按 mtime 从旧到新列出 work/packs/<pack>（整目录）。"""
    out = []
    for p in glob.glob(os.path.join(WORK, 'packs', '*')):
        if not os.path.isdir(p):
            continue
        try:
            out.append((os.path.getmtime(p), p, dir_size(p)))
        except OSError:
            continue
    out.sort()
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-mb', type=int, default=2048, help='work/ 目标上限（MB）')
    ap.add_argument('--apply', action='store_true', help='真归档（默认只预演）')
    ap.add_argument('--max-packs', type=int, default=0,
                    help='一次最多归档几个 pack（0=不限，够阈值即停）')
    ap.add_argument('--root', default=DEFAULT_ROOT, help='仓库根（单测用临时目录）')
    a = ap.parse_args(argv[1:])

    global ROOT, WORK, ARCHIVE
    ROOT = os.path.abspath(a.root)
    WORK = os.path.join(ROOT, 'work')
    ARCHIVE = os.path.join(WORK, 'archive', 'packs')
    if not os.path.isdir(WORK):
        print(f'[prune] {os.path.relpath(WORK, "/")} 不存在', file=sys.stderr)
        return 2

    cur = work_size()
    print(f'[prune] work/ 当前 {cur / 1e6:.0f} MB，目标 ≤ {a.target_mb} MB'
          f'（{"预演" if not a.apply else "执行"}）')
    if cur <= a.target_mb * 1e6:
        print('[prune] 已在限内，无需动作 ✓')
        return 0

    need = cur - a.target_mb * 1e6
    chosen = []
    # 按 mtime 从旧到新累加，**不设固定个数**：packs 是"小而多"（1220 个目录共 1.0 GB，
    # 最大单个 4.2 MB），只归档 40 个连 160 MB 都放不出去。估算用 0.75（抓取文本压缩比偏保守）。
    limit = a.max_packs if a.max_packs > 0 else 10 ** 9
    for mtime, path, size in candidates():
        if need <= 0 or len(chosen) >= limit:
            break
        chosen.append((path, size))
        need -= int(size * 0.75)
    if not chosen:
        print('[prune] 没有可归档的 pack（packs/ 为空？）', file=sys.stderr)
        return 2

    print(f'[prune] 计划归档 {len(chosen)} 个 pack（最旧的在前）：')
    for path, size in chosen:
        print(f'  - {os.path.relpath(path, ROOT)}  {size / 1e6:.1f} MB')

    if not a.apply:
        print('[prune] 预演结束；加 --apply 执行')
        return 0

    os.makedirs(ARCHIVE, exist_ok=True)
    ts = time.strftime('%Y-%m-%dT%H:%M:%S')
    manifest = {'ts': ts, 'work_size_before': cur, 'target_mb': a.target_mb, 'items': []}
    for path, size in chosen:
        name = os.path.basename(path) + '.tar.gz'
        out = os.path.join(ARCHIVE, name)
        try:
            with tarfile.open(out, 'w:gz') as t:
                t.add(path, arcname=os.path.basename(path))
            members = len(tarfile.open(out).getmembers()) if os.path.exists(out) else 0
            packed = os.path.getsize(out) if os.path.exists(out) else 0
            if packed > 0 and members > 1:      # tar 里至少要有成员（1 = 目录本身）
                shutil.rmtree(path)
            manifest['items'].append({'src': os.path.relpath(path, ROOT),
                                      'tar': os.path.relpath(out, ROOT),
                                      'src_bytes': size, 'tar_bytes': packed,
                                      'members': members,
                                      'reason': 'work/ 超阈值，按 mtime 最旧归档'})
            print(f'[prune]   ✓ {os.path.basename(path)} -> {packed / 1e6:.1f} MB')
        except (OSError, tarfile.TarError) as e:
            print(f'[prune]   ✗ {os.path.basename(path)}: {e}', file=sys.stderr)
            continue

    mpath = os.path.join(WORK, 'archive', f'MANIFEST-{ts.replace(":", "")}.json')
    with open(mpath, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f'[prune] 清单 -> {os.path.relpath(mpath, ROOT)}')

    # 归档后必须重建索引，否则 ㉤ 会因为"路径消失"红
    idx = os.path.join(ROOT, 'kit', 'scripts', 'index_evidence.py')
    if os.path.exists(idx):
        r = subprocess.run([sys.executable, idx], capture_output=True, text=True,
                           timeout=300, cwd=ROOT)
        print('[prune] 索引重建 rc=' + str(r.returncode) +
              ('（' + (r.stdout or r.stderr).strip().splitlines()[-1][:80] + '）'
               if (r.stdout or r.stderr).strip() else ''))
    print(f'[prune] work/ 现在 {work_size() / 1e6:.0f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
