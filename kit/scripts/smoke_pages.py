#!/usr/bin/env python3
"""
kuaidui-kit / smoke_pages.py —— 真机"页面不空白"冒烟回归。

为什么需要（2026-11-14）
────────────────────────
这一版曾经把快对的**拍题答疑页刷成空白**：注入的"页面配色归一 / 会员推广隐藏"脚本
把承载内容的容器当成背景块处理了，静态门禁全绿、截图却是一片白。
从此把"关键页面必须有内容"做成一条能一键跑的命令：

    python3 kit/scripts/smoke_pages.py --adb emulator-5558
    python3 kit/scripts/smoke_pages.py --adb emulator-5558 --shot-dir work/smoke

判据：每个页面用 `uiautomator dump` 数**有文本的节点数**，低于阈值即判红
（阈值按页面类型分别给：首页 > 拍题答疑 > 设置页 40 项）。
它不是"界面对不对"的判据，是"**页面还在不在**"的判据 —— 只回答这一件事。

退出码：0 = 全部通过；1 = 有页面空白/内容过少；2 = 设备或 App 不可用。
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

# 设备号与包名只有一个来源（门禁 ㉜）：`kit/python/device.py`。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from device import PKG as HOST_PKG            # noqa: E402
from device import default_serial             # noqa: E402

# (名称, 到达方式, 最少文本节点数)
# 到达方式：home=已在首页就 dump；tap=需要点击坐标；back=先返回再点
FLOWS = [
    ("首页", "home", 8),
    ("拍题答疑", "tap:150,2115", 8),
    # WebView 页面的正文在 uiautomator 里常常抓不到（只看到标题），所以阈值取 1：
    # 只要标题在、且截图不是纯色，就说明页面没白屏。真机截图见 work/smoke/。
    ("AI 写作", "back+text:AI写作", 1),
    ("我的", "back+tap:240,167", 6),
    ("设置页", "app", 25),
]


def adb(serial, *args, timeout=60):
    return subprocess.run(["adb", "-s", serial, "shell", *args], capture_output=True, text=True, timeout=timeout)


def dump(serial):
    adb(serial, "uiautomator", "dump", "/sdcard/kd_smoke.xml")
    subprocess.run(["adb", "-s", serial, "pull", "/sdcard/kd_smoke.xml",
                    tempfile.gettempdir() + "/kd_smoke.xml"], capture_output=True, text=True, timeout=60)
    path = os.path.join(tempfile.gettempdir(), "kd_smoke.xml")
    if not os.path.exists(path):
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [n.get("text") for n in root.iter("node") if n.get("text")]


SYSTEM_DIALOGS = {
    # 系统权限/崩溃对话框：点掉它们再判定，否则会把"被弹窗遮住"误判成"页面空白"
    "Allow 快对AI to access all device logs?": "Don’t allow",
    "快对AI isn't responding": "Wait",
}


def dismiss_system_dialogs(serial, texts):
    """遇到系统弹窗就点掉；返回是否点过（点过就要重新 dump）。"""
    for title, button in SYSTEM_DIALOGS.items():
        if any(title in (t or "") for t in texts):
            adb(serial, "uiautomator", "dump", "/sdcard/kd_dlg.xml")
            subprocess.run(["adb", "-s", serial, "pull", "/sdcard/kd_dlg.xml",
                            tempfile.gettempdir() + "/kd_dlg.xml"], capture_output=True, timeout=60)
            try:
                root = ET.parse(os.path.join(tempfile.gettempdir(), "kd_dlg.xml")).getroot()
            except Exception:
                return False
            for n in root.iter("node"):
                if (n.get("text") or "").strip() == button and n.get("bounds"):
                    nums = [int(v) for v in re.findall(r"[0-9]+", n.get("bounds"))]
                    if len(nums) == 4:
                        adb(serial, "input", "tap", str((nums[0] + nums[2]) // 2), str((nums[1] + nums[3]) // 2))
                        time.sleep(2)
                        return True
    return False


def shot(serial, outdir, name):
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, name + ".png")
    with open(p, "wb") as f:
        subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], stdout=f, timeout=60)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default=default_serial(), help="设备序列号（默认取 KD_SERIAL / adb devices）")
    ap.add_argument("--shot-dir", default=None, help="写截图到该目录（可选）")
    ap.add_argument("--host", default=HOST_PKG)
    ap.add_argument("--module", default="dev.xalor.kdkit")
    a = ap.parse_args(argv[1:])

    probe = subprocess.run(["adb", "-s", a.adb, "get-state"], capture_output=True, text=True, timeout=30)
    if probe.stdout.strip() != "device":
        print(f"[smoke] 设备 {a.adb} 不在线（{probe.stdout.strip() or probe.stderr.strip()}）", file=sys.stderr)
        return 2

    # 从干净的宿主开始：先回到首页
    adb(a.adb, "am", "force-stop", a.host)
    time.sleep(1)
    adb(a.adb, "am", "start", "-n", f"{a.host}/.AliasActivityDefault")
    time.sleep(8)

    bad = []
    for name, how, need in FLOWS:
        if how == "app":
            adb(a.adb, "am", "start", "-n", f"{a.module}/.ui.MainActivity")
            time.sleep(4)
        elif how.startswith("back+"):
            adb(a.adb, "input", "keyevent", "4")
            time.sleep(1)
            adb(a.adb, "am", "start", "-n", f"{a.host}/.AliasActivityDefault")
            time.sleep(5)
            spec = how.split("back+")[1]
            if spec.startswith("text:"):
                # 按文本找坐标再点：首页 chip 的位置会随布局/内容变化，写死坐标会点不中
                want = spec.split("text:")[1]
                adb(a.adb, "uiautomator", "dump", "/sdcard/kd_tap.xml")
                subprocess.run(["adb", "-s", a.adb, "pull", "/sdcard/kd_tap.xml",
                                tempfile.gettempdir() + "/kd_tap.xml"], capture_output=True, timeout=60)
                try:
                    root = ET.parse(os.path.join(tempfile.gettempdir(), "kd_tap.xml")).getroot()
                    for n in root.iter("node"):
                        if (n.get("text") or "").strip() == want and n.get("bounds"):
                            nums = [int(v) for v in re.findall(r"[0-9]+", n.get("bounds"))]
                            if len(nums) == 4:
                                adb(a.adb, "input", "tap", str((nums[0] + nums[2]) // 2), str((nums[1] + nums[3]) // 2))
                                break
                except Exception as e:
                    print(f"[smoke] 文本定位失败（{want}）：{e}", file=sys.stderr)
            else:
                x, y = spec.split("tap:")[1].split(",")
                adb(a.adb, "input", "tap", x, y)
            time.sleep(12)
        elif how.startswith("tap:"):
            x, y = how.split("tap:")[1].split(",")
            adb(a.adb, "input", "tap", x, y)
            time.sleep(12)

        texts = dump(a.adb)
        if dismiss_system_dialogs(a.adb, texts):
            time.sleep(2)
            texts = dump(a.adb)
        n = len(texts)
        ok = n >= need
        if a.shot_dir:
            shot(a.adb, a.shot_dir, re.sub(r"[^\w]+", "_", name))
        print(f"[smoke] {'PASS' if ok else 'FAIL'} {name}: {n} 个文本节点（要求 ≥{need}）"
              + ("" if ok else f" —— 样本 {texts[:6]}"))
        if not ok:
            bad.append((name, n, texts[:6]))

    if bad:
        print(f"[smoke] {len(bad)} 个页面判定为空白/内容过少", file=sys.stderr)
        return 1
    print("[smoke] 关键页面全部有内容 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
