#!/usr/bin/env python3
"""
kuaidui-kit / probe_paths.py — ask the server about endpoints the app never called.

`kd_api.py request` can sign a request for any path; this feeds it a *candidate list taken from the
APK's own string table* (not blind guessing), so we get a live answer for "does this endpoint
exist, and what does it say?".

    python3 kit/python/probe_paths.py --apk work/apktool_out --capture cap.txt \\
        --adb emulator-5558 --sign-a a.txt --sign-b b.txt --limit 25 --out work/probe.md

Classification per path:
  * `HTTP 200 / errNo 0`      — endpoint exists and answers without extra context
  * `HTTP 200 / errNo != 0`   — endpoint exists, business layer wants something we did not send
  * `HTTP 404`                — no such route on this host
  * `other`                   — anything else (do not over-interpret)

**Measured limitation (2026-10-11)**: the server binds the signature to the parameter set it
expects for that endpoint. Hosts whose requests carry a *closed* common model (`pluto.zuoyebang.com`,
`adx.zuoyebang.com`) accept constructed requests, so probing works there. The app's main API host
(`www.kuaiduizuoye.com`) answers `errNo 6 "antispam sign error"` for any parameter set that did not
come from that exact endpoint — probing it needs the endpoint's own captured params (`kd_api.py pull`).

Only paths whose first segment looks like a service root (`pluto`, `kdapi`, `kdcore`, `userident`,
`codesearch`, `init`, `napi`, `activity`, `hegui`, `pigai`, `kdchat`, `abengine`, `plutov2`) are
probed, and requests are spaced by `--delay` seconds.
"""
import argparse
import net
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import textio
import capture_schema
import kd_api  # noqa: E402  (sign_for / sign_material live there)

ROOTS = ('pluto', 'plutov2', 'kdapi', 'kdcore', 'kdchat', 'userident', 'codesearch', 'init',
         'napi', 'activity', 'hegui', 'pigai', 'abengine', 'adxserver', 'kdbook')

# 首段 -> 域名（来自实盘 capture 里各 host 上出现过的路径；未知的首段不猜，直接用默认 host）
_KD = 'www.kuaiduizuoye.com'
HOST_MAP = {
    'pluto': 'pluto.zuoyebang.com',
    'plutov2': 'pluto.zuoyebang.com',
    'abengine': 'abtest.zuoyebang.com',
    'adxserver': 'adx.zuoyebang.com',
    # 下面这些首段在实盘 capture 里都出现在 www.kuaiduizuoye.com 上
    'kdapi': _KD, 'kdcore': _KD, 'kdchat': _KD, 'userident': _KD, 'codesearch': _KD,
    'init': _KD, 'activity': _KD, 'hegui': _KD, 'pigai': _KD, 'kdbook': _KD,
}
SKIP = re.compile(r'\.(png|jpe?g|gif|js|css|html?|json|ttf|otf|so|apk|zip|svg|mp4|webp)$', re.I)


def candidates(apk_dir):
    paths = set()
    rx = re.compile(r'"(/[A-Za-z0-9_\-/]{4,60})"')
    for root, _dirs, files in os.walk(apk_dir):
        for fn in files:
            if not fn.endswith('.smali'):
                continue
            try:
                with open(os.path.join(root, fn), encoding='utf-8',
                          errors='replace') as _fh:
                    text = _fh.read()
            except OSError:
                continue
            for m in rx.finditer(text):
                p = m.group(1)
                seg = p.lstrip('/').split('/')[0]
                if seg in ROOTS and not SKIP.search(p) and p.count('/') >= 2 and '{' not in p:
                    paths.add(p)
    return sorted(paths)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk', required=True, help='apktool output tree to mine path strings from')
    ap.add_argument('--capture', required=True, help='capture used for the common parameter set')
    ap.add_argument('--adb', required=True)
    ap.add_argument('--sign-a', required=True)
    ap.add_argument('--sign-b', required=True)
    ap.add_argument('--limit', type=int, default=25)
    ap.add_argument('--delay', type=float, default=0.6)
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    cand = candidates(a.apk)
    print(f'[probe] {len(cand)} candidate path(s) in the APK; probing the first {min(a.limit, len(cand))}')

    const_a, x = kd_api.sign_material(a.adb, a.sign_a, a.sign_b)
    # 2026-11-03：走 `textio.read_lines` —— `--capture` 可以给 `.txt.gz`
    # （`pack_slim` 把旧包压过）。原来直接 `open()` 时，传 `.gz` 会
    # 读到 gzip 的二进制 ⇒ **每一行都解析失败** ⇒ 报告显示“这个包里
    # 没有这类行”，而真相是“没读到”。
    lines = textio.read_lines(a.capture)
    # 2026-11-04：走 `capture_schema.sign_urls`（同一个契约，不再自己 split）。
    urls = capture_schema.sign_urls(lines)

    def split_or_none(u):
        try:
            return urllib.parse.urlparse(u)
        except ValueError:
            return None

    # 公共参数**按 host 各算一份**：不同域名的请求带的公共字段不一样，
    # 拿 A 域名的集合去签 B 域名会被服务端判成 "antispam sign error"（errNo 6，实测踩过）。
    per_host = {}
    for u in urls:
        pu = split_or_none(u)
        if pu is None:
            continue
        per_host.setdefault(pu.netloc, []).append(urllib.parse.parse_qsl(pu.query, keep_blank_values=True))

    def template_for(h):
        parsed = per_host.get(h)
        if not parsed:
            return {}
        c = {}
        for q in parsed:
            for k, _v in q:
                c[k] = c.get(k, 0) + 1
        th = max(1, int(len(parsed) * 0.8))
        names = {k for k, n in c.items() if n >= th and k != 'sign'}
        return {k: v for k, v in parsed[-1] if k in names}

    host = next(iter(per_host), None)
    print('[probe] captured hosts: ' + ', '.join(f'{h}({len(v)}req,{len(template_for(h))}params)'
                                                 for h, v in per_host.items()))

    rows = []
    for path in cand[:a.limit]:
        root_host = HOST_MAP.get(path.lstrip('/').split('/')[0], host)
        template = template_for(root_host) or template_for(host)
        now = int(time.time())
        # 防重放的对时字段不能写 0：服务端对它有校验（写 0 会让 www.kuaiduizuoye.com 的接口
        # 一律返回 errNo 6 "antispam sign error"，实测踩过）。用同一 host 捕获里的值。
        kak = template.get('kakorrhaphiophobia', '0')
        signed = [f'{k}={v}' for k, v in template.items() if k != 'kakorrhaphiophobia']
        signed += [f'_t_={now}', f'kakorrhaphiophobia={kak}']
        sign, _p = kd_api.sign_for(const_a, x, signed)
        # 签名覆盖的参数里包含 `_t_`/`kakorrhaphiophobia`，但它们要**跟在 sign 之后**放到请求里
        # （和 App 的组装一致）；漏掉它们服务端会判 "antispam sign error"（errNo 6，实测踩过两次）。
        # **两个都要排除**（2026-11-03 修，代码审查 P1）。
        #
        # 旧实现只排 `_t_`，于是 `kakorrhaphiophobia` 在 body 里出现**两次**：
        # 一次来自 `signed`（上面刚 `+=` 进去的），一次来自结尾那句。
        # 其余 5 个调用点（`kd_api.py` ×3、`export_content.py`、
        # `extract_config.py`、`extract_samples.py`）排的都是**二者**。
        #
        # 症状与"漏掉它们"完全一样：服务端判 `antispam sign error`（errNo 6）——
        # 而上面那行注释写着"实测踩过两次"，说的是漏掉；重复是同一个坑的另一半。
        body = '&'.join(urllib.parse.quote(f, safe='=')
                        for f in signed
                        if not f.startswith(('_t_', 'kakorrhaphiophobia')))
        body += f'&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}'
        req = urllib.request.Request(f'https://{root_host}{path}', data=body.encode(),
                                     headers={'User-Agent': 'okhttp/4.9.0',
                                              'Accept-Encoding': 'identity',
                                              'Content-Type': 'application/x-www-form-urlencoded'})
        import ssl
        code, payload = 0, ''
        try:
            with urllib.request.urlopen(req, timeout=15, context=net.ssl_context()) as r:
                code, payload = r.status, r.read(600).decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            code, payload = e.code, e.read(200).decode('utf-8', 'replace')
        except Exception as e:
            payload = str(e)[:80]
        errno = re.search(r'"errNo"\s*:\s*(-?\d+)', payload)
        errstr = re.search(r'"err(?:str|Msg)"\s*:\s*"([^"]{0,40})', payload)
        verdict = ('exists/ok' if code == 200 and errno and errno.group(1) == '0'
                   else 'exists/business' if code == 200 and errno
                   else 'no-route' if code == 404 else 'other')
        rows.append((path, code, errno.group(1) if errno else '', errstr.group(1) if errstr else '',
                     verdict))
        rows[-1] = rows[-1] + (root_host,)
        print(f'  {path:44s} {root_host:24s} {code}  errNo={rows[-1][2] or "-":5s} {rows[-1][4]}')
        time.sleep(a.delay)

    if a.out:
        with open(a.out, 'w') as f:
            f.write(f'# 接口探测（候选来自 APK 字符串表，共 {len(cand)} 个，探测 {len(rows)} 个）\n\n')
            f.write(f'* 公共参数按 host 分别统计（从 capture）\n\n')
            f.write('| path | host | HTTP | errNo | errstr | 判定 |\n|---|---|---|---|---|---|\n')
            for p, c, e, s, v, h in rows:
                f.write(f'| `{p}` | `{h}` | {c} | {e or "-"} | {s or "-"} | {v} |\n')
        print(f'[probe] -> {a.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
