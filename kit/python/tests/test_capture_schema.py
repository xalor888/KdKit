#!/usr/bin/env python3
"""
Offline unit tests for `kit/python/capture_schema.py` — the declaration of the module's
capture line format.

Run (no device, no network, no pytest needed):

    python3 -m unittest discover -s kit/python/tests -v

What is asserted here, and why each matters:

* **every documented prefix parses** — the table must not silently lose a record type;
* **longest-prefix-first ordering** — `RC4PT(nontext)` must not be read as a plaintext
  `RC4PT`, `RC4KEYSTR` must not be read as `RC4KEY`, `HDR(v)` must keep its variant;
* **truncation tolerance** — a capture pulled while the app is still appending ends in a
  half-written line; that line must not make the whole file unparseable;
* **no timestamp** — hand-trimmed snippets (what `NEW_TARGETS.md` quotes) must still parse;
* **UNKNOWN is preserved verbatim** — the whole point of the rewrite: a new prefix shows up
  instead of vanishing;
* **the Kotlin side writes nothing we cannot parse** — `CAPTURE_PREFIXES` below is the list
  of literal prefixes the module emits; the last test greps the Kotlin sources and fails if
  a new one appears that the schema does not know. That is the actual drift guard.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_PY = os.path.dirname(HERE)
sys.path.insert(0, KIT_PY)

import capture_schema as cs  # noqa: E402

FIXTURE = os.path.join(HERE, 'fixtures', 'all_prefixes.txt')
MODULE_DIR = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'module'))
MODULE_SRC = os.path.abspath(
    os.path.join(HERE, '..', '..', '..', 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit'))


class ParseEveryPrefix(unittest.TestCase):
    """One case per prefix the module can write."""

    CASES = [
        # (line, expected kind, expected feature, expected variant, field assertions)
        ('16:42:15.543 RC4KEY b(1811): b2674b28',
         'RC4KEY', 'sign_observer', None, {'key': 'b2674b28', 'version': '1811'}),
        ('16:42:15.544 RC4KEY refreshed: b2674b28',
         'RC4KEY', 'sign_observer', 'refreshed', {'key': 'b2674b28'}),
        ('16:42:15.545 RC4KEYSTR 0123456789abcdef | len=16',
         'RC4KEYSTR', 'rc4_probe', None, {'key': '0123456789abcdef', 'length': 16}),
        ('16:42:15.546 RC4KEY deadbeef | len=4',
         'RC4KEY', 'rc4_probe', None, {'key': 'deadbeef', 'length': 4}),
        ('16:42:15.603 SIGN params: _t_=1 | abis=1 | vc=1811',
         'SIGN_PARAMS', 'sign_observer', None, {'count': 3}),
        ('16:42:15.604 SIGN result: abc123',
         'SIGN_RESULT', 'sign_observer', None, {'value': 'abc123'}),
        ('16:42:15.610 SIGNPARAM param=YWJj sign=9f8e',
         'SIGNPARAM', 'native_probe', None, {'param': 'YWJj', 'sign': '9f8e'}),
        ('16:42:15.611 FORMULA A=k1 X=k2 param=YWJj sign=9f8e',
         'FORMULA', 'native_probe', None, {'a': 'k1', 'x': 'k2'}),
        ('16:42:15.908 NET DECRYPT in: com.x.Model@1',
         'NET', 'sign_observer', None, {'op': 'DECRYPT', 'dir': 'in'}),
        ('16:42:15.910 H5 n out: {"a":1}',
         'H5', 'sign_observer', None, {'prim': 'n', 'dir': 'out'}),
        ('16:42:15.912 H5BRIDGE downloadMedia count=1 {"type":"1"}',
         'H5BRIDGE', 'h5_bridge_log', None, {'action': 'downloadMedia', 'count': 1}),
        ('16:42:15.914 BRIDGE downloadMedia type=1 url=https://cdn/a.jpg',
         'BRIDGE', 'bridge_action_log', 'download', {'type': 1, 'url': 'https://cdn/a.jpg'}),
        ('16:42:15.930 BRIDGE getuserinfo asked identity=student_42',
         'BRIDGE', 'bridge_action_log', 'userinfo', {'identity': 'student_42'}),
        # 页面驱动下单（第 28 轮）。三种形态都要能认出：值是**键名摘要**，从不落值。
        ('16:42:15.935 BRIDGE payorder submit len=48 keys=2:goodsId,price pid=vip',
         'BRIDGE', 'bridge_action_log', 'payorder',
         {'len': 48, 'shape': 'keys', 'keys': ['goodsId', 'price'], 'pid': 'vip'}),
        ('16:42:15.936 BRIDGE payorder submit len=0 empty pid=vip',
         'BRIDGE', 'bridge_action_log', 'payorder',
         {'len': 0, 'shape': 'empty', 'keys': [], 'pid': 'vip'}),
        ('16:42:15.937 BRIDGE payorder submit len=9 not-json pid=vip',
         'BRIDGE', 'bridge_action_log', 'payorder',
         {'len': 9, 'shape': 'not-json', 'keys': None, 'pid': 'vip'}),
        # 页面借宿主签名手代发请求（2026-10-26 第 31 轮）。`shouldDecode` 三态：
        # 缺键时宿主填 -1 且不发请求 ⇒ `?`（没传）与 `-1`/`0` 是不同路径，不能合并。
        ('16:42:15.938 BRIDGE decodeHttpRequest url=api.example.com/kdapi/x '
         'shouldDecode=1 params=keys=2:page,size',
         'BRIDGE', 'bridge_action_log', 'decode',
         {'url': 'api.example.com/kdapi/x', 'shouldDecode': 1, 'params': 'keys=2:page,size'}),
        ('16:42:15.939 BRIDGE decodeHttpRequest url=(empty) shouldDecode=? params=not-object',
         'BRIDGE', 'bridge_action_log', 'decode',
         {'url': '(empty)', 'shouldDecode': None, 'params': 'not-object'}),
        ('16:42:15.940 PAGEREQ from=EncryptDataRequestAction '
         'url=api.example.com/kdapi/y params=keys=2:page,size method=1',
         'PAGEREQ', 'page_request_log', None,
         {'action': 'pageRequest', 'from': 'EncryptDataRequestAction',
          'url': 'api.example.com/kdapi/y', 'params': 'keys=2:page,size', 'method': 1}),
        ('16:42:15.941 PAGEREQ from=(unknown) url=(empty) params=not-object method=?',
         'PAGEREQ', 'page_request_log', None,
         {'action': 'pageRequest', 'from': '(unknown)',
          'url': '(empty)', 'params': 'not-object', 'method': None}),
        ('16:42:15.940 GUARD blocked=core_showDebuger reason=blacklist url= #1',
         'GUARD', 'bridge_guard', None, {'action': 'core_showDebuger', 'reason': 'blacklist', 'seq': 1}),
        ('16:42:16.000 ADSLOT call aj.a.d(3) #1',
         'ADSLOT_CALL', 'ad_probe', None, {'method': 'd', 'pos': 3, 'seq': 1}),
        # 无参布尔变体（`j()` / `k()`）：`pos` 为空 ⇒ 必须是 None 而不是 0
        ('16:42:16.004 ADSLOT ret  di.a.j() -> false',
         'ADSLOT_RET', 'ad_probe', None, {'cls': 'di.a', 'method': 'j', 'pos': None, 'shown': 'false'}),
        ('16:42:16.001 ADSLOT ret  aj.a.d(3) -> false',
         'ADSLOT_RET', 'ad_probe', None, {'method': 'd', 'shown': 'false'}),
        ('16:42:16.002 blocked ad slot read: aj.a.f(7) -> null',
         'AD_BLOCK', 'rm_adconfig', None, {'method': 'f', 'pos': '7'}),
        # 拦截成功的证据（2026-11-02 加）：没有这一条时，广告面只能数"读数"，
        # 数不到"拦截"，于是 C1 永远给"无法验证"。
        ('16:42:16.030 ADBLOCK di.a.j -> false',
         'ADBLOCK', 'rm_adconfig', None, {'cls': 'di.a', 'method': 'j', 'result': False}),
        ('16:42:16.031 ADBLOCK di.a.k -> true',
         'ADBLOCK', 'rm_adconfig', None, {'cls': 'di.a', 'method': 'k', 'result': True}),
        ('16:42:16.010 ROUTE zyb://webview/main abc123 | from=com.x.MainActivity.onCreate',
         'ROUTE', 'route_log', None,
         {'route': 'zyb://webview/main', 'arg': 'abc123', 'from': 'com.x.MainActivity.onCreate'}),
        ('16:42:16.020 NAV index.html | https://www.kuaiduizuoye.com/h5/index.html',
         'NAV', 'nav_log', None, {'page': 'index.html'}),
        ('16:42:16.021 NAVACT MainActivity',
         'NAVACT', 'nav_log', 'activity', {'activity': 'MainActivity'}),
        ('16:42:16.030 HDR(static) Content-Type=application/json | User-Agent=kd/7.7.2',
         'HDR', 'req_headers', 'static',
         {'variant': 'static',
          'fields': {'Content-Type': 'application/json', 'User-Agent': 'kd/7.7.2'}}),
        ('16:42:16.031 HDR(v) host/api :: X-Sign=abc | _t_=1',
         'HDR', 'req_headers', 'v', {'variant': 'v', 'target': 'host/api'}),
        ('16:42:16.032 HDR host/api :: X-Sign=def',
         'HDR', 'req_headers', 'request', {'variant': 'request', 'target': 'host/api'}),
        ('16:42:16.040 WEBREQ https://cdn/app.js',
         'WEBREQ', 'web_request_log', None, {'url': 'https://cdn/app.js', 'headers': ''}),
        ('16:42:16.050 EXITCALL #1 com.byazt.a.b.run() blocked=true',
         'EXITCALL', 'exit_guard', None,
         {'seq': 1, 'where': 'com.byazt.a.b.run()', 'blocked': True, 'stack_suppressed': False}),
        ('16:42:16.060 EXITCALL #41 com.byazt.a.c.run() blocked=false (stack suppressed)',
         'EXITCALL', 'exit_guard', None, {'seq': 41, 'blocked': False, 'stack_suppressed': True}),
        ('16:42:16.051 EXITSTACK #1 java.lang.System.exit(System.java:1)',
         'EXITSTACK', 'exit_guard', None, {'seq': 1}),
        # ── 热修复补丁面（第 29 轮 robust_probe）───────────────────────────────
        # `supported` 三态：true（这次真被接管）/ false（有分派器但这次没接管）/
        # None（读不到 —— 用 `?` 表示"不知道"，绝不能默认成 false）。
        ('16:42:16.070 ROBUST patch lk.f #4dec supported=false redirect=false',
         'ROBUST', 'robust_probe', 'patch',
         {'who': 'lk.f', 'method_no': '4dec', 'supported': False, 'redirect': False}),
        ('16:42:16.071 ROBUST patch com.kuaiduizuoye.scan.web.actions.FetchPayInfosAction'
         ' #51fe supported=true redirect=true',
         'ROBUST', 'robust_probe', 'patch',
         {'who': 'com.kuaiduizuoye.scan.web.actions.FetchPayInfosAction',
          'method_no': '51fe', 'supported': True, 'redirect': True}),
        # 静态方法拿不到 `this` ⇒ 序号写成 `?`；`supported` 也可能是 `?`。
        ('16:42:16.072 ROBUST patch com.x.Y #? supported=? redirect=true',
         'ROBUST', 'robust_probe', 'patch',
         {'who': 'com.x.Y', 'method_no': '?', 'supported': None, 'redirect': True}),
        ('16:42:16.073 ROBUST stack lk.f #4dec AntiDebugThread.run <- Thread.run',
         'ROBUST', 'robust_probe', 'stack',
         {'who': 'lk.f', 'method_no': '4dec', 'stack': 'AntiDebugThread.run <- Thread.run'}),
        ('16:42:16.120 H5RET postMessage count=3 len=248 {"code":0}',
         'H5RET', 'h5_bridge_log', None,
         {'cb': 'postMessage', 'count': 3, 'len': 248, 'body': '{"code":0}'}),
        ('16:42:16.121 H5RET void count=1 len=4 null',
         'H5RET', 'h5_bridge_log', None,
         {'cb': 'void', 'count': 1, 'len': 4, 'body': 'null'}),
        ('16:42:16.115 NETERR no=-7 code=签名错误 | 请求失败',
         'NETERR', 'net_error_probe', None,
         {'no': '-7', 'code': '签名错误', 'detail': '请求失败'}),
        ('16:42:16.116 NETERR no=0',
         'NETERR', 'net_error_probe', None, {'no': '0'}),
        # ── HTTP 请求体 / 响应体（2026-10-25 第 14 轮 http_body_probe）────────────
        # 六种形态各一条：`text` 有内容、`bin` 只有长度、`unreadable` 是字段名变了，
        # 请求体又分 `getBody()`（编码后）与 `__jsonBody`（**加密前**）。
        ('16:42:16.200 REQBODY text HWRequest len=248 {"a":1}',
         'REQBODY', 'http_body_probe', 'text',
         {'who': 'HWRequest', 'len': 248, 'body': '{"a":1}', 'truncated': False}),
        ('16:42:16.201 REQBODY bin HWRequest len=20480',
         'REQBODY', 'http_body_probe', 'bin',
         {'who': 'HWRequest', 'len': 20480, 'body': None}),
        ('16:42:16.202 REQBODY json len=88 {"a":1}',
         'REQBODY', 'http_body_probe', 'json',
         {'who': None, 'len': 88, 'body': '{"a":1}', 'truncated': False}),
        # 表单参数：**绝大多数请求的真实 body 在这里**（不是 `__jsonBody`）
        # volley 侧请求头带业务域（2026-10-25）。三种情况必须可区分：
        #   缺 `pid` 键 = 旧格式；`pid='-'` = 读取失败；其余 = 真实业务域。
        ('16:42:16.210 HDR(v) host/cube pid=cube :: A=1',
         'HDR', 'req_headers', 'v',
         {'variant': 'v', 'pid': 'cube', 'target': 'host/cube', 'fields': {'A': '1'}}),
        ('16:42:16.211 HDR(v) host/x pid=- :: A=1',
         'HDR', 'req_headers', 'v',
         {'variant': 'v', 'pid': '-', 'target': 'host/x', 'fields': {'A': '1'}}),
        ('16:42:16.212 HDR(v) host/old :: A=1',
         'HDR', 'req_headers', 'v',
         {'variant': 'v', 'target': 'host/old', 'fields': {'A': '1'}}),
        ('16:42:16.204 REQBODY params Popwincontent$Input n=29 a=1&b=2 …+5',
         'REQBODY', 'http_body_probe', 'params',
         {'who': 'Popwincontent$Input', 'n': 29, 'kv': 'a=1&b=2', 'omitted': 5}),
        ('16:42:16.205 REQBODY params X n=1 onlykey',
         'REQBODY', 'http_body_probe', 'params',
         {'who': 'X', 'n': 1, 'kv': 'onlykey', 'omitted': 0}),
        ('16:42:16.203 RESPBODY text status=200 len=1024 {"errNo":0}',
         'RESPBODY', 'http_body_probe', 'text',
         {'status': 200, 'len': 1024, 'body': '{"errNo":0}', 'truncated': False}),
        ('16:42:16.204 RESPBODY bin status=200 len=65536',
         'RESPBODY', 'http_body_probe', 'bin',
         {'status': 200, 'len': 65536, 'body': None}),
        ('16:42:16.205 RESPBODY unreadable fields=a,b,c',
         'RESPBODY', 'http_body_probe', 'unreadable', {'fields': ['a', 'b', 'c']}),
        ('16:42:16.068 VIPLIMIT ask product=examRHW used=3',
         'VIPLIMIT', 'vip_limit_probe', 'ask', {'product': 'examRHW', 'used': 3}),
        ('16:42:16.069 VIPLIMIT result allowed=false remaining=0',
         'VIPLIMIT', 'vip_limit_probe', 'result', {'allowed': False, 'remaining': 0}),
        ('16:42:16.070 VIP unlock applied',
         'VIP', 'vip_unlock', None, {'note': 'unlock applied'}),
        # 原生退出守卫的**自证**（2026-11-02）。`selfTest` 三态：
        #   1=已拦住 / 0=装上了但没拦住 / -1=没装 / -2=对照组 / -3=调用失败。
        # 只记"installed=true"是不够的：过滤器装上但内核不支持时，进程照样活着，
        # 看起来像成功 —— 所以必须把自证结果一起写出来。
        ('16:42:16.071 NEXIT installed=true control=false selfTest=1 selfProof=2',
         'NEXIT', 'native_exit_guard', None,
         {'installed': True, 'control': False, 'selfTest': 1, 'selfProof': 2}),
        # 两条 WATERMARK：**同一前缀、同一 variant、不同链路**。尾部 `scope` 是唯一
        # 能把「导出合成」与「浏览页本地绘制」分开的字段，所以它必须是结构化键，
        # 不能被并进 `note` 字符串（否则按功能统计时两条链路永远合成一个数字）。
        ('16:42:16.075 WATERMARK off applied',
         'WATERMARK', 'watermark_off', 'off', {'note': 'off applied', 'scope': None}),
        ('16:42:16.076 WATERMARK off applied | scope=webpic',
         'WATERMARK', 'watermark_off', 'off',
         {'note': 'off applied', 'scope': 'webpic'}),
        # ── 服务端弹窗总闸门（第 21 轮 popwin_gate）───────────────────────────
        # 三种 action 各一条：`block=` 是"本来该不该拦"，`blocked=` 是"实际拦没拦"。
        # `OBSERVE` 那条是这两列**不相等**的唯一情形，也是这个功能存在的理由 ——
        # 合并成一列就再也看不出"只观测"到底有没有生效。
        ('16:42:16.076 POPWIN seen type=winAd block=true action=BLOCK',
         'POPWIN', 'popwin_gate', None,
         {'type': 'winAd', 'block': True, 'action': 'BLOCK', 'blocked': True}),
        ('16:42:16.077 POPWIN seen type=winUp block=false action=PASS',
         'POPWIN', 'popwin_gate', None,
         {'type': 'winUp', 'block': False, 'action': 'PASS', 'blocked': False}),
        ('16:42:16.078 POPWIN seen type=winVIPBottom block=true action=OBSERVE',
         'POPWIN', 'popwin_gate', None,
         {'type': 'winVIPBottom', 'block': True, 'action': 'OBSERVE', 'blocked': False}),
        # 前缀族：`"winActivity_" + bid`，`type` 里有下划线数字，必须整串保留。
        ('16:42:16.079 POPWIN seen type=winActivity_7 block=true action=BLOCK',
         'POPWIN', 'popwin_gate', None,
         {'type': 'winActivity_7', 'block': True, 'action': 'BLOCK', 'blocked': True}),
        ('16:42:16.071 UPDATE suppressed force-update popup',
         'UPDATE', 'skip_update', 'suppressed', {'mode': 'suppressed', 'variant': 'suppressed'}),
        ('16:42:16.072 UPDATE forceUp 1 -> 0',
         'UPDATE', 'skip_update', 'forceup', {'mode': 'forceup', 'variant': 'forceup', 'before': 1, 'after': 0}),
        ('16:42:16.080 ONBOARD clicked=\'跳过\' label=skip #1 ok=true',
         'ONBOARD', 'skip_onboarding', None,
         {'text': '跳过', 'label': 'skip', 'seq': 1, 'ok': True}),
        # 重试用尽的**结论行**：`decorReady` 是判断'是不是因为拿不到 decorView 才放弃'的唯一字段。
        ('16:42:16.007 ONBOARD giveup where="activity MainActivity" tries=6 decorReady=false',
         'ONBOARD', 'skip_onboarding', None,
         {'where': 'activity MainActivity', 'tries': 6, 'decorReady': False}),
        ('16:42:16.090 APPSIGN D/DProtect: init failed rc=-1',
         'APPSIGN', 'log_sink', None, {'level': 'D', 'tag': 'DProtect', 'msg': 'init failed rc=-1'}),
        ('16:42:16.100 RC4PT {"title":"三年级口算"}',
         'RC4PT', 'rc4_probe', None, {'text': '{"title":"三年级口算"}'}),
        ('16:42:16.101 RC4PT(nontext) len=44 b64=3q2+7w==',
         'RC4PT', 'rc4_probe', 'nontext', {'len': 44, 'b64': '3q2+7w=='}),
        ('16:42:16.102 RC4UP plain request body',
         'RC4UP', 'rc4_probe', None, {'text': 'plain request body'}),
        ('16:42:16.103 RC4UP(nontext) len=12 b64=AAECAwQFBgcICQoL',
         'RC4UP', 'rc4_probe', 'nontext', {'len': 12}),
        ('16:42:15.500 === KdKit host=7.7.2/1811 sdk=36 baseline=true',
         'MARK', None, None, {'text': 'KdKit host=7.7.2/1811 sdk=36 baseline=true'}),
        # 这两个原本只有各自的专项测试（`test_rc4_triple_roundtrip` / `Ordering`），
        # 不在 CASES 里 —— 于是"每条规则都有用例"这条断言会把它们漏报成已覆盖。
        ('16:42:15.600 SIGN URL: https://pluto.zuoyebang.com/pluto/app/hotfix?vc=1811&sign=abc&_t_=1',
         'SIGN_URL', 'sign_observer', None,
         {'host': 'pluto.zuoyebang.com', 'path': '/pluto/app/hotfix', 'sign': 'abc', '_t_': '1'}),
        ('16:42:15.907 RC4 decrypt key=b64[4]YWJjZA== in=b64[3]eHl6: b64[3]MTIz',
         'RC4', 'sign_observer', None,
         {'op': 'decrypt', 'key_len': 4, 'key_b64': 'YWJjZA==',
          'in_len': 3, 'in_b64': 'eHl6', 'out_len': 3, 'out_b64': 'MTIz'}),
        # 家长模式读/写侧（第 37/38 个功能）。`unavailable` 是**独立变体**：
        # 拿不到数据时也要能区分"没开启"与"读取失败"。
        ('16:42:16.210 PCTRL aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x5',
         'PCTRL', 'parent_ctrl_probe', None,
         {'aiwriting': 1, 'book': 0, 'picsearch': '?'}),
        ('16:42:16.212 PCTRL unavailable reason=not_logged_in',
         'PCTRL', 'parent_ctrl_probe', 'unavailable', {'reason': 'not_logged_in'}),
        ('16:42:16.211 PCTRLW aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x5 from=2 userMode=?',
         'PCTRLW', 'parent_ctrl_write', None, {'aiwriting': 1, 'from': 2}),
        ('16:42:16.213 PCTRLW unavailable reason=no_write_permission',
         'PCTRLW', 'parent_ctrl_write', 'unavailable', {'reason': 'no_write_permission'}),
    
        # 2026-11-14：会员推广清理 / MD3 皮肤（v1.2 两个新功能）
        ('16:42:16.500 PROMO blocked winVIPBottom',
         'PROMO', 'rm_vip_promo', None, {'event': 'blocked winVIPBottom'}),
        ('16:42:16.501 MD3 window themed',
         'MD3', 'md3_skin', None, {'event': 'window themed'}),
]

    def test_each_prefix(self):
        for line, kind, feature, variant, fields in self.CASES:
            with self.subTest(line=line):
                rec = cs.parse_line(line)
                self.assertEqual(rec.kind, kind, f'kind of {line!r}')
                self.assertEqual(rec.feature, feature, f'feature of {line!r}')
                self.assertEqual(rec.variant, variant, f'variant of {line!r}')
                for k, v in fields.items():
                    self.assertEqual(rec.get(k), v, f'{k} of {line!r}')

    def test_rc4_triple_roundtrip(self):
        """The RC4 line's base64 fields must be extracted, not shifted by one group."""
        line = ('16:42:15.907 RC4 decrypt key=b64[4]YWJjZA== in=b64[3]eHl6: '
                'b64[3]MTIz')
        rec = cs.parse_line(line)
        self.assertEqual(rec.kind, 'RC4')
        self.assertEqual(rec.get('key_b64'), 'YWJjZA==')
        self.assertEqual(rec.get('key_len'), 4)
        self.assertEqual(rec.get('in_b64'), 'eHl6')
        self.assertEqual(rec.get('in_len'), 3)
        self.assertEqual(rec.get('out_b64'), 'MTIz')
        self.assertEqual(rec.get('out_len'), 3)


class Ordering(unittest.TestCase):
    """Longest prefix wins. A reorder silently reclassifies whole record families."""

    def test_nontext_before_plaintext(self):
        rec = cs.parse_line('00:00:00.000 RC4PT(nontext) len=8 b64=AAAA')
        self.assertEqual(rec.variant, 'nontext')
        self.assertNotIn('text', rec.fields)

    def test_plaintext_still_plaintext(self):
        rec = cs.parse_line('00:00:00.000 RC4PT hello (nontext) world')
        self.assertIsNone(rec.variant)
        self.assertEqual(rec.get('text'), 'hello (nontext) world')

    def test_rc4keystr_not_rc4key(self):
        self.assertEqual(cs.parse_line('00:00:00.000 RC4KEYSTR abc | len=3').kind, 'RC4KEYSTR')
        self.assertEqual(cs.parse_line('00:00:00.000 RC4KEY abc | len=3').kind, 'RC4KEY')

    def test_navact_not_nav(self):
        self.assertEqual(cs.parse_line('00:00:00.000 NAVACT MainActivity').kind, 'NAVACT')
        self.assertEqual(cs.parse_line('00:00:00.000 NAV a.html | u').kind, 'NAV')

    def test_h5decode_forms(self):
        for prim in ('DECRYPT', 'ENCRYPT', 'n', 'o', 't', 'l'):
            with self.subTest(prim=prim):
                rec = cs.parse_line(f'00:00:00.000 H5 {prim} in: x')
                self.assertEqual(rec.kind, 'H5')
                self.assertEqual(rec.get('prim'), prim)


class NoShadowedRule(unittest.TestCase):
    """同一 (kind, variant) 不能被两条**重叠**的规则声明 —— 先命中的那条静默决定 builder。

    2026-10-25 第 21 轮真实踩到：`POPWIN` 同时存在一条内联 lambda 与一条 `_f_popwin`，
    两者正则逐字符相同，前者在前 ⇒ `blocked` 派生列**静默缺失**。当时
    `ParseEveryPrefix` 只断言 `kind`/`feature`/`variant`，所以在这个测试出现之前抓不到。

    注意"重复"本身不违规：`RC4KEY` 有两条（`b(1811): <key>` 与 `<key> | len=N`），
    它们是两个功能写的两种格式，正则互斥。违规的是**重叠**。
    """

    def test_no_duplicate_kind_variant(self):
        """重复的 `(kind, variant)` 是允许的**仅当**两条正则互斥（否则先命中者静默胜出）。

        `RC4KEY` 就是合法的重复：`RC4KEY b(1811): <key>` 与 `RC4KEY <key> | len=N`
        是两个不同功能写的两种格式，正则不重叠，谁先都不会错。
        而 `POPWIN` 那次两条正则**完全一样**，先命中的那个 lambda 少一个 `blocked` ——
        这才是"静默"的来源。所以要断言的是"重叠"，不是"重复"。
        """
        seen = {}
        overlapping = []
        for kind, _feature, variant, rx, _b in cs.RULES:
            key = (kind, variant)
            if key in seen:
                # 两条正则若能匹配同一行，就是真的冲突
                if _overlaps(seen[key], rx):
                    overlapping.append((key, seen[key].pattern, rx.pattern))
            else:
                seen[key] = rx
        self.assertEqual(overlapping, [],
                         f'这些 (kind, variant) 有正则重叠的重复声明: {overlapping}')

    def test_every_kind_has_exactly_one_prefix_owner(self):
        """`PREFIX_FEATURE` 是 setdefault 派生 ⇒ 重复 kind 不会报错，只会沿用第一条。"""
        owners = {}
        for kind, feature, _variant, _rx, _b in cs.RULES:
            owners.setdefault(kind, set()).add(feature)
        conflicted = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
        # RC4KEY / RC4 这类同一个 token 归两个功能是**真实存在**的（sign_observer 与
        # rc4_probe 都写它），所以这里只断言"没有意外的第三个归属方膨胀"。
        for k, v in conflicted.items():
            self.assertIn(k, ('RC4KEY', 'RC4'), f'{k} 被多个功能声明: {v}')

    def test_popwin_builder_provides_blocked(self):
        """`blocked` 是派生列：消费方用它区分"本来就该拦"和"实际拦了"。"""
        rec = cs.parse_line('00:00:00.000 POPWIN seen type=winVIPBottom block=true action=OBSERVE')
        self.assertEqual(rec.feature, 'popwin_gate')
        self.assertTrue(rec.get('block'))          # 命中清单
        self.assertFalse(rec.get('blocked'))       # 但只观测
        self.assertEqual(rec.get('action'), 'OBSERVE')
        # 规则表里 POPWIN 只能出现一次
        n = sum(1 for k, *_ in cs.RULES if k == 'POPWIN')
        self.assertEqual(n, 1, 'POPWIN 规则重复声明 ⇒ 先命中的 builder 会静默胜出')


def _overlaps(a: 're.Pattern', b: 're.Pattern') -> bool:
    """两条 `re` 是否可能匹配同一行。

    没有通用的正则交集算法（那要构造 DFA 乘积）。这里用**可判定的必要条件**：
    两条都已 `^` 锚定的规则，若一个字面量不同、且其中一个不含 `|` 交替，
    就不可能同时匹配。实用判据是逐字符比较固定的字面量前缀 —— `POPWIN seen type=`
    与 `POPWIN seen type=` 相同 ⇒ 重叠；`RC4KEY b\\(` 与 `RC4KEY ` 在前者更具体时
    仍会重叠，所以还要看"较短的那条是否被较长的那条接受"。

    做法：从每条正则的 pattern 里抽出**字面量骨架**（去掉正则元字符），
    再判断骨架是否互为前缀。对规则表这种"固定词 + 命名组"的形态足够准，
    也不会误伤 `RC4KEY` 那对（`b(` vs `<key>` 的分叉在骨架里一眼可见）。
    """
    def skeleton(p: 're.Pattern') -> str:
        s = p.pattern
        # 去掉命名/普通分组与其量词，只留字面
        s = re.sub(r'\(\?P<\w+>[^)]*\)', '\x00', s)
        s = re.sub(r'\(\?:[^)]*\)', '\x00', s)
        s = re.sub(r'\\[sSdDwW]', '\x00', s)
        s = re.sub(r'\{[^}]*\}', '', s)
        s = re.sub(r'[+*?]', '', s)
        s = s.replace('^', '').replace('$', '').replace('\\s', '\x00')
        return s

    sa, sb = skeleton(a), skeleton(b)
    n = min(len(sa), len(sb))
    # 短的骨架是长的前缀 ⇒ 前者可能是后者的特例；再看第一个分叉处是否一致
    return sa[:n] == sb[:n]


class Robustness(unittest.TestCase):
    def test_unknown_is_preserved(self):
        rec = cs.parse_line('00:00:00.000 FUTUREKIND something new')
        self.assertEqual(rec.kind, 'UNKNOWN')
        self.assertIsNone(rec.feature)
        self.assertIn('FUTUREKIND', rec.raw)

    def test_truncated_line_does_not_raise(self):
        for line in ('00:00:00.000 RC4 decrypt key=b64[128]YWI',
                     '00:00:00.000 SIGN URL: https://x/y?a=',
                     '00:00:00.000 GUARD blocked=',
                     '00:00:00.000 RC4PT(nontext) len=',
                     '00:00:00.000 EXITCALL #1'):
            with self.subTest(line=line):
                rec = cs.parse_line(line)          # must not raise
                self.assertIsInstance(rec.kind, str)

    def test_no_timestamp_still_parses(self):
        rec = cs.parse_line('VIP unlock applied')
        self.assertEqual(rec.kind, 'VIP')
        self.assertIsNone(rec.ts)

    def test_crlf_and_trailing_space(self):
        rec = cs.parse_line('16:42:16.070 VIP unlock applied\r\n')
        self.assertEqual(rec.kind, 'VIP')
        self.assertEqual(rec.get('note'), 'unlock applied')

    def test_guard_relative_url_resolves_to_self_host(self):
        rec = cs.parse_line('00:00:00.000 GUARD blocked=x reason=host_not_allowed url=/a/b #7')
        self.assertEqual(rec.get('host'), 'self:www.kuaiduizuoye.com')

    def test_guard_absolute_url_host(self):
        rec = cs.parse_line('00:00:00.000 GUARD blocked=x reason=host_not_allowed url=https://e.example/p #7')
        self.assertEqual(rec.get('host'), 'e.example')

    def test_empty_capture(self):
        self.assertEqual(cs.count_kinds(cs.parse_text('')), {})
        self.assertEqual(list(cs.parse_text('\n\n\n')), [])


class UnknownClassification(unittest.TestCase):
    """UNKNOWN 必须分档：`new-prefix` 是要处理的信号，`legacy-wrap` 是旧抓取的噪声。

    这条测试的由来：5 份冻结抓取里 564 行 UNKNOWN 中 560 行是同一张 PEM 证书的续行。
    一句"有 564 行没人认领"读起来像"模块在写未知格式"，实际是 2026-10-25 之前
    写入侧没压平换行（`CapturePolicy.oneLine` 已修）。分档让这条告警重新有用。
    """

    def test_new_prefix_is_flagged(self):
        for line in ('00:00:00.000 FUTUREKIND something new',
                     'FUTUREKIND a=b',
                     'NEWTHING: value',
                     'HDRX(v) whatever'):
            with self.subTest(line=line):
                self.assertEqual(cs.classify_unknown(line), cs.UNKNOWN_NEW_PREFIX)
                self.assertEqual(cs.parse_line(line).get('reason'), cs.UNKNOWN_NEW_PREFIX)

    def test_pem_and_base64_continuations_are_noise(self):
        for line in ('MIIFoTCCA4mgAwIBAgICO/cwDQYJKoZIhvcNAQELBQAwgYAxCzAJBgNVBAYTAkNO',
                     'MRAwDgYDVQQIDAdCZWlqaW5nMQwwCgYDVQQKDANNU0ExETAPBgNVBAsMCE9BSURf',
                     'Un7cTl4=',
                     '-----BEGIN CERTIFICATE-----',
                     '-----END CERTIFICATE-----'):
            with self.subTest(line=line):
                self.assertEqual(cs.classify_unknown(line), cs.UNKNOWN_LEGACY_WRAP)

    def test_truncated_line_is_its_own_class(self):
        self.assertEqual(cs.classify_unknown('00:00:00.000 NTNaMIGTMQsw …(2012)'),
                         cs.UNKNOWN_TRUNCATED)

    def test_lowercase_prose_is_not_a_prefix(self):
        """小写开头不可能是前缀，不该被当成"新前缀"去改 schema。"""
        self.assertEqual(cs.classify_unknown('this line has no known prefix at all'),
                         cs.UNKNOWN_OTHER)

    def test_reason_does_not_change_kind_or_raw(self):
        """分档只加一个字段：`kind` 仍是 UNKNOWN，`raw` 仍逐字保留（证据不能被我改）。"""
        line = 'MIIFoTCCA4mgAwIBAgICO/cwDQYJKoZIhvcNAQELBQAwgYAxCzAJBgNVBAYTAkNO'
        rec = cs.parse_line('00:00:00.000 ' + line)
        self.assertEqual(rec.kind, 'UNKNOWN')
        self.assertIn(line, rec.raw)

    def test_summarise_reports_reasons(self):
        s = cs.summarise(FIXTURE)
        self.assertEqual(s['unknown_reasons'], {cs.UNKNOWN_OTHER: 1})


class EveryPrefixHasATest(unittest.TestCase):
    """规则表里的**每一条**规则都必须在 `ParseEveryPrefix.CASES` 里有显式用例。

    原来 CASES 手写了 33 条，看起来"覆盖了新前缀"，但它是手工维护的列表：
    `H5BRIDGE` / `ONBOARD` / `H5` / `RC4KEY` / `RC4KEYSTR` / `RC4PT` / `RC4UP` /
    `SIGN_URL` / `RC4` 这 9 个 kind 当时**没有**逐字段用例 —— 它们只被 fixture 顺带解析，
    所以字段名写错、variant 取错都没有断言会红。
    """

    def test_every_kind_is_in_cases(self):
        kinds_in_cases = {k for _l, k, _f, _v, _x in ParseEveryPrefix.CASES}
        all_kinds = {k for k, *_ in cs.RULES}
        missing = sorted(all_kinds - kinds_in_cases)
        self.assertEqual(missing, [], f'这些 kind 没有逐字段用例（只被 fixture 顺带解析）: {missing}')

    def test_cases_provide_one_per_declared_variant(self):
        """`BRIDGE download` / `BRIDGE userinfo` 这类同 kind 多 variant，必须都有用例。"""
        pairs = {(k, v) for _l, k, _f, v, _x in ParseEveryPrefix.CASES}
        missing = [p for p in cs.VARIANT_PAIRS if p not in pairs]
        self.assertEqual(missing, [], f'这些 (kind, variant) 没有用例: {missing}')


class ActivityAppendixCoversEveryVariant(unittest.TestCase):
    """新增一个 **variant** 时，`ACTIVITY.md` §七 必须同时写出它长什么样。

    为什么这条比 `check_feature_parity.check_activity_doc` 更强：那道门禁只要求
    **feature id** 在 §七 出现一次。于是一条全新的子形态（`BRIDGE decode`）可以
    只活在代码里 —— 抓取里出现 `BRIDGE decodeHttpRequest …` 时，
    读的人在 §七 查不到它，只能去翻 smali。

    这正是 2026-10-26 第 31 轮加 `decode_httpRequest` 时差点漏掉的那一步：
    代码、schema、单测都齐了，而"给读日志的人看的那张表"没改。
    """

    #: 每个 variant 在 §七 里必须出现的**字面标记**（原样写在表里）。
    #: 新增 variant 时这里不补 ⇒ 测试红；补了但文档没写 ⇒ 测试红。
    MARKS = {
        ('BRIDGE', 'decode'): 'decodeHttpRequest',
        ('BRIDGE', 'download'): 'downloadMedia',
        ('BRIDGE', 'userinfo'): 'getuserinfo',
        ('BRIDGE', 'payorder'): 'payorder',
        # 家长模式读/写侧的"拿不到数据"变体 —— 它不是另一个前缀，
        # 而是同前缀下的独立形态，所以文档里按 `PCTRL unavailable` 登记。
        ('PCTRL', 'unavailable'): 'PCTRL unavailable',
        ('PCTRLW', 'unavailable'): 'PCTRLW unavailable',
        ('UPDATE', 'forceup'): 'UPDATE forceUp',
        ('UPDATE', 'suppressed'): 'UPDATE suppressed',
        ('HDR', 'v'): 'HDR(v)',
        ('HDR', 'static'): 'HDR(static)',
        ('HDR', 'request'): 'HDR <host>',
        ('VIPLIMIT', 'ask'): 'VIPLIMIT ask',
        ('VIPLIMIT', 'result'): 'VIPLIMIT result',
        ('RC4PT', 'nontext'): 'RC4PT(nontext)',
        ('RC4UP', 'nontext'): 'RC4UP(nontext)',
        ('RC4KEY', 'refreshed'): 'RC4KEY refreshed',
        ('NAVACT', 'activity'): 'NAVACT',
        ('ROBUST', 'patch'): 'ROBUST patch',
        ('ROBUST', 'stack'): 'ROBUST stack',
        ('REQBODY', 'text'): 'REQBODY text',
        ('REQBODY', 'json'): 'REQBODY json',
        ('REQBODY', 'params'): 'REQBODY params',
        ('REQBODY', 'bin'): 'REQBODY bin',
        ('RESPBODY', 'text'): 'RESPBODY text',
        ('RESPBODY', 'bin'): 'RESPBODY bin',
        ('RESPBODY', 'unreadable'): 'RESPBODY unreadable',
        ('WATERMARK', 'off'): 'WATERMARK off',
    }

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(KIT_PY, '..', 'scripts'))
        from hook_vocab import read_text
        path = os.path.join(MODULE_DIR, 'ACTIVITY.md')
        cls.text = read_text(path)
        idx = cls.text.find('\n## 七、')
        cls.section = cls.text[idx:] if idx >= 0 else ''

    def test_every_mapped_variant_is_documented(self):
        self.assertTrue(self.section, 'ACTIVITY.md 找不到 §七（功能↔前缀对照表）')
        missing = [f'{k}/{v} 缺少标记 {mark!r}'
                   for (k, v), mark in sorted(self.MARKS.items())
                   if mark not in self.section]
        self.assertEqual(missing, [], '这些 variant 在 ACTIVITY.md §七 里查不到：'
                         + '; '.join(missing))

    def test_mapping_covers_every_declared_variant(self):
        """有 variant 却不在 MARKS 里 ⇒ 说明新增了子形态但没决定它该怎么登记。"""
        unmapped = [p for p in cs.VARIANT_PAIRS if p not in self.MARKS]
        self.assertEqual(unmapped, [],
                         f'这些 variant 没有对应的文档标记约定，请补 MARKS: {unmapped}')


class FixtureCoverage(unittest.TestCase):
    def test_all_capturable_features_present(self):
        s = cs.summarise(FIXTURE)
        for f in cs.FEATURES_WITH_CAPTURE:
            with self.subTest(feature=f):
                self.assertGreater(s['features'].get(f, 0), 0,
                                   f'{f} 在 fixture 里没有行 —— 前缀解析或 fixture 缺项')

    def test_every_variant_pair_has_a_sample(self):
        """**每一个** (kind, variant) 都必须在 fixture 里有一行。

        为什么这条比"每个 feature 有一行"更强：下游是**按 variant 分支**的
        （`transcript` 对 `HDR(v)` / `HDR(static)` / `HDR` 三种写法不同；
        `session_report` 对 `UPDATE forceup` / `suppressed` 也不同）。
        只覆盖 feature 时，`HDR/request` 与 `UPDATE/forceup` 两个分支可以**从来没被执行过**
        而所有测试全绿 —— 2026-10-25 实测正是如此（36 条规则里 2 条无样本）。
        """
        seen = {(r.kind, r.variant) for r in cs.iter_records(FIXTURE)}
        missing = [(k, v) for (k, v) in cs.VARIANT_PAIRS if (k, v) not in seen]
        self.assertEqual(missing, [], f'fixture 缺这些 (kind, variant) 样本: {missing}')

    def test_declared_variants_are_reachable(self):
        """规则表/派生表声明的 variant 必须真的能从一行文本里得到 —— 没有死声明。"""
        self.assertEqual(cs.parse_line('HDR h/p :: A=1').variant, 'request')
        self.assertEqual(cs.parse_line('HDR(v) h/p :: A=1').variant, 'v')
        self.assertEqual(cs.parse_line('HDR(static) A=1').variant, 'static')
        self.assertEqual(cs.parse_line('UPDATE forceUp 1 -> 0').variant, 'forceup')
        self.assertEqual(cs.parse_line('UPDATE suppressed popup').variant, 'suppressed')
        # 派生表与规则表必须一致：漏一个 ⇒ VARIANT_PAIRS 里少一项 ⇒ 上一条测试失去意义。
        for kind, variants in cs.DERIVED_VARIANTS.items():
            with self.subTest(kind=kind):
                for v in variants:
                    self.assertIn(v, cs.VARIANTS[kind])

    def test_exactly_one_unknown_by_design(self):
        s = cs.summarise(FIXTURE)
        self.assertEqual(len(s['unknown']), 1)
        self.assertIn('no known prefix', s['unknown'][0])

    def test_span(self):
        span = cs.summarise(FIXTURE)['span']
        self.assertEqual(span[0], '16:42:15.500')
        self.assertGreater(span[1], span[0])

    def test_feature_sets_partition_all_features(self):
        union = set(cs.FEATURES_WITH_CAPTURE) | set(cs.FEATURES_LOGCAT_ONLY)
        self.assertEqual(union, set(cs.FEATURE_IDS))
        self.assertFalse(set(cs.FEATURES_WITH_CAPTURE) & set(cs.FEATURES_LOGCAT_ONLY))
        # 功能数由 FeatureRegistry 决定（见 test_feature_ids_match_the_registry），这里只要求
        # "分区完整"。写死数字会让每加一个功能都要改测试 —— 那会让人倾向于改测试而不是改代码。
        self.assertGreaterEqual(len(cs.FEATURE_IDS), 28)


class KindFieldContract(unittest.TestCase):
    """每个 kind 的 `fields` 必须带齐**消费端依赖的键**。

    为什么需要这一层：`VariantCoverage` 保证"每种变体都有一行样本"，
    但样本只证明"能解析出**某些**字段"，不证明"消费端要的那个字段在不在"。
    第 28 轮就是这样炸的：新增 `BRIDGE payorder`，它的 `fields` 少了 `action`，
    而 `bridge_inventory.py` 用 `rec.get('action')` 当分组键 ⇒ `semantic[None] += 1`
    ⇒ `sorted(..., key=(-n, action))` 抛 `TypeError: None < str`，整个统计工具崩掉。

    当时的 schema 测试**全绿**：那三行 fixture 解析正常、variant 对、字段也都取到了，
    只是**少一个别人要的键**。所以契约必须显式写下来。
    """

    #: (kind, variant) -> 该形态的 `fields` 里必须存在的键（取值为 None 也算存在）。
    #: `None` 作 variant = "该 kind 的所有变体都要有"。
    #:
    #: 必须按 variant 分开：`VIPLIMIT ask product=… used=…` 与
    #: `VIPLIMIT result allowed=… remaining=…` 是**两种不相交的形状**，
    #: 合并成一张表会把"结果行没有 product"误报成缺陷（第一版就这么报了一次错）。
    #: 两个消费端（`capture_transcript` / `session_report`）确实按 variant 分支，
    #: 所以"两形各缺一半字段"是设计，不是漏。
    REQUIRED_FIELDS = {
        # `bridge_inventory.py` 按 action 分组；`capture_transcript.py` 也读它。
        ('BRIDGE', None): ('action',),
        ('H5BRIDGE', None): ('action', 'count'),
        ('ADSLOT_CALL', None): ('method',),
        ('ADSLOT_RET', None): ('method',),
        ('GUARD', None): ('action', 'reason'),
        ('ROUTE', None): ('route',),
        ('WEBREQ', None): ('url',),
        ('EXITCALL', None): ('seq', 'blocked'),
        ('EXITSTACK', None): ('seq',),
        ('VIPLIMIT', 'ask'): ('product', 'used'),
        ('VIPLIMIT', 'result'): ('allowed', 'remaining'),
    }

    def test_declared_kinds_carry_required_fields(self):
        """用 fixture + CASES 里所有样本行验证，而不是只测"当前那条"实现。"""
        lines = []
        with open(FIXTURE, encoding='utf-8') as fh:
            lines += [ln.rstrip('\n') for ln in fh]
        lines += [ln for ln, *_ in ParseEveryPrefix.CASES]
        checked = 0
        for line in lines:
            rec = cs.parse_line(line)
            need = (self.REQUIRED_FIELDS.get((rec.kind, rec.variant))
                    or self.REQUIRED_FIELDS.get((rec.kind, None)))
            if not need:
                continue
            checked += 1
            for key in need:
                with self.subTest(kind=rec.kind, line=line[:60]):
                    self.assertIn(
                        key, rec.fields,
                        f'{rec.kind}/{rec.variant} 缺少消费端依赖的字段 `{key}`：{line[:80]}')
        self.assertGreater(checked, 0, '样本里没有任何 REQUIRED_FIELDS 覆盖的 kind —— 契约失效')

    def test_every_bridge_variant_declares_action(self):
        """`BRIDGE` 的每一个 variant 都必须带 `action`。

        单独一条，因为这是真的炸过的那个具体形态；泛化那条测试如果将来被改宽，
        这一条还能把 `BRIDGE` 钉住。
        """
        lines = []
        with open(FIXTURE, encoding='utf-8') as fh:
            lines += [ln.rstrip('\n') for ln in fh]
        lines += [ln for ln, *_ in ParseEveryPrefix.CASES]
        seen = set()
        for line in lines:
            rec = cs.parse_line(line)
            if rec.kind != 'BRIDGE':
                continue
            seen.add(rec.variant)
            with self.subTest(variant=rec.variant):
                self.assertIsNotNone(rec.fields.get('action'),
                                     f'BRIDGE/{rec.variant} 的 action 为空：{line[:80]}')
        self.assertEqual(seen, set(cs.VARIANTS['BRIDGE']),
                         'fixture/CASES 没有覆盖 BRIDGE 的全部变体')


class KotlinSideDrift(unittest.TestCase):
    """The module's literal capture prefixes must all be known to the schema.

    This is the test that would have caught "we added `VIP unlock applied` but no parser
    knows the `VIP` prefix": it reads the Kotlin sources, extracts the first token of every
    literal passed to `Capture.append(...)`, and requires each to appear in RULES.
    """

    # Prefixes whose token is built at call time — the literal in Kotlin is a template
    # (`"$tag ..."`, `"$tag(nontext) ..."`) or is passed through a wrapper that adds the
    # feature name (`NativeProbe.capture` prefixes "NativeProbe "). Listed explicitly and
    # each one is still asserted to exist in the schema, so this cannot become a loophole.
    VIA_VARIABLE = {
        'RC4PT': 'RC4Probe.emit("RC4PT", …) — literal is `$tag `',
        'RC4UP': 'RC4Probe.emit("RC4UP", …) — literal is `$tag `',
    }

    #: `emit(tag, …)` 会把 `(nontext)` 变体拼进同一行。这两条**必须**被规则表按
    #: 最长前缀优先认领，否则 `RC4PT(nontext) …` 会被读成明文而 b64 被当正文。
    NON_TEXT_VARIANTS = ('RC4PT', 'RC4UP')
    # `Capture.mark("…")` always writes `=== ` first, which is the MARK kind.
    WRAPPED_TO_MARK = True

    LITERAL = re.compile(r'Capture\.(append|record|mark)\(\s*"((?:[^"\\]|\\.)*)"')
    # 项目自己的**包装函数**：`emit("RC4PT", out)` / `capture("H5BRIDGE …")` /
    # `record(param)`。它们最终都落到 `Capture.append`，但字面量不在 `Capture.` 调用里，
    # 所以 2026-10-25 之前的漂移门禁**完全看不见**它们 —— RC4Probe 的 `RC4PT` / `RC4UP`
    # 一直靠一张 VIA_VARIABLE 手写例外表"证明"自己存在，而不是被扫出来。
    WRAPPER = re.compile(r'\b(?:emit|capture)\(\s*"((?:[^"\\]|\\.)*)"')
    #: 只接受"整文件就是写抓取"的窄包装，避免把无关的同名函数算进来。
    WRAPPER_FILES = ('RC4Probe.kt', 'H5BridgeLog.kt', 'NativeProbe.kt')

    def kotlin_files(self):
        for base, _dirs, files in os.walk(MODULE_SRC):
            if os.sep + 'build' + os.sep in base + os.sep:
                continue
            for f in sorted(files):
                if f.endswith('.kt'):
                    yield os.path.join(base, f)

    def test_every_literal_prefix_is_declared(self):
        self.assertTrue(os.path.isdir(MODULE_SRC), f'找不到模块源码: {MODULE_SRC}')
        seen, bad, skipped, via_wrapper = set(), [], [], set()
        for path in self.kotlin_files():
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
            base = os.path.basename(path)
            found = [(m.group(1), m.group(2)) for m in self.LITERAL.finditer(text)]
            if base in self.WRAPPER_FILES:
                found += [('append', m.group(1)) for m in self.WRAPPER.finditer(text)]
                via_wrapper.update(m.group(1).split(' ', 1)[0].rstrip(':')
                                   for m in self.WRAPPER.finditer(text)
                                   if '$' not in m.group(1).split(' ', 1)[0])
            for call, lit in found:
                if call == 'mark':
                    token = 'MARK'          # Capture.mark writes "=== <line>"
                elif '$' in lit.split(' ', 1)[0]:
                    skipped.append((base, lit[:40]))
                    continue                # template token, asserted via VIA_VARIABLE
                elif lit.startswith('=== '):
                    token = 'MARK'
                else:
                    token = lit.split(' ', 1)[0].rstrip(':')
                seen.add(token)
                if not cs.known_token(token):
                    bad.append((base, token))
        self.assertEqual(bad, [], f'这些前缀模块会写出、但 capture_schema 不认识: {bad}')
        # 包装函数写出的词必须**真的被扫到**，否则 WRAPPER_FILES 写错会让门禁静默失效。
        self.assertIn('H5BRIDGE', via_wrapper, 'H5BridgeLog 的 capture("H5BRIDGE …") 没被扫到')
        self.assertIn('RC4PT', seen, 'RC4Probe 的 emit("RC4PT") 没被扫到')        # The template ones are not silently ignored: every named one must exist.
        for token in self.VIA_VARIABLE:
            with self.subTest(via_variable=token):
                self.assertIn(token, cs.PREFIX_FEATURE, self.VIA_VARIABLE[token])
        self.assertIn('RC4PT', cs.PREFIX_FEATURE)
        # And the tagged prefix used by NativeProbe.capture must be a known wrapper.
        self.assertIn('NativeProbe', cs.TAGGED)
        self.assertTrue(skipped, 'expected at least one $-template literal (RC4Probe.emit)')

    def test_feature_ids_match_the_registry(self):
        """`FEATURE_IDS` must equal `FeatureRegistry.all` — a rename there breaks counting.

        Several features share one file (all ad removers live in `AdFeatures.kt`), so the
        id is looked up per `object <Name>` declaration, not per file name.
        """
        reg = os.path.join(MODULE_SRC, 'features', 'FeatureRegistry.kt')
        with open(reg, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
        block = text[text.index('val all'):]
        block = block[:block.index(')')]
        names = re.findall(r'^\s{8}(\w+),\s*$', block, re.M)
        # 不写死功能数：`FeatureRegistry` 是唯一事实源，schema 只需与它**相等**。
        self.assertGreaterEqual(len(names), 28, f'解析到 {len(names)} 个注册项，疑似解析失败')

        corpus = ''
        for base, _dirs, files in os.walk(MODULE_SRC):
            for f in sorted(files):
                if f.endswith('.kt'):
                    with open(os.path.join(base, f), encoding='utf-8', errors='replace') as fh:
                        corpus += fh.read() + '\n'

        ids, unresolved = set(), []
        for name in names:
            m = re.search(r'object %s\s*:\s*\w+Feature\((.*?)\n\)' % re.escape(name),
                          corpus, re.S)
            if not m:
                m = re.search(r'object %s\b[^{]*\{(.*?)\n\}' % re.escape(name), corpus, re.S)
            idm = re.search(r'id\s*=\s*"([a-z0-9_]+)"', m.group(1)) if m else None
            if idm:
                ids.add(idm.group(1))
            else:
                unresolved.append(name)
        self.assertEqual(unresolved, [], f'这些功能对象解析不到 id: {unresolved}')
        self.assertEqual(ids, set(cs.FEATURE_IDS),
                         'capture_schema.FEATURE_IDS 与 FeatureRegistry 不一致')

    def test_declared_prefixes_have_a_rule(self):
        rule_kinds = {k for k, *_ in cs.RULES}
        for kind in cs.PREFIX_FEATURE:
            with self.subTest(kind=kind):
                self.assertIn(kind, rule_kinds)
        # Alias tokens must point at kinds that really exist, not at typos.
        for token, kinds in cs.TOKEN_KINDS.items():
            with self.subTest(token=token):
                for k in kinds:
                    self.assertIn(k, rule_kinds)
        for tag, feature in cs.TAGGED.items():
            with self.subTest(tag=tag):
                self.assertIn(feature, cs.FEATURE_IDS)


class KotlinFieldNamesAreRecognised(unittest.TestCase):
    """**行内字段名**的双向漂移 —— ①b 现在只校验"前缀 token"，不校验字段。

    为什么这个缺口值得一道单独的断言：模型里 `type=` → `kind=` 改个名字，
    前缀还在、行还是那一行、`test_every_literal_prefix_is_declared` 照旧全绿，
    但规则正则不再匹配 ⇒ **整行落到 UNKNOWN**，按功能统计直接少一类事件，
    而且没有任何门禁会红。它的症状与"功能没生效"完全一样。

    两个方向都查：

    * Kotlin 写了 `name=` 而该 kind 的解析器**从不产出** `name` ⇒ 字段被吞掉；
    * 解析器产出 `name` 而 Kotlin **从不写** ⇒ 死字段（规则改了、产出方没改）。

    第二个方向只对"字面量里含 `=` 的行"生效：有些字段是解析器从**整段文本**里
    推出来的（`url` / `host` / `action` / `variant`），Kotlin 根本不写 `k=v`。
    那份白名单必须逐条给出理由，否则它会变成"任何不一致都能塞进去"的后门。
    """

    #: 解析器**推导**而非从 `k=v` 读出的键。键 -> 为什么它不该在 Kotlin 里出现。
    DERIVED = {
        'variant': '由 token 本身决定（`HDR(v)` / `UPDATE forceUp`），不是 `k=v`',
        'action': 'BRIDGE 各变体的动作名由规则**常量**给出，Kotlin 写的是方法名',
        'url': '从整段文本里截取（`BRIDGE downloadMedia type=… url=…` 的 url 无前缀约束）',
        'host': '由 `url` 解析出的 hostname，Kotlin 不写',
        'target': '`HDR` 的 `host/path ::` 段，不是 `k=v`',
        'fields': '`HDR` 的整段 `k=v | k=v` 聚合，键名由被钩方法的参数决定',
        'headers': '`WEBREQ` 的 `|` 之后整段，键名不固定',
        'keys': '由 `keys=N:a,b,c` 拆出的列表',
        'shape': '`BRIDGE payorder` 的形状枚举（empty/not-json/keys），Kotlin 写 `$shape`',
        'mode': '`UPDATE` 的两种形态由 token 决定',
        'note': '`VIP`/`WATERMARK` 的自由文本尾巴',
        'text': '`RC4PT` 明文 / `ONBOARD` 点击文案，整段文本',
        'stack': '`EXITSTACK` 的展开堆栈，整段文本',
        'msg': '`APPSIGN` 的消息正文，整段文本',
        'identity': '`BRIDGE getuserinfo` 的被问项，Kotlin 写 `asked identity=`',
        'reason': '`GUARD` 的拦截原因，Kotlin 写 `reason=`（见下）',
        'seq': '`#n` 序号，Kotlin 写 `#\\$n` 而非 `seq=`',
        'after': '`UPDATE forceUp X -> Y` 的 `->` 目标，不是 `k=v`',
        'before': '`UPDATE forceUp X -> Y` 的源值，不是 `k=v`',
        'len': '`len=N` —— 属于字面量里的 `len=`，见 CASES',
        'b64': '`b64=…` 由 `emit` 拼接，模板里是 `b64=`',
        'level': '`APPSIGN W/…` 的级别字母，Kotlin 写 `${m.uppercase()[0]}` 无 `level=`',
        'blocked': '`GUARD` 的 "实际拦没拦" 由 `action` 推出（见 `_f_guard`）',
    }

    def _produced(self):
        """kind -> 解析器从**已验证用例**里真正产出的键集合。"""
        out = {}
        for _line, kind, _feat, _var, _extra in ParseEveryPrefix.CASES:
            r = cs.parse_line(_line)
            self.assertEqual(r.kind, kind,
                             f'用例自身解析失败：{_line!r} 得到 {r.kind}')
            out.setdefault(kind, set()).update(r.fields)
        return out

    def _literals(self):
        """(文件, 字面量) —— 与 `KotlinSideDrift` 用同一套抽取规则。"""
        drift = KotlinSideDrift
        for path in drift().kotlin_files():
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
            base = os.path.basename(path)
            for m in drift.LITERAL.finditer(text):
                yield base, m.group(2)
            if base in drift.WRAPPER_FILES:
                for m in drift.WRAPPER.finditer(text):
                    yield base, m.group(1)

    def _literal_keywords(self, kind):
        """规则里作为**固定字面量**出现的 `name=` —— 它不是字段名。

        `ONBOARD clicked='…' label=…` 就是这种：`clicked=` 是语法的一部分，
        解析器把它后面的内容读成 `text`。把它当字段名比对会得出一条假缺口，
        而假缺口会教人加白名单、最后白名单成了后门。
        """
        out = set()
        for k, _feat, _var, rx, _fn in cs.RULES:
            if k != kind:
                continue
            for name in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=', rx.pattern):
                out.add(name)
        return out

    def test_kotlin_field_names_are_all_produced(self):
        produced = self._produced()
        bad = []
        for base, lit in self._literals():
            token = lit.split(' ', 1)[0]
            if '$' in token or token.startswith('==='):
                continue
            kind = re.sub(r'\(.*\)$', '', token.rstrip(':'))
            if kind not in produced:
                continue
            keywords = self._literal_keywords(kind)
            for name in re.findall(r'(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=', lit):
                if name in keywords:
                    continue          # 规则的固定字面量，不是字段名
                if name in produced[kind] or name.lower() in produced[kind]:
                    continue
                if name in self.DERIVED:
                    continue
                bad.append((base, kind, name, lit[:70]))
        self.assertEqual(bad, [],
                         '这些字段名 Kotlin 会写出、但该 kind 的解析器从不产出 '
                         '（整行会落 UNKNOWN 或字段被吞）：\n'
                         + '\n'.join(f'  {b} [{k}] {n}=  ← {l}' for b, k, n, l in bad))

    #: 正则里的**结构**分组：只用来定位分隔，其内容不进 fields。
    STRUCTURAL_GROUPS = {
        'cut': '正文末尾的 `…` 截断标记，已转成 `truncated` 布尔',
        'more': '`…+N` 省略条数，只用于人读，不参与统计',
        'n': '`n=3` 的条数，正文另有 `kv`；单列没有消费方',
        'block': '`POPWIN` 的"本来该不该拦"，已转成布尔 `block`',
    }

    #: builder 会把分组**改名**成别的键。键名不等于字段名时在这里登记映射，
    #: 否则"按值查找"仍然有效 —— 本表只是让报错信息更好读，不作为豁免。
    RENAMED = {
        ('RC4KEY', 'len'): 'length',
        ('RC4KEYSTR', 'len'): 'length',
        ('RC4KEY', 'ver'): 'version',
        ('BRIDGE', 'sd'): 'shouldDecode',
    }

    def test_regex_named_groups_reach_fields(self):
        """正则抓到的**每个分组的取值**都必须真的落进 fields。

        这是**可判定**的检查，也是本仓库最容易漏的一类静默失效：
        给正则加一个命名分组、忘了在 builder 里返回它 ⇒ 那一列永远是 None，
        但该行照样被认领、`kind` 照样正确、按前缀统计照样有数 ——
        **没有任何门禁会红**。它的症状与"宿主这个字段改名了"完全一样，
        排查要翻 smali 才能区分。

        判定方式不看**键名**（builder 常把 `len`→`length`、`sd`→`shouldDecode`），
        而看**值**：把该分组在样本里捕获到的字符串，拿去 fields 的键/值/嵌套容器
        里找。找不到 ⇒ 这个分组白抓。

        反向（解析器产出了、Kotlin 从没写过）不在这里做：Kotlin 大量把值
        **位置传参**（`emit("RC4PT", …)`、`"$who … len=$n"`），不存在 `k=` 可对，
        双向比对只会产出几十条没有意义的红。那一侧由
        `test_kotlin_field_names_are_all_produced` 从前缀+字面量方向封住。

        **覆盖边界（实测，不是估计）**：本用例只对**命名分组**成立 ——
        54 条规则里 21 条用命名分组，另 33 条只用位置分组。

        为什么不把位置分组也按"值是否落进 fields"一起查：位置分组里**大量是
        有意转换**，按值比对会产生 14 条假阳性，例如

        * `SIGN params: _t_=1 | abis=1` → `_kv_pairs()` 拆成 3 个键，整串不可能出现；
        * `HDR … Content-Type=x | User-Agent=y` → 同样被拆进 `fields` 字典；
        * `EXITCALL … (stack suppressed)` → 转成布尔 `stack_suppressed`；
        * `REQBODY … …+5` → 转成 `omitted=5`。

        这些不是缺陷，而是"合并/拆分/布尔化"，一个按值比对的检查分不清它与
        "白抓了"。**能判定的只有命名分组这一半，就把这一半判死；**
        另一半靠 `test_kotlin_field_names_are_all_produced`（前缀方向）与
        `EveryPrefixHasATest`（逐字段用例必须写出期望值）兜底 ——
        后者对位置分组同样有效，因为用例里写的就是**期望的字段字典**。
        """
        def values(v, acc):
            if isinstance(v, (list, tuple)):
                for x in v:
                    values(x, acc)
            elif isinstance(v, dict):
                for x in v.values():
                    values(x, acc)
            elif v is not None:
                acc.add(str(v))
            return acc

        dropped = []
        for kind, _feat, _var, rx, _builder in cs.RULES:
            if not rx.groupindex:
                continue
            samples = [ln for ln, k, *_ in ParseEveryPrefix.CASES if k == kind]
            for g in sorted(rx.groupindex):
                if g in self.STRUCTURAL_GROUPS:
                    continue
                landed = False
                for sample in samples:
                    body = re.sub(r'^\d{2}:\d{2}:\d{2}\.\d{3}\s+', '', sample)
                    m = rx.match(body)
                    if not m or m.group(g) is None:
                        continue
                    want = m.group(g).strip()
                    if not want:
                        continue          # 空串分组不产生信息，不算丢
                    fields = cs.parse_line(sample).fields
                    got = values(fields, set())
                    if want in got or want.lower() in {x.lower() for x in got}:
                        landed = True
                        break
                    # 分组可能被拆开（`fields=a,b` → `['a','b']`）：把列表拼回去再比。
                    if any(isinstance(v, list) and ','.join(map(str, v)) == want
                           for v in fields.values()):
                        landed = True
                        break
                if not landed:
                    hint = self.RENAMED.get((kind, g))
                    dropped.append((kind, g, hint, rx.pattern[:64]))
        self.assertEqual(dropped, [],
                         '这些正则分组抓到了值、但没进 fields（白抓，列恒为 None）：\n'
                         + '\n'.join(
                             f'  {k}.{g}' + (f' → 已改名成 `{h}`' if h else '')
                             + f'  ← /{p}/'
                             for k, g, h, p in dropped))


class FixtureIsFullyClaimed(unittest.TestCase):
    """
    `fixtures/all_prefixes.txt` 里**除显式标注的那一行外**，每一行都必须被某条规则认领。

    为什么这条比"每个前缀都声明了"更强
    ----------------------------------
    `KotlinSideDrift.test_every_literal_prefix_is_declared` 只校验**前缀存在**：
    只要 `blocked ad slot read` 这个词在规则表里出现过，它就绿。它看不出
    "模块改成 `di.a.d(501)`、而规则仍要求 `aj.a.f(7) -> null`"这种**整行形状漂移**。

    而这类漂移已经发生过两次：
      * `ADSLOT call/ret`：类名从 `aj.a` 挪到 `di.a`（7.9.0 的 R8 重排）；
      * `blocked ad slot read`：同一原因，且尾巴 `-> null` 被去掉。
    两次都是**规则表看起来完整、真实抓取里却全是 UNKNOWN**，而当时没有任何门禁会红。

    这条测试把"真实抓取里会长成什么样"搬进 fixture，然后要求解析器 100% 认得。
    新功能写出一条新形状的行 ⇒ 要么补规则、要么补 fixture，二者缺一即红。
    """

    #: 故意无法认领的行（用来证明 UNKNOWN 分支本身工作）。改这里必须说明理由。
    DELIBERATE_UNKNOWN = {
        'this line has no known prefix at all',
    }

    def test_every_fixture_line_is_claimed(self):
        unclaimed = []
        with open(FIXTURE, encoding='utf-8') as f:
            for raw in f:
                line = raw.rstrip('\n')
                if not line.strip():
                    continue
                rec = cs.parse_line(line)
                if rec.kind in (None, 'UNKNOWN'):
                    body = line.strip()
                    # 时间戳之后的部分才是正文
                    for cand in self.DELIBERATE_UNKNOWN:
                        if cand in body:
                            break
                    else:
                        unclaimed.append(body[:100])
        self.assertEqual(
            unclaimed, [],
            'fixture 里有行没有被任何规则认领 —— 说明模块**实际写出**的形状与规则不一致'
            '（不是"前缀不存在"，而是整行对不上）：\n'
            + '\n'.join('  ' + u for u in unclaimed),
        )


if __name__ == '__main__':
    unittest.main()
