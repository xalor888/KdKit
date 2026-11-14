#!/usr/bin/env bash
# kuaidui-kit / checkup.sh — one-command checkup (2026-10-12)
#
# For the next session: runs the key checks and prints one screen of summary.
#   ./kit/scripts/checkup.sh
#   ADB_SERIAL=emulator-5556 ./kit/scripts/checkup.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
SER="${ADB_SERIAL:-emulator-5558}"
source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"

# 2026-10-12：先确认设备在 ✓ —— 否则后面每步都会"安静地"打错误 ✓，
# 而看输出的人会以为"跑完了" ✗（本轮的纪律：**安静必须被验证** ✓）。
if ! adb devices 2>/dev/null | grep -q "^${SER}[[:space:]]\+device"; then
  echo "=== checkup @ ${SER} ==="
  echo "✗ 设备 ${SER} 不在（adb devices 里没有它）"
  echo "  ⇒ 跑 ./kit/scripts/recover_device.sh（三步恢复 ✓）或换 ADB_SERIAL=<别的设备>"
  exit 2
fi

echo "=== checkup @ ${SER} ($(date '+%Y-%m-%d %H:%M')) ==="

echo "--- (1) device & framework ---"
python3 kit/scripts/device_health.py --adb "${SER}" 2>&1 | tail -1

echo "--- (1a) docs claim numbers? ---"
python3 kit/scripts/docs_claims.py 2>&1 | tail -1

echo "--- (1b) session time (single source) ---"
python3 kit/scripts/session_time.py 2>&1 | tail -1

echo "--- (2) module: features alive? ---"
python3 kit/scripts/module_activity.py --adb "${SER}" 2>&1 | tail -1

echo "--- (3) eight surfaces (last 6 packs) ---"
python3 kit/scripts/surface_trends.py --last 6 2>&1 | tail -1
grep -E "^\* \*\*" work/SURFACE_TRENDS.md 2>/dev/null | head -3 | cut -c1-110

echo "--- (3b) tools report? (rule 18) ---"
./kit/scripts/tool_sanity.sh 2>&1 | tail -1

echo "--- (3c) AB 表结构（第九张面）---"
CUR=$(ls -t work/packs/*/responses.json 2>/dev/null | head -1)
PRV=$(ls -t work/packs/*/responses.json 2>/dev/null | head -2 | tail -1)
if [ -n "${CUR}" ]; then
  python3 kit/scripts/ab_diff.py --current "${CUR}" ${PRV:+--previous "${PRV}"} 2>&1 | tail -1
fi

echo "--- (4) gates ---"
python3 kit/scripts/acceptance.py --adb "${SER}" 2>&1 | tail -1
python3 kit/scripts/selftest.py 2>&1 | tail -1

echo "--- (5) open items ---"
grep -m1 "待解释清单" work/UNEXPLAINED.md 2>/dev/null | cut -c1-100
grep -c "^| \*\*" work/UNEXPLAINED.md 2>/dev/null | sed 's/^/  UNEXPLAINED 条目: /'
echo "--- (6) what does this system look like? ---"
echo "  work/SYSTEM_OVERVIEW.md — nine surfaces + five mechanisms + three states (one page)"
echo "  entry points: SURFACE_TRENDS.md (nine surfaces) / ARTIFACT_LIFECYCLE.md (alive files + wiring)"
echo "  if you get an account tomorrow: work/ACCOUNT_DAY_PLAYBOOK.md (five steps: baseline -> login -> check -> features -> write back)"
echo "  still waiting on: account (ACCOUNT_QUEUE.md) / real device (ads visibility, real-device anti-debug)"
echo "  full awaiting list (what is armed + what triggers it): work/AWAITING.md"
echo "  time windows (what to look at, and when): work/TIME_WINDOWS.md"
# 2026-10-15 加 ✓（规则 24 第四类 ✓）：**"缺能力"与"缺什么"并列** ✓
python3 - <<'PYEOF2'
import re
s = open('work/AWAITING.md', encoding='utf-8').read()
gap = s.count('能力缺口')
print(f"  capability gaps (need a tool feature, or accept): {gap} section(s) in work/AWAITING.md")
PYEOF2

echo "=== done (for a full evidence pack: evidence_pack.py --adb ${SER} --tag rNNN) ==="
