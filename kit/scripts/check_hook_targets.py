#!/usr/bin/env python3
"""
kuaidui-kit / check_hook_targets.py — static regression check for the KdKit module.

Every Xposed hook in `module/.../features/**` names a class + method in the host APK. Two
different failures make a hook useless, and this script checks both:

  1. **the target is gone** — a host update renamed/removed it. `Xp.hook` then returns false
     and logs "hook failed …" → the feature silently stops working.
  2. **the target is never called** — the class/method still exists, so (1) passes, and the
     hook installs "successfully", but nothing ever invokes it. The feature reports ready and
     produces zero evidence. `BrushMaskView` (§`module/NEW_TARGETS.md` §2.1) is the canonical
     case: its class is referenced **nowhere else in 60 972 smali files**, not even from a
     layout, because it lives in the packer's own namespace (`com.byazt.*`) and is dead code.

(2) is what the `CALLERS` column adds. The method is *deliberately blunt*: it counts
`invoke-*` references to the target class across all smali roots, in one streaming pass, and
classifies the result. It is not a call graph — see `--explain` output and the `limits` notes
in the JSON.

It understands the module's own conventions:
    private const val PKG = "com.kuaiduizuoye.scan"
    Xp.hook("$PKG...TabAdvertisementView", "initData", ...)
    for ((cls, m) in listOf("com.x.Y" to "initSdk", ...))

    python3 kit/scripts/check_hook_targets.py                # work/apktool_out + module
    python3 kit/scripts/check_hook_targets.py --json out.json
    python3 kit/scripts/check_hook_targets.py --no-callers   # skip layer (2)

Exit code 0 when every target resolves, 1 otherwise (usable as a pre-deploy gate).
`--strict-dead` also fails on targets proven dead; the default only *reports* them, because
"no caller found" can legitimately mean "called via reflection from the packer".

Caller classification (per target class):
    LIVE        ≥1 incoming invoke-* from another class
    SELF-ONLY   only referenced from its own file (fields/methods) — no external caller
    DEAD        zero references anywhere outside its own file
    PLATFORM    framework class (`android.*` / `java.*`) — not analysed
    UNKNOWN     class not in the index (already reported as MISSING-CLASS)
"""
import argparse
import json
import os
import re
import sys

import hook_vocab as vocab
from hook_vocab import read_text, repo_path
from collections import defaultdict

# The class argument is either a literal (`"a.b.C"`), a template (`"$PKG.C"`), or a bare
# `const val` name (`CLS`). All three appear in real module code, and a missed form means a
# target silently escapes the gate — which is the exact failure this script exists to prevent.
#
# `hookAll*`（`hookAll` / `hookAllBefore` / `hookAllAfter`）曾经只被 ⑥ 看到、**完全没进 ④⑤**：
# 旧正则写的是 `Xp\.(hook|hookAll|clazzOrNull)\(`，而 `hookAllBefore(` 在 `hookAll` 后面
# 紧跟的是 `B` 不是 `(`，于是 12 条钩子（`SignObserver` 2 / `LogSink` 1 / `NativeProbe` 1 /
# `BridgeGuard` 2 / `H5BridgeLog` 2 / `H5Debug` 2 / `ReqHeaders` 2）从未被"类和方法存在吗"校验过。
# 现在用 `hook\w*`，并把 `clazzOrNull` 单独留着（它没有方法名）。

# 本地包装器形态：`hook("类", "方法")` / `hookBytes("类", "方法")`。
# 存在理由：`SignObserver` 把 gate 检查、异常兜底、记账包在 `hook()` 里，
# 调用点只写字面量 —— 但门禁此前只认 `Xp.hook(`，于是这些目标全成了盲区
# （2026-10-25 发现 8 个：Net.appendSign、yl.f.*、baseutil.a.*）。
# 识别包装器比强迫每个调用点展开成 Xp.hook 更实际：包装器是有正当理由的。
LOCAL_WRAPPER_RE = re.compile(
    r'\bhook(?:Bytes)?\(\s*"([^"]+)"\s*,\s*"([^"]+)"')


CALL_RE = re.compile(
    r'Xp\.(hook\w*)\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*(?:,\s*"([^"]+)")?'
    r'|Xp\.(clazzOrNull)\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))')
# `Xp.hook("类", m, …)` —— 方法名是**循环变量**（或任意裸标识符）。
# `CALL_RE` 的第二实参只匹配引号形式，于是 `for (m in listOf("d","f","h")) Xp.hook("aj.a", m, …)`
# 会被记成一个"方法名为空"的目标：`aj.a.`（`OK(load)`）。后果是这 5 个真实钩子
# （`RemoveAdSlotConfig` 3 个 + `AdSlotProbe` 3 个 + `LogSink` 4 个）**从未被签名/调用方校验**。
# 单独一个正则把裸标识符也抓出来，再按 `listOf` 展开成字面量。
CALL_VAR_METHOD_RE = re.compile(
    r'Xp\.(hook\w*)\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*,\s*([A-Za-z_]\w*)')
# `Xp.hookCtor("a.b.C", String::class.java, …)` — 构造器钩。方法名恒为 `<init>`，不是字面量，
# 所以 CALL_RE 永远匹配不到它，`hookCtor` 的目标此前**完全没有**进入 ④⑤⑥ 三道门。
# 真实后果：`watermark_off` 的主钩点（`cu.l` 14 参构造器）和 `RC4Probe` 的构造器钩
# 从未被"目标存在/签名对/有人调用"校验过 —— 换版后它们静默失效，门禁照绿。
# 正则故意只取类名：形参由 `check_hook_signatures.py` 解码 `Class` 参数后比对。
CTOR_RE = re.compile(r'Xp\.hookCtor\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))')
# 第四种形态：直接调 `XposedHelpers.findAndHookMethod` / `findAndHookConstructor`。
# 正则定义在 `hook_vocab.py`（三份清单的单一定义处），这里只引用。
# 覆盖到的真实目标：`ReqHeaders` 的 3 处（volley `v.getHeaders`、`Net.getStaticHeaders`、
# `Net.d(…)`）与 `WebRequestLog` java 侧的 `shouldInterceptRequest`。
# 它们此前对 ④⑤⑥ **完全不可见** —— `VERIFICATION.md` 的「静态钩子」列显示 `-`，
# 被读成"没有静态依据"，实际是"门禁不认这种写法"。
XPOSED_METHOD_RE = vocab.XPOSED_METHOD_RE
XPOSED_CTOR_RE = vocab.XPOSED_CTOR_RE
PAIR_RE = re.compile(r'"([A-Za-z_$][\w.$]*)"\s+to\s+"([\w$<>]+)"')
CONST_RE = re.compile(r'const val (\w+)\s*=\s*"([^"]*)"')
# 功能自写的局部包装。两种形态都真实存在：
#   `ExitGuard.hookAll("java.lang.System", "exit")`            —— 5 个目标
#   `SignObserver.hook("com.zuoyebang.baseutil.a", "d")`       —— 11 个目标
# 第二条尤其关键：`SignObserver` 是全模块最大的观测功能，它的 **11 个钩子**此前对
# ④⑤⑥ 三道门**完全不可见**（旧正则只认 `Xp.hook(`，而这些调用写的是裸 `hook(`）。
LOCAL_HOOKALL_RE = re.compile(r'\bhookAll\(\s*"([\w.$]+)"\s*,\s*"([\w$<>]+)"\s*\)')
# `(?<!\.)` 排除 `Xp.hook(`：那是另一条形态，由 CALL_RE 负责。
LOCAL_HOOK_RE = re.compile(r'(?<![\w.])hook\(\s*"([\w.$]+)"\s*,\s*"([\w$<>]+)"\s*[,)]')
# `for (m in listOf("d", "i", "w", "e")) { … Xp.hookAll("android.util.Log", m, …) }`
# 方法名是**循环变量** ⇒ 需展开成 4 个目标，否则会得到一条"方法名为空"的假目标。
# `listOf(...)` 的参数若含括号嵌套（例如 `listOf(a.name())`），`[^)]*` 会在第一个
# 右括号停下 ⇒ **整个 for 循环不被识别**，循环里的钩子对门禁完全不可见。
# 2026-10-26：`feature_matrix.py` 的 `SwitchFeature(...)` 就是因为同一原因
# （`summary` 里写了 `钩 dj.e.f()`）导致第 37 个功能从文档里消失。
# 改成允许一层嵌套。真需要更深时，应该写括号平衡扫描而不是继续堆正则。
LOOP_LIST_RE = re.compile(r'for\s*\(\s*(\w+)\s+in\s+listOf\(((?:[^()]|\([^()]*\))*)\)\s*\)')
LOOP_STR_RE = re.compile(r'"([^"]*)"')

# `invoke-virtual {v0, v1}, Lcom/x/Y;->m(I)V` and the /range form.
INVOKE_RE = re.compile(rb'^[ \t]*invoke-[a-z/-]+(?:/range)? \{[^}]*\}, (L[\w/$]+;)->([\w$<>]+)\(',
                       re.M)


def consts_of(path):
    """All `const val X = "..."` of one Kotlin file, templates resolved within the file."""
    text = read_text(path)
    raw = dict(CONST_RE.findall(text))
    out = {}
    for k, v in raw.items():
        for _ in range(3):  # resolve $OTHER references up to 3 levels
            v = re.sub(r'\$\{?(\w+)\}?', lambda m: raw.get(m.group(1), m.group(0)), v)
        out[k] = v
    return out


def expand(s, consts):
    if s is None:
        return None
    for _ in range(3):
        s = re.sub(r'\$\{?(\w+)\}?', lambda m: consts.get(m.group(1), m.group(0)), s)
    # Kotlin 里内部类要写 `HybridWebView\$ReturnCallback`（`$` 必须转义），
    # 而 smali 的类名是 `HybridWebView$ReturnCallback`。
    #
    # 还原这一步**必须在这里做**：不做的话，字面量里带着反斜杠，
    # `collect_targets` 末尾的 `'$' in cls and not re.fullmatch(r'[\w.$]+', cls)` 会把整条
    # 目标**丢掉**，于是带内部类的钩子对 ④⑤⑥ 三道门**全部不可见** ——
    # 2026-10-25 实测：`H5BridgeLog` 的出站钩子
    # `Xp.hook("…HybridWebView\$ReturnCallback", "call", …)`（全 APK 277 处调用点）
    # 从来没被任何一道门校验过，而三道门一直是绿的。
    # `check_hook_signatures.expand_all` 早就做了同一件事（否则那里会误报不符），
    # ④ 却漏了 —— 两处各写一套的典型后果。
    return s.replace('\\$', '$')


def smali_roots(smali_root):
    """<root>/smali and <root>/smali_classesN are the class-path roots."""
    roots = []
    for name in sorted(os.listdir(smali_root)):
        p = os.path.join(smali_root, name)
        if os.path.isdir(p) and (name == 'smali' or re.fullmatch(r'smali_classes\d+', name)):
            roots.append(p)
    return roots


def smali_index(smali_root):
    """class name ('a.b.c' or 'a.b.C$D') -> .smali path."""
    index = {}
    for root in smali_roots(smali_root):
        for base, _dirs, files in os.walk(root):
            for f in files:
                if not f.endswith('.smali'):
                    continue
                full = os.path.join(base, f)
                rel = os.path.relpath(full, root)[:-len('.smali')]
                index.setdefault(rel.replace(os.sep, '.'), full)
    return index


def method_names(path, cache={}):
    if path in cache:
        return cache[path]
    names = set()
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if line.startswith('.method'):
                    m = re.search(r'([\w$<>]+)\(', line)
                    if m:
                        names.add(m.group(1))
    except OSError:
        pass
    cache[path] = names
    return names


def collect_targets(module_dir):
    """`[(class, method, 'file:line')]` —— 模块里声明的每个钩子目标。

    **必须按整个文件扫，不能逐行扫。** 真实代码里调用经常跨行：

        val ok = Xp.hookCtor(
            "cu.l",
            *ctorTypes(cls),
            gate = id, …

    `watermark_off` 的主钩点就是这种形态。逐行扫时 `Xp.hookCtor(` 那一行没有类名，
    下一行才有 —— 结果这个目标**从未进入任何一道门禁**（2026-10-25 第 3 轮修）。
    行号由 match 位置反推，报错时仍然指得准。

    **不扫 `src/test`**（2026-10-26 第 40 轮修）。测试源码里会出现

        `Xp.clazzOrNull("…") ?: return` 这种写法下，钩子连**尝试**都没有

    这是**注释里的示例**，`CALL_RE` 照样把它抓成类名 `…`、方法名 `None`。
    后果不是"多一条噪声"：它让 ④ 的结论从 `123/123` 变成 123 真 + 1 假，
    而假目标永远 `MISSING`，把 `smali_usage` 的汇总从
    `114/114 有静态使用证据` 拉成 `113/114`。那一个"差 1"没有任何门禁会红 ——
    它只是让"全部有证据"这句话变成"几乎全部"，从而再也无法当作结论使用。

    测试源码不是被测对象：它不进 APK，里面的类名也不该被要求能在 APK 里解析到。
    """
    targets, seen = [], set()
    for base, _dirs, files in os.walk(module_dir):
        if os.sep + 'build' + os.sep in base + os.sep:
            continue
        # `src/test` / `src/androidTest` 不是被测产物：里面的示例代码不进 APK。
        if f'{os.sep}src{os.sep}test' in base or f'{os.sep}src{os.sep}androidTest' in base:
            continue
        for f in sorted(files):
            if not f.endswith('.kt'):
                continue
            path = os.path.join(base, f)
            consts = consts_of(path)
            rel = os.path.relpath(path, module_dir)
            text = read_text(path)
            found = []
            for m in CALL_RE.finditer(text):
                if m.group(5):                      # clazzOrNull：只有类，没有方法
                    found.append((expand(m.group(6) or consts.get(m.group(7), ''), consts),
                                  None, m.start()))
                else:                               # hook / hookAll / hookAllBefore / …
                    cls_lit = m.group(2) or consts.get(m.group(3), '')
                    meth_lit = m.group(4)
                    if meth_lit is None:
                        # 第二实参不是字面量 —— 典型是循环变量 `Xp.hook("aj.a", m, …)`。
                        # 这些目标由下面的 `CALL_VAR_METHOD_RE` 按 `listOf` 展开；
                        # 这里**不能**退回成一个空方法名（那就是 `aj.a.` 的来源，
                        # 会让 5 个真实钩子以 `OK(load)` 蒙过去）。
                        continue
                    found.append((expand(cls_lit, consts),
                                  expand(meth_lit, consts), m.start()))
            # 构造器钩：类名走同一套 const 展开，方法名固定 `<init>`。
            for m in CTOR_RE.finditer(text):
                found.append((expand(m.group(1) or consts.get(m.group(2), ''), consts),
                              '<init>', m.start()))
            for m in PAIR_RE.finditer(text):
                found.append((expand(m.group(1), consts), expand(m.group(2), consts), m.start()))
            # 直接调 `XposedHelpers.*`：与 `Xp.hook` 是同一种东西，只是没包记账层。
            # 第一实参是**局部变量**（`findAndHookMethod(cand, cl, …)`）⇒ 类名在运行时才定，
            # 静态无从校验：`consts.get` 取不到就留空串，由下面的 `if not cls` 丢掉这条。
            # （`Xp` 的候选名循环正是这个形态；不这么判会在门禁里造出 `cand.` 这样的假目标。）
            for m in XPOSED_METHOD_RE.finditer(text):
                found.append((expand(m.group(1) or consts.get(m.group(2), ''), consts),
                              expand(m.group(3), consts), m.start()))
            for m in XPOSED_CTOR_RE.finditer(text):
                found.append((expand(m.group(1) or consts.get(m.group(2), ''), consts),
                              '<init>', m.start()))
            # 功能自写的 `hookAll("类", "方法")` / `hook("类", "方法")` 包装。
            # 只认**两个都是字面量**的调用：`hookAll(cls, method)` 这种转发本身不算目标。
            for rx in (LOCAL_HOOKALL_RE, LOCAL_HOOK_RE):
                for m in rx.finditer(text):
                    found.append((expand(m.group(1), consts), expand(m.group(2), consts), m.start()))
            # 循环变量方法名：`for (m in listOf("d","f","h")) { Xp.hook("aj.a", m, …) }`
            # 必须按**作用域**展开 —— 同一文件里有两个 `m`（`("d","f","h")` 与 `("j","k")`），
            # 用一个"变量名 -> 列表"的全局字典会让后者覆盖前者，造出签名不符的假目标。
            scopes = vocab.loop_scopes(text)
            if scopes:
                for m in CALL_VAR_METHOD_RE.finditer(text):
                    lits = vocab.loop_literals_at(scopes, m.group(4), m.start())
                    if not lits:
                        continue
                    cls = expand(m.group(2) or consts.get(m.group(3), ''), consts)
                    if not cls or '$' in cls:
                        continue
                    for val in lits:
                        found.append((cls, val, m.start()))
            for cls, meth, pos in found:
                if not cls or '$' in cls and not re.fullmatch(r'[\w.$]+', cls):
                    continue
                lineno = text.count('\n', 0, pos) + 1
                key = (cls, meth, f'{rel}:{lineno}')
                if key in seen:
                    continue
                seen.add(key)
                targets.append((cls, meth, f'{rel}:{lineno}'))
    return targets


# ── layer (2): 有没有人调用它 ─────────────────────────────────────────────────
#
# **唯一判定处是 `kit/scripts/smali_usage.py`**（分层：直接 invoke > 类内调用 > 父类槽位 >
# 类型引用 > 反射入口 > DEAD）。这里只做两件事：把模块里的目标格式转过去、把结论并回表格。
# 为什么不在本文件里再写一份扫描：这个仓库已经踩过一次"两份实现互相不一致"（2026-10-25，
# 两份独立的调用图分析给出不同 verdict，门禁时红时绿）。判定只留一处，测试也只测那一处。

def usage_of(smali_root, targets, enabled=True):
    """{(class, method): smali_usage.Usage}；`enabled=False` 或脚本缺失时返回 {}。"""
    if not enabled:
        return {}
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import smali_usage
    except ImportError:
        return {}
    try:
        rows = smali_usage.analyse(smali_root, [(c, m) for c, m, _w in targets])
    except OSError:
        return {}
    return {(r.target, r.method): r for r in rows}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--smali', default=repo_path('work/apktool_out'))
    ap.add_argument('--module', default='module/app/src/main/java/dev/xalor/kdkit')
    ap.add_argument('--json', default=None)
    ap.add_argument('--no-callers', action='store_true',
                    help='skip layer (2): only check that the target exists')
    ap.add_argument('--strict-dead', action='store_true',
                    help='exit 1 when any target class has no external caller '
                         '(default: report only, because TYPE-ONLY model hooks are legitimate)')
    a = ap.parse_args(argv[1:])

    index = smali_index(a.smali)
    print(f'[check] {len(index)} classes indexed from {a.smali} '
          f'({", ".join(os.path.basename(r) for r in smali_roots(a.smali))})')
    targets = collect_targets(a.module)
    # 宿主混淆名映射：源码里的字面量是**基线（7.10.2/1860）**名，而 1865 那棵树里
    # 同一个逻辑目标叫别的名字。解析放在 usage 之前，这样
    #   ① 存在性/方法名/签名都查**这棵树真实的那一侧**；
    #   ② 调用方证据（SMALI-USAGE）也查那一侧 —— 否则会拿"同名错类"的引用统计
    #      去解释一条其实指向另一个类的钩子（`di.a` 在 1865 里就是另一个类）。
    # 表外的目标原样返回，行为与加表之前逐字节相同（见 hook_vocab.resolve_target）。
    ver = vocab.tree_version(a.smali)
    resolved = []
    for cls, meth, where in targets:
        checked, alias = vocab.resolve_target(cls, ver, a.module)
        resolved.append((cls, meth, where, checked, alias))
    if any(alias for *_x, alias in resolved):
        n_alias = sum(1 for *_x, alias in resolved if alias)
        print(f'[check] host-map: tree={ver} — {n_alias} 个目标的类名来自 HostMap 翻译'
              f'（源码写基线名，这棵树里叫另一个名字）')

    rows, bad, dead, weak = [], 0, [], []
    # 目标名必须是**合法 Java 标识符**。这一层存在的原因（2026-10-26 第 40 轮）：
    # 收集器扫的是源码文本，注释里的示例也会被 `CALL_RE` 抓走。实测抓到过
    # `Xp.clazzOrNull("…") ?: return` 里的 `…`，于是 ④ 的结论变成 123 真 + 1 假，
    # 且假目标恒为 MISSING —— 没有门禁会红，只让"全部有证据"退化成"几乎全部"。
    # 注释剥离很容易写漏（块注释嵌套、字符串里的 `//`），而"类名必须是标识符"
    # 是**无例外**的判据：真实类名不可能含 `…`，含了就一定是解析错误。
    malformed = [(c, m, w) for c, m, w in targets
                 if not re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*', c)]
    if malformed:
        print(f'[check] ✗ {len(malformed)} 个目标名不是合法类名 —— 源码里的注释/示例'
              f'被当成了钩子（收集器缺陷，不是 APK 的问题）：')
        for c, m, w in malformed:
            print(f'  ✗ {c!r}{"." + m if m else ""}   ({w})')
        bad += len(malformed)

    usage = usage_of(a.smali, [(c, m, w) for _l, m, w, c, _a in resolved],
                     enabled=not a.no_callers)
    for cls, meth, where, checked, alias in resolved:
        path = index.get(checked)
        if path is None and re.match(r'^(android|java|javax|dalvik|libcore)\.', cls):
            status = 'OK(platform)'
        elif path is None:
            status = 'MISSING-CLASS'
        elif meth is None or meth == '':
            # `meth is None` 来自 `Xp.clazzOrNull("a.b.C")`（只解析类，不钩方法）；
            # `meth == ''` 是 `collect_targets` 对同一种用法的另一条产出路径
            # （正则里方法名分组没匹配到 → 空串）。两者都必须按"只校验类"处理，
            # 否则会误报 MISSING-METHOD（2026-10-25 踩过：aj.a / cu.l 被误判）。
            status = vocab.VERDICT_LOAD
        elif meth in method_names(path):
            status = vocab.VERDICT_OK
        else:
            status = 'MISSING-METHOD'

        use = usage.get((checked, meth))
        if status in (vocab.VERDICT_OK, vocab.VERDICT_LOAD) and use is not None:
            if use.verdict == 'DEAD':
                # 类/方法都在，但 APK 里没有任何字节提到它 ⇒ 钩了必然空转。
                # 这是调用方层**唯一**判红的结论：更弱的"方法级不可达"需要全程序分析，
                # 静态证据不足（见 smali_usage.py），只提示不判死。
                status = 'DEAD-TARGET'
                dead.append((cls, meth, where, use.note))
            elif use.verdict != 'USED':
                weak.append((cls, meth, where, use.label(), use.note))

        if status.startswith('MISSING') or status == 'DEAD-TARGET':
            bad += 1
        rows.append({'class': cls, 'method': meth, 'where': where, 'status': status,
                     'checked': checked, 'alias': alias,
                     'usage': use.to_dict() if use is not None else None})
        print(f'  {status:15s} {cls}{"." + meth if meth else ""}   ({where})'
              + (f'   [alias→{checked}]' if alias else '')
              + (f'   [{use.label()}]' if use is not None else ''))

    print(f'[check] {len(targets) - bad}/{len(targets)} resolved')
    if weak:
        by = {}
        for _c, _m, _w, label, _n in weak:
            by[label] = by.get(label, 0) + 1
        print(f'[check] {len(weak)} 个目标没有直接 invoke（'
              + ', '.join(f'{k}={v}' for k, v in sorted(by.items()))
              + '）—— 可能经分派 / 反射 / 布局进入，静态无法证明；只提示，不判红')
        for cls, meth, where, label, _n in weak[:10]:
            print(f'  ~ {label:16s} {cls}{"." + meth if meth else ""}   ({where})')
        if len(weak) > 10:
            print(f'  ~ … 另有 {len(weak) - 10} 个')
    if dead:
        print('[check] 死目标（类/方法在，但 APK 里没有任何地方用到它 ⇒ 钩了必然空转）：')
        for cls, meth, where, why in dead:
            print(f'  ✗ {cls}{"." + meth if meth else ""}   ({where})')
            print(f'    {why}')
    if a.json:
        json.dump({'rows': rows,
                   'dead': [r['class'] for r in rows if r['status'] == 'DEAD-TARGET'],
                   'limits': [
                       'invoke-* only: reflection (Class.getMethod/forName), JNI and '
                       'manifest-declared components are not counted as callers',
                       'DEAD means "no byte in these smali roots mentions the descriptor"; '
                       'the packer could still patch a call site at runtime (com.byazt.*)',
                       '@FeAction targets are REFLECTIVE-ENTRY by design, not dead',
                       'INCOMPLETE means the read budget truncated the hit set: not a '
                       'verdict, rerun with a larger --read-budget',
                   ]}, open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'[check] report -> {a.json}')
    if bad:
        return 1
    if a.strict_dead and weak:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
