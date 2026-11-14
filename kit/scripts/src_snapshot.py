#!/usr/bin/env python3
"""
kuaidui-kit / src_snapshot.py — **手写源码的整库快照**。

### 为什么需要（2026-11-03 的一次真实事故）

`run_negative_controls.py` 的“新建文件”用例被误用在一个**已存在**的文件上，
于是 `kit/scripts/verify_face.py` 被覆盖成注入文本、跑完又被删掉。

仓库**没有 `.git`**，任何备份目录里也没有它。
最后靠 `__pycache__/verify_face.cpython-314.pyc` 的常量树 + 6 条行为测试
才把它重建回来 —— 能重建是运气，不是设计。

**一个只存在于一处的手写文件，被误删就需要“考古”。**

### 做什么

把全部手写源码复制到 `work/src_backups/<UTC 时间戳>/`，并维护一个
`latest` 符号链接式的副本目录。整库 4.6 MB，一次快照 < 1 秒。

    python3 kit/scripts/src_snapshot.py            # 建一份
    python3 kit/scripts/src_snapshot.py --verify   # 只校验新鲜度，不建
    python3 kit/scripts/src_snapshot.py --restore kit/scripts/verify_face.py

### 保留策略

只留最近 `--keep` 份（默认 10）。不在这里做花哨的增量 ——
4.6 MB 的全量副本，10 份也才 46 MB，而“能一键还原”比省 40 MB 重要得多。

### 门禁

`check_src_snapshot.py`（门禁 ㉛）校验快照**足够新**：
超过 `--max-age-hours`（默认 48）就红 —— 一个三天前的快照，
挡不住今天下午的误删。
"""
import argparse
import datetime
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEST = os.path.join(ROOT, 'work', 'src_backups')

#: 手写源码的根。**不含** `work/`（那是产物与证据，另有 disk_audit 盯着）、
#: 不含 `h5/`（抓下来的页面样本）、不含 `module/build/`。
SOURCES = [
    'kit/python',
    'kit/scripts',
    'module/app/src',
    'module/scripts',
    'module/PARADIGM.md',
    'module/README.md',
    'module/OPTIMIZATION.md',
    'REPORT.md',
]


def stamp():
    return datetime.datetime.now().strftime('%Y%m%dT%H%M%S')


def create(keep=10, verbose=True):
    outdir = os.path.join(DEST, stamp())
    n = 0
    for rel in SOURCES:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            if verbose:
                print(f'[snap] 跳过不存在的 {rel}')
            continue
        dst = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc',
                                                          'build', '.gradle'))
        else:
            shutil.copy2(src, dst)
        n += 1
    # `latest` 用一个**目录副本**而不是符号链接：符号链接在跨工具/跨平台时
    # 行为不一，而"还原"这件事必须在最糟的那一刻也最直白。
    latest = os.path.join(DEST, 'latest')
    if os.path.isdir(latest):
        shutil.rmtree(latest)
    shutil.copytree(outdir, latest,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if verbose:
        size = sum(os.path.getsize(os.path.join(d, f))
                   for d, _s, fs in os.walk(latest) for f in fs)
        print(f'[snap] 已快照 {n} 个根到 {os.path.relpath(outdir, ROOT)}'
              f'（latest {size // 1024} KB）')
    # 只留最近 keep 份（`latest` 永远留）
    olds = sorted(d for d in os.listdir(DEST)
                  if d != 'latest' and os.path.isdir(os.path.join(DEST, d)))
    for d in olds[:-keep]:
        shutil.rmtree(os.path.join(DEST, d))
        if verbose:
            print(f'[snap] 清掉过期的 {d}')
    return outdir


def restore(rel):
    """从 `latest` 还原一个仓库相对路径。返回是否还原成功。"""
    src = os.path.join(DEST, 'latest', rel)
    dst = os.path.join(ROOT, rel)
    if not os.path.isfile(src):
        print(f'[snap] latest 里没有 {rel}')
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print(f'[snap] 已从 latest 还原 {rel}')
    return True


def age_hours():
    p = os.path.join(DEST, 'latest')
    if not os.path.isdir(p):
        return None
    ts = os.path.getmtime(p)
    return (datetime.datetime.now() - datetime.datetime.fromtimestamp(ts)).total_seconds() / 3600


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', type=int, default=10)
    ap.add_argument('--verify', action='store_true', help='只校验新鲜度，不建')
    ap.add_argument('--restore', default=None, help='从 latest 还原这个仓库相对路径')
    ap.add_argument('--max-age-hours', type=float, default=48.0)
    a = ap.parse_args(argv[1:])

    if a.restore:
        return 0 if restore(a.restore) else 1

    if a.verify:
        h = age_hours()
        if h is None:
            print('[snap] **没有快照** —— 跑一次 `src_snapshot.py`')
            return 1
        if h > a.max_age_hours:
            print(f'[snap] **快照已过期**：{h:.1f} 小时前'
                  f'（上限 {a.max_age_hours}）⇒ 它挡不住今天的误删')
            return 1
        print(f'[snap] 快照 {h:.1f} 小时前 ✓（上限 {a.max_age_hours}）')
        return 0

    create(keep=a.keep)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
