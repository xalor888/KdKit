#!/usr/bin/env python3
"""
kuaidui-kit / session_snapshot.py — freeze the login/session state so a *future* login can be diffed.

We have no account, so the post-login behaviour (收藏 / 错题本 / 支付闭环) cannot be walked today.
What we *can* build is the harness: snapshot everything login-related now, and after a real login run
the same command with `--diff` to see exactly what changed.

Collected per device (no secret values are written — only names, counts, sizes and prefixes):

  * `shared_prefs/*.xml` files whose name matches login/session/user/account/auth/token
  * the WebView cookie store metadata (`app_webview/Default/Cookies`): size + domain histogram
  * `app_webview/Default/` entry list (Session Storage / Local Storage / Web Data …)
  * the guest request state from the capture (`uid=`, `token=` prefix)

    python3 kit/scripts/session_snapshot.py --adb emulator-5558 --out work/session_guest.json
    python3 kit/scripts/session_snapshot.py --adb emulator-5558 --out work/session_after_login.json
    python3 kit/scripts/session_snapshot.py --adb emulator-5558 --diff work/session_guest.json
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
from device import PKG as PKG_CONST
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
D = f'/data/data/{PKG}'
KEYISH = re.compile(r'(login|session|user|account|auth|token|uid|vip)', re.I)


def sh(cmd, timeout=300):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=300):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def snapshot(serial):
    snap = {'device': serial}
    files = adb(serial, f'ls {D}/shared_prefs/')[1].split()
    prefs = {}
    for fn in files:
        if not KEYISH.search(fn):
            continue
        body = adb(serial, f'cat {D}/shared_prefs/{fn}')[1]
        keys = sorted(set(re.findall(r'name="([^"]+)"', body)))
        prefs[fn] = {'bytes': len(body), 'keys': keys[:40],
                     'shape_md5': hashlib.md5(re.sub(r'value="[^"]*"', 'value="*"', body).encode()).hexdigest()[:8]}
    snap['login_prefs'] = prefs

    web = adb(serial, f'ls -la {D}/app_webview/Default/')[1]
    entries = {}
    for line in web.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 7 and parts[-1] not in ('.', '..'):
            entries[parts[-1]] = parts[4]
    snap['webview_default'] = entries
    cookie = adb(serial, f'ls -la {D}/app_webview/Default/Cookies')[1]
    fields = cookie.split()
    # `ls -la` 列序：权限 链接 属主 属组 **大小** 日期… —— 用固定列而不是正则碰运气
    snap['cookie_bytes'] = int(fields[4]) if len(fields) > 4 and fields[4].isdigit() else 0
    dom = adb(serial, f"strings {D}/app_webview/Default/Cookies | grep -aoE '[a-z0-9.-]+\\.(com|cn)' | sort | uniq -c | sort -rn | head -8")[1]
    snap['cookie_domains'] = dict((l.split()[1], int(l.split()[0])) for l in dom.splitlines() if len(l.split()) == 2)

    # 只认后面紧跟分隔符的 uid（否则 `uid=69C8…` 那种 cuid 前缀会被误读成 uid=69）
    cap = adb(serial, f"grep -aoE 'uid=[0-9]+[& |]' {D}/files/kdkit_capture.txt | sort -u | head -5")[1].split()
    # token 值只取"看起来像 token"的字符集，避免把 UA/JSON 片段也扫进来
    tok = adb(serial, f"grep -aoE 'token=[A-Za-z0-9_|.-]{{6,80}}' {D}/files/kdkit_capture.txt | sort -u | head -5")[1].split()
    snap['guest_state'] = {'uid_values': sorted({x.rstrip('& |') for x in cap})[:5],
                           'token_prefixes': sorted({t.split('=')[-1][:12] for t in tok})}
    return snap


def diff(old, new):
    rows = []
    for k in sorted(set(old) | set(new)):
        if k in ('device',):
            continue
        if old.get(k) != new.get(k):
            if isinstance(old.get(k), dict) and isinstance(new.get(k), dict):
                for kk in sorted(set(old[k]) | set(new[k])):
                    if old[k].get(kk) != new[k].get(kk):
                        rows.append((f'{k}.{kk}', str(old[k].get(kk))[:70], str(new[k].get(kk))[:70]))
            else:
                rows.append((k, str(old.get(k))[:70], str(new.get(k))[:70]))
    return rows


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--diff', default=None, help='compare the fresh snapshot against this JSON')
    a = ap.parse_args(argv[1:])

    snap = snapshot(a.adb)
    text = json.dumps(snap, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[session] -> {a.out}')
    print(f"[session] login prefs: {len(snap['login_prefs'])}；cookie {snap['cookie_bytes']} B / "
          f"域名 {len(snap['cookie_domains'])} 个；guest uid={snap['guest_state']['uid_values']}")

    if a.diff:
        old = json.load(open(a.diff))
        rows = diff(old, snap)
        print(f'[session] 与 {a.diff} 的差异：{len(rows)} 处')
        for k, o, n in rows[:20]:
            print(f'  * {k}\n      旧: {o}\n      新: {n}')
        return 1 if rows else 0
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
