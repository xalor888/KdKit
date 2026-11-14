#!/usr/bin/env python3
"""
kuaidui-kit / extract_samples.py — 游客态到底能拿到什么**内容**（不只是配置结构）。

`extract_config.py` 回答"结构长什么样"；这个回答"**里面装的是什么**" —— 对每条接口取前 N 条记录，
挑出最有信息量的字段（标题/名称/URL/ID/时间）排成表。用于判断接口的数据价值，也作为内容快照基线。

    python3 kit/python/extract_samples.py --adb emulator-5558 --capture cap.txt \
        --sign-a a.txt --sign-b b.txt --out work/CONTENT_SAMPLES.md [--per 3] [--path ...]
"""
import argparse
import net
import base64
import json
import os
import re
import ssl
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textio
import capture_schema
import genstamp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kd_api  # noqa: E402

CANDIDATE_FIELDS = ('title', 'name', 'question', 'content', 'text', 'desc', 'author', 'bookName',
                    'url', 'imgUrl', 'icon', 'id', 'id2', 'bookId', 'markId', 'type', 'sceneName',
                    'time', 'updateTime', 'count', 'num')


B64ISH = re.compile(r'^[A-Za-z0-9+/=_-]{16,}$')


def maybe_decrypt(v, key):
    """字段可能是 yl.f.n 单值加密（见 TRIAGE §3.2.1）：基64 外形 + 解出来是可读文本 → 用明文。"""
    if not key or not isinstance(v, str) or not B64ISH.match(v):
        return v
    try:
        from kd_crypto import rc4
        pt = rc4(key, base64.b64decode(v + '=' * (-len(v) % 4))).decode('utf-8')
    except Exception:
        return v
    if not pt:
        return v
    printable = sum(1 for ch in pt if ch.isprintable() or ch in '\n\t')
    if printable / len(pt) < 0.9:
        return v              # 解出来是乱码 → 它本来就不是密文
    return pt + '（明文）'


def pick(rec, limit=5, key=None):
    if not isinstance(rec, dict):
        return str(rec)[:70]
    out = []
    for k in CANDIDATE_FIELDS:
        if k in rec and rec[k] not in ('', None, [], {}):
            v = re.sub(r'\s+', ' ', str(maybe_decrypt(rec[k], key)))
            out.append(f'{k}={v[:44]}')
        if len(out) >= limit:
            break
    if not out:
        out = [f'{k}={str(v)[:30]}' for k, v in list(rec.items())[:4]]
    return '; '.join(out)


def lists_in(d, depth=1, path='$'):
    """找出响应里"像列表内容"的字段（浅层优先）。"""
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                out.append((f'{path}.{k}', v))
            elif isinstance(v, dict) and depth < 3:
                out += lists_in(v, depth + 1, f'{path}.{k}')
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--capture', required=True)
    ap.add_argument('--sign-a', required=True)
    ap.add_argument('--sign-b', required=True)
    ap.add_argument('--per', type=int, default=3)
    ap.add_argument('--key', default=None, help='显式给负载密钥（不给则从抓取里找 RC4KEY 行）')
    ap.add_argument('--path', action='append', default=[])
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    # 2026-10-13：空抓取直接跳过 —— 否则后面会做一堆无意义的设备访问（并可能挂住 ✗）
    try:
        _sz = os.path.getsize(a.capture)
    except OSError:
        _sz = 0
    if _sz < 4096:
        print(f'[samples] 抓取只有 {_sz} 字节 ⇒ 跳过（空抓取没有可提取的样本）')
        return 0
    A, X = kd_api.sign_material(a.adb, a.sign_a, a.sign_b)
    # 2026-11-03：走 `textio.read_lines` —— `--capture` 可以给 `.txt.gz`
    # （`pack_slim` 把旧包压过）。原来直接 `open()` 时，传 `.gz` 会
    # 读到 gzip 的二进制 ⇒ **每一行都解析失败** ⇒ 报告显示“这个包里
    # 没有这类行”，而真相是“没读到”。
    lines = textio.read_lines(a.capture)
    # 2026-11-04：走 `capture_schema.sign_urls` —— 原来这里自己 split，
    # 与 `RULES` 的 `SIGN_URL` 契约不是同一个（行尾有别的词就一起当 URL）。
    urls = capture_schema.sign_urls(lines)
    m = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', '\n'.join(lines))
    key = (a.key or (m.group(1) if m else '')).encode() if (a.key or m) else b''

    paths = a.path or sorted({urllib.parse.urlparse(u).path for u in urls})
    md = ['# 游客态能拿到什么内容（每条取前 %d 条）' % a.per, '',
          f'* 设备 `{a.adb}`；抓取 `{os.path.relpath(a.capture, ROOT)}`',
          # 输入指纹：设备相关、离线跑不了生成器，靠指纹回答"是否还对应现在的输入"。
          *genstamp.header_line([os.path.relpath(a.capture, ROOT)], [a.capture]).split('\n'),
          '* 复现：`python3 kit/python/extract_samples.py --adb ' + str(a.adb)
          + ' --capture ' + os.path.relpath(a.capture, ROOT)
          + ' --sign-a <a.txt> --sign-b <b.txt> --out work/CONTENT_SAMPLES.md`',
          '']
    for path in paths:
        cand = [u for u in urls if urllib.parse.urlparse(u).path == path]
        if not cand:
            continue
        pu = urllib.parse.urlparse(cand[-1])
        q = dict(urllib.parse.parse_qsl(pu.query, keep_blank_values=True))
        kak = q.get('kakorrhaphiophobia', '0'); now = int(time.time())
        signed = [f'{k}={v}' for k, v in urllib.parse.parse_qsl(pu.query, keep_blank_values=True)
                  if k not in ('sign', '_t_', 'kakorrhaphiophobia')] + [f'_t_={now}', f'kakorrhaphiophobia={kak}']
        sign, _p = kd_api.sign_for(A, X, signed)
        body = '&'.join(urllib.parse.quote(f, safe='=') for f in signed if not f.startswith(('_t_', 'kakorrhaphiophobia')))
        doc = None
        for post in (True, False):
            try:
                if post:
                    req = urllib.request.Request(f'https://{pu.netloc}{path}',
                        data=(body + f'&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}').encode(),
                        headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity',
                                 'Content-Type': 'application/x-www-form-urlencoded'})
                else:
                    req = urllib.request.Request(f'https://{pu.netloc}{path}?&{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}',
                        headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity'})
                with urllib.request.urlopen(req, timeout=20, context=net.ssl_context()) as r:
                    doc = json.loads(r.read().decode('utf-8', 'replace'))
                break
            except Exception:
                continue
        if not doc:
            continue
        d = doc.get('data')
        if isinstance(d, dict) and d.get('encodeData') and key:
            try:
                from kd_crypto import rc4
                d = json.loads(rc4(key.encode(), base64.b64decode(d['encodeData'])).decode('utf-8', 'replace'))
            except Exception:
                pass
        found = lists_in(d)
        if not found:
            continue
        md += [f'## `{path}`', '']
        for where, lst in found[:2]:
            md.append(f'**{where}**（{len(lst)} 条，示意前 {min(a.per, len(lst))} 条）')
            md.append('')
            for rec in lst[:a.per]:
                md.append(f'* {pick(rec, key=key)}')
            md.append('')
    text = '\n'.join(md) + '\n'
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[samples] -> {a.out}')
    print('\n'.join(md[:14]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
