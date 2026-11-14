#!/usr/bin/env python3
"""
kuaidui-kit / check_capture_gz_parse.py — **`.txt.gz` 抓取必须解析得出 kind**。

### 为什么需要

2026-11-03：代码审查说“`capture_schema.py:45-52` 前缀表漏 10 个 kind”。
实测**一条都不漏** —— 但查出更要紧的一件事：

`iter_records()` 原来直接 `open(path)`，于是 `*.txt.gz` 被抓取被当成
gzip 的二进制字节读进来 —— **每一行都解析成 UNKNOWN**：

    r793/capture.txt.gz                      542/542  UNKNOWN
    r793/capture_emulator-5558_run2.txt.gz   237/237  UNKNOWN

后果不是“少读一半”，而是**整份抓取变成噪声**：任何按 kind 统计的工具都会显示
“这个包里什么都没有”，而真相是“这个包被 pack_slim 压过了”。

这是 `.gz` 盲区这一类缺陷里最严重的一处 —— 前面几处只是漏读，这里是**全量误读**。

### 判据

遍历 `work/packs/*/*.txt.gz`，每个都必须解析出**至少一条非 UNKNOWN** 记录。

### 退出码

0 = 全部解析得出；1 = 有 `.gz` 抓取整份都是 UNKNOWN。
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))

from capture_schema import iter_records                              # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad = []
    checked = 0
    for p in sorted(glob.glob(os.path.join(ROOT, 'work', 'packs', '*', '*.txt.gz'))):
        checked += 1
        known = unk = 0
        try:
            for r in iter_records(p):
                if r.kind == 'UNKNOWN':
                    unk += 1
                else:
                    known += 1
        except Exception as e:                                      # noqa: BLE001
            bad.append(f'{os.path.relpath(p, ROOT)} 读不了：{type(e).__name__}: {e}')
            continue
        if known == 0:
            bad.append(f'{os.path.relpath(p, ROOT)} 整份都是 UNKNOWN（{unk} 行）'
                       ' ⇒ iter_records 不认 .gz')
        elif a.verbose:
            print(f'  ✓   {os.path.relpath(p, ROOT)}  {known} 条已知 / {unk} UNKNOWN')

    print(f'[gzcap] 检查 {checked} 份 .txt.gz 抓取；整份 UNKNOWN 的 {len(bad)} 份')
    for b in bad:
        print(f'  ✗   {b}')
    if bad:
        print('[gzcap]   修法：`iter_records` 要走 `textio.read_text(path)`，'
              '不要直接 `open(path)`。')
        print('[gzcap]   这不是"少读一半"：整份抓取会变成噪声，'
              '按 kind 统计的工具只会显示"这个包里什么都没有"。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
