#!/usr/bin/env python3
"""
kuaidui-kit / check_device_writes_readback.py — 往设备写文件的脚本，必须把它读回来。

### 为什么需要

2026-11-02 一天里修掉 6 个"报告成功但不验证"的缺陷。其中两个是设备侧写入：

| 脚本 | 原来的样子 |
|---|---|
| `set_config.sh` | `adb push …` + `cp` 之后直接 `echo "profile applied"` |
| `set_flag.sh` | 同上，`echo "已写入"` |

push 失败、`/data/local/tmp` 满、`cp` 没权限 —— **全都一样地报告成功**。
而这两个脚本是"把模块配置成想要的样子"的唯一入口：写失败却报成功，
会让人以为开关已改，然后拿一个错配的配置去做后续所有判断。

这道门禁把那条经验固化成判据：**写了就要读回**。

### 判据

对每个 shell 脚本：

1. 收集所有**写目的地**：`adb push <src> <dst>` 的 `<dst>`，
   以及 `adb shell "… cp -f <src> <dst>"` 的 `<dst>`；
2. 收集所有**读来源**：`adb shell "… cat <path>"` 与裸 `cat <path>`；
3. 若某个写目的地的**文件名**没出现在任何读来源里 ⇒ 报出来。

按**文件名**匹配而不是全路径：`push` 落在 `/data/local/tmp/x.xml`、
`cp` 到发布目录、读回的是发布目录那条 —— 三个路径不同，但同一个文件。
第一版按全路径比，把两个刚修好的脚本也报了出来（假阳性会训练人忽略检查）。

### 退出码

0 = 每个写入都有对应的读回；1 = 有写了不读回的。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SERIAL = r'adb\s+-s\s+"?\$?\{?\w+\}?"?\s+'

#: 写：push 的目的地
RE_PUSH = re.compile(SERIAL + r'push\s+\S+\s+(\S+)')
#: 写：shell 里 cp -f 的目的地（取最后一个参数）
RE_CP = re.compile(SERIAL + r'shell\s+"[^"]*?\bcp\s+-f\s+\S+\s+([^";\s]+)')
#: 读：shell 里 cat 的路径 / 裸 cat
RE_CAT = re.compile(r'(?:' + SERIAL + r'shell\s+"[^"]*?)?\bcat\s+\'?"?([^"\'\s;]+)')


def scans():
    pats = [os.path.join(ROOT, 'kit', 'scripts', '*.sh'),
            os.path.join(ROOT, 'module', 'scripts', '*.sh'),
            os.path.join(ROOT, 'kit', '*.sh')]
    out = []
    for p in pats:
        out.extend(sorted(glob.glob(p)))
    return out


def basename(tok):
    """`'$PUB'` / `"$PUB"` / `/data/local/tmp/x.xml` → 可比较的名字。"""
    t = tok.strip().strip('"').strip("'").rstrip(';')
    if t.startswith('$'):
        return '${' + t[2:-1] + '}' if t.startswith('${') else '$' + t[1:]
    return os.path.basename(t)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true', help='连通过的也打印')
    a = ap.parse_args(argv[1:])

    bad = []
    total_writes = 0
    for path in scans():
        rel = os.path.relpath(path, ROOT)
        text = textio.read_text(path, encoding='utf-8', errors='replace')
        writes = []
        for m in RE_PUSH.finditer(text):
            writes.append((m.group(1), text.count('\n', 0, m.start()) + 1))
        for m in RE_CP.finditer(text):
            writes.append((m.group(1), text.count('\n', 0, m.start()) + 1))
        if not writes:
            continue
        reads = [basename(m.group(1)) for m in RE_CAT.finditer(text)]
        # **中转也算法**：`push → /data/local/tmp/x.xml` 之后 `cp` 到 `$PUB`，
        # 读回的是 `$PUB` —— 内容照样被验过。第一版不认这条链，把两个刚修好的
        # 脚本报成假阳性（假阳性会训练人忽略检查，今天已经为此修过 3 个检查器）。
        cp_dsts = [basename(m.group(1)) for m in RE_CP.finditer(text)]
        # 读回来的变量名也要算：`cat '$PUB'` 里的 $PUB
        for m in re.finditer(r'cat\s+\'?"?(\$\{?\w+\}?)', text):
            reads.append('$' + m.group(1).strip('${}').lstrip('$'))
        for tok, ln in writes:
            total_writes += 1
            name = basename(tok)
            var = None
            if name.startswith('$'):
                var = name.strip('${}')
            def _same(r, n):
                return r == n or (r and r in n) or (n and n in r)
            # 自己或中转目的地被读回，都算验过
            ok = (any(_same(r, name) for r in reads if r)
                  or (var and any(var in r for r in reads if r))
                  or any(_same(r, c) for c in cp_dsts for r in reads if r)
                  or (var and any(var in c for c in cp_dsts
                                  for r in reads if r and r in c)))
            if not ok:
                bad.append((rel, ln, tok.strip().strip('"').strip("'")))
                print(f'  ✗ {rel}:{ln}  写入 {tok.strip()} 之后没有读回它')
            elif a.verbose:
                print(f'  ✓ {rel}:{ln}  写入 {tok.strip()} 有读回')

    print(f'[writeback] 扫了 {len(scans())} 个脚本；{total_writes} 处设备写入，'
          f'{len(bad)} 处没有读回')
    if bad:
        print('[writeback] **写了不读回**：这些脚本会在推送失败时照样报告成功。')
        print('[writeback]   修法参照 `set_config.sh` / `set_flag.sh`：推完 `cat` 回来，'
              '按条目比（模块会用自己的序列化器重写文件，别按字节比）。')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
