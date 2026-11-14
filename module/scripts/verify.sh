#!/usr/bin/env bash
# KdKit 一键验收（纯离线，不需要设备）—— 改动前后的唯一入口。
#
# 跑四道门，任何一道红就退出非零：
#   ① 单元测试      —— 纯逻辑（过滤/限流/白名单/截断）的 JVM 测试
#   ② 编译          —— assembleDebug（含 Compose 设置页）
#   ③ 功能表一致    —— FeatureRegistry ↔ README ↔ 子选项 schema（含幽灵键检查）
#   ④ 钩子目标      —— 每条 Xp.hook 的类/方法在解码后的 APK 里真的存在
#
# 用法：
#   module/scripts/verify.sh                 # 全部
#   module/scripts/verify.sh --no-apk        # 跳过 ③④（改 UI/纯逻辑时更快）
#   module/scripts/verify.sh --quiet         # 只打印每道门的结论
#   module/scripts/verify.sh --deep          # 额外跑 ⑥b（死代码枚举，~65s）
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODULE="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$MODULE/.." && pwd)"
QUIET=0
SKIP_APK=0
SKIP_DEVICE=0
DEEP=0
for a in "$@"; do
  case "$a" in
    --quiet) QUIET=1 ;;
    --no-apk) SKIP_APK=1 ;;
    --no-device) SKIP_DEVICE=1 ;;
    --deep) DEEP=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

# ── 互斥：本脚本不能与"负对照 / 验收 / 另一次 verify"并发 ─────────────────
# 2026-11-09 实测：两条链同时跑时，`run_negative_controls` 的**注入态**会被别的门
# 读到 ⇒ 一次性假红 6~9 道门（①b/㉨/㉩/㉪/㉫/㉬/⑱/㉒/㉤），而单跑全绿。
# macOS 没有 flock，所以走 kit/scripts/with_lock.py（fcntl.flock）。
# 自锁而不是"要求调用者记得加锁"：**纪律写在脚本里才不会被忘掉**。
#
# **必须认 `KD_LOCK_HELD`**（2026-11-09 04:0x 修）：调用方若已经套了
# `with_lock.py -- bash verify.sh`，那把锁就在**父进程**手里；这里再 exec 一次
# `with_lock` 只会等一把永远等不到的锁 ⇒ 真死锁（`verify_r3.log` 只有
# `[lock] 持有 …` 一行、一道门都没跑就是它）。`KD_LOCK_HELD` 由 with_lock.py
# 在持锁时注入子进程环境，值与锁的 realpath 相同即表示"同链已持锁"。
if [ -z "${KD_VERIFY_LOCKED:-}" ] && [ -z "${KD_LOCK_HELD:-}" ] \
   && [ -x "$ROOT/kit/scripts/with_lock.py" ]; then
  export KD_VERIFY_LOCKED=1
  exec python3 "$ROOT/kit/scripts/with_lock.py" --label verify \
       --timeout "${KD_LOCK_TIMEOUT:-7200}" -- bash "$0" "$@"
fi
if [ -n "${KD_LOCK_HELD:-}" ] && [ -z "${KD_VERIFY_LOCKED:-}" ]; then
  echo "  (同链已持有 ${KD_LOCK_HELD}，跳过自锁)" >&2
  export KD_VERIFY_LOCKED=1
fi

# Gradle 8.14.5 只支持 JDK 17–21；本机默认的 Homebrew JDK 27 会让 gradle 直接失败
# （错误信息只有一行 "27.0.1.0.3"，非常难读）。所以这里主动挑一个受支持的 JDK：
# 已导出的 JAVA_HOME 若版本受支持就尊重它，否则回落到 jbr-21。
java_major() {
  "$1/bin/java" -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1
}
pick_java() {
  if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
    local m; m="$(java_major "$JAVA_HOME")"
    if [ -n "$m" ] && [ "$m" -ge 17 ] && [ "$m" -le 21 ]; then echo "$JAVA_HOME"; return; fi
    echo "  (忽略 JAVA_HOME=${JAVA_HOME}, JDK ${m} 不受 Gradle 8.14.5 支持)" >&2
  fi
  local cand
  for cand in "$(/usr/libexec/java_home -v 21 2>/dev/null)" \
              "$HOME/Library/Java/JavaVirtualMachines/jbr-21.0.11/Contents/Home" \
              "$(/usr/libexec/java_home -v 17 2>/dev/null)"; do
    [ -n "$cand" ] && [ -x "$cand/bin/java" ] && { echo "$cand"; return; }
  done
  echo ""
}
JAVA_HOME="$(pick_java)"
if [ -z "$JAVA_HOME" ]; then
  echo "✗ 找不到 JDK 17–21（Gradle 8.14.5 不支持更新的版本）" >&2
  exit 2
fi
export JAVA_HOME

FAILED=0
RETRIED=0
declare -a RESULTS

# 哪些门禁对"并发写文件"敏感 ⇒ 失败时自动重试一次。
#
# 背景（2026-10-25 实测）：本仓库有并行轮次在改 `kit/python/` 与 `module/`。
# 门禁读到的可能是**写了一半的文件**，于是偶发失败（实测 20 次连跑里红 1 次，
# 定位到 `test_super_slot_dispatch.py` 的时间戳正好落在循环开始那一刻）。
#
# 重试只解决"瞬时"这一类。若重试仍失败 ⇒ 是真问题，照常判红。
# **重试会打印 `RETRY-PASS`**，不静默吞掉 —— 否则"偶发"会变成没人知道的常态。
# 并发/外部状态敏感的门禁，失败时重试一次再看。
# ⑬ 列进来是因为它依赖 ADB 与设备：并行轮次也在操作设备时，
# `adb install` / `am start` 会短暂失败 —— 那不是代码问题。
RETRY_GATES=" ①b 抓取解析器 ⑦ 假测试扫描 ⑬ 真机验证 "

# **每个门禁自己声明"哪些退出码算过"**（默认只有 0）。
#:
#: 有些判据天生有三种结局：验过了(0) / **测不了**(2) / 坏了(1)。
#: 把 2 和 0 混同，就会出现"一轮全绿、其实什么都没验"（`face_board` 那一族的教训）。
#: 但把 2 当失败也不对：那会让门禁在没有抓取、没有设备时永远红，而红会训练人跳过它。
#: 所以门禁显式声明 `--accept " 0 2 "`，并且 2 通过时**在结果里写明"无法验证"**，
#: 不留模糊地带。
run_gate() {
  local name="$1"; shift
  local accept=" 0 "
  if [ "${1:-}" = "--accept" ]; then accept="$2"; shift 2; fi
  local log; log="$(mktemp)"
  local note=""
  # **接受集合里不许有 1**（2026-11-02 加）。
  #
  # `--accept` 的用途是区分"验过了(0)"与"测不了(2)"。一旦把 1（坏了）也放进去，
  # 这道门禁就**永远不可能红** —— 而那正是本项目反复在防的东西。
  # 这道守卫本身也必须能被触发，否则它只是装饰：见 verify.sh 末尾的自检。
  if [[ "$accept" == *" 1 "* ]]; then
    printf 'MISCONFIGURED\n'
    RESULTS+=("FAIL  ${name}（--accept 里含 1 ⇒ 这道门禁永远不可能红）")
    FAILED=1
    return 0
  fi
  printf '▶ %s ... ' "$name"
  # **逐门禁计时**（2026-11-04 加）。
  #
  # 2026-11-03 实测全量 842 秒、单套件 177 秒，我据此"算"出三道门禁在重复跑 ——
  # 那个判断对了一半（确实重复），但耗时分布是**猜**的：优化后只降到 793 秒，
  # 说明大头在别处。没有计时就只能继续猜。
  #
  # 落账到 `work/gate_times.tsv`，一行一道门禁。它同时也是
  # "某道门禁是不是越来越慢"的唯一证据。
  local _t0 _t1 _dur
  _t0=$(python3 -c 'import time;print(time.time())')
  "$@" >"$log" 2>&1
  local rc=$?
  _t1=$(python3 -c 'import time;print(time.time())')
  _dur=$(python3 -c "print(f'{$_t1-$_t0:.1f}')")
  printf '%s\t%s\n' "$_dur" "$name" >> "$ROOT/work/gate_times.tsv"
  if [[ "$accept" != *" $rc "* ]]; then
    :   # 不在接受集合里 ⇒ 走下面的失败路径
  elif [ "$rc" = "0" ]; then
    printf 'PASS\n'
    RESULTS+=("PASS  $name")
    if [ "$QUIET" -eq 0 ]; then tail -5 "$log" | sed 's/^/    /'; fi
    rm -f "$log"
    return 0
  else
    # 非 0 但在接受集合里 ⇒ "无法验证"，必须写在结果行上
    note="（退出码 $rc = 无法验证，**不算失败也不算通过**）"
    printf 'PASS%s\n' "$note"
    RESULTS+=("PASS  $name$note")
    if [ "$QUIET" -eq 0 ]; then tail -5 "$log" | sed 's/^/    /'; fi
    rm -f "$log"
    return 0
  fi

  # 并发敏感的门禁：重试一次
  if [[ "$RETRY_GATES" == *" $name "* ]]; then
    printf 'RETRY ... '
    _t0=$(python3 -c 'import time;print(time.time())')
    "$@" >"$log" 2>&1
    local rc2=$?
    _t1=$(python3 -c 'import time;print(time.time())')
    _dur=$(python3 -c "print(f'{$_t1-$_t0:.1f}')")
    printf '%s\t%s（重试）\n' "$_dur" "$name" >> "$ROOT/work/gate_times.tsv"
    if [[ "$accept" == *" $rc2 "* ]]; then
      if [ "$rc2" != "0" ]; then note="（退出码 $rc2 = 无法验证）"; fi
      printf 'PASS（首次失败，重试通过 —— 大概率是并行写入的瞬时状态；原因已存 %s）\n' "$log"
      RESULTS+=("PASS  ${name}（重试）${note}")
      # 不 rm 日志：留下证据，便于判断"是否越来越频繁"
      #
      # **同时落一行账**（2026-11-02 补）：日志留在 /tmp，重启就没了；
      # 而"重试是不是越来越频繁"正是判断"某个门禁开始不稳定"的唯一线索。
      # 没有账本时，`PASS（重试）` 只出现在当轮输出里，翻过去就看不见了 ——
      # 于是"偶发"悄悄变成"常态"，而每一轮都是绿的。
      RETRIED=$((RETRIED+1))
      printf '%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$name" \
        >> "$ROOT/work/gate_retries.log"
      return 0
    fi
    printf 'FAIL（重试仍失败 ⇒ 真问题）\n'
  else
    printf 'FAIL\n'
  fi
  RESULTS+=("FAIL  $name")
  FAILED=1
    # 失败原因**无条件打印**，包括 --quiet。
    # 2026-10-25: 第一版只在非 quiet 时 tail 日志，于是 `--quiet` 把唯一能定位
    # 原因的信息整段丢掉，只能靠重跑碰运气 —— 一次偶发失败（①b）因此无法当场定位。
    # 门禁的价值在于失败时告诉你为什么，quiet 只该压掉"成功时的啰嗦"。
    echo "    ── 失败原因（最后 40 行）──"
    tail -40 "$log" | sed 's/^/    /'
  if [ "$QUIET" -eq 0 ]; then
    grep -E '^(✓|✗|[0-9]+/[0-9]+|BUILD)' "$log" | tail -4 | sed 's/^/    /'
  fi
  rm -f "$log"
}

cd "$MODULE"

run_gate "① 单元测试" ./gw --offline testDebugUnitTest
# ①b 是 ① 的**另一半**：模块写的行格式由 `kit/python/capture_schema.py` 声明，六个解析器
# 都按它切分。Kotlin 侧新增一个前缀而 schema 不认识时，门禁①（JVM）与 ③④⑤（钩子目标）
# 都不会红 —— 只有一份"读模块源码 + 比对前缀表"的测试能抓到。见
# `kit/python/tests/test_capture_schema.py::KotlinSideDrift`。
# **走 `test_run.py` 的缓存**（2026-11-03 改）。
#
# 原来这里自己跑一遍套件（~150s），而 ㉥ / ㉦ 也各跑一遍 ——
# 同一个套件在一轮里跑了三遍，只为读三个数。verify.sh 因此多花 5 分钟。
# 缓存的失效判据在 `test_run.py`：**源码比缓存新 ⇒ 立即重跑**，
# 所以"改了代码没重测"这个风险被挡住了。
run_gate "①b 抓取解析器" python3 "$ROOT/kit/scripts/test_run.py" --ensure --quiet
run_gate "② assembleDebug" ./gw --offline assembleDebug
run_gate "③ 功能表/子选项一致" python3 scripts/check_feature_parity.py

if [ "$SKIP_APK" -eq 0 ]; then
  if [ -d "$ROOT/work/apktool_out" ]; then
    # 这两个脚本的默认路径是相对**仓库根**的，必须从根目录调用。
    # ④ 只比对类+方法名；⑤ 再比对形参类型 —— 签名写错时 ④ 仍报 OK、运行时却静默失效
    #   （2026-10-25 加，见 kit/scripts/check_hook_signatures.py 的说明）。
    run_gate "④ 钩子目标" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_targets.py --json '$ROOT/work/.hook_targets.json'"
    run_gate "⑤ 钩子签名" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_signatures.py --quiet"
    # ⑥ 目标有没有**调用方** —— 前两道只证明"存在且签名对"，死代码照样全绿。
    #   例：BrushMaskView 在加固壳里 0 引用，钩它永远不执行。
    #   这一步要扫 529MB smali，约 20s，所以只在 ④⑤ 都过之后跑。
    run_gate "⑥ 钩子调用方" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_callers.py --quiet"
    # ⑥b 反向枚举：**没钩到**的可证明死代码（零引用 UI 子类）。
    #   ⑥ 只检查"模块钩了的那些目标"；`BrushMaskView` 那次失效的根因不是判定错，
    #   是没人想到要把它列为目标。这一层正向扫一遍，给出"别去钩"的清单。
    #   只报告、不判红（这些类本来就没钩），所以它不会把门禁变成噪声。
    #   耗时 ~65s（7416 个类的单遍扫描）⇒ 放在 `--deep` 里，默认不跑，
    #   免得每次改代码都要等一分钟。发布前跑一次即可。
    if [ "$DEEP" -eq 1 ]; then
      run_gate "⑥b 死代码枚举" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_callers.py --quiet --dead-ui com/byazt >/dev/null && echo enumerated"
    fi
  else
    # **三条都要显式 SKIP**。曾经只写 ④ 一条，于是 `--no-apk` 的报告里
    # ⑤⑥ 直接**消失** —— 读报告的人会以为"这轮只有 10 道门"，而不是"3 道没跑"。
    # 消失与跳过是不同的：跳过的会让人问"为什么跳过"，消失的连问都不会问。
    for g in "④ 钩子目标" "⑤ 钩子签名" "⑥ 钩子调用方"; do
      echo "▶ $g ... SKIP（没有 work/apktool_out）"
      RESULTS+=("SKIP  ${g}（未解码 APK）")
    done
  fi
else
  for g in "④ 钩子目标" "⑤ 钩子签名" "⑥ 钩子调用方"; do
    RESULTS+=("SKIP  ${g}（--no-apk）")
  done
fi

# ⑦ 假测试扫描 —— 抓"看着通过、其实什么都没测"的测试。
#
# 为什么它配得上一道门：这类错误**没有 FAIL**，所以不会有任何别的机制发现它。
# 本项目踩过两次（都在 2026-10-25）：断言自我实现的字面量、以及
# if (!file.isFile) return 的静默跳过（JVM 单测 CWD 是 module/app，
# 永远读不到仓库根的 work/，于是测试一次都没执行断言却一直是绿的）。
# 红测试会说"我失败了"，假测试会说"一切都好" —— 后者更危险。
#
# **严格模式**（2026-10-25 第 25 轮从报告模式收紧）。
#
# 收紧的依据不是"等够了时间"，而是两条可复核的事实：
#   * 真实库命中 0 —— 没有需要豁免的存量；
#   * 注入 3 条假测试（变量断言 / 直接字面量断言 / 静默返回）后召回 3/3，
#     同时第 4 条真实测试没被误报 ⇒ 误报率 0、召回完整。
#
# 在此之前它跑了上一轮的完整周期，其间没有出现任何误报。
# 若将来出现误报：**修检测规则**，不要删掉被指的断言 ——
# 一道会误报的门禁会教人忽略门禁（`SIGNATURE-MISMATCH` 假红已给过教训）。
run_gate "⑦ 假测试扫描" bash -c "cd '$ROOT' && python3 kit/scripts/check_fake_tests.py --strict"

# ⑧ 钩点共享登记 —— 两个功能钩同一个方法时必须写明相互作用。
#
# 为什么它配得上一道门：**钩点冲突不会让任何别的门变红**。
# 一个功能在 before 里写了 `param.result = …`（短路），另一个功能可能再也读不到
# 这次调用 —— 但不崩溃、不打日志、钩子数照常。唯一的症状是"某个功能安静地少收数据"，
# 而那要等到有人拿抓取对照才发现。
#
# 当前实测 2 处跨文件共享（`BridgeGuard` 与 `H5BridgeLog` 都钩 `HybridWebView.dispatchAction*`），
# 语义已写在 `module/PARADIGM.md` §10。新增共享而未登记 ⇒ 红。
run_gate "⑧ 钩点共享登记" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_sharing.py --strict --targets-json '$ROOT/work/.hook_targets.json'"

# ⑨ Robust 热修复暴露面 —— **报告模式**，不判红。
#
# 为什么它该出现、但不该红：
#   ④⑤⑥⑧ 都隐含"静态看到的原方法体就是运行时执行的那个"。宿主集成了美团 Robust：
#   被插桩的方法开头会 `if (isSupported) return;`，**补丁一下发，原方法体一行都不执行**。
#   钩子仍挂着（`Xp.hook` 返回 true），但所有"改返回值/改字段/读回包"的语义全部失效
#   —— 和 `BrushMaskView` 同一种失败形态：绿门禁 + 零效果。
#
#   实测：全 APK **7594 个类 / 35784 个方法**带插桩，当前 115 个钩子目标里
#   **47 个方法本身**被插桩、另有 18 个目标与插桩方法同类。
#
#   不判红的理由（与 `--strict-dead` 同一逻辑）：这描述的是"宿主**能**做什么"，
#   不是"模块做错了什么"。静态**无法**证明运行时真的下发了补丁 ——
#   `changeQuickRedirect` 初值是 null，只有 `PatchExecutor` 在应用补丁时才写它。
#   把它做成红灯，等于让一条无法被本地证伪的规则永久变红，那会教人忽略门禁。
#
#   它仍然是门禁：每次跑都会把数字与清单打出来，于是"暴露面突然变大"是可发现的。
#   升级 APK 后如果 GUARDED 跳变，请按 `module/PARADIGM.md` §11 复核钩点。
run_gate "⑨ 热修复暴露面" bash -c "cd '$ROOT' && python3 kit/scripts/check_robust_coverage.py --quiet --fail-over 60 >/dev/null && echo measured"

# ⑩ smali_usage 读预算余量 —— 防止"结论随目标位置漂移"再次发生。
#
# 背景（2026-10-26）：④ 曾把 `NativeHelper.nativeGetSign` 判成"死目标"，
# 而它单独跑是 `USED`。根因是 `smali_usage` 按路径顺序读文件，预算 96 MB 用完后
# 排在后面的目标被降级成 `INCOMPLETE` —— **判定结果取决于目标在列表里的位置**。
# 把预算提到 640 MB 后降级归零，但当时实测用量 279.9 MB，320 MB 只剩 12% 余量。
#
# 这道门量的是"还够不够用"，余量 < 25% 就红。它防的不是当前错误，
# 而是"宿主 APK 下次变大时，同一个坑再踩一次且没人发现"。
run_gate "⑩ 读预算余量" bash -c "cd '$ROOT' && python3 kit/scripts/check_usage_budget.py --strict"

# ⑪ 解析规则往返 —— 每条 schema 规则是否都被真实样本触发过。
#
# 两个方向都要盯：
#   * **规则有、没人写** ⇒ 死规则（前缀改了没人更新，或功能删了规则留着）；
#   * **有人写、没规则** ⇒ 那行落到 UNKNOWN，读报告的人分不清"新前缀"与"解析器漏了"。
#
# 关键陷阱：**kind 名 ≠ 行前缀**。`AD_BLOCK` 这个 kind 对应的行是
# `blocked ad slot read: …` —— 按"前缀"比对会得到一堆假缺口
# （2026-10-26 就这样误判过 15 条）。
run_gate "⑪ 解析规则往返" bash -c "cd '$ROOT' && python3 kit/scripts/check_schema_roundtrip.py --strict"

# ⑫ shell 变量边界 —— `$var` 紧跟全角标点会 unbound variable。
#
# 同一个 bug 犯过两次（第 36 轮 ⑩ 的重试分支、5 分钟后 ④⑤⑥ 的 SKIP 分支），
# 所以做成门禁。它危险的地方：
#   * 只在**走到那条分支**时才炸（第一次那条路径潜伏了三轮）；
#   * 报错是 `name�: unbound variable`，`�` 让人看不出是变量名边界问题；
#   * `bash -n` **不报**（语法合法，是运行时展开问题）。
run_gate "⑫ shell 变量边界" bash -c "cd '$ROOT' && python3 kit/scripts/check_shell_vars.py --strict"

# ⑬ 真机/模拟器验证 —— 前十二道全是**静态**的：读源码、读 smali、读文档。
# 没有一道能回答"这个 APK 装得上吗""界面打得开吗""开关留得住吗"。
#
# 2026-10-26 第一次在模拟器上跑通这四件事。它**不**验证钩子是否真的拦住行为
# （那需要 LSPosed + 目标 App），只验证"装得上、打得开、读得到功能数"。
# 没有设备时**跳过而非失败** —— 否则这个仓库在没有手机的环境里永远红。
if [ "${SKIP_DEVICE:-0}" -eq 1 ]; then
  RESULTS+=("SKIP  ⑬ 真机验证（--no-device）")
else
  run_gate "⑬ 真机验证" "$ROOT/module/scripts/verify_on_device.sh"
fi

# ⑭ 自动生成的文档必须能由它的生成器复现。
#
# 为什么单列一门：这类文件过期后**带着"自动生成"的可信度骗人** ——
# 2026-11-02 实测 `work/MODULE_ACTIVITY.md` 少了 `native_exit_guard` 一行、
# 26/12 的分配已经变成 27/11，而文件里没有任何迹象。
# 判据是"真跑一遍再比对"，不是看时间戳（时间戳会被 checkout/touch 改掉）。
# 注意 `run_gate` 把命令当**多个参数**（内部 `"$@"`），所以这里不能写成一个大字符串 ——
# 那样会被当成一个叫 `python3 /path` 的可执行文件名。
run_gate "⑭ 生成文档新鲜度" bash -c "cd '$ROOT' && python3 kit/scripts/check_generated_fresh.py"

# ⑮ 在 before 钩里直接写 `param.result` 的目标，返回值类型必须与写入值相容。
#
# `param.result = X` 的语义是"用 X 当返回值跳过原方法"。对 void 写 null 无害；
# 但对有返回值的方法写错类型，调用方拿到错值或直接崩，而**症状与拦截毫无关系**。
# `hookAll` 钩的是同名**全部重载**，所以判据是"每一个都相容"。
# 覆盖：`bridge_guard`（写 null，要求全 V）、`anti_detect`（写 false，要求全 Z）。
run_gate "⑮ 钩子返回值类型相容" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_result_types.py"

# 重试账本：本轮几次 + 累计几次。
# 本轮有重试就**显式说一句**，不让"绿"掩盖"某个门开始不稳"。
LEDGER="$ROOT/work/gate_retries.log"
if [ "$RETRIED" -gt 0 ]; then
  R24="$(grep -c "$(date '+%Y-%m-%d')" "$LEDGER" 2>/dev/null || true)"
  RTOTAL="$(wc -l < "$LEDGER" 2>/dev/null | tr -d ' ')"
  echo
  echo "⟳ 本轮有 $RETRIED 次重试（今天 ${R24:-0} 次 / 累计 ${RTOTAL:-0} 次，明细见 work/gate_retries.log）"
  tail -"$RETRIED" "$LEDGER" 2>/dev/null | sed 's/^/    /'
  # **趋势而不是单点**：某道门开始经常重试，说明它守护的东西在变得不稳定。
  # 只报"今天几次"看不出趋势；累计次数才够分辨"偶发一次"和"每次都在重试"。
  if [ "${RTOTAL:-0}" -ge 5 ]; then
    echo "   ⚠ 累计已重试 ${RTOTAL:-0} 次 —— 某道门可能在变得不稳定，按门名聚合看看："
    cut -f2 "$LEDGER" 2>/dev/null | sort | uniq -c | sort -rn | head -3 | sed 's/^/     /'
  fi
fi

# ⑯ 「没配置时算不算开」只能有一个答案。
#
# 2026-11-01 的 P0：gate 回调用常量 `true` 兜底 ⇒ 19 个 `defaultOn=false` 的功能
# 在用户没点过开关时照跑（其中 7 个会改宿主行为）。修法是收敛到 `GatePolicy.defaultFor`。
# 这条门禁钉两处会回退的地方：功能回调里的字面量、以及 `HookCore` 灌默认值的来源。
run_gate "⑯ 开关默认值一致" bash -c "cd '$ROOT' && python3 kit/scripts/check_gate_defaults.py"

# ⑰ 已知的 shell 管道陷阱（今天付过的学费，不再重复付）
#
# `| tee f | grep -q` 会因 SIGPIPE 让 tee 早死、日志被截断 ⇒ 后续判断落空 ⇒ 误判 FAIL
# （2026-11-02 在 ⑬ 上真的红过两次，而单独跑同一个检查是 PASS）。
# `set -e` 下的 `$(… | grep -c …)` 会在 0 匹配时让整个脚本退出。
run_gate "⑰ shell 管道陷阱" bash -c "cd '$ROOT' && python3 kit/scripts/check_shell_pipes.py"

# ⑱ `verify.sh` 跑的门禁 ↔ `PARADIGM.md` §5 的门禁表必须一致。
#
# 表是新人了解"这个仓库靠什么保护自己"的唯一入口。今天实测它停在 ⑨，
# 而实际在跑 19 条 —— 少写 8 道，等于告诉读者"只有 10 道保护"，
# 而其中 ⑭⑮⑯⑯ 全是这几天踩坑换来的，恰恰最该被写进去。
run_gate "⑱ 门禁表一致" bash -c "cd '$ROOT' && python3 kit/scripts/check_gate_table.py"

# ⑲ 热路径上的重复计算：语句位置的正则构造 + 三处已修记忆点不许退化
#
# 症状只是多几个对象分配 —— 没有门禁会红、没有测试会失败，
# 所以要用一条断言把 R9/R45/R46 的修法钉住。
run_gate "⑲ 热路径重复计算" bash -c "cd '$ROOT' && python3 kit/scripts/check_hot_path.py"

# ⑳ 写入侧前缀 ↔ 解析侧规则
#
# R12 踩过：模块改了写入格式、规则没跟上 ⇒ 真实抓取 7 行落 UNKNOWN，而**所有离线门禁都是绿的**
# （夹具是按规则写的，规则和写入侧一起漂，夹具照样过）。
# R28 的"真实抓取全认领"只覆盖已经写出去的行；这一道覆盖**还没被触发过的新前缀**。
run_gate "⑳ 写入前缀有解析规则" bash -c "cd '$ROOT' && python3 kit/scripts/check_writer_prefixes.py"

# ㉑ 真实抓取的每一行都被认领（⑳ 的动态一半）
#
# ⑳ 静态地对"新前缀有没有规则"；这一道对"已经写出去的行实际上解析成什么"。
# R12 那次是动态这半发现的（7 行落 UNKNOWN），而当时静态那半不存在。
# `--accept " 0 2 "`：没有近期抓取时是"无法验证"，既不算通过也不算失败 ——
# 并在结果行上写明，不留模糊地带。
run_gate "㉑ 抓取行全部被认领" --accept " 0 2 " \
  bash -c "cd '$ROOT' && python3 kit/scripts/check_capture_claimed.py"

# ㉒ 方法纪律（能静态查的那几条）
#
# 它从建成起**不是任何门禁的一道** —— 一个没人跑的检查器等于没有。
# 2026-11-02 它第一次被跑就找出 25 处不符合项，其中 17 处是当天新写的代码
# （`shell=True` 不带 `start_new_session`：超时只杀 shell，`adb` 活着继续挂）。
run_gate "㉒ 方法纪律（静态可查）" bash -c "cd '$ROOT' && python3 kit/scripts/methodology_check.py --paths kit module"

# ㉓ 磁盘：可再生产物不许无声长大
#
# 它原来**永远返回 0**：算增量、写历史、打印"无显著增长"，但"显著"只出现在文案里。
# 永远绿的门禁比没有门禁更糟 —— 它会让人以为"磁盘有人在管"。
# 2026-11-02 实测：我给错 serial 跑了一次证据包，留下 5 个垃圾目录；若有这道门禁当时就会红。
run_gate "㉓ 磁盘体积在限内" bash -c "cd '$ROOT' && python3 kit/scripts/disk_audit.py"

# ㉔ `--accept` 守卫的自检：含 1 的接受集合必须被拒
#
# `--accept` 用来区分"验过了(0)"与"测不了(2)"，但它开了个口子：
# 写成 `--accept " 0 1 2 "` 的门禁**永远不可能红**。守卫写在 run_gate 里，
# 可守卫本身也可能是装饰 —— 所以这里把 run_gate 原样抽出来喂一个含 1 的集合。
run_gate "㉔ --accept 守卫可触发" bash -c "cd '$ROOT' && bash kit/scripts/check_gate_accept_guard.sh"

# ㉕ 文档里的门禁命令必须真能跑
#
# 门禁表的"命令"列是新人的操作入口。它与代码之间**没有任何断言**：
# 脚本改名、参数改了名，那一列就变成一句看起来能跑的假命令。
# 数字错了顶多一个数不对；**命令错了会让人以为"我跑过了"**，而他跑的是另一件事。
run_gate "㉕ 文档命令可执行" bash -c "cd '$ROOT' && python3 kit/scripts/check_doc_commands.py"

# ㉖ 负对照总检：每一道门禁都必须被证明**有能力变红**
#
# 今天在 STATE.md 里写了 44 处手工负对照，跑完只留在文字里 —— 没有人在下一轮再跑。
# 后果：门禁被改坏（正则范围变窄、判据换成"永远成立"）时，**没有任何东西会报警**，
# 因为门禁自己还是绿的。"一道永远不可能红的门禁，比没有门禁更糟" —— 那就该让它可执行。
# 每个用例：注入一个已知故障 ⇒ 断言退出码非 0 ⇒ try/finally 保证还原。
run_gate "㉖ 负对照总检" bash -c "cd '$ROOT' && python3 kit/scripts/run_negative_controls.py"

# ㉰ 负对照注入态不许留在树上
#
# 2026-11-05 → 11-09 的真实事故：`kit/python/kd_api.py.negctl.bak` 躺了三天，
# 而 `kd_api.py` 一直是注入态（`bad = []  # 负对照：故意永不报错`）⇒
# P1 校验（"blob 长度对但内容是乱码"）**三天都在假通过**。它不是红的，是绿得不对。
#
# 自愈逻辑确实存在，但它**只在"跑负对照"时触发** —— 没人跑负对照的那些天，
# 注入态就冒充正常态。㉖ 只管"门禁能不能红"，管不到"上次的注入有没有收尾"。
#
# 判据：`kit/` 与 `module/` 下出现任何 `*.negctl.bak` ⇒ 红。
# `work/archive/` 不扫（归档证据允许保留历史文件名）。
run_gate "㉰ 负对照无残留" --accept " 0 2 " bash -c "cd '$ROOT' && python3 kit/scripts/check_negctl_leftovers.py"

# ㉗ 设备写入必须读回
#
# 2026-11-02 一天修掉 6 个"报告成功但不验证"的缺陷，其中两个是设备侧写入
# （`set_config.sh` / `set_flag.sh` 都是推完直接 echo 成功）。
# 这道门禁把那条经验固化成判据：**写了就要读回**。
run_gate "㉗ 设备写入有回读" bash -c "cd '$ROOT' && python3 kit/scripts/check_device_writes_readback.py"

# ㉘ 签名请求体组装一致
#
# 同一个约定在 8 处重复：`_t_` 与 `kakorrhaphiophobia` 要跟在 `sign` 之后，
# 不能混在签名参数那段里。**每处单独看都像对的** —— 只有并排看才能发现
# 哪一处与其它不一致（2026-11-03：`probe_paths.py` 少排一个 ⇒ errNo 6）。
run_gate "㉘ 签名请求体组装一致" bash -c "cd '$ROOT' && python3 kit/scripts/check_sign_body_assembly.py"

# ㉙ TLS 只有一个决定点
#
# 2026-11-03 代码审查 P1：6 处**无条件**跳过证书校验，而 `kd_api` 要
# `--insecure` 才跳 —— 同库两种默认。现在统一走 `kit/python/net.py`，
# 这道门禁负责"不许再出现绕过它的地方"。
run_gate "㉙ TLS 只有一个决定点" bash -c "cd '$ROOT' && python3 kit/scripts/check_tls_default.py"

# ㉚ 验证链路上的静默吞噬要有预算
#
# 26 处 `except Exception: pass/continue` 里，多数合理。但有一类不合理：
# **吞掉异常的那段代码本身就是验证逻辑** —— `verify_inputs.py` 读设备 APK 的
# sha256，`adb` 一失败就 pass ⇒ 那个判据悄悄少了一半输入，而报告看不出异常。
run_gate "㉚ 验证链路吞噬有预算" bash -c "cd '$ROOT' && python3 kit/scripts/check_silent_except.py"

# ㉛ 手写源码快照够新
#
# 2026-11-03：负对照误删了 `verify_face.py`，仓库没有 `.git`、
# 备份里也没有它，最后靠 `.pyc` + 行为测试才重建回来 —— **能重建是运气，不是设计**。
# 一个只存在于一处的手写文件，被误删就需要“考古”。
run_gate "㉛ 源码快照够新" bash -c "cd '$ROOT' && python3 kit/scripts/src_snapshot.py --verify --max-age-hours 48"

# ㉜ 默认设备号只有一个来源
#
# 2026-11-03 代码审查 P2：“默认设备号散落 28 个文件”。排除 docstring 里的
# 用法示例后真正生效的是 5 处。漏改一处的后果是某个工具**静默操作另一台设备**。
run_gate "㉜ 默认设备号唯一来源" bash -c "cd '$ROOT' && python3 kit/scripts/check_default_serial.py"

# ㉝ 本地导入顺序
#
# 今天第三次在同一处栽倒（R78 / R85 / R86）：`from device import …` 插到了
# `sys.path.insert` 之前 ⇒ 文件能 parse、门禁全绿，而四个命令行工具一跑就炸。
run_gate "㉝ 本地导入顺序" bash -c "cd '$ROOT' && python3 kit/scripts/check_import_after_path.py"

# ㉝ 没有过期的 .pyc
#
# 2026-11-03：一个过期的 `.pyc` 让“改过的代码看起来没改” ——
# 负对照跑出来是绿的，我差一点把“这个 bug 测不出来”写进 STATE。
# 清掉 `__pycache__` 后行为立刻变了。**判据会指向错误的对象。**
run_gate "㉝ 没有过期的 pyc" bash -c "cd '$ROOT' && python3 kit/scripts/check_stale_pycache.py"

# ㉞ .gz 读取器不许再复制
#
# 2026-11-03：四份逐字相同的 `.gz` 读取器收敛到 `textio.py`。
# 但"收敛过一次"不等于"不会再长出来" —— 下一个人会照抄旁边那份。
run_gate "㉞ gz 读取器唯一" bash -c "cd '$ROOT' && python3 kit/scripts/check_dup_gz_reader.py"

# ㉟ 签名公式唯一
#
# 2026-11-03：同一段 md5 链在四个文件各写一遍。P0-5 正是"有一处没跟着改"造成的 ——
# 症状是服务端对每个请求回 errNo 6，与"参数集不对"完全一样。
run_gate "㉟ 签名公式唯一" bash -c "cd '$ROOT' && python3 kit/scripts/check_sign_formula_dup.py"

# ㉠ SDK 路径唯一
#
# 2026-11-03 代码审查 P2：七个脚本各自写死 `$HOME/Library/Android/sdk`。
# 漏改一处的后果是 `adb: command not found`，指向“你没装 SDK”，
# 与“你装在了别处”完全不像。
run_gate "㉠ SDK 路径唯一" bash -c "cd '$ROOT' && python3 kit/scripts/check_sdk_path_dup.py"

# ㉡ .gz 抓取解析得出 kind
#
# 2026-11-03：`iter_records` 不认 .gz ⇒ 891 份压缩抓取整份变成 UNKNOWN。
# 那不是"少读一半"，是整份抓取变噪声。
run_gate "㉡ gz 抓取可解析" bash -c "cd '$ROOT' && python3 kit/scripts/check_capture_gz_parse.py"

# ㉢ 不许直接 open(--capture)
#
# 2026-11-03：--capture 可给 .txt.gz。直接 open() 会读到 gzip 二进制 ⇒
# 每一行解析失败 ⇒ 报告**空白**，看起来像“这个包里没有这类行”。
run_gate "㉢ 不直接 open 抓取" bash -c "cd '$ROOT' && python3 kit/scripts/check_capture_open.py"

# ㉣ 同名函数参数顺序一致
#
# 2026-11-03：三个 `decrypt` 参数顺序不同，而参数都是字符串 ⇒
# 调换顺序不报错，只会解出一串垃圾。已改名 `decrypt_with_key` 并把旧名改成立刻抛。
run_gate "㉣ 同名同参不反序" bash -c "cd '$ROOT' && python3 kit/scripts/check_same_name_contract.py"

# ㉤ work/INDEX.md 不过期
#
# 2026-11-03：索引停在 11-01，而 `pack_slim` 之后 1332 个点名路径里
# **1212 个**已变成 .txt.gz —— 索引指着一堆不存在的文件。
# 顺带修了它的自指：INDEX.md / CATALOG.md 自己也在 work/ 底下，
# 写索引就改掉被索引的对象 ⇒ --check 永远 STALE。
run_gate "㉤ 证据索引新鲜" bash -c "cd '$ROOT' && python3 kit/scripts/index_evidence.py --check"

# ㉥ 跳过的测试必须登记过、且有上限
#
# R108 的教训：一条测试每次 skip（读 __pycache__ 而 preflight 每次清它），
# 而它本该在验“重建没丢判据常量”。skip 数不变红、不变绿，只是**悄悄少验一条**。
run_gate "㉥ 跳过数在限内" bash -c "cd '$ROOT' && python3 kit/scripts/check_skip_budget.py"

# ㉦ 测试数 / 负对照数只许涨
#
# 删掉一条测试，套件照样全绿 —— 只是验得少了。删掉一条负对照，㉖ 照样全绿 ——
# 只是那道门禁重新变成"可能永远不红"。**变红会叫人，变绿也会叫人，
# 只有"少了一个数"不叫人。**
run_gate "㉦ 覆盖数不缩水" bash -c "cd '$ROOT' && python3 kit/scripts/check_coverage_floors.py"

# ㉧ 循环里不许有裸 open()（句柄泄漏）
#
# 实测全库 234 处裸 open()、61 处在循环里；跑测试时 403 条 ResourceWarning。
# 当前基线 61：这道门禁现在的作用是**不许再涨**，每修一处就下调一次。
run_gate "㉧ 循环里无裸 open" bash -c "cd '$ROOT' && python3 kit/scripts/check_open_in_loop.py"

# ㉨ SIGN URL 提取只许一处
#
# 2026-11-04 代码审查 P2：9 处各写一遍 `split(' SIGN URL: ')`。那个写法三处都是错的：
# 不按 kind 判（把解密响应体里**回显**的 URL 当成请求）、不认中继形态、
# 不处理 `LogSink` 截断的 ` …(719)` 尾巴（拿坏 URL 发请求）。
run_gate "㉨ SIGN URL 只一处" bash -c "cd '$ROOT' && python3 kit/scripts/check_sign_url_dup.py"

# ㉩ 同一个函数里不许有两个 `if kind == '<同一个值>'`
#
# 前一个先 return ⇒ 后一个永远不执行。症状：代码能跑、测试能过、输出看着正常，
# 只是"我加的那段没生效"。2026-11-04 在 capture_transcript 里找到一个
# 死掉的 POPWIN 分支，而它恰好是唯一区分 BLOCK / OBSERVE / PASS 的那个。
run_gate "㉩ 无重复 kind 分支" bash -c "cd '$ROOT' && python3 kit/scripts/check_dup_kind_branch.py"

# ㉪ hot 功能的钩子必须能被关掉
#
# `hot = true` 会**绕过** `BaseFeature.enable()` 的配置检查 ⇒
# "关掉功能"只能靠回调里判配置。2026-11-04 找到 `AntiDetect`：
# hot、四个写侧钩子、文件里既无 `gate =` 也无 `KdConfig.isOn` ——
# 用户关掉它之后，它照样把 isDebuggerConnected / TracerPid 改成 false。
run_gate "㉪ hot 钩子可关闭" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_gated.py"

# ㉫ gate 判据只许一处、每个回调都要判
#
# `Xp.kt` 里那条判据原来抄了 6 遍。抄 6 遍的风险不是抄错，而是**改的时候漏改** ——
# 漏改的那一处让"关掉功能"失效，症状是开关是关的、行为完全不变，**不报错**。
run_gate "㉫ gate 判据只一处" bash -c "cd '$ROOT' && python3 kit/scripts/check_hook_gate_predicate.py"

# ㉬ 不许有完全静默的 except Exception
#
# `except Exception: pass` 把"解不开"和"本来就那样"混成同一件事 ⇒
# 产物里看不出区别，读者会得出相反的结论。豁免必须逐条写理由，且**陈旧豁免也算错**。
run_gate "㉬ 无静默 except" bash -c "cd '$ROOT' && python3 kit/scripts/check_silent_except.py"

# ㉱ 版本差异必须写进文档（真增删 NEW/GONE 逐条有出处）
#
# `work/dex_delta_*.json` 只说"哪些类增删了"，不说是谁。7.9.0→7.10.0：116 个"新增"里
# 91 个只是换 dex 分包，真新增 15 个（`work/reverse710/NEW-CLASSES.md`）。
# 不写进文档的后果：下一个人照着数字找 116 个新类，找完发现 91 个是幻觉。
run_gate "㉱ 版本差异有出处" bash -c "cd '$ROOT' && python3 kit/scripts/check_version_delta_documented.py"

# ㉲ dpsdk 检测面基线
#
# 7.10.0 差点把"体积 +43%、导出 1956→4"读成"检测增强"（其实是 QUIC/TLS 依赖扩张）；
# 而真正检测面变化（`/proc/self/maps` 有 4 处内联引用）是另一条，差点漏掉。
# 这条门禁把（串, 是否有引用, so 哈希, 导出符号）钉住 ⇒ 下次宿主更新会自动提醒重看。
run_gate "㉲ dpsdk 检测面未漂" bash -c "cd '$ROOT' && python3 kit/scripts/dpsdk_detect_baseline.py"

# ㉵ 配置双源一致（设置页读的 == 宿主读的）
#
# 2026-11-09 实测：设置页显示"0 项布尔 / 已启用 13/38"，宿主 `HookCore gates` 是 effective-on 18。
# 两个人对同一台设备的描述差 5 个功能，而**没有任何门禁能发现** —— `set_config.sh` 的回读
# 只验"推的条目在发布目录里"，它不看设置页那一份。无设备时退 2（测不了，不算失败）。
run_gate "㉵ 配置双源一致" --accept " 0 2 " \
  bash -c "cd '$ROOT' && python3 kit/scripts/check_config_dual_source.py --adb emulator-5558"

# ㉳ 套锁契约不破
#
# 2026-11-09 04:0x 的真事故：`with_lock … -- bash verify.sh` 里 verify.sh 再自锁
# ⇒ **子进程等父进程的锁**，`verify_r3.log` 只有一行 `[lock] 持有 …`，一道门都没跑，
# 两条链卡了 12 分钟。死锁没有失败信号（不红不绿不报错），只能靠静态判据。
# 这里钉四件事：with_lock 注入 KD_LOCK_HELD、重入分支在取锁循环之前、
# verify.sh 与 run_negative_controls.py 的自锁守卫都认它（任何新自锁脚本也必须认）。
run_gate "㉳ 套锁契约不破" bash -c "cd '$ROOT' && python3 kit/scripts/check_lock_contract.py"

echo
echo "──────── 结果 ────────"
for r in "${RESULTS[@]}"; do echo "  $r"; done
if [ "$FAILED" -ne 0 ]; then
  echo
  echo "✗ 有门未通过"
  exit 1
fi
echo
echo "✓ 全部通过"
