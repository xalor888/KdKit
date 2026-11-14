#!/usr/bin/env python3
"""
kuaidui-kit / ascii_lint.py — 脚本里的"变量紧邻全角字符"检查（2026-10-12）。

由来：同类 bug 已 **2 次** ✗（R295 `checkup.sh` ✓ / R361 `recover_device.sh` ✓）——
变量紧邻全角括号/逗号时，某些调用路径会把变量名与全角字节连在一起 ✗ ⇒ `unbound variable` ✓。

    python3 kit/scripts/ascii_lint.py [--fix-hint]
退出码：0 = 干净 ✓；1 = 有风险行 ✗。
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FW = r'[\u4e00-\u9fff（）：、，。！？；「」『』]'
# **`${var}` 是安全的**（2026-11-02 改）——它把变量名和后面的字符明确分界了，
# 所以 `${RC}（需要 Permissive）` 不会有 `unbound variable` 问题。
# 旧正则把 `$`、`{`、字母一视同仁地当作"变量开头"，于是**每一处正确的 `${…}`
# 都被报出来** —— 这种 linter 会教人忽略它（`env_up.sh` / `after_login.sh` 里
# 5 处全部是正确写法）。
# 现在的做法：匹配到时先看是不是 `${`，是就跳过。
PAT_A = re.compile(r'\$[A-Za-z_{][^\s]{0,24}' + FW)
PAT_B = re.compile(FW + r'[^\s]{0,4}\$[A-Za-z_{]')


def _safe_braced(line, pos):
    """pos 处的 `$` 是不是 `${…}` 形式 —— 是则为安全写法。"""
    return pos + 1 < len(line) and line[pos + 1] == '{'


def _risky(line):
    """这一行里有没有**未加花括号**的 `$var` 紧邻全角字符。

    `${var}` 一律放过：花括号已经把变量名和后面的字符分界，不会出现
    `unbound variable`。旧实现不区分，于是 `env_up.sh` / `after_login.sh` 里
    5 处**正确**写法全被报出来 —— linter 报假警比漏报更伤：
    它会训练人看见红就跳过。
    """
    for m in PAT_A.finditer(line):
        if _safe_braced(line, m.start()):
            continue
        return True
    for m in PAT_B.finditer(line):
        dollar = line.find('$', m.start())
        if dollar >= 0 and _safe_braced(line, dollar):
            continue
        return True
    return False


def scan():
    bad = []
    for f in sorted(glob.glob(os.path.join(ROOT, 'kit', 'scripts', '*.sh'))
                    + glob.glob(os.path.join(ROOT, 'kit', 'python', '*.py'))):
        try:
            lines = textio.read_text(f, encoding='utf-8').split('\n')
        except Exception:
            continue
        for i, ln in enumerate(lines, 1):
            # **Python 的纯注释行跳过**：`# … 写入侧是 "$tag: $msg" …` 只是文档，
            # 不会被执行，$(…) 也不会在那里展开。旧实现把 kit/python/*.py 整份扫进来，
            # 于是 capture_schema.py 里两条讲日志格式的注释让本门**恒红**
            # （代码审查 P0-8；tool_sanity 因此一直是红的，没人敢开）。
            # 真正有风险的形态是"用字符串拼 shell 命令"，那一定出现在字面量/ f-string 里。
            if f.endswith('.py') and ln.lstrip().startswith('#'):
                continue
            if _risky(ln):
                bad.append((os.path.relpath(f, ROOT), i, ln.strip()[:90]))
    return bad


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--fix-hint', action='store_true')
    a = ap.parse_args(argv[1:])
    bad = scan()
    if not bad:
        print('[ascii_lint] 干净 ✓（无"变量紧邻全角"的行 ✓）')
        return 0
    print(f'[ascii_lint] **{len(bad)} 行有风险** ✗：')
    for f, i, ln in bad[:20]:
        print(f'   {f}:{i}  {ln}')
    if a.fix_hint:
        print('   修法 ✓：把该行改成 ASCII ✓（中文提示与变量分行 ✓ 或整行英文 ✓）')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
