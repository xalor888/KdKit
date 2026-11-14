#!/usr/bin/env python3
"""
kuaidui-kit / module_report.py — "which features are actually running in the host right now?"

`acceptance.py` answers "is the whole pipeline healthy"; this answers the narrower question a
feature review asks: for each KdKit feature, is it enabled, did it install, and where is the
*observable* evidence that it did anything.

Sources (both pulled from the device with root):

  * the LSPosed module log  `/data/adb/lspd/log/modules_*.log`  → `feature on/off`, install lines
  * the host capture        `files/kdkit_capture.txt`           → feature-written records

    python3 kit/scripts/module_report.py --adb emulator-5558 [--out work/module_report.md]

Evidence keywords per feature are declared below; a feature with "installed" but no evidence is
reported as such instead of being quietly counted as working.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
from device import PKG as PKG_CONST
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
MODULE = 'dev.xalor.kdkit'

# feature id -> (install-log pattern, capture/log evidence patterns)
FEATURES = {
    'rm_adconfig':      ('AdConfig',      [r'blocked ad slot read', r'ad config']),
    'rm_splash':        ('Splash',        [r'splash']),
    'rm_tab_ad':        ('TabAd',         [r'tab ad']),
    'rm_main_banner':   ('MainBanner',    [r'banner']),
    'rm_popup':         ('Popup',         [r'popup']),
    'rm_feed_ad':       ('FeedAd',        [r'feed']),
    'block_ad_sdk':     ('AdSdk',         [r'ad sdk', r'blocked']),
    'pk_assist':        ('PkAssist',      [r'entering mock match', r'KdKit · 已完成']),
    'sign_observer':    ('SignObserver',  [r'SIGN URL:', r'SIGN params:']),
    'native_probe':     ('NativeProbe',   [r'SIGNPARAM', r'libbaseutil base']),
    'anti_detect':      ('AntiDetect',    [r'neutralised']),
    'exit_guard':       ('ExitGuard',     [r'ExitGuard installed']),
    'skip_onboarding':  ('SkipOnboarding', [r'SkipOnboarding: clicked']),
    'h5_bridge_log':    ('H5BridgeLog',   [r'H5BRIDGE ']),
    'ad_probe':         ('AdSlotProbe',   [r'ADSLOT call']),
    'bridge_guard':     ('BridgeGuard',   [r'GUARD blocked']),
    'native_exit_guard': ('NativeExitGuard', [r'NativeExitGuard: seccomp']),
    'h5_debug':         ('WebInjector',   [r'WebInjector installed']),
    # 2026-10-25 新增的三个功能：日志/抓取前缀在这里登记，否则报告里它们是"装了但没证据"
    'bridge_action_log': ('BridgeActionLog', [r'BRIDGE downloadMedia', r'BRIDGE getuserinfo']),
    'skip_update':      ('SkipForceUpdate', [r'UPDATE suppressed', r'UPDATE forceUp']),
    'vip_unlock':       ('VipUnlock',     [r'VIP unlock applied']),
}

# 钩子台账：`HookCore audit: ready 28/28 features, hooks 96 ok / 0 failed -> ...`
# 注意必须带 re.M：日志是**多行**文本，`$` 在无 MULTILINE 时只匹配整串结尾，
# 于是"台账行不是最后一行"就永远解析不到（实测：94 ok / 0 failed 明明在日志里，
# 报告却写"本版模块未输出"）。
AUDIT_RE = re.compile(
    r'HookCore audit: .*?hooks (\d+) ok / (\d+) failed'
    r'(?: -> failed: ([^-]*?))?'
    r'(?: -> skipped: (.+?))?$', re.M)


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
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    logpath = adb(a.adb, 'ls -t /data/adb/lspd/log/modules_*.log | head -1')[1].strip()
    modlog = adb(a.adb, f'grep -a KdKit {logpath}')[1] if logpath else ''
    cap = adb(a.adb, f'cat /data/data/{PKG}/files/kdkit_capture.txt')[1]
    pid = adb(a.adb, f'pidof {PKG}')[1].strip()
    feats = max((int(x) for x in re.findall(r'HookCore ready \((\d+) features\)', modlog)), default=0)
    # 钩子台账（可选；老版本模块没有这行）
    audit = AUDIT_RE.findall(modlog)
    audit_line = ''
    if audit:
        ok, failed, bad, skipped = audit[-1]
        audit_line = f'{ok} hooks ok / {failed} failed'
        if bad:
            audit_line += f' -> 装不上: {bad.strip()}'
        # skipped = 目标类根本没找到（clazzOrNull 返回 null），连尝试都没有。
        # 这类过去完全隐形：hook 数比预期少、日志里一行都没有。
        if skipped:
            audit_line += f' -> 从没尝试: {skipped.strip()}'

    if not re.search(r'feature (on|off): ', modlog):
        print('[module] 最新日志里没有 feature on/off 行（宿主可能刚重启）—— '
              '报告基于"看起来启用的功能"不可靠，先等 15 s 或重跑一次')
    # the last on/off line wins
    state = {}
    for m in re.finditer(r'feature (on|off): (\S+)', modlog):
        state[m.group(2)] = m.group(1) == 'on'

    rows = []
    for fid, (install_pat, ev_pats) in FEATURES.items():
        enabled = state.get(fid)
        installed = bool(re.search(install_pat, modlog, re.I))
        ev = sum(len(re.findall(p, cap)) + len(re.findall(p, modlog)) for p in ev_pats)
        judged = 'ON' if enabled else ('OFF' if enabled is False else '?')
        note = 'no evidence in this session' if (enabled and ev == 0) else ''
        rows.append((fid, judged, 'yes' if installed else '-', ev, note))

    out = [f'# KdKit 模块运行报告',
           f'',
           f'* 宿主：`{PKG}`  pid=`{pid or "-"}`',
           f'* 模块：`{MODULE}`，`HookCore ready ({feats} features)`',
           # 钩子台账：少挂了几条在这里直接可读（老版本模块没有这行就留空）
           (f'* 钩子台账：{audit_line}' if audit_line else '* 钩子台账：本版模块未输出（`HookCore audit:` 行缺失）'),
           f'* 日志：`{logpath}`；抓取：{len(cap)} B',
           f'* 开关状态取自日志里最后的 `feature on/off` 行（即当前进程的实际配置）',
           f'',
           f'| feature | 状态 | 有安装日志 | 本轮证据条数 | 备注 |',
           f'|---|---|---|---|---|']
    for fid, judged, inst, ev, note in rows:
        out.append(f'| `{fid}` | {judged} | {inst} | {ev} | {note} |')
    enabled_n = sum(1 for r in rows if r[1] == 'ON')
    silent = [r[0] for r in rows if r[1] == 'ON' and r[3] == 0]
    out += ['', f'* 打开的功能：{enabled_n}/{len(rows)}',
            f'* 打开但本轮没有证据：{", ".join(silent) if silent else "无"}',
            f'* 说明：证据条数来自"这一轮抓取/日志里出现过该功能写的记录"；0 不等于没生效，'
            f'只表示本轮没触发到它的路径。']
    text = '\n'.join(out) + '\n'
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[module] -> {a.out}')
    print('\n'.join(out[:8]))
    print('...')
    print('\n'.join(out[-3:]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
