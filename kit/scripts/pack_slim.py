#!/usr/bin/env python3
"""
kuaidui-kit / pack_slim.py — shrink old evidence-pack captures the reversible way.

By R73 the per-round packs had become the workspace's biggest product (128 MB, `work/CATALOG.md`),
almost all of it raw capture copies. Policy (same as `ARCHIVE.md`): **never delete evidence** —
gzip the raw captures of all but the newest N packs, and record what was done so it can be undone
with `gunzip`.

    python3 kit/scripts/pack_slim.py --keep 3 [--dry-run]
"""
import argparse
import fnmatch
import gzip
import os
import re
import shutil
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PACKS = os.path.join(ROOT, 'work', 'packs')
ARCHIVE = os.path.join(ROOT, 'work', 'ARCHIVE.md')


#: 文档复现命令里引用的路径。**这些文件不许压** —— 压掉之后
#: 照着文档跑一遍会 FileNotFoundError，而"可复现"的承诺就没了
#: （2026-11-03：我为了测本文件的守卫，用 `--keep 0` 跑了一次，
#:  全库 867 个 capture 被压，其中 `r793/capture.txt` 正被四份文档引用，
#:  门禁 ①b 当场红。事后抓到不如事前拦住。）
REPRO_RE = re.compile(r'`([^`]*work/packs/[^`]*)`')


def doc_referenced_paths():
    """所有文档复现命令里点名的 `work/packs/...` 路径（含 glob 形态）。"""
    out = set()
    for base in (os.path.join(ROOT, 'work'), os.path.join(ROOT, 'module')):
        for fn in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if not fn.endswith('.md'):
                continue
            try:
                with open(os.path.join(base, fn), encoding='utf-8', errors='replace') as _f:
                    txt = _f.read()
            except OSError:
                continue
            for m in REPRO_RE.finditer(txt):
                out.add(m.group(1).strip().strip('"'))
    return out


def is_doc_referenced(path, referenced):
    """`path` 是否被某条复现命令**点名到具体文件**。

    **只认精确路径，不认 glob**（2026-11-03 想清楚的一件事）：

    文档里大量出现 `work/packs/*/capture*.txt` 这种 glob。若把 glob 命中也算
    "被引用"，那么**每一个** `capture*.txt` 都受保护 ⇒ 瘦身名存实亡
    （第一版就是这样，测试当场指出"没人引用的包也被保护了"）。

    而 glob 本来就不需要保护：读它们的工具（`bridge_page_map.py:33`、
    `core_http_paths.py`）**都接受 `.gz`**。真正该修的是那些只列了 `*.txt`
    没列 `*.txt.gz` 的复现命令 —— 那是文档不完整，不是压缩有危险。
    """
    rel = os.path.relpath(path, ROOT)
    return rel in referenced


def roundtrip_ok(orig):
    """`orig + '.gz'` 解压回来必须与 `orig` **逐字节相同**。

    提成函数是为了能离线测：真机上要让一次 gzip 写出"打不开或内容不全"的产物
    很难注入（写失败往往是磁盘满，而那会影响整个仓库），
    但这个判据本身必须被证明是对的。

    判据刻意不用"文件存在且非空" —— 后者证不了内容。
    """
    try:
        with gzip.open(orig + '.gz', 'rb') as back, open(orig, 'rb') as src:
            return back.read() == src.read()
    except Exception as e:                                  # noqa: BLE001
        # **必须接住 `zlib.error`**：第一版只列了 `OSError/EOFError/BadGzipFile`，
        # 而一个被改坏的 gzip 抛的是 `zlib.error: invalid code lengths set`
        # —— 它不在那三类里 ⇒ 异常穿透 ⇒ 工具**崩溃**，而原文还躺在那儿
        # 没人删（侥幸），但瘦身整轮中断。
        #
        # 这里刻意用宽 except：判据是"能不能原样解压回来"，
        # 任何异常都意味着"不能" ⇒ False ⇒ 保留原文。这是少数
        # "宽 except 比窄 except 更安全"的场合 —— 漏一种异常类型，
        # 代价是崩在一次本可以优雅跳过的损坏上。
        print(f'[slim] 解压 {orig + ".gz"} 失败：{type(e).__name__}: {e}')
        return False


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', type=int, default=3, help='keep the newest N packs uncompressed')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv[1:])

    tags = sorted([t for t in os.listdir(PACKS) if os.path.isdir(os.path.join(PACKS, t))],
                  key=lambda t: os.path.getmtime(os.path.join(PACKS, t)))
    old = tags[:-a.keep] if a.keep else tags
    _referenced = {r for r in doc_referenced_paths() if '*' not in r}
    if _referenced:
        print(f'[slim] 文档点名引用了 {len(_referenced)} 个 packs 文件，这些不压'
              f'（glob 形态不算：读它们的工具都接受 .gz）')
    saved, rows = 0, []
    for tag in old:
        for fn in sorted(os.listdir(os.path.join(PACKS, tag))):
            if not fn.startswith('capture') or not fn.endswith('.txt'):
                continue
            p = os.path.join(PACKS, tag, fn)
            before = os.path.getsize(p)
            if before < 200 * 1024:              # 小于 200 KB 的不折腾
                continue
            if is_doc_referenced(p, _referenced):
                print(f'[slim] 跳过 {tag}/{fn}：被文档复现命令引用，压了就跑不起来了')
                continue
            if a.dry_run:
                rows.append((tag, fn, before, 0))
                continue
            with open(p, 'rb') as src, gzip.open(p + '.gz', 'wb', compresslevel=9) as dst:
                shutil.copyfileobj(src, dst)
            after = os.path.getsize(p + '.gz')
            # **解压验证通过才删原文**（2026-11-03 修）。
            #
            # 旧实现 gzip 一写完立刻 `os.remove(p)`：压缩成功 ≠ 内容对。
            # 磁盘满、写入被截断、或者 compresslevel 与读取方不匹配时，
            # 拿到的是一个**打不开或内容不全的 .gz**，而原文已经没了 ——
            # 那是永久丢失一份证据，只为省几百 MB。
            #
            # 判据用"解压回来的字节与原文逐字节相同"，不用"文件存在且非空"：
            # 后者证不了内容（今天已经在 `check_capture_claimed` /
            # `verify_membership.pull_capture` / `device_backup` 三次遇到
            # "有文件但内容不是那回事"）。
            if not roundtrip_ok(p):
                print(f'[slim] {tag}/{fn}: **解压回来与原文不一致** —— 原文保留，.gz 删掉')
                os.remove(p + '.gz')
                continue
            os.remove(p)
            saved += before - after
            rows.append((tag, fn, before, after))

    out = ['', f'## 证据包瘦身（{datetime.now().strftime("%Y-%m-%d %H:%M")}，`pack_slim.py --keep {a.keep}`）', '',
           '| 包 | 文件 | 原大小 | gz 后 |', '|---|---|---|---|']
    for tag, fn, before, after in rows:
        out.append(f'| `{tag}` | `{fn}` | {before // 1024} KB | {(after // 1024) if after else "-"} KB |')
    out += ['', f'* 共 {len(rows)} 个文件；省 **{saved // 1024 // 1024} MB**（原文可 `gunzip` 还原，证据不丢）',
            '* 读取方（`bridge_urls.py` / `api_login_map.py`）已同时接受 `.txt` 与 `.txt.gz`。', '']
    if not a.dry_run:
        with open(ARCHIVE, 'a') as _f:
            _f.write('\n'.join(out) + '\n')
    print(f'[slim] {len(rows)} 个文件，省 {saved // 1024 // 1024} MB（keep={a.keep}'
          + ('，dry-run' if a.dry_run else '') + ')')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
