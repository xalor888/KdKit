#!/usr/bin/env python3
"""
kuaidui-kit / version_diff.py — 两个版本的"机制 / 接口面 / 桥注册表"对比，一条命令。

做法：把两份 APK 的 dex 字符串提出来（或直接用已有的快照 `.txt` / `.txt.gz`），然后对比三张表：

  1. **机制标记**：签名 token 存放、`PatchProxy` 热修、`dpsdk`、核心桥、注解生成器、入口密钥片段…
  2. **路径前缀**：`/pluto` `/kdapi` `/aiwriting`…（回答"新增了哪些业务面"）
  3. **桥动作名**：`core_*` 与 `*Action`（回答"桥长了多少、加了什么能力"）

    python3 kit/scripts/version_diff.py --a old.apk --b new.apk --out work/versions/DIFF.md
    python3 kit/scripts/version_diff.py --a work/versions/strings/old.txt.gz \\
        --b work/versions/strings/new.txt.gz          # 用已有快照（最快）

只做**字符串层面**的对比 —— 适合回答"某机制/接口何时出现"；逐条语义演进仍需反编译。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import gzip
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

MARKERS = ['KEY_ANTISPAM_SIGN_A', 'kakorrhaphiophobia', 'RC4Encrypt', 'msyx6nw', 'PatchProxy',
           'dpsdk', 'com/dprotect', 'HybridCoreActionManager', 'ZYBActionFinder', 'yl/f',
           'api.kuaiduizuoye.com', 'log.kuaiduizuoye.com', 'rumt-zh.com']
PREFIXES = ('pluto', 'kdapi', 'kdcore', 'kdchat', 'codesearch', 'session', 'init', 'userident',
            'adxserver', 'activity', 'hegui', 'abengine', 'aiwriting', 'toolcenter', 'cameraSearch')


def load(src):
    """返回 (文本, 来源说明)。支持 .txt/.txt.gz 快照，或直接给 APK（现场抽字符串）。"""
    if src.endswith(('.txt', '.txt.gz')):
        # 与其它四个工具同一个读取器（2026-11-03 收敛到 `textio`）
        return textio.read_text(src), os.path.basename(src)
    tmp = tempfile.NamedTemporaryFile('w+', suffix='.txt', delete=False)
    subprocess.run(f'''unzip -p "{src}" 'classes*.dex' 2>/dev/null | strings -a > {tmp.name}''',
                   shell=True, timeout=900, start_new_session=True)
    txt = open(tmp.name, encoding='utf-8', errors='replace').read()
    os.unlink(tmp.name)
    return txt, os.path.basename(src)


def prefixes(txt):
    return {m.group(1) for m in re.finditer(
        r'(?<![\w/])/(' + '|'.join(PREFIXES) + r')/', txt)}


def actions(txt):
    return set(re.findall(r'\b(core_[A-Za-z0-9_]{3,40}|[a-z][A-Za-z0-9]{5,40}Action)\b', txt))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', required=True, help='旧版（APK 或字符串快照）')
    ap.add_argument('--b', required=True, help='新版（APK 或字符串快照）')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    ta, na = load(a.a)
    tb, nb = load(a.b)
    out = [f'# 版本对比：{na} → {nb}', '', '* 方法：dex 字符串层面（迁移/删除/新增），不做反编译', '']

    out += ['## 1 机制标记', '', '| 标记 | ' + na + ' | ' + nb + ' |', '|---|---|---|']
    for m in MARKERS:
        out.append(f'| `{m}` | {ta.count(m)} | {tb.count(m)} |')

    pa, pb = prefixes(ta), prefixes(tb)
    out += ['', '## 2 路径前缀', '',
            f'* 旧 {len(pa)}｜新 {len(pb)}｜共同 **{len(pa & pb)}**｜旧独有 **{len(pa - pb)}**｜新独有 **{len(pb - pa)}**',
            f'* 新独有：{sorted(pb - pa) or "（无）"}', f'* 旧独有：{sorted(pa - pb) or "（无）"}']

    aa, ab = actions(ta), actions(tb)
    ca, cb = {x for x in aa if x.startswith('core_')}, {x for x in ab if x.startswith('core_')}
    out += ['', '## 3 桥动作', '',
            f'* 旧 {len(aa)}｜新 {len(ab)}｜共同 **{len(aa & ab)}**｜淘汰 **{len(aa - ab)}**｜新增 **{len(ab - aa)}**',
            f'* `core_*`：旧 **{len(ca)}** → 新 **{len(cb)}**',
            '', f'* 新增 `core_*`（最多 12）：{sorted(cb - ca)[:12]}',
            f'* 淘汰 `core_*`（最多 12）：{sorted(ca - cb)[:12]}', '']
    text = '\n'.join(out) + '\n'
    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        open(a.out, 'w').write(text)
        print(f'[vdiff] -> {a.out}')
    print('\n'.join(out[3:10]))
    print(f'[vdiff] 前缀: 共同 {len(pa & pb)} / 新独有 {len(pb - pa)}  |  桥动作: 共同 {len(aa & ab)} / 新增 {len(ab - aa)} / 淘汰 {len(aa - ab)}  |  core_* {len(ca)}→{len(cb)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
