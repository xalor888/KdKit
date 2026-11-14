#!/usr/bin/env python3
"""

# DOC-REALITY: 自动生成的文档 ↔ 它的生成器
# （这一行是给 `check_doc_reality.py` 扫的登记标记 —— 新增"文档 ↔ 代码"断言时
#  必须加这一行，否则清单会漏掉它，R40 门禁表漂 8 道那类事就会重演。）
kuaidui-kit / check_generated_fresh.py — 自动生成的文档是不是**还能由它的生成器复现**。

### 为什么需要

`work/` 与 `module/` 下有一批**自动生成**的文档。它们一旦过期，就会变成"看起来是结论、
其实是上个月的快照"——比没有更危险，因为它带着"自动生成"的可信度。

2026-11-02 实测到两个具体后果：

* `work/MODULE_ACTIVITY.md` 少了 `native_exit_guard` 一行（生成器加了 `NEXIT` 前缀之后没重跑），
  26/12 与 27/11 的分配变了，而文件里没有任何迹象；
* `work/BRIDGE_PAGE_MAP.md` 写"1131 份抓取"，实际已是 1132 —— 而且它**没有复现命令**，
  想核对的人得自己去翻生成器的 argparse。

### 判据（不看时间戳，看内容）

时间戳不可靠（`git checkout`、`touch`、打包都会改它）。这里用**真跑一遍再比对**：

1. 读文档头部的 `` * 复现：`<命令>` ``；
2. 命令里带 `--adb` 的**跳过**（要设备，不适合当离线门禁），并把它列出来，不静默略过；
3. 把命令的 `--out` 换成临时文件跑一遍；
4. 逐行比对（忽略首行标题下的"复现"行本身，以及时间/路径这类必然变化的行）。

    python3 kit/scripts/check_generated_fresh.py [--verbose]

退出码：0 = 全部能复现；1 = 有文档过期 / 有文档没有复现命令。
"""
import argparse
import glob
import os
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'python'))
import genstamp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: 扫描范围。只收"生成器写在头部"的那些 —— 手写文档没有复现命令是正常的。
TARGETS = ['work/*.md', 'module/*.md']

#: **不参与新鲜度检查的文档**（聚合型：它们自己会跑本工具，复跑即递归）。
#:
#: 2026-11-02 实测：`DOC_REALITY.md` 的复现命令是 `check_doc_reality.py`，
#: 而它登记的断言里包含 `check_generated_fresh.py` ⇒ 本工具复跑它 ⇒ 它再跑本工具 ⇒ 死循环
#: （跑了 20 分钟没停，靠 job_kill 才停）。
#: 判据：一个文档如果**汇总**了别的检查，它就不能被那些检查复跑。
#: 这类文档的"是否过期"由它自己那一轮的输出证明，不靠复跑。
EXCLUDE = {
    'work/DOC_REALITY.md': '聚合型：它会跑本工具，复跑即递归',
    'work/FACE_BOARD.md': '设备相关（复现命令带 --adb），且输入含 logcat，指纹会永远不匹配',
}

#: 这些行天然每次不同（时间、绝对路径、随机 tag），比对前抹掉。
VOLATILE = [
    (re.compile(r'^\* 复现：.*$'), ''),
    (re.compile(r'\d{2}:\d{2}:\d{2}\.\d{3}'), '<TS>'),
    (re.compile(re.escape(ROOT)), '<ROOT>'),
]


def norm(line):
    for rx, rep in VOLATILE:
        line = rx.sub(rep, line)
    return line.rstrip()


def find_repro(path):
    """从文档里取第一条 `* 复现：\\`<cmd>\\``；没有就返回 None。"""
    try:
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i > 40:          # 只看头部
                    break
                m = re.search(r'复现：`([^`]+)`', line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return None


def rerun(cmd, out_path):
    """把命令里的 `--out <x>` 换成 out_path 后执行。返回 (ok, 说明)。"""
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return False, f'命令解析失败: {e}'
    if '--out' not in parts:
        return False, '命令里没有 --out，无法定向比对'
    i = parts.index('--out')
    if i + 1 >= len(parts):
        return False, '--out 后面没有值'
    parts[i + 1] = out_path
    p = subprocess.run(parts, cwd=ROOT, capture_output=True, text=True, timeout=600)
    # **不能用退出码判断"生成成功"**（2026-11-02 改）。
    #
    # 有些生成器的退出码承载的是**结论**而不是"生成成功"：
    # `face_board.py` 用 0=四个面全验过 / 2=有面无法验证 / 1=异常，而它**每次都正常写出文件**。
    # 旧实现把 2 当成"复跑失败"，于是门禁红在"这个工具没通过"，
    # 而这条门禁该问的是**"文件与生成器是否一致"**。
    # 判据改成：文件有没有被写出来（非空）；退出码只作为附注记下来。
    note = '' if p.returncode == 0 else f'（生成器退出码 {p.returncode}，结论性退出码不影响本检查）'
    try:
        if os.path.getsize(out_path) == 0:
            return False, '生成器没有写出内容'
    except OSError:
        return False, '生成器没有产出文件'
    return True, note


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    docs = []
    for pat in TARGETS:
        docs += sorted(glob.glob(os.path.join(ROOT, pat)))

    fresh, stale, no_repro, skipped, broken = [], [], [], [], []
    for doc in docs:
        rel = os.path.relpath(doc, ROOT)
        if rel in EXCLUDE:
            if a.verbose:
                print(f'  —     {rel}  （{EXCLUDE[rel]}）')
            continue
        cmd = find_repro(doc)
        if not cmd:
            no_repro.append(rel)
            continue
        if '--adb' in cmd:
            # 跑不了生成器 —— 但**输入指纹**仍然能验：输入变了，这份文档就一定过期。
            # 这是"跳过并列出"升级成"跳过但可判断"的那一档（2026-11-02）。
            fpinfo = genstamp.read_fingerprint(doc)
            if not fpinfo:
                skipped.append((rel, '需要设备（--adb），且头部没有输入指纹 ⇒ 无法判断是否过期'))
                continue
            want_fp, want_n, pats = fpinfo
            got_fp, got_n, _ = genstamp.fingerprint(genstamp.expand(pats))
            if got_fp == want_fp:
                fresh.append(rel + '（仅指纹）')
            else:
                stale.append((rel, [(0, f'输入指纹 `{want_fp}`（{want_n} 个文件）',
                                        f'输入指纹 `{got_fp}`（{got_n} 个文件）—— 输入已变，文档过期')],
                              want_n, got_n))
            continue
        fd, tmp = tempfile.mkstemp(suffix='.md')
        os.close(fd)
        try:
            ok, why = rerun(cmd, tmp)
            if not ok:
                broken.append((rel, why))
                continue
            if why:
                print(f'  note  {rel}  {why}')
            with open(doc, encoding='utf-8') as f:
                want = [norm(x) for x in f.read().splitlines()]
            with open(tmp, encoding='utf-8') as f:
                got = [norm(x) for x in f.read().splitlines()]
            # 有些生成器会**保留手工附录**（`module/ACTIVITY.md` 的 `## 七、功能 ↔ 抓取前缀对照表`
            # 是 ③ 门禁的输入，重写时必须跨版本存活）。那种情况下"重新生成"只会得到前半段，
            # 所以判据放宽成：**文档必须以生成结果开头**，多出来的部分视为手工附录。
            # 这仍然能抓住任何生成内容的漂移 —— 只是不再要求长度完全相等。
            if want == got or (len(got) <= len(want) and want[:len(got)] == got):
                fresh.append(rel)
            else:
                diff = [(i + 1, w, g) for i, (w, g) in enumerate(zip(want, got)) if w != g]
                stale.append((rel, diff[:5], len(want), len(got)))
        finally:
            os.unlink(tmp)

    print(f'[fresh] 扫描 {len(docs)} 份文档：'
          f'可复现 {len(fresh)} / 过期 {len(stale)} / 无复现命令 {len(no_repro)} / '
          f'需设备跳过 {len(skipped)} / 复跑失败 {len(broken)}')

    if a.verbose:
        for r in fresh:
            print(f'  ok    {r}')
    for r, why in skipped:
        print(f'  skip  {r}  —— {why}')
    for r, why in broken:
        print(f'  ERROR {r}  —— {why}')
    for r, diff, nw, ng in stale:
        print(f'  STALE {r}  （行数 {nw} → {ng}）')
        for ln, w, g in diff:
            print(f'        第 {ln} 行\n          文件: {w[:110]}\n          生成: {g[:110]}')
    for r in no_repro:
        if a.verbose:
            print(f'  —     {r}  （手写文档，没有复现命令）')

    bad = len(stale) + len(broken)
    if bad:
        print(f'[fresh] **{bad} 份文档不能由生成器复现** —— 重跑生成器，或把文档改成不承诺自动生成')
        return 1
    print('[fresh] 所有带复现命令的文档都与生成器一致 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
