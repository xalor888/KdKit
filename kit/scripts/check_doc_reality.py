#!/usr/bin/env python3
"""
kuaidui-kit / check_doc_reality.py — "文档描述 ↔ 代码事实"这一类断言的**统一清单与状态**。

### 为什么需要它

这类断言已经有好几个，但各自散落在不同脚本里，没有一处能回答
"**这个仓库里，文档与代码的一致性由哪些断言守着？现在都过吗？**"：

| 断言 | 工具 |
|---|---|
| 功能表 ↔ `FeatureRegistry` | `check_feature_parity.py` |
| 钩点共享 ↔ `PARADIGM.md` §10 | `check_hook_sharing.py --strict` |
| 门禁表 ↔ `verify.sh` | `check_gate_table.py` |
| 自动生成文档 ↔ 它的生成器 | `check_generated_fresh.py` |
| 文档里的数字 ↔ 代码算出的值 | `docs_claims.py` |
| Kotlin 侧 ↔ 解析规则往返 | `check_schema_roundtrip.py --strict` |

R40 的教训：门禁表停在 ⑨ 而实际跑 19 条，**漂了 8 道没人发现** ——
不是因为没人写断言，而是因为**没有一份清单**，于是"哪个断言该存在"本身没被审视。

### 这个脚本做什么

* 不重复实现任何判据（仓库自己的规矩：一个口径只写一次）；
* 只做**登记 + 汇总**：跑一遍上面每一个工具，出一张表；
* 登记表本身是产物 —— `--list` 只列不跑，用来看"有哪些断言"。

    python3 kit/scripts/check_doc_reality.py          # 跑一遍，出状态表
    python3 kit/scripts/check_doc_reality.py --list   # 只列登记表
退出码：0 = 全部通过；1 = 有失败 / 有登记项不存在。
"""
import argparse
import glob
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

#: (标签, 命令, 它守的"文档 ↔ 代码"是哪一对)
#: 登记标记：每个"文档 ↔ 代码"断言工具都必须带这一行。
#:
#: 为什么不能只靠本文件这张表：表是**手工维护**的，而"明天新增第 7 个断言时
#: 会不会记得登记"恰恰是 R40 那类漂移的温床（门禁表漂了 8 道没人发现）。
#: 所以判据是**双向**的：工具带标记但没登记 ⇒ 清单漏了它；登记了但工具没标记 ⇒ 表在描述不存在的东西。
MARKER = re.compile(r'^#\s*DOC-REALITY:\s*(.+)$', re.M)

REGISTRY = [
    ('功能表一致', ['python3', 'module/scripts/check_feature_parity.py'],
     '`FeatureRegistry.kt` ↔ `module/README.md` 功能表 ↔ `ACTIVITY.md`/`VERIFICATION.md`'),
    ('钩点共享登记', ['python3', 'kit/scripts/check_hook_sharing.py', '--strict'],
     '多个功能钩同一方法 ↔ `PARADIGM.md` §10 的共享表'),
    ('门禁表一致', ['python3', 'kit/scripts/check_gate_table.py'],
     '`verify.sh` 的 `run_gate` ↔ `PARADIGM.md` §5 的门禁表'),
    ('生成文档新鲜度', ['python3', 'kit/scripts/check_generated_fresh.py'],
     '自动生成的文档 ↔ 它的生成器能否复现'),
    ('文档数字一致', ['python3', 'kit/scripts/docs_claims.py'],
     '`SYSTEM_OVERVIEW.md` 等文档里的数字 ↔ 代码算出的值'),
    ('解析规则往返', ['python3', 'kit/scripts/check_schema_roundtrip.py', '--strict'],
     '模块侧写入的前缀 ↔ `capture_schema.py` 的规则'),
    ('抓取行全部认领', ['python3', 'kit/scripts/check_capture_claimed.py'],
     '真实抓取里每一行 ↔ `capture_schema.py`（⑳ 的动态一半；无近期抓取时退出码 2）'),
    ('写入前缀有规则', ['python3', 'kit/scripts/check_writer_prefixes.py'],
     '模块写抓取的前缀 ↔ `capture_schema.py` 的规则（含还没被触发过的新前缀）'),
    ('流程文档可执行', ['python3', 'kit/scripts/check_procedure.py'],
     '`PARADIGM.md`「新增功能的标准动作」提到的路径/命令/域目录 ↔ 仓库实际结构'),
]


def marked_tools():
    """仓库里所有带 `# DOC-REALITY:` 标记的工具 → {relpath: 它守的是什么}。"""
    out = {}
    for path in (glob.glob(os.path.join(ROOT, 'kit', 'scripts', '*.py'))
                 + glob.glob(os.path.join(ROOT, 'module', 'scripts', '*.py'))):
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
        m = MARKER.search(text)
        if m:
            out[os.path.relpath(path, ROOT)] = m.group(1).strip()
    return out


def registered_paths():
    out = set()
    for _label, cmd, _what in REGISTRY:
        py = next((c for c in cmd if c.endswith('.py')), None)
        if py:
            out.add(py if os.path.isabs(py) else os.path.normpath(py))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true', help='只列登记表，不跑')
    ap.add_argument('--out', default=None, help='把状态表写成 markdown（含复现命令）')
    a = ap.parse_args(argv[1:])

    # ── 自检：登记表 ↔ 仓库里带标记的工具 ──────────────────────────────
    # 这一条先跑：清单本身漏了东西，后面全过也没有意义。
    marks = marked_tools()
    regs = registered_paths()
    unregistered = sorted(set(marks) - regs)
    not_marked = sorted(regs - set(marks))
    if unregistered or not_marked:
        print('[doc-reality] **登记表与仓库里的标记不一致**：')
        for p in unregistered:
            print(f'   带标记但没登记：{p} —— {marks[p]}')
            print(f'      ⇒ 把它加进 check_doc_reality.py 的 REGISTRY（第 7 个断言就是这么漏掉的）')
        for p in not_marked:
            print(f'   登记了但工具没标记：{p} —— 给它加一行 `# DOC-REALITY: <守什么>`')
        return 1

    if a.list:
        print(f'[doc-reality] 登记了 {len(REGISTRY)} 条"文档 ↔ 代码"断言'
              f'（仓库里带标记的工具 {len(marks)} 个，一致 ✓）：')
        for label, cmd, what in REGISTRY:
            print(f'  {label:14s} {what}')
            print(f'  {"":14s} └─ {" ".join(cmd)}')
        return 0

    bad = []
    rows = {}

    # ⑧ 复用门禁 ④ 本轮写出的报告（若存在）—— 否则它要自己再扫一遍 smali（~13s）。
    # 与 `verify.sh` 里 ④→⑧ 的复用是同一个文件、同一种理由：**同一轮内**的复用，
    # 不涉及跨轮缓存过期。报告不在时自动退回自行扫描，结论不变。
    _tj = os.path.join(ROOT, 'work', '.hook_targets.json')
    registry = [
        (label, cmd + (['--targets-json', _tj] if os.path.isfile(_tj)
                       and 'check_hook_sharing.py' in ' '.join(cmd) else []), what)
        for label, cmd, what in REGISTRY
    ]

    # **并行跑**（2026-11-02）：9 个工具互不依赖，串行约 20s、并行约 3s。
    # 每个都是独立子进程、各自读各自的文件，没有共享可变状态。
    # 这与"门禁之间不要共享缓存"不冲突：那是**跨轮**的缓存（会过期），
    # 这是**同一轮内**的并发（没有过期问题）。
    # 输出仍按 REGISTRY 的顺序打印，便于人眼比对与 diff。
    jobs = []          # [(label, cmd, path|None)]
    for label, cmd, what in registry:
        # 从命令里找**第一个** `.py` 参数当脚本路径 —— 不猜位置，
        # 否则 `python3 kit/x.py --flag` 与 `python3 -m unittest …` 会取错。
        py = next((c for c in cmd if c.endswith('.py')), None)
        if py is None:
            bad.append((label, '登记的命令里没有 .py 脚本，无法核对存在性'))
            rows[label] = '**命令不可判定**'
            jobs.append((label, cmd, None))
            continue
        path = py if os.path.isabs(py) else os.path.join(ROOT, py)
        if not os.path.isfile(path):
            bad.append((label, f'登记的工具不存在：{py}'))
            rows[label] = '**工具缺失**'
        jobs.append((label, cmd, path))

    def run_one(job):
        _label, cmd, path = job
        if path is None or not os.path.isfile(path):
            return None
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
        tail = [x for x in (p.stdout or '').strip().splitlines() if x.strip()]
        return p.returncode, (tail[-1][:90] if tail else '')

    with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
        results = list(ex.map(run_one, jobs))

    print(f'{"断言":16s} {"结果":6s} 说明')
    for (label, cmd, path), res in zip(jobs, results):
        if res is None:
            print(f'{label:16s} {"缺失":6s} {path or "命令里没有 .py"}')
            continue
        rc, detail = res
        ok = rc == 0
        rows[label] = '通过' if ok else '**失败**'
        print(f'{label:16s} {"ok" if ok else "FAIL":6s} {detail}')
        if not ok:
            bad.append((label, detail))

    if a.out:
        os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('# 文档 ↔ 代码：断言清单与当前状态（自动生成）\n\n')
            f.write('* 复现：`python3 kit/scripts/check_doc_reality.py '
                    f'--out {os.path.relpath(a.out, ROOT)}`\n')
            f.write('* 为什么有这份清单：R40 实测门禁表停在 ⑨ 而实际跑 19 条，'
                    '**漂了 8 道没人发现** —— 不是因为没人写断言，'
                    '而是因为"哪个断言该存在"本身没被审视。\n\n')
            f.write('| 断言 | 守的是什么 | 命令 | 现在 |\n|---|---|---|---|\n')
            for label, cmd, what in REGISTRY:
                f.write(f'| {label} | {what} | `{" ".join(cmd)}` | {rows.get(label, "?")} |\n')
            f.write('\n')
            if bad:
                f.write(f'> **{len(bad)} 条失败**：' + ', '.join(l for l, _ in bad) + '\n')
            else:
                f.write(f'> {len(REGISTRY)} 条全部通过。\n')

    if bad:
        print(f'\n[doc-reality] **{len(bad)} 条断言失败**：'
              + ', '.join(l for l, _ in bad))
        return 1
    print(f'\n[doc-reality] {len(REGISTRY)} 条断言全部通过 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
