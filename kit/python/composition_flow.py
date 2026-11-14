#!/usr/bin/env python3
"""
kuaidui-kit / composition_flow.py — "AI 写作文"链路的**前四步**，离线一键跑完并留证。

这四步在 2026-10-12 逐条验证过（`work/PAGE_API_SURFACE.md`），形状**照抄页面**
（`writeCheck` 用 JSON body；`preInstantWriting` 用 query + body；`cungongRefresh` 是 GET；
`writingintent` 用页面原样 JSON body）。**不需要设备、签名或登录票据** —— 只要页面上下文的几个头。

    python3 kit/python/composition_flow.py --adb emulator-5558 --title "SummerVacation" --out work/packs/r139/flow.json

第五步（`instantWriting`，SSE 流式生成）**在登录分支之后**，游客态下页面连那段代码分片都不会取 ——
所以这个脚本**止步于第四步**，并把第五步为何做不了写进输出（不假装成功）。

退出码：0 = 四步全成功；2 = 有步骤失败；3 = 第五步（生成）不可达（登录分支，当前预期状态）。
"""
import argparse
import net
import glob
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import sh as shmod
import captures
from pageapi import base_headers  # noqa: E402

BASE = 'https://api.kuaiduizuoye.com/aiwriting/ai/composition/'


def cuid_from_captures():
    """从最近的抓取里找 cuid；找不到返回 None。

    2026-11-03：原来只 glob `capture*.txt` 并用 `open()` 读 ——
    `pack_slim` 把旧包压成 `.txt.gz` 之后，那些抓取**静默消失**，
    而这个函数只会返回 None，看不出是"没有 cuid"还是"没读到包"。
    现在走 `captures.iter_captures()`（两种形态都认）。
    """
    for c in captures.iter_captures()[:8]:
        got = captures.find_cuid(c)
        if got:
            return got
    return None


def call(path, body=None, method=None, cuid=None, timeout=35):
    h = base_headers(cuid)
    req = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=net.ssl_context()) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')[:200]
    except Exception as e:
        return 'ERR', f'{type(e).__name__}: {e}'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=None)
    ap.add_argument('--title', default='SummerVacation')
    ap.add_argument('--grade', type=int, default=13)
    ap.add_argument('--word-count', default='300-400')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    cuid = cuid_from_captures()
    if a.adb and not cuid:
        # 2026-11-03 代码审查 P2-18：原来用 `os.popen(f'adb -s {a.adb} …')`。
        # 三个问题：
        #   ① **没有 timeout** —— 设备不在线时永久挂住，整条流水线跟着卡死；
        #   ② `--adb` 的值**直接拼进 shell**，值里带空格/引号会改掉命令本身；
        #   ③ 不过 `sh()`，拿不到进程组超时（2026-11-02 实测泄漏过 `adb`）。
        # 改用 `sh.run()`：有界、可杀、并把 `--adb` 作为一个**参数**传下去。
        rc, out = shmod.run(f'adb -s {shmod._quote(a.adb)} shell '
                            f'"grep -o cuid=[0-9A-F]* '
                            f'/data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt | head -1"',
                            timeout=60)
        cuid = out.split('=', 1)[1] if '=' in out else None
    if not cuid:
        print('[flow] 找不到 cuid —— 用 --adb 或先跑一次证据包（抓取里有）')
        return 2

    steps, ok_all = [], True
    st, b = call('writeCheck', json.dumps({"hybrid": 1, "cuid": cuid, "title": a.title, "describe": "",
                                           "sid": "", "source": 1, "language": 1}).encode(), cuid=cuid)
    sess = {}
    try:
        sess = json.loads(b).get('data', {})
    except Exception:
        pass
    ok = bool(st == 200 and sess.get('sid'))
    ok_all &= ok
    steps.append(('writeCheck', st, bool(ok), f"sid={str(sess.get('sid'))[:12]}…"))

    sid, sn = sess.get('sid', ''), sess.get('sessionId', '')
    q = (f"uid=&gradeId={a.grade}&sid=&queryType=5&title={a.title}&wordCount={a.word_count}"
         f"&language=Chinese&isDefaultTitle=2")
    st, b = call('preInstantWriting?' + q,
                 json.dumps({"hybrid": 1, "cuid": cuid, "sid": sid, "sessionId": sn,
                             "gradeId": a.grade, "title": a.title, "wordCount": a.word_count,
                             "source": 1, "language": 1}).encode(), cuid=cuid)
    ok = bool(st == 200 and '"errNo":0' in b)
    ok_all &= ok
    steps.append(('preInstantWriting', st, ok, b[:80]))

    st, b = call(f'cungongRefresh?hybrid=1&sid={sid}&sessionId={sn}', None, 'GET', cuid)
    ok = bool(st == 200 and '"errNo":0' in b)
    ok_all &= ok
    steps.append(('cungongRefresh (GET)', st, ok, b[:80]))

    st, b = call('writingintent', json.dumps({"hybrid": 1, "pageFrom": "标题输入页", "adid": cuid, "cuid": cuid,
                                              "needAnti": [], "sid": "", "title": a.title,
                                              "gradeId": a.grade}).encode(), cuid=cuid)
    d = {}
    try:
        d = json.loads(b).get('data', {})
    except Exception:
        pass
    ok = bool(st == 200 and d.get('sid'))
    ok_all &= ok
    steps.append(('writingintent', st, ok,
                  f"pageTo={d.get('pageTo')} 新会话 sid={str(d.get('sid'))[:12]}…"))

    print(f'[flow] cuid={cuid[:18]}…  title={a.title!r}')
    for name, code, ok, detail in steps:
        print(f'  {"✅" if ok else "❌"} {name:24s} HTTP {code}  {detail}')
    print('  ⛔ instantWriting（第五步，SSE 生成）：**在登录分支之后** —— 游客态页面连代码分片都不取，'
          '故本脚本止步于此（不是失败，是权限模型边界）')

    if a.out:
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump([{'step': n, 'http': c, 'ok': o, 'detail': dt} for n, c, o, dt in steps]
                  + [{'step': 'instantWriting', 'http': None, 'ok': False,
                      'detail': 'login-branched: not reachable as a guest'}],
                  open(a.out, 'w'), ensure_ascii=False, indent=1)
        print(f'[flow] -> {a.out}')
    return 0 if ok_all else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
