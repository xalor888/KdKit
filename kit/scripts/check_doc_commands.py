#!/usr/bin/env python3
"""
kuaidui-kit / check_doc_commands.py — `PARADIGM.md` §5 里写的命令必须**真能跑**。

### 为什么需要

门禁表的"命令"列是新人的**操作入口**：照着抄就能单独跑那道门禁。
但它和代码之间没有任何断言 —— 脚本改名、参数改了名、搬到别的目录，
那一列就变成一句**看起来能跑的假命令**。

比数字漂移更糟的是：数字错了顶多一个数不对，**命令错了会让人以为"我跑过了"** ——
而他跑的是另一件事（或者根本没跑起来，只是没注意退出码）。

### 判据（只做便宜的两种，不真跑全部门禁）

| 检查 | 抓什么 |
|---|---|
| 脚本存在 | 文档写的路径在仓库里有没有 |
| 参数被接受 | `--help` 里有没有文档写的那些 flag（`--strict` / `--quiet` / `--fail-over` …） |

**不真跑**：① 要 30s、⑥b 要 65s，全跑一遍这门禁自己就成负担。
存在性 + 参数名能抓掉绝大部分漂移，且是 O(秒) 的。

    python3 kit/scripts/check_doc_commands.py
退出码：0 = 都对得上；1 = 有对不上的。
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(ROOT, 'module', 'PARADIGM.md')
MODULE = os.path.join(ROOT, 'module')

ROW = re.compile(r'^\|\s*([①-鿪]+[b]?)\s*\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|')
#: 文档里的占位符（不是真参数）
PLACEHOLDER = re.compile(r'<[^>]+>')


def rows():
    with open(DOC, encoding='utf-8') as f:
        text = f.read()
    i = text.find('## 5. 门禁')
    if i < 0:
        return []
    j = text.find('\n## ', i + 1)
    sec = text[i:j if j > 0 else len(text)]
    out = []
    for ln in sec.splitlines():
        m = ROW.match(ln)
        if m:
            out.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return out


def resolve(cmd):
    """把文档里的命令拆成 (可执行, [参数])，按 cwd=module/ 解析。

    `.py` 一律经 `sys.executable` 调 —— 第一版直接 `[exe, '--help']`，
    而仓库里的 `.py` 没有可执行位 ⇒ **6 条 PermissionError 假阳性**。
    """
    parts = cmd.split()
    if not parts:
        return None, [], None
    if parts[0] == 'python3':
        rest = parts[1:]
        # `python3 -m unittest …`：第二个 token 是 `-m`，不是脚本路径
        if rest and rest[0] == '-m':
            return sys.executable, rest, None
        # 相对路径按 cwd=module/ 解析
        if rest and not os.path.isabs(rest[0]):
            rest = [os.path.join(MODULE, rest[0]), *rest[1:]]
        return sys.executable, rest, (rest[0] if rest else None)
    if parts[0] == './gw':
        return os.path.join(MODULE, 'gw'), parts[1:], None
    if parts[0].startswith('./'):
        p = os.path.join(MODULE, parts[0][2:])
    elif parts[0].startswith('../'):
        p = os.path.join(ROOT, parts[0][3:])
    elif parts[0].endswith('.py') or parts[0].endswith('.sh'):
        # 文档省略了目录前缀（⑥b 那一行就是这么写的）⇒ 按 `module/scripts/` 兜底，
        # 找不到再报"文档里的命令缺路径"——那本身就是文档缺陷。
        for cand in (os.path.join(MODULE, 'scripts', parts[0]),
                     os.path.join(ROOT, 'kit', 'scripts', parts[0])):
            if os.path.isfile(cand):
                # 文档省略了目录 ⇒ 我能找到它，但**照抄的人找不到**。
                # 报出来（不判失败），因为这是文档缺陷，只是不致命。
                NOTES.append(f'{mark} {name}：命令省略了目录（`{parts[0]}`），'
                             f'实际在 `{os.path.relpath(cand, ROOT)}`')
                p = cand
                break
        else:
            return parts[0], parts[1:], None
    else:
        return parts[0], parts[1:]
    if p.endswith('.py'):
        return sys.executable, [p, *parts[1:]], p
    return p, parts[1:], (p if p.endswith('.sh') else None)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-cheap', action='store_true',
                    help='对判定为"秒级"的命令真的跑一遍（默认只查存在性与参数名）')
    a = ap.parse_args(argv[1:])

    rs = rows()
    if not rs:
        print('[doc-cmd] **在 PARADIGM.md §5 解析不出门禁表**')
        return 1

    bad = []
    NOTES = []
    print(f'{"门":4s} {"命令":44s} 结果')
    for mark, name, cmd in rs:
        exe, args, script = resolve(cmd)
        label = f'{mark} {name}'
        if exe is None:
            bad.append((label, cmd, '命令为空'))
            continue
        # **必须先查脚本本身**：`resolve` 会把 `.py` 换成 `sys.executable` 解释器，
        # 而解释器当然存在 —— 第一版只查了 exe，于是文档里把脚本名写错
        # （`check_shell_pipes_typo.py`）也照样通过，负对照当场失效。
        if script is not None and not os.path.isfile(script):
            rel = os.path.relpath(script, ROOT) if os.path.isabs(script) else script
            bad.append((label, cmd, f'找不到 {rel}'))
            print(f'{mark:4s} {cmd[:44]:44s} ✗ 找不到 {rel}')
            continue
        if script is None and not os.path.isfile(exe):
            bad.append((label, cmd, f'找不到 {exe}'))
            print(f'{mark:4s} {cmd[:44]:44s} ✗ 找不到 {exe}')
            continue

        # 参数名必须在 --help 里出现（去掉占位符后的每一个 --flag）
        flags = [p for p in args if p.startswith('--')]
        real_flags = [f for f in flags if not PLACEHOLDER.search(f)]
        # 只对"脚本 + flag"的形态查 --help；`./gw …` 那类交给 Gradle 自己。
        if real_flags and exe == sys.executable:
            script = next((p for p in args if not p.startswith('-')), None)
            if not script:
                bad.append((label, cmd, 'python3 后面没有脚本'))
                print(f'{mark:4s} {cmd[:44]:44s} ✗ python3 后面没有脚本')
                continue
            try:
                h = subprocess.run([exe, script, '--help'], capture_output=True,
                                   text=True, timeout=60, cwd=MODULE)
                helped = (h.stdout or '') + (h.stderr or '')
            except (subprocess.TimeoutExpired, OSError) as e:
                bad.append((label, cmd, f'--help 跑不起来：{type(e).__name__}'))
                print(f'{mark:4s} {cmd[:44]:44s} ✗ --help 跑不起来')
                continue
            missing = [f for f in real_flags if f not in helped]
            if missing:
                bad.append((label, cmd, f'--help 里没有 {missing}'))
                print(f'{mark:4s} {cmd[:44]:44s} ✗ 参数不被接受：{missing}')
                continue

        if a.run_cheap:
            try:
                r = subprocess.run([exe, *args], capture_output=True, text=True,
                                   timeout=180, cwd=MODULE)
                if r.returncode != 0:
                    bad.append((label, cmd, f'真跑退出码 {r.returncode}'))
                    print(f'{mark:4s} {cmd[:44]:44s} ✗ 真跑 rc={r.returncode}')
                    continue
            except (subprocess.TimeoutExpired, OSError) as e:
                bad.append((label, cmd, f'真跑失败：{type(e).__name__}'))
                print(f'{mark:4s} {cmd[:44]:44s} ✗ 真跑失败')
                continue

        print(f'{mark:4s} {cmd[:44]:44s} ✓')

    for n in NOTES:
        print(f'[doc-cmd] note  {n}')
    if bad:
        print(f'\n[doc-cmd] **{len(bad)} 条命令对不上**（照着抄会跑错事）：')
        for label, cmd, why in bad:
            print(f'   {label}  `{cmd}`  —— {why}')
        return 1
    print(f'\n[doc-cmd] {len(rs)} 条命令的脚本都在、参数都被接受 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
