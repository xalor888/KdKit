#!/usr/bin/env python3
"""
kuaidui-kit / check_shell_pipes.py — 两类"门禁红在自己身上"的管道写法。

### 为什么需要

2026-11-02 一天里踩到三次同一类问题，全在 shell 里，全都表现为
**"工具说坏了，其实没坏"**：

| # | 写法 | 后果 |
|---|---|---|
| 1 | `… \\| tee f \\| grep -q "^  PASS"` | `grep -q` 命中即退 ⇒ 上游 `tee` 收 SIGPIPE 被杀 ⇒ 日志文件被截断/没写成 ⇒ 第二个判断落空 ⇒ **误判 FAIL** |
| 2 | `set -e` 脚本里 `n=$(cmd \\| grep -c foo)` | 0 匹配时 `grep` 退出码 1 ⇒ 赋值语句"失败" ⇒ **整个脚本当场退出** |

第 1 条当天真的发生了（`verify_on_device.sh` 的 ⑬ 连红两次，重试也红；
单独跑同一个检查是 PASS）。第 2 条目前没有实例，但一旦有人写 `set -e` 就会中。

所以这道门禁不是"现在有 bug"，是**把今天付过的学费变成不再重复付**。

    python3 kit/scripts/check_shell_pipes.py
退出码：0 = 没有命中；1 = 有命中。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGETS = sorted(set(glob.glob(os.path.join(ROOT, 'kit', 'scripts', '*.sh')) +
                     glob.glob(os.path.join(ROOT, 'module', 'scripts', '*.sh'))))

#: ① tee 与 grep -q 同管（顺序不限）
TEE_AND_GREPQ = re.compile(r'tee\s+\S+.*\|\s*grep\s+-q|\|\s*grep\s+-q[^|\n]*\|\s*tee\s')
#: ② `$( … grep -c … )` —— 命令替换里数数
COUNT_IN_SUBST = re.compile(r'\$\(\s*[^)]*grep\s+-c[^)]*\)')
SET_E = re.compile(r'^\s*set\s+-[a-z]*e', re.M)


def main(argv):
    findings = []
    for path in TARGETS:
        rel = os.path.relpath(path, ROOT)
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
        # **注释不算**（2026-11-02：`verify_on_device.sh` 里有一段注释**引用**了旧写法，
        # 用来解释为什么改掉它 —— 结果检测器把"把 bug 写进注释"当成了"bug 还在"。
        # 和 `test_onboard_retry_shape.py` 那次是同一类假阳性。）
        # 只剔"整行注释"：行内注释里同样可能引用，但那种情况先接受，宁可多看一条。
        code = '\n'.join(ln for ln in text.splitlines()
                         if not ln.lstrip().startswith('#'))
        text = code
        has_set_e = bool(SET_E.search(text))

        for m in TEE_AND_GREPQ.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            findings.append((rel, line, 'tee+grep-q',
                             '`grep -q` 命中即退会让上游 `tee` 收 SIGPIPE 被杀，'
                             '日志文件可能被截断 ⇒ 后续判断落空 ⇒ 误判 FAIL。'
                             '改成"先捕获到变量、再落盘、再判断"。'))

        if has_set_e:
            for m in COUNT_IN_SUBST.finditer(text):
                line = text.count('\n', 0, m.start()) + 1
                findings.append((rel, line, 'set-e-grep-c',
                                 '`set -e` 下 `$(… grep -c …)`：0 匹配时 grep 退出码 1，'
                                 '赋值语句被判失败 ⇒ 整个脚本当场退出。'
                                 '改成 `n=$(cmd | grep -c foo || true)` 或先落盘再数。'))

    if not findings:
        print('[shell-pipes] 没有命中已知的管道陷阱')
        return 0
    print(f'[shell-pipes] **{len(findings)} 处**命中已知的管道陷阱：')
    for rel, line, rule, why in findings:
        print(f'  {rel}:{line}  [{rule}]  {why}')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
