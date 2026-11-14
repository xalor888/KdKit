#!/usr/bin/env python3
"""
kuaidui-kit / check_gate_defaults.py — 「没配置时算不算开」这件事只能有一个答案。

### 它守的是什么

2026-11-01 的 P0：热开关的 gate 回调首行写死 `KdConfig.isOn(gate, true)`，
而设置页**从不预置默认值** ⇒ 24 个 `defaultOn = false` 的功能在用户没点过开关时**照跑**。
其中 7 个会改宿主行为（拦弹窗、解会员、改水印）。修法是把判定收敛到 `GatePolicy.defaultFor(id)`。

修完之后仍有**两处会漂**：

1. 某个功能的回调里又写了字面量（`isOn(id, true)`），与它自己声明的 `defaultOn` 相反 ——
   只要那个钩子哪天不再带 `gate =`，字面量就成了"实际默认值"，P0 原样复现；
2. `HookCore` 灌默认值时写错来源（比如 `it.id to it.hot`）—— 一行改动，19 个默认关的功能全变开。

这条门禁把两处都钉住。当前实测：**0 处不一致**（`defaultOn=true` 的三个功能写的也是 `true`）。

    python3 kit/scripts/check_gate_defaults.py
退出码：0 = 一致；1 = 有不一致 / 找不到关键代码。
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KIT = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit')

ID = re.compile(r'^\s*id\s*=\s*"([\w]+)"', re.M)
DEFAULT_ON = re.compile(r'defaultOn\s*=\s*(true|false)')
#: 回调里对**自己**这个 id 的自查：`isOn(id, X)` 或 `isOn("<own id>", X)`
SELF_CHECK = r'isOn\(\s*(?:id|"{fid}")\s*,\s*(true|false)\s*\)'
#: `HookCore` 里灌默认值的唯一正确写法
INSTALL = re.compile(r'GatePolicy\.install\(\s*FeatureRegistry\.all\.associate\s*\{\s*'
                     r'it\.id\s+to\s+it\.defaultOn\s*\}\s*\)')


def main(argv):
    bad, checked = [], 0

    for path in sorted(glob.glob(os.path.join(KIT, '**', '*.kt'), recursive=True)):
        with open(path, encoding='utf-8') as f:
            src = f.read()
        m_id = ID.search(src)
        m_def = DEFAULT_ON.search(src)
        if not (m_id and m_def):
            continue
        fid, declared = m_id.group(1), m_def.group(1)
        rx = re.compile(SELF_CHECK.format(fid=re.escape(fid)))
        for m in rx.finditer(src):
            checked += 1
            if m.group(1) != declared:
                line = src.count('\n', 0, m.start()) + 1
                bad.append((
                    os.path.relpath(path, ROOT), line, fid, declared, m.group(1),
                    f'`{fid}` 声明 defaultOn={declared}，但回调自查写的是 {m.group(1)}',
                ))

    core = os.path.join(KIT, 'HookCore.kt')
    if not os.path.isfile(core):
        bad.append(('module/.../HookCore.kt', 0, '-', '-', '-', '找不到 HookCore.kt'))
    else:
        with open(core, encoding='utf-8') as f:
            csrc = f.read()
        if not INSTALL.search(csrc):
            bad.append((
                os.path.relpath(core, ROOT), 0, '-', '-', '-',
                '`GatePolicy.install` 没有用 `FeatureRegistry.all.associate { it.id to it.defaultOn }` '
                '—— 默认值的来源被改动了，19 个"默认关"的功能可能全部变开',
            ))

    print(f'[gate-defaults] 检查了 {checked} 处回调自查 + HookCore 的灌入口')
    if bad:
        print(f'[gate-defaults] **{len(bad)} 处不一致**：')
        for rel, line, fid, declared, lit, why in bad:
            print(f'  {rel}:{line}  {why}')
        print('  修法：回调里用 `KdConfig.isOn(id, GatePolicy.defaultFor(id))`，别再写字面量。')
        return 1
    print('[gate-defaults] 一致 ✓（回调自查与 defaultOn 相同，灌入口写法正确）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
