#!/usr/bin/env python3
"""
kuaidui-kit / api_health.py — how *stable* is the guest endpoint surface?

`GUEST_API_SWEEP.md` shows one snapshot; a single 200 says nothing about flakiness. This runs the
same sweep N times and reports, per endpoint: how many runs answered 200, and what the failures
said. Useful before relying on an endpoint in automation, and it is the cheapest way to notice a
server-side change that only shows up intermittently.

    python3 kit/scripts/api_health.py --adb emulator-5558 --runs 3 --out work/GUEST_API_HEALTH.md
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import sh as _shmod
from device import PKG as PKG_CONST
from device import PREFS as PREFS_CONST
import os
import re
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
PREFS = PREFS_CONST


def sh(cmd, timeout=1800):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=900):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--runs', type=int, default=3)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    outdir = os.path.join(ROOT, 'work', 'packs', 'api_health')
    os.makedirs(outdir, exist_ok=True)
    cap = os.path.join(outdir, 'capture.txt')
    textio.write_text(cap, adb(a.adb, f'cat /data/data/{PKG}/files/kdkit_capture.txt')[1])
    ta, tb = os.path.join(outdir, 'signA.txt'), os.path.join(outdir, 'signB.txt')
    for f, key in ((ta, 'KEY_ANTISPAM_SIGN_A'), (tb, 'KEY_ANTISPAM_SIGN_B')):
        val = adb(a.adb, f"grep -o '{key}\"[^>]*>[^<]*' {PREFS}")[1]
        with open(f, 'w') as _f:
            _f.write(val.split('>', 1)[-1].strip() if '>' in val else '')

    results = defaultdict(list)          # path -> [(http, method, errno, payload_head)]
    for run in range(1, a.runs + 1):
        rc, out = sh(f'python3 {ROOT}/kit/python/kd_api.py pull --adb {a.adb} --sign-a {ta} '
                     f'--sign-b {tb} --capture {cap} --insecure --auto-method --all-paths')
        textio.write_text(os.path.join(outdir, f'sweep_run{run}.tsv'), out)
        n = 0
        for ln in out.splitlines():
            f = ln.rstrip('\n').split('\t')
            if len(f) == 5 and f[1].isdigit():
                results[f[0]].append((f[1], f[2], f[3], f[4]))
                n += 1
        print(f'[health] run {run}/{a.runs}: {n} endpoint(s)')

    def keys_of(payload):
        m = re.search(r'"data"\s*:\s*\{', payload)
        if not m:
            return frozenset()
        return frozenset(re.findall(r'"([A-Za-z_][\w]*)"\s*:', payload[m.end():]))

    rows = []
    for path, obs in sorted(results.items()):
        ok = sum(1 for o in obs if o[0] == '200')
        errs = sorted({o[2] or '-' for o in obs if o[0] != '200'})
        shapes = {keys_of(o[3]) for o in obs}
        content_stable = len(shapes) == 1
        rows.append((path, ok, len(obs), errs, content_stable))

    flaky = [r for r in rows if r[1] != r[2]]
    shape_flaky = [r for r in rows if not r[4]]
    text = ['# 游客接口面健康度（多轮稳定性）', '',
            f'* 设备 `{a.adb}`；每端点跑 **{a.runs}** 轮（`api_health.py`，命令内嵌 `kd_api.py pull --all-paths`）',
            f'* 端点总数 **{len(rows)}**；全绿 **{len(rows) - len(flaky)}**；有失败 **{len(flaky)}**', '',
            '| path | 成功/总轮次 | data 字段集稳定 | 失败时的 errNo/errstr |', '|---|---|---|---|']
    for path, ok, tot, errs, stable in rows:
        text.append(f'| `{path}` | {ok}/{tot} | {"是" if stable else "**否（字段集变过）**"} | '
                    f'{", ".join(errs) if errs else "-"} |')
    if flaky:
        text += ['', '## HTTP 层不稳定', ''] + [f'* `{p}`（{o}/{t}）' for p, o, t, _e, _s in flaky]
    if shape_flaky:
        text += ['', '## **内容**不稳定（HTTP 都 200，但 data 字段集变过 —— 自动化里别假设字段固定）', ''] \
            + [f'* `{p}`' for p, _o, _t, _e, _s in shape_flaky]
    text += ['', '**读法**：全绿 = 这几轮里稳定可依赖；有失败 = 要么服务端抖动，要么该端点有额外前置条件'
             '（例如需要某个 token/场景参数）—— 后者往往是"看起来能打、其实有条件"的坑。', '']
    out_text = '\n'.join(text) + '\n'
    if a.out:
        textio.write_text(a.out, out_text)
        print(f'[health] -> {a.out}')
    print(f'[health] {len(rows)} 端点；HTTP 全绿 {len(rows) - len(flaky)}；HTTP 不稳 {len(flaky)}；'
          f'内容字段集不稳 {len(shape_flaky)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
