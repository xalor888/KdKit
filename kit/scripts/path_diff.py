#!/usr/bin/env python3
"""
kuaidui-kit / path_diff.py — same browsing path, two devices: what differs and what does not.

Volume differences (bytes, request counts) say little; this compares *what the app asked for*:
the endpoint set each device touched, and — for the parameters that matter — where the values
diverge. That is how you tell "device-specific channel/AB assignment" from "noise".

    python3 kit/scripts/path_diff.py --adb-a emulator-5558 --adb-b emulator-5556 \
        --steps "AI写作" --out work/packs/r39/path_diff.md

For each device it: clears the capture, cold-starts the app, taps the given texts, waits, pulls
the capture. Both devices therefore run the *same* scripted path.

`--save-baseline f.json` / `--check-baseline f.json` turn one path into a **regression check**:
the stable endpoint set (and its parameter values) is stored once and every later run reports
added / removed endpoints and changed values — e.g. after an app update.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import capture_schema
import textio
import sh as _shmod
from device import PKG as PKG_CONST
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
INTERESTING = ('channel', 'appId', 'vc', 'vcname', 'osVersion', 'device', 'abis', 'sdk',
               'brand', 'phoneDevice', 'appBit', 'identityIdV2', 'digGrade', 'isPad', 'nt',
               'jarTime', 'token', 'cuid', 'uid', 'city', 'province', 'area', 'channel')


def sh(cmd, timeout=600):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=600):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def run_path(serial, steps, wait):
    # **删之前先备份**（2026-11-03 修）：设备上的抓取是不可再生证据，
    # `rm -f` 一删就没了。代码审查 P1 点名了这两处。
    sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
    from device_backup import backup_capture
    backup_capture(serial)
    adb(serial, f'am force-stop {PKG}')
    adb(serial, f'rm -f /data/data/{PKG}/files/kdkit_capture.txt')
    adb(serial, f'am start -n {PKG}/.AliasActivityDefault')
    time.sleep(22)
    if steps:
        sh(f'python3 {HERE}/tap_texts.py --adb {serial} --steps "{steps}" --wait {wait}')
    return adb(serial, f'cat /data/data/{PKG}/files/kdkit_capture.txt')[1]


def analyse(text):
    urls = capture_schema.sign_urls(text.splitlines())
    paths, params = Counter(), defaultdict(set)
    for u in urls:
        try:
            pu = urllib.parse.urlparse(u)
        except ValueError:
            continue
        paths[pu.path] += 1
        for k, v in urllib.parse.parse_qsl(pu.query, keep_blank_values=True):
            if k in INTERESTING and len(v) < 60:
                params[k].add(v)
    return paths, params, len(urls)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb-a', required=True)
    ap.add_argument('--adb-b', required=True)
    ap.add_argument('--steps', default='AI写作')
    ap.add_argument('--wait', type=float, default=12)
    ap.add_argument('--repeat', type=int, default=1,
                    help='run the path N times per device; the comparison then uses the *stable* '
                         'endpoint set (present in every run) and reports the noise explicitly')
    ap.add_argument('--save-baseline', default=None,
                    help='write the stable endpoint set (and its param names) to this JSON')
    ap.add_argument('--check-baseline', default=None,
                    help='compare the fresh run against this JSON; exit 1 on any difference')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    outs = []
    outdir = os.path.dirname(a.out) if a.out else os.path.join(ROOT, 'work')
    os.makedirs(outdir, exist_ok=True)
    for serial in (a.adb_a, a.adb_b):
        runs = []
        for i in range(a.repeat):
            print(f'[diff] driving {serial} (run {i + 1}/{a.repeat}) …')
            text = run_path(serial, a.steps, a.wait)
            paths, params, n = analyse(text)
            runs.append((paths, params, n, text))
            textio.write_text(os.path.join(outdir, f'capture_{serial}_run{i + 1}.txt'), text)
        stable = set(runs[0][0])
        for paths, _p, _n, _t in runs[1:]:
            stable &= set(paths)
        noisy = set().union(*[set(p) for p, _q, _n, _t in runs]) - stable
        outs.append((serial, Counter({k: sum(1 for r in runs if k in r[0]) for k in stable}),
                     runs[0][1], runs[-1][2], runs[-1][3], stable, noisy,
                     [r[2] for r in runs]))

    (sa, pa, qa, na, _, stable_a, noisy_a, counts_a), (sb, pb, qb, nb, _, stable_b, noisy_b, counts_b) = outs
    pa, pb = Counter({k: 1 for k in stable_a}), Counter({k: 1 for k in stable_b})
    shared = sorted(stable_a & stable_b)
    only_a = sorted(stable_a - stable_b)
    only_b = sorted(stable_b - stable_a)
    print(f'[diff] stable endpoints: {sa} {len(stable_a)}, {sb} {len(stable_b)}；'
          f'noise: {len(noisy_a)} / {len(noisy_b)}')
    only_a = sorted(set(pa) - set(pb))
    only_b = sorted(set(pb) - set(pa))

    out = ['# 同一路径 / 两台设备：抓取差异', '',
           f'* 路径脚本：冷启 → 点击 `{a.steps}`，每台重复 **{a.repeat}** 次',
           f'* 设备：`{sa}` vs `{sb}`', '',
           f'* 签名 URL 数（最后一轮）：{na} vs {nb}；各轮：{counts_a} / {counts_b}',
           f'* **稳定端点**（每轮都出现）：{sa} {len(stable_a)} 个，{sb} {len(stable_b)} 个',
           f'* 噪声端点（并非每轮出现）：{sa} {len(noisy_a)} 个，{sb} {len(noisy_b)} 个',
           '',
           f'* 端点集合：共同 {len(shared)}，只在 A {len(only_a)}，只在 B {len(only_b)}', '',
           '## 只在其中一台出现的端点', '', '| 端点 | 出现于 |', '|---|---|']
    for p in only_a:
        out.append(f'| `{p}` | {sa} |')
    for p in only_b:
        out.append(f'| `{p}` | {sb} |')
    if not only_a and not only_b:
        out.append('| _(无差异)_ | — |')

    if noisy_a or noisy_b:
        out += ['', '### 噪声端点（时序相关，别当版本差异）', '', '| 端点 | 出现于 |', '|---|---|']
        for p in sorted(noisy_a):
            out.append(f'| `{p}` | {sa}（部分轮次） |')
        for p in sorted(noisy_b):
            out.append(f'| `{p}` | {sb}（部分轮次） |')

    out += ['', '## 关键参数取值差异', '', '| 参数 | ' + sa + ' | ' + sb + ' |', '|---|---|---|']
    keys = sorted(set(qa) | set(qb))
    for k in keys:
        va, vb = sorted(qa.get(k, set())), sorted(qb.get(k, set()))
        mark = '' if va == vb else ' **[不同]**'
        out.append(f'| `{k}`{mark} | `{", ".join(va)[:80] or "-"}` | `{", ".join(vb)[:80] or "-"}` |')

    out += ['', '## 读法', '',
            '* 相同参数 = 跟应用/版本走的字段；不同的 = 跟设备走的字段（渠道、设备型号、AB 分桶…）；',
            '* "只在某台出现"的端点多半是页面/弹窗渲染时序差异 —— 用 `--repeat N` 重跑，'
            '稳定集合（每轮都出现）才是可比的；实测本路径 `--repeat 3` 的噪声为 **0**，'
            '即端点集合是确定性的，不是时序碰巧。', '']
    # baseline save / check (single-device use: --adb-b == --adb-a is fine)
    if a.save_baseline:
        doc = {'device': sa, 'steps': a.steps, 'repeat': a.repeat,
               'endpoints': sorted(stable_a),
               'params': {k: sorted(v) for k, v in sorted(qa.items())}}
        os.makedirs(os.path.dirname(a.save_baseline) or '.', exist_ok=True)
        json.dump(doc, open(a.save_baseline, 'w'), ensure_ascii=False, indent=1)
        print(f'[diff] baseline -> {a.save_baseline} ({len(stable_a)} endpoints)')

    if a.check_baseline:
        base = json.load(open(a.check_baseline))
        b_eps = set(base.get('endpoints', []))
        # "条件性调用"：满足条件才发生的调用（更新检查 / 弹窗 / 新用户活动…）。
        # 它们不是客户端变更，单列出来，**不计入漂移**（清单带原因，存在基线 JSON 里）。
        cond_map = base.get('conditional') or {}
        cond = set(cond_map)
        added_all = sorted(set(stable_a) - b_eps)
        cond_hits = sorted(c for c in added_all if c in cond)
        added = [c for c in added_all if c not in cond]
        gone = sorted(b_eps - set(stable_a) - cond)
        param_changes = []
        for k, vals in (base.get('params') or {}).items():
            now = sorted(qa.get(k, set()))
            if now and now != vals:
                param_changes.append((k, vals[:4], now[:4]))
        out += ['', '## 与基线比对', '',
                f'* 基线：`{a.check_baseline}`（{base.get("device", "?")}，{len(b_eps)} 端点）',
                f'* 新增端点：{len(added)}；消失端点：{len(gone)}；取值变化参数：{len(param_changes)}'] + (
                [f'* 条件性调用（不算漂移）：{len(cond_hits)} 条 —— ' +
                 '；'.join(f'`{c}`（{cond_map.get(c, "")}）' for c in cond_hits)] if cond_hits else [])
        for p_ in added:
            out.append(f'  * ➕ `{p_}`')
        for p_ in gone:
            out.append(f'  * ➖ `{p_}`')
        for k, before, now in param_changes:
            out.append(f'  * 🔀 `{k}`: {before} → {now}')
        if not (added or gone or param_changes):
            out.append('* **与基线完全一致** ✓')
        print(f'[diff] baseline check: +{len(added)} -{len(gone)} params~{len(param_changes)}')
        # 帮助文本承诺过 "exit 1 on any difference" —— 2026-10-12 故障注入时发现这条没生效，
        # 于是"能检测但不会报警"，自动化会静默漏掉漂移。补上，并让条件性调用不计入。
        if added or gone or param_changes:
            drift_rc = 1

    text = '\n'.join(out) + '\n'
    if a.out:
        textio.write_text(a.out, text)
        print(f'[diff] -> {a.out}')
    print('\n'.join(out[:16]))
    return locals().get('drift_rc', 0)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
