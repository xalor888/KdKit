#!/usr/bin/env python3
"""
kuaidui-kit / device.py — **默认设备号的唯一来源**。

### 为什么需要

2026-11-03 代码审查 P2：“默认设备号散落 28 个文件”。

实测（把 docstring 里的用法示例排除后）真正会**生效**的硬编码默认值只有 5 处：

| 位置 | 形态 |
|---|---|
| `host_pairing.py` / `nav_log.py` / `rc4_plaintexts.py` / `route_log.py` | `--adb` 的 argparse default |
| `after_login.py` | `os.environ.get('SERIAL_FOR_BOARD', 'emulator-5558')` |

28 那个数字把 docstring 里的用法示例也算进去了 —— 那些不改行为。
但**5 处也够危险**：换一台设备时要改 5 个地方，漏一个的后果是
某个工具**静默地操作另一台设备**（而它看起来跑通了）。

### 用法

```python
from device import default_serial
ap.add_argument('--adb', default=default_serial())
```

优先级：`KD_SERIAL` 环境变量 → `SERIAL` 环境变量 → `emulator-5558`。
**不读配置文件**：这类默认值要在“什么都没配”时也能用，
而多一个配置文件就多一处“配了却没生效”的可能。
"""
import os

#: 最后兜底。写成常量而不是散落，是为了“全库只有一个字符串是 5558”。
FALLBACK = 'emulator-5558'

#: **目标 App 的包名**。2026-11-03 实测：18 个文件各自写死了这一行。
#:
#: 换一个目标 App 时要改 18 个地方，漏一个的后果是那个工具
#: **静静地什么都读不到**（路径不存在 ⇒ `cat` 空 ⇒ 判据 0 命中 ⇒
#:  "没看到"被报成"没有发生"）。
PKG = 'com.kuaiduizuoye.scan'

#: 模块的累积抓取（当前 + 上一份轮转）。
CAPTURE = f'/data/data/{PKG}/files/kdkit_capture.txt'
CAPTURE_PREV = CAPTURE[:-4] + '.prev.txt'

#: 登录态所在的宿主私有 prefs。**这个名字不属于我们分析的目标** ——
#: 它是宿主（作业帮 App）自己的偏好文件名，2026-10-12 用 20 分钟
#: 换来的教训就在 `export_content.py:33` 那句注释里。
PREFS = f'/data/data/{PKG}/shared_prefs/com.baidu.homework.Preference.LibPreference.xml'


def default_serial():
    """命令行 `--adb` 的默认值。"""
    for var in ('KD_SERIAL', 'SERIAL'):
        v = os.environ.get(var, '').strip()
        if v:
            return v
    return FALLBACK


if __name__ == '__main__':
    print(default_serial())
