#!/usr/bin/env python3
"""
kuaidui-kit / session_report.py — one capture file in, one reviewable report out.

The module writes everything it observes or blocks into a single file
(`files/kdkit_capture.txt`); this turns that file into the session summary a reviewer (or the
next round of work) actually wants:

  0  宿主版本      文件大小、时间跨度、每种记录各多少行
  1  接口面        App 说过话的 host / path（来自 `SIGN URL`）
  2  H5 桥调用     页面→原生的动作跑了哪些、各几次（`H5BRIDGE` / `BRIDGE` / `PAGEREQ` / `H5RET`）
  3  桥守卫拦截    守卫拦了什么、为什么（`GUARD`）
  4  加解密活动    RC4 / 解密痕迹（`RC4 …` / `NET …` / `RC4PT`）
  5  广告位        广告位读取与广告位拦截（`ADSLOT …` / `blocked ad slot`）
  6  宿主侧观测    头 / 页面请求 / 导航 / 路由（`HDR` / `WEBREQ` / `NAV` / `ROUTE`）
  7  行为改变类    退出尝试、更新抑制、VIP、引导点击、去水印开关
                   （`EXITCALL` / `UPDATE` / `VIP` / `ONBOARD` / `WATERMARK`）
  8  覆盖          注册表当前有 N 个功能，本抓取看到了谁、没看到谁 ——
                   N 从 `FEATURE_IDS` 现算，不写死，所以加功能不会留下一个过期的 "28"
  9  验收面状态    四张验收面的最近留档（来自 `after_login.sh`）

**上面这份清单必须与代码里 `w('## N. …')` 的实际章节一一对应** ——
`tests/test_session_report_sections.py` 会比对，写错了会红。

（2026-11-04 修：这份 docstring 原来写的是 **1..9**，而代码的章节编号是 **0..9** ——
docstring 少算了"0 宿主版本"这一节，于是从第 1 项起每个名字都对到了**下一节**的内容上。
"文档说 A、代码做 B" 是本项目反复抓到的一类缺陷；这一条的特别之处是
**偏移一位**，比整段写错更难发现 —— 因为每一条单独看都像个合理的描述。）

All prefix knowledge comes from `capture_schema.py` — no substring guessing in this file, so a
new prefix shows up in §1 and §9 immediately instead of silently.

    adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
    python3 kit/python/session_report.py cap.txt --out work/session_report.md
"""
import argparse
import datetime
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from capture_schema import (  # noqa: E402
    FEATURES_LOGCAT_ONLY, FEATURES_WITH_CAPTURE, FEATURE_IDS, PREFIX_FEATURE, iter_records,
)

MAX_EXAMPLE = 8


def table(w, header, rows, limit=None):
    w('| ' + ' | '.join(header) + ' |')
    w('|' + '---|' * len(header))
    for r in (rows[:limit] if limit else rows):
        w('| ' + ' | '.join(str(c) for c in r) + ' |')
    w('')



def _bridge_detail(r) -> str:
    """把 BRIDGE 四个变体各自的关键字段摊平成一列。"""
    v = r.variant
    if v == 'download':
        return f'type={r.get("type")} url={r.get("url")}'
    if v == 'userinfo':
        return f'identity={r.get("identity")}'
    if v == 'payorder':
        # 字段名以 capture_schema._f_bridge_payorder 为准：`shape` 三态 + `keys` 是**列表**
        shape = r.get('shape') or '?'
        keys = r.get('keys')
        if shape == 'keys':
            names = ','.join(keys) if isinstance(keys, (list, tuple)) else str(keys)
            return f'len={r.get("len")} keys={len(names.split(",")) if names else 0}:{names} pid={r.get("pid")}'
        return f'len={r.get("len")} {shape} pid={r.get("pid")}'
    if v == 'decode':
        sd = r.get('shouldDecode')
        return (f'url={r.get("url")} shouldDecode={sd if sd is not None else "?"} '
                f'params={r.get("params") or "?"}')
    # 未知变体：把能拿到的字段全打出来，别静默塞进某个已知分支
    return str({k: val for k, val in (r.fields or {}).items() if val not in (None, '')})[:90]

def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('capture')
    ap.add_argument('--out', default=None)
    # `after_login.sh` 的留档：把"四张验收面最近验到什么程度"带进报告，
    # 免得报告读完还是不知道"还有哪些面没验过"（2026-11-02 加）。
    ap.add_argument('--login-log', default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'work', 'DEVICE_LOGIN_LOG.md'))
    a = ap.parse_args(argv[1:])

    kinds = Counter()
    spans = []
    recs = []
    unknown_reasons = Counter()
    for rec in iter_records(a.capture):
        kinds[rec.kind] += 1
        if rec.ts:
            spans.append(rec.ts)
        if rec.kind == 'UNKNOWN':
            unknown_reasons[rec.get('reason') or 'unknown'] += 1
        recs.append(rec)
    features = Counter(r.feature for r in recs if r.feature)

    def of(*want):
        return [r for r in recs if r.kind in want]

    out = []
    w = out.append
    w(f'# 会话报告 — {a.capture}\n')
    w(f'* 记录行：{len(recs)}，带时间戳：{len(spans)}'
      + (f'，时间跨度 {spans[0]} → {spans[-1]}' if spans else ''))
    w(f'* 记录种类：' + ', '.join(f'{k}×{v}' for k, v in kinds.most_common(10)))
    if kinds.get('UNKNOWN'):
        detail = ', '.join(f'`{k}`×{v}' for k, v in sorted(unknown_reasons.items()))
        w(f'* ⚠ **{kinds["UNKNOWN"]} 行没有任何规则认领**（{detail}）。'
          f'`new-prefix` 才需要补规则；`legacy-wrap` 是旧抓取里被换行撑开的残留，'
          f'新构建不会再产生。见 `kit/python/capture_schema.py`。')
    w('')

    # 0 宿主版本 —— **放在最前面**，因为它决定后面每一节的可信度。
    #
    # 为什么必须显眼：整套钩子建立在某一版 App 的混淆名上（`dj.a` / `di.a` / `vm.g`…）。
    # App 一自动更新，这些名字会变，表现是"功能静默失效"而不是崩溃 ——
    # 这是本模块最坏的故障形态。而抓取里其实**一直有**这行（`=== KdKit host=… baseline=…`），
    # 只是从来没有报告读它（2026-11-02 审查 D4）。
    w('## 0. 宿主版本\n')
    # MARK 的载荷字段叫 `text`（`_f_mark` 返回 `{'text': …}`），不是 `note` ——
    # 第一版写成 `note` 于是恒为空，报告一直说"没有版本行"（2026-11-02 当场抓到）。
    _host_marks = [r.get('text') or '' for r in of('MARK') if 'KdKit host=' in (r.get('text') or '')]
    if not _host_marks:
        w('* ⚠ **抓取里没有宿主版本行**（`=== KdKit host=…`）——'
          '这可能是旧构建、或模块没在这个进程里跑过。**本报告所有结论都无法确认属于哪个版本。**\n')
    else:
        # **先看全量，再取最后一条**（2026-11-02 改）。
        #
        # 旧实现只读 `_host_marks[-1]`：抓取跨了一次 App 升级时，报告会按**最后一个**版本
        # 下结论（"与基线一致 ✓"），而前面半份数据其实来自另一个版本 ——
        # 于是"某功能没有记录"到底是"没触发"还是"钩子没挂上"，判据被悄悄换掉了。
        _seen = {}
        for _mk in _host_marks:
            _mm = re.search(r'host=(\S+?)/(\S+?)\s.*?baseline=(true|false)', _mk)
            if _mm:
                _k = (_mm.group(1), _mm.group(2), _mm.group(3))
                _seen[_k] = _seen.get(_k, 0) + 1
        if len(_seen) > 1:
            _parts = '、'.join(f'**{v} ({c})**×{n}' for (v, c, b), n in
                              sorted(_seen.items(), key=lambda kv: -kv[1]))
            w(f'* ⚠ **这份抓取跨了 {len(_seen)} 个宿主版本**：{_parts}。'
              '下面各节的"有/没有记录"**不能**当作某一个版本的结论 —— '
              '没有记录的项可能只是那一半数据来自别的版本。\n')
        _last = _host_marks[-1]
        # 版本行形如 `KdKit host=7.9.0/1840 sdk=36 baseline=true` —— 中间还有 sdk=NN，
        # 所以不能要求 `/1840` 后面直接跟 `baseline`。
        _m = re.search(r'host=(\S+?)/(\S+?)\s.*?baseline=(true|false)', _last)
        if not _m:
            w(f'* ⚠ 版本行格式不认识：`{_last[:120]}`\n')
        else:
            _ver, _code, _base = _m.group(1), _m.group(2), _m.group(3)
            if _base == 'true':
                w(f'* 宿主 **{_ver} ({_code})**，与适配基线一致 ✓（{len(_host_marks)} 次启动记录）\n')
            else:
                w(f'* 🚨 **版本漂移**：宿主 **{_ver} ({_code})**，而钩子是按基线版本建的。'
                  '**混淆名可能已经挪位 ⇒ 下面各节的功能"没有记录"很可能不是"没触发"，而是钩子没挂上。**'
                  '先跑 `python3 kit/scripts/check_hook_targets.py`。\n')
    w('')

    # 1 endpoints
    w('## 1. 接口面（host / path 计数）\n')
    hosts, paths = Counter(), Counter()
    for r in of('SIGN_URL'):
        hosts[r.get('host')] += 1
        paths[r.get('path')] += 1
    if hosts:
        table(w, ('host', '次数'), hosts.most_common())
        table(w, ('path', '次数'), paths.most_common(), 25)
    else:
        w('_(无签名 URL：`sign_observer` 可能没开)_\n')

    # 2 bridge
    w('## 2. H5 桥调用（页面 → 原生）\n')
    bridge = Counter()
    for r in of('H5BRIDGE'):
        bridge[r.get('action')] = max(bridge[r.get('action')], r.get('count') or 0)
    if bridge:
        table(w, ('action', '次数'), bridge.most_common())
    else:
        w('_(无 H5BRIDGE 记录：`h5_bridge_log` 可能没开)_\n')

    sem = [r for r in of('BRIDGE')]
    if sem:
        w('### 2a. 语义层（`bridge_action_log`）\n')
        # 四个变体都要有分支。旧实现只认 download / 其它 ⇒ `payorder`（页面驱动下单）与
        # `decodeHttpRequest`（页面借宿主签名代发请求）被渲染成 `getuserinfo identity=None`，
        # 7 个已解析字段全丢。变体清单以 capture_schema 的 VARIANTS['BRIDGE'] 为准。
        rows = [(r.get('action'), r.variant or '?', _bridge_detail(r)[:90]) for r in sem]
        table(w, ('action', '变体', '详情'), rows, 20)
        w(f'_共 {len(sem)} 条；`downloadMedia` 的 `type != 1` 表示页面请求了但宿主不落盘；'
          '`payorder` 只记长度与键名（`payInfo` 的值从不进抓取）；'
          '`decodeHttpRequest` 的 URL 已剥 query。_\n')

    # 2a' 页面**代发请求**的来源归属（`PAGEREQ`）。与 2a 的分工：
    #     2a 回答"页面让宿主做什么语义动作"（存图/打听身份/下单），
    #     2a' 回答"哪个 action 让宿主把 HTTP 请求打到哪、GET 还是 POST"。
    #     两者的判据不同，混在一张表里会让"action"这一列有两种含义。
    preq = [r for r in of('PAGEREQ')]
    if preq:
        w("### 2a'. 页面代发请求（`PAGEREQ`，钩 `dr.f.a` 汇聚点）\n")
        by_src = Counter(r.get('from') for r in preq)
        table(w, ('发起方 action', '次数'), by_src.most_common())
        rows = [(str(r.get('from')),
                 {0: 'GET', 1: 'POST'}.get(r.get('method'), '?'),
                 str(r.get('url'))[:70],
                 str(r.get('params')))
                for r in preq]
        table(w, ('发起方', 'method', '目标（已剥 query）', 'params 形状'), rows, 20)
        w(f'_共 {len(preq)} 条。`from` 是发起请求的 action；`method` 为 `?` 表示取不到（不猜）。_\n')

    # 2b 出站返回值（`H5RET`）—— **原生 → 页面**的方向。
    #
    # 这一段以前完全不存在：`H5RET` 只在 `capture_transcript` 里逐行渲染，本报告只把它数进
    # §8 的覆盖表。后果是"页面拿到了什么"这个方向从未被汇总过 —— 而 2/2a 只覆盖
    # "页面请求了什么"。两个方向缺一个，桥的证据链就是断的。
    outbound = [r for r in of('H5RET')]
    if outbound:
        w('### 2b. 桥**出站**返回值（`H5RET`，原生 → 页面）\n')
        by_fun = Counter(r.get('cb') for r in outbound)
        table(w, ('回调', '次数'), by_fun.most_common())
        sizes = [r.get('len') or 0 for r in outbound]
        w(f'* 共 {len(outbound)} 次回传，载荷合计 {sum(sizes)} 字节，'
          f'最大 {max(sizes)} 字节（`len` 是**回传前**的长度；`body` 只保留前 400 字节）\n')
        bodies = [r for r in outbound if r.get('body')]
        if bodies:
            table(w, ('回调', '载荷（截断）'),
                  [(f'`{r.get("cb")}`', f'`{str(r.get("body"))[:80]}`') for r in bodies],
                  MAX_EXAMPLE)
        w('')

    # 3 guard
    w('## 3. 桥守卫拦截\n')
    guard, reason, ghost = Counter(), Counter(), Counter()
    for r in of('GUARD'):
        guard[r.get('action')] += 1
        reason[r.get('reason')] += 1
        ghost[r.get('host')] += 1
    if guard:
        w('按原因：' + ', '.join(f'`{k}`×{v}' for k, v in reason.most_common()) + '\n')
        table(w, ('action', '次数'), guard.most_common())
        table(w, ('目标 host', '次数'), ghost.most_common())
    else:
        w('_(没有拦截记录：`bridge_guard` 未开、未命中，或该轮确实没有该拦的流量)_\n')

    # 4 crypto
    w('## 4. 加解密活动\n')
    ops = Counter()
    for r in of('RC4'):
        ops[f'RC4 {r.get("op")}'] += 1
    for r in of('NET', 'H5'):
        ops[f'{r.kind} {r.get("prim") or r.get("op")} {r.get("dir")}'] += 1
    for r in of('RC4PT', 'RC4UP'):
        ops[f'{r.kind}{"(nontext)" if r.variant == "nontext" else ""}'] += 1
    keys = {r.get('key') for r in of('RC4KEY', 'RC4KEYSTR') if r.get('key')}
    if ops or keys:
        if keys:
            w(f'* 密钥：{len(keys)} 把（`RC4KEY b(<vc>)` / `RC4KEY refreshed` / `RC4KEYSTR` / `RC4KEY` 合并去重）\n')
        table(w, ('操作', '次数'), ops.most_common())
    else:
        w('_(无加解密记录)_\n')

    plaintexts = [r.get('text') for r in of('RC4PT') if r.variant is None]
    if plaintexts:
        w('### 4a. 设备侧解出的明文（`RC4PT`，样例）\n')
        table(w, ('#', '明文（截断）'), [(i, f'`{v[:90]}`') for i, v in enumerate(plaintexts[:MAX_EXAMPLE], 1)])
        w(f'_共 {len(plaintexts)} 条；这类是响应里被解出来的书名 / 图片 URL / 配置文本。_\n')

    # 5 ads
    adc, adr = Counter(), Counter()
    blocked_ad = 0
    for r in of('ADSLOT_CALL'):
        adc[f'{r.get("method")}({r.get("pos")})'] += 1
    for r in of('ADSLOT_RET'):
        adr[f'{r.get("method")}({r.get("pos")}) -> {r.get("shown")}'] += 1
    blocked_ad = kinds.get('AD_BLOCK', 0)
    # `ADBLOCK` —— **拦截成功**的次数（2026-11-02 加）。
    # 与 `AD_BLOCK`（读数被拦）分开数：前者证明钩子真的触发并改写了结果，
    # 后者只是"宿主来问过一次"。少了前者，广告面（C1）永远只能给"无法验证"。
    adblock = Counter(f'{r.get("cls")}.{r.get("method")} -> {r.get("result")}'
                      for r in of('ADBLOCK'))
    # 条件是 `adc or adr or blocked_ad`，**不能**漏 `adr`：
    # 轮转把 `ADSLOT call` 切掉、只留下 `ADSLOT ret` 时，整节会消失，
    # 于是"某广告位返回了 false"这条唯一还剩的证据被静默丢掉。
    if adc or adr or blocked_ad or adblock:
        w('## 5. 广告位\n')
        if adc or adr:
            calls, rets = sum(adc.values()), sum(adr.values())
            w(f'* 调用 {calls} 次，返回记录 {rets} 次'
              + (f'；**有 {calls - rets} 次没有返回行**'
                 f'（被短路，或该键的写入上限到了）' if calls > rets else '') + '\n')
            if adc:
                table(w, ('位号', '调用次数'), adc.most_common())
            if adr:
                table(w, ('返回', '次数'), adr.most_common(), 15)
            if not adc:
                w('* ⚠ 只有返回行、没有调用行：多半是轮转把前面切掉了。'
                  '返回值的分布本身仍然有效（`false` = 该位没展示）\n')
        if blocked_ad:
            w(f'* `rm_adconfig` 直接拦下 {blocked_ad} 次广告位读取（`blocked ad slot read`）\n')
        if adblock:
            w(f'* `rm_adconfig` 改写过广告判定 {sum(adblock.values())} 次'
              f'（`ADBLOCK`，即钩子真的触发并写回了结果）：\n')
            table(w, ('判定', '次数'), adblock.most_common(10))

    # 6 host
    w('## 6. 宿主侧观测（头 / 页面请求 / 导航 / 路由）\n')
    hdr = Counter(r.get('variant') for r in of('HDR'))
    webreq = [r for r in of('WEBREQ')]
    naves = [r for r in of('NAV')]
    navact = [r for r in of('NAVACT')]
    routes = [r for r in of('ROUTE')]
    if not (hdr or webreq or naves or navact or routes):
        w('_(这些功能默认关，本抓取里没有记录)_\n')
    if hdr:
        w(f'* 请求头观测 `HDR`：' + ', '.join(f'{k}×{v}' for k, v in hdr.most_common()) + '\n')
    if webreq:
        w(f'* 页面自有请求 `WEBREQ`：{len(webreq)} 条，{len({r.get("url") for r in webreq})} 个不同 URL\n')
        table(w, ('URL（截断）', '头数'),
              [(f'`{str(r.get("url"))[:80]}`', len(r.get('header_names') or [])) for r in webreq],
              MAX_EXAMPLE)
    if naves or navact:
        w(f'* 导航：H5 页面 {len(naves)} 个，原生 Activity {len(navact)} 个\n')
        if naves:
            table(w, ('页面', 'URL'), [(f'`{r.get("page")}`', f'`{str(r.get("url"))[:70]}`') for r in naves],
                  MAX_EXAMPLE)
        if navact:
            w('  Activity：' + ', '.join(f'`{r.get("activity")}`' for r in navact[:12]) + '\n')
    if routes:
        w(f'* 路由 `ROUTE`：{len(routes)} 条，{len({r.get("route") for r in routes})} 个不同路由\n')
        table(w, ('路由', '调用方'), [(f'`{r.get("route")}`', f'`{r.get("from")}`') for r in routes],
              MAX_EXAMPLE)

    # 6b 请求体 / 响应体（`http_body_probe`）
    #
    # 这一段以前不存在：`REQBODY` / `RESPBODY` 只在 `capture_transcript` 里逐行渲染，
    # 本报告只把它们数进 §8。后果是**接口面只有 URL、没有载荷** —— 而
    # `bridge_inventory` 的 2a 已经能说明"页面要什么"，6b 才是"宿主实际发了/收了什么"。
    #
    # 四种形态分开统计，不能合并成一个"body 条数"：
    #   `params`  —— 表单参数（**绝大多数请求的真实 body 在这里**）
    #   `json`    —— `__jsonBody`（**加密前**，全 APK 只有两处写入）
    #   `text`    —— `getBody()` 解出的文本（编码后）
    #   `bin`     —— 二进制，只记长度（上传的图片/文件，故意不记内容）
    #   `unreadable` —— volley 字段名变了，必须显式报出来，否则"没记到"看起来像"没有 body"
    reqb, respb = of('REQBODY'), of('RESPBODY')
    if reqb or respb:
        w('### 6b. 请求体 / 响应体（`http_body_probe`）\n')
        # 循环变量**不能**叫 `recs`：那是 main() 顶层的"全部记录"列表，§7b 与 §8 都靠它。
        # 2026-10-25 本轮真的踩了一次 —— 覆盖它之后 `of()` 对所有 kind 都返回空，
        # 报告**静默丢掉整节 §7b**（没有异常、没有告警，只是那节不见了）。
        # 这类"变量遮蔽导致输出缺节"只能靠断言"每个节标题都在输出里"发现，见
        # `test_parsers_cli.py::ReportSectionsPresent`。
        for label, batch in (('请求', reqb), ('响应', respb)):
            if not batch:
                continue
            by_var = Counter(r.variant for r in batch)
            w(f'* {label}体 {len(batch)} 条：'
              + ', '.join(f'`{k}`×{v}' for k, v in sorted(by_var.items())) + '\n')
            if by_var.get('unreadable'):
                # 这是**我们看不见**，不是"对方没发"。必须点名，否则会被读成空 body。
                w(f'  * ⚠ {by_var["unreadable"]} 条响应**读不到 body 字段**'
                  f'（volley 字段名变了）—— 不是"响应为空"，是探针失效\n')
        params = [r for r in reqb if r.variant == 'params']
        if params:
            # `n` 是表单参数**总个数**；`kv` 只带前若干项，`omitted` 是其余数量。
            who = Counter(r.get('who') for r in params)
            table(w, ('参数归属（__pid）', '次数'), who.most_common(15))
            total_n = sum(r.get('n') or 0 for r in params)
            w(f'* 表单参数合计 {total_n} 个键（{len(params)} 次请求），'
              f'最多的一次 {max(r.get("n") or 0 for r in params)} 个\n')
        texts = [r for r in reqb + respb if r.variant in ('text', 'json') and r.get('body')]
        if texts:
            w('* 可读载荷样例（**明文**；`REQBODY json` 是加密前的原文，`RESPBODY text` 是解密后）：\n')
            table(w, ('方向', '载荷（截断）'),
                  [(r.kind, f'`{str(r.get("body"))[:80]}`') for r in texts], MAX_EXAMPLE)
        bins = [r for r in reqb + respb if r.variant == 'bin']
        if bins:
            sizes = sorted((r.get('len') or 0) for r in bins)
            w(f'* 二进制载荷 {len(bins)} 条，合计 {sum(sizes)} 字节，'
              f'最大 {sizes[-1]} 字节（**只记长度，不记内容** —— 上传的图片/文件）\n')
        w('')

    # 7 behaviour
    w('## 7. 行为改变类功能的痕迹\n')
    exits = [r for r in of('EXITCALL')]
    updates = [r for r in of('UPDATE')]
    vips = [r for r in of('VIP')]
    onboard = [r for r in of('ONBOARD')]
    applogs = [r for r in of('APPSIGN')]
    promos = [r for r in of('PROMO')]
    md3s = [r for r in of('MD3')]
    # 设置页里那一行「KdKit 模块设置」被点中 ⇒ 模块设置页起来了（`settings_entry`）。
    settings = [r for r in of('SETTINGS')]
    marks = [r for r in of('WATERMARK')]
    # `EXITSTACK #n <栈>` 是**另一个前缀**、另一个 feature-visible 事实：它记的是
    # "从哪条调用链退出的"。早先这里只取 `EXITCALL`，于是栈信息**整类被丢掉** ——
    # 报告读起来像"这个功能不记栈"，而模块其实写了。
    stacks = {r.get('seq'): r.get('stack') for r in of('EXITSTACK')}
    # 家长模式读/写侧。两侧共同说明"服务端 AB 给这个账号下发了哪几个闸门"，
    # 而 `unavailable` 变体说明"钩子执行了但数据拿不到" —— 后者比"没有这一行"有用：
    # 前者是"钩到了读不到"，后者只能猜是没触发还是失效。
    pctrl = [r for r in of('PCTRL')]
    pctrlw = [r for r in of('PCTRLW')]
    # 原生退出守卫的**自证**：seccomp 不回报命中次数，所以"装上了"和"真的拦住了"
    # 是两件事。`selfTest=1` 才是"拦住过"的活证据（`0` = 装了但内核不支持）。
    nexits = [r for r in of('NEXIT')]
    if not (exits or updates or vips or onboard or applogs or marks or stacks
            or pctrl or pctrlw or nexits):
        w('_(没有记录：`exit_guard` 未命中、`skip_update`/`vip_unlock`/`skip_onboarding` 默认关)_\n')
    if nexits:
        last = nexits[-1]
        verdict = {1: '已拦住', 0: '装上了但没拦住', -1: '未安装', -2: '对照组', -3: '调用失败'}
        st = last.get('selfTest')
        w(f'* `native_exit_guard`：installed=`{last.get("installed")}` '
          f'control=`{last.get("control")}` selfTest=**{verdict.get(st, st)}** '
          f'selfProof={last.get("selfProof")}（共 {len(nexits)} 次记录）\n')
        if st == 0:
            w('  * ⚠ **过滤器装上了但自证没拦住 `exit_group`** —— 别把"进程没死"当成功，'
              '那种情况下宿主是出于别的原因活着。\n')
    if pctrl or pctrlw:
        for label, rows in (('PCTRL', pctrl), ('PCTRLW', pctrlw)):
            if not rows:
                continue
            unavailable = [r for r in rows if r.get('reason')]
            if unavailable:
                rs = ', '.join(sorted({str(r.get('reason')) for r in unavailable}))
                w(f'* `{label}`：{len(rows)} 条，其中 **{len(unavailable)} 条读不到**'
                  f'（reason={rs}）—— 钩子执行了但家长模式数据拿不到\n')
            ok = [r for r in rows if not r.get('reason')]
            if ok:
                r0 = ok[0]
                w(f'* `{label}`：{len(ok)} 条有数据，首条 mask=`{r0.get("mask")}` '
                  f'aiwriting={r0.get("aiwriting")} book={r0.get("book")} '
                  f'correctsearch={r0.get("correctsearch")} picsearch={r0.get("picsearch")}\n')
    if exits:
        blocked = sum(1 for r in exits if r.get('blocked'))
        w(f'* `exit_guard`：{len(exits)} 次退出调用，其中**真拦下 {blocked}** 次、'
          f'只记录 {len(exits) - blocked} 次\n')
        table(w, ('#', '位置', '拦?'),
              [(r.get('seq'), f'`{str(r.get("where"))[:70]}`', 'Y' if r.get('blocked') else 'N')
               for r in exits], MAX_EXAMPLE)
    if stacks:
        # 按 seq 配到对应的 EXITCALL 上，配不上就单独列（轮转/截断时会发生）。
        if exits:
            matched = sum(1 for r in exits if r.get('seq') in stacks)
            w(f'* `exit_guard` 的调用栈：{matched}/{len(exits)} 条带栈（`EXITSTACK`），'
              f'共 {len(stacks)} 条栈记录\n')
        else:
            # 只留了栈、没留 EXITCALL —— 轮转把前者切掉了。仍然要显示：
            # 它单独就能回答"谁在调 System.exit"，是这一节最有用的证据之一。
            w(f'* `exit_guard` 的调用栈：{len(stacks)} 条（本抓取没有对应的 `EXITCALL`，'
              f'多半是轮转截断；栈本身仍然有效）\n')
        table(w, ('#', '栈（首两层）'),
              [(seq, f'`{str(st).split("⏎")[0].strip()[:80]}`')
               for seq, st in sorted(stacks.items(), key=lambda kv: str(kv[0]))],
              MAX_EXAMPLE)
        orphan = sorted(set(stacks) - {r.get('seq') for r in exits}, key=str)
        if orphan and exits:
            w(f'  * ⚠ 这 {len(orphan)} 条栈找不到对应的 `EXITCALL`（轮转/截断的正常形态，'
              f'不代表功能坏了）：{", ".join(f"#{s}" for s in orphan[:8])}\n')
    if updates:
        table(w, ('模式', '详情'),
              [(r.get('mode'),
                f'forceUp {r.get("before")}→{r.get("after")}' if r.get('mode') == 'forceup' else '入口已抑制')
               for r in updates])
    if vips:
        w(f'* `vip_unlock`：{len(vips)} 次判定被改写（**只有客户端结论，服务端未验证**）\n')
    if promos:
        events = sorted({str(r.get('event')) for r in promos})
        w(f'* `rm_vip_promo`：拦下 {len(promos)} 次会员推广（{", ".join(events[:4])}）\n')
    if md3s:
        events = sorted({str(r.get('event')) for r in md3s})
        w(f'* `md3_skin`：外观覆盖生效 {len(md3s)} 次（{", ".join(events[:4])}）\n')
    if settings:
        events = sorted({str(r.get('event')) for r in settings})
        w(f'* `settings_entry`：设置页入口命中 {len(settings)} 次（{", ".join(events[:4])}）\n')
    if onboard:
        w(f'* `skip_onboarding`：点过 {len(onboard)} 次，'
          f'成功 {sum(1 for r in onboard if r.get("ok"))} 次\n')
        table(w, ('文案', 'label', '#', 'ok'),
              [(f'`{r.get("text")}`', r.get('label'), r.get('seq'), r.get('ok')) for r in onboard],
              MAX_EXAMPLE)
    if applogs:
        w(f'* `log_sink` 收录了 {len(applogs)} 行宿主日志（tag 前 8：'
          + ', '.join(f'`{t}`' for t, _ in Counter(r.get('tag') for r in applogs).most_common(8)) + '）\n')
    if marks:
        # 只记"代用户按了开关"，产物是否真的无水印要真机对比 —— 报告不能把它读成"已生效"。
        w(f'* `watermark_off`：{len(marks)} 次把 App 自带的去水印开关置为开'
          f'（**只证明钩子执行过；产物与计次未验证**）\n')

    # 7a 热修复补丁面 —— **这一节回答的是"上面所有结论还算不算数"**
    #
    # 为什么它必须有自己的汇总、而不只是逐行渲染：`ROBUST` 的三个字段是三种不同结论，
    # 混着数就失去意义。
    #   redirect=false      ⇒ 这个类**根本没被补丁碰过**，`supported=false` 是正常；
    #   supported=true      ⇒ 这一次真被接管，**原方法体没执行** ⇒ 依赖它的功能结论作废；
    #   supported=?         ⇒ 读不到，**不等于**没接管。
    # 所以计数必须三者分开，且"有分派器"与"真被接管"是两个不同的分母。
    robust = of('ROBUST')
    # 注意：`Record.get()` 只查 `fields`，`variant` 是**记录属性**而不是字段 ——
    # 用 `r.get('variant')` 会永远得到 None（本节第一版就是这么写的，
    # 于是整节静默消失、而 `test_every_kind_is_actually_analysed` 立刻报"抓到了没人读"）。
    rpatch = [r for r in robust if r.variant == 'patch']
    rstack = [r for r in robust if r.variant == 'stack']
    if rpatch:
        w('## 7a. 热修复补丁面（其结论影响本报告其它各节）\n')
        taken = [r for r in rpatch if r.get('supported') is True]
        untouched = [r for r in rpatch if r.get('redirect') is False]
        armed = [r for r in rpatch if r.get('redirect') is True]
        unknown = [r for r in rpatch if r.get('supported') is None and r.get('redirect') is not False]
        w(f'* 观测到 {len(rpatch)} 次补丁分派：**真被接管 {len(taken)}**、'
          f'有分派器但本次未接管 {len(armed) - len(taken)}、'
          f'未被补丁涉及 {len(untouched)}、接管状态未知 {len(unknown)}\n')
        if taken:
            # 这是本节最要紧的一句话：被接管 = 原方法体没跑。
            w(f'* ⚠ **{len(taken)} 个方法被补丁接管 ⇒ 它们的原方法体没有执行。**'
              f'任何以"钩到原方法体"为前提的结论（改返回值 / 改字段 / 读回包）'
              f'在这一轮**不成立**，请对照 `kit/scripts/check_robust_coverage.py` 的静态暴露面\n')
            table(w, ('类', '#', 'supported', 'redirect'),
                  [(f'`{str(r.get("who"))[:60]}`', r.get('method_no'),
                    r.get('supported'), r.get('redirect')) for r in taken], MAX_EXAMPLE)
        elif untouched and not armed:
            w('  * 全部都是 `redirect=false`：本轮**没有任何补丁涉及**这些类，'
              '静态结论不受影响（这是"没有补丁"的证据，不是"补丁无效"）\n')
    if rstack:
        table(w, ('类', '#', '调用方（前几层）'),
              [(f'`{str(r.get("who"))[:50]}`', r.get('method_no'),
                f'`{str(r.get("stack"))[:80]}`') for r in rstack], MAX_EXAMPLE)

    # 7b 三类"只有逐行渲染、没有汇总"的观测
    #
    # 这三个前缀（`POPWIN` / `NETERR` / `VIPLIMIT`）此前**完全只活在
    # `capture_transcript.py` 的逐行渲染里**：本报告只在 §8 的覆盖表数了它们一行。
    # 后果是"功能抓到了，但没有任何一处回答'抓到了什么形状'"——
    # 而这三个恰好都是"分布本身就是结论"的观测：
    #   POPWIN   —— 服务端下发哪几类弹窗（决定拦截清单够不够）
    #   NETERR   —— 失败原因分布（决定是不是签名/限流问题）
    #   VIPLIMIT —— 允许/拒绝的比例（决定额度策略）
    #
    # ⚠ 变量名纪律：main() 顶层的 `recs` 是**全部记录**，`of()` 依赖它。
    # 在本函数里用 `recs` 作循环变量会静默清空后续所有 `of()` —— 本轮踩过一次。
    popwin = of('POPWIN')
    neterr = of('NETERR')
    viplim = of('VIPLIMIT')
    if popwin or neterr or viplim:
        w('## 7b. 分布型观测（弹窗 / 失败原因 / 额度判定）\n')
    if popwin:
        # `block` = 本来该不该拦；`action` = 实际做了什么。两列必须并排：
        # `OBSERVE` 就是 block=True 而 action≠BLOCK 的那一格 —— 合并成一列就再也
        # 看不出 observe_only 到底有没有生效。
        types = Counter(r.get('type') for r in popwin)
        acts = Counter(r.get('action') for r in popwin)
        w(f'* `popwin_gate`：{len(popwin)} 次分派，{len(types)} 种类型\n')
        table(w, ('服务端类型', '次数'), types.most_common())
        table(w, ('最终动作', '次数'), acts.most_common())
        hit = [r for r in popwin if r.get('block')]
        real = [r for r in popwin if r.get('blocked')]
        w(f'* 命中拦截清单 {len(hit)} 次，**真的拦下 {len(real)}** 次\n')
        # 三种情况必须分开说，不能都写成"差 N 次 = observe_only 生效"：
        #   命中 0 次      ⇒ 没有样本能证明拦截清单对不对（**不是** observe_only 的证据）
        #   命中 > 拦下    ⇒ 这一格才是 observe_only 生效的证据
        #   命中 == 拦下   ⇒ 要么没开 observe_only，要么开了但样本恰好没覆盖到
        # 第一版无条件打印"差 N 次 = observe_only 开着"，命中 0 次时会说
        # "差 0 次 = observe_only 开着，只记录未拦" —— 一句与事实无关的话。
        if not hit:
            w('  * 本次**没有一次命中拦截清单**：`observe_only` 是否生效无法由这份样本判断'
              '（缺的是"命中"这个前提，不是差值为零）\n')
        elif len(hit) != len(real):
            w(f'  * 差 {len(hit) - len(real)} 次 = `observe_only` 开着，命中后只记录未拦 —— '
              f'**这正是该模式生效的证据**；若两者恒等，反而说明它没起作用\n')
        else:
            w('  * 命中数 == 拦下数：可能没开 `observe_only`，也可能开了但本次样本没覆盖到'
              '（抓取里没有"开关状态"字段，无法区分这两者）\n')
        w('  * **未验证**：真机上被拦的弹窗是否真的不出现 —— 需要设备（本仓库当前'
          '没有可加载的 Xposed 框架，见 `module/OPTIMIZATION.md` §7）\n')
    if neterr:
        nos = Counter(str(r.get('no')) for r in neterr)
        codes = Counter(r.get('code') for r in neterr if r.get('code'))
        w(f'* `net_error_probe`：{len(neterr)} 次失败\n')
        table(w, ('errNo', '次数'), nos.most_common())
        if codes:
            table(w, ('错误码文案', '次数'), codes.most_common())
        w('  * `no` 是宿主给的 errNo；`code` 是它附带的中文文案。二者**都不是** HTTP 状态码 ——'
          '协议层的失败（超时/断连）不会产生 `NETERR` 行，所以这份分布只覆盖"服务端明确拒绝"那一类。\n')
    if viplim:
        asks = [r for r in viplim if r.variant == 'ask']
        results = [r for r in viplim if r.variant == 'result']
        w(f'* `vip_limit_probe`：{len(asks)} 次询问 / {len(results)} 次判定\n')
        if asks:
            table(w, ('产品', '已用次数'),
                  [(f'`{r.get("product")}`', r.get('used')) for r in asks], MAX_EXAMPLE)
        if results:
            allowed = sum(1 for r in results if r.get('allowed'))
            w(f'  * 允许 {allowed} 次 / 拒绝 {len(results) - allowed} 次\n')
            table(w, ('允许?', '剩余'),
                  [('Y' if r.get('allowed') else 'N', r.get('remaining')) for r in results],
                  MAX_EXAMPLE)
        paired = 0
        if asks and results:
            paired = min(len(asks), len(results))
            w(f'  * 询问与判定按出现顺序配对 {paired} 对（**不是**按请求 id —— 抓取里没有 id，'
              f'并发请求时这个配对可能错位，只作粗略对照）\n')
        w('  * **未验证**：客户端判定与服务端授权是否一致 —— 观测不改行为，'
          '要确认只能真机抓包看服务端返回\n')

    # 7c 签名链的四段观测（`SIGN_PARAMS` / `SIGN_RESULT` / `SIGNPARAM` / `FORMULA`）
    #
    # 这四类此前**只被计数**：`SIGN_URL` 有 §1（接口面）、`RC4*` 有 §4，
    # 但"签名到底是怎么算出来的"这一链路的中间三段完全没人汇总。
    # 而这四段拼起来才知道签名能不能离线复现：
    #   `SIGN_PARAMS` —— 参与签名的参数**键集合**（服务端也用同一份）
    #   `SIGN_RESULT` —— 算出来的 sign 值
    #   `SIGNPARAM`   —— 原生层拿到的 param/sign（对应关系）
    #   `FORMULA`     —— 原生公式的 A / X 常量
    # 缺任一段，"能不能离线算对"就只能靠猜。
    #
    # 注意：**只汇总形状，不回放值**。`sign` 是 `f(params+secret)` 的结果，
    # 把它当"可复现样例"贴进报告等于泄露一份输入/输出对（见
    # `OPTIMIZATION.md` §7 的凭证脱敏那一节）。
    sign_params = of('SIGN_PARAMS')
    sign_result = of('SIGN_RESULT')
    signparam = of('SIGNPARAM')
    formula = of('FORMULA')
    if sign_params or sign_result or signparam or formula:
        w('## 7c. 签名链的四段（参数 → 结果 → 原生 → 公式）\n')
        if sign_params:
            counts = Counter(r.get('count') for r in sign_params)
            w(f'* `SIGN_PARAMS`：{len(sign_params)} 次，参数个数分布 '
              + ', '.join(f'`{k} 个`×{v}' for k, v in sorted(counts.items(),
                                                              key=lambda kv: str(kv[0]))) + '\n')
            # 键集合的**并集**是复现签名的必需输入；只给键名，不给值。
            keys = Counter()
            for r in sign_params:
                for k in (r.get('keys') or []):
                    keys[k] += 1
            if keys:
                w('  * 出现过的参数键（**只记名，不记值**）：'
                  + ', '.join(f'`{k}`' for k, _ in keys.most_common(20)) + '\n')
                w(f'  * 共 {len(keys)} 个不同键；每份样本里恒有的键 = '
                  + ', '.join(f'`{k}`' for k, v in keys.items() if v == len(sign_params))
                  + '（其余键是可选/按接口变化）\n')
        if sign_result:
            w(f'* `SIGN_RESULT`：{len(sign_result)} 个 sign（**不回放值**；'
              f'`sign = f(params + secret)`，贴出来等于泄露一份输入/输出对）\n')
        if signparam:
            # `SIGNPARAM` / `FORMULA` 的 param 是 base64 后的原文，sign 是结果。
            w(f'* `SIGNPARAM`（原生层）：{len(signparam)} 次，'
              f'param 长度分布 '
              + ', '.join(f'`{k}`×{v}' for k, v in
                          Counter(len(str(r.get("param") or "")) for r in signparam).most_common(5))
              + '\n')
        if formula:
            # 变量名**不能**用 `a`：那是 `ap.parse_args()` 的结果（`a.out` 等）。
            # 本轮踩过一次 —— 覆盖后脚本在收尾处 `AttributeError: 'Counter' object
            # has no attribute 'out'`，而所有中间断言仍然通过。
            a_consts = Counter(r.get('a') for r in formula)
            x_consts = Counter(r.get('x') for r in formula)
            w(f'* `FORMULA`（原生公式）：{len(formula)} 次\n')
            table(w, ('A 常量', '次数'), a_consts.most_common(8))
            table(w, ('X 常量', '次数'), x_consts.most_common(8))
            w('  * A / X 是公式里的常量；换版后它们变不变，是"算法是否被改"的第一手信号\n')
        w('')

    if popwin or neterr or viplim or sign_params or sign_result or signparam or formula:
        w('')

    # 8 coverage
    w(f'## 8. 覆盖：{len(FEATURE_IDS)} 个功能里，本抓取看到了谁\n')
    w(f'* 有抓取能力的功能 {len(FEATURES_WITH_CAPTURE)} 个，本轮出现 '
      f'{len([f for f in FEATURES_WITH_CAPTURE if features.get(f)])} 个')
    rows = [(f'`{f}`', features.get(f, 0)) for f in FEATURES_WITH_CAPTURE]
    table(w, ('feature', '抓取行数'), sorted(rows, key=lambda r: -r[1]))
    missing = [f for f in FEATURES_WITH_CAPTURE if not features.get(f)]
    if missing:
        # **必须把"不可能出现"和"应该出现但没有"分开** —— 这是本项目反复踩的误读点：
        # 一份 2026-10-18 的抓取里，2026-10-25 才加的功能必然是 0 行，
        # 而报告若只写"可能是钩子失效"，读的人会去查一个根本不存在的问题。
        #
        # 判据是**样本时间**：抓取最后一行的时刻早于功能加入的时刻 ⇒ 结构性 0。
        # 拿不到时间就无法判断，此时明确写"无法区分"，不假装知道。
        first_ts = min((r.ts for r in recs if r.ts), default=None)
        last_ts = max((r.ts for r in recs if r.ts), default=None)
        w('* **本抓取里没有行**（三种原因，本报告无法区分是哪一种）：'
          + ', '.join(f'`{f}`' for f in missing) + '\n')
        w('  * 功能没开（`defaultOn=false` 的默认就没开）；')
        w('  * 开了但这条路径没被走到；')
        w('  * 钩子失效（类/方法改名）。')
        if last_ts:
            w(f'  * 若样本采集时间（{last_ts}）早于该功能的加入时间，'
              f'则为**结构性 0**，不是失效。对照 `module/ACTIVITY.md` §四 的日期表。')
        w('')
    w(f'* 只写 logcat、不写抓取的功能（{len(FEATURES_LOGCAT_ONLY)} 个，'
      f'本报告结构上无法证明它们工作）：' + ', '.join(f'`{f}`' for f in FEATURES_LOGCAT_ONLY) + '\n')
    unknown_feats = [f for f in features if f not in FEATURE_IDS]
    if unknown_feats:
        w(f'* ⚠ 抓取里出现了未知 feature id：{unknown_feats}\n')

    # 9 四张验收面的最近状态 -------------------------------------------------
    # 为什么放进报告：上面 §8 只回答"这份抓取里出现了谁"，回答不了
    # **"这个仓库现在到底验过什么"**。后者来自 `after_login.sh` 的留档。
    # 判据必须是"最近一次"，且要说出它有多旧 —— 一份 3 天前的"已验证"
    # 不能当作今天的结论（宿主升一次级就可能全变）。
    w('## 9. 四张验收面的最近状态（来自 after_login.sh 的留档）\n')
    log = a.login_log
    if not os.path.isfile(log):
        w('* ⚠ **没有留档**：`after_login.sh` 从未跑过 ⇒ '
          '**这个仓库的"验过什么"目前没有机器可读的结论**。\n')
    else:
        try:
            with open(log, encoding='utf-8') as _f:
                _blocks = re.findall(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
                                     r'\s+serial=(\S+)\s+宿主=(\S+)\s+rc=(\d+)\n'
                                     r'\n```\n(.*?)```', _f.read(), re.S | re.M)
        except OSError:
            _blocks = []
        if not _blocks:
            _rel = os.path.relpath(log)
            w(f'* ⚠ 留档存在（`{_rel}`）但解析不出结果块（格式变了？）\n')
        else:
            _ts, _ser, _host, _rc, _tbl = _blocks[-1]
            try:
                _age = (datetime.datetime.now() - datetime.datetime.strptime(
                    _ts, '%Y-%m-%d %H:%M:%S')).days
                _age_s = f'{_age} 天前' if _age else '今天'
            except ValueError:
                _age_s = '时间戳不认识'
            w(f'* 最近一次：**{_ts}**（{_age_s}），serial `{_ser}`，宿主 `{_host}`，'
              f'退出码 `{_rc}`')
            _verdict = {'0': '四个面**全部已验证**',
                        '2': '仍有面**无法验证**（不是失败，也**不是通过**）'}.get(
                           _rc, f'工具异常（rc={_rc}）')
            w(f'* 当时的总判定：{_verdict}\n')
            _rows = [ln for ln in _tbl.splitlines() if ln.startswith('| C')]
            if _rows:
                w('| 面 | 当时结论 | 证据 |')
                w('|---|---|---|')
                for _ln in _rows:
                    w(_ln)
                w('')
            if _age >= 3:
                w(f'* ⚠ 这次留档已经 **{_age} 天** 了。四张面都依赖宿主版本与设备状态，'
                  '升级一次 App 就可能全变 —— **重跑** '
                  '`./kit/scripts/after_login.sh` 再读这里的结论。\n')
    w('')

    text = '\n'.join(out) + '\n'
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[report] -> {a.out}  ({len(recs)} lines in, {len(text)} B out)')
        print('\n'.join(out[:6]))
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
