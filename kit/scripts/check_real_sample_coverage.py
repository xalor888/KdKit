#!/usr/bin/env python3
"""
kuaidui-kit / check_real_sample_coverage.py — 哪些解析规则**只有 fixture 验证过**？

## 为什么需要这个报告

`capture_schema.py` 的规则有两个证据来源：

* **真实抓取**（`work/activity_inputs/*.txt`）—— 从真机导出的行；
* **fixture**（`kit/python/tests/fixtures/*.txt`）—— 人工构造的行。

`check_schema_roundtrip.py` 报"每条正则都被命中过"时，**两个来源合并算**。
于是一个只在 fixture 里存在的形态，会和真实样本享受同等信用。

这不是缺陷（没有真机时 fixture 是唯一选择），但它是一个**需要被看见**的边界：

> "规则全部被验证过" 有两种强度 —— 用真实数据验证，和用我构造的数据验证。

## 它输出什么

每个 kind 的**真实样本数**，并把"只有 fixture"的那些单独列出。
不判红：没有真机的日子里，23/39 只有 fixture 是常态，判红等于天天红。

## 用法

```bash
python3 kit/scripts/check_real_sample_coverage.py           # 人读
python3 kit/scripts/check_real_sample_coverage.py --brief   # 只报数字
```
"""
import argparse
import glob
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))

import capture_schema as cs  # noqa: E402


def count(files):
    c: Counter = Counter()
    for f in files:
        for r in cs.iter_records(f):
            if r.kind != 'UNKNOWN':
                c[r.kind] += 1
    return c


def main(argv):
    ap = argparse.ArgumentParser(description='哪些规则只有 fixture 验证过')
    ap.add_argument('--brief', action='store_true')
    a = ap.parse_args(argv[1:])

    real_files = sorted(glob.glob(os.path.join(ROOT, 'work', 'activity_inputs', '*.txt')))
    fix_files = sorted(glob.glob(os.path.join(ROOT, 'kit', 'python', 'tests', 'fixtures', '*.txt')))
    real, fix = count(real_files), count(fix_files)

    allk = {k for k, *_ in cs.RULES}
    with_real = sorted(allk & set(real))
    fixture_only = sorted(allk - set(real))

    print(f'[real] 真实抓取 {len(real_files)} 份 / fixture {len(fix_files)} 份')
    print(f'[real] kind 覆盖：真实 {len(with_real)}/{len(allk)}，'
          f'仅 fixture {len(fixture_only)}/{len(allk)}')

    if a.brief:
        return 0

    print()
    print('  有真实样本的 kind（按行数降序）：')
    for k in sorted(with_real, key=lambda x: -real[x]):
        print(f'    {k:14s} {real[k]:6d} 行')
    print()
    print('  **只有 fixture 覆盖**的 kind（真实抓取里没有这类行）：')
    for k in fixture_only:
        n = fix.get(k, 0)
        flag = '' if n else '  ← fixture 也没有（只在规则表里）'
        print(f'    {k:14s} fixture {n:4d} 行{flag}')
    # 顺带校验 fixture 的**忠实度**：它产出的每个 kind 都必须在
    # `PREFIX_FEATURE`（schema 自己维护的权威映射）里。
    #
    # 为什么这条值得有：验证"fixture 是否反映真实"时，我先试过两种**字面量扫描**
    # （找 `Capture.append("PREFIX …`) 和找 `"PREFIX ` 字符串），两种都误报 ——
    # `RC4PT`/`RC4UP` 走 `emit("RC4PT", ...)` 包装、`H5` 走 `record("H5 DECRYPT in", ...)`。
    # **字面量扫描猜不出"模块能产出哪些前缀"**，权威来源只有 schema 的映射表。
    strict_kinds = set()
    for f in fix_files:
        for r in cs.iter_records(f):
            strict_kinds.add(r.kind)
    extra = sorted(strict_kinds - set(cs.PREFIX_FEATURE) - {'UNKNOWN'})
    if extra:
        print(f'  **fixture 产出了 PREFIX_FEATURE 里没有的 kind**：{extra}')
        print('  这不是"样本更真实"，而是 schema 缺规则 —— 那些行在真实抓取里也会落 UNKNOWN。')
    else:
        print('  fixture 忠实度：所有 kind 都在 `PREFIX_FEATURE` 里（除负样本 UNKNOWN）')

    print()
    print('  这不是缺陷 —— 没有真机的日子里 fixture 是唯一选择。')
    print('  但"全部规则都被验证过"有两种强度：用真实数据验证 vs 用我构造的数据验证。')
    print('  有真机后重跑一次本脚本，数字会自己变好。')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
