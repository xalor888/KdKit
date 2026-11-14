#!/usr/bin/env python3
"""
kuaidui-kit / catalog.py — "这个项目到底产出了什么" 的一张清单（按产物类型，而不是按文件名）。

`work/INDEX.md` 回答"某个文件在哪"；这张表回答"哪几类东西、各多少、哪些是自动生成的"。
生成方式与角色都由路径判断，因此不需要人维护。

    python3 kit/scripts/catalog.py [--out work/CATALOG.md]
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SKIP = {'apktool_out', 'jadx_out', '.git', '__pycache__', 'build', '.gradle', 'node_modules'}

# (类别, 匹配函数, 一句话说明, 是否自动生成)
RULES = [
    ('工具（kit/scripts）', lambda p: p.startswith('kit/scripts/'),
     '环境/验收/驱动/报告类脚本', False),
    ('工具（kit/python）', lambda p: p.startswith('kit/python/'),
     '密码学与协议工具', False),
    ('native 预言机', lambda p: p.startswith('kit/harness/'),
     'NDK oracle：直接调 libbaseutil 的 expand/xform', False),
    ('模块源码', lambda p: p.startswith('module/') and p.endswith(('.kt', '.java', '.c', '.xml')),
     'KdKit（Xposed/Vector 模块）', False),
    ('模块产物', lambda p: p.startswith('module/') and p.endswith(('.apk', '.so')),
     '可安装 APK / 随包 native 库', False),
    ('结论与文档', lambda p: p in ('README.md', 'REPORT.md', 'ROADMAP.md', 'kit/MANUAL.md',
                                    'kit/ONBOARDING.md', 'kit/README.md', 'module/README.md',
                                    'module/VERIFICATION.md', 'work/TRIAGE.md', 'work/API_SURFACE.md',
                                    'work/API_LOGIN_MAP.md', 'work/DECISIONS.md', 'work/ARCHIVE.md',
                                    'work/HANDOVER.md', 'work/HEALTH.md', 'work/native_reversal.md',
                                    'work/native_groundtruth.md'),
     '人读的结论 / 交接 / 决策', False),
    ('索引与汇总', lambda p: p in ('work/INDEX.md', 'work/CATALOG.md', 'work/GUEST_API_SWEEP.md',
                                   'work/GUEST_API_HEALTH.md') or p.startswith('work/DAILY-'),
     '自动生成的索引/日报/快照', True),
    ('每轮证据包', lambda p: p.startswith('work/packs/'),
     '每轮一条命令产出（抓取/报告/验收 JSON/基线…）', True),
    ('历轮证据', lambda p: p.startswith('work/dpsdk/'),
     '按轮次的原始证据（抓取/日志/截图/JSON）', False),
    ('历史实验（frida hooks）', lambda p: p.startswith('kit/hooks/'),
     '早期 Frida 实验脚本（保留作历史）', False),
    ('设备/构建基础设施', lambda p: p.startswith('infra/'),
     'magisk ramdisk 与设备侧脚本', False),
]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    buckets = defaultdict(lambda: {'n': 0, 'bytes': 0, 'desc': '', 'auto': False, 'dirs': set()})
    total_n = total_b = 0
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for fn in files:
            p = os.path.relpath(os.path.join(root, fn), ROOT)
            if p.startswith('com.kuaiduizuoye') and p.endswith('.apk'):
                continue                     # 输入样本，不算产物
            try:
                sz = os.path.getsize(os.path.join(root, fn))
            except OSError:
                continue
            total_n += 1
            total_b += sz
            for name, pred, desc, auto in RULES:
                try:
                    if pred(p):
                        b = buckets[name]
                        b['n'] += 1; b['bytes'] += sz; b['desc'] = desc; b['auto'] = auto
                        b['dirs'].add(os.path.dirname(p) or '.')
                        break
                except Exception:
                    pass

    out = ['# 产出清单（按类型）', '',
           f'* 生成：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}（`kit/scripts/catalog.py`）',
           f'* 工作区总计：{total_n} 个文件、{total_b / 1024 / 1024:.1f} MB（不含两棵反编译树与 APK 样本）', '',
           '| 类别 | 数量 | 体积 | 自动生成 | 说明 | 主要目录 |', '|---|---|---|---|---|---|']
    for name, b in sorted(buckets.items(), key=lambda kv: -kv[1]['n']):
        dirs = ', '.join(sorted(d for d in b['dirs'])[:3]) or '-'
        out.append(f"| {name} | {b['n']} | {b['bytes'] / 1024:.0f} KB | "
                   f"{'是' if b['auto'] else '否'} | {b['desc']} | `{dirs}` |")
    out += ['', '## 怎么补/怎么重生成', '',
            '* **自动生成**的（索引、日报、健康页、功能矩阵、证据包、时间线）都能一条命令重建：',
            '  `python3 kit/scripts/evidence_pack.py --adb <serial> --tag <tag>` 会刷新其中大部分；',
            '  `python3 kit/scripts/index_evidence.py` / `daily_report.py` / `feature_matrix.py` 可单独跑；',
            '* **人写的**（结论/决策/交接）只在这些地方改：`REPORT.md`、`work/TRIAGE.md`、`work/DECISIONS.md`、`work/HANDOVER.md`；',
            '* **历轮原始证据**只增不改（归档见 `work/ARCHIVE.md`）。', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'CATALOG.md')
    open(target, 'w').write(text)
    print(f'[catalog] -> {target}')
    print(out[3])                      # 总计行（证据包会解析它，别只打印表格）
    print('\n'.join(out[4:16]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
