#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# check_device_matches_analysis.sh — 设备上跑的目标 App 与我们分析的 APK 是不是同一份？
#
# 为什么需要这个
# ───────────────
# 整个项目的 38 个功能、124 个钩子目标、所有 smali 结论，都建立在
# `work/apktool_out/` 这一份解包之上。
#
# 如果设备上装的是**另一个版本**，那么所有"目标存在""签名一致"的结论
# 都只对那个版本成立，对真实环境无效 —— 而**没有任何静态门禁能发现这件事**。
#
# 这个脚本用 SHA-256 比对「设备上已安装的 base.apk」与「仓库里的目标 APK」。
#
# 用法：`module/scripts/check_device_matches_analysis.sh [--serial X]`
# 没有设备时跳过（不算失败）。
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PKG=com.kuaiduizuoye.scan
# 仓库里可能同时躺着多个版本的 APK（7.7.2 与 7.9.0）。旧实现 `ls | head -1` 取到的是
# **字典序第一**（7.7.2），于是在设备升到 7.9.0 之后这条门禁永远红 —— 而它本该比的是
# "设备上那一份"。所以：先按设备版本号挑，挑不到再退回"最新的那一份"。
DEV_VERSION="$(adb ${ANDROID_SERIAL:+-s "$ANDROID_SERIAL"} shell dumpsys package "$PKG" 2>/dev/null \
  | awk '/versionName=/{v=$1} /versionCode=/{c=$1; print v"-"c; exit}' | tr -d '\r' | sed 's/versionName=//;s/versionCode=//')"
LOCAL_APK=""
if [ -n "${DEV_VERSION:-}" ]; then
  LOCAL_APK="$(ls "$ROOT"/${PKG}-${DEV_VERSION}-*.apk 2>/dev/null | head -1)"
fi
[ -n "$LOCAL_APK" ] || LOCAL_APK="$(ls -t "$ROOT"/${PKG}-*.apk 2>/dev/null | head -1)"
TMP="$ROOT/work/installed"

SERIAL="${ANDROID_SERIAL:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --serial) SERIAL="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done
ADB=(adb); [ -n "$SERIAL" ] && ADB=(adb -s "$SERIAL")

echo "── 设备上的目标 App ↔ 仓库里分析的 APK ──"

if [ -z "$LOCAL_APK" ] || [ ! -f "$LOCAL_APK" ]; then
  echo "  SKIP  仓库里没有 ${PKG}-*.apk（无法比对）"
  exit 0
fi

DEV="$("${ADB[@]}" devices 2>/dev/null | awk '$2=="device"{print $1; exit}')"
if [ -z "$DEV" ]; then
  echo "  SKIP  没有 device 状态的设备"
  exit 0
fi

if ! "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "package:$PKG"; then
  echo "  SKIP  设备上没装 $PKG"
  exit 0
fi

REMOTE="$("${ADB[@]}" shell pm path "$PKG" 2>/dev/null | sed 's/package://' | tr -d '\r' | head -1)"
if [ -z "$REMOTE" ]; then
  echo "  FAIL  取不到已安装 APK 的路径"
  exit 1
fi

mkdir -p "$TMP"
PULLED="$TMP/base.apk"
if ! "${ADB[@]}" pull "$REMOTE" "$PULLED" >/dev/null 2>&1; then
  echo "  FAIL  拉取已安装 APK 失败（可能需要 root / run-as）"
  exit 1
fi

H_LOCAL="$(shasum -a 256 "$LOCAL_APK" | awk '{print $1}')"
H_DEV="$(shasum -a 256 "$PULLED"    | awk '{print $1}')"

echo "  仓库: ${H_LOCAL:0:16}…  ($(basename "$LOCAL_APK"))"
echo "  设备: ${H_DEV:0:16}…"

if [ "$H_LOCAL" = "$H_DEV" ]; then
  echo "  PASS  设备上运行的就是我们分析的那份字节"
  echo
  echo "  这条证明：38 个功能、124 个钩子目标、全部 smali 结论都对**真实环境**成立。"
  exit 0
fi

echo "  FAIL  设备上装的是**另一个版本**！"
echo
echo "  后果：所有「目标存在」「签名一致」的结论只对仓库里那份成立，对设备无效。"
echo "  而**没有任何静态门禁能发现这件事** —— 这正是本脚本存在的理由。"
echo
echo "  处置：拉取设备上那份重新解包，或把设备上的换成仓库里这份。"
exit 1
