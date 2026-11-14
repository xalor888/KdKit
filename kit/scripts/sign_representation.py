#!/usr/bin/env python3
"""
kuaidui-kit / sign_representation.py — 判定"某条请求的**待签表示**与 URL 表示是否一致"。

背景（`work/SIGNED_SURFACE.md` 追加三/四）：模块的 `sign_observer` 会写 `SIGN params`（**签名前的**参数列表）。
把它与同一条请求的 `SIGN URL` 对比，就能判断：

* **一致** ⇒ 我们基于 URL 的重算签名**有效**（`kd_api.py verify/pull` 可以信）；
* **不一致** ⇒ 该请求属于"值里带分隔符/需转义"的复杂参数类 ⇒ **URL 重算不可靠**（不是算法坏了）。

解析要点（踩过的坑）：待签列表用 `' | '` 连接，**而值内部可能含 `|`**（例如 `params={cuid=…|0, os=…}`）
⇒ 必须按 `' | '`（带空格）切分，**不能**按裸 `|` 切分（否则会切出假键）。

    python3 kit/scripts/sign_representation.py --capture <抓取文件> [--out work/SIGN_REPRESENTATION.md]
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import os
import re
import sys
import urllib.parse
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SIG_EXTRA = {'sign', '_t_', 'kakorrhaphiophobia'}


def parse_signed_pairs(line):
    """返回 {key: value}（按 ' | ' 切分，容忍值里含 '|'）。"""
    body = line.split('SIGN params:', 1)[1].strip()
    out = {}
    for kv in body.split(' | '):
        kv = kv.strip()
        if '=' in kv:
            k, v = kv.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def parse_signed(line):
    """把 `k=v | k=v | …` 解析成键集合（按 ' | ' 切分，容忍值里含 '|'）。"""
    body = line.split('SIGN params:', 1)[1].strip()
    keys = set()
    for kv in body.split(' | '):
        kv = kv.strip()
        if '=' in kv:
            keys.add(kv.split('=', 1)[0].strip())
    return keys


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', required=True)
    ap.add_argument('--out', default=None,
                        help='**不给 `--out` 会覆盖仓库里那份正式文档** —— 冒烟测试一律显式给 `--out /tmp/x.md`。')
    a = ap.parse_args(argv[1:])

    lines = textio.read_lines(a.capture)    # 2026-11-03：--capture 可给 .txt.gz
    # 配对**不能**用"最近一条 params + 下一条 URL"：抓取是多线程写的，两个请求交错时
    # 会把 A 的待签列表配到 B 的 URL 上，于是"键集不同"满天飞（实测 86/86 全红，
    # 而逐对核对其实是完全一致的）。改成按签名块的同一身份 (`_t_`, `kakorrhaphiophobia`)
    # 配对；同身份多条时取"字段名集合最接近"的那条；都对不上才退回最近的前一条。
    params_all, urls_all = [], []
    for l in lines:
        if 'APPSIGN' in l:          # 模块日志被 LogSink 二次收录的副本，会截断，不参与配对
            continue
        if 'SIGN params:' in l:
            params_all.append(l)
        elif 'SIGN URL:' in l:
            urls_all.append(l.split('SIGN URL:', 1)[1].strip())

    def _ident(kv):
        return (kv.get('_t_'), kv.get('kakorrhaphiophobia'))

    parsed_params = [(l, parse_signed_pairs(l)) for l in params_all]
    pairs, used = [], set()
    for url in urls_all:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query, keep_blank_values=True))
        want = (q.get('_t_'), q.get('kakorrhaphiophobia'))
        cands = [(i, kv) for i, (l, kv) in enumerate(parsed_params)
                 if i not in used and _ident(kv) == want]
        if not cands:
            cands = [(i, kv) for i, (l, kv) in enumerate(parsed_params) if i not in used]
        if not cands:
            continue
        sent_names = {k for k in q if k not in SIG_EXTRA}
        i, kv = min(cands, key=lambda t: len((set(t[1]) - SIG_EXTRA) ^ sent_names))
        used.add(i)
        pairs.append((parsed_params[i][0], url))

    simple, complex_ = [], []
    for signed_line, url in pairs:
        kv_signed = parse_signed_pairs(signed_line)
        ks = set(kv_signed) - SIG_EXTRA
        u = urllib.parse.urlparse(url)
        kv_url = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        ku = set(kv_url) - SIG_EXTRA
        ep = u.netloc + u.path
        if ks != ku:
            complex_.append((ep, sorted(ks - ku)[:4], sorted(ku - ks)[:4], '键集不同'))
            continue
        # 键集一致 → 再比**值**（URL 值先解码）—— 表示差异往往藏在值里（如 cuid 少了 |0、params 是 map 形态）
        bad = []
        for k in sorted(ks):
            v_signed = kv_signed.get(k, '')
            v_url = kv_url.get(k, '')
            if k == 'params':
                continue                      # 嵌套值单独看（下面单独标注）
            if v_url != v_signed:
                bad.append(k)
        nested = 'params' in ks and (kv_signed.get('params', '').lstrip().startswith('{')
                                     or kv_signed.get('params', '').lstrip().startswith('['))
        if bad or nested:
            complex_.append((ep, bad[:4] or (['params(嵌套)'] if nested else []), [], '值不同'))
        else:
            simple.append((ep, [], [], ''))

    out = ['# 待签表示 vs URL 表示（自动判定）', '',
           f'* 来源：`{os.path.relpath(a.capture, ROOT)}`（需要模块功能 `sign_observer` 在开）',
           f'* 配对 **{len(pairs)}** 条：**一致 {len(simple)}** ｜ **不一致 {len(complex_)}**', '',
           '**读法**：一致 ⇒ `kd_api.py verify/pull` 的 URL 重算可信；不一致 ⇒ 该请求属"复杂参数"类，URL 重算不可靠', '']
    if complex_:
        out += ['## 不一致的请求（键集不同 或 值表示不同）', '',
                '| endpoint | 差异 | 说明 |', '|---|---|---|']
        for item in complex_:
            ep, detail, _u, why = item[0], item[1], item[2], item[3]
            out.append(f'| `{ep}` | {", ".join(detail) or "—"} | {why} |')
        out += ['', '按 endpoint 计数：' + str(dict(Counter(i[0] for i in complex_))), '']
    else:
        out += ['* 全部一致 ✓（本批抓取里没有"复杂参数"类请求）', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'SIGN_REPRESENTATION.md')
    open(target, 'w').write(text)
    eps = sorted({i[0] for i in complex_})
    print(f'[signrep] -> {target}（配对 {len(pairs)}：一致 {len(simple)} / 不一致 {len(complex_)}'
          + (f'；涉及 {len(eps)} 个 endpoint：{", ".join(eps[:3])}' if eps else '') + '）')
    for item in complex_[:4]:
        print(f'   复杂: {item[0]}  差异={item[1]}  原因={item[3]}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
