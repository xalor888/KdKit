#!/usr/bin/env python3
"""
kuaidui-kit / handover_refresh.py — 交接说明的表头与规模快照刷新（**安全版** ✓，2026-10-12）。

由来 ✗：本会话用"**从 `## 3.3 规模快照` 到 `## 3.3g`**"的**区间替换**刷新快照 ✓，
而**夹在这两个锚点之间的段落**（3.3b/c/h/i/j/k ✓）被**连带删掉** ✗（**6 段** ✓）。
⇒ 改为**只替换 `## 3.3 规模快照` 这一节本身** ✓：
   从该标题起，到**下一个 `^## ` 标题**为止 ✓ —— **绝不跨节** ✓。

    python3 kit/scripts/handover_refresh.py
"""
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAND = os.path.join(ROOT, 'work', 'HANDOVER.md')
TIME = os.path.join(ROOT, 'work', 'SESSION_TIME.json')


def counts():
    tools = len([f for f in os.listdir(os.path.join(ROOT, 'kit', 'scripts')) if f.endswith(('.py', '.sh'))]) \
        + len([f for f in os.listdir(os.path.join(ROOT, 'kit', 'python')) if f.endswith('.py')])
    packs = len([d for d in os.listdir(os.path.join(ROOT, 'work', 'packs'))
                 if os.path.isdir(os.path.join(ROOT, 'work', 'packs', d))])
    exports = len([f for f in os.listdir(os.path.join(ROOT, 'work', 'exports')) if f.endswith(('.csv', '.json'))])
    enums = len(json.load(open(os.path.join(ROOT, 'work', 'exports', 'param_enums.json'), encoding='utf-8')))
    meth = len([l for l in open(os.path.join(ROOT, 'work', 'METHODOLOGY.md'), encoding='utf-8') if l.startswith('## ')])
    return tools, packs, exports, enums, meth


def main(argv):
    # **不接受任何参数**（2026-11-02 加）。
    #
    # 旧实现完全不看 `argv`：多打一个 `--bogus` 也照样 rc=0。
    # 而这两个工具都是"验证/刷新"类 —— 参数写错却返回成功，
    # 读的人会以为"核对过了"，实际**一次都没核对**。
    # 这和 `recover_device.sh` 静默忽略位置参数是同一类问题：
    # **静默忽略用户的输入，比报错危险得多**。
    if argv[1:]:
        sys.stderr.write('%s：本工具不接受参数，收到 %s\n' % (os.path.basename(argv[0]), argv[1:]))
        return 2

    t = json.load(open(TIME, encoding='utf-8'))          # 时间一律引自这里 ✓
    tools, packs, exports, enums, meth = counts()
    s = open(HAND, encoding='utf-8').read()
    # ① 标题与"生成于"行
    s = re.sub(r'^# 交接说明（[^\n]*）$',
               '# 交接说明（会话第 ' + str(round(t['elapsed_hours'])) + ' 小时 · 更新至第 ' + str(t.get('round', '')) + ' 轮）',
               s, count=1, flags=re.M)
    # **别再把负数当"还需"**（2026-11-02 修）：`session_time.py` 的截止时间
    # 一度推算出过去，于是这里写出"还需 **-367** 小时"，而交接文档是**给人看的** ——
    # 一个负数不会让任何人警觉，只会被读成"快到了"。
    if t.get('past_deadline'):
        tail = ('已超过截止 **' + str(-t['remaining_hours']) + ' 小时** ⇒ '
                '该停下来做收尾，不该再开新项')
    else:
        tail = '还需 **' + str(t['remaining_hours']) + ' 小时**'
    s = re.sub(r'^> 生成于[^\n]*$',
               '> 生成于 **' + t['now'] + '** ✓（**取自 `work/SESSION_TIME.json`** ✓ —— 单一来源 ✓）；起点 **'
               + t['start'] + '** ✓ ⇒ 已运行 **' + str(t['elapsed_hours']) + ' 小时**（' + str(t['elapsed_days'])
               + ' 天）✓；截止 **' + str(t.get('deadline', '?')) + '**（来源 '
               + str(t.get('deadline_source', '?')) + '）⇒ ' + tail + ' ✓。',
               s, count=1, flags=re.M)
    # ② 只替换 `## 3.3 规模快照` **这一节**（到下一个 ^## 为止 ✓，绝不跨节 ✓）
    body = (f"## 3.3 规模快照（数字由文件统计得出 ✓）\n\n"
            f"| 项 | 值 |\n|---|---|\n"
            f"| kit 工具/脚本 | **{tools}** |\n"
            f"| 证据包目录 | **{packs}** |\n"
            f"| 内容导出 | **{exports} 份文件** ✓ |\n"
            f"| 枚举索引 | **{enums} 组** ✓ |\n"
            f"| 方法论规则 | **{meth} 节** ✓ |\n\n")
    m = re.search(r'^## 3\.3 规模快照[^\n]*\n(?:.*?\n)*?(?=^## |\Z)', s, flags=re.M | re.S)
    if not m:
        print('[handover] 找不到 `## 3.3 规模快照` 节 ✗')
        return 1
    span_before = m.group(0)
    other_heads = re.findall(r'^## ', span_before, flags=re.M)
    if len(other_heads) != 1:
        print(f'[handover] 快照节里含 {len(other_heads)} 个标题 ✗ —— 拒绝替换 ✓（防再删别段 ✗）')
        return 1
    s = s[:m.start()] + body + s[m.end():]
    open(HAND, 'w', encoding='utf-8').write(s)
    print(f'[handover] 已刷新 ✓（工具 {tools} / 包 {packs} / 导出 {exports} / 枚举 {enums} / 方法论 {meth}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
