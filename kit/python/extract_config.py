#!/usr/bin/env python3
"""
kuaidui-kit / extract_config.py — 把几个"配置类"接口的响应变成可读结构。

离线客户端能拉接口只是前半程；后半程是**看得懂里面是什么**。这个脚本挑几条游客可达的配置接口，
把它们解出来的 JSON 按"顶层字段 → 关键子树的两层"展平，落到一份 markdown 里。

    python3 kit/python/extract_config.py --adb emulator-5558 --capture cap.txt \
        --sign-a a.txt --sign-b b.txt --out work/CONFIG_DUMP.md
"""
import argparse
import net
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# 同目录导入 `genstamp`（输入指纹）：脚本可能从任意 CWD 被调用。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capture_schema
import textio
import genstamp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kd_api  # noqa: E402

TARGETS = [
    ('/init/init/fesearchtree', ['segList']),
    ('/kdapi/conf/searchtree', ['segList']),
    ('/kdapi/conf/appconfig', ['homeBigBtn', 'homeJgBtn', 'tabList', 'homeConfig']),
    ('/kdapi/conf/appbannersv3', ['list']),
    ('/kdapi/conf/mycard', ['vipPlanId', 'vipInfo', 'cardContent']),
    ('/kdapi/conf/abtest', ['ab']),
]


def render(name, node, depth=0, max_depth=2, max_items=6, out=None):
    pad = '  ' * depth
    if isinstance(node, dict):
        for i, (k, v) in enumerate(node.items()):
            if i >= max_items and depth >= max_depth:
                out.append(f'{pad}- …（还有 {len(node) - max_items} 个键）')
                break
            if depth < max_depth:
                out.append(f'{pad}- **{k}**: {type(v).__name__}')
                render(k, v, depth + 1, max_depth, max_items, out)
            elif i < max_items:
                out.append(f'{pad}- {k} = {str(v)[:60]}')
    elif isinstance(node, list):
        out.append(f'{pad}- list[{len(node)}]')
        if depth < max_depth:
            for item in node[:max_items]:
                render(name, item, depth + 1, max_depth, max_items, out)
            if len(node) > max_items:
                out.append(f'{pad}- …（还有 {len(node) - max_items} 项）')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--capture', required=True)
    ap.add_argument('--sign-a', required=True)
    ap.add_argument('--sign-b', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--path', action='append', default=[])
    a = ap.parse_args(argv[1:])

    A, X = kd_api.sign_material(a.adb, a.sign_a, a.sign_b)
    # 2026-11-03：走 `textio.read_lines` —— `--capture` 可以给 `.txt.gz`
    # （`pack_slim` 把旧包压过）。原来直接 `open()` 时，传 `.gz` 会
    # 读到 gzip 的二进制 ⇒ **每一行都解析失败** ⇒ 报告显示“这个包里
    # 没有这类行”，而真相是“没读到”。
    lines = textio.read_lines(a.capture)
    urls = capture_schema.sign_urls(lines)
    key = ''
    import re
    m = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', '\n'.join(lines))
    if m:
        key = m.group(1)

    targets = [(p, dict(t for t in TARGETS).get(p, [])) for p in a.path] if a.path else TARGETS
    md = ['# 配置类接口内容（离线拉取 + 展平）', '',
          f'* 设备 `{a.adb}`；抓取 `{a.capture}`',
          # 输入指纹：这份文档的输入是"一份抓取 + 一组路径"。设备相关、离线跑不了生成器，
          # 所以靠指纹回答"它是不是还对应现在的输入"（`kit/python/genstamp.py`）。
          *genstamp.header_line([os.path.relpath(a.capture, ROOT)], [a.capture]).split('\n'),
          '* 复现：`python3 kit/python/extract_config.py --adb ' + str(a.adb)
          + ' --capture ' + os.path.relpath(a.capture, ROOT)
          + ' --sign-a <a.txt> --sign-b <b.txt> --out work/CONFIG_DUMP.md`',
          '']
    for path, keys in targets:
        cand = [u for u in urls if urllib.parse.urlparse(u).path == path]
        if not cand:
            md += [f'## `{path}`', '', '_抓取里没有这条路径（先逛一圈再跑）_', '']
            continue
        pu = urllib.parse.urlparse(cand[-1])
        q = dict(urllib.parse.parse_qsl(pu.query, keep_blank_values=True))
        kak = q.get('kakorrhaphiophobia', '0')
        now = int(time.time())
        signed = [f'{k}={v}' for k, v in urllib.parse.parse_qsl(pu.query, keep_blank_values=True)
                  if k not in ('sign', '_t_', 'kakorrhaphiophobia')] + [f'_t_={now}',
                                                                       f'kakorrhaphiophobia={kak}']
        sign, _p = kd_api.sign_for(A, X, signed)
        body = '&'.join(urllib.parse.quote(f, safe='=') for f in signed
                        if not f.startswith(('_t_', 'kakorrhaphiophobia')))
        ctx = net.ssl_context()
        data = None
        for use_post in (True, False):
            try:
                if use_post:
                    req = urllib.request.Request(f'https://{pu.netloc}{path}', data=(body + f'&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}').encode(),
                                                 headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity',
                                                          'Content-Type': 'application/x-www-form-urlencoded'})
                else:
                    req = urllib.request.Request(f'https://{pu.netloc}{path}?&{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}',
                                                 headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity'})
                with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                    doc = json.loads(r.read().decode('utf-8', 'replace'))
                data = doc
                break
            except Exception:
                continue
        md += [f'## `{path}`', '']
        if not data:
            md.append('_请求失败_')
            md.append('')
            continue
        d = data.get('data')
        if isinstance(d, dict) and 'encodeData' in d and d['encodeData'] and key:
            decode_note = ''
            try:
                from kd_crypto import rc4
                import base64
                d = json.loads(rc4(key.encode(), base64.b64decode(d['encodeData'])).decode('utf-8', 'replace'))
            except Exception as e:                        # noqa: BLE001
                # **不能静默**（2026-11-06，代码审查 P1）。
                #
                # 旧实现 `except Exception: pass` 的后果：解密失败时，
                # 报告里这一段只剩 `errNo`，**看不出"本来应该有内容"** ——
                # 读报告的人会以为"这个接口本来就只返回 errNo"。
                # 而真相是"密钥不对 / 载荷坏了"。
                decode_note = (f' _(encodeData 解不开：{type(e).__name__}: '
                               f'{str(e)[:60]} ⇒ 这一段只显示了 errNo，'
                               f'本来可能有更多字段)_')
                d = None
        md.append(f'* `errNo={data.get("errNo")}`；顶层字段：' + ', '.join(f'`{k}`' for k in (d or {}) if isinstance(d, dict)) + decode_note)
        md.append('')
        if isinstance(d, dict):
            for want in keys or list(d)[:3]:
                if want in d:
                    md.append(f'### `{path}` → `{want}`')
                    md.append('')
                    out = []
                    render(want, d[want], 0, 2, 6, out)
                    md += out
                    md.append('')
    text = '\n'.join(md) + '\n'
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[config] -> {a.out}')
    print('\n'.join(md[:10]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
