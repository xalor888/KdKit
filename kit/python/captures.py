#!/usr/bin/env python3
"""
kuaidui-kit / captures.py — **“找抓取文件”的唯一实现**。

### 为什么需要

2026-11-03：同一个“找最新抓取”在四个文件里各写一遍，而**四种写法不一致**：

| 位置 | glob | 读法 |
|---|---|---|
| `export_content.newest_capture` | `.txt` + `.txt.gz`，**再把 `.gz` 滤掉** | `open()` |
| `after_login.newest_capture` | 同上 | `open()` |
| `pageapi` | 只有 `capture*.txt` | `open()` |
| `composition_flow.cuid_from_captures` | 只有 `capture*.txt` | `open()` |

`pack_slim.py` 会把 `--keep` 之外的旧包压成 `.txt.gz`。于是后两个
**静默跳过所有被压过的抓取** —— 它们只会说“没找到 cuid”，
而真相是“那些包被压掉了，而我没认 `.gz`”。

前两个的“滤掉 `.gz`”是有意的（要未压缩的那份），
但那个意图**只存在于那两个文件里**，换个工具就变了。

### 用法

```python
from captures import iter_captures, newest_capture, read_capture
for path in iter_captures():        # 新的在前，两种形态都有
    ...
newest_capture()                    # 真正最新的（可能是 .gz）
newest_capture(prefer_plain=True)   # 只在未压缩里挑最新的
read_capture(path)                  # .gz 自动解压
```
"""
import glob
import os

from textio import read_text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKS = os.path.join(ROOT, 'work', 'packs')


def iter_captures(prefer_plain=False):
    """全部抓取文件，**新的在前**。

    `prefer_plain=True` 时只返回未压缩的那些（`export_content` /
    `after_login` 的原意：它们要把抓取原文交给下游工具）。
    """
    pats = [os.path.join(PACKS, '*', 'capture*.txt')]
    if not prefer_plain:
        pats.append(os.path.join(PACKS, '*', 'capture*.txt.gz'))
    out = []
    for pat in pats:
        out += glob.glob(pat)
    if prefer_plain:
        out = [c for c in out if not c.endswith('.gz')]
    return sorted(out, key=os.path.getmtime, reverse=True)


def newest_capture(prefer_plain=False):
    """最新的抓取；一个都没有时返回 None。"""
    got = iter_captures(prefer_plain=prefer_plain)
    return got[0] if got else None


def read_capture(path):
    """读一份抓取；`.gz` 自动解压（走 `textio`）。"""
    return read_text(path)


CUID_RE = None


def find_cuid(path):
    """从一份抓取里找 cuid；找不到返回 None。

    正则与原来四处一致（`|` 在正则里要转义）。
    """
    import re
    global CUID_RE
    if CUID_RE is None:
        CUID_RE = re.compile(r'cuid=([0-9A-F]{16,}\|?\d*)')
    m = CUID_RE.search(read_capture(path))
    return m.group(1) if m else None
