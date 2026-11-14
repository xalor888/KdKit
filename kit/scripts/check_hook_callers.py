#!/usr/bin/env python3
"""
kuaidui-kit / check_hook_callers.py — 钩子目标**有没有调用方**（死代码判定）。

为什么需要这第三个门禁：

  `check_hook_targets.py` 只问"类和方法存在吗"，
  `check_hook_signatures.py` 只问"形参类型一致吗"。

两个都回答"存在且签名对得上"，但**目标可能是永远不执行的死代码** ——
钩子挂上去、门禁全绿、功能从不生效。这个项目的真实案例：

  * `BrushMaskView.onDraw`（`smali_classes3/com/byazt/nd/`）：
    全 APK **0 处**引用它。它在加固壳 `com.byazt.*` 里，是残留的未使用代码。
    侦察阶段人工排除了它，但"人工排除"不是门禁。

本脚本的做法（全部静态，不需要设备）：

  1. 扫全部 `smali*` 的 `.method` 定义，建 `类->方法` 索引；
  2. 扫全部 `invoke-*` 指令，统计**每个方法被谁调用**（按 `L类;->方法名` 聚合，
     忽略签名 —— 混淆后同名重载很少，够用且不会漏）；
  3. 对我们 hook 的每个目标，给出：
       `OK`      有 ≥1 处外部调用
       `NO-CALLER` 0 处外部调用（**可疑死代码**，很可能是加固壳残留或从未接线的分支）
       `SELF-ONLY` 只有自调用（递归/同类内部调用，外部不可达）

适用边界（诚实写清）：

  * 反射调用（`Class.getMethod(...).invoke(...)`）不会被识别 ⇒ 可能把**可达**目标误报成 NO-CALLER。
    混淆后的 App 大量用反射，所以 `NO-CALLER` 是**待核查**而不是"确定死代码"。
  * `invoke-custom` / lambda（`invoke-static {..}, Lx;->a(Ljava/lang/Object;)Ljava/lang/Object;`）
    能识别到方法名，但 lambda 的合成方法名与业务无关，不构成"业务调用"。
  * 接口/抽象方法的实现由虚表分发，`invoke-virtual` 指向**声明类**而不是实现类 ⇒
    实现类的方法可能显示 0 调用方。这类要人工判断。

用法：
    python3 kit/scripts/check_hook_callers.py                # 全量
    python3 kit/scripts/check_hook_callers.py --json out.json
    python3 kit/scripts/check_hook_callers.py --strict       # NO-CALLER 也算失败

退出码：有 NO-CALLER 且未在 `KNOWN_DEAD` 白名单里时 1。
"""
import argparse
import json
import os
import re
import sys

import hook_vocab  # noqa: E402
import hook_vocab as vocab  # noqa: E402
from hook_vocab import read_text, repo_path

# 已知的死代码/不需要调用方的目标。**每一条都要写清为什么**，
# 不许为了让门禁变绿而往里塞名字。
# 键是 "类.方法"（精确）或 "类.*"（整类）。**每一条都要写清为什么**，
# 不许为了让门禁变绿而往里塞名字。
KNOWN_DEAD = {
    'com.byazt.nd.BrushMaskView.*': '加固壳残留 View，全 APK 0 引用（去水印误报）',
    # 加固壳 com.byazt.* 里的残留 View，全 APK 0 引用（2026-10-25 侦察确认）。
    # 它是"去水印"线索的误报来源：钩它不会有任何效果。
}


def dead_reason(cls, meth):
    """返回登记理由；未登记返回 None。支持 "类.方法" 与 "类.*"。"""
    return KNOWN_DEAD.get(f'{cls}.{meth}') or KNOWN_DEAD.get(f'{cls}.*')

# 方法名与 `.method` 头的词法**收在 `hook_vocab`**（单一定义处）。这里曾经自带一份
# `[\w$<>]+`，它把 Kotlin lambda 的 `foo$lambda-5$lambda-4` 切成方法名 `4` ——
# 24 个方法的真实名字因此从未进入索引，而门禁一直是绿的。见 `hook_vocab.SMALI_NAME`。
# 改词法只改那一处；三份脚本共用同一段正则，才不会漂移。
METHOD_RE = vocab.METHOD_HEADER_RE
# @FeAction 注解 = 由 FeActionDispatcher 反射调用，静态 0 调用方是**设计如此**
FEACTION_RE = re.compile(r'Lcom/zybang/annotation/FeAction;')
#: 保留 opcode 本身（`virtual` / `direct` / `interface` / `super` …）—— "有没有调用方"
#: 不够，还要看**是怎么调的**：只有虚分派/接口分派/父类调用才可能把子类覆写的方法带进来。
#: 少了这一位，`ql.a.getBody` 就只能报"0 调用点，待核查"。
INVOKE_RE = vocab.INVOKE_TARGET_RE
CLASS_RE = re.compile(r'^\.class\s+.*?L([\w$/]+);', re.M)


def smali_dirs(root):
    out = []
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if os.path.isdir(p) and (n == 'smali' or re.fullmatch(r'smali_classes\d+', n)):
            out.append(p)
    return out


_OVERRIDE_CACHE = {}


def collect_overrides(root):
    """类 -> 父类名。**带缓存**：单次要 ~19s（6 万类），不缓存会变成 O(n²)。"""
    if root in _OVERRIDE_CACHE:
        return _OVERRIDE_CACHE[root]
    sup = {}
    for d in smali_dirs(root):
        for base, _dirs, files in os.walk(d):
            for f in files:
                if not f.endswith('.smali'):
                    continue
                path = os.path.join(base, f)
                try:
                    # 只要 `.class` / `.super` 两行 ⇒ 有界读取。但**必须**用 with：
                    # 裸 `open(...).read(4096)` 会把句柄留给 GC，5 万个文件时撞
                    # `Too many open files` 并淹出 ResourceWarning（见 hook_vocab.read_text）。
                    with open(path, encoding='utf-8', errors='replace') as fh:
                        text = fh.read(4096)
                except OSError:
                    continue
                cm = CLASS_RE.search(text)
                sm = re.search(r'^\.super\s+L([\w$/]+);', text, re.M)
                if cm and sm:
                    sup[cm.group(1).replace('/', '.')] = sm.group(1).replace('/', '.')
    _OVERRIDE_CACHE[root] = sup
    return sup


_CHILD_CACHE = {}


def children_index(root):
    """父类 -> 直接子类集合（缓存一次，之后查子类不再全表扫描）。"""
    if root in _CHILD_CACHE:
        return _CHILD_CACHE[root]
    kids = {}
    for c, s2 in collect_overrides(root).items():
        kids.setdefault(s2, set()).add(c)
    _CHILD_CACHE[root] = kids
    return kids


def subclasses_of(root, cls):
    """找出所有直接/间接继承 cls 的类。用反向索引 BFS，不再每次全表扫描。"""
    kids = children_index(root)
    out, cur = set(), {cls}
    while cur:
        nxt = set()
        for c in cur:
            for k in kids.get(c, ()):
                if k not in out and k != cls:
                    out.add(k)
                    nxt.add(k)
        cur = nxt
    return out


def ancestors_of(root, cls, limit=32):
    """本类的祖先链（不含自己），由近及远。用于"向上"判定：本类是不是某个槽位的覆写。

    只走 `.super`（单继承）。接口槽位由 `invoke-interface` 指向接口声明类，那类通常
    不在解码目录里（`java.*` / `android.*`），因此接口场景由下面的 `SUPER-SLOT`
    在"祖先链上找不到声明"时按同类方法名保守兜底 —— 宁可多报一条待核查，也不漏判死代码。
    """
    sup = collect_overrides(root)
    out, cur = [], sup.get(cls)
    while cur and cur != cls and cur not in out and len(out) < limit:
        out.append(cur)
        cur = sup.get(cur)
    return out


#: 会把**子类覆写**带进来的调用形态。`invoke-super` 是子类显式调父类实现（钩覆写不会命中）；
#: 真正需要的是虚分派与接口分派 —— 接收者的实际类型可能是我们的目标类或其子类。
DISPATCH_OPS = frozenset({
    'virtual', 'interface', 'polymorphic', 'custom', 'custom/range', 'object',
})


def _defined_cached(root, cls):
    """某个类在解码目录里声明了哪些方法名（只读一次文件，避免 O(n²)）。"""
    if root not in _DEFINED_METHOD_CACHE:
        _DEFINED_METHOD_CACHE[root] = {}
    cache = _DEFINED_METHOD_CACHE[root]
    if cls in cache:
        return cache[cls]
    names = set()
    for d in smali_dirs(root):
        cand = os.path.join(d, cls.replace('.', os.sep) + '.smali')
        if os.path.exists(cand):
            try:
                text = read_text(cand)
            except OSError:
                break
            for m in METHOD_RE.finditer(text):
                names.add(m.group(2))
            break
    cache[cls] = names
    return names


_DEFINED_METHOD_CACHE = {}


def super_slot_sites(root, cls, meth, callers, self_file):
    """③ 层（向上）：本类的 `meth` 是不是某个祖先槽位的覆写，且那个槽位有人分派调用。

    返回 `[(rel, 偏移, 所在方法, opcode, 槽位类)]`；空列表表示"不是覆写，或槽位没人调"。

    为什么必须有这一层（2026-10-25 第 26 轮实测）：
      `ql.a` 直接 `extends Lcom/android/volley/d;`，自己声明 `getBody()[B`，
      全 APK **没有任何** `invoke-* ->Lql/a;->getBody` 调用点。旧逻辑只做**向下**判定
      （`subclasses_of` ⇒ polymorphic），于是把它降级成 `NEEDS-REVIEW`，门禁显示绿色
      却挂着一个"需确认"的悬案 —— 而那正是本项目最怕的形态：**绿门禁里的问号**。
      真槽位在**祖父类** `com.android.volley.v` 上（`d` 是抽象类但不声明 `getBody`），
      调用点有两处 `invoke-virtual {..}, Lcom/android/volley/v;->getBody()[B`。
      ⇒ 必须沿**整条祖先链**找声明，不能只看直接父类。
    """
    chain = ancestors_of(root, cls)
    if not chain:
        return []
    # 从最近的祖先开始找"声明了这个方法名"的那一层
    slot = next((a for a in chain if meth in _defined_cached(root, a)), None)
    if slot is None:
        # 祖先链上一个都没声明：可能是接口方法（接口不一定在解码目录里）。
        # 此时用**同类名方法的分派站点**保守判定：若某个 `invoke-interface`
        # 目标方法与 `meth` 同名且参数形状一致，按"可能进入"处理。
        sites = [(s, op, owner) for (owner, name), ss in callers.items()
                 if name == meth and owner != cls
                 for s in ss if s[3] in ('interface',)]
        if not sites:
            return []
        return [(s[0], s[1], s[2], op, owner) for s, op, owner in sites if s[0] != self_file]
    out = []
    for (owner, name), ss in callers.items():
        if name != meth or owner not in chain:
            continue
        for s in ss:
            if s[3] not in DISPATCH_OPS:
                continue
            # 自己文件里的分派不算外部入口（例如本类某个方法调父类实现）
            if s[0] == self_file:
                continue
            out.append((s[0], s[1], s[2], s[3], owner))
    return out


def build_index(root, wanted=None):
    """返回 (defined, callers, meta)。

    `wanted` = 我们 hook 的类名集合。给了它就只解析这些类的定义（快几个数量级），
    invoke 扫描仍然全量（要判"有没有调用方"，必须看全局）。

    meta['feaction'] = 带 @FeAction 注解的类（反射分发，静态无调用方是正常的）
    meta['private']  = {(类, 方法)} 表示该方法是 private
    """
    defined = {}
    callers = {}
    meta = {'feaction': set(), 'private': set()}
    # 只扫我们关心的类的**位置**，后续解析只读这些文件
    wanted_files = {}
    if wanted is not None:
        for d in smali_dirs(root):
            for cls in wanted:
                cand = os.path.join(d, cls.replace('.', os.sep) + '.smali')
                if os.path.exists(cand) and cls not in wanted_files:
                    wanted_files[cls] = cand
    for d in smali_dirs(root):
        for base, _dirs, files in os.walk(d):
            for f in files:
                if not f.endswith('.smali'):
                    continue
                path = os.path.join(base, f)
                try:
                    text = read_text(path)
                except OSError:
                    continue
                cm = CLASS_RE.search(text)
                if not cm:
                    continue
                cls = cm.group(1).replace('/', '.')
                # 定义了就不重复解析（同一类可能在多个 dex 里都有残留，取先见者）
                fresh = cls not in defined
                meths = defined.setdefault(cls, set())
                if fresh and wanted is not None and cls in wanted:
                    for m in METHOD_RE.finditer(text):
                        meths.add(m.group(2))
                    if FEACTION_RE.search(text):
                        meta['feaction'].add(cls)
                    for m in METHOD_RE.finditer(text):
                        if 'private' in m.group(1):
                            meta['private'].add((cls, m.group(2)))
                elif fresh and wanted is None:
                    for m in METHOD_RE.finditer(text):
                        meths.add(m.group(2))
                    if FEACTION_RE.search(text):
                        meta['feaction'].add(cls)
                    for m in METHOD_RE.finditer(text):
                        if 'private' in m.group(1):
                            meta['private'].add((cls, m.group(2)))
                rel = os.path.relpath(path, root)
                # 记录 (文件, 偏移, 调用点所在方法) —— 方法级才能区分"递归"与"同类别的方法在调它"。
                # 预过滤：文件里连 "invoke-" 都没有就整段跳过（529MB 里大部分是数据/资源类）。
                if 'invoke-' not in text:
                    continue
                hits = list(INVOKE_RE.finditer(text))
                if not hits:
                    continue
                # 只对命中行反查所在方法：把 method 的所有起点排好序，二分/线性一次走完
                meth_marks = [(dm.start(), dm.group(2)) for dm in METHOD_RE.finditer(text)]
                for m in hits:
                    # 组号全后移一位：1=opcode 2=owner 3=name
                    op, owner, name = m.group(1), m.group(2).replace('/', '.'), m.group(3)
                    enclosing = ''
                    for pos, mname in meth_marks:
                        if pos > m.start():
                            break
                        enclosing = mname
                    callers.setdefault((owner, name), set()).add(
                        (rel, m.start(), enclosing, op))
    return defined, callers, meta


def hook_targets(module_dir):
    """从 Kotlin 源码里取 (类名, 方法名, 出处)。

    **直接复用 `check_hook_targets.collect_targets`**，不再维护第二份正则。
    2026-10-25 实测三份清单互不相同：④ 73 条 / ⑤ 48 条 / ⑥ 48 条 —— 同一批钩子，
    三个数字。根因就是本函数与 `check_hook_targets.collect_targets` 各自演了一套
    （⑥ 旧正则只认 `Xp.hook(`，看不到 `hookAllBefore`，也看不到 `ExitGuard` 的局部包装）。
    判定层（`smali_usage`）早就是单一定义处了，识别层也必须一样。
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import check_hook_targets
    # 只判方法与类的**使用**，不判 `clazzOrNull` 的纯类引用（没有方法名可查调用方）。
    return [(c, m, w) for c, m, w in check_hook_targets.collect_targets(module_dir) if m]


def classify(root, module_dir):
    """把"钩子目标 → 状态"的判定做完整，返回 (rows, index)。

    与 `main()` 分开的原因：判定逻辑必须能被**测试直接调用**。
    以前它整段写在 `main()` 里，测试只能起子进程抓 stdout —— 于是
    "某个目标被降级成 NEEDS-REVIEW" 这类事实只能靠人眼看输出发现。
    """
    rows = hook_targets(module_dir)
    # 只解析我们 hook 的类的定义（6 万文件里几十个），invoke 仍全量扫
    defined, callers, meta = build_index(root, {c for c, _m, _w in rows})

    out = []
    for cls, meth, where in rows:
        slots = []
        # 平台类（android.* / java.*）不参与判定：它们的调用方在 framework 里
        if re.match(r'^(android|java|javax|kotlin|dalvik)\.', cls):
            out.append({'class': cls, 'method': meth, 'where': where,
                        'status': 'OK(platform)'})
            continue
        if cls not in defined:
            status = 'MISSING-CLASS'
        elif meth != '<init>' and meth not in defined[cls]:
            status = 'MISSING-METHOD'
        else:
            sites = callers.get((cls, meth), set())
            # 自调用（同一个 .smali 文件里的 invoke）不算"被外部使用"
            self_file = None
            for d in smali_dirs(root):
                cand = os.path.join(d, cls.replace('.', os.sep) + '.smali')
                if os.path.exists(cand):
                    self_file = os.path.relpath(cand, root)
                    break
            # 严格说："自调用" 应只指**方法调自己**（递归）。同文件里别的方法调它
            # 是正常的调用路径（例：HybridWebView.dispatchAction 由同类的
            # dispatchActionToListeners 调用 —— 那是真实业务入口）。
            external = {s for s in sites if s[0] != self_file}
            # 同文件、但**来自其它方法**的调用 = 真实入口（不是递归）
            in_class_other = {s for s in sites if s[0] == self_file and s[2] != meth}
            if external:
                status = 'OK'
            elif cls in meta['feaction']:
                # @FeAction 的 action 由 FeActionDispatcher 按 name 反射调用 ⇒ 静态 0 调用方是**设计如此**
                status = 'OK(reflective)'
            elif sites:
                if (cls, meth) in meta['private']:
                    # private 只可能被同类调用 ⇒ 正常形态
                    status = 'OK(private)'
                elif in_class_other:
                    # 同类的**别的方法**在调它 ⇒ 真实业务入口
                    status = 'OK(in-class)'
                elif subclasses_of(root, cls):
                    # 有子类 ⇒ 走虚表分发，钩父类能覆盖子类未重写的实现
                    status = 'OK(polymorphic)'
                else:
                    # 只有自己递归、没有子类 —— 真的可疑
                    status = 'SELF-ONLY'
            else:
                if dead_reason(cls, meth):
                    status = 'KNOWN-DEAD'
                elif (cls, meth) in meta['private']:
                    status = 'NO-CALLER'
                elif slots := super_slot_sites(root, cls, meth, callers, self_file):
                    # ③ 层（向上）：本方法是对**祖先槽位**的覆写，且那个槽位被分派调用过。
                    # 例：`ql.a.getBody` 覆写 `com.android.volley.v.getBody`（**祖父类**），
                    # 后者在 ZybHurlStack 与 lk.l0 里各有 `invoke-virtual`。
                    # 钩覆写**会**生效（分派落在这个实现上），所以这不是死代码。
                    status = 'OK(super-slot)'
                else:
                    # public/protected 却 0 调用方，且祖先链上也没有被分派的槽位：
                    # 可能是①死代码 ②反射/JS 注入入口。
                    # 标 NEEDS-REVIEW 而不是 NO-CALLER —— 它需要人看一眼，但不是"确定死"。
                    status = 'NEEDS-REVIEW'
        row = {'class': cls, 'method': meth, 'where': where, 'status': status,
               'call_sites': len(callers.get((cls, meth), ())),
               'callers_detail': sorted({(c[0], c[2])
                                         for c in callers.get((cls, meth), ())})[:6]}
        if slots:
            row['super_slot'] = slots[0][4]
            row['slot_call_sites'] = [(s[0], s[2], s[3]) for s in slots][:6]
        out.append(row)
    return out, {'defined': defined, 'callers': callers, 'meta': meta}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--smali', default=repo_path('work/apktool_out'))
    ap.add_argument('--module', default='module/app/src/main/java/dev/xalor/kdkit')
    ap.add_argument('--json', default=None)
    ap.add_argument('--strict', action='store_true', help='NO-CALLER 也算失败（默认只警告）')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--dead-ui', default=None, metavar='PKG',
                    help='额外反向枚举这个包下的"零引用 UI 子类"（可证明的死代码）。'
                         '只报告、不判红：这些类我们**没有**钩，它们只是"别去钩"的清单')
    a = ap.parse_args(argv[1:])

    if not os.path.isdir(a.smali):
        print(f'[callers] 跳过：{a.smali} 不存在（需要先 apktool 解码）')
        return 0

    out, _index = classify(a.smali, a.module)
    bad = sum(1 for r in out
              if r['status'] in ('NO-CALLER', 'MISSING-CLASS', 'MISSING-METHOD'))
    unknown = sum(1 for r in out if r['status'] in ('NEEDS-REVIEW', 'SELF-ONLY'))
    whitelisted = sum(1 for r in out if r['status'] == 'KNOWN-DEAD')
    if not a.quiet:
        for r in out:
            print(f'  {r["status"]:22s} {r["class"]}.{r["method"]}   ({r["where"]})')
            if r['status'] == 'NO-CALLER':
                print(f'  {"":22s} ↑ 全 APK 没有调用方：可能是死代码，也可能是反射/虚表调用'
                      f'（需人工确认，确认后加进 KNOWN_DEAD 并写理由）')
            if r['status'] == 'KNOWN-DEAD':
                print(f'  {"":22s} ↑ 已登记：{dead_reason(r["class"], r["method"])}')
            if r['status'] == 'OK(super-slot)' and 'slot_call_sites' in r:
                sites = ', '.join(f'{s[0]}:{s[2]}()' for s in r['slot_call_sites'][:2])
                print(f'  {"":22s} ↑ 覆写 {r["super_slot"]} 的槽位，'
                      f'分派调用点 {sites}')

    total = len(out)
    # 汇总行以前把 `NEEDS-REVIEW` 也算进"仅自调用"：它是 **0 个调用点**（一个都没有），
    # 而"仅自调用"意味着**有**递归调用。两件事被合并成一个数字，读起来像
    # "89 个目标里 88 个有调用、1 个只有自调用"，而真相是"1 个一个调用点都没有，
    # 需要人看一眼"。分开数：`grep -c NEEDS-REVIEW` 与括号里的明细要对得上。
    by_status = {}
    for r in out:
        by_status[r['status']] = by_status.get(r['status'], 0) + 1
    self_only = sum(1 for r in out if r['status'] == 'SELF-ONLY')
    review = sum(1 for r in out if r['status'] == 'NEEDS-REVIEW')
    print(f'[callers] {total} 个目标：{total - bad - unknown - whitelisted} 有外部调用 / '
          f'{bad} 无调用方 / {self_only} 仅自调用 / {whitelisted} 已登记死代码'
          + (f' / {review} 待核查（0 调用点，非递归）' if review else ''))
    if review:
        for r in out:
            if r['status'] == 'NEEDS-REVIEW':
                print(f'  ? {r["class"]}.{r["method"]}   ({r["where"]}) —— 0 个调用点，'
                      f'需确认是反射/JS 入口还是真死代码')
    # ── 反向枚举：**没有钩到**的可证明死代码 ──────────────────────────────────
    #
    # 上面那一轮只检查"模块钩了的那些目标"。但 `BrushMaskView` 那次失效的根因
    # 不是判定错，而是**没人想到要把它列为目标**。所以这里再正向扫一遍：
    # 哪些类是"零引用 + UI 子类"⇒ 无法被实例化 ⇒ 别去钩。
    #
    # 只报告、不判红：这些类我们本来就没钩，它们不是失败，是一张"别浪费钩子"的清单。
    # 一旦哪天有人把它们加进模块，上面那一轮就会把它们判成 DEAD-TARGET 并**真的**判红。
    if a.dead_ui is not None:
        try:
            import smali_usage as _su
            found = _su.find_dead_ui_classes(a.smali, limit=300,
                                             roots_filter=[a.dead_ui] if a.dead_ui else None)
        except Exception as e:                                # noqa: BLE001
            print(f'[callers] dead-ui 扫描失败（不判红，仅提示）：{e}')
            found = []
        if found:
            hooked = {(r['class'], r['method']) for r in out}
            print(f'[callers] 另有 {len(found)} 个"零引用 UI 子类"——'
                  f'**可证明的死代码，别去钩**（给 {a.dead_ui or "全量"}）：')
            for r in found:
                mark = '  ⚠ 模块已钩' if any(c == r['class'] for c, _m in hooked) else ''
                print(f'  ✗ {r["class"]:56s} <- {r["ui_base"]}{mark}')
            print('[callers] 判据：UI 子类 + 零外部引用 + 未被布局/清单引用 ⇒ 无路径可实例化。'
                  '加固壳仍可能在运行时 patch 出调用点，所以只报告、不判红。')
        else:
            print(f'[callers] dead-ui 扫描：{a.dead_ui or "全量"} 下没有零引用 UI 子类')

    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)
        print(f'[callers] report -> {a.json}')
    if bad:
        return 1
    if a.strict and unknown:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
