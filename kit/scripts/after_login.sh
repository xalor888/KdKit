#!/usr/bin/env bash
# kuaidui-kit / after_login.sh —— 登录之后，把 C1/C2/C3/C5 从"无法验证"推到"已验证"的那一条命令。
#
# 为什么不写成一份说明文档就完事：
# 说明文档只能描述"应该怎么做"，**没法回答"现在做到了哪一步"**。
# 结果就是每次都要有人重新判断一遍。
#
# 这个脚本做四件事：
#   ① 检查前置条件（设备在不在、框架活没活、宿主版本对不对）
#   ② 跑一遍四张验收面（`face_board.py`）
#   ③ 按**每个面的当前状态**给出下一步该做什么（而不是笼统的一句话）
#   ④ 把这一次的结果追加进 `work/DEVICE_LOGIN_LOG.md`（带时间戳，可回溯）
#
#   ./kit/scripts/after_login.sh [serial]
#
# 退出码与 `face_board.py` 一致：0=四面全验过 / 2=仍有面无法验证 / 1=异常。
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

SERIAL="${1:-${SERIAL:-emulator-5558}}"
LOG=work/DEVICE_LOGIN_LOG.md
PY=python3

say() { printf '%s\n' "$*"; }
hr()  { printf '%s\n' "────────────────────────────────────────────────────────"; }

hr
say "登录后升级路径 · serial=$SERIAL · $(date '+%Y-%m-%d %H:%M:%S')"
hr

# ① 前置条件 ---------------------------------------------------------------
if ! adb -s "$SERIAL" get-state >/dev/null 2>&1; then
  say "✗ 设备 $SERIAL 不在线。先跑：./kit/scripts/env_up.sh kd1 5558"
  exit 1
fi
say "✓ 设备在线"

if ! adb -s "$SERIAL" shell 'pidof system_server' >/dev/null 2>&1; then
  say "✗ system_server 不在（框架挂了）。先跑：./kit/scripts/recover_device.sh --force"
  exit 1
fi
say "✓ 框架存活"

# 宿主版本：结论寄生在版本上，版本不对就别谈"验过了"
VER="$(adb -s "$SERIAL" shell 'dumpsys package com.kuaiduizuoye.scan | grep -m1 versionName' 2>/dev/null | tr -d '\r' | awk -F= '{print $2}')"
say "· 宿主版本：${VER:-未知}（适配基线 7.10.2）"

# ② 跑四张面 ---------------------------------------------------------------
say ""
$PY kit/scripts/face_board.py --adb "$SERIAL" --out work/FACE_BOARD.md
RC=$?

# ③ 按每个面的状态给下一步 ------------------------------------------------
say ""
hr
say "下一步（按每个面当前的状态）"
hr

export SERIAL_FOR_BOARD="$SERIAL"
STATES="$($PY - <<'PY'
import json, subprocess, sys, os
common = ['--adb', os.environ.get('SERIAL_FOR_BOARD', 'emulator-5558')]
def one(args):
    p = subprocess.run(args, capture_output=True, text=True)
    for line in reversed((p.stdout or '').splitlines()):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            return json.loads(line)
    return {'face': '?', 'state': 'unknown', 'detail': ''}
out = []
out.append(one([sys.executable, 'kit/scripts/verify_membership.py', *common, '--json']))
for f in ('watermark', 'pk'):
    out.append(one([sys.executable, 'kit/scripts/verify_face.py', '--face', f, *common, '--json']))
for r in out:
    print(f"{r['face']}\t{r['state']}\t{r.get('detail','')}")
PY
)"

NEXT_watermark='在 App 内打开任意题目大图（H5 的 GotoPictureBrowseWebAction 入口），确认设置页里 web_picture_watermark 是开的'
NEXT_pk='首页 → 口算PK 进 PK 大厅（…/kd-pk/pk-home.html），确认 pk_assist 是开的；对局需登录，注入这一半不需要'
NEXT_vip='用一个**非会员**账号在本机登录后重跑本脚本；会员页逛一圈让 vip_unlock 走到判定'

while IFS=$'\t' read -r face state _detail; do
  case "$face:$state" in
    vip:verified)      say "· 会员面：**已验证** —— 无需动作";;
    vip:*)             say "· 会员面：${NEXT_vip}";;
    watermark:verified) say "· 水印面：**已验证** —— 无需动作";;
    watermark:*)        say "· 水印面：${NEXT_watermark}";;
    pk:verified)       say "· PK 面：**已验证** —— 无需动作";;
    pk:*)              say "· PK 面：${NEXT_pk}";;
  esac
done <<< "$STATES"

say ""
case "$RC" in
  0) say "✓ 四个面全部已验证 —— 把这条结论回填进 work/DEVICE_LOGIN.md 的 C1/C2/C3/C5，并更新 work/HEALTH.md。";;
  2) say "◐ 仍有面无法验证（**不是失败**）。照着上面的"下一步"逐条做，每做完一条重跑本脚本。";;
  *) say "✗ 工具异常（rc=${RC}），看上面的输出。";;
esac

# ④ 留档 -------------------------------------------------------------------
mkdir -p work
{
  echo ""
  echo "## $(date '+%Y-%m-%d %H:%M:%S')  serial=$SERIAL  宿主=${VER:-未知}  rc=$RC"
  echo ""
  echo '```'
  sed -n '1,40p' work/FACE_BOARD.md 2>/dev/null | grep '^|' || echo '（本次没有产出看板）'
  echo '```'
} >> "$LOG"
say ""
say "· 已追加到 $LOG"

exit "$RC"
