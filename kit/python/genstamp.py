#!/usr/bin/env python3
"""
kuaidui-kit / genstamp.py — 给自动生成的文档打一个**输入指纹**，让"是否过期"可以被判断。

### 为什么不是时间戳

时间戳不可靠：`git checkout`、`touch`、打包、复制都会改它，而内容没变；
反过来，内容变了时间戳也可能因为 `cp -p` 之类保持旧值。
所以"这份文档是不是还对应现在的输入"只能靠**内容指纹**回答。

### 为什么不是"重跑一遍比对"

那是最强的判据（`check_generated_fresh.py` 就是这么做的），但它要求生成器**能离线复跑**。
`work/` 里有四份文档（`BRIDGE_PAGE_MAP` / `CONFIG_DUMP` / `CONTENT_SAMPLES` / `CORE_HTTP_REQUESTS` 的 .gz 分支）的生成需要设备，
离线门禁跑不了 —— 以前只能"跳过并列出"，等于放弃判断。

指纹把这一档补上：**不需要重跑生成器，只需要重算输入指纹**。
输入变了 ⇒ 文档一定过期；输入没变 ⇒ 文档内容仍可信（生成器是纯函数）。

### 指纹怎么算

对每个输入文件取 `relpath + size + sha256(内容)`，按 relpath 排序后整体再 sha256，取前 12 位。
超过 [MAX_HASH_BYTES] 的文件只计 `relpath + size`（并在结果里标 `~`），避免门禁读几十 MB。

    from genstamp import fingerprint, header_line
    fp, n, approx = fingerprint(paths)
    print(header_line('`work/packs/*/capture*.txt`', paths))
"""
import glob
import hashlib
import os
import re

#: 单个文件超过这个大小就不全文哈希（只计路径 + 大小）。
MAX_HASH_BYTES = 16 * 1024 * 1024

#: 文档里指纹行的格式。`check_generated_fresh.py` 用它回读。
FINGERPRINT_RE = re.compile(r'输入指纹：`([0-9a-f]{12})`\s*（(\d+) 个文件')
INPUT_GLOB_RE = re.compile(r'输入：(.+?)\s*（(\d+) 个文件')


def expand(patterns):
    """把 glob 列表展开成去重排序的真实文件列表。"""
    out = []
    for p in patterns:
        out.extend(glob.glob(p))
    return sorted(set(x for x in out if os.path.isfile(x)))


def fingerprint(paths):
    """@return (12 位 hex, 文件数, 是否含"只计大小"的近似项)"""
    h = hashlib.sha256()
    approx = False
    rel = []
    for p in sorted(set(paths)):
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        rel.append((os.path.relpath(p), size))
    for relp, size in rel:
        h.update(relp.encode())
        h.update(str(size).encode())
        if size <= MAX_HASH_BYTES:
            try:
                with open(p, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        h.update(chunk)
            except OSError:
                approx = True
        else:
            approx = True
    return h.hexdigest()[:12], len(rel), approx


def header_line(patterns, paths):
    """生成写进文档头部的两行（输入 glob + 指纹）。

    [patterns] 是 glob 列表；输出里每个都包在反引号里、用 ` + ` 连接，
    这样 `read_fingerprint()` 能把它拆回来重算 —— 人读和机读用同一份文本。
    """
    fp, n, approx = fingerprint(paths)
    mark = '~' if approx else ''
    desc = ' + '.join(f'`{p}`' for p in patterns)
    return (f'* 输入：{desc}（{n} 个文件）\n'
            f'* 输入指纹：`{fp}`（{n} 个文件{mark}）')


def read_fingerprint(doc_path):
    """从已生成的文档里读回 `(指纹, 文件数, [glob, …])`；没有则 None。"""
    try:
        with open(doc_path, encoding='utf-8') as f:
            head = ''.join(f.readline() for _ in range(40))
    except OSError:
        return None
    fm = FINGERPRINT_RE.search(head)
    gm = INPUT_GLOB_RE.search(head)
    if not fm or not gm:
        return None
    pats = [x.strip().strip('`') for x in gm.group(1).split(' + ') if x.strip()]
    return fm.group(1), int(fm.group(2)), pats
