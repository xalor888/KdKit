#!/usr/bin/env python3
"""
kuaidui-kit / pageapi.py — 直连"页面自有接口"（`api.kuaiduizuoye.com`）的极简客户端。

2026-10-12 发现：H5 页面自己会调用 `api.kuaiduizuoye.com/*`（与宿主签名通道**不同 host、不同鉴权**）。
实测该 host **不需要签名/token**，只要页面上下文的几个头（`Origin` / `Referer` / `cuid` / `appid` / `channel`），
而且**校验错误会点名缺失字段**（Go 风格：`Key: 'XxxReq.Field' required`）—— 于是可以**迭代发现请求模型**。

    python3 kit/python/pageapi.py --path /aiwriting/ai/composition/titlepage            # 空 body（看缺什么）
    python3 kit/python/pageapi.py --path /aiwriting/ai/composition/titlepage --json '{"GradeId":7}'
    python3 kit/python/pageapi.py --path /path --discover                                # 自动迭代补必填字段

`--cuid` 不填则从设备的抓取里取（`cuid=` 出现在签名参数或 WEBREQ 头里）。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import captures
import argparse
import net
import json
import re
import ssl
import sys
import urllib.error
import urllib.request

HOST = 'api.kuaiduizuoye.com'


def base_headers(cuid):
    return {
        'Origin': 'https://www.kuaiduizuoye.com',
        'Referer': 'https://www.kuaiduizuoye.com/',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'cuid': cuid,
        'appid': 'scancode',
        'channel': 'yingyongbao',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 16; sdk_gphone64_arm64) AppleWebKit/537.36',
    }


def call(path, doc, cuid):
    url = f'https://{HOST}{path}'
    req = urllib.request.Request(url, data=json.dumps(doc).encode(), headers=base_headers(cuid))
    try:
        with urllib.request.urlopen(req, timeout=25, context=net.ssl_context()) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return 'ERR', f'{type(e).__name__}: {e}'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', required=True)
    ap.add_argument('--json', default='{}')
    ap.add_argument('--cuid', default=None)
    ap.add_argument('--discover', action='store_true', help='按校验错误自动补必填字段（最多 8 轮）')
    a = ap.parse_args(argv[1:])

    cuid = a.cuid
    if not cuid:
        # 2026-11-03：与 composition_flow 同一个来源（`captures`）。
        # 旧实现只 glob `capture*.txt` ⇒ 被 pack_slim 压成 .gz 的抓取静默消失。
        for c in captures.iter_captures()[:5]:
            m = captures.find_cuid(c)
            if m:
                cuid = m.group(1)
                break
    if not cuid:
        print('[pageapi] 找不到 cuid —— 用 --cuid 显式给')
        return 2
    print(f'[pageapi] cuid={cuid[:20]}…')

    doc = json.loads(a.json)
    for i in range(8 if a.discover else 1):
        st, body = call(a.path, doc, cuid)
        print(f'[{i}] {st} {body[:300]}')
        if not a.discover or "Key: '" not in body:
            break
        frag = body.split("Key: '", 1)[1].split("'", 1)[0]
        field = frag.split('.')[-1]
        doc[field] = 7 if field.lower().endswith('id') else '测试'
        print(f'    -> 补上 {field}={doc[field]!r}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
