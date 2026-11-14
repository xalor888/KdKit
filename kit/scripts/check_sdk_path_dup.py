#!/usr/bin/env python3
"""
kuaidui-kit / check_sdk_path_dup.py — Android SDK 路径只许有一个来源。

### 为什么需要

2026-11-03 代码审查 P2：“macOS SDK 绝对路径 7 处”。

七个脚本各自写死 `$HOME/Library/Android/sdk`，于是：

* 换机器 / 用 `ANDROID_HOME` 装的人，七个地方都要改；
* 漏改一处的后果不是报错，而是**那条命令找不到 adb** ——
  而错误信息是 `adb: command not found`，指向“你没装 SDK”，
  与“你装在了别处”完全不像。

已收敛到 `kit/scripts/sdk_paths.sh`（认 `ANDROID_HOME` → `ANDROID_SDK_ROOT`
→ `$HOME/Library/Android/sdk`）。

### 判据

`kit/scripts/*.sh` 与 `module/scripts/*.sh` 里，除了 `sdk_paths.sh` 自己，
**不许**再出现 `Library/Android/sdk`。

### 退出码

0 = 只有一处；1 = 又写死了一处。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'scripts', '*.sh'),
        os.path.join(ROOT, 'module', 'scripts', '*.sh')]
ALLOWED = {os.path.relpath(os.path.join(ROOT, 'kit', 'scripts', 'sdk_paths.sh'), ROOT),
           os.path.relpath(os.path.abspath(__file__), ROOT)}   # 不扫自己

NEEDLE = 'Library/Android/sdk'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad = []
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED:
                continue
            for i, line in enumerate(textio.read_lines(p, encoding='utf-8', errors='replace'), 1):
                if NEEDLE in line and not line.strip().startswith('#'):
                    bad.append(f'{rel}:{i}')
                    print(f'  ✗   {rel}:{i}  {line.strip()[:70]}')

    print(f'[sdk] 写死 SDK 路径的地方：{len(bad)} 处')
    if bad:
        print('[sdk]   修法：`source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"`，'
              '然后用 `$SDK_ADB` / `$SDK_EMU` / `$SDK_ROOT`。')
        print('[sdk]   它认 `ANDROID_HOME` 与 `ANDROID_SDK_ROOT`。')
        return 1
    if a.verbose:
        print('[sdk] SDK 路径只有 sdk_paths.sh 一处 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
