#!/usr/bin/env python3
"""

# DOC-REALITY: 真实抓取里的每一行 ↔ capture_schema.py 的规则（⑳ 的动态一半）
kuaidui-kit / check_capture_claimed.py — 真实抓取里的每一行，解析侧都必须认领。

### 它在契约里的位置

"模块写下的前缀" ↔ "解析侧的规则"这条契约有两半：

| 半 | 工具 | 能发现什么 |
|---|---|---|
| 静态 | `check_writer_prefixes.py`（门禁 ⑳） | **还没被触发过**的新前缀没有规则 |
| **动态** | **本脚本** | 已写出去的行**实际上**解析成什么 |

R12 那次是动态那半发现的（7 行落 UNKNOWN），而当时静态那半不存在。
R28 把动态那半放进了真机验收 —— 于是**没有设备就跑不到**，
而这条契约恰恰最该在每次改 `capture_schema.py` 时被验证。

### 判据

| 退出码 | 含义 |
|---|---|
| **0** | 抓取里每一行都被认领（`parse_line` 返回非 UNKNOWN） |
| **1** | 有未认领的行 ⇒ 模块改了写入格式而规则没跟上 |
| **2** | **无法验证**：没有抓取文件 / 最近一份超过 7 天 |

退出码 2 交给门禁的 `--accept " 0 2 "`，并在结果行上写明"无法验证" ——
既不冒充通过，也不在没有数据时永远红。

    python3 kit/scripts/check_capture_claimed.py
    python3 kit/scripts/check_capture_claimed.py --capture x.txt
"""
import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import captures
import capture_schema as cs  # noqa: E402

MAX_AGE_DAYS = 7


#: 抓取步骤失败时，错误信息会被写进 `capture.txt` —— 2026-11-02 实测：
#: 一次给错 serial 的证据包产出 `adb: device 'emulator-9999' not found` 一行，
#: 而它成了"最新的抓取"，于是本检查报"未认领 1 行：adb: device …" ——
#: **一个失败步骤伪装成证据**，还附带着一条假的"schema 漂移"结论。
NOT_A_CAPTURE = re.compile(r"adb: (device|error)|error: (device|no devices)|"
                           r"cannot connect to|device offline|more than one device")


def looks_like_capture(path):
    """这个文件是真的抓取，还是某次失败步骤的残留。"""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            head = [next(f, '').strip() for _ in range(3)]
    except OSError:
        return False
    joined = ' '.join(head)
    if NOT_A_CAPTURE.search(joined):
        return False
    # 真实抓取至少几十行；只有一两行且含错误字样的一律不当证据
    return True


def newest_capture():
    """最近的抓取：优先 `work/live_capture.txt`（真机验收每轮刷新），否则最近的包。"""
    stable = os.path.join(ROOT, 'work', 'live_capture.txt')
    cands = []
    if os.path.isfile(stable) and looks_like_capture(stable):
        cands.append(stable)
    # **两种形态都认**（2026-11-03 修）：原来只 glob `capture.txt`，
    # 于是 `pack_slim` 压过的包一概看不见 —— 门禁 ㉑ 名义上查"最近的抓取"，
    # 实际上只查"最近的**未压缩**抓取"。
    # （`.gz` 的整份解析由门禁 ㉡ 覆盖；这里要的是"最近的那一份"不缺形态。）
    for p in captures.iter_captures():
        if looks_like_capture(p):
            cands.append(p)
    return cands[0] if cands else None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', default=None)
    a = ap.parse_args(argv[1:])

    path = a.capture or newest_capture()
    if not path or not os.path.isfile(path):
        print('[claimed] **无法验证**：仓库里没有抓取文件'
              '（`work/live_capture.txt` 或 `work/packs/*/capture.txt`）')
        return 2

    import datetime
    age = (datetime.datetime.now() - datetime.datetime.fromtimestamp(
        os.path.getmtime(path))).days
    rel = os.path.relpath(path, ROOT)
    if not a.capture and age > MAX_AGE_DAYS:
        print(f'[claimed] **无法验证**：最近的抓取 `{rel}` 已经 {age} 天前'
              f'（阈值 {MAX_AGE_DAYS} 天）—— 它证明的是那时的规则，不是现在')
        return 2

    unk, tot = [], 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            tot += 1
            r = cs.parse_line(line)
            if r is None or r.kind == 'UNKNOWN':
                unk.append(line)

    print(f'[claimed] {rel}（{age} 天前）：{tot} 行，未认领 {len(unk)} 行')
    if unk:
        # 取**前缀**而不是"第二个词"：异常行可能没有时间戳。
        def pfx(line):
            for tok in line.split():
                if re.fullmatch(r'[A-Z][A-Z0-9_]{2,}', tok):
                    return tok
            return line[:16]
        heads = sorted({pfx(l) for l in unk})[:8]
        print(f'[claimed] **未认领的前缀**：{", ".join(heads)}')
        print('[claimed]   修法：模块改了写入格式而 `capture_schema.py` 没跟上'
              '（PARADIGM.md「新增功能的标准动作」第 7 步）。')
        for l in unk[:5]:
            print(f'[claimed]     {l[:110]}')
        return 1
    print('[claimed] 每一行都有归属 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
