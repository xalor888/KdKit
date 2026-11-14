#!/usr/bin/env python3
"""
kuaidui-kit / module_activity.py — the module's **trigger surface**, from real captures.

Why: "installed" is not "working". If a host update renames the class behind a hook, the
feature stops silently — the logs just have *fewer lines*, never an error. Counting each
feature's own capture prefix per round, and diffing against the previous round, is what makes
that visible.

This script used to read the LSPosed module log via `adb` and carry a hand-written `MARKS`
table of 15 regexes. Both were wrong by 2026-10-25:

  * the table knew 15 of 40 features and matched prefixes by substring, so `NAVACT` lines were
    counted as `NAV` and `RC4PT(nontext)` as `RC4PT`;
  * it required a device, so nothing could be re-verified offline.

Now the prefix table lives in `kit/python/capture_schema.py` (one declaration, shared with the
other five parsers and gated by `kit/python/tests/`), and this script reads **capture files**
(`--capture`, repeatable) or a directory of them (`--dir`). No device, no `adb`, repeatable.

    python3 kit/scripts/module_activity.py --dir work/dpsdk --out work/MODULE_ACTIVITY.md
    python3 kit/scripts/module_activity.py --capture cap1.txt --capture cap2.txt --json prev.json
    python3 kit/scripts/module_activity.py --dir work/dpsdk --prev work/MODULE_ACTIVITY.json

Two numbers per feature, deliberately kept apart:

  * **capture rows** — lines the feature wrote into `kdkit_capture.txt` (硬证据: the feature ran);
  * **presence** — in how many of the input files it appears (a feature that only shows up in
    one old file is not "continuously working").

Features that never write a capture line (11 of 40 — ad removers, anti-detect, seccomp guard,
PK assist, page-JS injection) are reported in their own table with `—`, and the script says so
explicitly instead of printing a misleading 0.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))

from capture_schema import (  # noqa: E402
    FEATURES_LOGCAT_ONLY, FEATURES_WITH_CAPTURE, FEATURE_IDS, PREFIX_FEATURE, iter_records,
)


def _registered_sample_date(path: str) -> str | None:
    """从 `work/activity_inputs/README.md` 的登记表里读出这份抓取的采样日期。

    表形如：
        | `acceptance_capture.txt` | `work/dpsdk/...` | 2026-10-18 | 25 功能版本 … |

    只认**第一列是文件名的行**，避免把正文里随便出现的日期当成采样日。
    读不到就返回 None（调用方写 `?`）—— 猜日期会让"样本早于功能"这条结论失真，
    而那正是本文件第四节存在的全部理由。
    """
    import os as _os
    import re as _re
    readme = _os.path.join(_os.path.dirname(_os.path.abspath(path)), 'README.md')
    if not _os.path.exists(readme):
        return None
    base = _os.path.basename(path)
    try:
        with open(readme, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return None
    for line in text.splitlines():
        m = _re.match(r'^\|\s*`?([^`|]+?)`?\s*\|', line)
        if not m or m.group(1).strip() != base:
            continue
        dates = _re.findall(r'\d{4}-\d{2}-\d{2}', line)
        if dates:
            return dates[0]
    return None


def collect(paths):
    """files[]: per-file kind/feature counts. Also global counters."""
    per_file, files = [], []
    total = {f: 0 for f in FEATURES_WITH_CAPTURE}
    kinds = {}
    for path in paths:
        feat, kind = {}, {}
        for rec in iter_records(path):
            kind[rec.kind] = kind.get(rec.kind, 0) + 1
            if rec.feature:
                feat[rec.feature] = feat.get(rec.feature, 0) + 1
                total[rec.feature] = total.get(rec.feature, 0) + 1
            for k, v in kind.items():
                kinds[k] = kinds.get(k, 0) + 0
        for k, v in kind.items():
            kinds[k] = kinds.get(k, 0) + v
        per_file.append({'path': path, 'features': feat, 'kinds': kind})
        files.append(path)
    return files, per_file, total, kinds


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', action='append', default=[], help='capture file (repeatable)')
    ap.add_argument('--dir', default=None, help='directory of *.txt captures')
    ap.add_argument('--glob', default='*.txt')
    ap.add_argument('--prev', default=None, help='previous JSON, for the growth diff')
    ap.add_argument('--out', default=None,
                    help='write markdown here. **不给 `--out` 会覆盖仓库里那份正式文档** '
                         '—— 冒烟测试一律显式给 `--out /tmp/x.md`。')
    ap.add_argument('--json', default=None, help='write this run as JSON (input for --prev)')
    ap.add_argument('--keep-section', default='## 七、',
                    help='重写 --out 时保留原文件从这个标题起的全部内容（手工补充的对照表）')
    ap.add_argument('--adb', default=None,
                    help='DEPRECATED, ignored: this script no longer talks to a device')
    a = ap.parse_args(argv[1:])

    paths = list(a.capture)
    if a.dir:
        paths += sorted(glob.glob(os.path.join(a.dir, a.glob)))
    if not paths:
        print('[activity] 需要 --capture 或 --dir（本脚本已不再用 adb 读日志）')
        return 2
    if a.adb:
        print(f'[activity] --adb {a.adb} 被忽略：改为读抓取文件（离线可重复）')

    files, per_file, total, kinds = collect(paths)
    prev = {}
    if a.prev and os.path.exists(a.prev):
        with open(a.prev, encoding='utf-8') as fh:
            prev = json.load(fh).get('total', {})

    present = {f: sum(1 for pf in per_file if pf['features'].get(f)) for f in FEATURES_WITH_CAPTURE}
    # 抓取文件的"最晚一份"时间：用来判断"某前缀 0 行"到底是没触发，还是**样本早于该功能**。
    #
    # **不能**用 `os.path.getmtime`。2026-10-25 抓到：脱敏脚本就地改写了 5 份抓取，
    # mtime 全变成"今天"，于是这一行会写成"最晚一份是 2026-10-25"，
    # 而真正的采样日期是 2026-10-18 —— 直接抹掉"样本早于功能"这个关键结论，
    # 让 `skip_update`/`vip_unlock` 等 0 行功能从"样本太旧"错判成"功能失效"。
    # 采样日期是**数据属性**，必须记在数据里，不能从文件系统借。
    #
    # 权威来源：`work/activity_inputs/README.md` 的登记表（每份抓取的 `日期` 列）。
    # 找不到登记就老实写 `?` —— 猜一个日期比不写更糟。
    import datetime
    newest_str = '?'
    dated = []
    for p in files:
        d = _registered_sample_date(p)
        if d:
            dated.append((d, p))
    if dated:
        newest_str = max(dated)[0]
    # `MARK`（`=== KdKit host=…` / `=== HookCore start …`）是**基础设施行，没有归属功能**
    # （`PREFIX_FEATURE['MARK'] is None`），所以它不属于"某个功能没有样本"。
    #
    # 但它 0 行这件事本身有信息量，不能静默丢掉 —— 曾经这里写的是硬编码
    # `k not in ('MARK',)`，既不解释原因，也不在输出里提一句，于是"5 份抓取里
    # 连一行启动标记都没有"这个事实谁也看不见。改为：从 `PREFIX_FEATURE` 派生
    # （新加一个无主前缀会自动落到这里，不需要改代码），并把结论写进 §四末尾。
    ownerless_zero = sorted(k for k in PREFIX_FEATURE
                            if PREFIX_FEATURE[k] is None and kinds.get(k, 0) == 0)
    no_sample = [k for k in PREFIX_FEATURE
                 if PREFIX_FEATURE[k] is not None and kinds.get(k, 0) == 0]
    rows = [(f, total.get(f, 0), present[f]) for f in FEATURES_WITH_CAPTURE]
    rows.sort(key=lambda r: (-r[1], r[0]))

    silent = [r for r in rows if r[1] == 0]
    single = [r for r in rows if r[1] and r[2] == 1 and len(files) > 1]
    shrank = [(f, prev[f], total[f]) for f in total if f in prev and total[f] < prev[f]]

    out = []
    w = out.append
    w('# 模块功能的实际触发面\n')
    w(f'* 输入：**{len(files)} 份抓取**，共 **{sum(kinds.values())} 行**')
    # 复现命令必须是**能直接粘进终端就得到同样数字**的那一条。旧版拼的是
    # `--capture <前 3 个文件> …`，既漏文件又写了不存在的路径（`capture_kd1_r11.txt`），
    # 照它跑会 FileNotFoundError —— 一份"可复现"的文档给出跑不通的命令，比不给更糟。
    # 用 `--dir` 时顺序由 `sorted(glob)` 固定，输入集合即目录快照本身。
    # `--out` 必须是**实际用的那个路径**（2026-11-02 修）。
    #
    # 旧实现把输出路径写死成 `module/ACTIVITY.md`，而 `evidence_pack.py` 用的是
    # `--out work/MODULE_ACTIVITY.md`。于是 `work/MODULE_ACTIVITY.md` 的复现命令
    # 指向另一个文件 ⇒ 门禁 ⑭ 复跑它、拿 `module/ACTIVITY.md` 与
    # `work/MODULE_ACTIVITY.md` 比 ⇒ **永远 STALE**（今天实测红了一次）。
    # 一份"可复现"的文档给出指向别处的命令，比不给更糟。
    _out_rel = os.path.relpath(a.out, ROOT) if a.out else 'module/ACTIVITY.md'
    if a.dir:
        repro = (f'python3 kit/scripts/module_activity.py '
                 f'--dir {os.path.relpath(a.dir, ROOT)} --out {_out_rel}')
    else:
        repro = ('python3 kit/scripts/module_activity.py '
                 + ' '.join(f'--capture {os.path.relpath(p, ROOT)}' for p in files)
                 + f' --out {_out_rel}')
    w(f'* 复现：`{repro}`')
    w(f'* 口径来源：`kit/python/capture_schema.py`（前缀表的唯一声明处，'
      f'被 6 个解析器 + 门禁 ①b 共用）')
    w('')
    w('## 判据（这一节是"怎么读"，不是结论）\n')
    w(f'* **有抓取行的功能 {len(FEATURES_WITH_CAPTURE)} 个**：数它们自己写的前缀行数 —— '
      f'这是"确实执行过"的硬证据；')
    w(f'* **只写 logcat 的功能 {len(FEATURES_LOGCAT_ONLY)} 个**：结构上不写抓取，本表给 `—`，'
      f'不代表没工作；')
    w('* **出现份数**：在多少份输入里出现过。只在 1 份里出现 = 那一轮跑过，不能推断"一直在跑"；')
    w('* 计数为 0 的**不等于失效** —— 默认关的功能没触发、或该轮没走到那条业务路径，都是 0。'
      '要区分"没开"与"钩子失效"，看 `module_report.py` 的 audit 行。')
    w('')

    w('## 一、有抓取证据的功能\n')
    w('| feature | 抓取行数 | 出现份数 | 上一轮 | 变化 |')
    w('|---|---|---|---|---|')
    for f, n, k in rows:
        before = prev.get(f)
        delta = '—' if before is None else (f'{n - before:+d}' if n != before else '0')
        w(f'| `{f}` | {n} | {k}/{len(files)} | '
          f'{"—" if before is None else before} | {delta} |')
    w('')

    w('## 二、只写 logcat 的功能（本表结构上无法计数）\n')
    # 数字必须**从 `FEATURES_LOGCAT_ONLY` 推出**，不能手写。
    # 2026-10-25 第 28 轮抓到：这里写着"这 11 个"，而下面那张表由 `FEATURES_LOGCAT_ONLY`
    # 生成、当时已是 **12** 行` —— 同一页上表头数字与表体行数互相矛盾，而所有门禁全绿。
    # 它和 §35 记的那三处是同一类：手写的数字没有人校验，于是它自己悄悄过期。
    # 同一个文件上方「判据」那两条已经在用 `len(...)` 了，这一处是漏网。
    w(f'这 {len(FEATURES_LOGCAT_ONLY)} 个功能改变行为或只走 `KdLog`，**不写抓取文件**。'
      '它们的"是否在工作"只能由模块日志的安装行 + 行为差异判断，不能由本表判断：\n')
    w('| feature | 为什么没有抓取行 |')
    w('|---|---|')
    why = {
        'rm_splash': '移除开屏广告：钩子改返回值，不落盘',
        'rm_tab_ad': '移除 Tab 广告：同上',
        'rm_main_banner': '移除主页横幅：同上',
        'rm_popup': '移除弹窗：同上',
        'rm_feed_ad': '移除信息流广告：同上',
        'block_ad_sdk': '广告 SDK 阻断：同上',
        'anti_detect': '反调试：只 `KdLog`（前 6 条 + 5 分钟心跳）',
        'native_exit_guard': 'seccomp 过滤器：装了就撤不回，无逐次记录',
        'pk_assist': 'PK 自动作答：行为改变 + `KdLog`',
        'page_js': '页面脚本注入：注入动作本身不落盘（页面侧结果走 `WEBREQ`/`NAV`）',
        'h5_debug': 'H5 调试台：注入 eruda，按需手动打开',
    }
    for f in FEATURES_LOGCAT_ONLY:
        w(f'| `{f}` | {why.get(f, "行为改变类，不落盘")} |')
    w('')

    w('## 三、需要解释的三类读数\n')
    w('### 3.1 计数为 0 的\n')
    if silent:
        w('| feature | 读法 |')
        w('|---|---|')
        for f, _n, _k in silent:
            w(f'| `{f}` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，'
              f'要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |')
    else:
        w('无 —— 所有有抓取能力的功能都至少出现过一次。')
    w('')
    w('### 3.2 只在 1 份输入里出现的\n')
    if single:
        for f, n, _k in single:
            w(f'* `{f}`：{n} 行，只在这 1 份里 ⇒ 那一轮跑过，**不能**据此说"持续在工作"')
    else:
        w('无。')
    w('')
    w('### 3.3 比上一轮少的\n')
    if shrank:
        for f, before, now in shrank:
            w(f'* `{f}`：{before} → {now}（-{before - now}）'
              f'—— 可能是开的窗口更短、也可能钩子开始失效，需要对照 audit 行')
    else:
        w('无（或缺 `--prev`）。')
    w('')

    w('## 四、没有任何运行时样本的前缀\n')
    if no_sample:
        w(f'这些前缀在**全部 {len(files)} 份输入里都是 0 行**。本批抓取最晚一份的日期是 '
          f'**{newest_str}**。2026-10-25 一轮新增/改写的功能（`skip_update` / `vip_unlock` / '
          f'`bridge_action_log`，以及 `EXITCALL` / `RC4PT(nontext)` / `EXITSTACK` 等行）都在'
          f'这个日期之后，因此它们没有样本属于"**样本早于功能**"，不能当成"功能失效"读。'
          f'要关闭这个缺口，只能拿 2026-10-25 之后构建的模块在真机上跑一轮再 pull。\n')
        w('| 前缀 | 归属功能 | 静态层证据 | 运行时 |')
        w('|---|---|---|---|')
        static = {
            'EXITCALL': '`ExitGuard.hookAll` — `module/README.md` 功能表',
            'EXITSTACK': '同上（同一处两行）',
            'VIP': '`module/NEW_TARGETS.md` §3（`bk.a.p` / `VipCurrentStatusWebAction`）',
            'UPDATE': '`module/NEW_TARGETS.md` §2（`ei.y.L`）',
            'BRIDGE': '`module/NEW_TARGETS.md` §4（`FeDownloadMediaAction` / `GetUserInfoWebAction`）',
            'RC4PT': '`RC4Probe.decrypt` 钩子',
            'RC4UP': '`RC4Probe.encrypt` 钩子',
            'ONBOARD': '`SkipOnboarding.click`',
            'WEBREQ': '`WebInjector.shouldInterceptRequest`',
            'HDR': '`ReqHeaders` 三处钩子（静态/每请求/Volley）；volley 侧 2026-10-25 起带 `pid=<业务域>`（`-` = 读不到）',
            'ROUTE': '`RouteLog` 钩子',
            'NAV': '`NavLog.record`',
            'ADSLOT_CALL': '`AdSlotProbe`',
            'ADSLOT_RET': '`AdSlotProbe`',
            'AD_BLOCK': '`RemoveAdSlotConfig`',
            'SIGN_RESULT': '`SignObserver`',
            'FORMULA': '`NativeProbe`',
            'APPSIGN': '`LogSink`；**2026-10-25 之前采集的样本里 99.7% 是模块自身日志的重复行**'
                       '（`SELF_TAG` 排除是之后才加的，见 `OPTIMIZATION.md` §22）',
            'WATERMARK': '`WatermarkOff`（`cu/l` 构造器，`NEW_TARGETS.md` §2.2）',
        }
        for k in sorted(no_sample):
            w(f'| `{k}` | `{PREFIX_FEATURE[k] or "-"}` | {static.get(k, "见功能源码")} | **未验证** |')
        w('')
        w('> 这些行的**格式**由门禁 ①b 用构造样本证明（`kit/python/tests/fixtures/'
          'all_prefixes.txt`），但"设备上真的会写出这些行"仍然**未验证**。\n')
        if ownerless_zero:
            # 无主前缀（没有归属功能）不属于上面那张表：那张表问的是"某个功能有没有样本"。
            # 但它们 0 行同样说明问题，必须显式写出来，否则等于静默丢掉一条结论。
            note = {
                'MARK': '`=== KdKit host=…` / `=== HookCore start …`；'
                        '由 `Capture.mark` 写入，理论上每次启动 1 行',
            }
            w('### 四之二、基础设施前缀：0 行（不属于任何功能）\n')
            w('| 前缀 | 归属功能 | 说明 |')
            w('|---|---|---|')
            for k in ownerless_zero:
                w(f'| `{k}` | — | {note.get(k, "无归属功能，本批 0 行")} |')
            w('')
            w('`MARK` 0 行的读法：**不能**据此说"模块没启动过" —— 这 5 份是 '
              '`work/activity_inputs/` 里冻结的原始 logcat，采集时可能只截取了业务行。'
              '真相需要重新 pull 一份完整抓取才能确定，本轮标**未验证**。\n')
    else:
        w('无 —— 每个已声明的前缀都至少出现过一次。')
    w('')

    w('## 五、按前缀的分布（用来发现"某类记录突然消失"）\n')
    w('| 前缀 | 行数 |')
    w('|---|---|')
    for k, v in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])):
        w(f'| `{k}` | {v} |')
    w('')

    w('## 六、这份表**不能**证明的事\n')
    w('* 不能证明**行为改变**真的生效（广告是否消失、会员是否解锁）—— 那需要真机前后对比；')
    w('* 不能证明**热开关**在 1–2 秒内生效 —— 需要真机翻转开关；')
    w('* 不能证明这些行对应的功能**已经**被用户打开 —— 抓取只记"执行过"，不记"为什么执行"；')
    w('* 本表全部数字来自**离线抓取文件**，可重复；真机行为一律标"未验证"。')
    w('')

    text = '\n'.join(out) + '\n'
    if a.out:
        # 手工补充的附录（`## 七、功能 ↔ 抓取前缀对照表`）必须跨重写存活。
        # 它同时是 ③ 的门禁输入（`check_activity_doc` 要求每个 feature id 在本文件里出现），
        # 所以一次"照文档说的重跑命令"就会把它抹掉、然后门禁报红 —— 那不是文档写错了，
        # 是生成器把手工内容当成了自己的领地。2026-10-25 后台轮次真的丢过这张表。
        tail = ''
        if a.keep_section and os.path.exists(a.out):
            old = open(a.out, encoding='utf-8').read()
            idx = old.find('\n' + a.keep_section)
            if idx >= 0:
                tail = old[idx:]
                if not tail.endswith('\n'):
                    tail += '\n'
        with open(a.out, 'w', encoding='utf-8') as fh:
            fh.write(text + tail)
        kept = '（保留手工附录）' if tail else ''
        print(f'[activity] -> {a.out}（{len(files)} 份，{sum(kinds.values())} 行）{kept}')
    else:
        print(text)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump({'files': files, 'total': total, 'present': present,
                       'kinds': kinds, 'per_file': per_file}, fh, indent=2, ensure_ascii=False)
        print(f'[activity] -> {a.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
