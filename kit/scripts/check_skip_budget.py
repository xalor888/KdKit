#!/usr/bin/env python3
"""
kuaidui-kit / check_skip_budget.py — **跳过的测试必须是登记过的、有上限的**。

### 为什么需要

2026-11-03 R108 的教训：

> 改一处之前，先问“谁还在依赖这个副作用”。而**跳过的测试不会告诉你** ——
> 所以 skip 数本身也该是个被盯的数字。

那天的事实：R101 给 `preflight.sh` 加了“每次清 `__pycache__`”，
于是 `test_verify_face.test_every_verdict_constant_survives`
（它读 `__pycache__/verify_face.cpython-314.pyc`）**每轮都 skip**。
skip 理由还写着“重建依据消失（换过 Python 版本？）”，
听着像环境问题 —— 其实是自己把依据删了。

**测试套件腐烂的方式不是变红，是变绿但验得越来越少。**
一条 skip 不会有任何迹象；十条也不会。只有把它变成数字才会。

### 判据

1. 跑一遍 Python 测试，收集每条 skip 的**理由**；
2. 理由必须在 `REASONS` 里**登记过**（含它允许的条数）；
3. 总 skip 数 ≤ `BUDGET`。

出现没登记过的理由 ⇒ 红。那意味着有人新加了一条跳过，
或者某条测试的跳过条件变了 —— 两种情况都该当场看见。

### 退出码

0 = skip 数在上限内且全部登记过；1 = 超限或出现未登记的理由。
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

#: 登记过的跳过理由 ⇒ 允许几条。
#:
#: 每一条都写清楚“为什么跳过是诚实的”：
#:   * 需要真机 —— 没有设备时跑不了，而**假装跑过**比跳过更坏；
#:   * 慢测试 —— 77 秒，放进每轮会让 verify.sh 从 3 分半变成 4 分半；
#:   * 输入不适用 —— 那条结论只对“MARK 为 0 行”的输入成立，当前输入有 2 行。
REASONS = {
    '需要真机：设 KD_TEST_SERIAL=<serial> 才跑（默认跳过，不假装验过）': 3,
    '没有真实令牌样本': 2,   # P1（blob 长度对但内容是乱码）需要真实 token；没样本时跳过是诚实的
    '慢测试（77s）：设 KDKIT_SLOW_TESTS=1 才跑': 1,
    # 实跑门禁 ④/⑤ 与 README 里的数对比 —— 17 秒，放进每轮会拖慢 verify.sh。
    '慢测试（~30s）：设 KDKIT_SLOW_TESTS=1 才跑': 1,
    '本份 ACTIVITY.md 的输入里 MARK 有 2 行 ⇒ 不适用 0 行那条结论': 2,
}

#: 总上限。刻意留 1 的余量：真机那三条在某些环境下会变成 2 条或 4 条。
BUDGET = 8

SKIP_RE = re.compile(r'\.\.\. skipped .(.*).$')


def collect():
    """从**测试运行缓存**里读 skip 理由（2026-11-03 改）。

    原来这道门禁自己跑一遍测试套件 —— 那要 **150 秒**，
    而同一个套件当天被 ①b / ㉥ / ㉦ 各跑一遍 ⇒ verify.sh 多花 5 分钟。
    现在统一走 `test_run.py` 的缓存：**跑一次，三道门禁读同一份结果**。

    缓存的失效判据在 `test_run.py` 里（解释器变了 / 超过 1 小时 /
    **源码比缓存新**）—— 最后一条是关键：改了代码必须重跑，
    否则这道缓存会变成"跑的是旧代码的结论"。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        '_test_run', os.path.join(ROOT, 'kit', 'scripts', 'test_run.py'))
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    rec = tr.ensure_suite(quiet=True)
    return dict(rec.get('skips', {})), '' 


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    got, raw = collect()
    total = sum(got.values())
    print(f'[skip] 跳过 {total} 条（上限 {BUDGET}）；登记过的理由 {len(REASONS)} 种')

    unknown = {r: n for r, n in got.items() if r not in REASONS}
    over = {r: (n, REASONS[r]) for r, n in got.items()
            if r in REASONS and n > REASONS[r]}

    for r, n in sorted(got.items(), key=lambda x: -x[1]):
        cap = REASONS.get(r)
        mark = '✓' if (cap is not None and n <= cap) else '✗'
        print(f'  {mark}   {n} 条  {r[:70]}')

    bad = False
    if unknown:
        print('[skip]   **没登记过的跳过理由** —— 要么有人新加了跳过，'
              '要么某条测试的跳过条件变了。两种情况都该当场看见：')
        for r, n in unknown.items():
            print(f'[skip]     ✗   {n} 条  {r[:80]}')
        bad = True
    if over:
        print('[skip]   **超出该理由的登记条数**：')
        for r, (n, cap) in over.items():
            print(f'[skip]     ✗   {r[:60]}  实际 {n} > 登记 {cap}')
        bad = True
    if total > BUDGET:
        print(f'[skip]   总跳过数 {total} > 上限 {BUDGET}')
        bad = True

    if bad:
        print('[skip]   修法：把新理由加进 `REASONS` 并写清"为什么跳过是诚实的"，'
              '或者**修好那条测试让它不必跳过**。')
        print('[skip]   R108 那次就是后者：一条测试每轮 skip，'
              '而它本该在验“重建没丢判据常量”。')
        return 1
    if a.verbose:
        print('[skip] 跳过数在上限内，理由全部登记过 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
