#!/usr/bin/env python3
"""
kuaidui-kit / check_hook_gate_predicate.py — gate 判据只许有一处实现。

### 为什么需要

2026-11-04：`Xp.kt` 里那条判据**抄了 6 遍**：

    if (gate != null && !KdConfig.isOn(gate, GatePolicy.defaultFor(gate))) return

（`hook` 的 before/after、`hookCtor` 的 before/after、`hookAllBefore`、`hookAllAfter`）

抄 6 遍的风险不是"抄错"，而是**改的时候漏改** ——
漏改的那一处会让"关掉功能"失效，症状是 UI 上开关是关的、
App 侧行为完全不变，**不报错**。

已收敛为 `Xp.gateOpen(gate)` 一处。

### 判据

1. `Xp.kt` 里出现 `gate != null && !KdConfig.isOn(` ⇒ 红（那是被抄开的判据）；
2. `Xp.kt` 里 `gateOpen` 的定义**恰好一处**；
3. `Xp.kt` 里每个 `if (!gateOpen(gate)) return` 出现在**钩子回调内部**
   —— 判据必须在回调里判，不能在装钩子时判（装钩子时配置还没生效）。

第 3 条用"每个 `gateOpen` 调用都在某个 `override fun ...HookedMethod` 体内"来判，
避免"判据写在 install() 里 ⇒ 装上就永远按当时配置跑"这种更隐蔽的错法。

### 退出码

0 = 判据只有一处且用对；1 = 有第二处，或用法不对。
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XP = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev',
                  'xalor', 'kdkit', 'util', 'Xp.kt')

SPREAD = 'gate != null && !KdConfig.isOn('
DEF_RX = re.compile(r'internal fun gateOpen\s*\(')
CALL_RX = re.compile(r'if \(!gateOpen\(gate\)\) return')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    if not os.path.isfile(XP):
        print('[gatepred] 找不到 Xp.kt')
        return 1
    src = open(XP, encoding='utf-8', errors='replace').read()
    lines = src.split('\n')

    bad = []

    n_spread = src.count(SPREAD)
    if n_spread:
        bad.append(f'`{SPREAD}` 出现 {n_spread} 次 —— 判据被抄开了')

    n_def = len(DEF_RX.findall(src))
    if n_def != 1:
        bad.append(f'`gateOpen` 的定义有 {n_def} 处（必须恰好 1 处）')

    # **每个有 gate 形参的钩子函数都必须至少有一个 gateOpen 调用**。
    #
    # 这一条是今天补的：上一版只查"调用点都在回调里"，结果"把回调里的那一行删掉"
    # 反而让门禁变绿（调用数从 6 变 5，两边一起少了一个）。
    # ⇒ 必须有一个**独立于调用数的下界**。
    for fn_name, params in re.findall(
            r'fun (hook\w*)\((.*?)\): (?:Boolean|Int)', src, re.S):
        if 'gate: String? = null' not in params:
            continue
        # 取这个函数的**整个函数体**（用大括号配平，而不是正则 —— 正则遇到
        # 嵌套大括号就会提前收尾，那正是第一版漏掉调用点的原因）。
        start = src.index(f'fun {fn_name}(')
        brace = src.index('{', start)
        depth = 0
        i = brace
        while i < len(src):
            if src[i] == '{':
                depth += 1
            elif src[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = src[brace:i]
        # **每个回调都要判**，不是"函数体里至少出现一次"。
        #
        # 第一版写成"函数体里出现过 gateOpen 就算过"，于是
        # `hook` 的两个回调（before/after）里删掉**一个**仍然绿 ——
        # 因为另一个还在。**判据的粒度比它以为的粗。**
        n_cb = len(re.findall(r'override fun \w*HookedMethod\s*\(', body))
        n_gate = body.count('gateOpen(gate)')
        if n_gate < n_cb:
            bad.append(f'`{fn_name}` 有 {n_cb} 个回调，但只判了 {n_gate} 次 gate '
                       f'⇒ 少判的那个回调装了之后永远按"开"处理')

    # 每个调用点必须在某个 `override fun ...HookedMethod` 体内
    inside = []
    depth = 0
    in_hook = False
    hook_depth = 0
    for i, l in enumerate(lines, 1):
        if re.search(r'override fun \w*HookedMethod\s*\(', l):
            in_hook = True
            hook_depth = depth
        if in_hook and CALL_RX.search(l):
            inside.append(i)
        depth += l.count('{') - l.count('}')
        if in_hook and depth <= hook_depth and l.strip() == '}':
            in_hook = False
    n_call = len(CALL_RX.findall(src))
    if len(inside) != n_call:
        bad.append(f'{n_call - len(inside)} 处 `gateOpen` 调用不在钩子回调体内 '
                   f'（调用 {n_call} 处、在回调内 {len(inside)} 处）')

    print(f'[gatepred] 抄开的判据 {n_spread} 次；gateOpen 定义 {n_def} 处；'
          f'调用 {n_call} 处（在回调内 {len(inside)} 处）')
    for b in bad:
        print(f'  ✗   {b}')
    if bad:
        print('[gatepred]   修法：判据只许写在 `Xp.gateOpen(gate)` 一处，'
              '调用点必须在钩子回调的首行。')
        print('[gatepred]   症状很轻：开关是关的，App 侧行为完全不变 —— **不报错**。')
        return 1
    if a.verbose:
        print('[gatepred] gate 判据只有一处且都在回调里 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
