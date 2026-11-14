#!/usr/bin/env python3
"""
kuaidui-kit / check_shell_vars.py — `$var` 紧跟非 ASCII 字符会炸。

## 这条检查的由来（同一 bug 我犯了两次）

```bash
RESULTS+=("PASS  $name（重试）")     # ← `（` 是全角括号
```

Bash 认变量名的边界是 `[A-Za-z0-9_]`。全角括号 `（`（U+FF08）不属于边界字符，
于是 `$name（重试）` 被当成一个变量名 `name（重试`，运行时报：

```
line 89: name�: unbound variable
```

第一次是第 36 轮，在 ⑩ 的重试分支里；修完 5 分钟，我在 ④⑤⑥ 的 SKIP 分支里
**又写了一遍**。同一个错误连犯两次，说明只靠"下次注意"不管用。

## 为什么它危险

* 只在**走到那条分支**时才炸 —— 第一次那条路径潜伏了三轮才现形；
* 报错信息是 `name�: unbound variable`，`�` 是编码问题的替身，
  很难一眼看出"是变量名边界"的问题；
* 默认的 `bash -n` **不报**这种错（语法合法，是运行时展开问题）。

## 修法

加花括号：`${name}（重试）`。

## 用法

```bash
python3 kit/scripts/check_shell_vars.py           # 人读
python3 kit/scripts/check_shell_vars.py --strict  # 有命中就 exit 1
```
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

#: `$var` 后面**直接**跟一个非 ASCII 字符（全角标点、中文等）。
#: 不报 `${var}`（已加花括号）、不报 `$var ` / `$var"` / `$var,` 这些 ASCII 边界。
BAD = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)([^\x00-\x7f])')

#: 注释行里的示例不算 —— 那是在说明这个 bug 本身。
COMMENT = re.compile(r'^\s*#')


def shell_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('.git', 'build', '.gradle')]
        for f in files:
            if f.endswith('.sh'):
                yield os.path.join(base, f)


def scan(root):
    hits = []
    for path in shell_files(root):
        rel = os.path.relpath(path, root)
        with open(path, encoding='utf-8', errors='replace') as fh:
            for no, line in enumerate(fh, 1):
                if COMMENT.match(line):
                    continue
                for m in BAD.finditer(line):
                    hits.append((rel, no, m.group(1), m.group(2), line.strip()))
    return hits


def main(argv):
    ap = argparse.ArgumentParser(description='$var 紧跟非 ASCII 字符会 unbound variable')
    ap.add_argument('--root', default=ROOT)
    ap.add_argument('--strict', action='store_true')
    a = ap.parse_args(argv[1:])

    hits = scan(a.root)
    if not hits:
        print('[shell-vars] 没有 $var 紧跟非 ASCII 字符的写法')
        return 0

    print(f'[shell-vars] {len(hits)} 处 `$var` 后面直接跟了非 ASCII 字符 —— 会 unbound variable：')
    for rel, no, var, ch, line in hits:
        print(f'  {rel}:{no}  ${var} 后跟 {ch!r}（U+{ord(ch):04X}）')
        print(f'      {line[:100]}')
        print(f'      修法：${{{var}}}{ch}…')
    return 1 if a.strict else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
