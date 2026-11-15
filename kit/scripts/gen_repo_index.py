#!/usr/bin/env python3
"""生成 LSPosed 模块仓库索引 `docs/modules.json`。

LSPosed 的"模块仓库"就是一个静态 JSON：
  repo.json    —— 仓库自述（name / homepage / index）
  modules.json —— 模块数组，每项带 releaseUrl / versionCode / md5 / size

为什么用脚本而不是手写：**md5 与 size 必须和发布出去的 APK 完全一致**，
手抄一次错一次；脚本直接从 CI 刚构建出的 APK 算，然后写回 docs/。

用法：python3 kit/scripts/gen_repo_index.py <apk> <versionName> <versionCode>
"""
import hashlib
import json
import pathlib
import sys

PKG = "dev.xalor.kdkit"
NAME = "KdKit"
AUTHOR = "xalor"
HOME = "https://github.com/xalor888/KdKit"
SCOPE = ["com.kuaiduizuoye.scan"]
MIN_API = 26
TARGET_API = 37
DESC = "快对去广告 / 界面 / 稳定性增强：去掉开屏、横幅、页签、弹窗、信息流与会员推销"


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    apk = pathlib.Path(sys.argv[1])
    version_name = sys.argv[2]
    version_code = int(sys.argv[3])
    data = apk.read_bytes()

    entry = {
        "id": PKG,
        "name": NAME,
        "author": AUTHOR,
        "description": DESC,
        "homepage": HOME,
        "version": version_name,
        "versionCode": version_code,
        "minApi": MIN_API,
        "targetApi": TARGET_API,
        "scope": SCOPE,
        "md5": hashlib.md5(data).hexdigest(),
        "size": len(data),
        "releaseUrl": f"{HOME}/releases/download/v{version_name}/KdKit-v{version_name}.apk",
    }

    out = pathlib.Path("docs/modules.json")
    existing = []
    if out.is_file():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    merged = [m for m in existing if m.get("id") != PKG] + [entry]
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}: {version_name} ({version_code}) md5={entry['md5']} size={entry['size']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
