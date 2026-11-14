#!/usr/bin/env python3
"""
kuaidui-kit / check_tls_default.py — 跳过 TLS 校验必须经过**同一个**决定点。

### 为什么需要

2026-11-03 代码审查 P1：

> 6 处**无条件**跳过 TLS 校验，而 `kd_api` 是 `--insecure` 才跳 —— 同库两种默认。

同一个仓库里两种默认值的后果：

* 同一个请求，走 A 工具能成、走 B 工具不能成，而差异不在代码逻辑里；
* 前面挂着代理/自签证书时，六个工具静默接受、`kd_api` 报错 ——
  "是服务端拒绝了，还是我的证书环境不对"**无法从现象区分**；
* 新写一个工具的人会照抄旁边那份，把"无条件跳"继承下去。

### 判据

`kit/python/` 与 `kit/scripts/` 下，除了 `net.py` 自己，
**不许**再出现 `_create_unverified_context()`。要跳就走 `net.ssl_context()`，
它认 `KD_INSECURE`，默认**校验**。

### 退出码

0 = 只有一个决定点；1 = 有文件绕过了它。
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = [os.path.join(ROOT, 'kit', 'python', '*.py'),
        os.path.join(ROOT, 'kit', 'scripts', '*.py')]
ALLOWED = {
    os.path.relpath(os.path.join(ROOT, 'kit', 'python', 'net.py'), ROOT),
    os.path.relpath(os.path.abspath(__file__), ROOT),   # **不扫自己**：正则在字面量里
}
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
from negctl_fixtures import is_fixture                              # noqa: E402

RE_BAD = re.compile(r'_create_unverified_context\s*\(')
RE_GOOD = re.compile(r'net\.ssl_context\s*\(')


def code_only(path):
    """只留代码，去掉注释与字符串字面量。

    **今天第四次**被"写在注释里的 bug"绎倒（前三次：R19 / R36 / R46）。
    本次实例：`negctl_fixtures.py` 的 docstring 里为了说明问题写了
    __create_unverified_context（），于是检查器把它当成一处真缺陷。
    """
    import io
    import tokenize
    try:
        with open(path, 'rb') as f:
            toks = [t for t in tokenize.tokenize(f.readline)
                    if t.type not in (tokenize.COMMENT, tokenize.STRING)]
        return tokenize.untokenize(toks).decode('utf-8', 'replace')
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return open(path, encoding='utf-8', errors='replace').read()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    bad, good = [], 0
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            if rel in ALLOWED or is_fixture(p):
                continue
            src = code_only(p)
            for m in RE_BAD.finditer(src):
                bad.append((rel, src.count('\n', 0, m.start()) + 1))
            good += len(RE_GOOD.findall(src))

    if a.verbose and good:
        print(f'[tls] {good} 处走 `net.ssl_context()` ✓')

    if bad:
        print(f'[tls] **{len(bad)} 处绕过统一决定点**，直接造了不校验的 context：')
        for rel, ln in bad:
            print(f'   {rel}:{ln}')
        print('[tls]   修法：改成 `net.ssl_context()` —— 它认 `KD_INSECURE`，'
              '默认**校验**，与 `kd_api --insecure` 语义一致。')
        return 1
    print('[tls] 只有一个 TLS 决定点（`kit/python/net.py`）✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
