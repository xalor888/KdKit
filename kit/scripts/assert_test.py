#!/usr/bin/env python3
"""
kuaidui-kit / assert_test.py —— **断言的回归测试**（2026-10-12）。

由来：R299 发现一条断言因"**排除式条件遇到子串**" ✗ 而**永不触发** ✗
（判"版本一致"用 `'一致' not in text` ✓，而反例是"**不**一致" ✓ 里面含有"一致" ✗）。
⇒ 把"**真实 + 伪造各跑一遍**"固化成脚本 ✓：**改了断言就跑它** ✓。

    python3 kit/scripts/assert_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

import re, os
# 复刻六条断言的判定（与 evidence_pack.py 同逻辑 ✓），真实 + 伪造各跑一遍 ✓
def six(snap, mod, repro, page, sw, ver):
    F = []
    m = re.search(r'结构形态变化[:：]?\s*(\d+)', snap)
    if m and int(m.group(1)) > 0: F.append('结构形态')
    # 2026-11-02：原来是三条 grep `未触发/无增长/早停` 的断言，而生成器早就不写那些词了
    # ⇒ 三条**永远匹配不到**（代码审查 P0-2）。现在按当前格式只保留一条可判定的：
    # "有抓取行的功能为 0" = 模块没注入或抓取为空。
    d = re.search(r'有抓取行的功能 \*{0,2}(\d+) 个', mod)
    if d and int(d.group(1)) == 0: F.append('模块触发面')
    r = re.search(r'\*\*(\d+)/(\d+)\*\*', repro)
    if r and r.group(1) != r.group(2): F.append('复现率')
    if page and '无变化' not in page: F.append('页面结构')
    s = re.search(r'结构变化：新增 (\d+) / 消失 (\d+)', sw)
    if s and (int(s.group(1)) + int(s.group(2))) > 0: F.append('开关结构')
    if ver and ('无新版本' not in ver and '与基线一致' not in ver): F.append('版本')
    return F

real = dict(
    snap=open('work/SERVER_SNAPSHOT.md', encoding='utf-8').read()[:800],
    mod=open('work/MODULE_ACTIVITY.md', encoding='utf-8').read(),
    repro='**36/36**',
    page=open('work/PAGE_INTERNALS.md', encoding='utf-8').read(),
    sw=open('work/SWITCH_DIFF.md', encoding='utf-8').read(),
    ver='设备上的目标应用与基线一致（无新版本）')
print("真实数据 →", six(**real) or '六条全过 ✓')
fakes = [
    ('结构形态', dict(real, snap='结构形态变化：1')),
    ('模块触发面', dict(real, mod='* 有抓取行的功能 **0 个**：模块没注入\n')),
    # 「模块无增长 / 早停」两条随旧格式一起退休：生成器不再产出那两个计数，
    # 留在这里只会让本自测永远报"未命中"。它们的语义（功能装了但没在干活）
    # 已由「模块触发面」这条覆盖。
    ('复现率', dict(real, repro='**35/36**')),
    ('页面结构', dict(real, page='页面方法表：新增 2 个')),
    ('开关结构', dict(real, sw='**结构变化：新增 1 / 消失 0**')),
    ('版本', dict(real, ver='设备上的目标应用与基线不一致（有新版本）')),
]
bad = []
for name, kw in fakes:
    got = six(**kw)
    ok = bool(got)
    print(f"  伪造 {name:10s} → {'✓ 命中 ' + str(got) if ok else '✗ 未命中'}")
    if not ok: bad.append(name)
print()
print("结论:", '全部命中 ✓' if not bad else f'**有 {len(bad)} 条未命中** ✗: {bad}')

# **必须给退出码**：本脚本被 `tool_sanity.sh:107` 当成"断言器自身有没有坏"的门
# （`chk "assert_test all hit" 0 python3 …`），而旧实现只 print 不 exit ⇒ 退出码恒 0，
# 于是"伪造样本一条都没命中"这件事永远不会让任何门变红 —— 一条永远绿的门
# （2026-11-01 代码审查 P0-8）。谁在用这个脚本，谁就需要这个退出码。
sys.exit(0 if not bad else 1)
