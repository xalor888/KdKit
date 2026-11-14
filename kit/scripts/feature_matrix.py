#!/usr/bin/env python3
"""
kuaidui-kit / feature_matrix.py — how strongly is each module feature *verified*?

The module has 40 features but their evidence is not equally strong: some were proven by dedicated
experiments (control arms, ablations), some only show up as a counter in the capture, and some are
merely "installed and enabled". This reads three sources and prints one honest table:

  * `module/.../FeatureRegistry.kt`   — the feature ids, titles, categories, defaults
  * the module log + capture          — what the *current* process is doing (enabled? evidence?)
  * `ROADMAP.md`                      — which rounds ran an experiment mentioning that feature

    python3 kit/scripts/feature_matrix.py --adb emulator-5558 --out module/VERIFICATION.md
    python3 kit/scripts/feature_matrix.py --offline --out module/VERIFICATION.md   # 无需设备

`--offline` 下"当前"列变成 `?`（没有进程可观测），等级只用静态事实（ROADMAP 轮次、计数器是否被代码写、
是否有 KdOption/钩子），因此**不会**因为"没连设备"就把所有功能判成弱。

Verification levels (deliberately blunt):
  强  = the journal contains a round that names the feature *and* lists evidence files for it
  中  = the feature writes records the kit can count (module_report / session_report see them)
  弱  = only "installed / enabled" is observable from here
"""
import argparse
import os
import re
import subprocess
import sys
from collections import defaultdict

from hook_vocab import read_text

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REGISTRY = os.path.join(ROOT, 'module/app/src/main/java/dev/xalor/kdkit/features/FeatureRegistry.kt')

# theme lines are written in prose, so a feature is "the subject" of a round when the theme
# contains its id **or** one of these phrases (kept next to COUNTERS so both stay visible).
KEYWORDS = {
    'rm_adconfig': ['去广告'], 'rm_splash': ['开屏', '去广告'], 'rm_tab_ad': ['去广告'],
    'rm_main_banner': ['去广告'], 'rm_popup': ['去广告'], 'rm_feed_ad': ['去广告'],
    'block_ad_sdk': ['去广告'],
    'ad_probe': ['广告位观测', '广告位'],
    'pk_assist': ['PK'],
    'sign_observer': ['签名链', '离线客户端', '响应体', '登记'],
    'native_probe': ['原生 oracle', '签名链'],
    'anti_detect': ['反调试', '反注入'],
    'exit_guard': ['反调试', '退出守卫', '自杀'],
    'native_exit_guard': ['seccomp', '反注入'],
    'skip_onboarding': ['跳过', '引导'],
    'h5_bridge_log': ['桥调用图', 'H5 桥'],
    'bridge_guard': ['桥守卫', '白名单'],
    'h5_debug': ['eruda', 'H5 调试'],
    'web_request_log': ['页面自有请求', 'WEBREQ', 'shouldInterceptRequest'],
    'native_probe2': [],
}

# 计数不再手写 marker：`capture_schema.py` 已经声明了"哪个前缀属于哪个功能"，直接用它。
# 旧表只有 8 项，于是 2026-10-25 新增的 3 个功能与 `rc4_probe`/`req_headers`/`route_log`/
# `nav_log`/`log_sink`/`rm_adconfig`/`web_request_log` 全被判成"无记录"。
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import textio
import sh as _shmod
from device import PKG as PKG_CONST

# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
from capture_schema import (  # noqa: E402
    FEATURE_IDS, FEATURES_LOGCAT_ONLY, FEATURES_WITH_CAPTURE, iter_records,
)

CAPTURE_FEATURES = set(FEATURES_WITH_CAPTURE)


def match_keyword(key: str, theme: str) -> bool:
    """关键词匹配：**纯 ASCII 词按边界匹配，且区分大小写**。

    ## 为什么不能直接 `k in theme`

    实测到一个纯子串造成的假阳性：`pk_assist` 的关键词是 `PK`，
    而 `R28` 的主题是「接口探测 —— 候选来自 AP**K** 字符串表…」。
    `'PK' in '…APK 字符串…'` 为真 —— **`APK` 里的 `PK`**。于是"接口探测"那一轮
    被当成了 `pk_assist` 的验证依据。

    同类问题还有：`跳过` 命中「可**跳过**性」（方法论讨论）、
    `引导` 命中「AI **引导**问题表」（导出数据）。这些都不做这个功能。

    规则：纯 ASCII 关键词（`PK` / `WEBREQ` / `eruda`…）要求前后不是 ASCII 字母数字，
    且大小写一致（`PK` 不该匹配 `pk` 或 `APK`）；中文关键词没有词边界概念，
    只能保留子串匹配 —— 所以上面那两个中文误命中仍未根除，属**已知残留**。

    残留的影响是有限的：`_rank()` 会优先选"建功能"的轮次并取最早的一轮，
    而误命中的轮次都是后来的引用，因此不会成为被引用的那一个。
    """
    if not key:
        return False
    if key.isascii() and key.replace('_', '').isalnum():
        return re.search(rf'(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])',
                         theme) is not None
    return key in theme
# `--adb` 模式下没有 schema 无法逐行解析整份抓取（几万行可接受，但仍走同一函数），
# 于是保留一份"前缀 -> 子串"的近似表，仅用于设备模式；离线模式一律用 count_from_captures。
CAPTURE_MARKERS = {
    'sign_observer': 'SIGN URL:', 'native_probe': 'SIGNPARAM', 'h5_bridge_log': 'H5BRIDGE ',
    'bridge_guard': 'GUARD blocked=', 'ad_probe': 'ADSLOT call', 'rc4_probe': 'RC4PT',
    'req_headers': 'HDR', 'route_log': 'ROUTE ', 'nav_log': 'NAVACT ',
    'log_sink': 'APPSIGN ', 'rm_adconfig': 'blocked ad slot read',
    'web_request_log': 'WEBREQ ', 'exit_guard': 'EXITCALL', 'skip_onboarding': 'ONBOARD ',
    'skip_update': 'UPDATE ', 'vip_unlock': 'VIP ', 'bridge_action_log': 'BRIDGE ',
}


def count_from_captures(paths):
    """feature -> 行数（真实前缀解析，不是 substring 匹配）。"""
    c = defaultdict(int)
    for p in paths:
        for rec in iter_records(p):
            if rec.feature:
                c[rec.feature] += 1
    return dict(c)


def feature_line_ranges():
    """每个功能对象在源文件里占据的行区间：{相对文件名: [(起始行, 结束行, 对象名)]}。

    `check_hook_signatures.py` 的每一行 `where` 是 `文件名:行号`，**没有** object 名。
    早先的版本直接把钩子数按文件名累加，于是同一个文件里的多个功能共享同一个数字 ——
    `AdFeatures.kt` 有 7 个功能、12 个钩子，7 行全都显示 `12/12`，其中
    `rm_feed_ad`（2 个钩子）与 `rm_splash`（3 个）看起来一模一样。
    `HostFeatures.kt` 更明显：`page_js` 一个钩子都没有，却显示 `4/4`。

    这里按行区间把每个钩子归给**包住它的那个 object**，让这一列回答
    "**这个功能**的钩子解析成功几个"，而不是"它所在的文件有几处钩子"。
    """
    base = os.path.join(ROOT, 'module/app/src/main/java/dev/xalor/kdkit/features')
    out: dict = defaultdict(list)
    for root, _d, files in os.walk(base):
        for fn in sorted(files):
            if not fn.endswith('.kt'):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, ROOT)
            text = read_text(path)
            starts = [(m.start(), m.group(1))
                      for m in re.finditer(r'^object\s+(\w+)\s*:\s*SwitchFeature\b', text, re.M)]
            if not starts:
                continue
            # object 的结束位置 = 从 `{` 起做花括号配平（字符串/注释里的括号不参与判断，
            # 但模块里功能对象的 KDoc 不含裸花括号，这样够用且可解释）。
            for idx, (pos, cls) in enumerate(starts):
                brace = text.find('{', pos)
                if brace < 0:
                    continue
                depth, i, n = 0, brace, len(text)
                while i < n:
                    ch = text[i]
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                start_line = text.count('\n', 0, pos) + 1
                end_line = text.count('\n', 0, i) + 1
                out[rel].append((start_line, end_line, cls))
    return dict(out)


def shared_hook_owners():
    """哪些功能把自己的 payload 挂在**共享钩子点**上：{'web_request_log': 'WebInjector', …}。

    `web_request_log` / `page_js` / `h5_debug` 三个功能自己**一个钩子都不装** ——
    它们只往 `WebInjector.register("<key>") { js }` 里注册一段脚本，真正的
    `WebView.setWebViewClient` / `loadUrl` / `loadDataWithBaseURL` 四个钩子
    由 `WebInjector.install()` 在 `HookCore` 里统一安装（对它自己而言是"共享"的）。

    早先这一列对它们写 `0/0`，读起来像"钩子全都没解析出来"。实际是"钩子不在
    这个对象里"—— 与"钩不上"是两件完全不同的事。这里把它区分开，数据来源是
    功能体内的 `WebInjector.register(` 调用，不是硬编码表。
    """
    base = os.path.join(ROOT, 'module/app/src/main/java/dev/xalor/kdkit/features')
    out = {}
    for root, _d, files in os.walk(base):
        for fn in sorted(files):
            if not fn.endswith('.kt'):
                continue
            path = os.path.join(root, fn)
            text = textio.read_text(path, encoding='utf-8', errors='replace')
            for m in re.finditer(r'^object\s+(\w+)\s*:\s*SwitchFeature\b', text, re.M):
                brace = text.find('{', m.end())
                if brace < 0:
                    continue
                depth, i = 0, brace
                while i < len(text):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                body = text[brace:i]
                owner = re.search(r'\bWebInjector\.register\(', body)
                if owner:
                    out[m.group(1)] = 'WebInjector'
    return out


def static_hook_evidence():
    """每个 feature 的钩子目标在 APK 里解析成什么样（静态证据）。

    为什么需要这一层：`验证等级` 只看 ROADMAP 轮次与可计数记录，于是"有 smali 级
    证据但还没上过真机"的功能会被一律判成**弱**，与"完全没证据"混为一谈。
    这一列把两者分开：`N/N` = 该功能的钩子目标全部解析成功（类+方法+**形参签名**）。

    数据来自 `check_hook_signatures.py --json`（同目录），失败则返回空（不影响主表）。
    归属单位是**功能对象**（按行区间），不是文件 —— 见 `feature_line_ranges()`。
    """
    import json
    import tempfile
    script = os.path.join(HERE, 'check_hook_signatures.py')
    if not os.path.exists(script):
        return {}
    # 输出文件必须**每次新建**，不能是 /tmp 下的固定名。
    # 固定名有两个真缺陷（2026-10-25 抓到）：
    #   1. 并发时两个进程写同一个文件 ⇒ 读到半个 JSON 或别人的结果，
    #      门禁①b 因此偶发红（实测 4 路并发能稳定复现）；
    #   2. 更坏的是**陈旧数据通过门禁**：旧代码写着
    #      `if rc != 0 and not os.path.exists(out): return {}` —— 门禁失败时只要
    #      文件在（上一轮留下的）就继续读，等于用旧证据冒充本次证据。
    #      这正是本项目最想防的那种"结论比事实乐观"。
    fd, out = tempfile.mkstemp(prefix='kdkit_sig_matrix_', suffix='.json')
    os.close(fd)          # 只需要一个**唯一的空路径**；让脚本自己写
    try:
        rc, _ = sh(f'{sys.executable} {script} --quiet --json {out}', timeout=300)
        # 门禁失败 ⇒ 一律返回空（表格里显示 '-'），绝不回落到旧文件。
        if rc != 0:
            return {}
        try:
            with open(out, encoding='utf-8') as fh:
                rows = json.load(fh)
        except Exception:
            return {}
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
    ranges = feature_line_ranges()
    by_file: dict = defaultdict(list)
    for rel, spans in ranges.items():
        by_file[os.path.basename(rel)] = spans
    per_cls = defaultdict(lambda: [0, 0])
    orphans = 0
    for r in rows:
        fname, _, lineno = r.get('where', '').partition(':')
        spans = by_file.get(fname) or []
        try:
            ln = int(lineno)
        except ValueError:
            ln = -1
        owner = next((cls for a, b, cls in spans if a <= ln <= b), None)
        if owner is None:
            orphans += 1          # 钩子写在功能对象之外（顶层 helper）：不进任何一行
            continue
        ok = (r.get('status', '').startswith('OK')
              or r.get('status') == 'UNKNOWN(signature not statically resolvable)')
        per_cls[owner][0 if ok else 1] += 1
    return {k: (v[0], v[0] + v[1]) for k, v in per_cls.items()}


def sh(cmd, timeout=300):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=300):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def features():
    """Every `object X : SwitchFeature(...)` under features/, ordered like the registry list."""
    src = read_text(REGISTRY)
    m = re.search(r'val all[^=]*=\s*listOf\((.*?)\n\s*\)', src, re.S)
    order = re.findall(r'^\s*([A-Z][A-Za-z0-9]{2,}),\s*$', m.group(1) if m else '', re.M)

    decls = {}
    base = os.path.join(ROOT, 'module/app/src/main/java/dev/xalor/kdkit/features')
    for root, _d, files in os.walk(base):
        for fn in files:
            if not fn.endswith('.kt'):
                continue
            body = read_text(os.path.join(root, fn))
            # `[^)]*?` 会在**第一个右括号**就停 —— 构造参数里只要有括号就解析失败。
            # 2026-10-26 实测：`ParentCtrlProbe` 的 summary 写了 `钩 dj.e.f()`，
            # 于是它的 id/title 全取不到，`VERIFICATION.md` 里直接少一行，
            # 而 ③ 报的是「VERIFICATION.md 缺少 parent_ctrl_probe」—— 看不出是正则的问题。
            # 改成「括号平衡」的匹配：允许一层嵌套括号。
            for m2 in re.finditer(
                    r'object\s+(\w+)\s*:\s*SwitchFeature\(((?:[^()]|\([^()]*\))*)\)\s*\{',
                    body, re.S):
                cls, args = m2.group(1), m2.group(2)
                def field(name, default=''):
                    mm = re.search(name + r'\s*=\s*"([^"]+)"', args)
                    return mm.group(1) if mm else default
                cat = re.search(r'Category\.(\w+)', args)
                dflt = re.search(r'defaultOn\s*=\s*(\w+)', args)
                decls[cls] = {'cls': cls, 'id': field('id', cls.lower()), 'title': field('title', cls),
                              'cat': cat.group(1) if cat else '?',
                              'default': dflt.group(1) if dflt else 'true',
                              'file': os.path.relpath(os.path.join(root, fn), ROOT)}
    return [decls[c] for c in order if c in decls] or list(decls.values())


def local_snapshot():
    """没有设备时，用 `work/activity_inputs/` 的冻结抓取当"计数"来源（README 说明其来源）。

    为什么改成目录：单一文件（旧的 `kdkit_capture_r1.txt`）只覆盖一轮、容易是切片，
    于是"某功能 0 条"既可能是没触发、也可能是这份文件里恰好没有。目录 + 固定清单让
    计数可重复，并与 `module/ACTIVITY.md` 用同一批输入。
    """
    cap = ''
    for cand in ('work/dpsdk/kdkit_capture_r1.txt', 'work/session_state.json'):
        fp = os.path.join(ROOT, cand)
        if os.path.exists(fp) and cand.endswith('.txt'):
            with open(fp, encoding='utf-8', errors='replace') as fh:
                cap = fh.read()
            break
    modlog = ''
    packs = os.path.join(ROOT, 'work/packs')
    if os.path.isdir(packs):
        for tag in sorted(os.listdir(packs), reverse=True)[:2]:
            mr = os.path.join(packs, tag, 'module_report.md')
            if os.path.exists(mr):
                modlog = textio.read_text(mr, encoding='utf-8', errors='replace')
                break
    return modlog, cap


def parse_state(modlog):
    """从模块日志算出每个功能的**真实生效状态**（`True`/`False`）。

    判据是两段，顺序不能反：

    1. `feature on|off: <id>` —— **钩子是否装上**（hot 功能恒装，所以这里几乎总是 True）；
    2. `HookCore gates off: a,b,c` —— **配置层面被关掉的清单**。

    `feature on` 只表示"装上了"，**不表示"配置开了"**。只用它算「当前」时，24 个
    `defaultOn=false` 的 hot 功能会被显示成 ON —— 2026-11-09 实测：矩阵说
    `block_ad_sdk` = ON，而同一份日志的 `gates off` 清单里明确列着它。
    两个人对同一台设备的描述不一致，而读报告的人不会去翻日志。
    """
    state = {}
    for m in re.finditer(r'feature (on|off): (\S+)', modlog):
        state[m.group(2)] = m.group(1) == 'on'
    off = re.search(r'HookCore gates off: ([^\n]+)', modlog)
    if off:
        closed = {x.strip() for x in off.group(1).split(',') if x.strip()}
        loaded = {k for k, v in state.items() if v}
        for fid in loaded:
            state[fid] = fid not in closed
    return state


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=None)
    ap.add_argument('--offline', action='store_true',
                    help='不需要设备：用工作区快照/纯静态事实生成矩阵（"当前"列为 ?）')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])
    if not a.offline and not a.adb:
        ap.error('需要 --adb <serial>，或使用 --offline')

    if a.offline:
        modlog, cap = local_snapshot()
        offline = True
        inputs = os.path.join(ROOT, 'work', 'activity_inputs')
        caps = sorted(os.path.join(inputs, f) for f in os.listdir(inputs)
                      if f.endswith('.txt')) if os.path.isdir(inputs) else []
        real_counts = count_from_captures(caps) if caps else {}
    else:
        logpath = adb(a.adb, 'ls -t /data/adb/lspd/log/modules_*.log | head -1')[1].strip()
        modlog = adb(a.adb, f'grep -a KdKit {logpath}')[1] if logpath else ''
        cap = adb(a.adb, f'cat /data/data/{PKG}/files/kdkit_capture.txt')[1]
        offline = False
        real_counts = {}
    state = parse_state(modlog)

    # 「当前」列的判据在 `parse_state()` 里（历史上这里是内联代码，2026-11-09 抽出来以便单测）（2026-11-09 修，B4）。
    #
    # `feature on: <id>` 只表示**钩子装上了**（hot 功能恒装），不表示"配置开了"。
    # 只用它算"当前"时，24 个 `defaultOn=false` 的 hot 功能会被显示成 ON ——
    # 实测例子：矩阵说 `block_ad_sdk` = ON，而同一份日志的
    # `HookCore gates off:` 清单里明确列着 `block_ad_sdk`。
    # 两个人对同一台设备的描述不一致，且**读报告的人不会去翻日志**。
    _off = re.search(r'HookCore gates off: ([^\n]+)', modlog)
    if _off:
        closed = {x.strip() for x in _off.group(1).split(',') if x.strip()}
        loaded = {k for k, v in state.items() if v}
        for fid in loaded:
            state[fid] = fid not in closed
    rm = textio.read_text(os.path.join(ROOT, 'ROADMAP.md'), encoding='utf-8')

    # Rounds are (id, theme, body). "Strong" needs the feature in the *theme line* — a round's
    # body mentions many ids incidentally (this very matrix round lists them), and counting those
    # would let a documentation round bless every feature.
    sections = []
    for sec in re.split(r'^### ', rm, flags=re.M)[1:]:
        head, _, body = sec.partition('\n')
        # `rid` 必须是**轮次号本身**，不能是整条标题。
        #
        # 旧写法 `head.split('·')[0]` 假设每个标题都是 `R3 · 日期（…）：主题`。
        # 但 ROADMAP 里有不合该格式的标题，例如：
        #     ### R3 追加（同轮下半场）：PK 自动作答实机复核 + 独立设备环境
        # 它没有 `·`，于是 `split('·')[0]` 返回整条标题 ⇒ 引用列渲染成
        #     "R3 追加（同轮下半场）：PK 自动作答实机复核 + 独立设备环境 以它为主题 + 证据文件"
        # 一句话里嵌了一整条标题，既难读，也没法按轮次号索引。
        # 正确做法是只取开头那个 `R<数字>`。
        m_rid = re.match(r'(R\d+)', head.strip())
        rid = m_rid.group(1) if m_rid else head.split('·')[0].strip()
        theme = head.split('：', 1)[-1].strip() if '：' in head else head.strip()
        files = [p for p in re.findall(r'`((?:work|kit|module)/[\w./\-]+\.(?:md|txt|json|png))`', body)
                 if os.path.exists(os.path.join(ROOT, p))]
        sections.append((rid, theme, body, files))

    static = static_hook_evidence()
    shared = shared_hook_owners()
    rows = []
    for f in features():
        # 离线模式没有进程可观测 ⇒ 一律 ?（不是 OFF —— 那会被读成"功能被关了"）
        on = None if offline else state.get(f['id'])
        if real_counts is not None and real_counts != {}:
            cnt = real_counts.get(f['id'], 0)
        elif f['id'] in CAPTURE_FEATURES:
            cnt = cap.count(CAPTURE_MARKERS.get(f['id'], '\x00'))
        else:
            cnt = 0
        keys = [f['id']] + KEYWORDS.get(f['id'], [])
        # 选哪一轮代表这个功能：**优先"建功能"的那一轮，而不是"最近提到它"的那一轮**。
        #
        # 旧实现是 `subject[-1]`，即"最后一个主题命中的轮次"。它把因果搞反了：
        # 后来一轮只要主题里出现同一个词，就会把前面的实测轮次顶掉。实测到的三例：
        #
        #   skip_onboarding → 取到 R501「把"七步的**可跳过性**"统计出来」（方法论讨论），
        #                     而真正做这个功能的是 R11「模块新功能 —— 跳过首次启动引导（含对照验收）」
        #   pk_assist       → 取到 R28「接口探测」，而真正做它的是 R3「PK 自动作答实机复核」
        #   web_request_log → 取到 R134「页面地图补上…」，而建功能的是 R119「加第 19 个功能」
        #
        # 关键词是**子串**匹配（`跳过` 命中了"可跳过性"，`引导` 命中了"AI 引导问题表"），
        # 所以越往后的轮次越容易误撞。只靠"取最后一个"必然逐渐漂到无关轮次。
        # 判据改成两条：(1) 主题里明确出现"功能 / 新功能"这类**建功能**措辞的优先；
        # (2) 都满足或都不满足时，取**最早**那一轮（建功能总在引用之前）。
        BUILD_MARKERS = ('新功能', '加**第', '加第', '第 19 个功能', '功能：', '模块新功能')

        def _rank(item):
            rid, theme, _b, _fl = item
            is_build = any(mk in theme for mk in BUILD_MARKERS)
            # 轮次号：R11 < R501，取小者（更早 = 更接近"建"的时刻）
            num = int(re.sub(r'\D', '', rid) or 0)
            return (0 if is_build else 1, num)

        subject = [s for s in sections
                   if any(match_keyword(k, s[1]) for k in keys) and s[3]]
        group = [(rid, fl) for rid, theme, _b, fl in sections
                 if f['cat'] == 'ADS' and '广告' in theme and fl
                 and (rid, fl) not in [(r, g) for r, _t, _b2, g in subject]]
        if subject:
            pick = sorted(subject, key=_rank)[0]
            level, why = '强', f'{pick[0]} 以它为主题 + 证据文件'
            ev = pick[3]
        elif f['id'] in CAPTURE_FEATURES:
            if cnt:
                level, why = '中', f'可计数记录（本轮 {cnt} 条）'
            else:
                # 有前缀、但样本 0 条：不能写成"可计数记录（0 条）"——那读起来像"功能坏了"。
                level, why = '中', '前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四）'
            ev = sorted({p for _rid, _th, _bd, fl in sections[-3:] for p in fl})[:3]
        elif group:
            level, why = '中', f'在"{group[-1][0]} 的广告组实验"里被覆盖（非单独验证）'
            ev = group[-1][1]
        else:
            level, why = '弱', '仅"已安装/已启用"可见'
            ev = []
        # 静态证据：按"该 feature 所在源文件"的钩子解析情况
        # 按 **功能对象** 取名，不是按文件名 —— 否则同文件里的 7 个广告功能共享一个数字。
        hooks = static.get(f['cls'])
        if hooks:
            sshow = f'{hooks[0]}/{hooks[1]}'
        elif f['cls'] in shared:
            # 钩子挂在共享点上（`WebInjector.install`）—— 记成 `共享:<owner>` 而不是 `0/0`，
            # 因为 `0/0` 会被读成"钩子一个都没解析出来"，与事实相反。
            sshow = f'共享:{shared[f["cls"]]}'
        elif f['id'] in FEATURES_LOGCAT_ONLY:
            # 结构性没有钩子的功能（seccomp / 纯注入 / PK 自动作答）写 `—`，
            # 与"有钩子但没解析出来"的 `0/N` 分开，避免把"不用钩"读成"钩不上"。
            sshow = '—'
        else:
            sshow = '0/0'
        # 静态证据把"弱"的含义说清：钩子解析成功 ≠ 运行有效，但也不等于"什么都没证明"。
        # 不这么写，读者会把"有 smali 级证据、只是还没上真机"当成"一次验证都没做过"。
        if level == '弱' and hooks and hooks[0] > 0:
            why = (f'钩子目标 {hooks[0]}/{hooks[1]} 在 APK 中解析成功（含形参签名），'
                   f'但尚无真机/实验证据')
        rows.append((f, on, cnt, level, why, sorted(dict.fromkeys(ev))[:3],
                     [rid for rid, _th, bd, _f in sections if f['id'] in bd][-2:], sshow))

    out = ['# 模块功能验证矩阵（自动生成）', '',
           f'* 来源：`FeatureRegistry.kt` + 模块日志/抓取（{"离线快照" if offline else "当前进程"}）+ `ROADMAP.md`',
           ('* 生成：`python3 kit/scripts/feature_matrix.py --offline --out module/VERIFICATION.md`'
            if offline else
            '* 生成：`python3 kit/scripts/feature_matrix.py --adb <serial> --out module/VERIFICATION.md`'),
           ('* **离线模式**：无设备 ⇒ "当前"列一律 `?`（不是 OFF）。**记录数**来自 '
            '`work/activity_inputs/` 的 5 份冻结抓取（与 `module/ACTIVITY.md` 同一批输入），'
            '按 `capture_schema.py` 的真实前缀解析计数，不是 substring 匹配。'
            if offline else ''), '',
           '| feature | 标题 | 分类 | 默认 | 当前 | 记录数 | 静态钩子 | 验证等级 | 真机 | 依据 | 代表证据 |',
           '|---|---|---|---|---|---|---|---|---|---|---|']
    for f, on, cnt, level, why, files, rounds, sshow in sorted(rows, key=lambda r: (r[3] != '强', r[0]['id'])):
        # 真机列永远是「未验证」直到有人真的跑过：静态钩子解析成功 + 编译通过 + 单测，
        # 都不能替代"设备上行为真的变了"。写死 '未验证' 比留空更安全 —— 空会被读成"没问题"。
        out.append(f'| `{f["id"]}` | {f["title"]} | {f["cat"]} | {f["default"]} | '
                   f'{"ON" if on else ("OFF" if on is False else "?")} | {cnt} | {sshow} | **{level}** | '
                   f'{"未验证" if offline else "见本轮日志"} | {why} | '
                   + ('<br>'.join(f'`{x}`' for x in files) if files else '-') + ' |')
    out += ['', '**`真机` 列**：`未验证` = 本轮**没有**设备跑过这个功能。'
                '门禁能证明的是"钩得住、编译过、纯逻辑对"，不能证明"设备上行为真的变了"。',
            '', '**读法**：`静态钩子` = 该功能的钩子目标在解码后的 APK 里解析成功数/总数'
                '（含形参签名，由 `check_hook_signatures.py` 给出）—— 它证明"钩得住"，'
                '**不**证明"跑起来有效"。等级只描述"我们现在能用什么证据说话"，'
                '不代表功能好坏；`弱` 的项要么补一个实验，要么承认它只能靠"安装 + 启用"作证。', '']

    # ── 「强」不等于"本批抓取里跑起来了" ─────────────────────────────────────
    #
    # 判「强」的依据是"ROADMAP 里有一轮以它为主题、且那一轮留了证据文件"。
    # 它衡量的是**历史上做过实验**，与**本批样本里有没有行**是两件事。
    # 于是会出现看起来自相矛盾的行：等级 `强`、记录数 `0`。
    #
    # 不解释这一格，读者会得出两种相反的错结论：要么"强 ⇒ 已验证"（把静态当运行时），
    # 要么"0 条 ⇒ 功能坏了"（把样本年龄当失效）。两种都写过文档、也都错过。
    strong_zero = sorted(f['id'] for f, _o, c, lvl, _w, _f2, _r, _s in rows
                         if lvl == '强' and c == 0)
    if strong_zero:
        out += [
            '### 为什么有"等级 `强`、记录数 `0`"的行\n',
            f'共 **{len(strong_zero)}** 行是这种组合：',
            ', '.join(f'`{i}`' for i in strong_zero) + '。\n',
            '两列回答的是**不同问题**，不矛盾：\n',
            '| 列 | 回答什么 | 来源 |',
            '|---|---|---|',
            '| 等级 `强` | 历史上**有没有做过**以它为主题的实验 | `ROADMAP.md` 的轮次 + 落盘证据文件 |',
            '| 记录数 `0` | **这 5 份冻结抓取里**有没有它写的行 | `work/activity_inputs/`（采样止于 2026-10-18） |\n',
            '所以 `强 + 0` 的正确读法是：**实验做过（有证据文件），但这批样本里没有它的行** ——'
            '原因通常是"功能默认关"或"样本早于该功能"（见 `module/ACTIVITY.md` §四）。\n',
            '**它不表示"已在真机上验证通过"。** 全表 36 行的 `真机` 列都是 `未验证` ——'
            '没有任何一行是设备上端到端跑通并前后对比过的。\n',
        ]
    text = '\n'.join(out) + '\n'
    if a.out:
        textio.write_text(a.out, text)
        print(f'[matrix] -> {a.out}')
    print('\n'.join(out[6:14]))
    counts = defaultdict(int)
    for _f, _o, _c, lvl, _w, _fl, _r, _s in rows:
        counts[lvl] += 1
    print(f'\n[matrix] {dict(counts)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
