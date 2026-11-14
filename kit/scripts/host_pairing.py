#!/usr/bin/env python3
"""
kuaidui-kit / host_pairing.py — 给"路径候选"，自动试**已知 host 集合**，输出命中矩阵。

为什么需要（2026-10-13，两次教训）：**字符串里的路径家族 ≠ 它的 host** ✗ ——
`/pigai/detail/*` 在 `www.` 而不在 `pigai.` ✓；`/adxserver/ad/getconfig` 在 `www.` 而不在 `adx.` ✓。
两次都是"手工换 host"才发现的关键事实 ⇒ 把它做成工具 ✓。

    python3 kit/scripts/host_pairing.py --paths-file /tmp/adx_paths.txt \
        --hosts adx.zuoyebang.com www.kuaiduizuoye.com --out work/HOST_PAIRING.md

默认：对每条路径先 GET 再 POST（`--method post` 可只试 POST）；命中即停（`--all` 可全试）。
"""
import argparse
import os
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
from device import default_serial


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_HOSTS = ['www.kuaiduizuoye.com', 'adx.zuoyebang.com', 'pigai.kuaiduizuoye.com',
                 'gtactivity.zuoyebang.com', 'resourceserver.zybang.com', 'yujie.yukeweb.com',
                 'abtest.zuoyebang.com', 'pluto.zuoyebang.com']


def newest(pat):
    import glob
    c = sorted(glob.glob(os.path.join(ROOT, pat)), key=os.path.getmtime, reverse=True)
    return c[0] if c else None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--paths-file', required=True)
    ap.add_argument('--hosts', nargs='*', default=DEFAULT_HOSTS)
    ap.add_argument('--adb', default=default_serial())
    ap.add_argument('--sign-a', default=None)
    ap.add_argument('--sign-b', default=None)
    ap.add_argument('--capture', default=None)
    ap.add_argument('--method', default='auto', choices=['auto', 'post', 'get'])
    ap.add_argument('--all', action='store_true', help='即使命中，也把其余 host 试完')
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'HOST_PAIRING.md'))
    a = ap.parse_args(argv[1:])

    sa = a.sign_a or newest('work/packs/*/reverify_signA.txt')
    sb = a.sign_b or newest('work/packs/*/reverify_signB.txt')
    cap = a.capture or newest('work/packs/*/capture.txt')
    paths = [l.strip() for l in open(a.paths_file) if l.strip().startswith('/')]
    print(f'[pair] 路径 {len(paths)} 条 × host {len(a.hosts)} 个（sign={os.path.basename(sa or "")}）')

    rows = []
    for p in paths:
        hit = None
        for h in a.hosts:
            methods = (['--post'] if a.method == 'post' else [''] if a.method == 'get' else ['--post', ''])
            for m in methods:
                cmd = (f'python3 {ROOT}/kit/python/kd_api.py call --adb {a.adb} '
                       f'--sign-a {sa} --sign-b {sb} --url https://{h}{p} '
                       f'--common-from {cap} {m} --insecure')
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='replace',
                                   timeout=120, stdin=subprocess.DEVNULL, start_new_session=True)
                out = (r.stdout or '') + (r.stderr or '')
                code = '200' if 'HTTP 200' in out else ('404' if 'HTTP 404' in out else 'other')
                if code == '200':
                    head = ''
                    for ln in out.splitlines():
                        if 'body head:' in ln:
                            head = ln.split('body head:', 1)[1].strip()[:60]
                    rows.append((p, h, code, head))
                    hit = h
                    if not a.all:
                        break
                else:
                    rows.append((p, h, code, ''))
            if hit and not a.all:
                break

    ok = [r for r in rows if r[2] == '200']
    text = ['# host 配对矩阵（自动）', '',
            f'* 路径 {len(paths)} 条 × host {len(a.hosts)} 个；**命中 {len(ok)}**', '',
            '| 路径 | host | HTTP | body |', '|---|---|---|---|']
    for p, h, c, head in rows:
        mark = ' ✅' if c == '200' else ''
        text.append(f'| `{p}` | `{h}` | {c}{mark} | {head} |')
    text += ['', '读法：**404 常常只是"host 打错了"**（见 `work/PARTNER_HOSTS.md` 追加二/三）✓', '']
    open(a.out, 'w').write('\n'.join(text) + '\n')
    print(f'[pair] -> {a.out}（命中 {len(ok)}/{len(rows)} 次尝试）')
    for p, h, c, head in ok[:6]:
        print(f'   ✅ {p} → {h}  {head}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
