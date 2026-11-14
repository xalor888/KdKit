#!/usr/bin/env python3
"""
kuaidui-kit / check_hook_gated.py — **`hot = true` 的功能，每条钩子都必须能被关掉**。

### 为什么需要

`BaseFeature.enable()` 的判据是：

    if (!hot && !shouldRun()) { "feature off"; return }

⇒ **`hot = true` 的功能绕过配置检查，无论如何都会装钩子。**
注册表里有 37 个 hot 功能，所以"关掉一个功能"几乎总是靠**回调里判配置**。

2026-11-04 找到 `AntiDetect`：`hot = true`，四个钩子，**文件里既没有 `gate =`
也没有 `KdConfig.isOn`**。它把 `isDebuggerConnected()` / `TracerPid` / `FLAG_DEBUGGABLE`
统统改成 false —— 用户把 `antidetect` 关掉之后，**它照样在骗 App**。

症状：UI 上开关是关的，App 侧行为完全不变。**不报错，只是开关没用。**

### 判据

对每个 `features/**/*.kt`：

1. 文件里有 `hot = true` ⇒ 它是 hot 功能；
2. 文件里有 `Xp.hook(` / `Xp.hookAll(` / `Xp.hookCtor(` 这类调用；
3. **每一条**这样的调用，在其后 `WINDOW` 行内必须出现 `gate =` 或 `KdConfig.isOn`。

第 3 条**第一版用的是"全文件出现一次就算过"**，而负对照当场证明了它太粗：
把 `AntiDetect` 四个钩子里**一个**的 `gate = id` 删掉，文件里还剩另外两个 + 一个
`isOn` ⇒ 检查器照样绿。**判据的粒度比它以为的粗** —— 今天第 12 次。

改成逐调用看一个窗口：`hook()` / `hookAllBefore()` / `hookAllAfter()` 的 `gate =`
写在同一个调用里；`hookAll()` 没有 gate 形参，`isOn` 写在回调前几行 —— 窗口都覆盖得到。

`Xp.hookAllBefore` / `Xp.hookAllAfter` 有 `gate` 形参；
`Xp.hook` / `Xp.hookAll` / `Xp.hookCtor` 里只有 `hook` 有。

### 退出码

0 = 每条 hot 功能都能被关掉；1 = 有 hot 功能关不掉。
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FEATURES = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev',
                        'xalor', 'kdkit', 'features')

HOOK_RX = re.compile(r'Xp\.(hook|hookAll|hookAllBefore|hookAllAfter|hookCtor)\s*\(')

#: 一个钩子调用往后看多少行算"它自己的作用域"。
#:
#: 12 行覆盖了最长的形态：`Xp.hookAll(..., cb = object : XC_MethodHook() {` +
#: `override fun beforeHookedMethod` + `if (!KdConfig.isOn(...)) return`。
WINDOW = 12
GATE_RX = re.compile(r'gate\s*=|KdConfig\.isOn\(')

#: Kotlin 注释。**必须先剥掉再判**（2026-11-04 的负对照就是这么失败的）：
#: 我在 `AntiDetect` 里写了一段解释"为什么必须传 `gate = id`"的注释，
#: 而 `GATE_RX` 从注释里匹配到了那个字符串 ⇒ 把功能去掉 gate 之后，
#: 检查器**照样绿**。这和 ㉞ 被自己的 docstring 命中是同一类：
#: **判断器读了它自己的说明文字。**
_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
_LINE_COMMENT = re.compile(r'//[^\n]*')


def strip_comments(src):
    return _LINE_COMMENT.sub('', _BLOCK_COMMENT.sub('', src))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    hot_n = 0
    bad = []
    for p in glob.glob(os.path.join(FEATURES, '**', '*.kt'), recursive=True):
        with open(p, encoding='utf-8', errors='replace') as _f:
            src = strip_comments(_f.read())
        src_lines = src.split('\n')
        if 'hot = true' not in src:
            continue
        hooks = HOOK_RX.findall(src)
        if not hooks:
            continue
        hot_n += 1
        rel = os.path.relpath(p, ROOT)
        # 逐调用检查（见文件头"判据"第 3 条的说明）
        for m in HOOK_RX.finditer(src):
            ln = src.count('\n', 0, m.start())
            win = '\n'.join(src_lines[ln:ln + WINDOW])
            if not GATE_RX.search(win):
                bad.append((f'{rel}:{ln + 1}', [m.group(1)]))

    print(f'[hookgate] hot 功能里有钩子的：{hot_n} 个；关不掉的：{len(bad)} 个')
    for rel, kinds in bad:
        print(f'  ✗   {rel}  {", ".join(kinds)} 这一条既没有 `gate =` 也没有 `KdConfig.isOn`')

    if bad:
        print('[hookgate]   `hot = true` 会**绕过** `BaseFeature.enable()` 的配置检查，'
              '所以"关掉功能"只能靠回调里判配置。')
        print('[hookgate]   修法：给 `Xp.hook(..., gate = id, ...)`；'
              '`hookAll`/`hookCtor` 没有 gate 形参 ⇒ 回调首行写')
        print('[hookgate]         `if (!KdConfig.isOn(id, GatePolicy.defaultFor(id))) return`')
        print('[hookgate]   症状很轻：UI 上开关是关的，App 侧行为完全不变 —— **不报错，只是开关没用**。')
        return 1
    if a.verbose:
        print('[hookgate] 每个 hot 功能的钩子都能被关掉 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
