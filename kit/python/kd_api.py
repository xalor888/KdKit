#!/usr/bin/env python3
"""
kuaidui-kit / kd_api.py — speak 快对's HTTP protocol outside the app.

Everything the app needs to sign a request is now reconstructed offline:

    param = base64_NO_WRAP( TextUtils.join("", sorted(params)) )
    sign  = md5( A + "[" + md5hex(X) + "]@" + param )
    url   = <host><path> + "?" + <original params in order> + "&sign=<sign>&_t_=<sec>&kakorrhaphiophobia=<ms>"

`A` and `X` come from the two stored tokens (see `decode_token_native.py`, which uses the native
oracle in `kit/harness/native/`). This script then does two things:

  verify  — for every `SIGN params` / `SIGN URL` pair in a KdKit capture, rebuild the signature
            from the param list alone and compare with the URL that the app actually sent;
  call    — take one of those URLs (or build one), fire it at the real host and show the answer,
            which proves the signed request is accepted by the server.

    python3 kd_api.py verify --adb emulator-5558 --sign-a a.txt --sign-b b.txt --capture cap.txt
    python3 kd_api.py call   --adb emulator-5558 --sign-a a.txt --sign-b b.txt \
        --url "https://pluto.zuoyebang.com/pluto/app/hotfix?&..."        # a captured URL
"""
import os
import net
import capture_schema
import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request


def adb(serial, *args, timeout=120):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout)


def decode_token(serial, token, key):
    out = adb(serial, f"/data/local/tmp/decode_token /data/local/tmp/libbaseutil.so '{token}' '{key}'")
    m = re.search(r'blob .*?\n  hex: ([0-9a-f]+)', out.stdout, re.S)
    if not m:
        raise RuntimeError(f'oracle failed (key={key!r}):\n{out.stdout}{out.stderr}')
    return bytes.fromhex(m.group(1))


# 错误码 → 该怎么做（来自 REPORT.md §2.6 的实测表，2026-10-13）
ERRNO_HINTS = {
    0: '成功',
    6: '参数集不对的通用拒绝码 —— 用那条请求**自己的参数**即可（verify 已证签名与 App 一致 ⇒ 不是签名问题；见 REPORT §2.5 / 规则 15）。'
       '若它**本来就是**游客从不调用的路径 ⇒ 按 REPORT §2.8 的**三层**查：开关层（DISABLED_FEATURES.md）→ 配置层 → **调用身份层**（COVERAGE.md）',
    7: '参数不足/不合法（与 6 同类：属通用拒绝，不是签名问题）',
    4000: '读它点名的字段 —— 校验错误会把请求模型报出来',
    5301: '业务层失败（校验已过，差业务前置条件）',
    5302: '业务层失败（同上）',
    906003: '服务端状态/时序绑定 —— 这类接口不可独立复现',
    10000: '业务数据条件（不是错误，是"没有数据"）',
}


ENUM_HINT = ('    ↳ 该参数可能有**枚举取值** ⇒ 见 `work/PARAM_ENUMS.md` ✓'
             '（16 组：gradeId/versionId/typeId/areaId/identityIdV2/… ✓）')


def enum_hint_for(body_text):
    """2026-10-12：`errNo:4000` 会把**缺的字段名**报出来 ✓；
    本函数在那种响应后追加一句"这个字段可能是有枚举的" ✓ ——
    把 §2.6 的"读它点名的字段"与 `work/PARAM_ENUMS.md` 接起来 ✓。"""
    t = body_text if isinstance(body_text, str) else str(body_text)
    if 'param invalid' in t or '"errNo":4000' in t:
        return ENUM_HINT
    return ''


def hint_for(code):
    try:
        c = int(code)
    except (TypeError, ValueError):
        return ''
    h = ERRNO_HINTS.get(c)
    return f'    ↳ errNo={c}：{h}' if h else ''


def _need_file(path, what):
    """令牌文件必须存在且非空 —— 否则给一句**说得清**的错。

    2026-11-03 代码审查 P1：旧实现直接 `open(sign_a_file)`，
    而调用方（`export_content.token_files()`）找不到文件时返回 **None**
    ⇒ `TypeError: expected str, bytes or os.PathLike object, not NoneType`。
    那个错因指向“类型”，而真正的问题是“你没有先跑证据包拿令牌”。
    """
    if not path:
        raise RuntimeError(f'{what} 没找到 —— 先跑一次 evidence_pack / server_shape '
                           f'把 signA/signB 令牌取到本地（旧报错是 TypeError，指向错地方）')
    if not os.path.exists(path):
        raise RuntimeError(f'{what} 不存在：{path}')
    body = open(path, encoding='utf-8', errors='replace').read().strip()
    if not body:
        raise RuntimeError(f'{what} 是空文件：{path}')
    return body


def _need_blob(blob, n, what):
    """解出来的 blob 必须够长 —— 短了就是**密钥不对**，不是算法问题。

    旧实现 `blob_a[0:5]` 对短 blob 静默给出一串短字符，
    签名照样算得出来，只是**每一个请求都被服务端拒**（errNo 6），
    而现象与"参数集不对"完全一样。
    """
    if len(blob) < n:
        raise RuntimeError(f'{what} 解出来只有 {len(blob)} 字节（需要 ≥{n}）'
                           f'—— 密钥不对，不是参数问题')


def _need_printable(raw, what):
    """解出来的每个字节都必须可打印 ASCII —— 否则是**密钥不对**。

    2026-11-04 代码审查 P1（`_need_blob` 只查长度，没查内容）：

        blob_a[0:5]   → const_a，实测恒为 `8&%d*`（5 个可打印字符）
        blob_b[0xc:0x16] → x，实测恒为 `VzYfc94fbW`（10 个可打印字符）

    长度对、内容错是**最坏的一种错**：签名照样算得出来，只是每个请求都被
    服务端拒（errNo 6），而现象与“参数集不对”完全一样 —— 人会去翻参数表，
    翻不出来。密钥错一步，解出来的是长度正确的一堆乱码。

    所以：**长度对了之后必须再验字符类**。
    """
    bad = [(i, b) for i, b in enumerate(raw) if not (0x20 <= b <= 0x7e)]
    if bad:
        i, b = bad[0]
        raise RuntimeError(
            f'{what} 第 {i} 字节是 0x{b:02x}，不是可打印 ASCII'
            f'（前 16 字节：{raw[:16]!r}）—— 密钥不对，不是参数问题。'
            f'旧实现会把这段乱码当常量用，于是**每个请求都被拒（errNo 6）**，'
            f'而现象与“参数集不对”一模一样。')
    return raw


def sign_material(serial, sign_a_file, sign_b_file):
    tok_a = _need_file(sign_a_file, 'signA 令牌')
    tok_b = _need_file(sign_b_file, 'signB 令牌')
    blob_a = decode_token(serial, tok_a, '@fG2SuLA')
    _need_blob(blob_a, 16, 'signA 解出的 blob')
    const_a = _need_printable(blob_a[0:5], 'signA 的 const_a').decode('latin1')
    key2 = blob_a[7:12].decode('latin1') + '#G4'
    blob_b = decode_token(serial, tok_b, key2)
    _need_blob(blob_b, 0x16, 'signB 解出的 blob')
    x = _need_printable(blob_b[0x0c:0x16], 'signB 的 x').decode('latin1')
    return const_a, x


def sign_digest(const_a, x, param):
    """**签名公式的唯一实现**（2026-11-03 收敛，代码审查 P2）。

    旧实现同一段公式在四处各写一遍：

        md5( const_a + '[' + md5(x) + ']@' + param )

    `kd_api.sign_for` / `read_sign_inputs.py` / `decode_token_native.py` /
    `find_sign_strings.py`。P0-5（“请求体里 `kakorrhaphiophobia` 重复”）
    正是这一类“有一处没跟着改”造成的。

    这一处有测试（`test_kd_api_sign.SignFor`），
    其它三处现在都调它 —— **改公式只改一个地方**。
    """
    inner = hashlib.md5(x.encode()).hexdigest()
    return hashlib.md5((const_a + '[' + inner + ']@' + param).encode()).hexdigest()


def sign_for(const_a, x, params):
    """
    Android's Base64.NO_WRAP = no line breaks, **padding kept** — the padding is part of the
    signed string, so it must not be stripped (stripping it silently breaks every request whose
    byte length is not a multiple of 3 — 54 of the 80 captured ones).
    """
    # the app signs the **sorted** parameter strings, concatenated without separators
    param = base64.b64encode(''.join(sorted(params)).encode()).decode()
    # **digest 走 `sign_digest`**（2026-11-03）：那才是公式的唯一实现。
    # `sign_for` 只负责"把参数列表变成 param 串"这一件事。
    return sign_digest(const_a, x, param), param


def sign_from_url(const_a, x, url):
    """Rebuild the signature from a captured URL's own fields (sorted, `sign` excluded)."""
    q = urllib.parse.parse_qsl(urllib.parse.urlparse(url).query, keep_blank_values=True)
    fields = sorted(f'{k}={v}' for k, v in q if k != 'sign')
    return sign_for(const_a, x, fields)[0]


def _read_lines(path):
    """读整个文件的行；显式关闭句柄（`open(...).read()` 会留 ResourceWarning）。"""
    with open(path, encoding='utf-8', errors='replace') as fh:
        return fh.read().splitlines()


def pairs_of(capture):
    """
    Match every `SIGN URL` with the `SIGN params` that produced it.

    The capture is written by several threads, so "the line above" is not reliable. Requests are
    tied together by the sign-block identity `(_t_, kakorrhaphiophobia)`; when a burst shares both
    (same second, same counter), the candidate whose field-name set equals the URL's wins.
    """
    lines = _read_lines(capture)
    entries = []          # (is_url, payload)
    for ln in lines:
        if ' SIGN params: ' in ln:
            entries.append((False, ln.split(' SIGN params: ', 1)[1].split(' | ')))
        elif ' SIGN URL: ' in ln:
            entries.append((True, ln.split(' SIGN URL: ', 1)[1].strip()))  # signurl-ok: 需保留与 params 的相对顺序

    def fields(plist):
        return dict(x.split('=', 1) for x in plist if '=' in x)

    out = []
    used = set()
    for i, (is_url, payload) in enumerate(entries):
        if not is_url:
            continue
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(payload).query, keep_blank_values=True))
        sent_names = {k for k in q if k not in ('sign', '_t_', 'kakorrhaphiophobia')}
        cands = []
        for j, (j_url, j_payload) in enumerate(entries):
            if j_url or j in used:
                continue
            f = fields(j_payload)
            if f.get('_t_') != q.get('_t_') or f.get('kakorrhaphiophobia') != q.get('kakorrhaphiophobia'):
                continue
            cands.append((len({k for k in f if k not in ('_t_', 'kakorrhaphiophobia')} ^ sent_names), j, j_payload))
        if not cands:      # fall back to the nearest preceding params line
            prev = [j for j, (j_url, _) in enumerate(entries[:i]) if not j_url and j not in used]
            if not prev:
                continue
            j = prev[-1]
            cands = [(0, j, entries[j][1])]
        cands.sort()
        _, j, plist = cands[0]
        used.add(j)
        out.append((plist, payload))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['verify', 'call', 'pull', 'request'])
    ap.add_argument('--adb', required=True)
    ap.add_argument('--sign-a', required=True)
    ap.add_argument('--sign-b', required=True)
    ap.add_argument('--capture')
    ap.add_argument('--url')
    ap.add_argument('--auto-method', action='store_true',
                    help='pull mode: try GET first, retry the same path as POST when the server answers 404')
    ap.add_argument('--all-paths', action='store_true',
                    help='pull mode: sweep every distinct path found in the capture (cdns are skipped)')
    ap.add_argument('--host', default=None, help='request mode: send to this host instead of the capture\'s first host')
    ap.add_argument('--param', action='append', default=[],
                    help='request mode: extra parameter(s) as k=v (repeatable)')
    ap.add_argument('--common-from', default=None,
                    help='request mode: capture whose URLs define the "common parameters" '
                         '(names present in >=80%% of that host\'s captured requests)')
    ap.add_argument('--post', action='store_true',
                    help='pull mode: send the signed fields as a form body (Volley-style POST) instead of a query string')
    ap.add_argument('--path', action='append', default=[],
                    help='pull mode: endpoint path(s) to re-sign and call, e.g. --path /pluto/app/hotfix')
    ap.add_argument('--rc4-key', help='call mode: payload key (yl.f.b) used to decrypt encrypted fields in '
                                      'the response; take it from the same-epoch capture "RC4KEY b(<vc>): …" line')
    ap.add_argument('--retime', action='store_true',
                    help='call mode: replace _t_ with the current epoch second and re-sign the request, '
                         'so the server-side anti-replay window does not reject a captured (stale) URL')
    ap.add_argument('--insecure', action='store_true',
                    help='skip TLS verification (host CA bundle is often incomplete; the app itself '
                         'has no pinning, see TRIAGE §4)')
    ap.add_argument('--dump', default=None, help='把完整响应体写入该文件（JSON；便于结构化导出）')
    a = ap.parse_args(argv[1:])

    const_a, x = sign_material(a.adb, a.sign_a, a.sign_b)
    print(f'[api] A={const_a!r}  X={x!r}  md5(X)={hashlib.md5(x.encode()).hexdigest()}')

    if a.mode == 'request':
        # Build a signed request for an endpoint the app never called on this device: the signed
        # parameter set is reconstructed from the *common* params observed in a capture, plus
        # whatever the caller supplies. Data-driven, not hand-copied.
        if not a.path or not a.common_from:
            print('[api] request needs --path and --common-from')
            return 2
        path = a.path[0]        # --path is an append list; this mode takes one endpoint
        import time
        lines = _read_lines(a.common_from)
        urls = capture_schema.sign_urls(lines)
        # 2026-10-12 加 ✓（规则 25 查出来的修法 ✓）：**先在抓取里找该路径的真 URL** ✓
        # 找到 ⇒ **照抄它的参数集** ✓（"照抄"永远比"自己拼"可靠 ✓）；
        # 找不到 ⇒ 才回落到"common 参数"拼装 ✓。
        direct = None
        for _u in urls:
            _q = _u.split('?', 1)[1] if '?' in _u else ''
            if _u.split('?', 1)[0].endswith(path) and _q:
                direct = _q
                break
        if direct:
            print(f'[api] **照抄抓取里的真参数** ✓（{len(direct.split("&"))} 个 ✓）')
        if not urls:
            print('[api] no signed URLs in --common-from capture')
            return 2
        def _split(u):
            # captured URLs can contain unbalanced '[' inside JSON-ish parameter values, which
            # makes urlparse raise "Invalid IPv6 URL" — skip those instead of dying.
            try:
                return urllib.parse.urlparse(u)
            except ValueError:
                return None

        host = a.host or _split(urls[0]).netloc
        parsed = [urllib.parse.parse_qsl(pu.query, keep_blank_values=True)
                  for pu in (_split(u) for u in urls) if pu is not None and pu.netloc == host]
        if not parsed and a.host:      # 该 host 在 capture 里没有样本 → 退回任意 host 的公共参数
            host = _split(urls[0]).netloc
            parsed = [urllib.parse.parse_qsl(pu.query, keep_blank_values=True)
                      for pu in (_split(u) for u in urls) if pu is not None and pu.netloc == host]
        count = {}
        for q in parsed:
            for k, _v in q:
                count[k] = count.get(k, 0) + 1
        threshold = max(1, int(len(parsed) * 0.8))
        # 2026-10-12 最后一处 ✓（照抄 `pull` 的做法 ✓）：
        # `pull` 不靠外面传的 A/X ✓ —— 它用 `pairs_of()` 去抓取里把
        # "SIGN URL" 与 "SIGN params" 配成对 ✓，再用那一对的 `plist` 重签 ✓。
        _pair_plist = None
        try:
            # 2026-10-12 fix: pick the pair with the MOST fields for this path.
            # The real sign input can contain fields that are NOT in the URL
            # (e.g. codeMD5 is signed but never sent) -> the richest pair wins.
            _best = 0
            for _plist, _url in pairs_of(a.common_from):
                if _url.split('?', 1)[0].endswith(path) and len(_plist) > _best:
                    _best = len(_plist)
                    _pair_plist = _plist
        except Exception as _e:
            print(f'[api] pairs_of 失败: {_e}')
        if _pair_plist:
            print(f'[api] **用抓取里配对好的 SIGN params** ✓（{len(_pair_plist)} 项 ✓）')
        if direct:
            template = {}
            for kv in direct.split('&'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    # 2026-10-12 修 ✓：**别把 `sign` 抄进来** ✗ ——
                    # 抄进来会导致"对着已含 sign 的集合再签一次" ✗ ⇒ 服务端报 `5103` ✗。
                    if k in ('sign', '_t_', 'kakorrhaphiophobia'):
                        continue
                    template[k] = v
        common = {k for k, n in count.items() if n >= threshold and k != 'sign'}
        template = {}
        for k, v in (parsed[-1] if parsed else []):
            if k in common:
                template[k] = v
        for kv in a.param:
            if '=' in kv:
                k, v = kv.split('=', 1)
                template[k] = v
        print(f'[api] host={host} common params={len(common)} (>= {threshold}/{len(parsed)} requests) '
              f'+ {len(a.param)} supplied -> {len(template)} total')
        now = int(time.time())
        signed = [f'{k}={v}' for k, v in template.items()] + [f'_t_={now}',
                                                              'kakorrhaphiophobia='
                                                              + template.get('kakorrhaphiophobia', '0')]
        if _pair_plist:
            signed = list(_pair_plist)   # 用抓取里配对好的字段集 ✓（照抄 `pull` ✓）
        if os.environ.get('KD_DEBUG_SIGN'):
            print('[DBG sign-request] ' + ' | '.join(sorted(signed))[:400])
        sign, _param = sign_for(const_a, x, signed)
        # 2026-10-12 **改回** ✓（对照法定的案 ✓）：
        # `pull` 流**能成** ✓ 而它的 body **排除** `_t_` 与 `kakorrhaphiophobia` ✓
        # ⇒ 说明这两个是走 **URL query** 的 ✓，不该进 body ✗。
        # （R448 那次"让它们进 body"是**改错方向** ✗ —— 而 5110 的真因是**参数集不全** ✓，
        #  那已由"照抄抓取"修好 ✓ ⇒ 两个修法要**合起来** ✓。）
        body = '&'.join(urllib.parse.quote(f, safe='=')
                        for f in signed if not f.startswith(('_t_', 'kakorrhaphiophobia')))
        # 与其它六个文件**同一个决定点**（2026-11-03 修）：以前这里认
        # `--insecure`，而 `pageapi` / `probe_paths` 等六个文件无条件跳 ——
        # 同库两种默认。现在统一走 `net.ssl_context()`，它认 `KD_INSECURE`，
        # 而 `--insecure` 仍然有效（下面把它转成环境变量）。
        ctx2 = net.ssl_context() if (a.insecure or net.insecure()) else None
        target_host = a.host or host
        if a.post:
            # 2026-10-12 **关键修正** ✓（对照法定的案 ✓）：`pull` 流**能成** ✓，而它的 URL 是
            # `https://{host}{path}?&{body}` ✓ —— **参数在 query 里** ✓；
            # 而 `request` 流原先**只把它们放 body** ✗ ⇒ 服务端报 `5110 lack time param` ✗。
            # 2026-10-12 **照 `pull` 的写法** ✓（对照法一步步定出来的 ✓）：
            # body = 参数 + `&sign=…&_t_=…&kakorrhaphiophobia=…` ✓ —— **三个尾字段按此顺序追加** ✓。
            # 2026-10-12 最后一跳：kakorrhaphiophobia 我抄的时候跳过了 ⇒ 默认 0；
            # 而它进了 sign 的输入 ⇒ 值不同 ⇒ sign 不同 ⇒ errNo:6 ⇒ 从原始 URL 读回来。
            _kak = '0'
            for _kv in direct.split('&'):
                if _kv.startswith('kakorrhaphiophobia='):
                    _kak = _kv.split('=', 1)[1]
                    break
            _data = f'{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={_kak}'
            if os.environ.get('KD_DEBUG_SEND'):
                print(f'[DBG request {path}] {_data[:400]}')
            req = urllib.request.Request(f'https://{target_host}{path}',
                                         data=_data.encode(),
                                         headers={'User-Agent': 'okhttp/4.9.0',
                                                  'Accept-Encoding': 'identity',
                                                  'Content-Type': 'application/x-www-form-urlencoded'})
        else:
            req = urllib.request.Request(f'https://{host}{path}?&{body}',
                                         headers={'User-Agent': 'okhttp/4.9.0',
                                                  'Accept-Encoding': 'identity'})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx2) as r:
                raw = r.read(200000 if a.dump else 2000)   # --dump 时要完整响应体
                print(f'[api] HTTP {r.status} {target_host}{path}')
                print('[api] body:', raw[:400])
        except urllib.error.HTTPError as e:
            print(f'[api] HTTP {e.code} {target_host}{path}: {e.read(200)[:200]}')
        except Exception as e:
            print(f'[api] request failed: {e}')
            return 1
        return 0

    if a.mode == 'pull':
        if not a.capture or (not a.path and not a.all_paths):
            print('[api] pull needs --capture and at least one --path (or --all-paths)')
            return 2
        import time
        lines = _read_lines(a.capture)
        urls = capture_schema.sign_urls(lines)
        m = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', '\n'.join(lines))
        key = m.group(1) if m else ''

        paths = list(a.path)
        if a.all_paths:
            seen = set(paths)
            for u0 in urls:
                pu = urllib.parse.urlparse(u0)
                if any(h in pu.netloc for h in ('cdn', 'adx.', 'gtactivity', 'img', 'static')):
                    continue
                if pu.path and pu.path not in seen:
                    seen.add(pu.path)
                    paths.append(pu.path)

        def attempt(path, src_url, use_post):
            u = urllib.parse.urlparse(src_url)
            q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
            kak = q.get('kakorrhaphiophobia', '0')
            now = int(time.time())
            signed = [f'{k}={v}' for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
                      if k not in ('sign', '_t_', 'kakorrhaphiophobia')]
            signed += [f'_t_={now}', f'kakorrhaphiophobia={kak}']
            if os.environ.get('KD_DEBUG_SIGN'):
                print(f'[DBG sign-pull {path}] ' + ' | '.join(sorted(signed))[:400])
            sign, _param = sign_for(const_a, x, signed)
            body = '&'.join(urllib.parse.quote(f, safe='=') for f in signed
                            if not f.startswith(('_t_', 'kakorrhaphiophobia')))
            ctx2 = net.ssl_context() if (a.insecure or net.insecure()) else None
            if use_post:
                _d2 = f'{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}'
                if os.environ.get('KD_DEBUG_SEND'):
                    print(f'[DBG pull {path}] {_d2[:400]}')
                req = urllib.request.Request(f'{u.scheme}://{u.netloc}{u.path}',
                                             data=_d2.encode(),
                                             headers={'User-Agent': 'okhttp/4.9.0',
                                                      'Accept-Encoding': 'identity',
                                                      'Content-Type': 'application/x-www-form-urlencoded'})
            else:
                req = urllib.request.Request(
                    f'{u.scheme}://{u.netloc}{u.path}?&{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}',
                    headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity'})
            try:
                with urllib.request.urlopen(req, timeout=20, context=ctx2) as r:
                    return r.status, r.read(200000 if a.dump else 4000), "POST" if use_post else "GET"
            except urllib.error.HTTPError as e:
                return e.code, e.read(200), 'POST' if use_post else 'GET'
            except Exception as e:
                return 0, str(e).encode(), 'POST' if use_post else 'GET'

        rows = []
        for path in paths:
            cand = [u for u in urls if urllib.parse.urlparse(u).path == path]
            if not cand:
                rows.append((path, 'no-capture', '', '', ''))
                continue
            modes = [False, True] if a.auto_method else [a.post]
            code, raw, mode = 0, b'', ''
            for use_post in modes:
                code, raw, mode = attempt(path, cand[-1], use_post)
                if code == 200:
                    break
            errstr, plain = '', ''
            try:
                doc = json.loads(raw)
                errstr = str(doc.get('errstr', ''))
                enc = (doc.get('data') or {}).get('encodeData') if isinstance(doc.get('data'), dict) else None
                if enc and key:
                    from kd_crypto import rc4 as _rc4
                    import base64 as _b64
                    plain = _rc4(key.encode(), _b64.b64decode(enc)).decode('utf-8', 'replace')[:70]
                elif isinstance(doc.get('data'), dict):
                    plain = json.dumps(doc['data'], ensure_ascii=False)[:70]
            except Exception:
                plain = raw[:60].decode('utf-8', 'replace')
            rows.append((path, str(code), mode, errstr, plain))
            if a.dump:
                import json as _j      # 本函数内已有局部 import json，故此处另起别名避免作用域冲突
                _d = {}
                if os.path.exists(a.dump):
                    try:
                        with open(a.dump, encoding='utf-8') as _fh:
                            _d = _j.load(_fh)
                    except Exception:
                        _d = {}
                _d[path] = {'http': code, 'method': mode, 'errstr': errstr,
                            'body': raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)}
                with open(a.dump, 'w', encoding='utf-8') as _fh:
                    _j.dump(_d, _fh, ensure_ascii=False, indent=1)
            time.sleep(0.4)

        print('path\thttp\tmethod\terrstr\tpayload')
        for path, code, mode, errstr, plain in rows:
            print(f'{path}\t{code}\t{mode}\t{errstr}\t{plain}')
            import re as _re
            m = _re.search(r'"errNo":(-?\d+)', plain) or _re.search(r'errNo[=:]\s*(-?\d+)', plain)
            if m and m.group(1) != '0':
                h = hint_for(m.group(1))
                if h:
                    print(h)
                eh = enum_hint_for(plain)
                if eh:
                    print(eh)
        ok = sum(1 for r in rows if r[1] == '200')
        print(f'[api] {ok}/{len(rows)} endpoint(s) returned 200')
        return 0 if ok else 1

    if a.mode == 'verify':
        if not a.capture:
            print('[api] verify needs --capture')
            return 2
        lines = _read_lines(a.capture)
        param_lines = [ln.split(' SIGN params: ', 1)[1].split(' | ')
                       for ln in lines if ' SIGN params: ' in ln]
        urls = capture_schema.sign_urls(lines)

        # index every captured param list by the signature it produces
        by_sign = {}
        for plist in param_lines:
            want, param = sign_for(const_a, x, plist)
            by_sign.setdefault(want, []).append(plist)
        print(f'[api] {len(param_lines)} param list(s), {len(urls)} signed URL(s), '
              f'{len(by_sign)} distinct computed sign(s)')

        # Endpoints whose *signing input* is provably not the URL query. They are counted and
        # reported as "excluded", never silently passed: a NEW endpoint that stops reconstructing
        # is still a failure (see `unexpected` below).
        #   abtest…/abengine/api/client signs a Java Map.toString() copy of its params
        #   (`params={cuid=…, params=(this Map), …}`), while the URL carries a JSON `params`
        #   array — different bytes, so no URL projection can rebuild it.
        SIGN_INPUT_NOT_URL = {
            'abtest.zuoyebang.com/abengine/api/client':
                'signs a Java Map.toString() copy of its params, not the JSON `params` that reaches the URL',
        }

        verified = unexpected = missing_sign = 0
        excluded = {}
        for url in urls:
            u = urllib.parse.urlparse(url)
            got = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True)).get('sign')
            if got is None:
                # the capture truncates long lines, so `sign` never reached the log: not rebuildable
                missing_sign += 1
                continue
            want = sign_from_url(const_a, x, url)
            if want == got:
                verified += 1
                continue
            key = f'{u.netloc}{u.path}'
            if key in SIGN_INPUT_NOT_URL:
                excluded.setdefault(key, []).append(got)
                continue
            unexpected += 1
            print(f'  MISMATCH {key}: recomputed={want} sent={got}')
        n_excluded = sum(len(v) for v in excluded.values())
        for key, gots in sorted(excluded.items()):
            held = sum(1 for g in gots if g in by_sign)   # the algorithm is proven, the projection differs
            print(f'  EXCLUDED {key}: {len(gots)} url(s), signing input captured for {held}/{len(gots)} '
                  f'— {SIGN_INPUT_NOT_URL[key]}')
        print(f'[api] rebuild: verified={verified} excluded={n_excluded} unexpected={unexpected} '
              f'missing_sign={missing_sign} of {len(urls)} url(s); '
              f'assertion covers the {verified + n_excluded + unexpected} url(s) whose sign reached the log')
        if unexpected == 0:
            print('[api] OK — every rebuildable signed URL reproduces byte-exactly; '
                  'truncated URLs and non-URL signing inputs are listed, not silently passed')
        return 0 if (unexpected == 0 and verified > 0) else 1

    # call
    url = a.url
    if url is None:
        print('[api] call needs --url')
        return 2
    u = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    if a.retime:
        import time
        now = int(time.time())
        kak = q.get('kakorrhaphiophobia', '0')
        signed = [f'{k}={v}' for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
                  if k not in ('sign', '_t_', 'kakorrhaphiophobia')] + [f'_t_={now}',
                                                                        f'kakorrhaphiophobia={kak}']
        sign, param = sign_for(const_a, x, signed)
        body = '&'.join(urllib.parse.quote(f, safe='=') for f in signed
                        if not f.startswith(('_t_', 'kakorrhaphiophobia')))
        url = f'{u.scheme}://{u.netloc}{u.path}?&{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}'
        print(f'[api] re-timed and re-signed (_t_={now}, param={len(param)} B) for {u.netloc}{u.path}')
    elif 'sign' in q and '_t_' in q:
        print(f'[api] using captured signature for {u.netloc}{u.path}')
    req = urllib.request.Request(url, headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity'})
    ctx = net.ssl_context() if (a.insecure or net.insecure()) else None
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            body = r.read(600)
            print(f'[api] HTTP {r.status}  {u.netloc}{u.path}  bytes={len(body)}+')
            print('[api] body head:', body[:400])
            import re as _re2
            _m = _re2.search(r'"errNo":(-?\d+)', body.decode('utf-8', 'replace') if isinstance(body, bytes) else str(body))
            if _m and _m.group(1) != '0':
                _h = hint_for(_m.group(1))
                if _h:
                    print(_h)
                _eh = enum_hint_for(body.decode('utf-8', 'replace') if isinstance(body, bytes) else str(body))
                if _eh:
                    print(_eh)
        if a.rc4_key:
            import base64 as _b64
            sys.path.insert(0, __file__.rsplit('/', 1)[0])
            from kd_crypto import rc4 as _rc4
            try:
                doc = json.loads(body)
            except Exception:
                doc = None
            if isinstance(doc, dict) and isinstance(doc.get('data'), dict):
                for field in ('encodeData', 'encryptData', 'content'):
                    val = doc['data'].get(field)
                    if isinstance(val, str) and val:
                        try:
                            pt = _rc4(a.rc4_key.encode(), _b64.b64decode(val))
                            print(f'[api] {field} decrypted: {pt[:300]!r}')
                        except Exception as ex:
                            print(f'[api] {field} decrypt failed: {ex}')
    except urllib.error.HTTPError as e:
        print(f'[api] HTTP {e.code} for {u.netloc}{u.path}: {e.read(200)!r}')
        return 1
    except Exception as e:
        print(f'[api] request failed: {e}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
