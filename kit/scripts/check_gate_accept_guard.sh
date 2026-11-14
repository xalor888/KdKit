#!/usr/bin/env bash
# kuaidui-kit / check_gate_accept_guard.sh —— `run_gate` 的"不接受 1"守卫必须能触发。
#
# 为什么值得单独一道：`--accept` 是 2026-11-02 新加的机制，用来区分
# "验过了(0)" 与 "测不了(2)"。但它开了一个口子 —— 一旦某道门禁写成
# `--accept " 0 1 2 "`，那道门禁就**永远不可能红**。
# 守卫写在 run_gate 里，可**守卫本身也可能是装饰**（写了但走不到）。
# 所以这里把 run_gate 从 verify.sh 里原样抽出来，喂一个含 1 的接受集合，
# 看它到底红不红。
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ① 把 run_gate 函数体原样抽出（不重写一遍 —— 重写就等于测了别的东西）
sed -n '/^run_gate() {/,/^}/p' module/scripts/verify.sh > "$TMP/fn.sh"
if [ ! -s "$TMP/fn.sh" ]; then
  echo "[accept-guard] **抽不出 run_gate 函数体**（verify.sh 的结构变了？）"
  exit 1
fi

# ② 造一个最小环境：只提供 run_gate 依赖的那几个变量
cat > "$TMP/harness.sh" <<'EOF'
set -uo pipefail
RESULTS=()
FAILED=0
QUIET=1
RETRY_GATES=" "
ROOT="$(pwd)"
source "$1"
run_gate "负对照：接受集合含 1" --accept " 0 1 " true
if [ "$FAILED" -eq 1 ]; then
  echo "[accept-guard] 守卫触发了 ✓（含 1 的接受集合被拒）"
  exit 0
fi
echo "[accept-guard] **守卫没触发** —— run_gate 接受了含 1 的集合 ⇒ 那道门禁永远不可能红"
exit 1
EOF

if bash "$TMP/harness.sh" "$TMP/fn.sh"; then
  exit 0
fi
exit 1
