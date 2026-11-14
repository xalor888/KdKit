#!/usr/bin/env python3
"""
kuaidui-kit / face_board.py — 四个"真机验收面"一张表。

### 为什么需要它

C1（广告）/ C3（会员）/ C2（水印）/ C5（PK）四个面的判据已经分别做成了命令
（`verify_membership.py`、`verify_face.py`），但**四条命令需要有人记得去跑**。
靠"记得"的东西等于不存在 —— 于是每轮收尾都会漏掉其中一两个，
而"这一轮到底验了什么"又变成靠回忆。

这里把它们合成一条命令、一张表，并且写进 `work/FACE_BOARD.md`：

    python3 kit/scripts/face_board.py --adb emulator-5558
    python3 kit/scripts/face_board.py --capture x.txt --logcat-file y.txt --out board.md

### 退出码（和单面脚本同一套语义）

| 码 | 含义 |
|---|---|
| **0** | 四个面**全部**已验证 |
| **2** | 至少一个面无法验证（这是今天最常见的情况，**不是失败**） |
| 1 | 有面自相矛盾 / 工具本身出错 |

**2 与 0 必须分开**：混在一起就会出现"一轮全绿、其实四个面一个都没验"。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable

STATE_CN = {'verified': '已验证', 'blocked': '无法验证', 'unknown': '未知'}
TITLES = {
    'ad': 'C1 广告面',
    'vip': 'C3 会员面',
    'watermark': 'C2 大图页水印',
    'pk': 'C5 口算 PK',
}


def run_one(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=600)
    for line in reversed((p.stdout or '').splitlines()):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                break
    return {'face': '?', 'code': 1, 'state': 'unknown',
            'detail': (p.stderr or p.stdout or '工具没有输出 JSON').strip()[-160:]}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=None)
    ap.add_argument('--capture', default=None)
    ap.add_argument('--logcat-file', default=None)
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'FACE_BOARD.md'))
    a = ap.parse_args(argv[1:])
    if not a.adb and not a.capture:
        ap.error('需要 --adb，或 --capture')

    common = ['--adb', a.adb] if a.adb else []
    if not a.adb:
        common = ['--capture', a.capture]
        if a.logcat_file:
            common += ['--logcat-file', a.logcat_file]

    # 广告面与会员面共用同一个判据（同一份埋点决定"能不能验"），但**结论分开呈现**：
    # 会员看 vip_unlock 有没有生效，广告看广告位读了多少次、拦了多少次。
    rows = []
    rows.append(run_one([PY, os.path.join(HERE, 'verify_membership.py'), *common, '--json']))
    for face in ('watermark', 'pk'):
        rows.append(run_one([PY, os.path.join(HERE, 'verify_face.py'), '--face', face,
                             *common, '--json']))

    # 广告面：复用会员那份结果的 code，但换一个标题与说明（结论来源不同）
    vip = rows[0]
    # C1 的说明用**真实计数**，不用写死的句子（2026-11-02 改）：
    # "读了 132 次、拦了 0 次"与"读了 88 次、拦了 88 次"是两件不同的事 ——
    # 前者是没生效，后者是生效了。`ADBLOCK` 这条证据 R63 才加，之前根本不存在。
    if vip['state'] == 'blocked':
        ad_detail = (f'广告位读 {vip.get("ad_read", "?")} 次 / 拦截生效 '
                     f'{vip.get("ad_blocked", "?")} 次（游客态下通常是空配置，'
                     f'读得到但没有可拦的投放）')
    else:
        ad_detail = vip['detail']
    ad = dict(vip, face='ad', detail=ad_detail)
    rows = [ad] + rows

    print(f'{"面":22s} {"结论":10s} 证据')
    for r in rows:
        title = TITLES.get(r['face'], r['face'])
        state = STATE_CN.get(r['state'], r['state'])
        print(f'{title:22s} {state:10s} {r["detail"]}')

    codes = [r['code'] for r in rows]
    overall = 1 if any(c not in (0, 2) for c in codes) else (0 if all(c == 0 for c in codes) else 2)

    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('# 四张验收面（自动生成）\n\n')
            f.write('* 复现：`python3 kit/scripts/face_board.py '
                    + (f'--adb {a.adb}' if a.adb else f'--capture {a.capture}')
                    + f' --out {os.path.relpath(a.out, ROOT)}`\n')
            f.write('* 结论取值：**已验证**（有生效证据）/ **无法验证**（环境到不了，'
                    '不代表通过）/ **未知**\n\n')
            f.write('| 面 | 结论 | 证据 |\n|---|---|---|\n')
            for r in rows:
                f.write(f'| {TITLES.get(r["face"], r["face"])} | '
                        f'{STATE_CN.get(r["state"], r["state"])} | {r["detail"]} |\n')
            f.write('\n')
            if overall == 2:
                f.write('> 至少一个面**无法验证**。这不是失败，也**不是通过** —— '
                        '它说的是"这台设备测不了这件事"。\n')
            print(f'\n[board] 已写 {os.path.relpath(a.out, ROOT)}')

    print(f'[board] 总判定：{"全部已验证" if overall == 0 else ("有面无法验证" if overall == 2 else "有面异常")}')
    return overall


if __name__ == '__main__':
    sys.exit(main(sys.argv))
