#!/usr/bin/env bash
# kuaidui-kit / recon.sh
# macOS counterpart of apk-reverse skill's decode.ps1 + manifest-summary.ps1.
# Usage: ./recon.sh [APK_PATH]
set -euo pipefail

# **先检查有没有参数，再尝试从当前目录找**（2026-11-04 修，代码审查 P1）。
#
# 旧写法是 `APK="$(ls -1 ./*.apk 2>/dev/null | head -1)"` —— 当没有任何 *.apk
# 时，`ls` 返回非零且输出到 `/dev/null`，于是 `head -1` 得到空串；`set -e` 让
# `$()` 里的命令失败 ⇒ 整行赋值失败，脚本直接退出。
#
# 修法：先把 `$1` 的有无和合法性单独查，再进入 `find ... -name '*.apk'`。
if [ $# -ge 1 ]; then
    APK="$1"
else
    # `-maxdepth 1 -name '*.apk'` 确保只搜当前目录（递归太慢）；
    # **不用 `-print0 | head -z1`**：macOS 的 `head` 不支持 `-z` ⇒ 换平台就崩（2026-11-04 实测）。
    APK="$(find . -maxdepth 1 -type f -name '*.apk' 2>/dev/null | head -1)"
fi
APK="${APK:-}"
[ -n "$APK" ] && [ -f "$APK" ] || { echo "no apk given and none found in cwd"; exit 1; }
[ -f "$APK" ] || { echo "apk not found: $APK"; exit 1; }

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="$(basename "${APK%.apk}")"
OUT="$ROOT/work"
mkdir -p "$OUT/native"

echo "== target : $APK"
echo "== outdir : $OUT"
echo

echo "== [1/5] apktool decode (smali + resources)"
if [ ! -d "$OUT/apktool_out" ]; then
  apktool d "$APK" -o "$OUT/apktool_out" -f > "$OUT/apktool.log" 2>&1 || true
else
  echo "   reuse $OUT/apktool_out"
fi

echo "== [2/5] jadx decode (java)"
if [ ! -d "$OUT/jadx_out" ]; then
  jadx -d "$OUT/jadx_out" --deobf "$APK" > "$OUT/jadx.log" 2>&1 || true
else
  echo "   reuse $OUT/jadx_out"
fi

echo "== [3/5] native libs"
unzip -o -j "$APK" 'lib/*/*.so' -d "$OUT/native" >/dev/null 2>&1 || true
unzip -l "$APK" | grep -E 'lib/.*\.so$' \
  | awk '{printf "%10d  %s\n", $1, $4}' | sort -rn > "$OUT/so_inventory.txt"
sed -n '1,200p' "$OUT/so_inventory.txt"

echo
echo "== [4/5] manifest summary"
MAN="$OUT/apktool_out/AndroidManifest.xml"
python3 - "$MAN" <<'PY'
import re, sys
m = open(sys.argv[1], encoding='utf-8', errors='ignore').read()
def show(label, rx):
    v = re.findall(rx, m)
    print(f"{label}: {v[:8]}")
print("package        :", (re.findall(r'package="([^"]+)"', m) or ["?"])[0])
show("versionName    ", r'android:versionName="([^"]+)"')
show("versionCode    ", r'android:versionCode="([^"]+)"')
show("application    ", r'<application[^>]*android:name="([^"]+)"')
show("debuggable     ", r'android:debuggable="([^"]+)"')
show("allowBackup    ", r'android:allowBackup="([^"]+)"')
show("cleartext      ", r'android:usesCleartextTraffic="([^"]+)"')
acts = re.findall(r'<activity\b', m); svcs = re.findall(r'<service\b', m)
rcvs = re.findall(r'<receiver\b', m); provs = re.findall(r'<provider\b', m)
print(f"components     : activities={len(acts)} services={len(svcs)} receivers={len(rcvs)} providers={len(provs)}")
print("permissions    :", len(re.findall(r'<uses-permission', m)))
print("-- launcher ----")
for blk in re.findall(r'<activity[^>]*>(?:(?!</activity>).)*?LAUNCHER.*?</activity>', m, re.S):
    nm = re.search(r'android:name="([^"]+)"', blk)
    tgt = re.findall(r'targetActivity="([^"]*)"', blk)
    if nm: print("  ", nm.group(1), ("-> " + tgt[0]) if tgt else "")
print("-- exported (non-SDK) --")
for blk in re.findall(r'<activity[^>]*android:exported="true"[^>]*>', m):
    nm = re.search(r'android:name="([^"]+)"', blk).group(1)
    if not re.search(r'com\.(alipay|tencent|bytedance|ss\.android|kwad|baidu\.location|huawei|xiaomi|heytap|vivo|meizu|unionpay|sina|amap|xingin)\.', nm):
        print("  ", nm)
PY

echo
echo "== [5/5] app-code inventory"
SRC="$OUT/jadx_out/sources"
if [ -d "$SRC" ]; then
  echo "java files total : $(find "$SRC" -name '*.java' | wc -l | tr -d ' ')"
  echo "app java files   : $(find "$SRC/com/kuaiduizuoye" -name '*.java' 2>/dev/null | wc -l | tr -d ' ')"
  echo "-- hosts --"
  grep -rhoE 'https?://[a-zA-Z0-9._-]+\.(com|cn|net|org)' "$SRC/com/kuaiduizuoye" 2>/dev/null \
    | sort | uniq -c | sort -rn | head -20
fi
echo
echo "done. report -> $ROOT/work/TRIAGE.md"
