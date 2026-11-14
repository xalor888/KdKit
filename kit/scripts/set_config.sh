#!/usr/bin/env bash
# kuaidui-kit / set_config.sh — put a device back into a known module configuration.
#
# Rounds switch single features on and off; without this you end up with a device in a state nobody
# can describe. Three named profiles, each with the *expected* feature count so the result is
# checkable:
#
# 数字是**实测**的（`module_report` 的"打开的功能 N/17"）：注意"没写进文件的键会回落到各功能自己的
# 默认值"，所以 `min` 不是 1 —— 去广告那组默认就是开的。
#
#   regular (default)  诊断开 + 守卫开 + 观测开，实验/危险项关          -> 实测 13/17
#   diag               regular + h5_debug（页面里注入 eruda，调试用）   -> 实测 14/17
#   min                只写 sign_observer（最小落盘）                   -> 实测 10/17
#
#   ./kit/scripts/set_config.sh --adb emulator-5558 [--profile regular]
#   ./kit/scripts/set_config.sh --adb emulator-5558 --verify-only     # 只比对不推送
#
# 写的是框架发布目录（root 可写），随后重启宿主让配置生效；字符串型配置（守卫黑名单/域名白名单）
# 一并写入，避免"只恢复布尔、忘了字符串"。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SERIAL=""
PROFILE="regular"
VERIFY_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --adb) SERIAL="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    # 只比对、不推送：先按同一份 profile 生成期望条目，再与设备上的比。
    # 没有这个开关时，回读紧跟推送之后，**永远比的是自己刚写进去的东西** ——
    # 那样"回读不一致"这一支根本没有被触发过（2026-11-02 实测：把设备上的
    # ad_probe 改成 false，重跑仍然绿，因为推送已把它覆盖）。
    --verify-only) VERIFY_ONLY=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SERIAL" ] || { echo "usage: $0 --adb <serial> [--profile regular|diag|min]" >&2; exit 2; }

PKG=com.kuaiduizuoye.scan
PUB="$(adb -s "$SERIAL" shell 'ls /data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml 2>/dev/null | head -1' | tr -d '\r')"
if [ -z "$PUB" ]; then
  # 文件可能被删过（例如做"默认配置"实验）：目录仍在，就用同一个 <uuid> 路径重建，
  # 不要在这里直接退出 —— 否则恢复配置这件事本身会变成死路（2026-10-11 踩过）。
  PUB="$(adb -s "$SERIAL" shell 'ls -d /data/misc/*/prefs/dev.xalor.kdkit 2>/dev/null | head -1' | tr -d '\r')/kdkit.xml"
  case "$PUB" in
    /kdkit.xml|"") echo "找不到发布目录（模块是否已注入过？）" >&2; exit 1 ;;
  esac
  echo "[config] 发布文件不存在，将在 $PUB 重建"
fi

TMP="$(mktemp)"
EXPECT_TMP="$TMP"
if [ "$VERIFY_ONLY" -eq 1 ]; then
  # 只比对：期望条目另存一份，推送整段跳过
  EXPECT_TMP="$(mktemp)"
fi
{
  echo "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>"
  echo "<map>"
  case "$PROFILE" in
    regular|diag)
      echo '    <boolean name="sign_observer" value="true" />'
      echo '    <boolean name="native_probe" value="true" />'
      echo '    <boolean name="h5_bridge_log" value="true" />'
      echo '    <boolean name="bridge_guard" value="true" />'
      echo '    <boolean name="ad_probe" value="true" />'
      [ "$PROFILE" = "diag" ] && echo '    <boolean name="h5_debug" value="true" />'
      echo '    <string name="bridge_guard_list">core_showDebuger,core_login</string>'
      echo '    <string name="bridge_guard_http_allow">kuaiduizuoye.com,zuoyebang.com</string>'
      ;;
    min)
      echo '    <boolean name="sign_observer" value="true" />'
      ;;
    *) echo "unknown profile: $PROFILE" >&2; exit 2 ;;
  esac
  echo "</map>"
} > "$EXPECT_TMP"
if [ "$VERIFY_ONLY" -eq 0 ] && [ "$EXPECT_TMP" != "$TMP" ]; then cp "$EXPECT_TMP" "$TMP"; fi

# **回读校验**（2026-11-02 加）。
#
# 旧实现推完就 `echo "applied"`：push 失败、`/data/local/tmp` 满了、cp 没权限，
# 全都一样地打印"已应用" —— 而模块会拿**上一份** profile 继续跑。
# 后果是所有功能开关都与报告对不上，而每一轮门禁都是绿的。
# 这与今天在 `check_capture_claimed` / `verify_membership.pull_capture`
# 修掉的是同一类问题：**一个步骤报告成功，却不验证它真的发生了**。
if [ "$VERIFY_ONLY" -eq 0 ]; then
adb -s "$SERIAL" shell "am force-stop dev.xalor.kdkit" >/dev/null 2>&1 || true
fi
if [ "$VERIFY_ONLY" -eq 0 ] && ! adb -s "$SERIAL" push "$TMP" /data/local/tmp/kdkit-profile.xml >/dev/null; then
  echo "[config] **推送失败**：$SERIAL 不在线或 /data/local/tmp 不可写" >&2
  rm -f "$TMP" "$EXPECT_TMP"; exit 1
fi
if [ "$VERIFY_ONLY" -eq 0 ]; then
# **双源同步（2026-11-09 加）**：发布目录是宿主读的（`KdConfigBridge` 的 XSharedPreferences），
# 模块自己的 App prefs 是**设置页读的**（`KdConfig.isOn` 走 `getSharedPreferences`）。
# 只写发布目录时，设置页会显示"0 项布尔"、与实际生效集合对不上（实测 UI 说 13/38、
# 宿主 `HookCore gates` 说 effective-on 18）—— 这是 B2「配置双源一致」要消灭的那个差。
APP_PREFS=/data/data/dev.xalor.kdkit/shared_prefs/kdkit.xml
adb -s "$SERIAL" shell "mkdir -p \$(dirname '$PUB'); cp -f /data/local/tmp/kdkit-profile.xml '$PUB'; chmod 644 '$PUB'; \
  mkdir -p \$(dirname '$APP_PREFS'); cp -f /data/local/tmp/kdkit-profile.xml '$APP_PREFS' 2>/dev/null; \
  chown u0_a214:u0_a214 '$APP_PREFS' 2>/dev/null; chmod 660 '$APP_PREFS' 2>/dev/null; true"
fi

# **按条目比，不按字节比**（2026-11-02 第一版按字节比，永远不成立）。
#
# 模块读到 profile 后会用自己的序列化器把文件重写一遍：
# XML 声明从 `version="1.0"` 变成 `version='1.0'`，其余条目原样。
# 于是字节比较**永远失败** —— 那和"永远绿"一样坏：一道永远红的检查会被直接跳过。
# 真正要保证的是"**我推的每一条都在设备上**"，所以抽 `name`/`value` 成集合再比。
BACK="$(adb -s "$SERIAL" shell "cat '$PUB' 2>/dev/null")"
if [ -z "$BACK" ]; then
  echo "[config] **回读为空**：$PUB 没有内容 ⇒ 模块会用默认配置跑" >&2
  rm -f "$TMP" "$EXPECT_TMP"; exit 1
fi
entries() { grep -oE '<(boolean|string) name="[^"]+"[^>]*>[^<]*' | sed 's/ value=/|/' | sort; }
if ! diff -q <(entries < "$EXPECT_TMP") <(printf '%s\n' "$BACK" | entries) >/dev/null 2>&1; then
  echo "[config] **回读不一致**：设备上的条目与刚推的不是同一批" >&2
  diff <(entries < "$EXPECT_TMP") <(printf '%s\n' "$BACK" | entries) | head -8 | sed 's/^/    /' >&2
  rm -f "$TMP" "$EXPECT_TMP"; exit 1
fi
echo "[config] 回读校验通过（$(entries < "$EXPECT_TMP" | wc -l | tr -d ' ') 条一致）"
rm -f "$TMP" "$EXPECT_TMP"
[ "$VERIFY_ONLY" -eq 1 ] && exit 0

adb -s "$SERIAL" shell "am force-stop $PKG" >/dev/null 2>&1 || true
adb -s "$SERIAL" shell "am start -n $PKG/.AliasActivityDefault" >/dev/null 2>&1
sleep 18

echo "[config] profile=$PROFILE applied to $SERIAL"
python3 "$ROOT/kit/scripts/module_report.py" --adb "$SERIAL" | grep -E "打开的功能|没有证据|说明" || true
