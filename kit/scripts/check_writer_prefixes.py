#!/usr/bin/env python3
"""

# DOC-REALITY: 模块写入侧的前缀 ↔ capture_schema.py 的解析规则
kuaidui-kit / check_writer_prefixes.py — 模块写抓取用的每个前缀，解析侧必须有对应规则。

### 为什么需要

R12 踩过一次：模块把 `blocked ad slot read: aj.a.…` 改成 `di.a.…` 并去掉了尾巴，
`capture_schema.py` 的规则没跟上 ⇒ 真实抓取里 7 行落 UNKNOWN。
**当时所有离线门禁都是绿的**，因为夹具是按规则写的 —— 规则和写入侧一起漂，夹具照样过。

R28 补了"真实抓取全认领"（在验收里，要设备）。但那只覆盖**已经写出去的行**：
新加一个前缀、还没被触发过的时候，它不在任何抓取里，那条检查看不见它。

这道门禁补上那一档：**静态地把写入侧的前缀与解析侧的 kind 对上**。
不等设备、不等抓取，写下的那一刻就能发现漏规则。

### 判据

| 来源 | 怎么取 |
|---|---|
| 写入侧 | `Capture.append("PREFIX …")` / `Capture.mark("PREFIX …")` / `Capture.record("PREFIX …")` 的字面前缀 |
| 解析侧 | `capture_schema.RULES` 里每条规则的 kind |

例外要**显式登记**：`ADSLOT` 在解析侧拆成 `ADSLOT_CALL` / `ADSLOT_RET` 两个 kind
（调用与返回是两回事），所以它没有同名 kind —— 这是有意的，写在 `ALLOWED` 里并说明理由。

    python3 kit/scripts/check_writer_prefixes.py
退出码：0 = 每个前缀都有归属；1 = 有前缀没有规则 / 白名单过期。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import capture_schema as cs  # noqa: E402

SRC = glob.glob(os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor',
                             'kdkit', '**', '*.kt'), recursive=True)
# 两种调用形态都要收：
#   ① `Capture.append("ADSLOT …")`                      —— 直接写
#   ② `record("SIGN URL", …)`                          —— `SignObserver` 的私有包装，
#      它内部也是 `Capture.append("$tag: $full")`，前缀来自**调用点的字面量**
#      （第一版只收 ①，于是 9 个 SIGN/NET/RC4KEY 前缀全部漏掉 —— 静态检查看不见它们）。
# `sb.append("VIP…")` 这种 StringBuilder 形态**必须排除**：它不是写抓取文件。
WRITE = re.compile(r'(?<![\w.])(?:Capture\.)?(?:append|mark|record)\(\s*"([A-Z][A-Z0-9_]{2,})')

#: 有意没有同名 kind 的前缀（附理由）。**过期要报**：理由不成立了就该删白名单。
#: 注意：判据不是字符串相等（`SIGN URL:` ↔ `SIGN_URL`、`ADSLOT call` ↔ `ADSLOT_CALL`），
#: 所以这里**不需要**为 `ADSLOT` 设白名单 —— 第一版按相等比，白名单里躺着它；
#: 判据一改，白名单立刻"过期"并报了出来，这正是它该有的行为。
ALLOWED = {}


def main(argv):
    prefixes = set()
    where = {}
    for path in SRC:
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if line.lstrip().startswith(('*', '//')):
                    continue
                for m in WRITE.finditer(line):
                    prefixes.add(m.group(1))
                    where.setdefault(m.group(1), f'{os.path.relpath(path, ROOT)}:{i}')

    kinds = {r[0] for r in cs.RULES}

    def covered(tag):
        """这个写入前缀在解析侧有没有归属。

        **不能比字符串相等**：写入侧是 `SIGN URL:`（带空格），
        kind 名是 `SIGN_URL`（下划线）；`ADSLOT call …` 对应 `ADSLOT_CALL`。
        规则：把 tag 规范成 `大写+下划线`，然后要求某个 kind 等于它、或以 `它_` 开头。
        """
        norm = tag.strip().replace(' ', '_').upper()
        return norm in kinds or any(k.startswith(norm + '_') for k in kinds)

    missing = sorted(p for p in prefixes if not covered(p) and p not in ALLOWED)
    stale = sorted(p for p in ALLOWED if covered(p))

    print(f'[writer-prefixes] 写入侧前缀 {len(prefixes)} 个；解析侧 kind {len(kinds)} 个')

    if stale:
        print('[writer-prefixes] **白名单过期**（这些前缀现在有对应 kind 了，把理由删掉）：')
        for p in stale:
            print(f'   {p}')

    if missing:
        print(f'[writer-prefixes] **{len(missing)} 个前缀没有解析规则**'
              '（真实抓取里这些行会落 UNKNOWN，而夹具看不见）：')
        for p in missing:
            print(f'   {p:14s} {where.get(p, "?")}')
        print('   修法：在 `kit/python/capture_schema.py` 加规则 + fixture 一行 + CASES 一条'
              '（PARADIGM.md「新增功能的标准动作」第 7 步）。')
        return 1

    if stale:
        return 1
    print('[writer-prefixes] 每个写入前缀都有解析规则 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
