## Goal

把 `baicizhan-kit`（`/Users/xalor/Documents/baicizhan-kit`）的 **R3（kit 工具链）从 `[~]` 做到 `[x]`**，让"这个项目现在到底验到了什么"可以用**命令**回答，而不是靠读文档相信。

需要真实交付的四项能力（结果层面）：

1. **环境拉起入口** `kit/scripts/env_up.sh`：一条命令把项目自有模拟器（`kd1`）拉到"模块能注入"的状态；设备/框架缺件时**明确点名缺什么**，绝不伪装成功。
2. **统一验收入口** `kit/scripts/acceptance.py`：一条命令复跑项目声称的全部结论（hook 目标、功能表一致性、构建产物、配置通道、抓取落盘、模块运行态），输出逐项 `PASS/FAIL/ENV` 清单 + 三类计数汇总行 + 三态退出码。
3. **模块运行态报告** `kit/scripts/module_report.py`：对给定本地样本（模拟 LSPosed 日志 + 模拟 `bczkit_capture.txt`）产出 Markdown 报告，回答"三个功能各自的开关状态 / 是否装上 / 本轮有无可观测证据"，**没证据必须如实标注**。
4. **文档与现实一致**：新增 `kit/README.md` 说明每个脚本用途与退出码契约；根 `README.md` 的 R3 行改为 `[x]` 并写入真实可跑命令与本次取证文件路径。
5. **退出码契约统一三态**（沿用本项目 `ab-run.sh` 既有约定）：`0` = 全通过；`1` = 真的失败；`2` = 环境不具备，不可据此判负。**禁止**把"没设备"渲染成 PASS，也禁止渲染成 FAIL。

## Acceptance criteria

以下每条由我亲自执行并记录真实输出；达不到即视为未完成。

1. **hook 目标门禁未退化**：`python3 kit/scripts/check_hook_targets.py` → 退出码 `0`，末行 `9/9 resolved, 0 missing`。
2. **功能表门禁未退化**：`python3 module/scripts/check_feature_parity.py` → 退出码 `0`，输出含 `功能表一致`。
3. **构建通过**：`cd module && JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gw assembleDebug` → 含 `BUILD SUCCESSFUL`，且 `module/app/build/outputs/apk/debug/app-debug.apk` 存在、非空（`stat -f%z` > 0）。
4. **env_up.sh 基本契约**：文件存在且可执行（`test -x`）、`bash -n kit/scripts/env_up.sh` 语法检查退出码 `0`、`kit/scripts/env_up.sh --help` 退出码 `0` 并打印用法。
5. **设备缺失路径可验证（三态第 2 态）**：先以 `adb devices` 证明当时无 `device` 状态设备；再运行 `kit/scripts/env_up.sh`，退出码**恰为 `2`**（不是 0、不是 1），且 stdout/stderr 点名缺项，至少覆盖「无在线设备 / 无 Magisk / 无 Vector(vectord)」三类中的实际缺项。
6. **acceptance.py 无设备时行为**：退出码为 `2`；逐项清单中**离线项（hook targets、feature parity、构建产物）显示 PASS**；**设备项显示 `ENV`** 并注明原因；汇总行明确区分「通过 / 失败 / 环境缺失」三类计数。**任何设备项在无设备时都不得显示 PASS**。
7. **module_report.py 正反两测**：对给定两份本地样本（模拟 LSPosed 日志 + 模拟 `bczkit_capture.txt`）生成 Markdown 报告，退出码 `0`，报告表格的功能行**恰好**为注册表三个 id（`token_observer` / `sign_probe` / `sign_bypass`，无多余行、无缺失行）；对一份"已开启但零证据"的构造样本，该行必须标注无证据（而非算作正常）。
8. **负样本（坏门禁必须红）**：在**仓库外**临时副本上把 `kit/hook_targets.json` 中某个描述符改坏，运行 `acceptance.py` → 退出码为 `1`，且失败项被点名。证明它不会永远绿。
9. **文档命令可复现**：根 `README.md` 与新建 `kit/README.md` 中每一条 `bash` 命令块，按原文执行所得退出码与文档声称一致；两份文档中不存在指向不存在脚本的命令。
10. **状态与取证**：根 `README.md` 的 R3 行由 `[~]` 改为 `[x]`；`work/` 下新增一份本轮验收证据文件（真实命令原始输出，非手写摘录），并在 README 中写出其路径。
11. **未退化**：`kit/hook_targets.json` 的 9 个目标内容不变；`module/app/src` 下全部源文件哈希与本轮开工前基线一致（基线：`find module/app/src -type f \( -name '*.kt' -o -name '*.xml' \) | sort | xargs shasum -a 256 | shasum -a 256` = `e6df5b19cbf008915ba557be69fb12f6dc479bbd5b25b3485e05da0e1ad6d757`）。仓库尚未纳入 git，故以哈希对比替代，并如实说明。

## Boundaries

- **不动被测物**：不修改、不重签、不安装 `百词斩_7.10.22.apk`；不修改 `module/app/src` 下任何 Kotlin/XML 源码。
- **不碰设备与环境**：不启动/重启/擦除任何模拟器，不安装 Magisk/Vector/frida-server，不下载任何东西。设备侧结论一律只以「环境不具备（exit 2）」呈现。
- **不越界**：`kuaidui-kit` 只读参考，绝不写入；不修改 `/Users/xalor/Documents` 下其他任何项目。
- **不为变绿而放松门禁**：不调低断言、不把缺失项从检查列表删掉、不用 `|| true` 吞失败；三态语义不得退化成两态。
- **不动既有证据**：`work/` 下已有文件（`BCZ_REPORT.md`、`T11-LOGCAT.txt`、`R2-VERIFICATION.txt`、`ab-run-*` 等）只读；本轮证据以新文件名追加。
- **红线**：任何凭据 / token / 密钥的实际值不写入仓库内任何文件；抓取样本一律使用合成数据。
- **明确不在本轮范围**（须在文档中如实保留为已知开放项）：登录态 `access_token` 实际取值、URL 中 `f42507d` 段语义。
- **诚实兜底**：若构建或任一验收项因本机环境原因确实无法达成，如实报告为阻塞项，不粉饰、不跳过、不缩小检查范围。
