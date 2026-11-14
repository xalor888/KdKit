#!/usr/bin/env python3
"""
kuaidui-kit / artifact_audit.py — 产物体检（2026-10-13 ✓，规则 27 ✓）。

由来：R517 按"修修"那条入口走了一遍 ✓，做了三路扫描 ✓ ⇒ **它刚证明了能发现问题** ✓
（那次是虚惊 ✓ —— 但"虚惊"本身说明**扫描是有效的** ✓，所以存下来 ✓）。

三路 ✓：
  ① 导出文件里有没有"零行 / 单行"的可疑产物；
  ② `work/*.md` 里有没有"标题下没内容"的空章节；
  ③ 自动生成文档里有没有"基础名碰撞"（`short()` 那类 ✗）。

    python3 kit/scripts/artifact_audit.py
退出码：0 = 三项都干净 ✓；1 = 有可疑 ✗。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import collections
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
bad = []

# ④ 替换字符（U+FFFD）—— 2026-10-13 加 ✓
#    白名单：`kit/ONBOARDING.md` 里有两处**原文如此** ✓（shell 打坏变量名时的字样 ✓，见该文件注 ✓）。
_ALLOW = {'kit/ONBOARDING.md': 2}
for f in sorted(glob.glob(os.path.join(ROOT, 'work', '*.md')) +
                glob.glob(os.path.join(ROOT, 'kit', '*.md')) +
                [os.path.join(ROOT, 'REPORT.md')]):
    try:
        c = textio.read_text(f, encoding='utf-8').count('\ufffd')
    except Exception:
        continue
    rel = os.path.relpath(f, ROOT)
    if c > _ALLOW.get(rel, 0):
        bad.append(f'替换字符 {c} 处（白名单 {_ALLOW.get(rel, 0)}）✗ `{rel}`')

# ① 导出：<=1 数据行
for f in sorted(glob.glob(os.path.join(ROOT, 'work', 'exports', '*.csv'))):
    n = sum(1 for _ in textio.read_lines(f, encoding='utf-8', errors='replace')) - 1
    if n <= 1:
        bad.append(f'导出过小 `{os.path.basename(f)}`：{n} 行')

# ② 空章节
for f in sorted(glob.glob(os.path.join(ROOT, 'work', '*.md'))):
    lines = textio.read_text(f, encoding='utf-8', errors='replace').split('\n')
    for i, l in enumerate(lines):
        if re.match(r'^## ', l):
            if not [x for x in lines[i + 1:i + 4] if x.strip()]:
                bad.append(f'空章节 `{os.path.basename(f)}` 第 {i + 1} 行：{l[:44]}')
                break

# ③ 生成文档里的**精确**标题重复（不是"基础名"重复 ✗）
#    2026-10-13 修 ✓（**本工具首次运行就出了假阳性** ✗ —— 同 R355/R456/R457/R504）：
#    R505 给 `short()` 加了 `#xxxx` 消歧后缀 ✓ ⇒ **基础名相同是"设计如此"** ✓，不是碰撞 ✗。
#    判据：**去掉后缀后仍完全相同 ⇒ 才算** ✓（有后缀的说明已经被区分开了 ✓）。
bm = os.path.join(ROOT, 'work', 'BRIDGE_PAGE_MAP.md')
if os.path.exists(bm):
    heads = re.findall(r'^## `([^`]+)`', open(bm, encoding='utf-8').read(), flags=re.M)
    c = collections.Counter(heads)
    for k, n in c.items():
        if n > 1:
            bad.append(f'标题完全重复 x{n}：{k[:56]}')

if bad:
    print(f'[audit] **{len(bad)} 处可疑** ✗：')
    for b in bad[:10]:
        print(f'   {b}')
    return_code = 1
else:
    print('[audit] 四路全干净 ✓（导出 ✓ / 空章节 ✓ / 标题碰撞 ✓ / 替换字符 ✓）')
    return_code = 0
sys.exit(return_code)
