#!/usr/bin/env python3
"""
kuaidui-kit / capture_transcript.py — turn a KdKit capture into a readable transcript of what
the app actually sent, received, decrypted, blocked and clicked.

Input: `files/kdkit_capture.txt` (pulled from the host app's private dir), one line per event:

    HH:MM:SS.mmm <prefix> <body>

Every prefix is decoded through `capture_schema.py` — the single declaration of the module's
capture format — so a prefix this script has never heard of shows up as `UNKNOWN` with its raw
text, instead of vanishing from the transcript.

What gets special treatment (the count is **derived**, never restated here —
see `len(FEATURE_IDS)`; this line used to say "28" after the registry had 33):

  * `RC4 encrypt|decrypt …` — **decrypted on the fly** with `kd_crypto.py`, using the key that
    is inside the line (the app's own live key);
  * `RC4PT <text>` / `RC4PT(nontext) len=… b64=…` — RC4Probe's plaintext view, both shapes;
    the non-text form is printed as a byte count, never as a bogus string;
  * `SIGN URL` — split into host / path / query, signature triple highlighted;
  * `SIGN params` — summarised as a key list (full list stays in the capture);
  * `EXITCALL` / `EXITSTACK` — paired so "who called exit" reads as a block, not two orphans;
  * `BRIDGE` / `VIP` / `UPDATE` / `ONBOARD` / `GUARD` / `WEBREQ` / `HDR` / `WATERMARK` /
    `POPWIN` — one readable row each;
  * everything else — printed as-is, truncated.

    adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
    python3 capture_transcript.py cap.txt > transcript.md
"""
import base64
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from capture_schema import iter_records  # noqa: E402
from kd_crypto import rc4  # noqa: E402

MAX = 180


def pretty(b: bytes) -> str:
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b[:32].hex() + f'… ({len(b)} B)'


def one_line(rec) -> str:
    """Render exactly one record. Unknown records keep their raw body."""
    ts = rec.ts or '--:--:--.---'
    f, kind, var = rec.fields, rec.kind, rec.variant

    if kind == 'RC4':
        key = base64.b64decode(f.get('key_b64') or '')
        try:
            got = rc4(key, base64.b64decode(f.get('in_b64') or ''))
        except Exception as e:                       # truncated line pulled mid-write
            return f'- `{ts}` **RC4 {f.get("op")}** _(undecodable: {e})_'
        return (f'- `{ts}` **RC4 {f.get("op")}** → `{pretty(got)}`  '
                f'_(key {len(key)} B, ct {f.get("in_len")} B)_')

    if kind == 'SIGN_URL':
        return (f'- `{ts}` **SIGN URL** `{f.get("host")}{f.get("path")}` '
                f'`sign={f.get("sign")} t={f.get("_t_")} kak={f.get("kakorrhaphiophobia")}` '
                f'({f.get("query_count")} query field(s))')

    if kind == 'SIGN_PARAMS':
        keys = f.get('keys') or []
        return (f'- `{ts}` **SIGN params** ({f.get("count")}): `{", ".join(keys[:14])}`'
                + (' …' if len(keys) > 14 else ''))

    if kind in ('RC4PT', 'RC4UP'):
        if var == 'nontext':
            return (f'- `{ts}` **{kind}(nontext)** {f.get("len")} B '
                    f'`{str(f.get("b64"))[:48]}…` _(不是文本；只作为计数证据)_')
        return f'- `{ts}` **{kind}** `{str(f.get("text"))[:MAX]}`'

    if kind in ('RC4KEY', 'RC4KEYSTR'):
        key = str(f.get('key') or '')
        n = f.get('length') or len(key)
        return f'- `{ts}` **{kind}** `{key[:48]}…` ({n} 字符)'

    if kind in ('NET', 'H5'):
        label = f'{kind} {f.get("prim") or f.get("op")}'.strip()
        val = str(f.get('value') or '')
        return f'- `{ts}` **{label} {f.get("dir")}** `{val[:MAX]}`' + (' …' if len(val) > MAX else '')

    if kind == 'H5BRIDGE':
        return (f'- `{ts}` **H5BRIDGE** `{f.get("action")}` × {f.get("count")} '
                f'`{str(f.get("args"))[:120]}`')

    if kind == 'BRIDGE':
        # 四个变体各有分支（旧实现只认 download / 其它 ⇒ payorder 与 decodeHttpRequest
        # 被渲染成 `getuserinfo identity=None`，字段全丢）。
        if var == 'download':
            return (f'- `{ts}` **BRIDGE downloadMedia** type={f.get("type")} '
                    f'`{f.get("url")}`' + (' _(非 1 ⇒ 宿主不落盘)_' if f.get('type') != 1 else ''))
        if var == 'userinfo':
            return f'- `{ts}` **BRIDGE getuserinfo** identity=`{f.get("identity")}`'
        if var == 'payorder':
            shape = f.get('shape') or '?'
            keys = f.get('keys')
            names = ','.join(keys) if isinstance(keys, (list, tuple)) else ''
            shape_txt = f'keys={names}' if shape == 'keys' else shape
            return (f'- `{ts}` **BRIDGE payorder** len={f.get("len")} {shape_txt} '
                    f'pid=`{f.get("pid")}` _(payInfo 的值从不落盘)_')
        if var == 'decode':
            sd = f.get('shouldDecode')
            return (f'- `{ts}` **BRIDGE decodeHttpRequest** `{f.get("url")}` '
                    f'shouldDecode={sd if sd is not None else "?"} params=`{f.get("params") or "?"}`')
        return f'- `{ts}` **BRIDGE {var}** `{str(f)[:120]}`'

    if kind == 'NEXIT':
        # 原生退出守卫的自证。`selfTest` 是**关键字段**：seccomp 不回报命中次数，
        # "装上了"（installed=true）不等于"拦住了"，只有 selfTest=1 才是活证据。
        verdict = {1: '已拦住', 0: '装上了但没拦住', -1: '未安装', -2: '对照组', -3: '调用失败'}
        st = f.get('selfTest')
        return (f'- `{ts}` **NEXIT 自证** installed=`{f.get("installed")}` '
                f'control=`{f.get("control")}` → **{verdict.get(st, st)}** '
                f'selfProof={f.get("selfProof")}')

    if kind == 'PAGEREQ':
        # 「哪个 action 让宿主把请求打到哪」。method 三态：0=GET / 1=POST / ? 取不到，
        # 所以不能直接打印数字 —— `?` 要看得见，否则会被读成 0（GET）。
        meth = f.get('method')
        verb = {0: 'GET', 1: 'POST'}.get(meth, '?')
        return (f'- `{ts}` **PAGEREQ** from=`{f.get("from")}` {verb} '
                f'`{f.get("url")}` params={f.get("params")}')

    if kind == 'GUARD':
        return (f'- `{ts}` **GUARD 拦截** `{f.get("action")}` '
                f'reason=`{f.get("reason")}` host=`{f.get("host") or "-"}` #{f.get("seq")}')

    if kind == 'ADSLOT_CALL':
        return (f'- `{ts}` **ADSLOT call** `{f.get("cls")}.{f.get("method")}({f.get("pos")})` '
                f'#{f.get("seq")}')

    if kind == 'ADSLOT_RET':
        return (f'- `{ts}` **ADSLOT ret** `{f.get("cls")}.{f.get("method")}({f.get("pos")})` '
                f'→ `{f.get("shown")}`')

    if kind == 'AD_BLOCK':
        return (f'- `{ts}` **广告位读取被拦** `aj.a.{f.get("method")}({f.get("pos")})` '
                f'→ `{f.get("result")}`')

    if kind == 'ADBLOCK':
        # `ADBLOCK di.a.j -> false` —— **拦截成功**的证据（2026-11-02 加）。
        # 与 `AD_BLOCK`（读数被拦）是两件事：这一条证明"这个钩子真的触发并改写了结果"，
        # 而广告面（C1）原来只能数读数、数不到拦截，于是永远给"无法验证"。
        return (f'- `{ts}` **广告判定被改写** `{f.get("cls")}.{f.get("method")}` '
                f'→ `{f.get("result")}`')

    if kind == 'ROUTE':
        return f'- `{ts}` **ROUTE** `{f.get("route")}` arg=`{f.get("arg")}` from=`{f.get("from")}`'

    # 2026-11-14：会员推广清理 / MD3 皮肤 / 设置页入口 —— 只有事件名一层
    # （见 capture_schema._f_event）
    if kind in ('PROMO', 'MD3', 'SETTINGS'):
        return f'- `{ts}` **{kind}** `{f.get("event")}`'

    if kind == 'NAV':
        return f'- `{ts}` **NAV** `{f.get("page")}` `{f.get("url")}`'.rstrip()

    if kind == 'NAVACT':
        return f'- `{ts}` **NAVACT** `{f.get("activity")}`'

    if kind == 'HDR':
        flds = f.get('fields') or {}
        return (f'- `{ts}` **HDR({f.get("variant")})** `{f.get("target") or "-"}` '
                f'→ {len(flds)} 个头: `{", ".join(sorted(flds)[:10])}`')

    if kind == 'WEBREQ':
        names = f.get('header_names') or []
        extra = f' | 头: `{", ".join(names[:8])}`' if names else ''
        return f'- `{ts}` **WEBREQ** `{f.get("url")}`{extra}'

    if kind == 'EXITCALL':
        tag = '**真拦下**' if f.get('blocked') else '只记录'
        extra = '（栈已省略）' if f.get('stack_suppressed') else ''
        return f'- `{ts}` **EXITCALL #{f.get("seq")}** {tag} `{f.get("where")}`{extra}'

    if kind == 'EXITSTACK':
        return f'  - ↳ 栈 #{f.get("seq")}: `{str(f.get("stack"))[:MAX]}`'

    if kind == 'ROBUST':
        # 热修复补丁面。措辞刻意区分三件事，别混：
        #  * `redirect=false` ⇒ 这个类**根本没被补丁碰过**（`isSupport` 第一分支直接 false），
        #    此时 `supported=false` 是**正常**，不是异常；
        #  * `supported=true` ⇒ 这一次真被补丁接管，**原方法体没执行** —— 对模块结论最要紧；
        #  * `supported=?`   ⇒ 读不到（拿不到 `PatchProxyResult`）—— 当作"不知道"，不是"没接管"。
        if var == 'stack':
            return f'  - ↳ 调用方 #{f.get("method_no")}: `{str(f.get("stack"))[:MAX]}`'
        sup = f.get('supported')
        rdr = f.get('redirect')
        if rdr is False:
            verdict = '未被补丁涉及（正常）'
        elif sup is True:
            verdict = '**被补丁接管，原方法体未执行**'
        elif sup is False:
            verdict = '有分派器但这次未接管'
        else:
            verdict = '接管状态读不到（不等于没接管）'
        return (f'- `{ts}` **ROBUST #{f.get("method_no")}** `{f.get("who")}` → {verdict}')

    if kind == 'VIP':
        return f'- `{ts}` **VIP** {f.get("note")} _(客户端判定；服务端未验证)_'

    if kind == 'H5RET':
        body = f.get('body')
        extra = f' `{str(body)[:120]}`' if body else ''
        return (f'- `{ts}` **H5RET** `{f.get("cb")}` × {f.get("count")} '
                f'({f.get("len")} 字节){extra}')

    if kind in ('REQBODY', 'RESPBODY'):
        # 请求体 / 响应体：`text` 有内容、`bin` 只有长度、`unreadable` 说明字段名变了。
        # 三者分开渲染 —— 把 `bin` 打印成"空 body"会让人以为响应是空的，
        # 而实际是我们**故意不记**二进制内容（见 HttpBodyProbe 的 KDoc）。
        if var == 'unreadable':
            return (f'- `{ts}` **{kind}** 读不到 body 字段 '
                    f'(volley 字段名变了: `{", ".join(f.get("fields") or [])}`)')
        if var == 'params':
            # 表单参数：`n` 是**总个数**，`kv` 只带前 24 个，`omitted` 是其余数量。
            # 不能按 body 渲染 —— 它没有 `len`/`body` 字段。
            who = f' `{f.get("who")}`' if f.get('who') else ''
            kv = str(f.get('kv') or '')[:MAX]
            more = f' …+{f.get("omitted")}' if f.get('omitted') else ''
            names_only = ' _(只记名，未记值)_' if kv and '=' not in kv else ''
            return (f'- `{ts}` **{kind} params**{who} n={f.get("n")} '
                    f'`{kv}`{more}{names_only}')
        size = f.get('len')
        if var == 'bin':
            who = f' `{f.get("who")}`' if f.get('who') else ''
            st = f' status={f.get("status")}' if f.get('status') is not None else ''
            return (f'- `{ts}` **{kind} bin**{who}{st} — {size} 字节'
                    f' _(非文本；只作为长度证据)_')
        who = f' `{f.get("who")}`' if f.get('who') else ''
        st = f' status={f.get("status")}' if f.get('status') is not None else ''
        cut = ' …' if f.get('truncated') else ''
        return (f'- `{ts}` **{kind}{who}{st}** ({size} 字节) '
                f'`{str(f.get("body"))[:MAX]}`{cut}')

    if kind == 'NETERR':
        no = f.get('no')
        code = f.get('code')
        detail = f.get('detail')
        bits = [f'no={no}']
        if code:
            bits.append(f'`{code}`')
        line = f'- `{ts}` **NETERR** ' + ' '.join(bits)
        if detail:
            line += f' — {detail}'
        return line

    if kind == 'VIPLIMIT':
        if var == 'ask':
            return (f'- `{ts}` **VIPLIMIT 问额度** product=`{f.get("product")}` '
                    f'used={f.get("used")}')
        allowed = f.get('allowed')
        mark = '允许' if allowed else '**拒绝**'
        return (f'- `{ts}` **VIPLIMIT 判定** {mark} remaining={f.get("remaining")} '
                f'_(客户端判定；服务端会再校验一次)_')

    if kind in ('PCTRL', 'PCTRLW'):
        # 家长模式读/写侧。两侧都是"服务端 AB 配置下发的四个闸门 + 一个掩码"，
        # 差别只在读侧没有 `from`/`userMode`（那两个是提交时才有的）。
        #
        # `unavailable` 是独立变体：拿不到数据时只写 `reason=`。
        # 这比"没有这一行"有用得多 —— 前者说明"钩到了但读不到"，后者只能猜。
        if var == 'unavailable':
            return (f'- `{ts}` **{kind} 读不到** reason=`{f.get("reason")}` '
                    f'_(钩子执行了，但家长模式数据拿不到)_')
        side = '写侧' if kind == 'PCTRLW' else '读侧'
        gates = (f'aiwriting={f.get("aiwriting")} book={f.get("book")} '
                 f'correctsearch={f.get("correctsearch")} picsearch={f.get("picsearch")}')
        tail = ''
        if kind == 'PCTRLW':
            tail = f' from={f.get("from")} userMode={f.get("userMode")}'
        return (f'- `{ts}` **{kind} 家长模式{side}** mask=`{f.get("mask")}` '
                f'{gates}{tail}')

    if kind == 'WATERMARK':
        # `WATERMARK off applied` —— 模块代用户按下了 App 自带的去水印开关（`cu.l` 构造器置
        # 字段 r）。它只证明钩子执行过，**不证明**服务端真的交出了无水印产物（`WatermarkOff`
        # 的 KDoc 已写明这条限制）。之前这一支漏了，整行渲染成 `__UNKNOWN__`，
        # 而统计表却按 `WATERMARK` 计数 —— 两处不一致（2026-10-25 第 3 轮修）。
        return f'- `{ts}` **WATERMARK** {f.get("note")} _(客户端开关；产物未验证)_'

    if kind == 'UPDATE':
        if f.get('mode') == 'forceup':
            return f'- `{ts}` **UPDATE** forceUp {f.get("before")} → {f.get("after")}'
        return f'- `{ts}` **UPDATE** 强制更新流程已抑制（{f.get("mode")}）'

    if kind == 'POPWIN':
        # 服务端弹窗分派观测。三个字段分开展示，因为它们回答三个不同问题：
        #   type   —— 服务端这次下发的是哪一类（`winAd` / `winUp` / `winActivity_7` …）
        #   block  —— 它**本来**该不该被拦（命中清单）
        #   action —— 实际做了什么（PASS / OBSERVE / BLOCK）
        # `OBSERVE` 这一档是"命中清单但只记录"：只有把 block 与 action 并排看，
        # 才看得出"只观测"确实生效了。合并成一句"已拦截"会把观测模式说成拦截。
        act = f.get('action')
        t = f.get('type')
        if act == 'BLOCK':
            return f'- `{ts}` **POPWIN 拦截** type=`{t}` _(服务端弹窗未展示；真机效果未验证)_'
        if act == 'OBSERVE':
            return (f'- `{ts}` **POPWIN 观测** type=`{t}` '
                    f'_(命中拦截清单但 observe_only 开着 ⇒ 只记录、未拦截)_')
        return f'- `{ts}` **POPWIN 放行** type=`{t}`'

    if kind == 'ONBOARD':
        return (f'- `{ts}` **ONBOARD** 点 `{f.get("text")}` label={f.get("label")} '
                f'#{f.get("seq")} ok={f.get("ok")}')

    if kind == 'APPSIGN':
        return f'- `{ts}` **APPSIGN {f.get("level")}** `{f.get("tag")}`: {str(f.get("msg"))[:MAX]}'

    if kind == 'SIGNPARAM':
        return f'- `{ts}` **SIGNPARAM** sign=`{f.get("sign")}` param=`{str(f.get("param"))[:60]}`'

    if kind == 'FORMULA':
        return f'- `{ts}` **FORMULA** A=`{f.get("a")}` X=`{f.get("x")}` sign=`{f.get("sign")}`'

    if kind == 'SIGN_RESULT':
        return f'- `{ts}` **SIGN result** `{str(f.get("value"))[:MAX]}`'

    if kind == 'MARK':
        return f'\n### `{ts}` 会话标记: {f.get("text")}\n'

    body = rec.raw.split(' ', 1)[1] if ' ' in rec.raw else rec.raw
    return f'- `{ts}` __UNKNOWN__ `{body[:MAX]}`'


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    kinds, reasons, out = {}, {}, []
    for rec in iter_records(argv[1]):
        kinds[rec.kind] = kinds.get(rec.kind, 0) + 1
        if rec.kind == 'UNKNOWN':
            r = rec.get('reason') or 'unknown'
            reasons[r] = reasons.get(r, 0) + 1
        out.append(one_line(rec))

    print(f'# Capture transcript — {argv[1]}\n')
    print('## 事件统计（按 `capture_schema.py` 的前缀表）\n')
    for k, v in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f'- {v:5d}  `{k}`')
    if kinds.get('UNKNOWN'):
        # 分三档报告，而不是一句"有 N 行没人认领"：旧抓取里 PEM 证书的续行会有几百行，
        # 混在一起读会让人以为模块在写未知格式。真正要处理的是 `new-prefix`。
        print(f'\n> ⚠ {kinds["UNKNOWN"]} 行没有规则认领，按形状分：'
              + ', '.join(f'`{k}`×{v}' for k, v in sorted(reasons.items())))
        if reasons.get('new-prefix'):
            print('> **其中有 `new-prefix`：首词像未登记的新前缀，需要在 '
                  '`capture_schema.py` 的 RULES 里补规则。**')
        if reasons.get('legacy-wrap'):
            print('> `legacy-wrap` = 2026-10-25 之前写入侧没有压平换行，一条带换行的记录'
                  '被读成多行（`CapturePolicy.oneLine` 已修）；新构建不会再产生。')
    print('\n## 时间线\n')
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
