#!/usr/bin/env python3
"""
kuaidui-kit / page_internals.py — 页面的"内部结构"快照（Vue 方法名 + 是否在页面侧）。

2026-10-12 发现的观测维度：模块功能 `page_js` 能让页面执行任意 JS ⇒ 于是可以从**外部**读出
每个页面的 **Vue 根组件方法名**。这解决一个常见判断："某功能在页面侧还是原生侧" ——
页面侧的方法名里会有对应的渲染/事件入口；如果没有，那它就在原生层。

    python3 kit/scripts/page_internals.py --adb emulator-5558 [--steps "AI写作" --steps "批作文"]

产物：`work/PAGE_INTERNALS.md`（每页一行方法名 + 与上次快照的差异）。
注意：它会**改写**配置通道里的 `page_js_script`（这是该能力的用法），并需要页面重新加载才生效。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PROBE = ('(function(){var U=location.href.split("?")[0].split("/").pop();try{var r=document.querySelector("#app")'
         '||document.body.firstElementChild;var v=r&&r.__vue__;if(v){var m=Object.keys(v).filter(function(k){'
         'return typeof v[k]==="function";}).filter(function(k){return k.indexOf("$")!==0&&k!=="_c";});'
         'console.log("[KdKit] PAGE="+U+" VUE="+m.length+" :: "+m.join(","));}else{console.log("[KdKit] PAGE="+U+" VUE=none");}}'
         'catch(e){console.log("[KdKit] PAGE="+U+" VUE=err");}})();')


def sh(cmd, timeout=900):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='replace', timeout=timeout, start_new_session=True)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--steps', action='append', default=None,
                    help='驱动路径（可多次，默认 AI写作 → 批作文）')
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'PAGE_INTERNALS.md'))
    a = ap.parse_args(argv[1:])

    steps = a.steps if a.steps else ['AI写作', '批作文']
    sh(f'python3 {HERE}/call_page_js.py --adb {a.adb} --js {json.dumps(PROBE)}')
    sh(f'adb -s {a.adb} logcat -c')
    sh(f'adb -s {a.adb} shell am force-stop com.kuaiduizuoye.scan')
    sh(f'adb -s {a.adb} shell am start -n com.kuaiduizuoye.scan/.AliasActivityDefault')
    import time
    time.sleep(16)
    for s in steps:
        sh(f'python3 {HERE}/tap_texts.py --adb {a.adb} --steps "{s}" --wait 13')
    time.sleep(8)

    rc, log = sh(f'adb -s {a.adb} logcat -d')
    pages = {}
    for m in re.finditer(r'KdKit\] PAGE=(\S+) VUE=(\d+|none|err) :: ?([^\n"]*)', log):
        name, n, methods = m.group(1), m.group(2), m.group(3).strip().rstrip(',')
        if name not in pages or pages[name]['n'] in ('none', 'err', '0'):
            pages[name] = {'n': n, 'methods': [x for x in methods.split(',') if x]}

    prev = {}
    if os.path.exists(a.out):
        for m in re.finditer(r'\| `([^`]+)` \| (\d+) \| ([^|]*)\|', textio.read_text(a.out, encoding='utf-8')):
            prev[m.group(1)] = m.group(3).strip()

    out = ['# 页面内部结构快照（Vue 方法表）', '',
           f'* {datetime.now().strftime("%Y-%m-%d %H:%M")}　设备 `{a.adb}`；驱动路径：{" → ".join(steps)}',
           '* 来源：模块功能 `page_js` 注入探针 → 读页面 Vue 根组件的方法名（`work/PAGE_API_SURFACE.md` 追加十四）',
           '* **读法**：页面侧功能会在方法名里留下渲染/事件入口；**读不到** ⇒ 该功能在**原生侧**', '',
           '| 页面 | 方法数 | 方法名 |', '|---|---|---|']
    for name, d in sorted(pages.items(), key=lambda kv: -len(kv[1]['methods'])):
        out.append(f'| `{name}` | {len(d["methods"])} | {", ".join(d["methods"][:24])} |')
    changed = [n for n in pages if n in prev and prev[n] != ', '.join(pages[n]['methods'][:24])]
    out += ['', ('**与上次快照相比有变化的页面**：' + '、'.join(f'`{c}`' for c in changed)) if changed
            else '**与上次快照相比：无变化**（或首次运行）', '']
    textio.write_text(a.out, '\n'.join(out) + '\n')
    print(f'[internals] -> {a.out}（{len(pages)} 页）')
    for name, d in sorted(pages.items(), key=lambda kv: -len(kv[1]['methods']))[:4]:
        print(f'   {name}: {len(d["methods"])} 个方法')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
