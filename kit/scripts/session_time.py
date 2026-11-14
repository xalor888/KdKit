#!/usr/bin/env python3
"""
kuaidui-kit / session_time.py — 会话时间的**单一来源**（2026-10-12）。

由来：本会话**两次**把"已运行时长"手写错 ✗（R270 ✓、R314 ✓）。
⇒ 把时间做成文件 ✓，文档一律引用它 ✓。

    python3 kit/scripts/session_time.py            # 刷新 work/SESSION_TIME.json 并打印一行
    python3 kit/scripts/session_time.py --print    # 只打印，不写
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = datetime.datetime(2026, 10, 11, 17, 0)      # 会话起点（首批设备日志 ✓）
OUT = os.path.join(ROOT, 'work', 'SESSION_TIME.json')



def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--print', action='store_true')
    a = ap.parse_args(argv[1:])
    now = datetime.datetime.now()
    hrs = (now - START).total_seconds() / 3600
    doc = {
        'start': START.strftime('%Y-%m-%d %H:%M'),
        'now': now.strftime('%Y-%m-%d %H:%M'),
        'elapsed_hours': round(hrs, 1),
        'elapsed_days': round(hrs / 24, 2),
        '_comment': '会话时间的唯一来源 ✓ —— 文档写时长一律引用这里 ✓，不手写 ✗（本会话已错两次 ✗）',
    }
    if not a.print:
        json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"[time] 已运行 {doc['elapsed_hours']} 小时（{doc['elapsed_days']} 天）")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
