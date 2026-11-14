#!/usr/bin/env python3
"""

# DOC-REALITY: 模块侧写入前缀 ↔ capture_schema.py 规则
# （这一行是给 `check_doc_reality.py` 扫的登记标记 —— 新增"文档 ↔ 代码"断言时
#  必须加这一行，否则清单会漏掉它，R40 门禁表漂 8 道那类事就会重演。）
kuaidui-kit / check_schema_roundtrip.py — 每条解析规则是否都真的被触发过？

## 为什么要这个检查

`capture_schema.py` 声明了 38 条规则，模块侧写抓取行。两边必须对得上：

* **规则有、没人写** ⇒ 规则是死的（可能前缀改了没人更新，或功能删了规则留着）；
* **有人写、没规则** ⇒ 那行会落到 `UNKNOWN`，在报告里变成"没有规则认领的残留"，
  而读报告的人分不清"这是新前缀"还是"这是解析器漏了"。

## 它检查什么

把样本抓取喂给解析器，统计**每条规则的 kind 是否至少命中过一次**。

关键点：**kind 名 ≠ 行前缀**。例如 `AD_BLOCK` 这个 kind 对应的行是
`blocked ad slot read: …` —— 按"前缀"去比对会得到一堆假缺口（本轮就这样误判过 15 条）。

## 用法

```bash
python3 kit/scripts/check_schema_roundtrip.py           # 人读
python3 kit/scripts/check_schema_roundtrip.py --strict  # 有从未命中的 kind 就 exit 1
```
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import textio

import capture_schema as cs  # noqa: E402

#: 没有任何需要排除的"内部 kind"。
#:
#: 曾经以为 `MARK`（会话头 `=== KdKit host=…`）是解析器自产的、不在规则表里，
#: 实测**它在**（`RULES` 共 53 条，含 `MARK`）。这个错误假设会让"规则覆盖率"
#: 少算一条、还会在反向检查里把它误报成"解析器产出了表外 kind"。
INTERNAL: set = set()

#: **已定义但样本尚未产生**的规则（附理由与移除条件）。
#:
#: 判据"每条规则都要被真实样本命中"是对的 —— 死规则意味着写入侧或规则已经漂移。
#: 但有一类规则是"为将来才会出现的证据准备的"：`ADBLOCK` 是 2026-11-02 新加的
#: 拦截证据，而**游客态下 `di.a.j/k`（"有没有广告配置"）根本不会被调用**，
#: 所以它现在不可能有真实样本。
#:
#: 处理方式与 `check_writer_prefixes.ALLOWED` 相同：**显式列出 + 写过期告警**。
#: 理由不成立时（登录态抓到过 ADBLOCK），这里必须删掉 —— 否则它就是一辈子的豁免。
#: 当前为空。`ADBLOCK` 曾在里面（2026-11-02：游客态下 `di.a.j/k` 不被调用，
#: 规则刚加时没有样本）—— 补了 fixture 行之后**过期告警立刻把它报了出来**，
#: 于是删掉。这正是这套机制该有的行为：豁免不许变成一辈子。
NOT_YET: dict = {}


def sample_files():
    pats = [
        os.path.join(ROOT, 'work', 'activity_inputs', '*.txt'),
        os.path.join(ROOT, 'kit', 'python', 'tests', 'fixtures', '*.txt'),
    ]
    out = []
    for p in pats:
        out.extend(sorted(glob.glob(p)))
    return out


def main(argv):
    ap = argparse.ArgumentParser(description='每条解析规则是否都被触发过')
    ap.add_argument('--strict', action='store_true',
                    help='有从未命中的 kind 就 exit 1')
    a = ap.parse_args(argv[1:])

    files = sample_files()
    if not files:
        print('[roundtrip] 没有样本抓取 —— 跳过')
        return 0

    seen: dict[str, int] = {}
    for f in files:
        for r in cs.iter_records(f):
            seen[r.kind] = seen.get(r.kind, 0) + 1

    # `NOT_YET` 只豁免**"规则没有样本"这一个方向**。
    #:
    #: 第一版把它从 `allk` 里整体减掉，于是反向检查（"解析器产出了表外 kind"）
    #: 把 fixture 里真实的 `ADBLOCK` 行也当成表外产物 ⇒ 门禁红在自己身上。
    #: 两个方向必须分开：样本缺失可以豁免，**产出表外 kind 永远不行**。
    table_kinds = {k for k, *_ in cs.RULES} - INTERNAL
    never = sorted(table_kinds - set(NOT_YET) - set(seen))
    unknown = seen.get('UNKNOWN', 0)

    # **`RULES` 的条数 ≠ kind 的个数**：多个变体可以共用一个 kind
    # （`BRIDGE` 有 4 条正则、`REQBODY` 有 4 条…）。两个数字都报，
    # 否则读者会以为"规则 39 条"和别处说的"54 条"中有一个是错的。
    print(f'[roundtrip] 样本 {len(files)} 份；`RULES` {len(cs.RULES)} 条正则 / '
          f'{len(table_kinds)} 个唯一 kind')
    print(f'[roundtrip] 命中过的 kind {len(table_kinds & set(seen))} 个')

    # 反向：出现了但 schema 不认识的 kind（UNKNOWN 之外）——不该发生
    extra = sorted(set(seen) - table_kinds - {'UNKNOWN'} - INTERNAL)
    if extra:
        print(f'[roundtrip] **解析器产出了规则表里没有的 kind**：{extra}')

    if never:
        print(f'[roundtrip] **从未命中过的规则（{len(never)}）**：')
        for k in never:
            # 打印该规则的正则，方便判断"是前缀改了还是功能删了"
            pat = next((p.pattern for kk, _f, _v, p, _b in cs.RULES if kk == k), '?')
            print(f'    {k:14s} {pat[:70]}')
        print('  要么补一条样本，要么删掉这条规则 —— 死规则会让"规则数"这个数字虚高。')
    else:
        print('[roundtrip] 全部规则都被真实样本触发过')

    if unknown:
        # 区分"新前缀没人认领"与"已知的残缺形态" —— 前者要补规则，后者不用。
        reasons: dict[str, int] = {}
        for f in files:
            for r in cs.iter_records(f):
                if r.kind == 'UNKNOWN':
                    reasons[r.get('reason') or '?'] = reasons.get(r.get('reason') or '?', 0) + 1
        # `legacy-wrap` = 旧抓取里被换行撑开的残留；`truncated` = 被截断的行；
        # `unknown` = **确实没有规则认领的一行**。
        # 前两个是"已知的残缺形态"，第三个要分情况：fixture 里故意放了一行
        # `this line has no known prefix at all` 作为负样本（证明解析器不会瞎认领），
        # 真实抓取里出现才是要补规则。所以 `unknown` 不当成"已知"，但也不直接判红 ——
        # 打印出来让人看是哪个文件。
        known_reasons = {'legacy-wrap', 'truncated'}
        newish = {k: v for k, v in reasons.items() if k not in known_reasons}
        print(f'[roundtrip] 样本里 {unknown} 行落在 UNKNOWN，原因：{reasons}')
        if newish:
            print(f'[roundtrip] 其中 {newish} 需人工看：')
            print('    - 若来自 `tests/fixtures/`（负样本，故意不认领）⇒ 正常；')
            print('    - 若来自 `work/activity_inputs/`（真实抓取）⇒ 可能是新前缀，要补规则。')
            for f in files:
                for r in cs.iter_records(f):
                    if r.kind == 'UNKNOWN' and (r.get('reason') or '') in newish:
                        where = 'fixture（负样本）' if 'fixtures' in f else '**真实抓取**'
                        print(f'    {os.path.basename(f)} [{where}] ts={r.ts}')

    # **逐条正则**检查（比 kind 层更细）。
    #
    # 为什么需要这一层：`RULES` 有 54 条正则但只有 39 个 kind，`BRIDGE` 一个 kind
    # 就有 4 条正则（不同变体）。只查 kind 的话，**某个变体的正则写坏/格式漂移
    # 完全看不出来** —— 同 kind 的其他变体命中，绿着。
    #
    # 当前实测：54 条里 53 条被样本命中，1 条（`REQBODY json len=…`）从未出现 ——
    # 那是"真实抓取里没有 JSON 请求体样本"，不是规则写错。所以**只报告、不判红**。
    dead_res = []
    body_lines = []
    for f in files:
        for ln in textio.read_lines(f, encoding='utf-8', errors='replace'):
            m = cs.TS_RE.match(ln.strip())
            if m:
                body_lines.append(m.group(2))
    for idx, (kind, _feat, variant, pat, _fn) in enumerate(cs.RULES):
        hit = sum(1 for bl in body_lines if pat.match(bl))
        if hit == 0:
            dead_res.append((idx, kind, variant, pat.pattern))

    # 豁免条目是否已过期：样本里出现了 ⇒ 理由不成立，必须删掉豁免
    stale = sorted(k for k in NOT_YET if k in seen)
    if stale:
        print(f'[roundtrip] **NOT_YET 豁免已过期**（这些规则已有真实样本，把豁免删掉）：{stale}')
        return 1
    if dead_res:
        print(f'[roundtrip] **{len(dead_res)} 条正则从未被样本命中**（kind 层可能仍是绿的）：')
        for idx, kind, variant, pat in dead_res:
            print(f'    [{idx}] {kind}{"/" + str(variant) if variant else ""}  {pat[:64]}')
        print('  「从未命中」有两种含义，要分开看：')
        print('    a) 真实抓取里缺这类输入 ⇒ 补样本或接受；')
        print('    b) 正则格式与模块写出的格式不符 ⇒ **真 bug**，该行会落 UNKNOWN。')
    else:
        print('[roundtrip] 每一条正则都被样本命中过')

    bad = bool(never or extra)
    return 1 if (a.strict and bad) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
