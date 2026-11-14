#!/bin/bash
# kuaidui-kit / watchdog.sh -- device watchdog (2026-10-12)
# Device has vanished 4 times this session. This script checks and auto-recovers.
# Usage: ./kit/scripts/watchdog.sh [--adb SERIAL] [--force]
SER="${ADB_SERIAL:-emulator-5558}"
FORCE=0
CHECK_ONLY=0   # --check-only: report only, never touch the device
while [ $# -gt 0 ]; do
  case "$1" in
    --adb) SER="$2"; shift 2;;
    --force) FORCE=1; shift;;
    --check-only) CHECK_ONLY=1; shift;;
    *) shift;;
  esac
done
source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"
LOG="work/watchdog.log"
mkdir -p work

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

if adb devices 2>/dev/null | grep -q "^${SER}[[:space:]]*device"; then
  # device present: also check the framework layer
  if python3 kit/scripts/device_health.py --adb "${SER}" >/dev/null 2>&1; then
    echo "$(stamp) OK   device=${SER} framework=ok" >> "${LOG}"
    exit 0
  fi
  echo "$(stamp) WARN device=${SER} present but framework unhealthy -> recovering" >> "${LOG}"
else
  echo "$(stamp) DOWN device=${SER} not in adb devices -> recovering" >> "${LOG}"
fi

if [ "${CHECK_ONLY}" = "1" ]; then
  echo "$(stamp) CHECK-ONLY: would recover device=${SER} (no action taken)" >> "${LOG}"
  exit 1
fi

# `recover_device.sh` **只认 `--force`**，设备号从**环境变量 SERIAL** 读（见其 15 行）。
# 旧写法传 `--adb "$SER"` ⇒ 未知参数被拒 + 换设备号后永远恢复 5558 那台。
# 这条必须正确，否则模拟器一掉线就再也起不来。
if [ "${FORCE}" = "1" ]; then
  SERIAL="${SER}" bash kit/scripts/recover_device.sh --force >> "${LOG}" 2>&1
else
  SERIAL="${SER}" bash kit/scripts/recover_device.sh >> "${LOG}" 2>&1
fi
rc=$?
echo "$(stamp) RECOVER exit=${rc}" >> "${LOG}"
exit ${rc}
