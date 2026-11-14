#!/usr/bin/env python3
"""
kuaidui-kit / milestones.py — 从轮次日志里抽出"真正的转折点"，做成一页。

`REPORT.md` 的时间线是**每轮一句话**（94 行，全）；这页只挑**改变了认知或路线**的那些轮：
冻结了某个等式、做出了判决性实验、拿到负结论、收口了未解项、或修掉了会反复咬人的工具缺陷。
挑选规则写在 KEY 里，所以它随日志自动更新，不会变成一份手抄的清单。

    python3 kit/scripts/milestones.py [--out work/MILESTONES.md]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# 判断"这一轮是不是转折点"的关键词（出现在**轮次标题或结论段**里）
KEY = ('冻结', '判决', '闭环', '逐字节', '一致', '负结论', '收口', '撤回', '首次', '首见',
       '崩溃', '卡死', '恢复', '扯平', '完全一致', '0 次', '0 条', '全绿', '铁证', '纠')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    rm = open(os.path.join(ROOT, 'ROADMAP.md'), encoding='utf-8').read()
    secs = re.split(r'^### ', rm, flags=re.M)[1:]
    rows = []
    for sec in secs:
        head, _, body = sec.partition('\n')
        m0 = re.match(r'(R\d+)', head.strip())      # 标题可能是 "R2 追加（同一轮下半场）：…"，只取轮号
        rid = m0.group(1) if m0 else head.strip()[:12]
        title = head.split('：', 1)[-1].strip() if '：' in head else head.strip()
        concl = ''
        m = re.search(r'\*\*结论\*\*[：:]\s*(.+?)(?:\n\n|\Z)', body, re.S)
        if m:
            concl = re.sub(r'\s+', ' ', m.group(1)).strip()
        if not concl:                                 # 没有"结论"段的轮次：退而取最后一段正文
            paras = [re.sub(r'\s+', ' ', x).strip() for x in body.split('\n\n') if x.strip()]
            tail = [x for x in paras if not x.startswith('|') and not x.startswith('#')]
            concl = tail[-1][:150] if tail else ''
        hit = [k for k in KEY if k in title or k in concl]
        if hit:
            rows.append((rid, title, concl[:150], hit[0]))

    out = ['# 转折点（从轮次日志里自动挑出来的）', '',
           f'* 共 {len(secs)} 轮，其中**{len(rows)} 轮改变了认知或路线**（挑选关键词：{"、".join(KEY[:8])}…）',
           '* 每行给"这一轮改变了什么"；完整逐轮见 `ROADMAP.md`，一句话版见 `REPORT.md` §12。',
           '* **注意**：结论用的是**当时**的措辞 —— 后续轮次可能更新过它（例如 R15 的"绝对 URL 未见限制"',
           '  在 R66 被量化成"1106 次调用、绝对 URL 0"，并以后者为准）。要当前口径请看 `REPORT.md` / `work/TRIAGE.md`。', '',
           '| 轮次 | 主题 | 改变 / 结论 |', '|---|---|---|']
    for rid, title, concl, _hit in rows:
        out.append(f'| **{rid}** | {title[:40]} | {concl} |')
    out += ['', '**怎么用**：想快速了解"这个项目凭什么说自己做完了什么"，读这一页；想核对细节，顺着轮次号回 `ROADMAP.md`。', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'MILESTONES.md')
    open(target, 'w').write(text)
    print(f'[milestones] -> {target}（{len(rows)}/{len(secs)} 轮入选）')
    print('\n'.join(out[4:16]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
