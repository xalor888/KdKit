#!/usr/bin/env python3
"""
kuaidui-kit / api_login_map.py — split the app's endpoint surface into "guest-reachable" vs "we have
never seen it answer".

The main API host refuses a freely-constructed parameter set (TRIAGE §8.2 / R27–R28: `errNo 6`), so
"probe it and see" does not work there. What *does* work is the evidence we already have: every path
the app itself called while in the **guest** state (`uid=0`) is, by construction, guest-reachable.
Everything else is "unobserved" — and among those, the ones whose name looks account-scoped are the
first place to look once an account exists.

    python3 kit/scripts/api_login_map.py --apk work/apktool_out --captures 'work/packs/*/capture*.txt' \
        --out work/API_LOGIN_MAP.md
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import capture_schema
import textio                                  # noqa: E402  （.gz 感知读取，2026-11-03 收敛）
import argparse
import glob
import os
import re
import sys
import urllib.parse
from collections import Counter

def read_lines(path):
    """抓取文件可能被 `pack_slim.py` 压成 .gz（证据不删、只压缩），两个形态都要能读。"""
    return textio.read_lines(path)      # 2026-11-03：四份逐字相同的读取器收敛成 `textio`
    # **必须写 `textio.` 而不是裸 `read_lines`**：本文件里就有同名函数，
    # 裸调用会无限递归（第一版就这么崩的，RecursionError）。


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ROOTS = ('pluto', 'plutov2', 'kdapi', 'kdcore', 'kdchat', 'userident', 'codesearch', 'init',
         'napi', 'activity', 'hegui', 'pigai', 'abengine', 'adxserver', 'kdbook', 'session')
ACCOUNTISH = re.compile(r'(session|user|account|login|logout|vip|order|pay|cashier|card|member|'
                        r'collect|coupon|wallet|bind|realname|idcard|message|notify|redpacket)', re.I)


def apk_paths(apk_dir):
    paths = set()
    rx = re.compile(r'"(/[A-Za-z0-9_\-/]{4,60})"')
    for root, _dirs, files in os.walk(apk_dir):
        for fn in files:
            if not fn.endswith('.smali'):
                continue
            try:
                text = textio.read_text(os.path.join(root, fn), encoding='utf-8', errors='replace')
            except OSError:
                continue
            for m in rx.finditer(text):
                p = m.group(1)
                if p.lstrip('/').split('/')[0] in ROOTS and '{' not in p and p.count('/') >= 2 \
                        and not re.search(r'\.(png|jpe?g|js|css|html?|json|ttf|svg)$', p, re.I):
                    paths.add(p)
    return paths


def captured_paths(globs):
    seen, per_host = set(), Counter()
    for g in globs:
        for path in glob.glob(g):
            try:
                lines = read_lines(path)
            except OSError:
                continue
            for u in capture_schema.sign_urls(lines):
                try:
                    pu = urllib.parse.urlparse(u)
                except ValueError:
                    continue
                if pu.path:
                    seen.add(pu.path)
                    per_host[pu.netloc] += 1
    return seen, per_host


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk', default=os.path.join(ROOT, 'work', 'apktool_out'))
    # **两个 glob 都要列**（2026-11-03 修）：`pack_slim` 会把 `--keep` 之外的
    # 旧包压成 `.txt.gz`。只列 `.txt` 时不带 `--captures` 跑会**静默漏掉它们**，
    # 而报告里只会显示"路径变少了"。
    ap.add_argument('--captures', nargs='+',
                    default=[os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt'),
                             os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt.gz'),
                             os.path.join(ROOT, 'work', 'dpsdk', 'capture*.txt')])
    ap.add_argument('--out', default=None,
                        help='**不给 `--out` 会覆盖仓库里那份正式文档** —— 冒烟测试一律显式给 `--out /tmp/x.md`。')
    a = ap.parse_args(argv[1:])

    cand = apk_paths(a.apk)
    seen, per_host = captured_paths(a.captures)

    guest = sorted(cand & seen)
    unobserved = sorted(cand - seen)
    accountish = [p for p in unobserved if ACCOUNTISH.search(p)]
    other = [p for p in unobserved if p not in accountish]

    out = ['# 接口面 × 登录态：哪些游客就能打、哪些没见过', '',
           f'* APK 里挖出的候选路径：**{len(cand)}** 条',
           f'* 抓取里**游客态真的调用过**的路径：**{len(seen)}** 条（其中属于候选集的 {len(guest)} 条）',
           f'* 抓取见过的主机：' + ', '.join(f'`{h}`×{n}' for h, n in per_host.most_common(6)), '',
           '## 1 游客可达（App 自己在 uid=0 下调用过）', '',
           f'共 **{len(guest)}** 条 —— 这些不需要登录即可被调用（由 App 自身行为证明，不是推断）：', '']
    for p in guest:
        out.append(f'* `{p}`')

    out += ['', '## 2 没见过应答、且**名字像账号域**（有账号后第一批看这里）', '',
            f'共 **{len(accountish)}** 条：' if accountish else '（无）', '']
    for p in accountish[:80]:
        out.append(f'* `{p}`')

    out += ['', '## 3 没见过应答、名字也不像账号域', '',
            f'共 **{len(other)}** 条（可能是冷路径、活动页、或已下线）：', '']
    for p in other[:40]:
        out.append(f'* `{p}`')
    if len(other) > 40:
        out.append(f'* _（还有 {len(other) - 40} 条）_')

    out += ['', '## 方法与限制', '',
            '* "游客可达"= **App 自己在 `uid=0` 时调用过**（抓取为证）；不是我们推断的；',
            '* 主接口域拒绝自由构造参数集（§8.2），所以**不能**靠离线探测来分类，只能靠"见过/没见过"；',
            '* "没见过"里混着三种情况：需要登录、需要特定流程/活动、或已下线 —— 有账号后用',
            '  `session_snapshot.py --diff` 与真机抓取即可区分。', '']

    text = '\n'.join(out) + '\n'
    if a.out:
        textio.write_text(a.out, text)
        print(f'[map] -> {a.out}')
    print(f'[map] 候选 {len(cand)}；游客可达 {len(guest)}；未见·账号域 {len(accountish)}；未见·其它 {len(other)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
