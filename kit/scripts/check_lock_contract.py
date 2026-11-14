#!/usr/bin/env python3
"""
kuaidui-kit / check_lock_contract.py — “套锁”的契约必须成立，否则门禁会**静默死锁**。

### 为什么值得一道门（2026-11-09 04:0x 的真事故）

跨进程互斥靠 `kit/scripts/with_lock.py`。`verify.sh` 和 `run_negative_controls.py`
都"自锁"（自己 exec 一层 `with_lock`）—— 这个设计本身是对的（纪律写进脚本里）。
但它与"调用方也套了锁"组合时，变成**子进程等父进程的锁**：

    with_lock --label r3-nd2 -- bash verify.sh
      └─ verify.sh 自锁 → exec with_lock … → flock 同一把锁 → 永久等待

现场证据：`work/program/verify_r3.log` 全文只有一行 `[lock] 持有 …：r3-final2`，
**一道门都没跑**；两条链同时卡了 12 分钟才被外部 `kill`（`obs`）。同型事故还在
`verify_r4.log` 复现过一次：跑到 ㉖ 被外部 SIGTERM（`ps`/`lsof` 均为空、owner 残留）。

死锁这种故障**没有任何失败信号**（不红、不绿、不报错），所以必须有静态门禁。

### 判据（五条，全部是"文本里必须有/必须没有"）

| # | 判据 | 失败含义 |
|---|---|---|
| L1 | `with_lock.py` 注入 `KD_LOCK_HELD` 到子进程环境 | 同链无法识别"锁已在手" |
| L2 | `with_lock.py` 在 flock **之前**读 `KD_LOCK_HELD` 并走继承分支 | 重入不成立 ⇒ 死锁 |
| L3 | `verify.sh` 的自锁条件**同时**判断 `KD_LOCK_HELD` | 调用方套锁 ⇒ verify 死锁 |
| L4 | `run_negative_controls.py` 的自锁条件判断 `KD_LOCK_HELD` | 同上（它改源码，更贵） |
| L5 | 任何"自锁"文件缺 `KD_LOCK_HELD` ⇒ 红 | 新加的自锁 script 会重蹈覆辙 |

### 退出码

0 = 契约成立；1 = 有违反；2 = 无法验证（找不到 `with_lock.py` / 目标文件缺失）。

    python3 kit/scripts/check_lock_contract.py
    python3 kit/scripts/check_lock_contract.py --root /tmp/mini   # 自测用
    python3 kit/scripts/check_lock_contract.py --selftest         # 证明这道门能红
"""
import argparse
import ast
import os
import shutil
import sys
import tempfile

TOKEN = 'KD_LOCK_HELD'


def _read(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError as e:
        print(f'[lock-contract] 读不到 {path}：{e}', file=sys.stderr)
        return None


def _self_lock_guarded(text, suffix):
    """文本里是否存在"自锁 exec"，且它的守卫条件提到 KD_LOCK_HELD。

    两个坑（2026-11-09 04:3x 实测，都被本工具自己踩过）：
      1. **注释/文档里的 `exec with_lock` 不是自锁**（verify.sh 的注释就写了
         "这里再 exec 一次"）—— 所以跳过 `#` 开头的行；
      2. `os.execv(...)` 的 `with_lock.py` 常在**下一行**（negctl 就是这样），
         只匹配同一行会把最贵的那个自锁点漏掉。

    返回 (ok, why)；没有自锁 ⇒ (True, 'no-self-lock')。
    """
    lines = text.splitlines()

    # ── 找"自锁 exec"的位置 ─────────────────────────────────────────────
    # .py 走 AST：只有**真的 os.execv(…)/subprocess.run(…)** 且实参里出现
    # `with_lock` 才算自锁。纯文本匹配会把 docstring 里那句
    # "`os.execv(...)` 的 `with_lock.py` 常在下一行" 当自锁（2026-11-09 04:4x 假红）。
    # .sh 没有 AST 可用，仍然看行（跳过 `#` 注释行）。
    execs = []
    if suffix == '.py':
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return False, f'语法错误，无法判定：{e}'
        names = {'os.execv', 'subprocess.run', 'subprocess.Popen'}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            fn = (f'{getattr(f.value, "id", "")}.{f.attr}'
                  if isinstance(f, ast.Attribute) else getattr(f, 'id', ''))
            if fn not in names:
                continue
            seg = ast.get_source_segment(text, node) or ''
            if 'with_lock' in seg:
                execs.append(node.lineno - 1)
    else:
        marks = ('exec python3', 'exec "$', 'subprocess.run(')
        for i, ln in enumerate(lines):
            if ln.strip().startswith('#'):
                continue
            if not any(m in ln for m in marks):
                continue
            if 'with_lock' not in ''.join(lines[i:i + 4]):
                continue
            execs.append(i)

    if not execs:
        return True, 'no-self-lock'
    for i in execs:
        guard = None
        for j in range(i, max(-1, i - 16), -1):
            st = lines[j].lstrip()
            if st.startswith(('if ', 'if(', 'if (')):
                guard = j
                break
        if guard is None:
            return False, f'第 {i + 1} 行的自锁 exec 找不到守卫条件'
        region = '\n'.join(lines[guard:i + 1])
        if TOKEN not in region:
            return False, (f'第 {guard + 1} 行起的守卫没有判断 {TOKEN} '
                           f'⇒ 调用方套锁时会死锁（exec 在第 {i + 1} 行）')
    return True, 'guarded'


def check(root):
    """返回 (problems, notes)；problems 非空 ⇒ 红。"""
    problems, notes = [], []
    lock = os.path.join(root, 'kit', 'scripts', 'with_lock.py')
    verify = os.path.join(root, 'module', 'scripts', 'verify.sh')
    negctl = os.path.join(root, 'kit', 'scripts', 'run_negative_controls.py')

    src = _read(lock)
    if src is None:
        return None, ['找不到 kit/scripts/with_lock.py ⇒ 无从验证']

    # L1：注入到子进程环境
    if f"env['{TOKEN}']" not in src:
        problems.append(f'L1 with_lock.py 没有把 {TOKEN} 注入子进程环境 ⇒ 子链无法继承')

    # L2：重入分支必须在"取锁循环"之前 —— 用 AST 判，不靠字符串先后
    # （`--status` 分支里也有一次 flock，纯文本比较会误判，上一版就这么假红过）。
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return None, [f'with_lock.py 语法都过不了：{e}']
    main_fn = next((n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'main'), None)
    if main_fn is None:
        return None, ['with_lock.py 里找不到 main() ⇒ 无从判定']
    branch_line = None
    for node in ast.walk(main_fn):
        if isinstance(node, ast.If) and any(
                isinstance(x, ast.Name) and x.id == 'held_by_ancestor'
                for x in ast.walk(node.test)):
            branch_line = node.lineno
            has_early_return = any(isinstance(x, ast.Return) for x in ast.walk(node))
            if not has_early_return:
                problems.append('L2 重入分支没有提前 return ⇒ 仍会往下走到取锁')
    while_line = min((n.lineno for n in ast.walk(main_fn) if isinstance(n, ast.While)),
                     default=None)
    if branch_line is None:
        problems.append(f'L2 with_lock.py 没有基于 {TOKEN} 的重入分支')
    elif while_line is None:
        problems.append('L2 找不到取锁循环（结构变了？）⇒ 无从判定顺序')
    elif branch_line > while_line:
        problems.append(f'L2 重入分支在第 {branch_line} 行，取锁循环在 {while_line} 行 '
                        '⇒ 先等锁再判重入，等于没判')
    else:
        notes.append(f'L2 重入分支（第 {branch_line} 行）在取锁循环（第 {while_line} 行）之前 ✓')

    # L3 / L4 / L5：凡是"自锁 exec"的那一行，**紧挨着的守卫条件**里必须有 token
    # （只看文件里出现过 token 是不够的 —— 注释/日志里提一句就会蒙混过关，
    #  2026-11-09 04:2x 的 selftest 正是这么假绿的）。
    for path, tag in ((verify, 'L3 verify.sh'), (negctl, 'L4 run_negative_controls.py')):
        text = _read(path)
        if text is None:
            return None, [f'{tag}: 目标文件缺失 ⇒ 无法验证']
        ok, why = _self_lock_guarded(text, os.path.splitext(path)[1])
        if ok:
            notes.append(f'{tag} 的自锁守卫认 {TOKEN} ✓')
        else:
            problems.append(f'{tag} {why}')

    others = []
    for d in (os.path.join(root, 'kit', 'scripts'), os.path.join(root, 'module', 'scripts')):
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(('.py', '.sh')):
                continue
            p = os.path.join(d, name)
            if os.path.abspath(p) in (os.path.abspath(lock), os.path.abspath(verify),
                                      os.path.abspath(negctl)):
                continue
            text = _read(p)
            if text is None:
                continue
            ok, why = _self_lock_guarded(text, name[name.rfind('.'):])
            if why == 'no-self-lock':
                continue
            if not ok:
                others.append(f'{name}（{why}）')
    if others:
        problems.append('L5 这些文件自锁却没能识别同链持锁：' + '; '.join(others))

    return problems, notes


def selftest():
    """三个最小树：正确 ⇒ 0；删掉继承判断 ⇒ 1；缺文件 ⇒ 2。
    （门禁能红才算门禁 —— 与 ㉔ 的口径一致。）"""
    ok = True
    base = tempfile.mkdtemp(prefix='kdlock-contract-')
    try:
        cases = []
        # ① 正确树：直接从仓库拷三个文件
        good = os.path.join(base, 'good')
        for rel in ('kit/scripts/with_lock.py', 'kit/scripts/run_negative_controls.py',
                    'module/scripts/verify.sh'):
            dst = os.path.join(good, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), rel)
            shutil.copyfile(src, dst)
        cases.append(('good', good, 0))

        # ② 坏树：把 verify.sh 里的 KD_LOCK_HELD 判断删掉
        bad = os.path.join(base, 'bad')
        shutil.copytree(good, bad)
        vp = os.path.join(bad, 'module', 'scripts', 'verify.sh')
        text = _read(vp) or ''
        text = text.replace('${' + TOKEN + ':-}', '')
        with open(vp, 'w', encoding='utf-8') as f:
            f.write(text)
        cases.append(('bad', bad, 1))

        # ③ 缺树：没有 with_lock.py ⇒ 无法验证
        miss = os.path.join(base, 'miss')
        os.makedirs(miss, exist_ok=True)
        cases.append(('miss', miss, 2))

        for label, root, want in cases:
            probs, notes = check(root)
            rc = 2 if probs is None else (1 if probs else 0)
            mark = 'OK' if rc == want else '**FAIL**'
            print(f'[selftest] {label}: rc={rc} 期望 {want} → {mark}')
            if rc != want:
                ok = False
                for p in (probs or notes):
                    print(f'[selftest]   · {p}')
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--root', default=None, help='仓库根（默认本脚本所在仓库）')
    ap.add_argument('--selftest', action='store_true', help='证明这道门禁会红')
    a = ap.parse_args(argv[1:])

    if a.selftest:
        return selftest()

    root = a.root or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    probs, notes = check(root)
    if probs is None:
        print('[lock-contract] 无法验证：' + (notes[0] if notes else '未知原因'))
        return 2
    for n in notes:
        print(f'[lock-contract]   {n}')
    if probs:
        print(f'[lock-contract] {len(probs)} 处违反：')
        for p in probs:
            print(f'[lock-contract]   ✗ {p}')
        return 1
    print('[lock-contract] 套锁契约成立 ✓（注入 + 重入 + 两个自锁点都认 '
          f'{TOKEN}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
