#!/usr/bin/env python3
"""
kuaidui-kit / race_test.py — 验证"重启后立刻读"不会产生假结论。

同一类竞态在这个项目里出现过三次（`module_report` 读到 0/17、证据包抓取读空、验收的 module alive 假红）：
宿主重启的那几秒里，**日志与抓取文件不是立即可读的**。修法是"有界等待 + 明确说明"，
但修完必须能证明它有效 —— 这就是这个脚本：

    1. 冷启宿主；
    2. **立刻**跑 `module_report`：允许"功能数不完整"，但不允许**静默给出错误结论**
       （必须显式说明"刚重启/稍等"，或已等到状态行）；
    3. 跑 `acceptance`：不允许因为这次冷启而出红（11/11）。

    python3 kit/scripts/race_test.py --adb emulator-5558
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
from device import PKG as PKG_CONST
import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
def sh(cmd, timeout=900):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    a = ap.parse_args(argv[1:])

    sh(['adb', '-s', a.adb, 'shell', f'am force-stop {PKG}'])
    sh(['adb', '-s', a.adb, 'shell', f'am start -n {PKG}/.AliasActivityDefault'])
    print('[race] 已冷启宿主，立刻读（不睡）')

    rc1, out1 = sh(f'python3 {HERE}/module_report.py --adb {a.adb}')
    m = re.search(r'打开的功能：(\d+)/(\d+)', out1)
    n = int(m.group(1)) if m else -1
    honest = ('刚重启' in out1) or (n > 0)
    print(f'[race] module_report 立刻读：功能数 {n}；是否诚实标注过"刚重启"：{"是" if "刚重启" in out1 else "否"}')
    ok1 = honest
    print(f'[race] {"ok " if ok1 else "FAIL"} 立刻读不产生静默错误结论')

    rc2, out2 = sh(f'python3 {HERE}/acceptance.py --adb {a.adb}', timeout=1200)
    m2 = re.search(r'(\d+)/(\d+) checks passed', out2)
    ok2 = bool(m2) and m2.group(1) == m2.group(2)
    print(f'[race] {"ok " if ok2 else "FAIL"} 冷启后验收：{m2.group(0) if m2 else "未跑出结果"}')
    if not ok2:
        print('\n'.join(l for l in out2.splitlines() if 'FAIL' in l)[:400])

    return 0 if (ok1 and ok2) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
