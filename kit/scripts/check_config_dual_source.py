#!/usr/bin/env python3
"""
kuaidui-kit / check_config_dual_source.py — 模块的两份配置**必须是同一集合**。

为什么需要（2026-11-09 实测）
────────────────────────────
配置有两份，读的人不一样：

| 路径 | 谁读 | 用途 |
|---|---|---|
| `/data/misc/<uuid>/prefs/dev.xalor.kdkit/kdkit.xml` | **宿主进程**（`KdConfigBridge` 的 XSharedPreferences） | 决定功能是否生效 |
| `/data/data/dev.xalor.kdkit/shared_prefs/kdkit.xml` | **模块自己的设置页**（`KdConfig.isOn`） | 决定界面显示 |

只写前者时，设置页显示"**0 项布尔** / 已启用 13/38"，而宿主侧 `HookCore gates` 是
**effective-on 18** —— 两个人对同一台设备的描述差 5 个功能，而且**没有门禁能发现**。
（`set_config.sh` 的回读校验只验"我推的条目在发布目录里"，它不看设置页那一份。）

判据（可以一眼看懂的等式）
  * 两份 XML 里 `<boolean|string name="…">` 的 **name/value 集合逐条相等**；
  * 无设备 / 无 root ⇒ 退出码 **2**（"测不了"，不算通过也不算失败 —— verify 用 `--accept " 0 2 "`）。

    python3 kit/scripts/check_config_dual_source.py
    python3 kit/scripts/check_config_dual_source.py --adb emulator-5558

覆盖边界：只比**条目集合**，不比文件字节（两边由不同序列化器写出，声明行格式本来就不同）。
"""
import argparse
import re
import subprocess
import sys

ENTRY = re.compile(r'<(boolean|string)\s+name="([^"]+)"[^>]*>?([^<]*)')


def adb(serial, cmd):
    return subprocess.run(['adb'] + (['-s', serial] if serial else []) +
                          ['shell', 'su', '-c', cmd],
                          capture_output=True, text=True, errors='replace', timeout=60)


def entries(text):
    out = set()
    for m in ENTRY.finditer(text):
        kind, name, rest = m.group(1), m.group(2), m.group(3)
        val = rest.strip()
        if not val:
            v = re.search(r'value="([^"]*)"', m.group(0))
            val = v.group(1) if v else ''
        out.add((kind, name, val))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', default=None, help='设备序列号（省略则取第一台）')
    a = ap.parse_args(argv[1:])

    dev = a.adb
    if not dev:
        r = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=20)
        for ln in r.stdout.splitlines()[1:]:
            if '\tdevice' in ln:
                dev = ln.split('\t')[0]
                break
    if not dev:
        print('[dual] 没有设备 ⇒ 测不了（既不算通过也不算失败）')
        return 2

    pub = adb(dev, 'cat /data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml 2>/dev/null')
    app = adb(dev, 'cat /data/data/dev.xalor.kdkit/shared_prefs/kdkit.xml 2>/dev/null')
    if pub.returncode != 0 and not pub.stdout.strip():
        print(f'[dual] 读不到发布目录（{dev}）：{pub.stderr.strip()[:120]}')
        print('[dual] 常见原因：没有 root / 模块从未在宿主里注入过 / LSPosed prefs 被 SELinux 挡住')
        return 2
    if not app.stdout.strip():
        print('[dual] 读不到模块 App 的 prefs ⇒ 设置页会显示"0 项"（这正是这道门禁要抓的形态）')
        return 1

    A, B = entries(pub.stdout), entries(app.stdout)
    print(f'[dual] 发布目录 {len(A)} 条 / App prefs {len(B)} 条')
    only_pub = sorted(A - B)
    only_app = sorted(B - A)
    if only_pub or only_app:
        print('[dual] **两份配置不是同一集合**：')
        for k, n, v in only_pub[:10]:
            print(f'   ✗ 只在发布目录：{k} {n}={v}')
        for k, n, v in only_app[:10]:
            print(f'   ✗ 只在 App prefs：{k} {n}={v}')
        print('[dual] 修法：`bash kit/scripts/set_config.sh --adb <serial> --profile regular`'
              '（它现在会双写两份）')
        return 1
    print('[dual] 双源一致 ✓（设置页与宿主读的是同一批配置）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
