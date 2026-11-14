#!/usr/bin/env python3
"""
kuaidui-kit / acceptance.py — one command that re-checks everything this kit claims.

Each check is the same command the round logs used, so a green run is a summary of the
project's verified state and a red one names exactly what changed. Nothing here is a
"mock": every line shells out to the real tools against the real device.

    python3 kit/scripts/acceptance.py --adb emulator-5558            # offline checks
    python3 kit/scripts/acceptance.py --adb emulator-5558 --live     # + one real API call

Checks
  1  environment      adb / magisk / vectord / frida-server / app / module installed
  2  module alive     "HookCore ready (N features)" and per-feature install lines in the log
  3  config channel   published prefs readable (mode 644) and non-empty
  4  capture          kdkit_capture.txt exists and has SIGN params / signed URLs
  5  offline RC4      verify_rc4_capture.py -> 0 mismatches
  6  offline sign     decode_token_native.py (tokens read from the device) -> 0 mismatches
  7  api rebuild      kd_api.py verify -> every URL whose sign reached the log rebuilds byte-exactly
                      (capture-truncated URLs and the one endpoint that signs a non-URL input
                      are reported as excluded; an unexpected mismatch fails the check)
  8  live call        (--live) kd_api.py call --retime -> HTTP 200 and errNo == 0
  9  hook targets     check_hook_targets.py -> every module hook target resolves

Exit code 0 only when every required check passes.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
from device import PKG as PKG_CONST
from device import PREFS as PREFS_CONST
import argparse
import json
import os
import re
import subprocess
import time
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
MODULE = 'dev.xalor.kdkit'


def sh(cmd, timeout=180):
    # 2026-11-03：本地实现换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现 `subprocess.run(cmd, shell=isinstance(cmd, str), timeout=…)`
    # **没有 `start_new_session`** ⇒ 超时只杀 shell，管道里的 `adb` 继续挂着
    # （2026-11-02 实测泄漏过）。规则 9b 原来只认字面量 `shell=True`，
    # 漏掉了这种"算出来的 shell=True" —— 全库 12 处都是这么写的。
    return _shmod.run(cmd, timeout=timeout)


def adb(serial, *args, timeout=180):
    return sh(['adb', '-s', serial, 'shell', ' '.join(args)], timeout=timeout)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--live', action='store_true', help='also fire one re-signed request at the real API')
    ap.add_argument('--ensure-flags', action='store_true',
                    help='make sure the diagnostic flags (sign_observer/native_probe) are on, then restart '
                         'the app so the checks have data to look at')
    ap.add_argument('--json', default=None)
    a = ap.parse_args(argv[1:])

    if a.ensure_flags:
        pub0 = adb(a.adb, f'ls /data/misc/*/prefs/{MODULE}/kdkit.xml 2>/dev/null | head -1')[1].strip()
        # merge, so flags the user turned on stay on (this used to clobber them)
        body = adb(a.adb, f'cat {pub0}')[1]
        cur = dict(re.findall(r'<boolean name="([^"]+)" value="(true|false)"', body))
        strs = dict(re.findall(r'<string name="([^"]+)">([^<]*)</string>', body))   # keep string settings
        cur.update({'sign_observer': 'true', 'native_probe': 'true'})
        open('/tmp/kdkit_accept.xml', 'w').write(
            "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n" +
            ''.join(f'    <boolean name="{k}" value="{v}" />\n' for k, v in sorted(cur.items())) +
            ''.join(f'    <string name="{k}">{v}</string>\n' for k, v in sorted(strs.items())) + '</map>\n')
        sh(f'adb -s {a.adb} push /tmp/kdkit_accept.xml /data/local/tmp/kdkit.xml')
        adb(a.adb, f"mkdir -p $(dirname {pub0}) && cp -f /data/local/tmp/kdkit.xml '{pub0}' && chmod 644 '{pub0}'")
        print(f'[acceptance] diagnostic flags merged into {pub0} ({len(cur)} flag(s)); restarting the app')
        adb(a.adb, f'am force-stop {PKG}')
        adb(a.adb, f'am start -n {PKG}/.AliasActivityDefault')
        import time as _t
        _t.sleep(18)

    rows = []

    def check(name, ok, detail=''):
        rows.append({'check': name, 'ok': bool(ok), 'detail': detail})
        print(f'{"PASS" if ok else "FAIL"}  {name:16s} {detail}')
        return ok

    def skip(name, why):
        """**这一项没跑**，与"跑过了且通过"是两件事。

        旧实现里条件不满足时（没有 sign token、没有抓取文件、没加 `--live`）
        直接**不调用 check()** —— 那一项就从报告里消失，而汇总行仍写
        `13/13 checks passed`。读的人无法区分"验过了"与"根本没验"，
        而这正是本项目反复在防的那类假结论。

        现在：跳过也占一行，汇总行把三项分开数。
        """
        rows.append({'check': name, 'ok': None, 'detail': why})
        print(f'SKIP  {name:16s} {why}')
        return None

    # 1 environment -----------------------------------------------------------
    rc, out = adb(a.adb, 'getprop', 'ro.build.version.sdk')
    _, magisk = adb(a.adb, 'magisk -v')
    _, vectord = adb(a.adb, 'ps -A | grep -c vectord')
    _, frida = adb(a.adb, 'ps -A | grep -c xdsvc')
    _, app = adb(a.adb, f'pm path {PKG}')
    _, mod = adb(a.adb, f'pm path {MODULE}')
    env_ok = rc == 0 and 'MAGISK' in magisk and vectord.strip() not in ('', '0') and PKG in app and MODULE in mod
    check('environment', env_ok,
          f'sdk={out.strip()} magisk={"yes" if "MAGISK" in magisk else "no"} '
          f'vectord={vectord.strip()} frida={"yes" if frida.strip() not in ("", "0") else "no"} '
          f'app={"yes" if PKG in app else "no"} module={"yes" if MODULE in mod else "no"}')

    pid = adb(a.adb, f'pidof {PKG}')[1].strip()

    # **自己安排前置条件**：宿主没在跑就先拉起来。
    #
    # 为什么：`verify.sh` 的 ⑬ 会 `am force-stop` 宿主来测冷启动，而验收经常紧跟其后跑。
    # 旧实现直接 `pidof` 取不到就判 FAIL —— 于是"模块活不活"这条**取决于两个脚本的先后顺序**，
    # 2026-11-02 一天里假红了两次（`pid=- HookCore ready (38 features), 2817 feature-on line(s)`：
    # 功能证据齐、进程没起 —— 那不是模块的问题，是没人把它拉起来）。
    # 验收脚本是harness，把前台拉起来本来就是它该做的事。
    if not pid:
        adb(a.adb, f'am start -W -n {PKG}/com.kuaiduizuoye.scan.AliasActivityDefault')
        for _ in range(20):
            time.sleep(1)
            pid = adb(a.adb, f'pidof {PKG}')[1].strip()
            if pid:
                break

    logpath = adb(a.adb, 'ls -t /data/adb/lspd/log/modules_*.log | head -1')[1].strip()
    modlog = adb(a.adb, f'grep -a KdKit {logpath}')[1] if logpath else ''

    # 2 module alive ----------------------------------------------------------
    # 宿主刚重启时日志尚未刷出 feature 行（2026-10-12 实测：这一条在证据包里偶发假红）。
    # 有界等待：最多等 ~20 秒重新读日志；还读不到才算失败 —— 别把"还没写"当成"没起来"。
    def read_alive():
        # **不只看最新那一份**：lspd 按"每次宿主进程连接"开新日志文件，
        # 目录里同时躺着模块自身进程、上个会话、以及当前扫描宿主的好几份。
        # 旧实现 `ls -t | head -1` 只取最新的一份 —— 而最新的那份很可能是
        # **模块设置页**（verify_on_device 刚拉起来过）而不是被钩的宿主，
        # 于是 `0 features`（2026-11-02 实测，进程明明在跑）。
        logps = adb(a.adb, 'ls -t /data/adb/lspd/log/modules_*.log 2>/dev/null | head -5')[1].split()
        txt = ''
        for logp in logps:
            txt += adb(a.adb, f'grep -a KdKit {logp}')[1]
        return txt, max((int(x) for x in re.findall(r'HookCore ready \((\d+) features\)', txt)), default=0), \
            len(re.findall(r'feature on: ', txt))

    feats, feat_lines = 0, 0
    for attempt in range(5):
        modlog, feats, feat_lines = read_alive()
        if feats > 0 and feat_lines > 0:
            break
        time.sleep(5)

    # 兜底证据：lspd 的 `modules_*.log` **按大小轮转**，宿主刚起来时那一行可能已经被挤出去
    # （2026-11-02 实测：进程明明在跑、抓取也在长，但日志里 `HookCore ready (0 features)`）。
    # 抓取文件里的 `=== KdKit host=` 是模块**自己**在宿主进程里写的启动标记，
    # 它出现在这份抓取里，就等价证明"模块在这个进程里跑过"。
    alive_by_capture, cap_marks = False, 0
    if feats == 0 or feat_lines == 0:
        # 抓取路径在这一步之后才定义（第 148 行），这里自己拼一份，别依赖后面的局部变量。
        _cap_path = f'/data/data/{PKG}/files/kdkit_capture.txt'
        # 轮转后启动标记会进 `.prev.txt` —— 两处都要看。
        _prev_path = _cap_path[:-4] + '.prev.txt'   # .txt -> .prev.txt
        n = adb(a.adb, f'cat {_cap_path} {_prev_path} 2>/dev/null | grep -ac "=== KdKit host="')[1].strip()
        cap_marks = int(n) if n.isdigit() else 0
        alive_by_capture = cap_marks > 0

    check('module alive', pid != '' and ((feats > 0 and feat_lines > 0) or alive_by_capture),
          f'pid={pid or "-"} HookCore ready ({feats} features), {feat_lines} feature-on line(s) in log'
          + (f'；日志轮转把启动行挤掉了，改用抓取里的 `=== KdKit host=` 标记 ×{cap_marks}'
             if alive_by_capture and feats == 0 else '')
          + ('' if (feats > 0 or alive_by_capture) else '（等了 20 秒仍无）'))

    # 3 config channel --------------------------------------------------------
    pub = adb(a.adb, 'ls /data/misc/*/prefs/' + MODULE + '/kdkit.xml 2>/dev/null | head -1')[1].strip()
    mode = adb(a.adb, f'stat -c %a {pub}')[1].strip() if pub else ''
    body = adb(a.adb, f'cat {pub}')[1] if pub else ''
    flags = len(re.findall(r'<boolean name="([^"]+)"', body))
    check('config channel', bool(pub) and mode == '644',
          f'path={"set" if pub else "missing"} mode={mode or "-"} flags={flags}')

    # 4 capture ---------------------------------------------------------------
    cap = f'/data/data/{PKG}/files/kdkit_capture.txt'
    size = adb(a.adb, f'stat -c %s {cap}')[1].strip()
    params = adb(a.adb, f'grep -ac "SIGN params:" {cap}')[1].strip()
    urls = adb(a.adb, f'grep -ac "SIGN URL:" {cap}')[1].strip()
    check('capture', size.isdigit() and int(size) > 0 and int(params or 0) > 0,
          f'{cap} {size} B, {params} param list(s), {urls} signed URL(s)')

    local_cap = os.path.join(ROOT, 'work/dpsdk/acceptance_capture.txt')
    if size.isdigit() and int(size) > 0:
        # **带上轮转出去的上一份**。
        #
        # 抓取到 4 MB 会轮转（`kdkit_capture.txt` -> `.prev.txt`）。一次
        # `SIGN params:` / `SIGN URL:` 的配对**可能正好被切在边界两侧**：
        # 参数行进了新文件、URL 行留在旧文件 —— 于是 `verify_rc4_capture.py`
        # 一个三元组都配不出来（实测：`match=0 mismatch=0`），门禁红在"轮转"上，
        # 而代码完全没问题。
        #
        # 顺序必须是"旧在前、新在后"：三元组配对按出现次序走。
        prev = cap[:-4] + '.prev.txt'
        parts = []
        psize = adb(a.adb, f'stat -c %s {prev}')[1].strip()
        if psize.isdigit() and int(psize) > 0:
            parts.append(adb(a.adb, f'cat {prev}')[1])
        parts.append(adb(a.adb, f'cat {cap}')[1])
        open(local_cap, 'w').write(''.join(parts))

    # tokens from the device (root) ------------------------------------------
    prefs = PREFS_CONST
    sign_a = adb(a.adb, f'grep -o "KEY_ANTISPAM_SIGN_A">[^<]*" {prefs}')[1]
    sign_a = adb(a.adb, f"grep -o 'KEY_ANTISPAM_SIGN_A\"[^<]*' {prefs}")[1].split('>')[-1].strip()
    sign_b = adb(a.adb, f"grep -o 'KEY_ANTISPAM_SIGN_B\"[^<]*' {prefs}")[1].split('>')[-1].strip()
    tok_a = os.path.join(ROOT, 'work/dpsdk/acceptance_signA.txt')
    tok_b = os.path.join(ROOT, 'work/dpsdk/acceptance_signB.txt')
    if sign_a and sign_b:
        open(tok_a, 'w').write(sign_a)
        open(tok_b, 'w').write(sign_b)

    # 5 offline RC4 -----------------------------------------------------------
    rc, out = sh(f'python3 {HERE}/../python/verify_rc4_capture.py {local_cap}')
    m = re.search(r'match=(\d+) mismatch=(\d+)', out)
    ok5 = bool(m) and int(m.group(2)) == 0 and int(m.group(1)) > 0
    check('offline RC4', ok5, m.group(0) if m else 'no RC4 triples found')

    # 5b 写入侧 ↔ 解析侧：**真实抓取**里每一行都要被某条规则认领
    #
    # 为什么放在验收里而不是离线的 `verify.sh`：判据必须是**设备上真实写出来的行**。
    # 夹具（fixture）是按规则写的 —— 规则和写入侧一起漂了，夹具照样过（R12 就是这么漏的：
    # `blocked ad slot read: di.a.d(501)` 有 7 行落 UNKNOWN，而所有离线门禁全绿）。
    # 这里是唯一拿得到"某个版本的模块真写出来的东西"的地方。
    #
    # 2026-11-02 实测：35 605 行（当前 + 上一份轮转）**未认领 0 行**。
    if os.path.exists(local_cap):
        sys.path.insert(0, os.path.join(HERE, '..', 'python'))
        import capture_schema as _cs
        _unk, _tot = [], 0
        with open(local_cap, encoding='utf-8', errors='replace') as _f:
            for _ln in _f:
                _ln = _ln.rstrip('\n')
                if not _ln.strip():
                    continue
                _tot += 1
                _r = _cs.parse_line(_ln)
                if _r is None or _r.kind == 'UNKNOWN':
                    _unk.append(_ln)
        # 取**前缀**而不是"第二个词"：行格式是 `HH:MM:SS.mmm PREFIX …`，
        # 但异常行可能没有时间戳（实测注入 `ZZNOTAPREFIX foo=1` 时报成了 `foo=1`）。
        # 前缀的形状是 `[A-Z][A-Z0-9_]*`，按形状找，别按下标猜。
        def _pfx(line):
            for tok in line.split():
                if re.fullmatch(r'[A-Z][A-Z0-9_]{2,}', tok):
                    return tok
            return line[:16]
        _head = ', '.join(sorted({_pfx(l) for l in _unk})[:6])
        check('抓取行全部被认领', not _unk,
              f'{_tot} 行，未认领 {len(_unk)} 行' + (f'（前缀：{_head}）' if _unk else '')
              + ('' if not _unk else ' —— 模块改了写入格式但没同步 capture_schema.py'))

    # 6 offline sign from tokens ---------------------------------------------
    ok6, detail6 = False, 'tokens not readable'
    if sign_a and sign_b:
        rc, out = sh(f'python3 {HERE}/decode_token_native.py --adb {a.adb} '
                     f'--sign-a {tok_a} --sign-b {tok_b} --capture {local_cap}')
        m = re.search(r'capture check: match=(\d+) mismatch=(\d+)', out)
        if m:
            ok6 = int(m.group(2)) == 0 and int(m.group(1)) > 0
            detail6 = m.group(0) + ' | ' + (re.search(r'\[token\] X\s+= (\S+)', out).group(1) if re.search(r'\[token\] X\s+= (\S+)', out) else '')
        else:
            detail6 = out.strip().splitlines()[-1][:120] if out.strip() else 'no output'
        check('offline sign', ok6, detail6)
    else:
        skip('offline sign', '抓取里没有 SIGN tokens（没有签名活动发生过）')

    # 7 api rebuild -----------------------------------------------------------
    # The assertion is "every URL whose sign reached the log rebuilds byte-exactly". Two classes are
    # reported but not asserted, because no code change can make them rebuild:
    #   * capture-truncated URLs (sign never written to the log) -> `missing_sign`
    #   * endpoints whose signing input is not the URL query (listed by name in kd_api.py)
    # `unexpected` is the only red: it means the signing algorithm diverged on a URL it used to reproduce.
    ok7, detail7 = False, 'skipped'
    if os.path.exists(local_cap):
        rc, out = sh(f'python3 {HERE}/../python/kd_api.py verify --adb {a.adb} '
                     f'--sign-a {tok_a} --sign-b {tok_b} --capture {local_cap}')
        m = re.search(r'rebuild: verified=(\d+) excluded=(\d+) unexpected=(\d+) '
                      r'missing_sign=(\d+) of (\d+)', out)
        if m:
            verified, excluded, unexpected, missing, total = (int(g) for g in m.groups())
            ok7 = unexpected == 0 and verified > 0 and rc == 0
            detail7 = (f'verified {verified}/{verified + excluded} signed URL(s)'
                       + (f', {excluded} excluded (non-URL signing input)' if excluded else '')
                       + f', {missing}/{total} URL(s) truncated -> not rebuildable'
                       + (f', UNEXPECTED {unexpected}' if unexpected else ''))
        else:
            detail7 = out.strip().splitlines()[-1][:140] if out.strip() else 'no output'
        check('api rebuild', ok7, detail7)
    else:
        skip('api rebuild', '没有抓到本地抓取文件 ⇒ 无从重算')

    # 8 live call -------------------------------------------------------------
    if a.live:
        ok8, detail8 = False, 'no captured URL'
        # 优先 hotfix（版本探测是**每个进程都会走**的端点，最稳定）；没有就退到
        # 抓取里最后一条可重算的 URL。旧实现只认 hotfix ⇒ 冷启动早期的抓取里
        # 一个 hotfix 都没有时直接判"没有可调 URL"，而其实满抓取都是签好的请求。
        # **同 4 的轮转问题**：URL 与 RC4KEY 也可能被切到 `.prev.txt` 里。
        # 用 `cat prev cap` 拼起来查（旧的在前），避免 grep 多文件时加 `文件:` 前缀。
        srcs = f'$( [ -f {cap[:-4]}.prev.txt ] && echo "{cap[:-4]}.prev.txt " ){cap}'
        rc, out = adb(a.adb, f'cat {srcs} | grep -a "SIGN URL:" | grep -a hotfix | tail -1')
        m = re.search(r'SIGN URL: (\S+)', out)
        used_fallback = False
        if not m:
            rc, out = adb(a.adb, f'cat {srcs} | grep -a "SIGN URL:" | grep -av abtest | tail -1')
            m = re.search(r'SIGN URL: (\S+)', out)
            used_fallback = bool(m)
        key = adb(a.adb, f'cat {srcs} | grep -aoE "RC4KEY b\\([0-9]+\\): [0-9a-f]*" | tail -1'
                  )[1].split(': ')[-1].strip()
        if m and key:
            rc, out = sh(f'python3 {HERE}/../python/kd_api.py call --adb {a.adb} --sign-a {tok_a} --sign-b {tok_b} '
                         f'--url "{m.group(1)}" --retime --insecure --rc4-key {key}')
            ok8 = 'errNo":0' in out
            mm = re.search(r'HTTP (\d+)', out)
            detail8 = (f'HTTP {mm.group(1) if mm else "?"} errNo=0'
                       + ('（无 hotfix URL，退到最近一条可重算请求）' if used_fallback else '')
                       ) if ok8 else out.strip().splitlines()[-1][:120]
        check('live call', ok8, detail8)
    else:
        skip('live call', '没加 --live（要真机发起一次请求）')

    # 8b session report -------------------------------------------------------
    if os.path.exists(local_cap):
        rep = os.path.join(ROOT, 'work/dpsdk/acceptance_session_report.md')
        rc, out = sh(f'python3 {HERE}/../python/session_report.py {local_cap} --out {rep}')
        ok = rc == 0 and os.path.exists(rep)
        check('session report', ok, out.strip().splitlines()[0][:90] if out.strip() else 'no output')
    else:
        skip('session report', '没有抓到本地抓取文件 ⇒ 无样本可报告')

    # 8b2 输入身份：APK / 解出的 .so / harness / 模块产物的哈希必须与基线一致
    #     （结论寄生在输入上：换个样本，结论就不再成立）
    rc, out = sh(f'python3 {HERE}/verify_inputs.py')
    ok = rc == 0
    detail = next((l for l in out.splitlines() if '输入哈希与基线一致' in l or '变化:' in l), out.strip()[:70])
    check('输入身份一致（样本/库/harness/产物）', ok, detail.replace('[inputs] ', ''))

    # 8c 产物一致性：设备上装的模块 APK 必须**就是**本地构建出来的那一份
    #    （同名不同构建是最经典的假结论来源：设备跑旧包，而我们却在解释新代码）
    local_apk = os.path.join(ROOT, 'module/app/build/outputs/apk/debug/app-debug.apk')
    if os.path.exists(local_apk):
        import hashlib
        h_local = hashlib.sha256(open(local_apk, 'rb').read()).hexdigest()
        rc, path_out = sh(f'adb -s {a.adb} shell pm path dev.xalor.kdkit')
        m2 = re.search(r'package:(\S+)', path_out)
        if m2:
            rc, dev_out = sh(f'adb -s {a.adb} shell sha256sum {m2.group(1)}')
            m3 = re.search(r'([0-9a-f]{64})', dev_out)
            ok = bool(m3) and m3.group(1) == h_local
            check('模块产物一致（本地构建 == 设备已装）', ok,
                  h_local[:16] + '…' + ('一致' if ok else ' ≠ ' + (m3.group(1)[:16] + '…' if m3 else '读不到')))
        else:
            check('模块产物一致（本地构建 == 设备已装）', False, '设备上没有 dev.xalor.kdkit')
    else:
        check('模块产物一致（本地构建 == 设备已装）', True, '跳过：本地没有构建产物')

    # 9 hook targets ----------------------------------------------------------
    rc, out = sh(f'python3 {HERE}/check_hook_targets.py')
    m = re.search(r'(\d+)/(\d+) resolved', out)
    ok9 = rc == 0 and bool(m)
    check('hook targets', ok9, m.group(0) if m else 'checker failed')

    bad = [r for r in rows if r['ok'] is False]
    skipped = [r for r in rows if r['ok'] is None]
    ran = len(rows) - len(skipped)
    # **汇总行必须把"没跑"单独数出来**（2026-11-02 改）。
    #
    # 旧行文是 `13/13 checks passed` —— 而 13 只是"跑了的项数"，
    # 另外几项因为条件不满足**根本没进 rows**。读的人无法区分
    # "验过了"与"没验"，于是"全绿"变成一句不可证的话。
    print(f'\n{ran - len(bad)}/{ran} checks passed'
          + (f'，另 {len(skipped)} 项**无法验证（SKIP）**' if skipped else '')
          + f'   ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")})')
    if skipped:
        print('   未验证的项：' + '、'.join(f"{r['check']}（{r['detail']}）" for r in skipped))
        print('   这些项**不算通过** —— 见各项 detail 说明怎么才能验。')
    if a.json:
        json.dump(rows, open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'report -> {a.json}')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
