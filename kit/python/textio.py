#!/usr/bin/env python3
"""
kuaidui-kit / textio.py — **读文本文件**（`.txt` 与 `.txt.gz` 一视同仁）。

### 为什么需要

2026-11-03 代码审查 P2：

> **`.gz` 感知读取器 4 份逐字相同**（`core_http_paths:25` / `bridge_urls:20` /
> `api_login_map:23` / `bridge_page_map:26`）

四份一模一样的 5 行。一模一样意味着**改一处要改四处** ——
而这类读取器恰好是"证据的入口"：任何一处漏了 `.gz`，
那个工具就会**静默少读一半抓取**，而报告看不出异常。

（R76 刚把 `--captures "…*.txt" "…*.txt.gz"` 补进两份文档的复现命令，
那一刻起"读不读 `.gz`"就是四个工具共同的行为契约。）

### 用法

```python
from textio import read_lines, read_text
lines = read_lines(path)          # list[str]，自动识别 .gz
```
"""
import gzip
import os


def is_gz(path):
    return str(path).endswith('.gz')


def read_text(path, encoding='utf-8', errors='replace'):
    """读整个文件；`.gz` 自动解压。"""
    if is_gz(path):
        with gzip.open(path, 'rt', encoding=encoding, errors=errors) as f:
            return f.read()
    with open(path, encoding=encoding, errors=errors) as f:
        return f.read()


def read_lines(path, encoding='utf-8', errors='replace'):
    """按行读；`.gz` 自动解压。**行尾不带换行符**（与 `str.splitlines()` 一致）。"""
    return read_text(path, encoding, errors).splitlines()


def expand(patterns):
    """把一批 glob（可含 `.txt` 与 `.txt.gz`）展开成实际文件列表。

    四个工具的 `--captures` 都收多个 glob；展开逻辑一致才谈得上"同一份输入"。
    """
    import glob as _glob
    out = []
    for pat in patterns:
        out += sorted(_glob.glob(pat))
    return out


def write_text(path, content, encoding='utf-8'):
    """写一个文本文件；句柄一定关闭。"""
    with open(path, 'w', encoding=encoding) as f:
        f.write(content)


def exists(path):
    """`.gz` 与明文都算存在。"""
    return os.path.isfile(path)
