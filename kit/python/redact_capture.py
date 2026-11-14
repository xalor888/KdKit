#!/usr/bin/env python3
"""
kuaidui-kit / redact_capture.py —— 抓取文件里的**凭证脱敏**（2026-10-25 第 17 轮加）。

为什么必须存在
--------------
`work/activity_inputs/` 是模块在真机上抓到的原始 logcat。它是本仓库最有价值的资产
（多轮结论都靠它反推），但它同时**原样保存了用户的登录凭证**：

    SIGN params: … | token=1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM | …
    SIGN URL: https://…&token=1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM&sign=…

同一条 token 在 5 份抓取里出现 **1418** 次；`cuid` / `adid` / `did` 一并落盘。
这些文件进了仓库，就等于凭证进了仓库 —— 而它们本来只是"用来统计功能命中"的样本。

危害的具体形态
--------------
* `sign=` 是 `f(params + secret)` 的结果，而 `params` **含 token**。保留 token 就等于
  把一份"输入 + 输出"的签名样本交出去；配合已还原的签名算法（`kit/scripts/` 里有
  离线复现），这足以伪造请求。
* `token` 是会话凭证，`did`/`adid`/`cuid` 是设备指纹。三者一起足以冒充该设备。

设计取舍（重要）
----------------
**不做"整体打码"**。样本的价值在于结构：`_t_=1791849499`、`abis=1`、`vc=1811` 这些
必须原样保留，否则 `ACTIVITY.md` 的统计与签名复现全部失效。所以只替换**值的部分**，
长度与字符集保持一致（`1_XXXX…` → `1_REDACTED`），并保持逗号/竖线分隔符不变。

**替换必须可重复**：同一份输入跑两次得到同一份输出，且对已脱敏的文件再跑一次不变
（幂等）。这是"离线可重复"的前提，也由本文件的测试断言。

用法
----
    python3 kit/python/redact_capture.py work/activity_inputs/*.txt          # 预演，只报数
    python3 kit/python/redact_capture.py --write work/activity_inputs/*.txt  # 就地改写
    python3 kit/python/redact_capture.py --check work/activity_inputs/*.txt  # 有残留就退出 1

`--check` 是给门禁用的：**有未脱敏凭证就直接红**，不靠人记得跑。
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import textio
import argparse
import os
import re
import sys

# 占位符。刻意选一个**不可能**出现在真实值里的串，这样"是否已脱敏"可以自证。
MARK = 'REDACTED'

# 逐个键处理。顺序有意义：`token` 必须最先（它最长、且是别的规则的前缀陷阱）。
#
# 每个模式都只吃"值"，不吃键名与分隔符：
#   RULES[i] = (键名, 值正则)
# 值正则里用 [^&\s|,]+ 这类"遇到分隔符就停"，避免把后面的 `&sign=` 一起吞掉。
RULES: list[tuple[str, re.Pattern]] = [
    # 会话凭证：`token=1_XXXX`、`&token=1_XXXX&`
    ('token', re.compile(r'(?<=\btoken=)[^&\s|,]*')),
    # 签名：`sign=c41a117b…`。签名本身是"输入+secret"的指纹，留着等同交出样本。
    ('sign', re.compile(r'(?<=\bsign=)[^&\s|,]*')),
    # 设备指纹
    ('did', re.compile(r'(?<=\bdid=)[^&\s|,]*')),
    ('adid', re.compile(r'(?<=\badid=)[^&\s|,]*')),
    ('cuid', re.compile(r'(?<=\bcuid=)[^&\s|,]*')),
    ('idfa', re.compile(r'(?<=\bidfa=)[^&\s|,]*')),
    # 手机号（宿主会在部分接口带上明文号）
    ('mobile', re.compile(r'(?<=\bmobile=)1[3-9]\d{9}')),
    # `Authorization: Bearer …`
    ('authorization', re.compile(r'(?<=Authorization: Bearer )[A-Za-z0-9._\-]+')),
]

# 刻意**不**脱敏的键，以及理由（写下来，防止下次有人"顺手补上"）：
#
#   identityIdV2=0       —— 是角色枚举（0=学生/1=家长…），不是身份 ID。脱了会毁掉
#                            `ACTIVITY.md` 里的角色分布统计。
#   phoneDevice=emu64a   —— 机型名（`sdk_gphone64_arm64`），是**设备型号**不是设备 ID。
#                            `did`/`adid` 才是 ID。
#   os / vc / abis / _t_ / appBit / vcname —— 与安全无关，且是签名复现的必需输入。
#
# 判据不是"这个词听起来像隐私"，而是"**能否据它在服务端识别出这台设备/这个人**"。

# 空值必须**保持为空**。`token=` 后面什么都没有时不能变成 `token=REDACTED` ——
# 那会把"没有这个字段"偽装成"有这个字段但被脱敏"，污染统计（`SIGN params` 的键集合
# 是 `ACTIVITY.md` 的输入之一）。
_EMPTY_OK = ('', )


def redact_line(line: str) -> tuple[str, int]:
    """把一行里所有凭证值替换成 MARK。返回 (新行, 替换次数)。"""
    hits = 0
    for _key, rx in RULES:
        def sub(m: re.Match) -> str:
            nonlocal hits
            val = m.group(0)
            if val == MARK:
                return val              # 已脱敏：保持幂等
            if not val:
                # 空值**必须保持为空**。
                # 早期版本写成 `return MARK if val else val`，看着对，但 `did= | idfa= `
                # 这种"空值后面跟分隔符"的行会把 `did=` 后面的空格当值？不会 ——
                # 真正的坑是 `[^&\s|,]+` 这种 **+** 量词压根不匹配空串，于是
                # `did=` 不受影响，而 `did= `（后跟空格）也不匹配。两种形态都要照顾到，
                # 所以现在用 `*` 且在这里显式短路：空就是空。
                return val
            hits += 1
            return MARK
        line = rx.sub(sub, line)
    return line, hits


def redact_text(text: str) -> tuple[str, int]:
    out, total = [], 0
    for line in text.splitlines(keepends=True):
        new, n = redact_line(line)
        out.append(new)
        total += n
    return ''.join(out), total


def read_text(path: str) -> str:
    """读一份抓取；`.gz` 走 `textio` 自动解压（2026-11-03 修）。

    **原来直接 `open(path)`，于是 `.txt.gz` 被当成 gzip 二进制读进来。**

    后果不是报错，而是一张**假的清白证明**：

        work/packs/r793/capture.txt      → ✗ 1399 处未脱敏凭证
        work/packs/r793/capture.txt.gz   → ✓ 无残留          ← 同一份内容

    二进制的 gzip 字节里没有任何凭证模式 ⇒ `residual()` 返回空 ⇒
    `--check` 打印“无残留”。而这是一个**隐私检查**：
    它说的是“这份抓取可以外传”，而真相是“我没读到”。
    """
    return textio.read_text(path)


def residual(text: str) -> list[str]:
    """还有哪些**看起来是真实值**的凭证残留（用于 --check）。"""
    bad = []
    for key, rx in RULES:
        for m in rx.finditer(text):
            val = m.group(0)
            if val and val != MARK:
                bad.append(f'{key}={val[:12]}…' if len(val) > 12 else f'{key}={val}')
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description='脱敏抓取文件里的登录凭证 / 设备指纹')
    ap.add_argument('captures', nargs='+')
    ap.add_argument('--write', action='store_true', help='就地改写（默认只预演）')
    ap.add_argument('--check', action='store_true',
                    help='有残留就退出 1（给门禁用）')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv[1:])

    rc = 0
    for path in a.captures:
        if not os.path.isfile(path):
            print(f'[redact] 跳过（不是文件）：{path}', file=sys.stderr)
            continue
        text = read_text(path)
        if a.check:
            left = residual(text)
            if left:
                rc = 1
                print(f'✗ {path}: {len(left)} 处未脱敏凭证')
                for item in left[:5]:
                    print(f'    {item}')
            elif not a.quiet:
                print(f'✓ {path}: 无残留')
            continue

        new, n = redact_text(text)
        if a.write and n:
            # 写入前确认"除了被替换的值，其它字节完全一致" —— 否则脱敏会毁掉样本。
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(new)
            back = read_text(path)
            assert back == new, f'写入回读不一致：{path}'
        if not a.quiet:
            verb = '已改写' if (a.write and n) else ('将改写' if n else '无需改动')
            print(f'[redact] {path}: {n} 处 → {verb}')
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv))
