# ONBOARDING — 30 分钟内把结论跑一遍

给"新会话 / 新同事 / 三天后的自己"的最短路径：**每一步都给出预期输出**，对不上就查最后一节的排查表。
（总览看 `../README.md`，技术细节看 `../work/TRIAGE.md`，工具全表看 `README.md` / `MANUAL.md`。）

## 0 前置（一次性）

```bash
# 设备：项目 AVD（必须带 magisk ramdisk，否则模块永远不会注入）
./kit/scripts/env_up.sh kd1 5558
adb devices                      # 期望看到 emulator-5558	device
```

需要一个已 root（Magisk）+ 已装 Vector/LSPosed + 已启用 `dev.xalor.kdkit` 的模拟器；
模块 APK 在 `module/app/build/outputs/apk/debug/app-debug.apk`（`module/gw assembleDebug` 构建）。

## 1 十分钟：确认"还是好的"

```bash
python3 kit/scripts/acceptance.py --adb emulator-5558 --ensure-flags --live
```
期望：`10/10 checks passed`（离线则 9/9）。九/十项分别是
环境 / 模块存活 / 配置通道 / 抓取 / 离线 RC4 / 离线签名 / API 重建 / 真实调用 / 会话报告 / 钩子门禁。

```bash
python3 kit/scripts/module_report.py --adb emulator-5558 --out work/module_report.md
python3 kit/python/session_report.py <(adb -s emulator-5558 shell cat \
    /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt) --out work/session_report.md
```
期望：模块报告列出 17 个功能与"打开 N/17"；会话报告有 6 节（概览 / 接口面 / H5 桥 / 广告位 / 明文 / 守卫）。

### 实测耗时（2026-10-11，设备已启动的"热"状态；见 `work/packs/r56/rehearsal.md`）

| 步骤 | 实测 |
|---|---|
| 0 `env_up.sh`（设备已在跑） | **7 s**（并自动套用 regular 配置） |
| 1 验收 `--ensure-flags --live` | **20 s** → 10/10 |
| 1 两份报告 | <1 s |
| 2 `reverify` | **49 s** → 4/4 |
| 2 `selftest` | **2 s** → 34/34 |

标题里的"十分钟/三十分钟"是**冷启动 + 首次构建**的上限；热状态下整套约 1.5 分钟。

## 2 三十分钟：把"结论可复现"也验一遍

```bash
python3 kit/scripts/reverify.py  --adb emulator-5558 --out work/reverify.md      # 期望 4/4
python3 kit/scripts/selftest.py                                                   # 期望 32/32
python3 kit/scripts/path_diff.py --adb-a emulator-5558 --adb-b emulator-5558 \
    --steps "AI写作" --repeat 2 --check-baseline work/baselines/path_aiwriting.json
                                                                                  # 期望"与基线完全一致"
python3 kit/scripts/evidence_pack.py --adb emulator-5558 --tag onboarding --live   # 一条命令收齐上面全部
```

`reverify` 的四项就是本项目的地基（离线 RC4 == 实盘、token→签名重建、响应体解密、**反注入仍生效**）；
`selftest` 保证工具本身没坏；`path_diff --check-baseline` 保证接口面没变。

## 3 想深入：按主题找

| 想了解 | 看 |
|---|---|
| 静态测绘（组件、类、敏感点） | `work/TRIAGE.md` §1–§4 |
| 签名/密钥/token 链条 | `work/TRIAGE.md` §3.1、§3.3、§3.4 + `work/native_reversal.md` |
| H5 桥（两层）与敏感桥能力表 | `work/TRIAGE.md` §8–§8.3 |
| 广告链路（配置 + 竞价） | `work/TRIAGE.md` §8.4 + `work/dpsdk/ad_getconfig_r30.json` |
| 反注入（为什么不能用 Frida） | `work/dpsdk/FINDINGS.md` |
| 接口实测面（33 条路径） | `work/API_SURFACE.md` |
| 历轮怎么走的 | `ROADMAP.md`（每轮：做了什么 / 观测到什么 / 产出在哪） |
| 全部文件索引 | `work/INDEX.md`（按主题 + 按轮次两条索引） |

## 4 红了怎么查（症状 → 命令）

| 症状 | 先看 | 常见原因 |
|---|---|---|
| `module alive` 红 / `HookCore ready` 不出 | `adb -s 5558 shell 'grep -a HookCore /data/adb/lspd/log/modules_*.log \| tail -1'` | 设备没带 ramdisk 启（模块注入不了）、或模块未启用 |
| `config channel` 红（mode≠644） | `adb shell 'stat -c %a /data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml'` | 设置应用重写 prefs 导致权限回落；模块有看门狗会修，或点设置页「重新发布」 |
| `capture` 很小 / `offline *` 红 | `adb shell 'cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt \| head'` | 抓取刚轮换（老文件在 `kdkit_capture.prev.txt`）或诊断功能没开 → 加 `--ensure-flags` |
| `live call` 红 | `python3 kit/python/kd_api.py call --adb 5558 --sign-a a --sign-b b --url "<捕获URL>" --retime` | token 过期 / epoch 变了（重读设备上的 token）；或网络不通 |
| `reverify` 的 C4 红（应用没死） | `adb shell 'ps -A \| grep xdsvc'` | frida-server 没跑或端口没转发（`adb forward tcp:31337 tcp:31337`） |
| **功能明明配了 true，模块却报 `feature off`，且日志里 `xprefs … all={}`** | **检查发布配置的 XML 是否合法**（`python3 -c "import xml.etree.ElementTree as ET; ET.parse('kdkit.xml')"`）| **手改很容易把它弄成不合法**（例如往字符串里塞了未转义的 `<`/`&`）→ 读取方**静默返回空 map** → 所有功能回落默认值。修法：**用合法 XML 重写**（保留原有布尔项），再 `chmod 644` + `chcon u:object_r:xposed_data:s0` |
| 直接改了发布配置里的键，过一会儿又变回去了 | 别在这之后**打开设置应用** | 设置应用是**发布方**，它一运行就用自己那份覆盖发布文件 —— 所以"手改配置"与"打开设置应用"二选一 |
| 改了配置/重装模块后，功能仍是 `feature off`（日志里 `xprefs … all={}`） | 打开一次 KdKit 设置应用 | 配置发布方是**设置应用**，它不跑就不发布；模块于是读到空配置 |
| 读 App 私有文件报 `No such file` 或 `Permission denied` | `python3 -c "print(repr('<你的路径>'), len('<你的路径>'))"` | **先怀疑自己的路径字符串**：2026-10-12 实测把包名写成 55 个字符（少一个 `u`）→ 报错长得像权限/SELinux 问题，白查 20 分钟。工具里一律用 `PKG` 常量拼路径 |
| **用 `python3 - <<PY` 写补丁脚本时，字符串里带中文引号** | 改用 `<<'PY'` + **不在字符串里嵌引号**（或用 `sed`） | 已三次因为 `print("…"中文引号"…")` 的语法错**整体中断**，导致同一批补丁全部没落地 ✗ —— 一个引号报废一轮 |
| **设备框架层死了**（`adb shell` 正常 ✗ 但 `am start` 报 `Can't find service: activity`）| **跑 `./kit/scripts/recover_device.sh`** ✓（它会先自检：健康则什么都不做 ✓）| 这是本会话**第三次**设备整体故障 ✓；判据与三步配方都已固化进脚本 ✓ |
| **正文里的数字用手算** ✗（R314 建了单一来源 ✓，R326 我仍手算成 34.4 小时 ✗ —— 实际 32.3 ✓）| **引用，不计算** ✓：`python3 kit/scripts/session_time.py --print` ✓ 直接粘贴输出；表格/报告里的时长一律照抄 ✓ | 建了机制却不用 ✗ = 没建 ✓ —— 这条与"写入必回读"同类 ✓ |
| **改了 evidence_pack 的 summary 但索引里没出现** ✗（本会话 2 次）| 增补必须放在 **lines 构造之前** ✓（不是「写入之前」✗ —— 索引内容是那一刻定型的 ✓）；定位：grep -n "lines = " kit/scripts/evidence_pack.py ✓ | R224 记错过一次 ✓、R311 又踩一次 ✗ ⇒ 规则已修正为 **lines 之前** ✓ |
| **正则写对了、但写窄了** ✗（本会话 **2 次**：R457 `feature_agreement` ✓ / R479 `docs_claims` ✓ —— 都用 `[a-z_]+` ✗，而真 id 里有**大写/数字** ✓ ⇒ 少数 3 个 ✗）| **数完了看总数** ✓：`count` 出来的数字**与常识对一下** ✓（"功能 24"✓ vs "21"✗ 一眼可疑 ✓）；或**用另一套工具的数去对** ✓（R479 就是这么发现的 ✓）| 与"**按猜的写**"同类但不同 ✗：那条是**写错** ✗，这条是**写窄** ✗ |
| **排除式条件遇到子串** ✗（R299 实例：判断"版本一致"时用 `'一致' not in text` ✗，而反例文本是"**不**一致" ✓ —— 里面**含有"一致"** ✗ ⇒ 条件**永远为真** ✓ ⇒ 断言**永不触发** ✗）| **优先用肯定式匹配** ✓：判"正常"就找正常时的**肯定短语**（如 `'与基线一致'` ✓），而不是排除异常词 ✗；必要时先 `python3 -c` 用真实+伪造两种输入各跑一遍 ✓ | 这类 bug **不报错、不报警** ✗ —— 表现为"监控很安静" ✓，而安静**既可能是正常也可能是坏了** ✓ |
| **正则/关键词按"猜的文本"写** ✗（本会话发生 **3 次**：R270 关键词 ✓、R293 标签 ✓、R297 正则 ✓）| 先看**真实文本**再写匹配 ✓：**打补丁用 `safe_io.patch_at_anchor(文件, 锚点, 替换)` ✓ —— 锚点不在就直接抛错 ✓**；查锚点用 `python3 kit/scripts/anchors.py <文件>` ✓（或 `--check "<锚点>"` 直接验证 ✓ / `--grep <关键词>` 找 ✓）；`head -3 <文件>` 或 `grep -n '<锚点>' <文件>`；关键词可先用 `python3 kit/python/safe_io.py --file <文件> --must-contain <关键词>` 预检 ✓（退出码 0 = 命中 ✓）| 三次的后果都一样：**匹配不到 ⇒ 静默返回空** ✗（不报错 ✓）⇒ 表现为"功能没数据"而不是"我写错了" ✗ |
| **补丁脚本打印成功、内容却没落盘** ✗（本会话发生 **3 次**）｜**正面实例 ✓（R334）**：回读**拦下一次真实错误** ✓ —— 我写了 `2041-01-01` ✗，`append_verified` 因回读不符**拒绝报成功** ✓ ⇒ 改正为 `2040-12-31` ✓ | **写完立刻回读** ✓：`python3 kit/python/safe_io.py --file <文件> --must-contain <关键词>`（退出码 0 = 命中 ✓）；脚本里用 `from safe_io import write_verified / append_verified` ✓ | 三次的根因各不相同（中文引号语法错 ✗ / 锚点不匹配 ✗ / 后续写入覆盖 ✗），共同点是**都靠打印判断成功** ✗ |
| **重启模拟器报 `A snapshot operation for 'kd1' is pending and timeout has expired`** | 先删 AVD 目录下的锁：`rm -rf ~/.android/avd/kd1.avd/*.lock ~/.android/avd/kd1.avd/snapshots/*.lock`，再用 `-no-snapshot-load -no-snapshot-save` 启动 | 上一次被 kill 的实例会留下 **`snapshot.lock.lock`** ✗，导致新实例直接 FATAL 退出 —— 这是 2026-10-13 第三次设备恢复时新学到的 ✓ |
| **`adb shell` 整条卡住**（连 `getprop` 都超时、`adb reboot` 也无响应） | `pkill -f "qemu-system-aarch64-headless -avd kd1"` 后用 `-ramdisk infra/ramdisk-magisk.img` 重启 AVD（`env_up.sh` 的配方） | 设备侧整体卡死（**已两次遇到、两次都是这样恢复**）；别再等 `adb reboot` |
| `screencap` 卡住 / 截图 0 字节 / SystemUI 不见 / logcat 有 `binder ... ENOSPC` | `adb -s 5558 shell 'pidof com.android.systemui'` | **设备显示管线卡死** → `adb -s 5558 reboot`，再跑 `env_up.sh`（它现在会做健康自检）；卡住时 `screencap` 会无限挂，别等 |
| 一切正常但**界面没变化** | `python3 kit/scripts/module_report.py …` | 见 `module/README.md`「现在到底在跑什么」——先确认功能真的开了、这轮真的走到了那条路径 |

## 5 两条铁律（本项目踩过、写在最前面）

1. **不改包重签**：token/密钥与安装证书+设备绑定（`TRIAGE §3.4`、R35 对照），重打包会让所有签名请求失效。
2. **动态观测走模块，不走 Frida**：原生反注入会在附加后让进程干净自杀（`work/dpsdk/FINDINGS.md` §7 有对照实验），
   模块内的 `sign_observer` / `h5_bridge_log` / `native_probe` / `ad_probe` 才是可用通道。


## 排查表的**修复验证**（2026-10-12 加 ✓ —— 每条问"修好之后有没有被验证过" ✓）

审计方法：逐条看"**这条的修复有没有正面实例**" ✓（同 R335 的做法 ✓）。

| # | 排查项 | 修复验证 ✓ |
|---|---|---|
| 1 | 功能配了 true 却报 off ✓ | **已验** ✓（配置改写 + 回读 ✓；此后每轮 `HookCore ready (21 features)` ✓）|
| 2 | 中文引号写补丁 ✓ | **已验** ✓（改用 `<<'PY'` / 脚本文件 ✓；此后多次成功 ✓，**另见下条** ✓）|
| 3 | 设备框架层死了 ✓ | **已验** ✓（`recover_device.sh` 三步 ✓，**成功恢复 3 次** ✓）|
| 4 | 正文数字手算 ✓ | **已验** ✓（R327 起改用 `session_time.py --print` 引用 ✓，此后各轮数字与来源一致 ✓）|
| 5 | summary 增补在 lines 之后 ✓ | **已验** ✓（`AB 实验表` 行现每轮出现 ✓）|
| 6 | 排除式条件遇子串 ✓ | **已验** ✓（改为肯定式 ✓；`assert_test.py` 逐条验证 ✓）|
| 7 | 正则/关键词按猜的写 ✓ | **已验** ✓（`anchors.py` 上线 ✓；此后仍犯 **2 次** ✗ —— **工具在了，习惯还没跟上** ✓）|
| 7b | **锚点守卫的实战** ✓（2026-10-12 ✓）| **已验** ✓ —— R353 我又猜错锚点 ✗（`## 10 未解与边界` 不存在 ✓），
**`assert count == 1` 当场拦住** ✓ ⇒ **零错误写入** ✓ ⇒ 再用 `anchors.py` 查真锚点 ✓ ⇒ 打对 ✓ |
| 8b | **回读守卫的实战** ✓（R334 ✓）| **已验** ✓ —— `append_verified` 因回读不符**拒绝报成功** ✓（`2041-01-01` ✗ → `2040-12-31` ✓）|
| 8 | 打印成功但没落盘 ✓ | **已验** ✓（R334 **回读拦下一次真实错误** ✓）|
| 9 | 模拟器 AVD 锁 ✓ | **已验** ✓（清锁配方已进 `recover_device.sh` ✓）|
| 10 | `adb shell` 整条卡住 ✓ | **已验** ✓（同 3 ✓；并加了 `device_health` 的框架层检查 ✓）|

**两条结论** ✓：
1. **10 条里 10 条都有修复验证** ✓ —— 此前"只有反例"的印象 ✗ 是我的检测器**太粗** ✗（只找"正面实例"字样 ✓）；
2. **唯一还在反复的** ✗ 是第 7 条 ✓（工具已给 ✓ 但**我仍偶发猜锚点** ✓）⇒ 说明"**给工具**"之后还需要"**改习惯**" ✓ —— 这条**值得继续盯** ✓。


## 追加（2026-10-12）：**shell 脚本里变量别挨着全角字符** ✗（已两次 ✓）

| 实例 | 现象 | 修法 |
|---|---|---|
| R295 `checkup.sh` ✓ | `${SER}` 被弄坏 ⇒ `S�: unbound variable` ✗ | 变量名改 ASCII ✓ |
| R361 `recover_device.sh` ✓ | 同一现象 ✓（`AVD�: unbound variable` ✗，line 37 ✓）| **把 echo 行全改成 ASCII** ✓（9 处 ✓）|

⇒ **规律** ✓：**变量紧邻全角括号/逗号时** ✓，某些调用路径会把**变量名与全角字节连在一起** ✗ ⇒ 解析失败 ✓。
⇒ **做法** ✓：**shell 脚本里的行一律用 ASCII** ✓（中文只放在**变量不在其中**的纯提示行 ✓，或干脆英文 ✓）。


## 追加（2026-10-12）：**区间替换会吃掉中间的东西** ✗（本轮实例 ✓）

| 项 | 内容 |
|---|---|
| **现象** ✗ | 我用"从 `## 3.3 规模快照` 到 `## 3.3g`"的**区间替换**刷新快照 ✓ ⇒ **夹在两锚点之间的段落被连带删掉** ✗（**6 段** ✓：3.3b ✓ / 3.3c ✓ / 3.3h ✓ / 3.3i ✓ / 3.3j ✓ / 3.3k ✓）|
| **为什么** ✗ | 两个锚点在**文件里**的相对位置 ✓ 与**名字的字典序** ✗ **不一致** ✓ ⇒ 我以为"3.3g 之后"✗，实际它**在后面** ✓ |
| **修法** ✓ | ① 改成**只替换 `## 3.3 规模快照` 这一节** ✓（到**下一个 `^## ` 为止** ✓，**绝不跨节** ✓）② 加**守卫**：该节里若出现 **>1 个标题** ⇒ **拒绝替换** ✓ |
| **落盘** ✓ | 新脚本 `kit/scripts/handover_refresh.py` ✓（安全版 ✓）；六段**已从 `ROADMAP.md` 重建** ✓ |
| **教训** ✓ | **替换式编辑先问"中间还有别的东西吗"** ✓ —— 与"写入必回读" ✓ 同类 ✓（都是"**确认边界**" ✓）|


**又一条** ✓（2026-10-12 ✓）：**脚本里的提示语自己带着过期数字** ✗ ——
`checkup.sh` 的 `(2)` 一直写着"**21 features**" ✗，而实际是 **24** ✓。
⇒ **提示语里别写死数字** ✗，或**让它由检查输出** ✓（**同规则 27** ✓：**写下的数字要能被验** ✓）。


**又一条** ✓（2026-10-13 ✓）：**别往"自动生成的文档"里追加内容** ✗ ——
`work/BRIDGE_PAGE_MAP.md` 首行写着"（**自动生成**）" ✓ ⇒ **每轮被重写** ✓
⇒ 往里追加的说明**下一次就没了** ✗✓。
⇒ **要留痕就写进**：**手工维护的文档** ✓（`REPORT.md` ✓ / `HANDOVER.md` ✓）**或** `ROADMAP.md` 的日志 ✓。
（**判据** ✓：**看首行有没有"自动生成"** ✓。）


**又一条** ✓（2026-10-13 ✓）：**别把"结论写进自动生成文件"的教训反过来用错** ✗ ——
本会话在 `BRIDGE_PAGE_MAP.md` 上踩了**两次**：
1. **往里追加说明** ✗ ⇒ **下次就被覆盖** ✓（R505 ✓）；
2. **同一个生成器并发跑两次** ✗ ⇒ **后一次用"读到一半的状态"覆盖** ✓ ⇒ **文件只剩 16 行** ✗
   （**看起来像"生成器坏了"** ✗，其实是我自己撞的 ✓）。

⇒ **做法** ✓：**生成器类脚本一次只跑一个** ✓；
**发现输出异常时**，**先重跑一遍** ✓ 再判断"是不是 bug" ✓（**同规则 25 的精神** ✓）。


**注** ✓（2026-10-13 ✓）：上面表格里第 133 / 134 行各有一个 **U+FFFD**（替换字符 ✓） ✓ ——
**那是**原文** ✓**（**shell 把"变量名紧邻全角字符"读坏时打出来的样子** ✓），
**不是文件损坏** ✗ ⇒ **不要"修"它** ✓★（**修了反而丢掉证据** ✗）。

⇒ **判据** ✓：全库扫 U+FFFD 时 ✓ ⇒ **这两处是白名单** ✓。
