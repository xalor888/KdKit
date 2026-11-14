#!/usr/bin/env python3
"""

# DOC-REALITY: verify.sh 的 run_gate ↔ PARADIGM.md §5 门禁表
# （这一行是给 `check_doc_reality.py` 扫的登记标记 —— 新增"文档 ↔ 代码"断言时
#  必须加这一行，否则清单会漏掉它，R40 门禁表漂 8 道那类事就会重演。）
kuaidui-kit / check_gate_table.py — `verify.sh` 跑的门禁 ↔ `PARADIGM.md` 的门禁表，必须一致。

### 为什么需要

`module/PARADIGM.md` §5 写着"一条命令跑全部**十道**"，而表格只列到 ⑨。
而 `verify.sh` 现在跑 **19 条**（⑩–⑰ 全部缺失，⑥b 是 `--deep` 附加）。

这不是"文档旧了"的小事：**门禁表是新人了解"这个仓库靠什么保护自己"的唯一入口**。
表里少 8 道，等于告诉读者"只有 10 道"，而真正在保护仓库的有 19 条 ——
而且今天新加的 ⑭⑮⑯⑰ 全是这几天踩坑换来的，**恰恰最该被写进去**。

### 判据

| 来源 | 怎么取 |
|---|---|
| 代码 | `module/scripts/verify.sh` 里每条 `run_gate "<名字>"` |
| 文档 | `module/PARADIGM.md` §5 表格里 `\\| <编号> \\| <名字> \\|` |

两边必须**互相覆盖**：代码有文档没有 ⇒ 表过期；文档有代码没有 ⇒ 表在描述不存在的东西。

    python3 kit/scripts/check_gate_table.py
退出码：0 = 一致；1 = 有差。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERIFY = os.path.join(ROOT, 'module', 'scripts', 'verify.sh')
DOC = os.path.join(ROOT, 'module', 'PARADIGM.md')

#: `run_gate "① 单元测试" …`
RUN_GATE = re.compile(r'run_gate\s+"([^"]+)"')
#: `| ① | 单元测试 | … |`
#:
#: **字符类覆盖整段区域，不再手写端点**
#: （`\u2460-\u24ff` Enclosed Alphanumerics 的圈号部分；
#:  `\u3251-\u32bf` Enclosed CJK Letters and Months 的圈号部分）。
#:
#: 这个坑今天踩了**三次**：
#:   ① `[①-①⑳]`            ⇒ 漏掉 ㉑
#:   ② `[①-⑳㉑-㉗]` ⇒ 漏掉 ㉘
#:   ③ `[①-⑳㉑-㉛]` ⇒ 漏掉 ㉜   ← 就是这次
#:
#: 每次都“刚好覆盖到当时的最大值”，所以每加一道门禁就要再改一次。
#: 覆盖整段之后，门禁号再涨也不用改这里。
CIRCLED = '\u2460-\u24ff\u3251-\u32bf'
DOC_ROW = re.compile(r'^\|\s*([' + CIRCLED + r']+[b]?)\s*\|\s*([^|]+?)\s*\|', re.M)


def code_gates():
    with open(VERIFY, encoding='utf-8') as f:
        text = f.read()
    out = {}
    for m in RUN_GATE.finditer(text):
        name = m.group(1).strip()
        mark = name.split()[0] if name.split() else name
        out[mark] = name[len(mark):].strip()
    return out


def doc_gates():
    with open(DOC, encoding='utf-8') as f:
        text = f.read()
    i = text.find('## 5. 门禁')
    if i < 0:
        return {}
    j = text.find('\n## ', i + 1)
    section = text[i:j if j > 0 else len(text)]
    return {m.group(1).strip(): m.group(2).strip() for m in DOC_ROW.finditer(section)}


def main(argv):
    code, doc = code_gates(), doc_gates()
    if not doc:
        print('[gate-table] **在 PARADIGM.md §5 里解析不出门禁表**（章节标题变了？）')
        return 1

    only_code = sorted(set(code) - set(doc))
    only_doc = sorted(set(doc) - set(code))
    renamed = sorted(k for k in set(code) & set(doc) if code[k] != doc[k])

    print(f'[gate-table] verify.sh {len(code)} 条 ↔ PARADIGM.md §5 {len(doc)} 行')
    if only_code:
        print('[gate-table] **代码里有、表里没有**（表过期，读者会以为仓库只有 '
              f'{len(doc)} 道保护）：')
        for k in only_code:
            print(f'   {k}  {code[k]}')
    if only_doc:
        print('[gate-table] **表里有、代码里没有**（表在描述不存在的东西）：')
        for k in only_doc:
            print(f'   {k}  {doc[k]}')
    if renamed:
        print('[gate-table] **名字不一致**：')
        for k in renamed:
            print(f'   {k}  代码: {code[k]}  /  文档: {doc[k]}')

    if only_code or only_doc or renamed:
        print('  修法：把差的那几行补进 `module/PARADIGM.md` §5 的表，'
              '命令列写真实调用。')
        return 1
    print('[gate-table] 一致 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
