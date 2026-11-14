#!/usr/bin/env python3
"""
kuaidui-kit / call_page_js.py — 把一段 JS 交给宿主页面执行（通用能力）。

原理：模块（宿主进程内）在每次 `onPageFinished` 后读取**配置通道**里的字符串 `page_js_script`，
若非空就 `evaluateJavascript` 执行 —— 于是"从外部触发页面自身逻辑"只需写一次配置 + 让页面重新加载。

    python3 kit/scripts/call_page_js.py --adb emulator-5558 --js "console.log('[KdKit] hello from kit')"
    python3 kit/scripts/call_page_js.py --adb emulator-5558 --clear          # 清空（不再执行）

注意：需要模块功能 `page_js` 为开（默认关）；写完配置后**要重新加载一次页面**才生效。
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--js', default=None, help='要执行的脚本（不传则只打印当前值）')
    ap.add_argument('--clear', action='store_true')
    a = ap.parse_args(argv[1:])

    pub = subprocess.run(['adb', '-s', a.adb, 'shell',
                          'ls /data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml 2>/dev/null | head -1'],
                         capture_output=True, text=True, timeout=180).stdout.strip()
    if not pub:
        print('[pagejs] 找不到发布配置（模块是否注入过？）')
        return 2
    cur = subprocess.run(['adb', '-s', a.adb, 'shell', f'cat {pub}'],
                         capture_output=True, text=True, errors='replace', timeout=180).stdout

    m = re.search(r'<string name="page_js_script">(.*?)</string>', cur, re.S)
    if a.js is None and not a.clear:
        print('[pagejs] 当前脚本：', (m.group(1)[:120] if m else '（空）'))
        return 0

    value = '' if a.clear else a.js
    # XML 转义（脚本里常有 < > & "）
    esc = (value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                .replace('"', '&quot;'))
    line = f'    <string name="page_js_script">{esc}</string>'
    if m:
        new = re.sub(r'<string name="page_js_script">.*?</string>', line.strip(), cur, flags=re.S)
    else:
        new = cur.replace('</map>', line + '\n</map>')

    tmp = '/tmp/kdkit_pagejs.xml'
    open(tmp, 'w').write(new)
    subprocess.run(['adb', '-s', a.adb, 'push', tmp, '/data/local/tmp/pj.xml'], capture_output=True, timeout=180)
    subprocess.run(['adb', '-s', a.adb, 'shell',
                    f"cp -f /data/local/tmp/pj.xml '{pub}'; chmod 644 '{pub}'"], capture_output=True, timeout=180)
    print(f"[pagejs] 已写入 {len(value)} 字符" + ('（已清空）' if a.clear else ''))
    print('[pagejs] 记得让页面**重新加载**一次（例如重新进入该页面）才会生效')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
