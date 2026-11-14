#!/usr/bin/env python3
"""
kuaidui-kit / tap_texts.py — drive an Android screen by **visible text**, one step at a time.

The kit repeatedly needs "open this page, then that one" on a real device (to exercise the H5
bridge, the PK page, the ad surfaces…). Coordinate guessing is brittle; `uiautomator dump` +
bounds is not. This helper dumps the tree, finds the first node whose text contains the needle,
taps its centre, waits, and reports what the foreground activity became.

    python3 tap_texts.py --adb emulator-5558 --steps "我的,同步学,收藏,错题本" --wait 6

`--dump` prints the visible texts of each step (useful when a label is missing).
"""
import argparse
import re
import subprocess
import sys
import time


def adb(serial, *args, timeout=90):
    return subprocess.run(['adb', '-s', serial, 'shell', *args],
                          capture_output=True, text=True, timeout=timeout)


def dump(serial):
    adb(serial, 'uiautomator dump /sdcard/_tap.xml >/dev/null 2>&1')
    return adb(serial, 'cat /sdcard/_tap.xml').stdout


def find(xml, needle):
    """Shortest visible label that matches — exact match wins over a substring hit
    (page copy often contains the word we are looking for somewhere deep in a paragraph)."""
    hits = []
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        t = re.search(r'text="([^"]*)"', tag)
        if not t:
            continue
        text = t.group(1)
        if not text or len(text) > 24 or needle not in text:
            continue
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        hits.append((0 if text == needle else 1, len(text), b, text))
    if not hits:
        return None
    hits.sort(key=lambda h: (h[0], h[1]))
    _, _, b, text = hits[0]
    x = (int(b.group(1)) + int(b.group(3))) // 2
    y = (int(b.group(2)) + int(b.group(4))) // 2
    return x, y, text


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--steps', required=True, help='comma-separated texts to tap in order')
    ap.add_argument('--wait', type=float, default=6.0)
    ap.add_argument('--dump', action='store_true')
    a = ap.parse_args(argv[1:])

    # **三种结局，退出码分开**（2026-11-03 修）。
    #
    # 旧实现恒定 `return 0`：某一步 MISS 只 print，于是调用方**分不出**
    # "没驱动/设备不在线" 与 "每步都点到了"。实测（`--adb emulator-7777`，
    # 一个不存在的 serial）：dump 返回空 ⇒ 每一步都 MISS ⇒ 仍然 rc=0。
    # **一个完全离线的设备报告成功** —— 这正是"报告成功但不验证"那一类。
    #
    # 0 = 每步都点到；1 = 有步骤没点到（含设备不可达）；2 = 设备根本不可达。
    unreachable = False
    notext = False
    missed = []
    for step in [s.strip() for s in a.steps.split(',') if s.strip()]:
        xml = dump(a.adb)
        if not xml.strip():
            # dump 空 = 设备不在线 / uiautomator 起不来。这不是"文案不在屏幕上"，
            # 是**判据本身不成立**，必须分开说。
            unreachable = True
            print(f'[tap] NODUMP {step!r}：拿不到界面树（设备不在线？）')
            missed.append(step)
            continue
        texts = [t.group(1) for t in re.finditer(r'text="([^"]{2,20})"', xml)]
        if a.dump:
            print('   visible:', ', '.join(texts[:14]))
        if not texts:
            # 树取到了，可**一个文案都没有**（实测：开屏/加载页就是这样）。
            # 这时每一步都必然 MISS —— 但结论不是"文案不在"，
            # 是"**这一屏没有可用判据**"。混在一起会让人去改步骤文案，
            # 而真正该做的是等页面加载完。
            print('[tap] NOTEXT 界面树里一个文案都没有（开屏/加载中？）⇒ 判据不成立')
            notext = True
            break
        hit = find(xml, step)
        if not hit:
            print(f'[tap] MISS   {step!r} not on screen')
            missed.append(step)
            continue
        x, y, label = hit
        adb(a.adb, f'input tap {x} {y}')
        time.sleep(a.wait)
        act = adb(a.adb, 'dumpsys activity activities | grep -m1 ResumedActivity').stdout
        m = re.search(r'u0 ([\w.]+/[\w.$]+)', act)
        print(f'[tap] OK     {label!r} at ({x},{y})  ->  {m.group(1) if m else "?"}')
    if unreachable:
        print(f'[tap] **设备不可达**：{len(missed)} 步没能执行 —— 调用方请判"无法验证"，不要当成点过了')
        return 2
    if notext:
        print('[tap] **界面没有可用判据**：拿得到树但一个文案都没有 ⇒ 判"无法验证"，'
              '不要当成"文案不存在"而去改步骤')
        return 2
    if missed:
        print(f'[tap] {len(missed)} 步没点到：{missed}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
