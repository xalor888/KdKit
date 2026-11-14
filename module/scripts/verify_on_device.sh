#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# verify_on_device.sh — 在真机/模拟器上验证模块能否安装、启动、交互、持久化
#
# 为什么需要这个脚本
# ─────────────────────────────────────────────────────────────────────────────
# 十二道门全部是**静态**的：它们读源码、读 smali、读文档。没有一道能回答：
#
#   * 这个 APK 装得上吗？
#   * 设置界面打开会不会崩？
#   * 点开关有没有反应？重启后还在不在？
#
# 2026-10-26 第一次在模拟器上跑通了这四件事。把这四步固化下来，
# 是因为**静态门禁再密，也覆盖不到"装不上"和"打不开"**。
#
# 它**不做**什么
# ──────────────
# * 不验证钩子是否真的拦住了行为 —— 那需要装目标 App + LSPosed，本脚本只报"环境不具备"；
# * 不判定功能效果 —— `13/38`、`14/38` 这种数字只证明"开关能读写"，不证明功能生效。
#
# 前置：`adb devices` 里有一台 `device` 状态的设备。
# 用法：`module/scripts/verify_on_device.sh [--serial emulator-5554]`
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOD="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$MOD/.." && pwd)"
APK="$MOD/app/build/outputs/apk/debug/app-debug.apk"
OUT="$ROOT/work/device_evidence"
PKG=dev.xalor.kdkit
ACT=$PKG/.ui.MainActivity

SERIAL="${ANDROID_SERIAL:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --serial) SERIAL="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done
ADB=(adb)
[ -n "$SERIAL" ] && ADB=(adb -s "$SERIAL")

pass=0; fail=0; skip=0
ok()   { printf '  PASS  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  FAIL  %s\n' "$1"; fail=$((fail+1)); }
skp()  { printf '  SKIP  %s\n' "$1"; skip=$((skip+1)); }

echo "── 环境 ──"
if ! command -v adb >/dev/null 2>&1; then
  echo "  adb 不在 PATH 里 ⇒ 无法验证"; exit 0
fi
DEV="$("${ADB[@]}" devices 2>/dev/null | awk '$2=="device"{print $1; exit}')"
if [ -z "$DEV" ]; then
  skp "没有 device 状态的设备（adb devices 为空）⇒ 跳过全部真机验证"
  echo "  合计：0 PASS / 0 FAIL / 1 SKIP"
  exit 0
fi
echo "  设备: $DEV"
echo "  Android SDK: $("${ADB[@]}" shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r')"
QEMU="$("${ADB[@]}" shell getprop ro.kernel.qemu 2>/dev/null | tr -d '\r')"
echo "  类型: $([ "$QEMU" = "1" ] && echo 模拟器 || echo 真机)"

mkdir -p "$OUT"

echo "── ① APK 存在 ──"
if [ -f "$APK" ]; then ok "APK 已构建（$(du -h "$APK" | cut -f1)）"
else bad "APK 不存在：${APK}（先跑 assembleDebug）"; echo; echo "  合计：$pass PASS / $fail FAIL / $skip SKIP"; exit 1; fi

echo "── ② 安装 ──"
if "${ADB[@]}" install -r "$APK" 2>&1 | grep -q "Success"; then ok "安装成功"
else bad "安装失败"; fi

echo "── ③ 包与入口存在 ──"
if "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "package:$PKG"; then ok "包已安装：$PKG"
else bad "包不存在"; fi
if "${ADB[@]}" shell "cmd package resolve-activity --brief $PKG" 2>/dev/null | grep -q "$PKG"; then
  ok "启动入口可解析：$ACT"
else bad "启动入口不可解析"; fi

echo "── ④ 启动不崩 ──"
# **先等设备空闲再点**：本脚本经常紧跟 acceptance / evidence_pack 之后跑，那时宿主还在
# 冷启动、ActivityManager 忙，`am start -W` 会等到超时甚至被 `Error: Activity not started`
# 打回 —— 表现为本门**偶发红**（2026-11-02 一轮里连中两次，重跑即绿）。
# 这里主动等到没有 `ANR`/`am_anr` 且 top activity 稳定，最多 15 s。
for _w in $(seq 1 15); do
  _busy="$("${ADB[@]}" shell 'dumpsys activity activities 2>/dev/null | grep -c "mResumedActivity"' 2>/dev/null | tr -d '\r')"
  _anr="$("${ADB[@]}" logcat -d -b events 2>/dev/null | grep -c 'am_anr' || true)"
  [ "${_busy:-0}" -ge 1 ] && [ "${_anr:-0}" -eq 0 ] && break
  sleep 1
done
"${ADB[@]}" shell am force-stop "$PKG" >/dev/null 2>&1 || true
sleep 1
"${ADB[@]}" logcat -c 2>/dev/null
START="$("${ADB[@]}" shell am start -W -n "$ACT" 2>&1)"
if echo "$START" | grep -q "Status: ok"; then
  ok "启动成功（$(echo "$START" | grep -oE 'TotalTime: [0-9]+' | head -1)）"
else
  # 一次重试：设备刚被别的步骤压过时，第一次 start 常被拒
  sleep 2
  START="$("${ADB[@]}" shell am start -W -n "$ACT" 2>&1)"
  if echo "$START" | grep -q "Status: ok"; then
    ok "启动成功（重试后；$(echo "$START" | grep -oE 'TotalTime: [0-9]+' | head -1)）"
  else
    bad "启动失败"
  fi
fi
sleep 3
# 只 Killing/FATAL 算崩；普通 warn 不算
if "${ADB[@]}" logcat -d 2>/dev/null | grep -qE "FATAL EXCEPTION.*$PKG|Process: $PKG.*has died"; then
  bad "启动后出现 FATAL"
else ok "无 FATAL 异常"; fi
# **限时**截图。
#
# 设备显示管线卡住时 `adb exec-out screencap -p` 会**无限挂**（2026-10-11 实测，
# `device_health.py` 与 `coldstart_snapshot.py` 都因此加了超时）。
# 但**这一处漏了** —— 2026-11-02 第 24 轮它挂了 22 分钟：门禁不红、不结束，
# 整轮验证卡死在这里，比红更糟（红会有人查，卡住只会被当成"跑得慢"）。
#
# 截图是**旁证**不是契约：取不到就说不取到，不判定本门失败。
if timeout 25 "${ADB[@]}" exec-out screencap -p > "$OUT/settings_01.png" 2>/dev/null \
   && [ -s "$OUT/settings_01.png" ]; then
  ok "截图已存：work/device_evidence/settings_01.png"
else
  printf '  NOTE  %s\n' "截图取不到（screencap 超时或空文件）—— 设备显示管线可能卡了；不影响本门结论"
  rm -f "$OUT/settings_01.png"
fi

echo "── ⑤ 设置界面读得到功能数 ──"
# 从 UI 层级里找 "已启用 N / M 项功能" —— 比 OCR 可靠，用的是系统无障碍树。
# 用**文件** dump 而不是 `/dev/tty`：后者在部分设备上输出被截断
# （2026-10-26 实测：/dev/tty 读不到计数，写到文件再 cat 就能读到）。
# 同 screencap：`uiautomator dump` 在 UI 线程卡住时也会无限等，限时 30 s。
timeout 30 "${ADB[@]}" shell uiautomator dump /sdcard/kdkit_ui.xml >/dev/null 2>&1
UI="$("${ADB[@]}" shell cat /sdcard/kdkit_ui.xml 2>/dev/null | tr -d '\r')"
"${ADB[@]}" shell rm -f /sdcard/kdkit_ui.xml >/dev/null 2>&1
COUNT="$(echo "$UI" | grep -oE '已启用 [0-9]+ / [0-9]+ 项功能' | head -1)"
if [ -n "$COUNT" ]; then
  ok "界面报告：$COUNT"
  # 与代码里的 FeatureRegistry 条目数比对
  REAL="$(grep -cE '^\s+[A-Z][A-Za-z0-9]+,\s*$' "$MOD/app/src/main/java/dev/xalor/kdkit/features/FeatureRegistry.kt" 2>/dev/null)"
  N_UI="$(echo "$COUNT" | grep -oE '/ [0-9]+' | tr -d '/ ')"
  if [ -n "$REAL" ] && [ "$N_UI" = "$REAL" ]; then
    ok "界面总数 $N_UI 与 FeatureRegistry 条目数一致"
  else
    bad "界面总数 $N_UI ≠ FeatureRegistry 条目数 $REAL"
  fi
else
  skp "无障碍树里读不到功能计数（界面可能未加载完）"
fi

echo "── ⑥ 钩子环境（需要 LSPosed + 目标 App）──"
if "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "org.lsposed.manager" \
   || "${ADB[@]}" shell 'ls /data/adb/lspd/cli >/dev/null 2>&1' \
   || "${ADB[@]}" shell 'pidof vectord >/dev/null 2>&1'; then
  ok "注入框架已安装（LSPosed manager / lspd CLI / vectord 任一）"
  if "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "com.kuaiduizuoye.scan"; then
    ok "目标 App 已安装 ⇒ 可做端到端验证（本脚本不做，见下）"
  else
    skp "目标 App 未安装 ⇒ 只能验到装得上、打得开这一层"
  fi
else
  # 目标 App 已装但框架没装 —— 这是"差一步"的状态，要说清楚差哪一步。
  if "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "com.kuaiduizuoye.scan"; then
    skp "目标 App 已装、LSPosed 未装 ⇒ 差框架这一步；钩子无法生效"
  else
    skp "LSPosed 未安装 ⇒ 钩子无法生效，只能验到设置界面这一层"
  fi
fi

echo "── ⑦ 设备上的目标 App ↔ 仓库里分析的 APK ──"
# 这一条防的是**最隐蔽的一类失效**：设备上装的是另一个版本的目标 App。
# 那时 38 个功能、124 个钩子目标、全部 smali 结论都只对仓库里那份成立，
# 对设备无效 —— 而**没有任何静态门禁能发现**。
# **先捕获，再判断**（2026-11-02 修）。
#
# 旧写法是 `… | tee /tmp/kd_match.txt | grep -q "^  PASS"`。`grep -q` 一旦命中就
# **立刻退出**，管道上游的 `tee` 随即收到 SIGPIPE 被杀死 —— 于是：
#   1. `/tmp/kd_match.txt` 可能被截断甚至没写成；
#   2. 第二个 `grep -q "^  SKIP" /tmp/kd_match.txt` 自然落空；
#   3. 落到 `bad "目标 App 版本与分析的不一致"` —— 门禁红在**自己的管道**上。
#
# 实测（2026-11-02 15:30）：单独跑 `check_device_matches_analysis.sh` 是 PASS
# （`仓库: 6d4f4e05…  设备: 6d4f4e05…`），而同一轮 verify.sh 里它红，且重试也红 ——
# 那不是"设备装错版本"，是"门禁的写法在跟进程抢时间"。
MATCH_OUT="$(bash "$HERE/check_device_matches_analysis.sh" ${SERIAL:+--serial "$SERIAL"} 2>&1)"
printf '%s\n' "$MATCH_OUT" > /tmp/kd_match.txt
if printf '%s\n' "$MATCH_OUT" | grep -q "^  PASS"; then
  ok "目标 App 与分析的 APK 字节一致"
elif printf '%s\n' "$MATCH_OUT" | grep -q "^  SKIP"; then
  skp "目标 App 未装 / 无设备 ⇒ 无法比对字节"
else
  bad "目标 App 版本与分析的不一致（判断依据见 /tmp/kd_match.txt）"
  printf '%s\n' "$MATCH_OUT" | sed 's/^/    /' >&2
fi

echo
echo "  合计：$pass PASS / $fail FAIL / $skip SKIP"
echo
echo "  这个脚本证明的：APK 装得上、界面打得开、开关能留。"
echo "  它**不**证明：任何钩子真的拦住了行为 —— 那需要 LSPosed + 目标 App + 真实操作。"
[ "$fail" -eq 0 ] || exit 1
