#!/usr/bin/env python3
"""
kuaidui-kit / drift_report.py — 三张"有没有变"的面，合成一页。

三个监控各有分工，平时分散在三个工具里；这页把它们并排，回答一个每天都在问的问题：
**"今天有没有什么东西变了？"**

  * 客户端请求面  `path_diff --check-baseline`   → 基线 `work/baselines/path_aiwriting.json`
  * 服务端响应形状 `server_shape`                → 基线 `work/baselines/server_shape.json`
  * 结论的输入身份 `verify_inputs`               → 基线 `work/baselines/input_hashes.json`

    python3 kit/scripts/drift_report.py --adb emulator-5558 [--with-path-diff] [--out work/DRIFT.md]

**合法变更怎么接受**（三张面都一样）：确认变化是我们自己造成的（换样本 / 服务端改版 / 客户端升级）之后，
重建对应基线 —— 换样本要重建**三张**（输入变了，形状与请求面很可能也变）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
B = os.path.join(ROOT, 'work', 'baselines')


def run(cmd, timeout=900):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='replace',
                           timeout=timeout, start_new_session=True)
    except subprocess.TimeoutExpired:
        return 1, 'TIMEOUT'
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def baseline_age(path):
    if not os.path.exists(path):
        return '缺失', 0
    d = datetime.fromtimestamp(os.path.getmtime(path))
    return d.strftime('%m-%d %H:%M'), os.path.getsize(path)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--with-path-diff', action='store_true', help='连客户端请求面一起跑（约 3 分钟）')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rows = []

    # 1 服务端形状
    rc, out = run(f'python3 {HERE}/server_shape.py --adb {a.adb}')
    m = re.search(r'形状变化 (\d+) 条', out)
    rows.append(('服务端响应形状', os.path.join(B, 'server_shape.json'),
                 ('一致' if (m and m.group(1) == '0') else (f'**变化 {m.group(1)} 条**' if m else '**跑不通**')),
                 '`server_shape.py --adb <serial> --save`'))

    # 2 输入身份
    rc, out = run(f'python3 {HERE}/verify_inputs.py')
    ok = '一致' if rc == 0 and '一致' in out else '**有变化**'
    rows.append(('结论的输入身份', os.path.join(B, 'input_hashes.json'), ok,
                 '`verify_inputs.py --save`'))

    # 3 客户端请求面（可选：慢）
    bp = os.path.join(B, 'path_aiwriting.json')
    if a.with_path_diff and os.path.exists(bp):
        rc, out = run(f'python3 {HERE}/path_diff.py --adb-a {a.adb} --adb-b {a.adb} '
                      f'--steps "AI写作" --repeat 2 --check-baseline {bp}', timeout=1200)
        m = re.search(r'baseline check: \+(\d+) -(\d+) params~(\d+)', out)
        val = ('一致' if (m and m.group(1) == '0' and m.group(2) == '0')
               else (f'**+{m.group(1)} -{m.group(2)} 参数变{m.group(3)}**' if m else '**跑不通**'))
        rows.append(('客户端请求面', bp, val, '`path_diff.py … --save-baseline ' + bp + '`'))
    else:
        rows.append(('客户端请求面', bp, '未跑（加 `--with-path-diff`）',
                     '`path_diff.py … --save-baseline ' + bp + '`'))

    text = ['# 漂移面板（三张面）', '',
            f'* 生成：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}（`kit/scripts/drift_report.py`）',
            f'* 设备：`{a.adb}`', '',
            '| 面 | 状态 | 基线 | 基线时间 | 接受合法变更 |', '|---|---|---|---|---|']
    for name, bp_, val, how in rows:
        age, size = baseline_age(bp_)
        text.append(f'| {name} | {val} | `{os.path.relpath(bp_, ROOT)}` | {age} | {how} |')
    text += ['', '**怎么读**：三张面全"一致"= 今天的结论与建立基线时所说的还是同一件事。',
             '任何一张显示变化，先判断它是**我们造成的**（换样本/升级客户端）还是**对方改的**（服务端改版）；',
             '前者重建基线，后者要回头检查受影响的结论。', '']
    out_text = '\n'.join(text) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'DRIFT.md')
    open(target, 'w').write(out_text)
    print(f'[drift] -> {target}')
    # 机器可读的一行（证据包把它放进健康页，和四道门并列）
    print('[drift] 面状态: ' + '；'.join(f'{name}={val}' for name, _b, val, _h in rows))
    print('\n'.join(text[4:9]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
