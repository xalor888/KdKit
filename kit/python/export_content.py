#!/usr/bin/env python3
"""
kuaidui-kit / export_content.py — 把离线客户端能拿到的内容导成结构化文件。

这是"离线客户端到底能干什么"的**结果展示**：不是再证明一次能拉接口，而是把内容变成
可以用别的东西处理的数据（CSV / JSON）。

    python3 kit/python/export_content.py --adb emulator-5558 [--outdir work/exports]

产出：`books.csv`（最近书目：书名明文 + bookId）、`questions.csv`（推荐问题）、
`search_tree.json`（学段/年级结构）。
"""
import capture_schema
import textio
import argparse
import net
import base64
import csv
import glob
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import captures
from device import PKG as PKG_CONST
import kd_api  # noqa: E402

# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST


def newest_capture():
    # 2026-11-03：与另外三处同一个来源（`captures`）。
    # `prefer_plain=True` 保留原意：只要未压缩的那份
    # （下游要把抓取原文交给其它工具）。
    return captures.newest_capture(prefer_plain=True)


def token_files():
    for ca in sorted(glob.glob(os.path.join(ROOT, 'work', 'packs', '*', '*signA.txt')),
                     key=os.path.getmtime, reverse=True):
        cb = ca.replace('signA', 'signB')
        if os.path.exists(cb) and os.path.getsize(ca) > 100:
            return ca, cb
    return None, None


def fetch(netloc, path, params, A, X):
    kak = params.get('kakorrhaphiophobia', '0')
    now = int(time.time())
    signed = [f'{k}={v}' for k, v in params.items() if k not in ('sign', '_t_', 'kakorrhaphiophobia')]
    signed += [f'_t_={now}', f'kakorrhaphiophobia={kak}']
    sign, _p = kd_api.sign_for(A, X, signed)
    body = '&'.join(urllib.parse.quote(f, safe='=') for f in signed if not f.startswith(('_t_', 'kakorrhaphiophobia')))
    body += f'&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}'
    req = urllib.request.Request(f'https://{netloc}{path}', data=body.encode(),
        headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity',
                 'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=20, context=net.ssl_context()) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--capture', default=None)
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'work', 'exports'))
    a = ap.parse_args(argv[1:])

    cap = a.capture or newest_capture()
    # **抓取与令牌都要先确认在**（2026-11-03 修，代码审查 P1）。
    # 旧实现 `open(cap)` 而 `newest_capture()` 找不到时返回 None
    # ⇒ `TypeError: … not NoneType`；令牌那一半同理（`token_files()` 返回 `(None, None)`）。
    # 两个错因都指向“类型”，而真正的问题是“你没有先跑证据包”。
    if not cap:
        raise RuntimeError('找不到任何抓取（work/packs/*/capture*.txt）—— '
                           '先跑一次 evidence_pack，或用 --capture 指定')
    if not os.path.exists(cap):
        raise RuntimeError(f'抓取不存在：{cap}')
    txt = textio.read_text(cap, encoding='utf-8', errors='replace')
    A_f, B_f = token_files()
    if not A_f or not B_f:
        raise RuntimeError('找不到 signA/signB 令牌（work/packs/*/*signA.txt）—— '
                           '先跑一次 evidence_pack / server_shape 把它们取到本地')
    A, X = kd_api.sign_material(a.adb, A_f, B_f)
    m = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', txt)
    key = m.group(1).encode() if m else b''
    # 2026-11-04：走 `capture_schema.sign_urls`（同一个契约，不再自己 split）。
    urls = capture_schema.sign_urls(txt.splitlines())

    def params_of(path):
        cand = [u for u in urls if urllib.parse.urlparse(u).path == path]
        if not cand:
            return None, None
        pu = urllib.parse.urlparse(cand[-1])
        return pu.netloc, dict(urllib.parse.parse_qsl(pu.query, keep_blank_values=True))

    def dec(v):
        if key and isinstance(v, str) and re.match(r'^[A-Za-z0-9+/=_-]{16,}$', v):
            try:
                from kd_crypto import rc4
                p = rc4(key, base64.b64decode(v + '=' * (-len(v) % 4))).decode('utf-8')
                if p and sum(ch.isprintable() for ch in p) / len(p) >= 0.9:
                    return p
            except Exception:
                pass
        return v

    os.makedirs(a.outdir, exist_ok=True)
    stats = []

    # 书目
    host, p = params_of('/kdcore/submit/homebookv2')
    if host:
        doc = fetch(host, '/kdcore/submit/homebookv2', p, A, X)
        books = ((doc.get('data') or {}).get('homeRecentList') or [])
        with open(os.path.join(a.outdir, 'books.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['bookId', 'name'])
            for b in books:
                w.writerow([b.get('bookId', ''), dec(b.get('name', ''))])
        stats.append(('books.csv', len(books)))

    # 推荐问题
    host, p = params_of('/kdchat/api/chatrecommendconf')
    if host:
        doc = fetch(host, '/kdchat/api/chatrecommendconf', p, A, X)
        qs = ((doc.get('data') or {}).get('list') or [])
        with open(os.path.join(a.outdir, 'questions.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['question'])
            for q in qs:
                w.writerow([dec(q.get('question', '')) if isinstance(q, dict) else str(q)])
        stats.append(('questions.csv', len(qs)))

    # 学段/年级结构
    host, p = params_of('/init/init/fesearchtree')
    if host:
        doc = fetch(host, '/init/init/fesearchtree', p, A, X)
        segs = ((doc.get('data') or {}).get('segList') or [])
        tree = [{'title': s.get('title'), 'grades': [g.get('title') if isinstance(g, dict) else g
                                                     for g in (s.get('gradeList') or [])]}
                for s in segs if isinstance(s, dict)]
        json.dump(tree, open(os.path.join(a.outdir, 'search_tree.json'), 'w'),
                  ensure_ascii=False, indent=1)
        stats.append(('search_tree.json', len(tree)))

    print(f'[export] -> {a.outdir}')
    for name, n in stats:
        print(f'[export]   {name}: {n} 行/项')
    if not stats:
        print('[export] 没导到东西 —— 抓取里缺这些路径，先逛一圈')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
