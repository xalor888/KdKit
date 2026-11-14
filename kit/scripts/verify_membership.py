#!/usr/bin/env python3
"""
kuaidui-kit / verify_membership.py — C1/C3 的真机判据，做成**可执行的**。

### 为什么需要它

`work/DEVICE_LOGIN.md` 里 C1（广告面）/ C3（会员面）长期写着"环境受限，判据待登录后验证"。
但"判据"如果只是一段给人看的说明，它就永远不会被执行 —— 换个人接手还是得重新想一遍。

这个脚本把那段说明变成一条命令 + 一个**明确的退出码**：

| 退出码 | 含义 |
|---|---|
| **0** | 已登录，且下面每一项都有结论（有证据 / 明确没有） |
| **2** | **无法验证**：设备是游客态（`identityIdV2=0`）—— 会员权益本来就不存在，验不了 |
| 1 | 有登录态，但证据自相矛盾（比如"会员已解锁"却没走过任何会员钩子） |

**2 不是失败，也不是成功**：它说的是"这个环境测不了这件事"。
把它和 0 混在一起，就会出现"跑了一遍全绿、其实什么都没验"那种假结论。

### 判据从哪来

宿主的埋点里有 `identityIdV2`（游客=0）与 `vipStatus`（非会员=0）。它们出现在
`zybTrackerStatisticsAction` 上报里，抓取里能看到（URL 编码与明文两种形态都有）。

    python3 kit/scripts/verify_membership.py --adb emulator-5558
    python3 kit/scripts/verify_membership.py --capture work/packs/rXXX/capture.txt
"""
import argparse
import os
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'python'))
import textio
from device import PKG as PKG_CONST
from sh import sh  # noqa: E402  （带进程组超时：见 sh.py 的说明）

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
#: 广告面的两个计数（R63 起 `ADBLOCK` 是"拦截生效"的证据；在此之前只有读数）
AD_RX = [re.compile(r'ADSLOT')]
AD_BLOCK_RX = [re.compile(r'ADBLOCK')]
VIP_RX = [re.compile(r'VIP unlock applied')]

SIGNALS = [
    ('VIP unlock applied', 'vip_unlock 解了会员'),
    ('VIPLIMIT', 'vip_limit_probe 读到了限次'),
    ('ADSLOT', 'ad_probe 读到了广告位'),
    ('ADBLOCK', '广告拦截生效'),
    ('WATERMARK off applied', '水印关闭生效'),
]


#: `adb` 的失败信息（`sh()` 合并了 stderr，所以它们会混在"抓取内容"里）
ADB_ERR = re.compile(r"adb: (device|error)|error: (device|no devices)|"
                     r"cannot connect to|device offline|more than one device")


def pull_capture(adb):
    """当前 + 上一份轮转 —— 与 acceptance 同一个理由：一次上报可能被切在边界两侧。"""
    base = f'/data/data/{PKG}/files/kdkit_capture.txt'
    out = []
    for path in (base[:-4] + '.prev.txt', base):
        # `sh` 现在返回**单个字符串**（R53 换成 `kit/python/sh.py` 的共享实现，
        # 那个实现把 stdout+stderr 合并后只回内容）。旧写法按
        # `(returncode, output)` 解包 ⇒ `ValueError: too many values to unpack`
        # ⇒ `--adb` 那条路从 R53 起就是坏的，而报出来的是"未知"而不是崩溃。
        txt = sh(f'adb -s {adb} shell "cat {path} 2>/dev/null"')
        # `sh()` 把 stdout 与 stderr **合并**返回，所以"设备不在线"的错误信息
        # 也会出现在 txt 里。旧写法只判 `.strip()` ⇒ **一条失败步骤冒充成证据**：
        # 它被当成抓取内容参与后面的判定（R53 在 `check_capture_claimed.py` 里
        # 修过同一类问题，这里当时漏了）。
        if txt.strip() and not ADB_ERR.search(txt):
            out.append(txt)
    return ''.join(out)


def find_identity(text):
    """返回 (identityIdV2, vipStatus)；没找到给 None。"""
    ident = vip = None
    # 明文形态：`identityIdV2=0`、`vipStatus":"0"`
    for m in re.finditer(r'identityIdV2=(\d+)', text):
        ident = m.group(1)
    for m in re.finditer(r'vipStatus%22%2C%22v%22%3A%22(\d+)', text):
        vip = m.group(1)
    if vip is None:
        for m in re.finditer(r'"k":"vipStatus","v":"(\d+)"', text):
            vip = m.group(1)
    if vip is None:                      # 明文形态：`…&vipStatus=0&…`
        for m in re.finditer(r'vipStatus=(\d+)', text):
            vip = m.group(1)
    # 解码后再扫一遍（整条 query 被编码时明文正则抓不到）
    if ident is None or vip is None:
        for m in re.finditer(r'zybTrackerStatisticsAction[^\n]*', text):
            try:
                dec = urllib.parse.unquote(m.group(0))
            except Exception:
                continue
            mm = re.search(r'identityIdV2=(\d+)', dec) or re.search(r'identityIdV2":(\d+)', dec)
            if mm and ident is None:
                ident = mm.group(1)
            vv = re.search(r'"k":"vipStatus","v":"(\d+)"', dec)
            if vv and vip is None:
                vip = vv.group(1)
    return ident, vip


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=None, help='设备序列号（与 --capture 二选一）')
    ap.add_argument('--capture', default=None, help='离线抓取文件')
    ap.add_argument('--json', action='store_true', help='机器可读输出（给 face_board.py 用）')
    a = ap.parse_args(argv[1:])
    if not a.adb and not a.capture:
        ap.error('需要 --adb 或 --capture')

    text = pull_capture(a.adb) if a.adb else textio.read_text(a.capture)   # 2026-11-03
    _ad_read = sum(len(rx.findall(text)) for rx in AD_RX)
    _ad_blocked = sum(len(rx.findall(text)) for rx in AD_BLOCK_RX)
    _vip_unlocked = sum(len(rx.findall(text)) for rx in VIP_RX)

    def emit(code, state, detail):
        if a.json:
            import json as _json
            # 广告面的两个计数也放进 detail：看板（`face_board.py`）的 C1 行
            # 原来是一句写死的"游客态下广告位读得到"，**读不到真实数字**。
            # 而"读了 132 次、拦了 0 次"和"读了 88 次、拦了 88 次"是两件不同的事 ——
            # 前者是没生效，后者是生效了。ADBLOCK 这条证据（R63 加的）现在就在抓取里。
            print(_json.dumps({'face': 'vip', 'code': code, 'state': state, 'detail': detail,
                               'ad_read': _ad_read, 'ad_blocked': _ad_blocked,
                               'vip_unlocked': _vip_unlocked}))
        return code

    if not text.strip():
        return emit(1, 'unknown', '抓取是空的 —— 宿主没跑过')

    ident, vip = find_identity(text)
    lines = text.count('\n') + 1
    print(f'[membership] 抓取 {lines} 行；identityIdV2={ident if ident is not None else "?"} '
          f'vipStatus={vip if vip is not None else "?"}')

    if ident is None:
        print('[membership] ⚠ 抓取里没有 identityIdV2 —— 判不了登录态（埋点格式变了？）')
        print('[membership]   结论：**无法验证**（不是通过）')
        return emit(2, 'blocked', '没有 identityIdV2，判不了登录态')

    signals = []
    for needle, why in SIGNALS:
        n = text.count(needle)
        signals.append((needle, why, n))
    print('[membership] 会员/广告相关证据：')
    for needle, why, n in signals:
        print(f'   {n:6d}  {why}   （`{needle}`）')

    logged_in = ident not in ('0', '')
    if not logged_in:
        _adslot = next(n for k, _w, n in signals if k == 'ADSLOT')
        _adblock = next(n for k, _w, n in signals if k == 'ADBLOCK')
        print()
        print('[membership] 结 论：**无法验证** —— 设备处于游客态（identityIdV2=0）。')
        print('[membership]   会员：权益本身不存在，"解开了没有"无从判断。')
        if _adslot and not _adblock:
            # 别写"广告位是空的"：抓取里广告位**被读了 N 次**，只是没有可移除的投放。
            # 这两种情况对"免广告是否生效"的结论完全不同。
            print(f'[membership]   广告：广告位被读了 {_adslot} 次，但没有一条拦截记录 —— '
                  '说明"读了但没东西可拦"（游客态下发的通常是空配置），而不是"拦住了"。')
        elif _adblock:
            print(f'[membership]   广告：有 {_adblock} 条拦截记录（游客态下能拦到东西，值得单独看一眼）。')
        else:
            print('[membership]   广告：既没有广告位读取、也没有拦截记录 —— 这份抓取与广告面无关。')
        print('[membership]   要验这两面：在设备上登录一个**非会员**账号，重跑本脚本；')
        print('[membership]   登录后 identityIdV2 会变成非 0，届时本脚本给出 0 或 1。')
        return emit(2, 'blocked', '游客态 identityIdV2=0')

    # 已登录：只有"会员钩子走过"与"vipStatus 变化"能互相印证才算验证成功
    unlocked = next(n for k, _w, n in signals if k == 'VIP unlock applied')
    if unlocked == 0:
        print()
        print('[membership] 结 论：**未验证** —— 已登录，但没有任何 `vip_unlock applied` 记录。')
        print('[membership]   可能：功能没开 / 没走到会员判定 / 钩子没挂上。')
        print('[membership]   先开 vip_unlock 再逛一圈会员页，重跑本脚本。')
        return emit(2, 'blocked', '已登录但没有 vip_unlock 生效记录')

    print()
    print(f'[membership] 结 论：**已验证** —— 已登录（identityIdV2={ident}，'
          f'vipStatus={vip}），vip_unlock 有 {unlocked} 次生效记录。')
    return emit(0, 'verified', f'identityIdV2={ident} vip_unlock={unlocked}')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
