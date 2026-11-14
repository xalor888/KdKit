#!/usr/bin/env bash
# kuaidui-kit / set_flag.sh — 往模块的**发布配置**里精确写/删一个键，用于「开/关对照」实验。
#
# 为什么不用 set_config.sh：那三个 profile 是"日常状态"，而行为验收需要的是
# "只翻一个开关、其余完全不动" —— 差一点就不是对照实验了。
#
#   ./kit/scripts/set_flag.sh --adb emulator-5558 --on rm_adconfig ad_probe
#   ./kit/scripts/set_flag.sh --adb emulator-5558 --off rm_adconfig
#   ./kit/scripts/set_flag.sh --adb emulator-5558 --drop rm_adconfig      # 从文件里删掉 → 回落默认
#   ./kit/scripts/set_flag.sh --adb emulator-5558 --str bridge_guard_list is_login
#   ./kit/scripts/set_flag.sh --adb emulator-5558 --list
#
# 写完立刻 force-stop 宿主，需要调用方自己再 `am start`（这样"什么时候生效"是可控的）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SER=""; MODE=""; KEYS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --adb)  SER="$2"; shift 2 ;;
    --on)   MODE=on;   shift;  while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do KEYS+=("$1"); shift; done ;;
    --off)  MODE=off;  shift;  while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do KEYS+=("$1"); shift; done ;;
    --drop) MODE=drop; shift;  while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do KEYS+=("$1"); shift; done ;;
    --str)  MODE=str; STRFROM="$2"; STRVAL="$3"; shift 3 ;;
    --list) MODE=list; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SER" ] || { echo "usage: $0 --adb <serial> --on|--off|--drop KEY... | --str KEY VALUE | --list" >&2; exit 2; }

# 字符串型（黑名单/白名单）也要能写：行为验收要用"把黑名单改成页面真的会调用的 action"
# 这种**正对照**来证明拦截器真的会拦，而不是只看"没写 GUARD 行"。
PUB="$(adb -s "$SER" shell 'ls /data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml 2>/dev/null | head -1' | tr -d '\r')"
[ -n "$PUB" ] || { echo "找不到发布配置（模块是否已注入过？）" >&2; exit 1; }

if [ "$MODE" = "list" ]; then
  # 布尔是 `<boolean name="x" value="true"/>`，字符串是 `<string name="x">v</string>`
  # —— 只 grep `value=` 会**看不见所有字符串键**（2026-11-02 踩到：以为没写进去）。
  adb -s "$SER" shell "cat '$PUB'" \
    | sed -nE 's#.*<boolean name="([^"]+)" value="([^"]*)".*#\1 = \2#p; s#.*<string name="([^"]+)">([^<]*)</string>.*#\1 = "\2"#p'
  exit 0
fi

TMP="$(mktemp)"; adb -s "$SER" shell "cat '$PUB'" > "$TMP"
for k in ${KEYS[@]+"${KEYS[@]}"}; do
  # 先删同名旧行（void 重复键：SharedPreferences 只认第一个，重复会让"到底哪个生效"变成谜）
  grep -v "name=\"$k\"" "$TMP" > "$TMP.1" && mv "$TMP.1" "$TMP"
  case "$MODE" in
    on)  sed -i '' "s#</map>#    <boolean name=\"$k\" value=\"true\" />\n</map>#" "$TMP" ;;
    off) sed -i '' "s#</map>#    <boolean name=\"$k\" value=\"false\" />\n</map>#" "$TMP" ;;
    drop) : ;;   # 只删不加 → 回落该功能自己的 defaultOn
  esac
  echo "[flag] $k -> $MODE"
done
if [ "$MODE" = "str" ]; then
  grep -v "name=\"$STRFROM\"" "$TMP" > "$TMP.1" && mv "$TMP.1" "$TMP"
  sed -i '' "s#</map>#    <string name=\"$STRFROM\">$STRVAL</string>\n</map>#" "$TMP"
  echo "[flag] str $STRFROM = $STRVAL"
fi
# **回读校验**（2026-11-02 加，与 `set_config.sh` 同一个理由）。
#
# 旧实现推完就 `echo 已写入`：push 失败、cp 没权限都照样说"写好了" ——
# 而这个脚本是**手工开关功能的唯一入口**，写失败却报成功会让人以为开关已改。
# 按条目比（不按字节）：模块会用自己的序列化器重写文件，XML 声明的引号会变。
if ! adb -s "$SER" push "$TMP" /data/local/tmp/kdkit-flag.xml >/dev/null; then
  echo "[flag] **推送失败**：$SER 不在线或 /data/local/tmp 不可写" >&2
  rm -f "$TMP"; exit 1
fi
adb -s "$SER" shell "cp -f /data/local/tmp/kdkit-flag.xml '$PUB'; chmod 644 '$PUB'"
BACK="$(adb -s "$SER" shell "cat '$PUB' 2>/dev/null")"
if [ -z "$BACK" ]; then
  echo "[flag] **回读为空**：$PUB 没有内容 ⇒ 模块会用默认配置跑" >&2
  rm -f "$TMP"; exit 1
fi
entries() { grep -oE '<(boolean|string) name="[^"]+"[^>]*>[^<]*' | sed 's/ value=/|/' | sort; }
if ! diff -q <(entries < "$TMP") <(printf '%s\n' "$BACK" | entries) >/dev/null 2>&1; then
  echo "[flag] **回读不一致**：设备上的条目与刚写的不是同一批" >&2
  diff <(entries < "$TMP") <(printf '%s\n' "$BACK" | entries) | head -8 | sed 's/^/    /' >&2
  rm -f "$TMP"; exit 1
fi
adb -s "$SER" shell 'am force-stop com.kuaiduizuoye.scan' >/dev/null 2>&1 || true
rm -f "$TMP"
echo "[flag] 回读校验通过（$(entries < /dev/null; printf '%s\n' "$BACK" | entries | wc -l | tr -d ' ') 条一致）；宿主已停，需要时自己 am start"
