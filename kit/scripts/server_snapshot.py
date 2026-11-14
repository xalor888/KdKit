#!/usr/bin/env python3
"""
kuaidui-kit / server_snapshot.py — 服务端**响应内容**的漂移面（比 `server_shape` 更深一层）。

`server_shape` 只看"字段集合与列表长度"；这个工具看**值**：把每个 endpoint 的响应
**归一化**（去掉时间戳/随机串等易变字段 ✓）后取哈希，与上一次快照比较 —— 于是
"服务端悄悄改了内容"（文案、模板、图标 URL、类型表…）会被看见 ✓。

    python3 kit/scripts/server_snapshot.py --current work/packs/rN/responses.json \
        --previous work/packs/rN-1/responses.json --out work/SERVER_SNAPSHOT.md

快照由 `kd_api.py pull --all-paths --dump <file>` 生成（见 work/REPRODUCTION.md ✓）。
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

VOLATILE = re.compile(r'("(?:t|ts|_t_|timestamp|serverTime|curTime|now|expire|nonce|requestId|traceId|sessionId|sid)"\s*:\s*)'
                      r'("[^"]*"|\d+)')


def normalize(text):
    """去掉易变字段的值，再压掉空白 —— 只留下"内容"本身。"""
    t = VOLATILE.sub(r'\1"<volatile>"', text)
    t = re.sub(r'\s+', ' ', t)
    return t


def digest(text):
    return hashlib.sha256(normalize(text).encode('utf-8', 'replace')).hexdigest()[:16]


def skeleton(obj, depth=0):
    """结构骨架（键 + 类型 ✓）—— 2026-10-12 加 ✓。

    由来：R273/R274 量出"易变集合"的 5 位**结构都稳定** ✓、只有**值**在轮换 ✗。
    ⇒ 把这条判据接进本面 ✓：**结构变了才是真异常** ✓，值变了可能只是轮换 ✓。
    """
    if depth > 6:
        return '…'
    if isinstance(obj, dict):
        return {k: skeleton(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [skeleton(obj[0], depth + 1)] if obj else []
    return type(obj).__name__


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--current', required=True)
    ap.add_argument('--previous', default=None)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    cur = json.load(open(a.current, encoding='utf-8'))
    prev = json.load(open(a.previous, encoding='utf-8')) if a.previous and os.path.exists(a.previous) else {}

    rows = []
    for path, rec in sorted(cur.items()):
        body = rec.get('body', '') if isinstance(rec, dict) else str(rec)
        h = digest(body)
        old = digest(prev[path]['body']) if path in prev and isinstance(prev[path], dict) else None
        rows.append((path, h, old, 'new' if old is None else ('same' if old == h else 'CHANGED')))

    # 2026-10-13：读"动态/轮换"清单 —— 真正有信息量的信号是"**稳定集合里有没有动静**"（见 work/VOLATILITY.md）
    vol = {}
    vol_path = os.path.join(ROOT, 'work', 'volatility.json')
    if os.path.exists(vol_path):
        try:
            vol = json.load(open(vol_path, encoding='utf-8'))
        except Exception:
            vol = {}
    dyn = set(vol.get('dynamic') or [])
    rot = set(vol.get('rotating') or [])
    changed = [r for r in rows if r[3] == 'CHANGED']
    stable_changed = [r for r in changed if r[0] not in dyn and r[0] not in rot]
    dyn_changed = [r for r in changed if r[0] in dyn]
    rot_changed = [r for r in changed if r[0] in rot]
    # 结构形态比对（与上次 ✓）
    skel_now = {}
    for path, rec in sorted(cur.items()):
        try:
            body = rec['body'] if isinstance(rec, dict) else str(rec)
            skel_now[path] = hashlib.sha256(
                json.dumps(skeleton(json.loads(body)), sort_keys=True).encode()).hexdigest()[:12]
        except Exception:
            skel_now[path] = '?'
    skel_prev = {}
    if prev:
        for path, rec in sorted(prev.items()):
            try:
                body = rec['body'] if isinstance(rec, dict) else str(rec)
                skel_prev[path] = hashlib.sha256(
                    json.dumps(skeleton(json.loads(body)), sort_keys=True).encode()).hexdigest()[:12]
            except Exception:
                pass
    skel_changed = [p for p in skel_now if p in skel_prev and skel_now[p] != skel_prev[p]]

    text = ['# 服务端响应内容快照（值级漂移面）', '',
            f'* **结构形态变化：{len(skel_changed)}** ← **这才是"真异常"** ✓（值变多半只是轮换 ✓）',
            f'* **稳定集合变化：{len(stable_changed)}** ← 这才是信号（>0 才值得看）',
            f'* 动态集合变化：{len(dyn_changed)}（按请求动态，预期每次都变 ✓）｜轮换集合变化：{len(rot_changed)}（预期偶尔 ✓）',
            f'* endpoint 数：**{len(rows)}**；总计变化 {len(changed)}、相同 {sum(1 for r in rows if r[3]=="same")}、'
            f'新增基线 {sum(1 for r in rows if r[3]=="new")}', '',
            '* 归一化：去掉 `t/ts/timestamp/sessionId/sid/nonce/…` 这类易变字段后再哈希 ✓（只看"内容"）', '',
            '| endpoint | 内容哈希 | 状态 |', '|---|---|---|']
    for path, h, _old, st in rows:
        mark = {'same': '✓', 'new': '（基线）', 'CHANGED': '**变了**'}[st]
        text.append(f'| `{path}` | `{h}` | {mark} |')
    text += ['', '读法：`变了` 表示**服务端返回的内容**与上次不同（不是我们这边变了）——'
                 '配合 `DRIFT.md` 的其它面判断"是内容更新还是接口改版" ✓', '']
    target = a.out or os.path.join(ROOT, 'work', 'SERVER_SNAPSHOT.md')
    open(target, 'w').write('\n'.join(text) + '\n')
    print(f'[snap] -> {target}（稳定集合变化 {len(stable_changed)}；动态 {len(dyn_changed)}；轮换 {len(rot_changed)}；'
          f'**结构形态变化 {len(skel_changed)}**；共 {len(rows)} 个 endpoint）')
    for path, _h, _o, _st in stable_changed[:6]:
        print(f'   ★ 稳定集合变化: {path}')
    for path in skel_changed[:6]:
        print(f'   ★★ 结构形态变化（真异常）: {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
