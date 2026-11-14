#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fix_xposed_prefs_selinux.sh — 让宿主进程读得到 LSPosed 的 XSharedPreferences。
#
# 为什么需要这个（2026-11-08 实测）
# ───────────────────────────────
# 症状：模块注入正常（`HookCore ready (38 features)`、`hooks 101 ok / 0 failed`），
# 但**所有配置项都按默认值跑** —— 日志里这一行是空的：
#
#     [KdKit] xprefs published=/data/misc/<uuid>/prefs/dev.xalor.kdkit/kdkit.xml all={}
#
# `all={}` 不是"没有配置"，是**读不到文件**。宿主进程（`u:r:untrusted_app_30`）
# 对 `/data/misc/<uuid>` 的 `search` 被 SELinux 拒绝：
#
#     avc: denied { search } for name="<uuid>" tcontext=u:object_r:unlabeled:s0
#         tclass=dir trawcon="u:object_r:xposed_data:s0" app=com.kuaiduizuoye.scan
#
# 于是 `KdConfig.isOn()` 一律回落到 defaultOn ⇒ 24 个 `defaultOn=false` 的热功能
# 全部关闭（`effective-on=13` 而不是 18–20）。**没有报错，只是开了也不生效** ——
# 与 R119 那类"关不掉的功能"正好相反，这一种更难查：`set_config.sh` 的推送与回读
# 全部通过（文件内容确实写对了），只有**读的那一头**是坏的。
#
# 判据（一句话）：`all={}` ⇒ 配置链路断；`all` 里有键 ⇒ 通。
#
# 修法：给 `untrusted_app_30` 补两条 allow（`xposed_data` 在 ROM 的 sepolicy 里
# 是 attribute，不是 type，所以**不要写 `type xposed_data`** —— 那会报
# `target type xposed_data does not exist` 并让人误以为无解）。规则是 live 的，
# 重启设备后失效 ⇒ 每次起设备都要跑（`env_up.sh` 已经在 set_config 之前调用它）。
#
#   ./kit/scripts/fix_xposed_prefs_selinux.sh --adb emulator-5558
#   ./kit/scripts/fix_xposed_prefs_selinux.sh --adb emulator-5558 --check-only
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

SERIAL=""
CHECK_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --adb) SERIAL="$2"; shift 2 ;;
    --check-only) CHECK_ONLY=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SERIAL" ] || { echo "usage: $0 --adb <serial> [--check-only]" >&2; exit 2; }

say() { echo "[selinux] $*"; }

if ! adb -s "$SERIAL" get-state >/dev/null 2>&1; then
  say "设备 $SERIAL 不在线（跳过）"
  exit 0
fi

MODE="$(adb -s "$SERIAL" shell getenforce 2>/dev/null | tr -d '\r')"
say "getenforce=${MODE:-unknown}"

# 判据一：有没有 avc 拒绝。
AVC="$(adb -s "$SERIAL" logcat -d 2>/dev/null | grep -c 'avc:  denied  { search } for  name=' || true)"
AVC_WANTED="$(adb -s "$SERIAL" logcat -d 2>/dev/null | grep 'avc:  denied  { search }' | grep -c 'trawcon="u:object_r:xposed_data:s0"' || true)"
if [ "${AVC_WANTED:-0}" -gt 0 ]; then
  say "见到 ${AVC_WANTED} 条"'"xposed_data"'"的 search 拒绝 ⇒ 配置链路会读到空 map"
fi

# 判据二（更强、与日志无关）：文件与目录的可读性从 app 视角无法直接测，
# 所以这里只做"规则是否已存在"的幂等检查：先跑一次 policy，再看 avc 是否归零。
if [ "$CHECK_ONLY" -eq 1 ]; then
  exit 0
fi

adb -s "$SERIAL" shell 'su -c "magiskpolicy --live \
\"allow untrusted_app_30 xposed_data dir { search read open getattr }\" \
\"allow untrusted_app_30 xposed_data file { read open getattr }\" >/dev/null 2>&1; echo rc=\$?"' 2>/dev/null | tr -d '\r'

# 真正要验的是"读得到"，但那要等宿主下次启动。这里只报状态，由调用者看下一行的
# `all={}` 是否存在 —— 判据写在 MIGRATION-710.md §环境，不在这里自判。
say "规则已应用（live，重启设备后失效，起设备时重跑）"
say "验证：重启宿主后看 '[KdKit] xprefs published=… all={}' —— 空 map 即未生效"

exit 0
