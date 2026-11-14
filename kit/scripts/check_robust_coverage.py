#!/usr/bin/env python3
"""
kuaidui-kit / check_robust_coverage.py — 钩子目标有多少落在**热修复补丁点**后面。

为什么这值得一道门禁
--------------------
第 ④⑤⑥ 三道门都建立在同一个隐含前提上：**"静态看到的这个方法体就是运行时执行的那个"**。

宿主集成了美团 Robust（`com.meituan.robust`）。它的做法是在每个"可打补丁"的方法开头插一段：

    sget-object v3, Llk/f;->changeQuickRedirect:Lcom/meituan/robust/ChangeQuickRedirect;
    ...
    const/16 v5, 0x4dec                      # 方法序号
    invoke-static/range {v1 .. v7}, Lcom/meituan/robust/PatchProxy;->proxy(...)
    move-result-object v0
    iget-boolean v0, v0, Lcom/meituan/robust/PatchProxyResult;->isSupported:Z
    if-eqz v0, :cond_0
    return / return-void                     # ← 补丁生效时**直接返回，原方法体一行都不执行**
    :cond_0
    ...                                      # 原方法体

`PatchProxy.isSupport()` 在 `changeQuickRedirect != null` 时把判定委派给那个对象
（`PatchProxy.smali:586-701`），所以**服务端下发一个补丁就能让任意被插桩的方法换实现**。

对模块的含义，具体而不是抽象的：

  * `XposedBridge.hookMethod` 挂的是 `Method` 对象 ⇒ 钩子仍在，`before`/`after` 仍会跑；
  * 但被 `return` 掉的是**原方法体** ⇒ 所有"改返回值 / 改字段 / 读回包"的语义都失效；
  * 于是功能会显示 `installed`、日志有 `hooked`，**行为却完全不发生** —— 与
    `BrushMaskView` 那类死代码同一种失败形态：绿门禁 + 零效果。

第 ⑥ 道门（`check_hook_callers.py`）已经能证明"有人调用"，它同样看不见这一层：
被插桩的方法**确实有调用方**，只是调用方拿到的是补丁的返回值。

静态能证明什么、不能证明什么（**这一节是这道门禁的边界，不要越过**）
------------------------------------------------------------------
能证明（本脚本的全部输出）：
  * APK 里哪些方法是"被插桩的" —— 判据是**同一个方法体内同时出现**
    ① `sget-object …, L<本类>;->changeQuickRedirect:…`、
    ② `PatchProxy;->proxy(`；
  * 我们 hook 的 115 个目标里，有多少落在这张表里。

**不能**证明：
  * 运行时是否**真的**有补丁下发。`changeQuickRedirect` 的静态初值是 `null`
    （全 APK 只有 `PatchExecutor` 在应用补丁时写它，见 `PatchExecutor.smali:1284/1488`），
    而 `zc/c`（`PatchesInfo` 的实现类）在**本地**只有空表；
  * 加固壳是否另有注入路径（`com.byazt.*` 可能自行改写）。

所以本脚本的措辞统一是"**暴露面**"，不是"已被替换"。默认**只报告不判红**，
因为它描述的是"宿主能做什么"，不是"模块做错了什么"。
`--fail-over <N>` 可把"暴露目标数"变成预算护栏（升级后突然变大 ⇒ 人工复核）。

    python3 kit/scripts/check_robust_coverage.py                  # 人读
    python3 kit/scripts/check_robust_coverage.py --json out.json  # 机器读
    python3 kit/scripts/check_robust_coverage.py --method lk.f:d  # 查单个目标

退出码：0 正常；1 目标解析失败或超过 `--fail-over` 预算。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hook_vocab as vocab  # noqa: E402
from hook_vocab import repo_path  # noqa: E402

# `changeQuickRedirect` 字段的类型描述符。用它而不是字段名匹配，是为了排除
# 同名但无关的字段（例如某个业务类自己叫 `changeQuickRedirect` 的 boolean）。
REDIRECT_DESC = 'Lcom/meituan/robust/ChangeQuickRedirect;'
PROXY_CALL = 'Lcom/meituan/robust/PatchProxy;->proxy('

# 与 `check_hook_callers.py` / `smali_usage.py` 保持同一套 `.method` 词法，
# 否则"哪些方法"这张表会和别的门禁对不上（同一个坑本仓库踩过：`hookAllBefore(` 漏识别）。
# `.method` 头词法**收在 hook_vocab**（单一定义处）—— 三份脚本共用，避免漂移。
# 旧版本自带 `[\w$<>]+`，把 `foo$lambda-5$lambda-4` 切成 `4`（见 hook_vocab.SMALI_NAME）。
METHOD_RE = vocab.METHOD_HEADER_RE
CLASS_RE = re.compile(r'^\.class\s+.*?L([\w$/]+);', re.M)
# Robust 的方法序号：`move-object v2, p0` 之后 `const/16 v5, 0x4dec`。
# 只取 sget 与 proxy 之间的那一个，避免把方法体里业务自己的 `const/16` 记成序号。
METHOD_NO_RE = re.compile(r'const/16\s+\w+,\s*(0x[0-9a-fA-F]+|-?\d+)')


def smali_roots(root: str) -> list[str]:
    """只认 `smali` / `smali_classesN` —— 与其余四道门禁同一规则。"""
    out = []
    for n in sorted(os.listdir(root)):
        p = os.path.join(root, n)
        if os.path.isdir(p) and (n == 'smali' or re.fullmatch(r'smali_classes\d+', n)):
            out.append(p)
    return out


def scan_file(path: str) -> tuple[str, list[dict]]:
    """解析一个 smali 文件 → (点分类名, [被插桩的方法…])。

    判定要求**同一方法体内**三条同时成立：有 `changeQuickRedirect` 的 sget、
    有 `PatchProxy;->proxy(` 调用、且两个标记之间读到了方法序号。
    缺任一条都可能是"字段存在但方法没插桩"或"调用了 proxy 但不是标准桩"——
    宁可漏报也不要把它们算成可补丁点（假红会教人无视门禁）。
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return '', []
    head = text[:4096]
    cm = CLASS_RE.search(head)
    if not cm:
        return '', []
    raw = cm.group(1)
    dotted = raw.replace('/', '.')

    # 快速否决：绝大多数文件既无字段也无调用，先按子串跳过 60k 次逐行解析。
    if REDIRECT_DESC not in text or PROXY_CALL not in text:
        return dotted, []

    has_field = any(l.lstrip().startswith('.field') and REDIRECT_DESC in l for l in text.splitlines())
    if not has_field:
        return dotted, []

    sget_marker = f'L{raw};->changeQuickRedirect'
    methods: list[dict] = []
    cur: tuple[str, str] | None = None
    seen_sget = False
    seen_proxy = False
    method_no: int | None = None

    for line in text.splitlines():
        s = line.strip()
        if s.startswith('.method '):
            h = vocab.parse_method_header(s)
            cur = (h[1], h[2] + h[3]) if h else None
            seen_sget = seen_proxy = False
            method_no = None
            continue
        if s.startswith('.end method'):
            if cur and seen_sget and seen_proxy:
                methods.append({'method': cur[0], 'desc': cur[1], 'method_no': method_no})
            cur = None
            continue
        if cur is None:
            continue
        if s.startswith('sget-object') and sget_marker in s:
            seen_sget = True
        elif PROXY_CALL in s:
            seen_proxy = True
        elif seen_sget and method_no is None:
            m = METHOD_NO_RE.search(s)
            if m:
                method_no = int(m.group(1), 0)
    return dotted, methods


def build_index(root: str, progress=None) -> dict[str, dict[str, dict]]:
    """点分类名 → 方法名 → 该方法被插桩的记录。**单遍**扫全部 smali 根。"""
    index: dict[str, dict[str, dict]] = {}
    all_methods: list[str] = []
    files = 0
    for r in smali_roots(root):
        for base, _dirs, names in os.walk(r):
            for n in names:
                if not n.endswith('.smali'):
                    continue
                files += 1
                if progress and files % 10000 == 0:
                    progress(f'… 已扫 {files} 个 smali')
                dotted, methods = scan_file(os.path.join(base, n))
                if not methods:
                    continue
                bucket = index.setdefault(dotted, {})
                for m in methods:
                    # 同名重载很少（混淆后更少）；保留**任一**插桩即算暴露，
                    # 因为运行时是按方法序号分派的，我们无法从钩子侧指定序号。
                    # ⇒ 索引键是**方法名**，同名重载会合并。所以下面报的
                    # `distinct_methods` 是"不同方法名的个数"，不是方法个数；
                    # `guarded_methods` 才是真正的桩数量。别把这两个数字混着用。
                    bucket.setdefault(m['method'], m)
                    all_methods.append(dotted)
    if progress:
        progress(f'… 共扫 {files} 个 smali 文件')
    setattr(build_index, 'guarded_methods', len(all_methods))
    return index


def load_hook_targets(apk_root: str) -> list[dict]:
    """复用 ④ 的解析结果，避免两套钩子词法漂移。"""
    import check_hook_targets as cht  # noqa: E402  延迟导入：它自己会扫源码，比较慢

    module = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit')
    targets = cht.collect_targets(module)          # [(class, method|None, 'file:line')]
    return [{'class': c, 'method': m or '', 'where': w} for (c, m, w) in targets]


def classify(index: dict, targets: list[dict]) -> list[dict]:
    rows = []
    for t in targets:
        cls, meth = t['class'], t['method']
        patched = index.get(cls, {})
        if meth in patched:
            status = 'GUARDED'
            info = patched[meth]
        elif patched:
            status = 'CLASS-PATCHED'
            info = None
        elif cls in index:
            status = 'CLASS-PATCHED'
            info = None
        else:
            status = 'PLAIN'
            info = None
        rows.append({**t, 'status': status, 'method_no': (info or {}).get('method_no')})
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description='哪些钩子目标落在 Robust 热修复补丁点后面')
    ap.add_argument('--smali', default=repo_path('work/apktool_out'))
    ap.add_argument('--json', default=None)
    ap.add_argument('--method', default=None, metavar='CLASS:METHOD',
                    help='只查一个目标（冒号分隔，方法可省）')
    ap.add_argument('--fail-over', type=int, default=None, metavar='N',
                    help='暴露目标数超过 N 时退出 1（默认只报告）')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--no-targets', action='store_true',
                    help='不读模块源码，只统计全 APK 的插桩规模')
    a = ap.parse_args(argv)

    if not os.path.isdir(a.smali):
        print(f'✗ 找不到解码目录：{a.smali}', file=sys.stderr)
        return 1

    def progress(msg):
        if not a.quiet:
            print(msg, file=sys.stderr)

    index = build_index(a.smali, None if a.quiet else progress)
    distinct_names = sum(len(v) for v in index.values())
    guarded_methods = getattr(build_index, 'guarded_methods', distinct_names)
    if not a.quiet:
        print(f'[robust] {len(index)} 个类、{guarded_methods} 个方法带 changeQuickRedirect 插桩'
              f'（{distinct_names} 个不同方法名）')

    if a.no_targets:
        if a.json:
            json.dump({'classes': len(index), 'guarded_methods': guarded_methods,
                       'distinct_method_names': distinct_names}, open(a.json, 'w'), indent=2)
        return 0

    targets = load_hook_targets(a.smali)
    if a.method:
        cls, _, meth = a.method.partition(':')
        targets = [t for t in targets if t['class'] == cls and (not meth or t['method'] == meth)]
        if not targets:
            # 允许直接查一个没被 hook 的方法，便于人工核查候选
            targets = [{'class': cls, 'method': meth, 'where': '(手动查询)'}]

    rows = classify(index, targets)
    guarded = [r for r in rows if r['status'] == 'GUARDED']
    cls_patched = [r for r in rows if r['status'] == 'CLASS-PATCHED']
    plain = [r for r in rows if r['status'] == 'PLAIN']

    if not a.quiet:
        print(f'[robust] 钩子目标 {len(rows)} 个：'
              f'GUARDED {len(guarded)} / CLASS-PATCHED {len(cls_patched)} / PLAIN {len(plain)}')
        for r in guarded:
            no = r["method_no"]
            print(f'  ⚠ GUARDED      {r["class"]}.{r["method"]}'
                  f'{"  #" + hex(no) if no is not None else ""}   ({r["where"]})')
        for r in cls_patched:
            print(f'  ~ CLASS-PATCHED {r["class"]}.{r["method"]}   ({r["where"]})')
        print('[robust] 说明：GUARDED = **该方法**被插桩（补丁生效时原方法体不执行）；'
              'CLASS-PATCHED = 同类里有别的插桩方法，目标方法本身未见插桩')
        print('[robust] 边界：静态无法证明运行时**真的**下发了补丁'
              '（changeQuickRedirect 初值为 null，只有 PatchExecutor 会写它）')

    if a.json:
        json.dump({
            'classes': len(index),
            'guarded_methods': guarded_methods,
            'distinct_method_names': distinct_names,
            'rows': rows,
            'limits': [
                'GUARDED 只证明方法被插桩，不证明运行时下发了补丁',
                'changeQuickRedirect 静态初值为 null；只有 PatchExecutor 应用补丁时写它',
                '加固壳（com.byazt.*）可能另有改写路径，不在本索引里',
                '同名重载按方法名归档：任一重载被插桩即整名标记',
            ],
        }, open(a.json, 'w'), indent=2, ensure_ascii=False)
        if not a.quiet:
            print(f'[robust] report -> {a.json}')

    if a.fail_over is not None and len(guarded) > a.fail_over:
        print(f'✗ GUARDED {len(guarded)} > 预算 {a.fail_over}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
