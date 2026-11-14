#!/usr/bin/env python3
"""
kuaidui-kit / check_sign_url_dup.py — `SIGN URL` 的提取只许有一处。

### 为什么需要

2026-11-04 代码审查 P2：**三处**各写了一遍

    urls = [l.split(<标记>, 1)[1].strip() for l in lines if <标记> in l]   # <标记> = 空格+SIGN URL: 空格

（`extract_samples.py` / `export_content.py` / `probe_paths.py`）

收敛到 `capture_schema.sign_urls()` 时发现那个写法**两处都是错的**：

| 旧写法 | 后果 |
|---|---|
| 只按子串 `' SIGN URL: '` 判 | 解密响应体里**回显**的 URL 也被当成发出去的请求（实测 9 份抓取里各多 1 条） |
| 不认 `APPSIGN I/Tag: [KdKit] SIGN URL:` 中继形态 | 除非靠上面的"宽判据"顺带蒙对 |
| 不处理 `LogSink` 的截断尾巴 ` …(719)` | 45 条截断 URL 被当正常 URL 用；`urlparse` 仍给出正确 path ⇒ **拿坏 URL 发请求** |

三种错误里最坏的是第三种：它不报错，只是把坏参数发出去。

### 判据

AST / 文本扫描 `kit/**/*.py`：出现 `split(<标记>` 且文件不是
`capture_schema.py` ⇒ 红。（测试文件里可以出现 —— 那里是在**记录**旧写法有多坏。）

### 退出码

0 = 只有一处；1 = 又出现了第二处。
"""
import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

#: 唯一允许的地方。
OWNER = os.path.join('kit', 'python', 'capture_schema.py')

#: 测试里允许出现 —— 那里是**反例**，用来钉住"旧写法确实会错"。
ALLOW_PREFIXES = (os.path.join('kit', 'python', 'tests'),)

#: **负对照的用例表里也允许出现** —— 那个文件的职责就是"装一段故意写坏的代码，
#: 然后证明某道门禁能红"。它的字符串常量里必然含有被禁的模式。
#: 这不是豁免某个实现，是把"样本"和"实现"分开。
ALLOW_FILES = (os.path.join('kit', 'scripts', 'run_negative_controls.py'),)

NEEDLE = "split(' SIGN URL: '"

#: 允许的例外记号。**为什么不许静默豁免**：
#: 豁免表会长大，而长大的豁免表就是"永远绿的门禁"。
#: 要求"每个例外在同一行写清理由"，至少让它在 diff 里可见。
#: 目前只有一处：`kd_api.py` 的 `common_from` 模式需要**保留 URL 与
#: params 的相对顺序**，`sign_urls()` 只给 URL，丢掉顺序就没法配对。
ANNOT = '# signurl-ok:'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    hits = []
    for pat in ('kit/**/*.py',):
        for p in glob.glob(os.path.join(ROOT, pat), recursive=True):
            rel = os.path.relpath(p, ROOT)
            if rel == os.path.relpath(os.path.abspath(__file__), ROOT):
                continue          # 检查器自己（NEEDLE 与 docstring）
            if rel == OWNER or rel.startswith(ALLOW_PREFIXES) or rel in ALLOW_FILES:
                continue
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f, 1):
                        if NEEDLE in line and ANNOT not in line:
                            hits.append(f'{rel}:{i}')
            except OSError:
                continue

    print(f'[signurl] `split(\' SIGN URL: \')` 出现在 {len(hits)} 处（只许 0 处）')
    for h in hits:
        print(f'  ✗   {h}')
    if hits:
        print("[signurl]   修法：`import capture_schema` 然后用 "
              "`capture_schema.sign_urls(source)`。")
        print('[signurl]   它同时处理三件旧写法做错的事：')
        print('[signurl]     1. 按 kind 判，不把解密响应体里**回显**的 URL 当成请求；')
        print('[signurl]     2. 认 `APPSIGN …: [KdKit] SIGN URL:` 中继形态；')
        print('[signurl]     3. 剔除 `LogSink` 截断的 ` …(719)` 尾巴，并单独计数。')
        return 1
    if a.verbose:
        print('[signurl] 只有 capture_schema 一处 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
