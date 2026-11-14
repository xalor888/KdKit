#!/usr/bin/env bash
# kuaidui-kit / preflight.sh — 起手检查：保证设备在位、模块在位、配置在位。
#
# 为什么需要：唯一的高频故障是"模拟器掉线"（2026-11-01 夜间就掉过一次，
# 表现为 `adb: device 'emulator-5558' not found`）。每次开始前先跑这一条，把三件事收敛成一条命令：
#   ① 设备在线且 framework 活着（adbd 活着 ≠ 系统活着）
#   ② 目标 App 与仓库分析的 APK 字节一致
#   ③ 模块的 config 发布文件在位（install -r 会重置它，开关会回到全部默认）
#
#   ./kit/scripts/preflight.sh [serial]
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SER="${1:-${SERIAL:-emulator-5558}}"
source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"
cd "$ROOT" || exit 1

say() { printf '[ready] %s\n' "$*"; }

if ! adb -s "$SER" get-state >/dev/null 2>&1; then
  say "设备不在，serial=${SER} ⇒ 走 env_up.sh 冷启（带 magisk ramdisk）"
  bash kit/scripts/env_up.sh kd1 5558 >/tmp/preflight_env_up.log 2>&1 || {
    say "env_up 失败，见 /tmp/preflight_env_up.log"; exit 1; }
fi

if ! adb -s "$SER" shell 'pidof system_server' >/dev/null 2>&1 || \
   [ -z "$(adb -s "$SER" shell 'pidof system_server' 2>/dev/null | tr -d '\r')" ]; then
  say "framework 不活 ⇒ recover_device.sh"
  SERIAL="$SER" bash kit/scripts/recover_device.sh >/tmp/preflight_recover.log 2>&1 || true
fi

say "设备: $(adb -s "$SER" get-state 2>&1 | tr -d '\r')"

# 注意：不能写 `cmd | grep -q` —— `grep -q` 命中即退，producer 吃 SIGPIPE，
# 在 `set -o pipefail` 下整条管道返回非 0，于是"匹配成功"被判成不一致（实测踩到）。
_MATCH_OUT="$(bash module/scripts/check_device_matches_analysis.sh --serial "$SER" 2>/dev/null)"
if printf '%s' "$_MATCH_OUT" | grep -q 'PASS'; then
  say "目标 App 与分析的 APK 字节一致 ✓"
else
  say "目标 App 与分析的 APK 不一致（或未装）⇒ 装 com.kuaiduizuoye.scan-7.10.2.apk（或 7.10.0 的归档基线）"
  adb -s "$SER" install -r -g com.kuaiduizuoye.scan-7.10.2.apk >/dev/null 2>&1 || true
fi

bash kit/scripts/set_config.sh --adb "$SER" --profile regular >/dev/null 2>&1 \
  && say "模块配置 = regular ✓" || say "模块配置写入失败（框架没起？）"

if adb -s "$SER" shell 'pidof com.kuaiduizuoye.scan' 2>/dev/null | grep -q .; then
  say "宿主在跑 ✓"
else
  say "宿主没跑 ⇒ 冷启一次（拿 HookCore ready 行）"
  adb -s "$SER" shell 'am start -n com.kuaiduizuoye.scan/com.kuaiduizuoye.scan.AliasActivityDefault' >/dev/null 2>&1 || true
  sleep 8
fi

adb -s "$SER" logcat -d -s KdKit 2>/dev/null | grep -m1 'HookCore ready' | sed 's/^/[ready] 上个会话: /' || true

# **每次起手刷一次源码快照**（2026-11-03 加）。
#
# 门禁 ㉛ 只校验“快照够新”，而**没有任何东西刷新它** ⇒ 那道门禁会在
# 48 小时后红，然后要么被跳过、要么临时补一次。R81 已经证明
# “快照过期”和“没有快照”在实际发生时的代价。
#
# 刷在这里而不是别处：起手检查是每次**必然**会跑的那一步，
# 而“每次都刷”才让 48 小时的上限真的有意义。
python3 kit/scripts/src_snapshot.py 2>&1 | sed 's/^/[ready] /' || say "源码快照失败（不阻塞本轮，但 ㉛ 会红）"

# **清掉 __pycache__**（2026-11-03 加）。
#
# 门禁 ㉝ 检查"源码比 .pyc 新"。而**编辑一个 .py 就会让它过期** ——
# 于是每次改完代码，㉝ 都会红一次，直到那个模块被重新 import。
# 那让这道门禁从"发现真问题"退化成"每响一次都要手工清"。
#
# 真正的教训在 R93：一个过期 .pyc 让负对照跑出**假绿**，
# 我差一点把"这个 bug 测不出来"写进 STATE。所以清缓存要发生在
# **跑任何验证之前**，而不是等门禁红了再清。
#
# 不清也不行：`.pyc` 在这个仓库里是恢复源之一（R81 靠它重建了
# 被误删的 verify_face.py）—— 但那是 `work/` 之外的**已编译产物**，
# 与"源码改了没用上"是两件事。
find . -name __pycache__ -type d -not -path './work/*' -exec rm -rf {} + 2>/dev/null || true
say "__pycache__ 已清（源码改动立刻生效）"

say "起手检查完成"
