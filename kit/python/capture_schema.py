#!/usr/bin/env python3
"""
kuaidui-kit / capture_schema.py — the **single source of truth** for the KdKit capture format.

Why this file exists
--------------------
Before 2026-10-25 every parser in `kit/python/` did its own `if 'RC4PT ' in line` style
substring test. That works until the module grows a new prefix: then the new lines are
*silently invisible* to every report (they are just "unknown lines"), and the only symptom
is a number that stays at zero. `OPTIMIZATION.md` §7 lists exactly this gap.

So the format is now declared **once**, as an ordered table of rules, and every parser
asks `parse_line()` instead of guessing:

    from capture_schema import parse_line, iter_records, summarise

    for rec in iter_records('cap.txt'):
        if rec.kind == 'RC4PT' and rec.variant is None:
            ...

Contract
--------
* The module writes one event per line: `HH:mm:ss.SSS <body>` (see `util/Capture.kt`).
  The timestamp is optional on read — hand-trimmed snippets and older captures lack it.
* `<body>` starts with a **prefix token**. The token is the module's public contract with
  this kit; renaming one in Kotlin silently breaks every parser, so
  `module/scripts/check_capture_prefixes.py` gates it (see `REQUIRED_BY_MODULE` below).
* Rules are tried **longest-prefix-first** (`RC4KEYSTR` before `RC4KEY` before `RC4`,
  `RC4PT(nontext)` before `RC4PT`). Order is part of the contract: a careless reorder
  makes `RC4PT(nontext)` be read as a plaintext record.

Prefixes covered (as of 2026-10-25)
----------------------------------
**Don't hard-code the feature count here.** It was written as "module 28 features" while
`FeatureRegistry.all` had grown to 33, so this line — the file that calls itself the single
source of truth — was the one place stating a stale number. The live counts are derived from
`FEATURE_IDS` / `FEATURES_WITH_CAPTURE`; print them instead of restating them:

    python3 capture_schema.py cap.txt      # prints "N/M capturable feature(s)"

Prefix tokens (the first word of every record). This list is documentation for humans;
`RULES` below is the actual contract, and `tests/test_capture_schema.py` proves every token
here has a rule:

`SIGN URL` / `SIGN params` / `SIGN result` / `SIGNPARAM` / `FORMULA` / `RC4KEY` /
`RC4KEYSTR` / `RC4` / `NET DECRYPT|ENCRYPT` / `H5 <prim>|DECRYPT|ENCRYPT` /
`H5BRIDGE` / `H5RET` / `ADSLOT call|ret` / `blocked ad slot read` / `GUARD` / `ROUTE` /
`NAV` / `NAVACT` / `RC4PT` / `RC4PT(nontext)` / `RC4UP` / `RC4UP(nontext)` / `EXITCALL` /
`EXITSTACK` / `BRIDGE` / `BRIDGE decodeHttpRequest` / `VIP` / `VIPLIMIT` / `UPDATE` /
`ONBOARD` / `APPSIGN` / `WEBREQ` /
`HDR` / `HDR(v)` / `HDR(static)` / `NETERR` / `REQBODY` / `RESPBODY` / `POPWIN` /
`WATERMARK` / `=== <mark>`.

CLI (handy for "what is actually in this file?"):

    python3 capture_schema.py cap.txt            # kind table + per-feature counts
    python3 capture_schema.py cap.txt --unknown  # show lines no rule claimed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

# ── feature ids ───────────────────────────────────────────────────────────────
# These are the exact `BaseFeature.id` values in module/.../FeatureRegistry.kt. A prefix
# that cannot be attributed to a feature would make ACTIVITY.md unverifiable, so every
# rule below names one (or None for session markers).
FEATURE_IDS = (
    'ad_probe', 'anti_detect', 'block_ad_sdk', 'bridge_action_log', 'bridge_guard',
    'exit_guard', 'h5_bridge_log', 'h5_debug', 'http_body_probe', 'log_sink', 'nav_log',
    'native_exit_guard',
    'native_probe', 'page_js', 'pk_assist', 'rc4_probe', 'req_headers', 'rm_adconfig',
    'rm_feed_ad', 'rm_main_banner', 'rm_popup', 'rm_splash', 'rm_tab_ad', 'robust_probe', 'route_log',
    'sign_observer', 'net_error_probe', 'skip_onboarding', 'skip_update', 'vip_limit_probe', 'vip_unlock',
    'watermark_off', 'web_picture_watermark',
    'popwin_gate',
    'web_request_log',
    'page_request_log',
    'parent_ctrl_probe',
    'parent_ctrl_write',
    # 2026-11-14：会员推广清理与 MD3 皮肤（v1.2）
    'rm_vip_promo',
    'md3_skin',
    # 2026-11-14：设置页 KdKit 入口（settings_entry）
    'settings_entry',
)

TS_RE = re.compile(r'^(\d{2}:\d{2}:\d{2}\.\d{3})\s+(.*)$', re.S)


@dataclass(frozen=True)
class Record:
    """One parsed capture line. `fields` is always a dict (never None)."""

    raw: str
    ts: Optional[str]
    kind: str
    feature: Optional[str]
    variant: Optional[str] = None
    fields: dict = field(default_factory=dict)

    def get(self, name: str, default=None):
        return self.fields.get(name, default)

    def __bool__(self) -> bool:          # a parsed record is always truthy
        return True


# ── helpers ───────────────────────────────────────────────────────────────────

def _b64_len(token: str) -> Optional[int]:
    """`b64[44]` -> 44; anything else -> None."""
    m = re.fullmatch(r'b64\[(\d+)\]', token)
    return int(m.group(1)) if m else None


def _kv_pairs(text: str) -> dict:
    """`k=v | k2=v2` -> {'k': 'v', 'k2': 'v2'} (first wins; never raises)."""
    out = {}
    for part in text.split(' | '):
        if '=' in part:
            k, v = part.split('=', 1)
            out.setdefault(k.strip(), v.strip())
    return out


def _url_fields(url: str) -> dict:
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return {}
    q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
    out = {'host': u.netloc, 'path': u.path, 'query_count': len(q)}
    for k in ('sign', '_t_', 'kakorrhaphiophobia'):
        if k in q:
            out[k] = q[k]
    return out


# ── the rule table ────────────────────────────────────────────────────────────
# (kind, feature, variant, compiled regex, field builder)
#
# Field builders take the regex match and return a dict. Keep them total: they must not
# raise on malformed input, because a half-written trailing line is normal in a capture
# that was pulled while the app was still appending.

def _f_sign_url(m):
    url = m.group(1).strip()
    d = {'url': url}
    d.update(_url_fields(url))
    return d


def _f_sign_params(m):
    body = m.group(1)
    keys = [p.split('=', 1)[0].strip() for p in body.split(' | ') if p.strip()]
    return {'count': len(keys), 'keys': keys}


def _f_rc4key(m):
    """Shared by the three key lines; groups are optional so use `groupdict`, not `group`."""
    g = m.groupdict()
    d = {'key': (g.get('key') or '').strip()}
    if g.get('ver'):
        d['version'] = g['ver']
    if g.get('len'):
        d['length'] = int(g['len'])
    return d


def _f_rc4(m):
    return {
        'op': m.group(1),
        'key_len': int(m.group(2)),
        'key_b64': m.group(3),
        'in_len': int(m.group(4)),
        'in_b64': m.group(5),
        'out_len': int(m.group(6)),
        'out_b64': m.group(7),
    }


def _f_net(m):
    return {'op': m.group(1), 'dir': m.group(2), 'value': m.group(3)}


def _f_h5(m):
    return {'prim': m.group(1), 'dir': m.group(2), 'value': m.group(3)}


def _f_h5bridge(m):
    return {'action': m.group(1), 'count': int(m.group(2)), 'args': (m.group(3) or '').strip()}


def _f_adslot_call(m):
    return {'cls': m.group('cls'), 'method': m.group('method'),
            'pos': int(m.group('pos')), 'seq': int(m.group('seq'))}


def _f_adslot_ret(m):
    # 无参方法（`j()` / `k()` —— "有没有配广告"）的 `pos` 是空串，不能硬转 int
    return {'cls': m.group('cls'), 'method': m.group('method'),
            'pos': int(m.group('pos')) if m.group('pos') else None,
            'shown': m.group('shown')}


def _f_route(m):
    return {'route': m.group(1).strip(), 'arg': (m.group(2) or '').strip(),
            'from': (m.group(3) or '').strip()}


def _f_nav(m):
    return {'page': m.group(1).strip(), 'url': (m.group(2) or '').strip()}


def _f_navact(m):
    return {'activity': m.group(1).strip()}


def _f_event(m):
    """`PROMO <what>` / `MD3 <what>` —— 只有"发生了什么"这一层，没有结构化子字段。

    为什么不硬拆字段：这两个功能写的是**事件名**（`blocked dialog show`、
    `native bg neutralised`），拆成 key=value 只会把人造结构塞进一个本来扁平的记录。
    需要更细的结构时再改，别现在猜。
    """
    return {'event': m.group(1).strip()}


def _f_rc4text(m):
    """`RC4PT <text>` / `RC4UP <text>` — printable plaintext, truncated to 120 chars."""
    return {'text': m.group(1).strip()}


def _f_rc4nontext(m):
    """`RC4PT(nontext) len=44 b64=...` — deliberately *not* text; kept for counter evidence."""
    return {'len': int(m.group(1)), 'b64': m.group(2)}


def _f_guard(m):
    url = (m.group(3) or '').strip()
    d = {'action': m.group(1), 'reason': m.group(2), 'url': url,
         'seq': int(m.group(4)) if m.group(4) else None}
    if url:
        h = urllib.parse.urlparse(url).hostname
        # A relative path is resolved by the guard against BridgeGuard.SELF_HOST.
        d['host'] = h or 'self:www.kuaiduizuoye.com'
    return d


def _f_exitcall(m):
    return {
        'seq': int(m.group(1)),
        'where': m.group(2).strip(),
        'blocked': m.group(3) == 'true',
        'stack_suppressed': bool(m.group(4)),
    }


def _f_exitstack(m):
    return {'seq': int(m.group(1)), 'stack': m.group(2)}


def _f_bridge_download(m):
    return {'action': 'downloadMedia', 'type': int(m.group(1)), 'url': m.group(2).strip()}


def _f_bridge_userinfo(m):
    return {'action': 'getuserinfo', 'identity': m.group(1).strip()}



def _f_bridge_decode(m):
    """`BRIDGE decodeHttpRequest url=<host+path> shouldDecode=<0|1|?> params=keys=N:a,b,c`。

    三个字段各自回答一个问题，且都**不含值**（见 `DecodeRequestShape` 的离线断言）：

    * `url` —— 已经剥掉 query 与 fragment（那里几乎是 token / 用户输入）；
      空串写成 `(empty)`，与"解析失败"区分开。
    * `shouldDecode` —— `?` 表示页面**没传**这个键。宿主的 smali 里缺键填 `-1`
      然后 `if (v1 != -1)` 才发请求 ⇒ "没传"与"传了 0"是两条不同路径，
      合并会让观测结论错，所以这里保留三态。
    * `params` —— 只有键名与个数。`0` = 空对象，`not-object` = 传了非对象。
    """
    sd = m.group('sd')
    return {
        'action': 'decodeHttpRequest',
        'url': m.group('url'),
        'shouldDecode': (None if sd == '?' else int(sd)),
        'params': m.group('params'),
    }


def _f_page_request(m):
    """`PAGEREQ from=<action> url=<host+path> params=keys=N:a,b,c method=<0|1|?>`。

    四个字段各自回答一个问题，且都**不含值**：

    * `from` —— 发起请求的那个 action 类名（`EncryptDataRequestAction` /
      `CoreHttpRequestAction` …）。由 `dr.f.a` 首参的匿名内部类名剥掉末尾纯数字后缀得到，
      见 `PageRequestOrigin.actionOf`；拿不到时是字面量 `(unknown)`，**不编造**。
    * `url` —— 已剥 query / fragment（与 `decodeHttpRequest` 同一条规则、同一个实现）。
    * `params` —— 只有键名与个数；`0` = 空 Map，`not-object` = 形参不是 Map。
    * `method` —— `dr.f.a` 的 `p4`：0=GET / 1=POST；`?` = 取不到（不猜）。

    `action` 字段与其它 BRIDGE 变体保持一致（`bridge_inventory.py` 用它分组）；
    这里的值是**页面驱动的动作名**，不是某个固定 action —— 所以叫 `pageRequest`。
    """
    meth = m.group('meth')
    return {
        'action': 'pageRequest',
        'from': m.group('from'),
        'url': m.group('url'),
        'params': m.group('params'),
        'method': (None if meth == '?' else int(meth)),
    }


def _f_bridge_payorder(m):
    """`len` 是 `payInfo` 原串长度；`keys` 是它的**键名**（不是值）。"""
    kind, keys_raw = m.group(2), m.group(3)
    if kind == 'empty':
        shape, keys = 'empty', []
    elif kind == 'not-json':
        shape, keys = 'not-json', None
    else:
        shape, keys = 'keys', (keys_raw.split(',') if keys_raw else [])
    # `action` 必须出现在**每一个** BRIDGE 变体上：`bridge_inventory.py` 用它做分组键。
    # 第 28 轮漏了这一个字段，于是 `semantic[None] += 1`，排序时 `None < str` 抛 TypeError
    # —— 一个消费端假设被新变体打破。不变式由 `test_capture_schema.py::KindFieldContract` 兜住。
    return {'action': 'fetchPayInfos', 'len': int(m.group(1)), 'shape': shape,
            'keys': keys, 'pid': m.group(4)}


def _f_robust_patch(m):
    """`ROBUST patch lk.f #4dec supported=true redirect=true`。

    `no` 是 **Robust 的方法序号**（十六进制，来自插桩里的 `const/16`），
    不是「第几次事件」—— 所以它不做 int 转换，保留原字符串，
    免得把 `?`（静态方法拿不到序号时写的占位）弄丢。
    """
    return {
        'who': m.group('who'),
        'method_no': m.group('no'),
        'supported': (None if m.group('supported') == '?' else m.group('supported') == 'true'),
        'redirect': m.group('redirect') == 'true',
    }


def _f_robust_stack(m):
    return {'who': m.group('who'), 'method_no': m.group('no'), 'stack': m.group('stack')}


def _f_update(m):
    """Both UPDATE shapes share this builder, so read named groups defensively."""
    g = m.groupdict()
    if g.get('before') is not None:
        return {'variant': 'forceup', 'mode': 'forceup',
                'before': int(g['before']), 'after': int(g['after'])}
    return {'variant': 'suppressed', 'mode': 'suppressed'}


def _f_onboard(m):
    return {'text': m.group(1), 'label': m.group(2), 'seq': int(m.group(3)),
            'ok': m.group(4) == 'true'}


def _f_appsign(m):
    return {'level': m.group(1), 'tag': m.group(2).strip(), 'msg': m.group(3)}


def _f_webreq(m):
    brief = (m.group(2) or '').strip()
    url = m.group(1).strip()
    d = {'url': url, 'headers': brief}
    hdrs = _kv_pairs(brief) if brief else {}
    if hdrs:
        d['header_names'] = sorted(hdrs)
    # 业务域标注：同一路径在 APK 里可能被多个 `Xxx$Input` 声明（不同 `__pid`），
    # 全列出来而不是猜一个 —— 猜错会让重放带错 pid（见 `SIGNED_SURFACE.md`）。
    pids = pid_of(url)
    if pids:
        d['pid'] = pids if len(pids) > 1 else pids[0]
    return d



# ── 业务域 `__pid` 标注（可选增强）─────────────────────────────────────────────
#
# 数据来源是 `kit/scripts/api_pid_map.py` 从 smali 静态提取的映射（路径 → 业务域）。
# **惰性加载 + 失败即降级为空**：解析器必须能在没有 APK 的环境里单独跑
# （单元测试、CI），不能因为找不到 `work/apktool_out` 就整体失败。
_PID_CACHE = {}


def _pid_index():
    if 'v' in _PID_CACHE:
        return _PID_CACHE['v']
    out = {}
    try:
        import sys as _sys
        from pathlib import Path as _P
        root = _P(__file__).resolve().parents[2]
        _sys.path.insert(0, str(root / 'kit' / 'scripts'))
        import api_pid_map as _m
        smali = root / 'work' / 'apktool_out'
        if smali.is_dir():
            for row in _m.scan(str(smali)):
                out.setdefault(row['url'], set()).add(row['pid'] or '')
        _PID_CACHE['v'] = out
    except Exception:
        _PID_CACHE['v'] = {}
    return _PID_CACHE['v']


def pid_of(url: str):
    """某个 URL 在 APK 里声明的业务域 pid 列表（去重、排序）；未知返回 []。"""
    from urllib.parse import urlparse
    try:
        path = urlparse(url).path
    except Exception:
        return []
    if not path:
        return []
    pids = _pid_index().get(path)
    if not pids:
        return []
    return sorted(('(空)' if p == '' else p) for p in pids)


def _f_hdr(m):
    variant = m.group(1) or 'request'
    rest = m.group(2)
    if ' :: ' in rest:
        target, body = rest.split(' :: ', 1)
        target = target.strip()
        d = {'variant': variant}
        # `HDR(v) host/path pid=cube :: K=V | …`（2026-10-25 起 volley 侧会带业务域）
        #
        # `-` 表示**读不到**（非 HWRequest 子类 / 字段改名），不是"没有域"。
        # 三种情况必须可区分：缺这个键 = 旧格式；`pid='-'` = 读取失败；其余 = 真实值。
        mm = re.search(r'\s+pid=(\S+)$', target)
        if mm:
            d['pid'] = mm.group(1)
            target = target[:mm.start()].strip()
        d['target'] = target
        d['fields'] = _kv_pairs(body)
        return d
    return {'variant': variant, 'target': '', 'fields': _kv_pairs(rest)}


def _f_parentctrl(m):
    """`PCTRL aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x5` — 家长模式**读侧**。

    四个闸门都是 `int`（宿主本来就是 `int`，不是 `boolean`），读不到写 `?`。

    `mask` 是四位十六进制：某位为 1 当且仅当该字段**读到且非 0**。
    它必须与四个字段一起读 —— `mask=0x0` 既可能是"全关"也可能是"全没读到"，
    两者**不可由掩码区分**（写侧同名字段的掩码可以直接对拍）。
    """
    d = {'aiwriting': m.group('aiwriting'), 'book': m.group('book'),
         'correctsearch': m.group('correctsearch'), 'picsearch': m.group('picsearch'),
         'mask': m.group('mask')}
    # `?` 保持字符串，其余转 int。**不能**把 `?` 折成 0：0 是合法取值。
    return {k: (v if v == '?' else int(v))
            for k, v in d.items() if k != 'mask'} | {'mask': d['mask']}


def _f_parentctrl_write(m):
    """`PCTRLW … mask=0x5 from=2 userMode=?` — 家长模式**写侧**（提交快照）。

    比读侧多两个字段：`from`（提交来源）与 `userMode`（提交时的模式）。
    它们**不参与** `mask`：`mask` 只描述四个闸门的组合，掺进非闸门字段会让
    "读侧写侧对拍"这个用途失效。
    """
    base = _f_parentctrl(m)
    for k in ('from', 'userMode'):
        v = m.group(k)
        base[k] = (v if v == '?' else int(v))
    return base


def _f_watermark(m):
    """`WATERMARK off applied` / `WATERMARK off applied | scope=webpic`.

    这一行只有一件事要说：**代用户按下了去水印开关**。它不带任何图片内容。

    但尾部的 `scope` 不是装饰 —— 有两个功能写同一前缀、同一 variant：

    * `watermark_off`（导出合成，钩 `cu.l` 构造器置 `r` 字段）
    * `web_picture_watermark`（浏览页本地绘制，钩 `c2`）

    `PREFIX_FEATURE` 由 `setdefault` 派生，一个 token 只能归属一个功能，所以两者
    只能是同一个 `watermark_off`。**`scope` 是唯一能把它们分开的字段**；
    它若被并进 `note` 字符串，按功能统计时两条链路就永远合成一个数字。

    `scope` 缺省为 `None`（老样本 / 导出合成那条链路），**不**补成 `'export'`：
    "没写" 与 "写了 export" 是两件事，猜一个值就等于伪造来源。
    """
    body = m.group(1).strip()
    scope = None
    if ' | scope=' in body:
        body, _, scope = body.partition(' | scope=')
        scope = scope.strip() or None
    return {'note': body.strip(), 'scope': scope}


def _f_mark(m):
    return {'text': m.group(1).strip()}


def _f_popwin(m):
    """`POPWIN seen type=winAd block=true action=BLOCK` — 服务端弹窗分派观测。

    `type` 是服务端下发的字符串（`winAd` / `winUp` / …），`block` 是"它是否命中拦截清单"，
    `action` 是最终动作（`PASS` / `OBSERVE` / `BLOCK`）。三者分开记，因为
    "本来该拦" 与 "实际拦了" 在 `observe_only` 打开时**不相等** —— 合并成一个字段
    就再也看不出观测模式到底有没有生效。
    """
    action = m.group('action')
    return {'type': m.group('type'),
            'block': m.group('block') == 'true',
            'action': action,
            # 冗余一个布尔：消费方通常只关心"这次真的拦下来了吗"，
            # 而 action == 'BLOCK' 才是"改行为"的唯一取值（OBSERVE 只是记录）。
            'blocked': action == 'BLOCK'}


def _f_bodytext(m):
    """`REQBODY text HWRequest len=248 {"a":1}` — 请求体/响应体的可读形态。"""
    body = m.group('body')
    return {'who': m.group('who') or None,
            'len': int(m.group('len')),
            'body': body,
            'truncated': bool(m.group('cut'))}


def _f_resptext(m):
    """`RESPBODY text status=200 len=1 {"a":1}` — 带 HTTP 状态码。"""
    st = m.group('status')
    body = m.group('body')
    return {'status': st if st == '?' else int(st),
            'len': int(m.group('len')),
            'body': body,
            'truncated': bool(m.group('cut'))}



RULES = (
    # ── plaintext / key probing (rc4_probe) — the `(nontext)` forms FIRST ──────
    ('RC4PT', 'rc4_probe', 'nontext',
     re.compile(r'^RC4PT\(nontext\) len=(\d+) b64=(\S*)\s*$'), _f_rc4nontext),
    ('RC4UP', 'rc4_probe', 'nontext',
     re.compile(r'^RC4UP\(nontext\) len=(\d+) b64=(\S*)\s*$'), _f_rc4nontext),
    ('RC4PT', 'rc4_probe', None, re.compile(r'^RC4PT (.+)$'), _f_rc4text),
    ('RC4UP', 'rc4_probe', None, re.compile(r'^RC4UP (.+)$'), _f_rc4text),
    # ── signing / crypto observation (sign_observer, native_probe) ────────────
    ('SIGN_URL', 'sign_observer', None, re.compile(r'^SIGN URL:\s*(\S+)\s*$'), _f_sign_url),
    ('SIGN_PARAMS', 'sign_observer', None, re.compile(r'^SIGN params:\s*(.*)$'), _f_sign_params),
    ('SIGN_RESULT', 'sign_observer', None, re.compile(r'^SIGN result:\s*(.*)$'),
     lambda m: {'value': m.group(1).strip()}),
    ('SIGNPARAM', 'native_probe', None,
     re.compile(r'^SIGNPARAM param=(\S*) sign=(\S*)\s*$'),
     lambda m: {'param': m.group(1), 'sign': m.group(2)}),
    ('FORMULA', 'native_probe', None,
     re.compile(r'^FORMULA A=(\S*) X=(\S*) param=(\S*) sign=(\S*)\s*$'),
     lambda m: {'a': m.group(1), 'x': m.group(2), 'param': m.group(3), 'sign': m.group(4)}),
    # RC4KEYSTR before RC4KEY before RC4 (longest prefix first)
    ('RC4KEYSTR', 'rc4_probe', None,
     re.compile(r'^RC4KEYSTR (?P<key>\S+)(?: \| len=(?P<len>\d+))?\s*$'), _f_rc4key),
    ('RC4KEY', 'sign_observer', None,
     re.compile(r'^RC4KEY b\((?P<ver>[^)]*)\):\s*(?P<key>\S*)\s*$'), _f_rc4key),
    ('RC4KEY', 'sign_observer', 'refreshed',
     re.compile(r'^RC4KEY refreshed:\s*(?P<key>\S*)\s*$'), _f_rc4key),
    ('RC4KEY', 'rc4_probe', None,
     re.compile(r'^RC4KEY (?P<key>\S+)(?: \| len=(?P<len>\d+))?\s*$'), _f_rc4key),
    ('RC4', 'sign_observer', None,
     re.compile(r'^RC4 (encrypt|decrypt) key=b64\[(\d+)\](\S*) in=b64\[(\d+)\](\S*): b64\[(\d+)\](\S*)\s*$'),
     _f_rc4),
    ('NET', 'sign_observer', None,
     re.compile(r'^NET (DECRYPT|ENCRYPT) (in|out):\s*(.*)$'), _f_net),
    ('H5', 'sign_observer', None,
     re.compile(r'^H5 (DECRYPT|ENCRYPT|[notl]) (in|out):\s*(.*)$'), _f_h5),
    # ── bridge observation ────────────────────────────────────────────────────
    ('H5BRIDGE', 'h5_bridge_log', None,
     re.compile(r'^H5BRIDGE (\S+) count=(\d+)\s*(.*)$'), _f_h5bridge),
    ('BRIDGE', 'bridge_action_log', 'download',
     re.compile(r'^BRIDGE downloadMedia type=(-?\d+) url=(.*)$'), _f_bridge_download),
    ('BRIDGE', 'bridge_action_log', 'userinfo',
     re.compile(r'^BRIDGE getuserinfo asked identity=(.*)$'), _f_bridge_userinfo),
    # 页面驱动下单：`payInfo` 的值**不进抓取**（见 BridgeActionLog.recordPayOrder），
    # 所以这里只能解析长度与键名形态 —— 不要幻想能从这里拿到订单内容。
    ('BRIDGE', 'bridge_action_log', 'payorder',
     re.compile(r'^BRIDGE payorder submit len=(\d+) (empty|not-json|keys=\d+:(\S*)) pid=(\S+)\s*$'),
     _f_bridge_payorder),
    ('BRIDGE', 'bridge_action_log', 'decode',
     re.compile(r'^BRIDGE decodeHttpRequest url=(?P<url>\S*) '
                r'shouldDecode=(?P<sd>-?[0-9]+|\?) params=(?P<params>\S+)\s*$'),
     _f_bridge_decode),
    # 页面代发请求的**来源归属**（`page_request_log`，钩 `dr.f.a` 这一个汇聚点）。
    #
    # 为什么用**独立前缀** `PAGEREQ` 而不是 `BRIDGE` 的第 5 个变体：`PREFIX_FEATURE`
    # 由 `setdefault` 派生（一个 token 只能有一个归属功能），而 `BRIDGE` 已经属于
    # `bridge_action_log`。硬塞进去会让两个功能的行混在同一个前缀名下 ——
    # `NoShadowedRule::test_every_kind_has_exactly_one_prefix_owner` 正是拦这个的。
    # 归属清晰比前缀复用重要：grep 一个前缀就恰好对应一个功能。
    ('PAGEREQ', 'page_request_log', None,
     re.compile(r'^PAGEREQ from=(?P<from>\S+) url=(?P<url>\S*) '
                r'params=(?P<params>\S+) method=(?P<meth>-?[0-9]+|\?)\s*$'),
     _f_page_request),
    ('GUARD', 'bridge_guard', None,
     re.compile(r'^GUARD blocked=(\S+) reason=(\S+) url=(\S*?)(?: #(\d+))?\s*$'), _f_guard),
    # ── ads ───────────────────────────────────────────────────────────────────
    # 类名**不写死**：`aj.a.` → `di.a.` 是 7.9.0 的类名重排（R8 把广告配置从 `aj.a` 移到 `di.a`，
    # 而 `aj.a` 这个名字转给了旧的 `bk.a` 会员类）。旧抓取里是 `aj.a`，新抓取里是 `di.a`，
    # 两者都要能解析 —— 写死任一个都会让另一半证据变成 `unknown`。
    ('ADSLOT_CALL', 'ad_probe', None,
     re.compile(r'^ADSLOT call (?P<cls>[\w.]+)\.(?P<method>\w+)\((?P<pos>\d+)\) #(?P<seq>\d+)\s*$'),
     _f_adslot_call),
    ('ADSLOT_RET', 'ad_probe', None,
     re.compile(r'^ADSLOT ret\s+(?P<cls>[\w.]+)\.(?P<method>\w+)\((?P<pos>\d*)\) -> (?P<shown>\S+)\s*$'),
     _f_adslot_ret),
    # 类名不写死（`aj.a` → `di.a` 是 7.9.0 的 R8 重排），尾部 `-> null` **可选**：
    # 2026-11-02 把模块侧这条证据从 `aj.a` 改成真实的 `di.a` 时，顺手去掉了恒为 null 的尾巴，
    # 而这条规则仍要求 `-> (\S+)$` ⇒ 真实抓取里 7 行全部变成 UNKNOWN。
    # 这与 ADSLOT 那次是**同一类漂移**：规则只校验"前缀存在"，不校验"整行形状"。
    ('AD_BLOCK', 'rm_adconfig', None,
     re.compile(r'^blocked ad slot read: (?P<cls>[\w.]+)\.(?P<method>\w+)\((?P<pos>[^)]*)\)'
                r'(?:\s+->\s+(?P<result>\S+))?\s*$'),
     lambda m: {'cls': m.group('cls'), 'method': m.group('method'),
                'pos': m.group('pos'), 'result': m.group('result')}),
    # 拦截成功的证据（2026-11-02 加）。
    #
    # 为什么单独一条：广告面（C1）的判据原来只能数 `ADSLOT`（**读数**），
    # 数不到**拦截**。而"读了 88 次但一次没拦"与"拦了 88 次"是两件完全不同的事 ——
    # 前者说明功能没生效，后者说明生效了。少了这一条，C1 永远只能给"无法验证"。
    ('ADBLOCK', 'rm_adconfig', None,
     re.compile(r'^ADBLOCK (?P<cls>[\w.]+)\.(?P<method>\w+) -> (?P<result>false|true)\s*$'),
     lambda m: {'cls': m.group('cls'), 'method': m.group('method'),
                'result': m.group('result') == 'true'}),
    # ── navigation / routing ──────────────────────────────────────────────────
    ('ROUTE', 'route_log', None,
     re.compile(r'^ROUTE (\S+)(?: (.*?))? \| from=(.*)$'), _f_route),
    ('NAVACT', 'nav_log', 'activity', re.compile(r'^NAVACT (.+)$'), _f_navact),
    ('NAV', 'nav_log', None, re.compile(r'^NAV (.+?)(?: \| (.+))?$'), _f_nav),
    # ── headers / page requests ───────────────────────────────────────────────
    ('HDR', 'req_headers', None,
     re.compile(r'^HDR(?:\((v|static)\))? (.*)$'), _f_hdr),
    ('WEBREQ', 'web_request_log', None,
     re.compile(r'^WEBREQ (\S+)(?: \| (.*))?$'), _f_webreq),
    # ── exit guard ────────────────────────────────────────────────────────────
    ('EXITSTACK', 'exit_guard', None,
     re.compile(r'^EXITSTACK #(\d+) (.*)$'), _f_exitstack),
    ('EXITCALL', 'exit_guard', None,
     re.compile(r'^EXITCALL #(\d+) (.+?) blocked=(true|false)( \(stack suppressed\))?\s*$'),
     _f_exitcall),
    # ── 热修复补丁面（2026-10-25 第 29 轮）─────────────────────────────────────
    # `ROBUST patch lk.f #4dec supported=true redirect=true` —— 哪个方法被补丁接管。
    # 只看"发生过什么"：`supported` 是 `PatchProxyResult.isSupported` 的原值，
    # `redirect` 是 `changeQuickRedirect != null`（false ⇒ 这个类根本没被补丁碰过）。
    # **不是**模块在改宿主：本功能只读，不拦截、不替换。
    ('ROBUST', 'robust_probe', 'patch',
     re.compile(r'^ROBUST patch (?P<who>\S+) #(?P<no>[0-9a-fA-F?]+) '
                r'supported=(?P<supported>true|false|\?) redirect=(?P<redirect>true|false)\s*$'),
     _f_robust_patch),
    ('ROBUST', 'robust_probe', 'stack',
     re.compile(r'^ROBUST stack (?P<who>\S+) #(?P<no>[0-9a-fA-F?]+) (?P<stack>.*)$'),
     _f_robust_stack),
    # ── the three features added 2026-10-25 ───────────────────────────────────
    ('VIP', 'vip_unlock', None, re.compile(r'^VIP (.+)$'),
     lambda m: {'note': m.group(1).strip()}),
    # ── 原生退出守卫的**自证**（2026-11-02，A4）────────────────────────────────
    # `NEXIT installed=True control=False selfTest=1 selfProof=2`
    #
    # 为什么要落一行：seccomp 的 `SECCOMP_RET_ERRNO` 不向用户态回报命中次数，
    # 所以"拦了几次"内核根本不说。旧实现把恒为 0 的 `g_blocked` 当"拦了几次"打印，
    # 那个数字没有含义。现在改成**自证**：装完立刻试一次 `exit_group`，
    # 被 EPERM 否决才算生效（`selfTest=1`），`selfProof` 是自证次数。
    ('NEXIT', 'native_exit_guard', None,
     re.compile(r'^NEXIT installed=(?P<installed>\w+) control=(?P<control>\w+) '
                r'selfTest=(?P<selfTest>-?\d+) selfProof=(?P<selfProof>-?\d+)\s*$'),
     lambda m: {'installed': m.group('installed').lower() == 'true',
                'control': m.group('control').lower() == 'true',
                'selfTest': int(m.group('selfTest')),
                'selfProof': int(m.group('selfProof'))}),
    ('UPDATE', 'skip_update', None,
     re.compile(r'^UPDATE forceUp (?P<before>-?\d+) -> (?P<after>-?\d+)\s*$'), _f_update),
    ('UPDATE', 'skip_update', 'suppressed',
     re.compile(r'^UPDATE suppressed (.+)$'), _f_update),
    # ── 重练额度检查观测（2026-10-25）───────────────────────────────────────────
    # `VIPLIMIT ask product=examRHW used=3`      —— 谁在问、问哪个产品、已用几次
    # `VIPLIMIT result allowed=false remaining=0` —— 回调拿到的判定
    ('VIPLIMIT', 'vip_limit_probe', 'ask',
     re.compile(r'^VIPLIMIT ask product=(?P<product>\S+) used=(?P<used>-?\d+)\s*$'),
     lambda m: {'product': m.group('product'), 'used': int(m.group('used'))}),
    ('VIPLIMIT', 'vip_limit_probe', 'result',
     re.compile(r'^VIPLIMIT result allowed=(?P<allowed>true|false) '
                r'remaining=(?P<remaining>-?\d+)\s*$'),
     lambda m: {'allowed': m.group('allowed') == 'true',
                'remaining': int(m.group('remaining'))}),
    # ── H5 桥**出站**返回值（2026-10-25）───────────────────────────────────────
    # `H5RET postMessage count=3 len=248 {"code":0,...}`
    ('H5RET', 'h5_bridge_log', None,
     re.compile(r'^H5RET (?P<fun>\S+) count=(?P<count>\d+) len=(?P<len>\d+)(?: (?P<body>.*))?$'),
     lambda m: {'cb': m.group('fun'), 'count': int(m.group('count')),
                'len': int(m.group('len')),
                'body': (m.group('body') or '').strip() or None}),
    # ── 网络失败原因（2026-10-25）─────────────────────────────────────────────
    # `NETERR no=-7 code=签名错误 | 请求参数校验失败`
    ('NETERR', 'net_error_probe', None,
     re.compile(r'^NETERR no=(?P<no>-?\d+|\?)'
                r'(?: code=(?P<code>[^|]*?))?'
                r'(?: \| (?P<detail>.*))?\s*$'),
     lambda m: {k: val for k, val in
                (('no', m.group('no')),
                 ('code', (m.group('code') or '').strip() or None),
                 ('detail', (m.group('detail') or '').strip() or None)) if val is not None}),
    # ── onboarding / app log ──────────────────────────────────────────────────
    ('ONBOARD', 'skip_onboarding', None,
     re.compile(r"^ONBOARD clicked='(.*)' label=(\S+) #(\d+) ok=(true|false)\s*$"), _f_onboard),
    # `ONBOARD giveup where="activity X" tries=6 decorReady=true`
    # —— 重试用尽时写的**结论行**。没有它，"没找到引导弹窗"与"功能根本没跑"无法区分；
    # `decorReady` 尤其关键：false 说明重试链曾经因为拿不到 decorView 而断掉过。
    ('ONBOARD', 'skip_onboarding', None,
     re.compile(r'^ONBOARD giveup where="(?P<where>[^"]*)" tries=(?P<tries>\d+) '
                r'decorReady=(?P<decorReady>true|false)\s*$'),
     lambda m: {'where': m.group('where'), 'tries': int(m.group('tries')),
                'decorReady': m.group('decorReady') == 'true'}),
    # `APPSIGN <级别>/<tag>: <msg>` —— 写入侧是 `"$tag: $msg"`（`LogSink.kt:115`）。
    #
    # tag 里**可以含冒号**：`android.util.Log` 的 tag 没有字符白名单，业务代码
    # 出现过 `Some:Tag` 这种写法。旧正则写 `([^:]+):` ⇒ 遇到它就截在第一个冒号，
    # 得到 tag='Some'、msg='Tag: message'：**tag 被截断、msg 被污染**，
    # 而 kind/feature 全都对，所以除了逐字段断言没有别的机制能发现。
    #
    # 分隔符是写入侧拼的那个 `": "`（`LogSink.kt:115` 的 `"$tag: $msg"`），
    # 而 tag 本身可以含冒号（`android.util.Log` 的 tag 无字符白名单）。
    # 两种直觉写法都错，实测过：
    #   `[^:]+`      ⇒ `Some:Tag: m` 得 tag='Some'，msg 被污染成 'Tag: m'
    #   `(.+?)` 惰性 ⇒ 同上（后面 `(.*)$` 贪婪，引擎在第一个可行冒号处就停）
    #   `(.+)`  贪婪 ⇒ 吃到行尾再回溯，得 tag='Some:Tag: message with'、msg='colons'
    # 正确做法：切分点是最后一个 **`:` 后跟空格**，而冒号后不跟空格的（`//x` 那种）
    # 不算分隔符。用一个字符类排除 `": "` 的起点。
    ('APPSIGN', 'log_sink', None,
     re.compile(r'^APPSIGN ([DIWE])/((?:(?!: ).)+): (.*)$'), _f_appsign),
    # ── 家长模式读/写两侧（2026-10-26 第 40 轮新增写侧）──────────────────────
    # 读侧 `PCTRL`：钩 `dj.e.f()`，宿主**当前**认为四个闸门是什么。
    # 写侧 `PCTRLW`：钩 `dj.e.l(ParentCtrlData,int,Callback)`，宿主**正要把**什么提交给
    #   `/kdcore/user/setparentmode`。六个字段是提交时的快照。
    #
    # 为什么必须是两个前缀：`PREFIX_FEATURE` 由 `setdefault` 派生，一个 token 只能归属
    # 一个功能。共用 `PCTRL` 会让"读"与"写"在按功能统计时合成一个数字，而这两个方向
    # 回答的是**相反**的问题 —— 只有读侧时，看到 `aiwriting=0` 分不清是"服务端下发 0"
    # 还是"本地改成 0 等着提交"。两行时间戳一前一后才能把这两件事分开。
    #
    # 写成 `(?:\\?|-?\\d+)` 而不是 `\\d+`：读不到写 `?`，宿主也可能给负数。
    ('PCTRLW', 'parent_ctrl_write', None,
     re.compile(r'^PCTRLW aiwriting=(?P<aiwriting>\?|-?\d+) book=(?P<book>\?|-?\d+) '
                r'correctsearch=(?P<correctsearch>\?|-?\d+) '
                r'picsearch=(?P<picsearch>\?|-?\d+) mask=(?P<mask>0x[0-9a-f]+) '
                r'from=(?P<from>\?|-?\d+) userMode=(?P<userMode>\?|-?\d+)\s*$'),
     _f_parentctrl_write),
    # 注意顺序：`PCTRLW` 在前。解析器按 token **精确匹配**，不是 startsWith，
    # 所以顺序其实无关；但把更长的 token 放前面，将来若有人改成前缀匹配也不会踩坑。
    ('PCTRL', 'parent_ctrl_probe', None,
     re.compile(r'^PCTRL aiwriting=(?P<aiwriting>\?|-?\d+) book=(?P<book>\?|-?\d+) '
                r'correctsearch=(?P<correctsearch>\?|-?\d+) '
                r'picsearch=(?P<picsearch>\?|-?\d+) mask=(?P<mask>0x[0-9a-f]+)\s*$'),
     _f_parentctrl),
    # `PCTRL unavailable reason=null-return` —— 读侧拿到 null 时写的那一行。
    # 它**不是**错误行：`dj.e.f()` 返回 null 本身是信息（可能还没拉到配置）。
    # 单独一条规则而不是并进上面那条：字段完全不同（没有四个闸门），
    # 合并会让 `mask` 恒缺、让"形状"与"为什么没有形状"混成一种记录。
    ('PCTRL', 'parent_ctrl_probe', 'unavailable',
     re.compile(r'^PCTRL unavailable reason=(?P<reason>\S+)\s*$'),
     lambda m: {'reason': m.group('reason')}),
    ('PCTRLW', 'parent_ctrl_write', 'unavailable',
     re.compile(r'^PCTRLW unavailable reason=(?P<reason>\S+)\s*$'),
     lambda m: {'reason': m.group('reason')}),
    # ── watermark (2026-10-25 新增功能 watermark_off) ─────────────────────────
    ('WATERMARK', 'watermark_off', 'off', re.compile(r'^WATERMARK (off .*)$'), _f_watermark),
    # `PROMO blocked dialog show` / `PROMO blocked winVIPBottom` / `PROMO hid membership card view`
    ('PROMO', 'rm_vip_promo', None, re.compile(r'^PROMO (.+)$'), _f_event),
    # `MD3 window themed` / `MD3 native bg neutralised`
    ('MD3', 'md3_skin', None, re.compile(r'^MD3 (.+)$'), _f_event),
    # `SETTINGS entry opened ctx=CommonCacheHybridActivity` — 设置页里那一行被点中，
    # 模块设置页已经起来。后面若被宿主拦（包可见性 / OEM），写 `SETTINGS launch failed ...`，
    # 两种都是 `SETTINGS <一句话>`，事件名一层就够（与 PROMO / MD3 同形）。
    ('SETTINGS', 'settings_entry', None, re.compile(r'^SETTINGS (.+)$'), _f_event),
    # ── 服务端弹窗总闸门（2026-10-25 第 21 轮 popwin_gate）─────────────────────
    # 分派点是 `ei.y.H(String type, ListItem)`，8 个类型全部来自服务端 `/kdapi/conf/popwindow`。
    # 一行三字段，缺一不可：
    #   `type`   服务端下发的是什么（`winAd` / `winUp` / `winActivity_7` …）
    #   `block`  是否命中拦截清单（"本来该不该拦"）
    #   `action` 最终动作（`PASS` / `OBSERVE` / `BLOCK`，"实际做了什么"）
    # `block != blocked` 正是 `observe_only` 生效的证据，合并两列就看不见它了。
    ('POPWIN', 'popwin_gate', None,
     re.compile(r'^POPWIN seen type=(?P<type>\S+) block=(?P<block>true|false) '
                r'action=(?P<action>PASS|OBSERVE|BLOCK)\s*$'), _f_popwin),
    # ── HTTP 请求体 / 响应体（2026-10-25 第 14 轮 http_body_probe）─────────────
    # 四种形态，`text` 与 `bin` 用 variant 区分（同一个 token，body 不同）：
    #   `REQBODY text HWRequest len=248 {"a":1}`      —— getBody() 的字节解出了文本
    #   `REQBODY bin  HWRequest len=20480`            —— 二进制（上传的图片/文件），只记长度
    #   `REQBODY json len=88 {"a":1}`                 —— InputBase.__jsonBody（**加密前**）
    #   `RESPBODY text status=200 len=1024 {"errNo":0`
    #   `RESPBODY bin  status=200 len=65536`
    #   `RESPBODY unreadable fields=a,b,c`            —— volley 字段名变了（明确记，不静默少记）
    ('REQBODY', 'http_body_probe', 'text',
     re.compile(r'^REQBODY text (?P<who>\S+) len=(?P<len>\d+) (?P<body>.*?)(?P<cut>…)?\s*$'),
     _f_bodytext),
    ('REQBODY', 'http_body_probe', 'json',
     re.compile(r'^REQBODY json len=(?P<len>\d+) (?P<body>.*?)(?P<cut>…)?\s*$'),
     lambda m: {'who': None, 'len': int(m.group('len')),
                'body': m.group('body'), 'truncated': bool(m.group('cut'))}),
    #   `REQBODY params Popwincontent$Input n=29 a=1&b=2 …+5`
    #   —— `volley.v.getParams()` 的表单参数（**绝大多数请求的 body 在这里，
    #      而不是 `getJsonBody`**：`__jsonBody` 全 APK 只有两处写入，
    #      `JsonInput` 只被 new 一次，其余恒为 `"{}"`）。
    ('REQBODY', 'http_body_probe', 'params',
     re.compile(r'^REQBODY params (?P<who>\S+) n=(?P<n>\d+)(?: (?P<kv>.*?))?(?P<more> …\+\d+)?\s*$'),
     lambda m: {'who': m.group('who'), 'n': int(m.group('n')),
                'kv': (m.group('kv') or '').strip() or None,
                'omitted': int(m.group('more').strip().lstrip('…+')) if m.group('more') else 0}),
    ('REQBODY', 'http_body_probe', 'bin',
     re.compile(r'^REQBODY bin (?P<who>\S+) len=(?P<len>\d+)\s*$'),
     lambda m: {'who': m.group('who'), 'len': int(m.group('len')), 'body': None}),
    ('RESPBODY', 'http_body_probe', 'text',
     re.compile(r'^RESPBODY text status=(?P<status>\d+|\?) len=(?P<len>\d+) '
                r'(?P<body>.*?)(?P<cut>…)?\s*$'), _f_resptext),
    ('RESPBODY', 'http_body_probe', 'bin',
     re.compile(r'^RESPBODY bin status=(?P<status>\d+|\?) len=(?P<len>\d+)\s*$'),
     lambda m: {'status': int(m.group('status')) if m.group('status') != '?' else '?',
                'len': int(m.group('len')), 'body': None}),
    ('RESPBODY', 'http_body_probe', 'unreadable',
     re.compile(r'^RESPBODY unreadable fields=(?P<fields>.*)$'),
     lambda m: {'fields': [f for f in m.group('fields').split(',') if f]}),
    # ── session marker (Capture.mark) ─────────────────────────────────────────
    ('MARK', None, None, re.compile(r'^=== (.+)$'), _f_mark),
)

# Prefix token -> (kind, feature). Derived from RULES so it cannot drift; used by the
# module-side gate that proves every prefix a Kotlin file writes is known here.
PREFIX_FEATURE = {}
for _kind, _feature, _variant, _rx, _ in RULES:
    PREFIX_FEATURE.setdefault(_kind, _feature)

# ── variants ──────────────────────────────────────────────────────────────────
# A *kind* is the prefix token; a *variant* is the second thing a consumer branches on.
# Most variants are declared by the rule table, but two kinds decide theirs inside the field
# builder (`_f_hdr`, `_f_update`) because the token is identical and only the body differs:
#
#     HDR host/api :: X-Sign=…          -> 'request'
#     HDR(v) host/api :: X-Sign=…       -> 'v'
#     HDR(static) Content-Type=…        -> 'static'
#     UPDATE forceUp 1 -> 0             -> 'forceup'
#     UPDATE suppressed <why>           -> 'suppressed'
#
# Those are listed here explicitly instead of being invisible, so a consumer that branches on
# `variant` can be gated: `tests/test_capture_schema.py::VariantCoverage` requires a fixture
# line for **every** pair below. Before this table existed, `HDR/request` and `UPDATE/forceup`
# had no sample at all — a rendering branch nobody had ever executed.
DERIVED_VARIANTS = {
    'HDR': ('request', 'v', 'static'),
    'UPDATE': ('forceup', 'suppressed'),
    # `REQBODY` / `RESPBODY` 的 variant 由规则表直接声明（text / json / bin / unreadable），
    # 不需要在这里补 —— 加到这张表里的只有"token 相同、形状靠 builder 判"的那些。
}

VARIANTS: dict = {}
for _kind, _feature, _variant, _rx, _ in RULES:
    if _variant:
        VARIANTS.setdefault(_kind, set()).add(_variant)
for _kind, _vs in DERIVED_VARIANTS.items():
    VARIANTS.setdefault(_kind, set()).update(_vs)
VARIANTS = {k: tuple(sorted(v)) for k, v in VARIANTS.items()}

VARIANT_PAIRS = tuple(sorted((k, v) for k, vs in VARIANTS.items() for v in vs))

# ── tagged lines ──────────────────────────────────────────────────────────────
# A few features write their own name in front of the record:
#
#     NativeProbe SIGNPARAM param=… sign=…          (NativeProbe.capture)
#     NativeProbe FORMULA A=… X=… param=… sign=…
#
# This is real and appears throughout `work/dpsdk/*.txt`, so it is part of the format, not
# an accident: the tag lets `grep NativeProbe` find them. It is resolved *before* the rule
# table so `SIGNPARAM` still lands on the `native_probe` feature with its fields intact, and
# the tag is preserved in `fields['tag']` for anyone who needs the raw shape.
TAGGED = {
    'NativeProbe': 'native_probe',
}
TAG_RE = re.compile(r'^(%s) (.+)$' % '|'.join(TAGGED))

# Some first tokens are **not** one-to-one with a kind: one prefix spawns two record shapes,
# or the variant lives inside the token rather than after it. The module writes those tokens
# verbatim, so they have to be recognised as "declared" or the drift gate would have to
# special-case them (which is how loopholes start). Each entry must point at a real kind.
TOKEN_KINDS = {
    'ADSLOT': ('ADSLOT_CALL', 'ADSLOT_RET'),   # `ADSLOT call …` / `ADSLOT ret  …`
    'HDR(v)': ('HDR',),                        # variant is in the token
    'HDR(static)': ('HDR',),
}


def known_token(token: str) -> bool:
    """Is this first word (as written by the module) covered by the schema?"""
    return (token in PREFIX_FEATURE or token in TOKEN_KINDS or token in TAGGED)

# Which features are expected to leave trace in the capture at all, and which are
# logcat-only by design. Both are derived, never hand-maintained:
#   * FEATURES_WITH_CAPTURE  = every feature some rule can attribute a line to;
#   * FEATURES_LOGCAT_ONLY   = the rest (ad remover hooks, anti-detect, seccomp guard,
#                              PK assist, page-JS injection) — they change behaviour or
#                              log via KdLog and never call Capture.append.
# `module/ACTIVITY.md` counts both clusters separately, which is why the split lives here.
FEATURES_WITH_CAPTURE = tuple(sorted({f for _k, f, _v, _r, _b in RULES if f}))
FEATURES_LOGCAT_ONLY = tuple(f for f in FEATURE_IDS if f not in FEATURES_WITH_CAPTURE)


# ── UNKNOWN 行的归类 ───────────────────────────────────────────────────────────
#
# "UNKNOWN" 原本只有一种声音："新前缀没登记，或该行被截断"。但实测（`work/activity_inputs/`
# 5 份冻结抓取）564 行 UNKNOWN 里，**526 行是同一张 PEM 证书的 base64 续行**、
# 17 行是 `-----BEGIN/END CERTIFICATE-----`、只剩 21 行是"短 base64 片段"（`Un7cTl4=` 之类）。
#
# 这不是小事：告警的价值在于"出现新东西"，而 564 行噪声会让它变成背景。更糟的是
# `ACTIVITY.md` 的「按前缀分布」里 `UNKNOWN` 长期排在第四位，读起来像"模块在写未知格式"。
#
# 因此只做**归类**，不改解析结果（`kind` 仍是 UNKNOWN，raw 仍逐字保留）：
#   * `legacy-wrap`  —— 2026-10-25 之前写入侧没有 `⏎` 压平，一条带换行的记录被读成 N 行；
#                      只在旧抓取里出现，新构建不可能再产生（`CapturePolicy.oneLine`）。
#   * `truncated`    —— 行尾被轮转/上限切断，属于正常采集形态。
#   * `new-prefix`   —— 首词是 `[A-Z][A-Z0-9_]{2,}`，才真的可能是未登记的新前缀。
#   * `unknown`      —— 都不匹配，需要人看一眼。
_PEM_MARK_RE = re.compile(r'^-----(BEGIN|END) [A-Z0-9 ]+-----$')
_B64_RE = re.compile(r'^[A-Za-z0-9+/]+={0,2}$')
_NEW_PREFIX_RE = re.compile(r'^\$*([A-Z][A-Z0-9_]{2,})(?:[ (:]|$)')

UNKNOWN_LEGACY_WRAP = 'legacy-wrap'   # 旧抓取里被换行撑开 / 被 base64 续行污染的残留
UNKNOWN_TRUNCATED = 'truncated'
UNKNOWN_NEW_PREFIX = 'new-prefix'     # ← 唯一需要立刻处理的类别
UNKNOWN_OTHER = 'unknown'


def classify_unknown(raw: str) -> str:
    """把一条没有规则认领的行归到四类之一。只看形状，不改任何解析结果。"""
    body = raw
    m = TS_RE.match(raw)
    if m:
        body = m.group(2)
    body = body.rstrip('\r').strip()
    if not body:
        return UNKNOWN_OTHER
    if _PEM_MARK_RE.match(body):
        return UNKNOWN_LEGACY_WRAP
    # 纯 base64 续行：**不含空格**、长度 ≥ 20、字符集属于 base64。
    # 这三条同时成立时不可能是一条 `PREFIX body` 记录（后者必有空格分隔），
    # 所以这样归类不会掩盖真正的新前缀；`Un7cTl4=`（8 字符）这种碎片另按含 `=` 判。
    if ' ' not in body and _B64_RE.match(body) and (
            len(body) >= 20 or '=' in body or '+' in body or '/' in body):
        return UNKNOWN_LEGACY_WRAP
    toks = body.split(' ', 1)
    if toks and _NEW_PREFIX_RE.match(body):
        # 像 `FOO ...` / `FOO(...) ...` / `FOO: ...` 的未知大写词 —— 可能是新前缀。
        # 不设长度上限：`FUTUREKIND`（10 字符）正是这条分类要抓的形态，
        # 而密文/证书续行首字符后面必然跟着小写字母，不会命中这个正则。
        return UNKNOWN_NEW_PREFIX
    if body.endswith(('…', '...')) or '…(' in body:
        return UNKNOWN_TRUNCATED
    return UNKNOWN_OTHER


def _rule_rx(kind):
    """从 `RULES` 里取出某个 kind 的正则 —— **不另写第二个**。"""
    for k, _feat, _var, rx, _fn in RULES:
        if k == kind:
            return rx
    raise KeyError(kind)


#: `APPSIGN` 的 `msg` 会带一层 `[KdKit] ` 前缀（写入侧见 `LogSink.kt`）。
_RELAY_PREFIX = re.compile(r'^\[KdKit\] (.*)$')

#: 日志中继会截断长消息，尾巴上留一个 ` …(原长度)`。
#:
#: 实测 `work/packs/api_health/capture.txt` 里中继形态的 45 条 `SIGN URL`
#: **全部**带这个尾巴 —— 也就是说旧写法（`split(' SIGN URL: ')`）
#: 返回的 90 条里有 45 条是**被截断的 URL**：query 里嵌着 ` …(719)`。
#: `urlparse` 仍然给出正确的 path（截断落在 query 里），所以下游
#: `params_of(path)` 会照常匹配 —— **然后拿一个坏 URL 去发请求**。
_TRUNC_MARK = re.compile(r' …\(\d+\)$')


def sign_urls_truncated(source):
    """中继形态里**被截断**的 `SIGN URL` 条数 —— 它们不进 `sign_urls`。

    单独暴露出来，是为了让"少了一些"这件事**可见**：
    静默丢数据与静默报成功是同一类错误。
    """
    n = 0
    for rec in _records_or_lines(source):
        if getattr(rec, 'kind', None) != 'APPSIGN':
            continue
        m = _RELAY_PREFIX.match(rec.fields.get('msg') or '')
        if not m:
            continue
        body = m.group(1).strip()
        if body.startswith('SIGN URL:') and _TRUNC_MARK.search(body):
            n += 1
    return n


def sign_urls(source):
    r"""抓取里的全部 `SIGN URL` 值 —— **唯一实现**（2026-11-04 收敛，代码审查 P2）。

    旧实现在**三处**各写一遍：

        urls = [l.split(' SIGN URL: ', 1)[1].strip() for l in lines if ' SIGN URL: ' in l]

    （`extract_samples.py` / `export_content.py` / `probe_paths.py`）

    那种写法与 `RULES` 里的 `SIGN_URL` 规则**不是同一个契约**，但**覆盖面更宽**：
    它同时认下了 `APPSIGN I/VectorLegacyBridge: [KdKit] SIGN URL: …` 这种
    **经 logcat 中继**的形态。

    实测 `work/packs/api_health/capture.txt`：
    直接形态 45 条、中继形态 45 条，**只有 15 个 URL 重叠** —— 也就是说
    两种形态各自都带来了独有的 URL。第一版 `sign_urls` 只认直接形态，
    于是同一份抓取从 90 条掉到 45 条：**一个"收敛重复实现"的重构
    静默丢掉了一半数据。** 这就是为什么重构之后必须逐包对比新旧输出。

    现在两种形态都走 `RULES` 里那**同一个** `SIGN_URL` 正则：
    直接形态由 `parse_line` 认，中继形态把 `[KdKit] ` 前缀剥掉再交给同一个正则。

    `source` 可以是路径（`.txt` / `.txt.gz` 都认）、也可以是 `Record` 的可迭代对象。
    """
    rx = _rule_rx('SIGN_URL')
    out = []
    for rec in _records_or_lines(source):
        kind = getattr(rec, 'kind', None)
        url = None
        if kind == 'SIGN_URL':
            url = rec.fields.get('url')
        elif kind == 'APPSIGN':
            m = _RELAY_PREFIX.match(rec.fields.get('msg') or '')
            if m:
                body = m.group(1).strip()
                if _TRUNC_MARK.search(body):
                    continue      # 截断的 URL 不进结果（见 `_TRUNC_MARK` 注释）
                mm = rx.match(body)
                if mm:
                    url = mm.group(1).strip()
        if url:
            out.append(url)
    return out


def _records_or_lines(source):
    """把三种输入统一成 `Record` 流。

    三种输入都是**真实调用方**在用的形态，缺一个就会静默返回空 list：

    * 路径（`str`/`bytes`/`PathLike`）—— `.txt` / `.txt.gz` 都认；
    * `Record` 的可迭代 —— `iter_records(...)` 的结果；
    * `str` 行的可迭代 —— `textio.read_lines(...)` 的结果
      （`extract_samples` / `probe_paths` 就是这么调的）。

    **第一版只做了前两种**，而两个真实调用方恰好给的是第三种 ⇒
    测试里 `sign_urls([DIRECT])` 返回空 list。三条用例当场红，
    这正是为什么"新函数要配一条用真实调用形态的用例"。
    """
    if isinstance(source, (str, bytes, os.PathLike)):
        yield from iter_records(source)
        return
    for item in source:
        if isinstance(item, Record):
            yield item
        elif isinstance(item, bytes):
            yield parse_line(item.decode('utf-8', 'replace'))
        elif isinstance(item, str):
            yield parse_line(item)
        else:
            yield item


def parse_line(line: str) -> Record:
    """Parse one capture line. Never raises; unclaimed lines come back as kind='UNKNOWN'."""
    raw = line.rstrip('\n')
    ts = None
    body = raw
    m = TS_RE.match(raw)
    if m:
        ts, body = m.group(1), m.group(2)
    body = body.rstrip('\r').strip()
    tag = None
    tm = TAG_RE.match(body)
    if tm:
        tag, body = tm.group(1), tm.group(2)
    for kind, feature, variant, rx, build in RULES:
        hit = rx.match(body)
        if hit is None:
            continue
        try:
            fields = build(hit)
        except (IndexError, ValueError, AttributeError, KeyError) as exc:
            # A builder bug must be *visible* (it would otherwise look like "this capture
            # simply has no such line"). Keep the kind, drop the fields, and say why.
            fields = {'_builder_error': f'{type(exc).__name__}: {exc}'}
        if tag:
            fields.setdefault('tag', tag)
        # A variant declared by the rule owns the record; a rule with variant=None keeps
        # whatever the builder decided (e.g. UPDATE's two shapes, HDR's three).
        got_variant = fields.get('variant', variant) if variant is None else variant
        return Record(raw=raw, ts=ts, kind=kind, feature=feature,
                      variant=got_variant, fields=fields)
    return Record(raw=raw, ts=ts, kind='UNKNOWN', feature=None, variant=None,
                  fields={'reason': classify_unknown(raw)})


def iter_records(path: str) -> Iterator[Record]:
    """Stream parsed records; blank lines are skipped, bad lines become UNKNOWN.

    **`.gz` 走 `textio`**（2026-11-03 修）：原来直接 `open(path)`，
    于是 `*.txt.gz` 被抓取被当成 gzip 的二进制字节读进来 ——
    **每一行都解析成 UNKNOWN**（实测 `r793/capture.txt.gz`：542/542）。

    后果不是“少读一半”，而是**整份抓取变成噪声**：
    任何按 kind 统计的工具都会显示“这个包里什么都没有”，
    而真相是“这个包被 pack_slim 压过了”。

    这是 `.gz` 盲区这一类缺陷里最严重的一处 —— 前面几处
    （`probe_paths` / `pageapi` / 三个 `--captures` 默认值）只是漏读，
    这里是**全量误读**。
    """
    from textio import read_text
    for line in read_text(path).splitlines():
        if not line.strip():
            continue
        yield parse_line(line)


def parse_text(text: str) -> Iterator[Record]:
    for line in text.splitlines():
        if not line.strip():
            continue
        yield parse_line(line)


def count_kinds(records: Iterable[Record]) -> Counter:
    return Counter(r.kind for r in records)


def count_features(records: Iterable[Record]) -> Counter:
    c = Counter()
    for r in records:
        if r.feature:
            c[r.feature] += 1
    return c


def group_by_feature(records: Iterable[Record]) -> dict:
    out = defaultdict(list)
    for r in records:
        if r.feature:
            out[r.feature].append(r)
    return dict(out)


def summarise(path: str) -> dict:
    """Everything the docs/CLI want, in one pass: kinds, features, span, unknown lines."""
    kinds, features = Counter(), Counter()
    unknown, first_ts, last_ts, n = [], None, None, 0
    unknown_reasons = Counter()
    for rec in iter_records(path):
        n += 1
        kinds[rec.kind] += 1
        if rec.feature:
            features[rec.feature] += 1
        if rec.kind == 'UNKNOWN':
            unknown.append(rec.raw)
            unknown_reasons[rec.get('reason') or UNKNOWN_OTHER] += 1
        if rec.ts:
            first_ts = first_ts or rec.ts
            last_ts = rec.ts
    return {
        'lines': n,
        'kinds': dict(kinds),
        'features': dict(features),
        'unknown': unknown,
        'unknown_reasons': dict(unknown_reasons),
        'span': [first_ts, last_ts] if first_ts else None,
    }


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('capture')
    ap.add_argument('--unknown', action='store_true', help='list lines no rule claimed')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv[1:])

    s = summarise(a.capture)
    print(f'[schema] {a.capture}: {s["lines"]} line(s)'
          + (f', span {s["span"][0]} → {s["span"][1]}' if s['span'] else ''))
    print('\nkind                        count   feature')
    for k, v in sorted(s['kinds'].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  {k:24s} {v:7d}   {PREFIX_FEATURE.get(k) or "-"}')
    print('\nfeature                     count')
    for k, v in sorted(s['features'].items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'  {k:24s} {v:7d}')
    absent = [f for f in FEATURE_IDS if f in FEATURES_WITH_CAPTURE and f not in s['features']]
    print(f'\n[schema] {len(s["features"])}/{len(FEATURES_WITH_CAPTURE)} capturable feature(s) '
          f'appear in this file')
    print(f'[schema] declared but absent here: {", ".join(absent) or "none"}')
    print(f'[schema] logcat-only by design (no capture rule): '
          f'{", ".join(FEATURES_LOGCAT_ONLY)}')
    if s['unknown']:
        reasons = s['unknown_reasons']
        # 只有 `new-prefix` 是"需要立刻处理"的信号；其余是旧抓取/截断的正常形态。
        # 把三类分开说，是为了让 564 行 PEM 续行不再把这一行变成背景噪声。
        print(f'[schema] {len(s["unknown"])} UNKNOWN line(s) — '
              + ', '.join(f'{k}={v}' for k, v in sorted(reasons.items())))
        if reasons.get(UNKNOWN_NEW_PREFIX):
            print(f'[schema] ⚠ {reasons[UNKNOWN_NEW_PREFIX]} 行首词像**未登记的前缀** '
                  f'⇒ 要么在 RULES 里补规则，要么确认它不该被解析')
        else:
            print('[schema] 没有疑似新前缀：其余都是旧抓取被换行撑开的残留（legacy-wrap）或截断行')
        if a.unknown:
            for u in s['unknown'][:40]:
                print(f'  ? {u[:160]}')
    if a.json:
        json.dump(s, open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'[schema] -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
