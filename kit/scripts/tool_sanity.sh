#!/usr/bin/env bash
# kuaidui-kit / tool_sanity.sh — rule 18 as a script (2026-10-12)
#
# Runs the "inject a deliberate anomaly" checks for the anomaly-judging tools.
# Discipline -> tool: run this after changing any assertion or gate.
#
#   ./kit/scripts/tool_sanity.sh
#
# Requirements (rule 18): run BOTH real and fabricated inputs; prefer positive-form
# matching; fossilize the test; and NEVER pipe when checking exit codes.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

FAIL=0
chk() {  # chk <name> <expected-exit> <cmd...>
  local name="$1" want="$2"; shift 2
  "$@" >/dev/null 2>&1
  local got=$?
  if [ "$got" = "$want" ]; then
    printf "  ok   %-42s exit=%s\n" "$name" "$got"
  else
    printf "  FAIL %-42s exit=%s (want %s)\n" "$name" "$got" "$want"
    FAIL=$((FAIL+1))
  fi
}

echo "=== tool_sanity (rule 18) ==="

echo "--- safe_io: keyword present / absent ---"
chk "safe_io keyword present"      0 python3 kit/python/safe_io.py --file work/SWITCH_DIFF.md --must-contain "结构变化"
chk "safe_io keyword absent"       1 python3 kit/python/safe_io.py --file work/SWITCH_DIFF.md --must-contain "zzz_not_there"

echo "--- argparse tools: bad args must not be silent ---"
chk "catalog bad arg"              2 python3 kit/scripts/catalog.py --dir /tmp/nonexist_dir_xyz
chk "day_summary bad arg"          2 python3 kit/scripts/day_summary.py --from 1 --to 2 --bogus 1

echo "--- normal runs must be 0 ---"
# **每个工具都要有一条"坏输入"用例**（2026-11-02 补）。
#
# 原来这里只有 `${t} normal → 0`：一个工具即使把参数全忽略、什么都不校验，
# 也照样全绿。今天实测 `handover_refresh.py` / `docs_claims.py` 就是那样 ——
# 多打 `--bogus` 也返回 0。而它们都是"核对/刷新"类工具：
# **参数写错却返回成功，读的人会以为核对过了，实际一次都没核对。**
for t in catalog milestones page_map trend_report disk_audit surface_trends; do
  if [ -f "kit/scripts/${t}.py" ]; then
    chk "${t} normal"              0 python3 "kit/scripts/${t}.py"
    chk "${t} bad arg"             2 python3 "kit/scripts/${t}.py" --bogus-arg-xyz
  fi
done

# 这两个"不接受参数"的工具同样要能拒绝参数
chk "docs_claims bad arg"          2 python3 kit/scripts/docs_claims.py --bogus-arg-xyz
chk "handover_refresh bad arg"     2 python3 kit/scripts/handover_refresh.py --bogus-arg-xyz
chk "coverage_check bad arg"       2 python3 kit/scripts/coverage_check.py --bogus-arg-xyz
chk "artifact_lifecycle bad arg"   2 python3 kit/scripts/artifact_lifecycle.py --bogus-arg-xyz
chk "session_time bad arg"         2 python3 kit/scripts/session_time.py --bogus-arg-xyz

# 这两个要参数 ✓ —— 用最近两个包当输入 ✓（否则它们的 exit 2 是"缺参数"而不是"坏了" ✓）
CUR=$(ls -t work/packs/*/responses.json 2>/dev/null | head -1)
PRV=$(ls -t work/packs/*/responses.json 2>/dev/null | head -2 | tail -1)
if [ -n "${CUR}" ] && [ -n "${PRV}" ]; then
  chk "server_snapshot normal"     0 python3 kit/scripts/server_snapshot.py --current "${CUR}" --previous "${PRV}"
  chk "switch_diff normal"         0 python3 kit/scripts/switch_diff.py --current "${CUR}" --previous "${PRV}"
fi
chk "server_snapshot no args"      2 python3 kit/scripts/server_snapshot.py
chk "switch_diff no args"          2 python3 kit/scripts/switch_diff.py

echo "--- anchors: real / absent / missing file ---"
chk "anchors real anchor"          0 python3 kit/scripts/anchors.py REPORT.md --check "## 1 目标画像"
chk "anchors absent anchor"        1 python3 kit/scripts/anchors.py REPORT.md --check "## 1 这个锚点不存在xyz"
chk "anchors missing file"         2 python3 kit/scripts/anchors.py /tmp/no_such_file_xyz.md

echo "--- session_time / artifact_lifecycle normal ---"
chk "session_time print"           0 python3 kit/scripts/session_time.py --print
chk "artifact_lifecycle normal"    0 python3 kit/scripts/artifact_lifecycle.py

echo "--- safe_io tolerant matching (backtick / case / bogus) ---"
chk "safe_io backtick-tolerant"    0 python3 kit/python/safe_io.py --file work/DISABLED_FEATURES.md --must-contain "commonShow 全貌"
chk "safe_io case-tolerant"        0 python3 kit/python/safe_io.py --file work/DISABLED_FEATURES.md --must-contain "COMMONSHOW 全貌"
chk "safe_io still catches bogus"  1 python3 kit/python/safe_io.py --file work/DISABLED_FEATURES.md --must-contain "zzz_bogus_xyz"

echo "--- safe_io.patch_at_anchor: good / bad anchor ---"
printf '# t\n## A\n' > /tmp/sanity_t.md
chk "patch_at_anchor good"         0 python3 -c "import sys;sys.path.insert(0,'kit/python');from safe_io import patch_at_anchor;patch_at_anchor('/tmp/sanity_t.md','## A','## A2',['## A2'])"
chk "patch_at_anchor bad"          1 python3 -c "import sys;sys.path.insert(0,'kit/python');from safe_io import patch_at_anchor;patch_at_anchor('/tmp/sanity_t.md','## NOPE','x',['x'])"

echo "--- coverage_check (tolerant matcher) ---"
chk "coverage_check key level"     0 python3 kit/scripts/coverage_check.py
chk "coverage_check field level"   0 python3 kit/scripts/coverage_check.py --level field

echo "--- ascii_lint (variables next to full-width chars) ---"
chk "ascii_lint clean"             0 python3 kit/scripts/ascii_lint.py

echo "--- handover_refresh (safe section replace) ---"
chk "handover_refresh runs"        0 python3 kit/scripts/handover_refresh.py

echo "--- watchdog: healthy / down (check-only, never touches the device) ---"
chk "watchdog healthy path"        0 ./kit/scripts/watchdog.sh
chk "watchdog down path"           1 ./kit/scripts/watchdog.sh --adb emulator-9999 --check-only

echo "--- feature_agreement (code = docs) ---"
chk "feature_agreement consistent"  0 python3 kit/scripts/feature_agreement.py
printf '| `bogus_feature` | x |\n' > /tmp/sanity_fake_ver.md
chk "feature_agreement mismatch"    1 python3 kit/scripts/feature_agreement.py --doc /tmp/sanity_fake_ver.md

echo "--- source_health (authoritative sources still alive) ---"
chk "source_health all alive"       0 python3 kit/scripts/source_health.py
printf '{}' > /tmp/sanity_empty_dump.json
chk "source_health dead detected"   1 python3 kit/scripts/source_health.py --dump /tmp/sanity_empty_dump.json

echo "--- docs_claims (numbers written in the docs still match) ---"
chk "docs_claims consistent"        0 python3 kit/scripts/docs_claims.py

echo "--- doc_dups (no duplicated sections in hand-maintained docs) ---"
chk "doc_dups clean"                 0 python3 kit/scripts/doc_dups.py

echo "--- artifact_audit (exports / empty sections / title collisions) ---"
chk "artifact_audit clean"          0 python3 kit/scripts/artifact_audit.py

echo "--- assertion regression test ---"
chk "assert_test all hit"          0 python3 kit/scripts/assert_test.py

echo "=== failures: ${FAIL} ==="
[ "$FAIL" = "0" ] && echo "tool_sanity: ALL OK" || echo "tool_sanity: FAILED (${FAIL})"
exit "$FAIL"
