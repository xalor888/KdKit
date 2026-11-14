#!/usr/bin/env python3
"""
kuaidui-kit / check_comment_claims.py — 找出"注释里说门禁会做 X"的地方，供人工核对。

## 为什么需要它

注释比代码更容易过期，而且**过期后不会有人发现** —— 它不会编译失败、不会让测试变红。

本项目已经踩过三次：
1. `AdFeatures.kt:158` 说"门禁会标 UNKNOWN"，而 `smali_usage` 早已细分出
   `TYPE-ONLY` / `SUPER-SLOT` / `REFLECTIVE-ENTRY` —— 注释描述的是一年前的判定体系；
2. `check_hook_targets.py` 里 `FORWARD_FN_RE` / `DYNAMIC_CLASS_RE` 的说明段
   在函数删掉后还留着；
3. `module_activity.py` 的注释说某张表是手写的，实际已由生成器产出。

这类问题的共同点：**注释断言了一个可验证的事实，但没人去验证。**

## 它检查什么

扫描模块源码的注释，揪出"声称某个门禁/脚本会怎样"的句子，列出位置，
让人能逐条去核。

**它不做自动判定** —— 判断"这条注释是否仍然成立"需要理解语义，
自动判定会误报。这道工具的价值是**把散落各处的断言集中起来**，
让核对从"想不起来要查"变成"照单核对"。

## 用法

```bash
python3 kit/scripts/check_comment_claims.py          # 列出所有断言
python3 kit/scripts/check_comment_claims.py --count  # 只报数量
```
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

#: "谁 会 怎样" —— 主语是门禁/脚本/生成器，谓语是判断类动词。
CLAIM_RE = re.compile(
    r'(门禁|脚本|生成器|check_\w+|smali_usage|feature_matrix|module_activity)'
    r'[^\n]{0,24}?'
    r'(会|将|必须|总是|从不|不会)'
    r'[^\n]{0,40}'
)

SRC_EXT = ('.kt', '.py')


def walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('.git', 'build', '.gradle', 'apktool_out')]
        for f in files:
            if f.endswith(SRC_EXT):
                yield os.path.join(base, f)


def comment_lines(path):
    """只取注释行（`//` / `*` / `#`）—— 代码行里的字符串不算"注释断言"。"""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for no, line in enumerate(fh, 1):
                s = line.strip()
                if s.startswith('//') or s.startswith('*') or s.startswith('#'):
                    yield no, s
    except OSError:
        return


def scan(root):
    hits = []
    for path in walk(root):
        rel = os.path.relpath(path, root)
        for no, line in comment_lines(path):
            m = CLAIM_RE.search(line)
            if m:
                hits.append((rel, no, m.group(0).strip()))
    return hits


def main(argv):
    ap = argparse.ArgumentParser(description='列出注释里"门禁会怎样"的断言')
    ap.add_argument('--root', default=os.path.join(ROOT, 'module', 'app', 'src', 'main'))
    ap.add_argument('--count', action='store_true')
    a = ap.parse_args(argv[1:])

    hits = scan(a.root)
    if a.count:
        print(f'[claims] {len(hits)} 处注释断言了门禁/脚本行为')
        return 0

    by_file: dict[str, list] = {}
    for rel, no, text in hits:
        by_file.setdefault(rel, []).append((no, text))

    print(f'[claims] {len(hits)} 处注释断言了门禁/脚本行为 —— 逐条核对它们是否仍成立：\n')
    for rel in sorted(by_file):
        print(f'  {rel}')
        for no, text in by_file[rel][:8]:
            print(f'    :{no}  {text[:100]}')
        if len(by_file[rel]) > 8:
            print(f'    … 另有 {len(by_file[rel]) - 8} 处')
        print()
    print('  提示：这类断言不会自动失效 —— 函数删了、门禁改了，注释照样留在这儿。')
    print('  核对过的可以在行尾加 `（YYYY-MM-DD 已核对）`，方便下次跳过。')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
