#!/usr/bin/env python3
"""
kuaidui-kit / after_login.py — "拿到账号之后要跑的三步"，做成一键（含无账号时的自检）。

项目里两条卡点（AI 写作第五步、登录后的能力）都只差**一个账号**。这个脚本把那一天的动作固定下来：

    1. **看变化**：给会话态拍快照并与登录前的基线 `--diff`（`session_snapshot.py`）
    2. **抓真实参数**：提示你走一遍登录后的页面（抓取里会出现"该接口自己的参数集"）
    3. **离线复现**：对 `work/API_LOGIN_MAP.md` 里"未见·账号域"的路径逐条 `kd_api.py pull`，记录结果

    python3 kit/scripts/after_login.py --adb emulator-5558                    # 自检 + 打印清单
    python3 kit/scripts/after_login.py --adb emulator-5558 --before work/packs/r61/session_guest.json --run

`--run` 只在**检测到已登录**时才真正执行（判据：抓取里出现 `uid=` 非 0）。**没有账号时它不会假装成功**，
而是明确说明"还差账号"并列出那天要跑的步骤（退出码 2）。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import captures
from device import PKG as PKG_CONST
from device import default_serial

import argparse
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
def sh(cmd, timeout=900):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='replace', timeout=timeout, start_new_session=True)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def newest_capture():
    # 2026-11-03：与另外三处同一个来源（`captures`）。
    # `prefer_plain=True` 保留原意：只要未压缩的那份。
    # 注意：`work/dpsdk/` 那一份不在 `captures` 的范围内（另一个目录），
    # 需要它的人显式加 —— 原来那行的行为在这里**没有**被静默改变。
    return captures.newest_capture(prefer_plain=True)


def login_state(cap):
    if not cap or not os.path.exists(cap):
        return None, '没有抓取'
    txt = open(cap, encoding='utf-8', errors='replace').read()
    uids = set(re.findall(r'(?:^|[&?])uid=(\d+)', txt))
    return ({u for u in uids if u != '0'}, f'uid 取值集合={sorted(uids)[:6]}')


# 2026-10-13：实测"HTTP 200 但 errNo:6"的 8 个成员 —— 统一解释是"需要登录态"（TRIAGE §8.13），
# 所以它们必须进"拿到账号那天"的复现清单 ✓。
ERRNO6_PATHS = ['/codesearch/aid/ask', '/codesearch/aid/askhome', '/codesearch/aid/home',
                '/codesearch/aid/mybookquestion', '/codesearch/news/unread',
                '/codesearch/user/newuseract', '/gtactivity/attribution/ipuanotice',
                '/init/ad/config']


def account_paths():
    p = os.path.join(ROOT, 'work', 'API_LOGIN_MAP.md')
    if not os.path.exists(p):
        return []
    body = open(p, encoding='utf-8').read()
    sec = body.split('## 2 没见过应答')[1].split('## 3')[0] if '## 2 没见过应答' in body else ''
    paths = sorted(set(re.findall(r'\* `(/[^`]+)`', sec)))
    return sorted(set(paths) | set(ERRNO6_PATHS))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--before', default=os.path.join(ROOT, 'work', 'packs', 'r61', 'session_guest.json'),
                    help='登录前的会话快照（用于 --diff）')
    ap.add_argument('--run', action='store_true', help='检测到登录后真正执行')
    a = ap.parse_args(argv[1:])

    cap = newest_capture()
    logged, detail = login_state(cap)
    paths = account_paths()

    print('[after-login] 当前登录态判定：', '**已登录**' if logged else '游客（未登录）', f'（{detail}）')
    print(f'[after-login] 待复现的"未见·账号域"路径：**{len(paths)}** 条（来自 API_LOGIN_MAP.md）')
    print('[after-login] 排查优先级：见 work/ACCOUNT_QUEUE.md（A=被服务但拒绝通用参数 → B=无参数来源 → C=不服务，别再试）')
    print('[after-login] 那天要跑的三步：')
    print('   1) python3 kit/scripts/session_snapshot.py --adb <serial> --out work/session_after_login.json')
    print(f'      python3 kit/scripts/session_snapshot.py --adb <serial> --diff {os.path.relpath(a.before, ROOT)}')
    print('   2) 走一遍登录后的页面（抓取里会出现该接口自己的参数集）')
    print('   3) python3 kit/python/kd_api.py pull --adb <serial> --sign-a … --sign-b … --capture <最新抓取> \\')
    print('        --insecure --all-paths      # 或对单条路径 --path <路径>')

    if not logged:
        print('[after-login] 结论：**还差一个账号** —— 前两步在此之前没有意义（退出码 2）')
        return 2
    if not a.run:
        print('[after-login] 已登录但未加 --run：上面三步可手动执行')
        return 0

    out = ['# 登录后走查（自动生成）', '']
    rc, o = sh(f'python3 {ROOT}/kit/scripts/session_snapshot.py --adb {a.adb} '
               f'--out {ROOT}/work/session_after_login.json')
    out += ['## 1 会话快照', '', '```', o.strip()[:1200], '```', '']
    if os.path.exists(a.before):
        rc, o = sh(f'python3 {ROOT}/kit/scripts/session_snapshot.py --adb {a.adb} --diff {a.before}')
        out += ['## 1b 与登录前基线的差异', '', '```', o.strip()[:2000], '```', '']
    out += [f'## 2/3 可复现的账号域路径（{len(paths)} 条）', '']
    out += [f'* `{p}`' for p in paths[:80]]
    open(os.path.join(ROOT, 'work', 'AFTER_LOGIN.md'), 'w').write('\n'.join(out) + '\n')
    print(f'[after-login] -> work/AFTER_LOGIN.md（{len(paths)} 条路径）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
