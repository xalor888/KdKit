#!/usr/bin/env bash
# kuaidui-kit / recover_device.sh — 设备恢复"三步配方"（2026-10-13 第三次故障后固化成脚本）
#
# 为什么需要：本会话里设备**三次**整体卡死，每次都是同一套动作：
#   ① 杀 qemu 进程
#   ② **清 AVD 锁**（第三次新学：`snapshot.lock.lock` 会让新实例直接 FATAL 退出 ✗）
#   ③ 带 `infra/ramdisk-magisk.img` 重启，然后等 boot 完成 + 跑 env_up.sh
#
#    ./kit/scripts/recover_device.sh            # 自动判断：健康则什么都不做
#    ./kit/scripts/recover_device.sh --force    # 无条件恢复
#
# 判据（adbd 活着 ≠ 系统活着 ✗）：`pidof system_server` 与 `cmd activity` —— 见 device_health.py 的 framework_alive()
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
# 位置参数（2026-11-02 补）：第一个参数可以是 **serial**（`emulator-5558`）或 **avd**（`kd1`）。
#
# 为什么：旧版只认环境变量，位置参数被**静默忽略**。我当晚就是这样踩的 ——
# 敲了 `recover_device.sh emulator-5558`，脚本照 `AVD=kd1` 干自己的事，
# 一句提示都没有。命令看起来"跑了"，其实参数根本没进去。
# **静默忽略用户的输入**和静默跳过测试是同一类问题：看起来做了什么，其实没做。
# 先落默认值，再让位置参数覆盖 —— 脚本开了 `set -u`，顺序反了会在引用时炸 `unbound variable`。
# （第一版就是写反了，测试当场报 `AVD: unbound variable`。）
SERIAL=${SERIAL:-emulator-5558}
AVD=${AVD:-kd1}
PORT=${PORT:-5558}

for _arg in "$@"; do
  case "$_arg" in
    --*|-*) continue ;;                       # 开关交给下面的 --force 处理
    emulator-[0-9]*) SERIAL="$_arg"; PORT="${_arg#emulator-}" ;;
    *) AVD="$_arg" ;;
  esac
  echo "[recover] arg '$_arg' => serial=$SERIAL avd=$AVD port=$PORT"
done
RAMDISK=${RAMDISK:-infra/ramdisk-magisk.img}
source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"

framework_ok() {
  local out pid act
  out=$(adb -s "$SERIAL" shell 'printf "%s|%s" "$(pidof system_server)" "$(cmd activity 2>&1 | head -1 | cut -c1-12)"' 2>/dev/null | tr -d '\r')
  pid=${out%%|*}; act=${out#*|}
  [ -n "${pid// /}" ] && case "$act" in Activity*) return 0;; esac
  return 1
}

# 2026-10-15 加 ✓（R547 的设备事故 ✓）：**"能连上"不等于"能用"** ✗ ——
# 01:23 那次恢复失败后，设备起来了但**没有 root** ✗（/data/adb 全 Permission denied ✓），
# 而本脚本却答"framework healthy -> nothing to do" ✗★ ⇒ **判据缺一条** ✓。
root_ok() {
  local r
  r=$(adb -s "$SERIAL" shell 'su -c id' 2>/dev/null | tr -d '\r')
  case "$r" in *uid=0*) return 0;; esac
  return 1
}

if [ "${1:-}" != "--force" ]; then
  if framework_ok && root_ok; then
    echo "[recover] framework healthy -> nothing to do (use --force to force)"
    exit 0
  fi
  framework_ok && echo "[recover] 设备在线但**没有 root** ✗ ⇒ 需要带 magisk ramdisk 重启 ✓"
  echo "[recover] framework unhealthy -> three-step recovery"
fi

echo "[recover] 1/3 kill qemu (avd=$AVD)"
pkill -f "qemu-system-aarch64-headless -avd $AVD" 2>/dev/null
pkill -f "adb -s $SERIAL" 2>/dev/null

# **确认它真的死了**（2026-11-02 补）。
#
# 旧版 `pkill` 之后就 `sleep 4` 往下走 —— 若 pkill 没匹配到（进程名变了、
# 参数顺序变了、或者 AVD 名不对），旧实例还在占着端口，新实例起不来，
# 表现为"等 4 分钟仍 not ready"，而**日志里看不出是没杀干净**。
# 杀掉之后必须**看见它不在**，否则升级到 -9 并明说。
still_alive() { pgrep -f "qemu-system-aarch64-headless -avd $AVD" >/dev/null 2>&1; }
for _i in 1 2 3 4 5; do
  still_alive || break
  sleep 2
done
if still_alive; then
  echo "[recover]   pkill 之后进程仍在 ⇒ 升级 -9"
  pkill -9 -f "qemu-system-aarch64-headless -avd $AVD" 2>/dev/null
  sleep 3
fi
if still_alive; then
  echo "[recover] ✗ 无法杀掉 avd=$AVD 的 qemu；它占着端口，重启注定失败。"
  echo "[recover]   实际在跑的实例："
  # macOS 的 pgrep 没有 `-a`：用 ps 取命令行，别依赖 GNU 扩展。
  ps -o pid=,command= -p "$(pgrep qemu-system | tr '\n' ',' | sed 's/,$//')" 2>/dev/null \
    | cut -c1-170 | sed 's/^/     /'
  exit 1
fi
# **另一种"没杀干净"：进程没了、adb 还看得见它。**
#
# 2026-11-02 实测：把 AVD 名写错（`kd9`）时 pkill 匹配不到任何进程，
# 于是旧实例仍在跑 —— 而后面"等 adb 看见 serial"会**立刻满足**，
# 脚本便以为"我启动的那个实例起来了"，实际上什么也没重启。
# "看得见 serial"不是"我的实例起来了"的充分条件，所以这里把前置条件说死：
# 杀完之后**必须看不到**它，否则直接失败。
if adb devices | grep -q "^$SERIAL[[:space:]]"; then
  echo "[recover] FAIL: $SERIAL still visible to adb after kill - old instance is alive."
  echo "[recover]       实际在跑的实例（AVD 名可能写错了）："
  # macOS 的 pgrep 没有 `-a`：用 ps 取命令行，别依赖 GNU 扩展。
  ps -o pid=,command= -p "$(pgrep qemu-system | tr '\n' ',' | sed 's/,$//')" 2>/dev/null \
    | cut -c1-170 | sed 's/^/     /'
  echo "[recover]       pass the right AVD name, or unset AVD to use the default."
  exit 1
fi
sleep 1

echo "[recover] 2/3 clear AVD locks"
rm -rf "$HOME/.android/avd/$AVD.avd"/*.lock "$HOME/.android/avd/$AVD.avd"/snapshots/*.lock 2>/dev/null

echo "[recover] 3/3 relaunch with magisk ramdisk"
nohup "$SDK_EMU" -avd "$AVD" -port "$PORT" -no-window -no-audio \
  -no-snapshot-load -no-snapshot-save -gpu swiftshader_indirect -no-boot-anim -memory 4096 -cores 4 \
  -ramdisk "$PWD/$RAMDISK" > work/emu_boot_$AVD.log 2>&1 &
disown

echo "[recover] waiting for boot (max 4 min)"
# 先等 adb **看见**这个 serial，再谈 boot_completed。
# 旧版直接轮询 `adb -s $SERIAL ...`：设备还没注册时它每 5 秒返回一次空，
# 4 分钟全部空转，最后只说 "not ready"，看不出是"没起来"还是"起来了但没连上"。
_seen=0
for _ in $(seq 1 60); do
  if adb devices | grep -q "^$SERIAL[[:space:]]"; then _seen=1; break; fi
  sleep 2
done
if [ "$_seen" -eq 0 ]; then
  # ASCII-only message: a stray non-ASCII byte next to `$SERIAL` made bash
  # treat the variable name as `SERIAL<garbage>` (unbound variable).
  echo "[recover] FAIL: adb did not see $SERIAL within 120s - instance did not come up"
  tail -5 "work/emu_boot_$AVD.log" 2>/dev/null | sed 's/^/     /'
  exit 1
fi
echo "[recover]   adb sees $SERIAL; waiting for boot_completed"
for _ in $(seq 1 48); do
  [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ] && break
  sleep 5
done

if framework_ok; then
  echo "[recover] framework ready -> env_up.sh"
  ./kit/scripts/env_up.sh "$AVD" "$PORT" 2>&1 | grep -E "health|frida|功能" | head -4
  echo "[recover] done (next: start host app, check HookCore ready)"
  exit 0
fi
echo "[recover] still not ready - see work/emu_boot_$AVD.log"
exit 1
