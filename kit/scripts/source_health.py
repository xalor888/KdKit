#!/usr/bin/env python3
"""
kuaidui-kit / source_health.py — 导出**来源健康**核对（2026-10-12）。

由来：本会话发现**一条来源路径退役了** ✗（`/kdapi/conf/searchtree` ✓ → 只回 errNo:6 ✓），
而**所有搜索树导出都来自它** ✗ ⇒ 于是给 README 标了"**权威源**" ✓。
本脚本让那条标注**不会过期** ✓：拿 README 里提到的每个来源端点 ✓，
与**最新一份 dump** 对一遍 ✓ ⇒ **声称是权威源却已死的** ⇒ **报错** ✗。

    python3 kit/scripts/source_health.py [--dump work/packs/rNNN/responses.json]
退出码：0 = 都活着 ✓；1 = 有声称权威却已死的 ✗。
"""
import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README = os.path.join(ROOT, 'work', 'exports', 'README.md')
# 只认"真正的 App 端点"（排除 SDK 内部单字母路径 ✓）
PAT = re.compile(r'`(/(?:kdapi|kdchat|kdcore|codesearch|pigai|pluto|plutov2|hegui|abengine|init|activity|user|exam|submit|news|map|mistake|record|conf|userident)/[\w/\-]+)`')


def latest_dump():
    cands = sorted(glob.glob(os.path.join(ROOT, 'work', 'packs', '*', 'responses.json')),
                   key=os.path.getmtime)
    return cands[-1] if cands else None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', default=None)
    a = ap.parse_args(argv[1:])
    dump = a.dump or latest_dump()
    if not dump or not os.path.exists(dump):
        print('[health] 没有 dump，跳过 ✓')
        return 0
    live = set(json.load(open(dump, encoding='utf-8')))
    txt = open(README, encoding='utf-8').read()
    srcs = sorted(set(PAT.findall(txt)))
    dead = [s for s in srcs if s not in live]
    if dead:
        print(f'[health] **{len(dead)} 个来源不在最新 dump 里** ✗（共 {len(srcs)} 个）：')
        for s in dead:
            print(f'   {s}')
        print('   ⇒ 若其中有被标为"权威源"的，**必须改标** ✗（本会话踩过这个坑 ✓）')
        return 1
    print(f'[health] 全部 {len(srcs)} 个来源都在最新 dump 里 ✓（{os.path.basename(os.path.dirname(dump))}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
