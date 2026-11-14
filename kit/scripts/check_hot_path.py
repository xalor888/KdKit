#!/usr/bin/env python3
"""
kuaidui-kit / check_hot_path.py — 热路径上不该出现的重复计算。

### 它守的两件事

**① 语句位置上的 `Regex(...)` 构造**

正则编译是几十微秒 + 一次分配。出现在钩子回调（每页上百次）里就是白烧。
正确写法是提成 `private val` 编译一次。

    fun isAsset(url: String) =
        Regex("\\.(js|css|...)").containsMatchIn(url)      # X 每次调用都编译

今天实测：这类写法 **0 处**（R45 刚把 `NavFilter` 修掉）。这条门禁的价值在以后。

**② 三个已修的"重复计算"点不许退回去**

| 位置 | 修法 | 轮次 |
|---|---|---|
| `BridgeGuard.blacklist` | `RawListMemo` 按原始字符串记忆 | R9 |
| `PopwinGate.matches` | `RawListMemo` 同上 | R46 |
| `NavFilter.isAsset` | 正则提为 `private val` | R45 |

这三处都是"热路径 + 输入几乎不变"。任何一处被重构回现算，
**症状只是多几个对象分配，没有任何门禁会红、没有任何测试会失败** ——
所以要用一条断言把它们钉住。

    python3 kit/scripts/check_hot_path.py
退出码：0 = 干净；1 = 有命中。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = glob.glob(os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor',
                             'kdkit', '**', '*.kt'), recursive=True)

#: ① 语句位置的 `Regex(` —— 即不是 `val x = Regex(` / `private val X = Regex(`
INLINE_REGEX = re.compile(r'(?<!val )\bRegex\(')

#: ② 三处已修点必须仍然带着它们的记忆/提升
MEMO_SITES = [
    ('BridgeGuard.kt', 'blacklist', 'listMemo'),
    ('PopwinGate.kt', 'matches', 'listMemo'),
    ('NavFilter.kt', 'isAsset', 'ASSET_RX'),
]


def main(argv):
    bad = []

    # ① 语句位置的 Regex(
    for path in SRC:
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                # 注释行跳过：KDoc 里**引用**旧写法来说明"以前是怎么写的"是常态
                # （`NavFilter.kt` 就有这么一段），不跳过会把"把 bug 写进注释"当成"bug 还在"
                # —— 和 R19 的 `test_onboard_retry_shape`、R36 的 `check_shell_pipes` 同一类假阳性。
                if stripped.startswith('*') or stripped.startswith('//'):
                    continue
                code = line.split('//')[0]
                if not INLINE_REGEX.search(code):
                    continue
                # `val x = Regex(` / `private val X = Regex(` 是提升过的，合法。
                # **不能锚 `$`**：正则可能跨行（`KdConfigBridge` 的两处就是），
                # 行尾没有 `)` 会被误判成"语句位置构造"。
                if re.search(r'\bval\s+\w+\s*[:=][^=]*Regex\(', code):
                    continue
                bad.append((f'{rel}:{i}', 'inline-regex',
                            f'语句位置构造正则：{line.strip()[:70]}'))

    # ② 三处记忆点
    by_name = {os.path.basename(p): p for p in SRC}
    for fname, fn, token in MEMO_SITES:
        path = by_name.get(fname)
        if not path:
            bad.append((fname, 'site-missing', f'找不到 {fname}'))
            continue
        with open(path, encoding='utf-8') as f:
            text = f.read()
        if token not in text:
            bad.append((fname, 'memo-regression',
                        f'`{fn}` 附近看不到 `{token}` —— 记忆/提升被重构掉了，'
                        '热路径会退回每次现算'))

    if bad:
        print(f'[hot-path] **{len(bad)} 处**命中：')
        for where, rule, why in bad:
            print(f'  {where}  [{rule}]  {why}')
        return 1
    print('[hot-path] 干净 ✓（无语句位置正则构造；3 处记忆点都在位）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
