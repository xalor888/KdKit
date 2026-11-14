#!/usr/bin/env python3
"""
kuaidui-kit / guard_report.py — what the module's bridge guard actually blocked.

`BridgeGuard` appends one line per block to the same capture the rest of the kit reads:

    GUARD blocked=<action> reason=<blacklist|host_not_allowed> url=<url> #<n>

This turns that into the numbers a reviewer wants: how often, on which action, for which host,
and (for `host_not_allowed`) which host was refused — i.e. the evidence that the §8.1 finding
"pages can borrow the signed channel with no host restriction" is actually fenced off.

`#<n>` is the in-process counter, so `max(#n)` also answers "did the module's own budget
truncate the record?" — the writer stops at 5000 lines, and a capture whose highest `#n`
is below its own line count means the pulled file is a *slice*, not the whole session.

    adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
    python3 kit/python/guard_report.py cap.txt

Exit code 0 = at least one block found (the guard fired); 1 = none found (which is not an
error in itself — it may simply mean no page tried a forbidden action this session).
"""
import argparse
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from capture_schema import iter_records  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('capture')
    a = ap.parse_args(argv[1:])

    by_action, by_reason, hosts = Counter(), Counter(), Counter()
    rows = 0
    last_n = 0
    for rec in iter_records(a.capture):
        if rec.kind != 'GUARD':
            continue
        rows += 1
        by_action[rec.get('action')] += 1
        by_reason[rec.get('reason')] += 1
        if rec.get('host'):
            hosts[rec.get('host')] += 1
        if rec.get('seq'):
            last_n = max(last_n, rec.get('seq'))

    if not rows:
        print('[guard] 抓取里没有 GUARD 行 —— 守卫未开、没有命中，或抓取文件被清过')
        print('        （`bridge_guard` 默认关；`GUARD` 也只在真拦下时才写，放行不写。）')
        return 1

    print(f'[guard] {rows} block(s), 进程内计数最高 #{last_n}')
    print('  by action :', ', '.join(f'{k}={v}' for k, v in by_action.most_common()))
    print('  by reason :', ', '.join(f'{k}={v}' for k, v in by_reason.most_common()))
    if hosts:
        print('  top hosts :')
        for h, n in hosts.most_common(10):
            print(f'    {n:4d}  {h}')
    if last_n and rows < last_n:
        print(f'  ⚠ 抓取里只有 {rows} 条而计数已到 #{last_n} ⇒ 这份文件是**切片**'
              f'（轮转或写入上限 5000），不是整轮视图。')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
