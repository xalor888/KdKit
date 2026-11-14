#!/usr/bin/env python3
"""
kuaidui-kit / bridge_inventory.py — turn KdKit's two bridge observers into a live usage map of
the app's JS bridge.

`work/feactions.txt` is the *static* inventory (215 `@FeAction` classes). Two module features
record what the pages **actually call**, at two different granularities:

    H5BRIDGE <action> count=<n> <json args>          h5_bridge_log   — every action, raw JSON
    BRIDGE downloadMedia type=<n> url=<url>          bridge_action_log — semantic, 2 actions
    BRIDGE getuserinfo asked identity=<s>            bridge_action_log

The wide observer dominates by volume, so the semantic one is reported as a separate column
("this action was also seen *semantically*") instead of being merged into the counts — merging
them would double-count the same call and make the static/dynamic gap look bigger than it is.

    adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
    python3 bridge_inventory.py cap.txt [--static ../work/feactions.txt] [--json out.json]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from capture_schema import iter_records  # noqa: E402


def load_static(path):
    if not path:
        return set()
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return set()
    return {m.group(1) for m in re.finditer(r'^([A-Za-z_][\w_]*)\s+\S+\.java$', text, re.M)}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('capture')
    ap.add_argument('--static', default=None, help='feactions.txt for the static/dynamic gap')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv[1:])

    calls, samples = Counter(), {}
    semantic = Counter()                     # action -> how many *semantic* observations
    detail = defaultdict(list)               # action -> readable one-liners
    for rec in iter_records(a.capture):
        if rec.kind == 'H5BRIDGE':
            action = rec.get('action')
            calls[action] = max(calls[action], rec.get('count') or 0)
            if action not in samples and rec.get('args'):
                samples[action] = rec.get('args')
        elif rec.kind == 'BRIDGE':
            # 每个 BRIDGE 变体都必须带 `action`（schema 侧由 `KindFieldContract` 断言）。
            # 但这里仍然兜一层：一个**新变体**漏字段时，本脚本是"统计工具"，
            # 它应该报出这条记录而不是抛 `TypeError: None < str` 整段崩掉 ——
            # 崩溃会让"有多少条"这个本来能回答的问题变成不可回答。
            # 第 28 轮就是这么炸的（`payorder` 漏 `action`），而修法不是改这里，
            # 是补 schema 的字段契约；此处只保证消费端不会把统计变成崩溃。
            action = rec.get('action') or f'(未知变体:{rec.variant})'
            semantic[action] += 1
            if rec.variant == 'download':
                detail[action].append(f'type={rec.get("type")} url={str(rec.get("url"))[:90]}')
            elif rec.variant == 'payorder':
                detail[action].append(
                    f'len={rec.get("len")} shape={rec.get("shape")} keys={rec.get("keys")}')
            else:
                detail[action].append(f'identity={rec.get("identity")}')

    total = sum(calls.values())
    print(f'[bridge] {len(calls)} distinct action(s) via H5BRIDGE, {total} call(s) recorded')
    for action, n in sorted(calls.items(), key=lambda kv: (-kv[1], kv[0])):
        sample = samples.get(action, '')
        try:
            preview = json.dumps(json.loads(sample), ensure_ascii=False)[:110] if sample else ''
        except Exception:
            preview = sample[:110]
        mark = '  ← 语义层也记到' if action in semantic else ''
        print(f'  {n:4d}  {action:38s} {preview}{mark}')

    if semantic:
        print(f'\n[bridge] 语义层（bridge_action_log）{sum(semantic.values())} 条，'
              f'{len(semantic)} 个 action：')
        for action, n in sorted(semantic.items(), key=lambda kv: (-kv[1], kv[0])):
            uniq = sorted(set(detail[action]))
            print(f'  {n:4d}  {action:24s} {uniq[0]}')
            for extra in uniq[1:4]:
                print(f'  {"":4s}  {"":24s} {extra}')
            if len(uniq) > 4:
                print(f'  {"":4s}  {"":24s} …（另 {len(uniq) - 4} 种）')
    else:
        print('\n[bridge] 无语义层记录（`bridge_action_log` 默认关）')

    static = load_static(a.static)
    if static:
        used = set(calls) | set(semantic)
        print(f'\n[bridge] 静态清单 {len(static)} 个 action；本轮业务里见过 {len(used & static)} 个；'
              f'见过但静态清单里没有: {sorted(used - static) or "无"}')
        print(f'[bridge] 静态清单里没被本轮触发的: {len(static - used)} 个'
              f'（不是"不存在"，只是这一轮没走到）')

    if a.json:
        json.dump({'calls': dict(calls), 'semantic': dict(semantic),
                   'samples': samples, 'static_size': len(static)},
                  open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'[bridge] -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
