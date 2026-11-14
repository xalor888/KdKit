#!/usr/bin/env bash
# kuaidui-kit / env_up.sh — bring up the project's own emulator the way the kit needs it.
#
# Why a script: the Magisk ramdisk is mandatory (`-ramdisk infra/ramdisk-magisk.img`);
# without it magiskd/vectord never start and the KdKit module cannot inject. Booting the
# AVD without it *looks* fine and silently produces a device the module can never use.
#
#   ./kit/scripts/env_up.sh [avd] [port]
#       default: kd1 5558      (project-owned AVD, see ROADMAP §4)
#
# Leaves behind: rooted device, permissive SELinux, frida-server (`xdsvc`) on 31337 with the
# port forwarded, and a device the KdKit module can inject into.
set -euo pipefail

AVD="${1:-kd1}"
PORT="${2:-5558}"
SERIAL="emulator-$PORT"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"
ADB="$SDK_ADB"
EMU="$SDK_EMU"



# "Magisk 在不在" —— 单独成函数：判定逻辑只写一次，避免两处口径漂移。
magisk_present() { "$ADB" -s "$SERIAL" shell 'ls /data/adb/magisk/magisk >/dev/null 2>&1'; }

if "$ADB" -s "$SERIAL" get-state >/dev/null 2>&1; then
  echo "[env] $SERIAL already up"
else
  echo "[env] booting $AVD -> $SERIAL"
  nohup "$EMU" -avd "$AVD" -port "$PORT" -no-window -no-audio -no-snapshot \
    -gpu swiftshader_indirect -no-boot-anim -memory 4096 -cores 4 \
    -ramdisk "$ROOT/infra/ramdisk-magisk.img" >"$ROOT/work/emu_boot_$AVD.log" 2>&1 &
fi

echo -n "[env] waiting for boot"
# **先看 emulator 进程还在不在**（2026-11-02 补）。
#
# 旧版只轮询 `sys.boot_completed`，连等 60×5=300 秒。若 AVD 名写错、
# ramdisk 路径不对、或端口被占，emulator 进程早就退出了 —— 而那 300 秒
# 全在等一个**永远不会来**的设备，最后也没有一句"它其实没起来"。
_booted=0
for _ in $(seq 1 60); do
  b="$("$ADB" -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [ "$b" = "1" ]; then _booted=1; break; fi
  # 进程没了 + adb 也看不见 ⇒ 不可能自己好起来，立刻停
  if ! pgrep -f "qemu-system-aarch64-headless -avd $AVD" >/dev/null 2>&1 \
     && ! "$ADB" devices | grep -q "^$SERIAL[[:space:]]"; then
    echo
    echo "[env] FAIL: emulator for avd=$AVD is not running and $SERIAL never appeared" >&2
    tail -5 "$ROOT/work/emu_boot_$AVD.log" 2>/dev/null | sed 's/^/[env]       /' >&2
    exit 1
  fi
  echo -n .
  sleep 5
done
echo
[ "$_booted" = "1" ] || { echo "[env] FAIL: boot did not complete in 300s" >&2; exit 1; }

"$ADB" -s "$SERIAL" root >/dev/null 2>&1 || true
sleep 2
"$ADB" -s "$SERIAL" shell setenforce 0 || true

# **没有 Magisk 就自己修，别让用户去手工重跑**（2026-11-02 改）。
#
# 旧版只是打印一句 "kill it and re-run this script." —— 也就是说：
# 脚本**已经知道**这台设备起错了（没带 patched ramdisk），却把唯一有效的动作
# 推给了人。而那个动作 `recover_device.sh --force` 本来就在仓库里。
#
# 自动化链路里最贵的一句话就是"请你手动重来"：它把一次可自愈的失败变成一次人工介入，
# 而人工介入等于**卡死**（2026-11-02 就是这么卡住整晚的）。
NO_MAGISK_REBOOT="${NO_MAGISK_REBOOT:-1}"
if ! magisk_present; then
  if [ "$NO_MAGISK_REBOOT" = "1" ]; then
    echo "[env] no Magisk — this boot lost the patched ramdisk; restarting via recover_device.sh --force"
    "$ROOT/kit/scripts/recover_device.sh" --force >/dev/null 2>&1 || true
    NO_MAGISK_REBOOT=0
  fi
fi
if ! magisk_present; then
  echo "[env] FAIL: still no Magisk after one forced restart." >&2
  echo "[env]       the AVD's ramdisk is wrong, or infra/ramdisk-magisk.img is missing:" >&2
  ls -l "$ROOT/infra/ramdisk-magisk.img" 2>&1 | sed 's/^/[env]       /' >&2
  exit 1
fi

# frida-server under a non-default name; the app scans for "frida_server"
if ! "$ADB" -s "$SERIAL" shell 'ls /data/local/tmp/xdsvc >/dev/null 2>&1'; then
  echo "[env] pushing frida-server -> /data/local/tmp/xdsvc"
  "$ADB" -s "$SERIAL" push "$ROOT/work/frida-server" /data/local/tmp/xdsvc >/dev/null
  "$ADB" -s "$SERIAL" shell chmod 755 /data/local/tmp/xdsvc
fi
"$ADB" -s "$SERIAL" shell 'pkill -f xdsvc 2>/dev/null' || true
sleep 1
"$ADB" -s "$SERIAL" shell 'setsid nohup /data/local/tmp/xdsvc -l 0.0.0.0:31337 >/dev/null 2>&1 &' || true
sleep 3
"$ADB" -s "$SERIAL" forward tcp:31337 tcp:31337 >/dev/null

echo "[env] --- status ---"
"$ADB" -s "$SERIAL" shell 'printf "sdk=%s magisk=%s\n" "$(getprop ro.build.version.sdk)" "$(magisk -v 2>/dev/null || echo none)"'
"$ADB" -s "$SERIAL" shell 'ps -A | grep -q vectord && echo "vectord: running" || echo "vectord: MISSING"'
"$ADB" -s "$SERIAL" shell 'ps -A | grep -q xdsvc && echo "frida-server: running on 31337" || echo "frida-server: MISSING"'
"$ADB" -s "$SERIAL" shell 'pm path com.kuaiduizuoye.scan >/dev/null 2>&1 && echo "快对: installed" || echo "快对: MISSING"'
"$ADB" -s "$SERIAL" shell 'pm path dev.xalor.kdkit >/dev/null 2>&1 && echo "KdKit: installed" || echo "KdKit: MISSING"'
echo "[env] serial=$SERIAL  (use: adb -s $SERIAL ...)"

# **收尾自检**（2026-11-02 改）：上面那段只是 `printf` 状态，退出码永远是 0 ——
# 于是"设备没 root / 没 magisk / frida 没起来"这些**致命的**前置条件失败时，
# 脚本仍然返回成功，下游一路带着坏环境跑，直到某个门禁莫名变红。
# 现在把结论变成退出码：这三样是"kit 能不能用"的硬条件，缺一样就 exit 1。
_env_fail=0
_env_bad() { printf '[env] FAIL: %s\n' "$1" >&2; _env_fail=$((_env_fail+1)); }

_ver="$("$ADB" -s "$SERIAL" shell 'magisk -v 2>/dev/null' | tr -d '\r')"
[ -n "$_ver" ] || _env_bad "magisk 不在（没有 patched ramdisk ⇒ 模块永远注入不了）"

_enf="$("$ADB" -s "$SERIAL" shell getenforce 2>/dev/null | tr -d '\r')"
[ "$_enf" = "Permissive" ] || _env_bad "SELinux=${_enf}（需要 Permissive）"

"$ADB" -s "$SERIAL" shell 'ps -A | grep -q xdsvc' >/dev/null 2>&1 \
  || _env_bad "frida-server (xdsvc) 没在跑"

"$ADB" -s "$SERIAL" shell 'pm path com.kuaiduizuoye.scan >/dev/null 2>&1' \
  || _env_bad "宿主 com.kuaiduizuoye.scan 没装"

if [ "$_env_fail" -gt 0 ]; then
  echo "[env] ✗ 环境不可用（${_env_fail} 项不满足），别拿它跑门禁" >&2
  exit 1
fi
echo "[env] ✓ 环境自检通过：magisk / SELinux=Permissive / frida / 宿主"

# 设备健康自检（统一走 device_health.py：显示管线卡死时会明确告诉我们 reboot）
#
# **失败必须可见**（2026-11-03 修）：原来是 `… || true` ⇒ 设备不健康时
# 这个脚本照样返回 0，而它是**整条自动化链的入口** ——
# 后面每一轮都会带着一台坏设备跑，直到某个门禁莫名变红。
_health_rc=0
python3 "$ROOT/kit/scripts/device_health.py" --adb "$SERIAL" || _health_rc=$?
if [ "$_health_rc" -ne 0 ]; then
  echo "[env] ✗ 设备健康自检未过（rc=${_health_rc}）—— 别拿它跑门禁" >&2
  exit 1
fi

# 起来之后顺手把模块配置收敛到常规档（诊断开、守卫开、实验项关）——避免"设备起来了但配置是上一轮的实验态"。
#
# **不许把退出码丢在管道里**（2026-11-03 修）：
#     set_config.sh … 2>&1 | sed 's/^/[env] /'
# 这条管道的退出码是 **sed 的**，永远是 0 ⇒ 配置写入失败也报告成功。
# 今天已经在三处为"退出码被管道吃掉"修过（verify_membership /
# acceptance 的 grep -c / tap_texts），这是第四处。
# **配置链路的前置条件**（2026-11-08 加）：LSPosed 的 prefs 在 enforcing 下会被
# SELinux 挡住 ⇒ 模块读到空 map ⇒ 所有 defaultOn=false 的功能静默关闭。
# 判据：宿主日志里 `xprefs published=… all={}` 是空的就是断了。
# 必须在 set_config 之前跑，否则"写进去"与"读得到"两件事都会被误判成功。
if [ -x "$ROOT/kit/scripts/fix_xposed_prefs_selinux.sh" ]; then
  "$ROOT/kit/scripts/fix_xposed_prefs_selinux.sh" --adb "$SERIAL" 2>&1 | sed 's/^/[env] /' || true
fi

if [ -x "$ROOT/kit/scripts/set_config.sh" ]; then
  echo "[env] applying regular module config"
  _cfg_log="$(mktemp)"
  if "$ROOT/kit/scripts/set_config.sh" --adb "$SERIAL" --profile regular >"$_cfg_log" 2>&1; then
    sed 's/^/[env] /' "$_cfg_log"
  else
    _cfg_rc=$?
    sed 's/^/[env] /' "$_cfg_log"
    echo "[env] ✗ 模块配置写入失败（rc=${_cfg_rc}）—— 开关会停在上一轮的状态" >&2
    rm -f "$_cfg_log"
    exit 1
  fi
  rm -f "$_cfg_log"
fi
