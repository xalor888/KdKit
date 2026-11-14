# KdKit 7.10.0 → 7.10.2 适配记录

> 2026-11-14 · 宿主：`com.kuaiduizuoye.scan` **7.10.2 / versionCode 1860**
> 旧基线：7.10.0 / 1850（解包树归档 `work/apktool_out_710.tar.gz`）
> 更旧基线：7.9.0 / 1840（`work/apktool_out_790.tar.gz`）、7.7.2 / 1811（`work/apktool_out_772.tar.gz`）
> 差异全表与证据见 [`../work/reverse7102/REPORT-7102.md`](../work/reverse7102/REPORT-7102.md)

## 一句话结论

**7.10.2 是补丁版，混淆名没有重掷 —— 126 个钩子目标全部同名、99 条钩子签名 0 处变化、
钩子方法体逐条只有 `const` 平移（CHANGED = 0）、接口面与桥面 0 增 0 减。
模块只把版本基线推到 `7.10.2/1860`（并把 7.10.0、7.9.0 留在兼容集合），钩子字面量一个字不改。**

## 1. 结构与体量

| 项 | 7.10.0 (1850) | 7.10.2 (1860) | 变化 |
|---|---|---|---|
| APK | 51,289,446 B（arm64 包） | 51,153,282 B（v7a 包） | 不同 ABI，体积不可比 |
| dex | 7 个 | 7 个 | 同 |
| smali 类文件 | 61,348 | 61,349 | **+1** |
| 删除类 | — | **0** | — |
| 新增类 | — | **1** | `smali_classes5/com/kuaiduizuoye/scan/activity/main/fragment/homeai/AiVipPageFragment$c`（点分全名 `com.kuaiduizuoye.scan.activity.main.fragment.homeai.AiVipPageFragment$c`；`rename_match.json` 判定 NEW） |
| 同名类中内容变化 | — | 6,314 | 其中 6,252 仅 `const`；62 是同一 `const` 行的浮点注释变化；2 个行数变化 |
| `AndroidManifest.xml` | — | — | **逐行 0 差异** |
| `res/values/public.xml` | — | — | **逐行 0 差异**（资源表未增删） |

## 2. 钩子：三张表全绿，无需改字面量

```bash
python3 kit/scripts/check_hook_targets.py    --smali work/apktool_out --json work/reverse7102/targets.json
#   → 126/126 resolved（66 个目标类；46 条只提示不判红的 REFLECTIVE/TYPE-ONLY/USED(self) 与 7.10.0 完全一致）
python3 kit/scripts/check_hook_signatures.py --smali work/apktool_out --json work/reverse7102/sig.json
#   → 99 签名吻合 / 0 不符 / 0 无法静态判定
python3 kit/scripts/method_diff.py --old <710树> --new work/apktool_out \
        --targets work/reverse7102/targets.json --json work/reverse7102/method_diff.json
#   → IDENTICAL 471 / CONST-SHIFT 125 / CHANGED 0 / CLASS-GONE 23（23 条全是 android/java 平台类）
```

`method_diff.py` 是本轮新增的工具（`kit/scripts/`）：它把"这版到底动了哪个方法"从人工读 diff
变成一条命令。判据三层 —— 去调试指令后逐行相同（IDENTICAL）、差异只在 `const` 立即数
（CONST-SHIFT）、其余（CHANGED）。

## 3. 唯一有真实改动的类（不在钩子清单里）

`AiVipPageFragment`（AI 首页 VIP 页）：新增 `public L()Lxs/c;`（页面状态出口）+
内部类重组（`$b` 505→102 行，`$c` 为新类）。**该类不在 66 个钩子目标类里** —— 检查：

```bash
python3 -c "import json;print([r['class'] for r in json.load(open('work/reverse7102/targets.json'))['rows'] if 'AiVip' in r['class']])"
# → []
```

所以本轮的唯一代码改动**不会碰到任何钩子**。

## 4. 一处旧说法的更正（本轮实测）

`MIGRATION-710.md` §2 把方法体里的 `const/16 v5, 0x5267 → 0x527d`（+0x16）称为
"资源 ID 常量平移"。实测两版都验证：该常量是
`invoke-static … Lcom/meituan/robust/PatchProxy;->proxy(…, Z, I, …)` 的 **`I` 形参（方法索引）**，
紧贴 `invoke-static` 的前一行；而本轮 `public.xml` **逐行 0 差异**、这个常量却有 +1/+2 的混合平移。

⇒ 它随"插桩方法总数"平移，**不是资源 ID**。判据：真正的资源 ID 在 smali 里以完整的
`0x7f…` 出现，不会是 4 位小整数。往下适配时，**不要**再拿这个数字当"资源表变了"的信号。

## 5. 兼容性

`HostVersion` 的判定（`module/app/src/main/java/dev/xalor/kdkit/HostVersion.kt`）：

```kotlin
BASELINE_VERSION_NAME = "7.10.2"   // 1860
COMPATIBLE_VERSIONS  = setOf("7.10.0/1850", "7.9.0/1840")
```

三版共用同一套混淆名，所以同一个模块同时服务三版；版本不一致时只打一条 drift 警告，不阻止运行。

## 6. 真机验证（prototype 级，边界写清）

**边界**：应用宝当前只发 `armeabi-v7a` 单 ABI 包，本项目 AVD（android-36 arm64，64-only）
装不上（`INSTALL_FAILED_NO_MATCHING_ABIS`）。官方 arm64 的 7.10.2 包本轮**没取到**
（CDN 目录名未知；更新闸门只返回更旧的 6.21.11 的 64 位包）。

**替代验证**：保留 7.10.2 的 dex/资源，把 native 库换成 7.10.0 的 `arm64-v8a`（34 个同名库），
debug 证书重签 → `work/reverse7102/repack/kd-7102-repack-signed.apk`。装到 `emulator-5558` 实测：

| 检查 | 结果 |
|---|---|
| 安装/版本 | `Success`，`7.10.2 / 1860 / primaryCpuAbi=arm64-v8a` |
| 启动 | `AliasActivityDefault` 起来，隐私协议页正常渲染（`screen_7102_after_launch.png`） |
| 注入 | `HookCore ready (38 features)` · `hooks 101 ok / 0 failed` |
| 版本守卫 | `host com.kuaiduizuoye.scan 7.10.2 (1860) sdk=36` |
| 反检测 | `neutralised lk.f.c (FLAG_DEBUGGABLE)` / `Debug.isDebuggerConnected` 持续中和 |

**这个重签包不是交付物**：证书变了 ⇒ 所有证书派生的签名请求会失效（本项目既有结论）。
它只回答"101 条钩子在新版能否全部命中"，答案：能。

## 7. 回归

`module/scripts/verify.sh`（五道门 + 48 条门禁），本轮对着 **7.10.2 的解包树**跑：
`work/apktool_out` 已切换为 7.10.2（旧树归档 `work/apktool_out_710.tar.gz`）。

| 结果 | 门 |
|---|---|
| PASS | ① 单测（**529** 条 / 8 skipped）、①b 抓取解析器、② 编译、③ 功能表一致、④ 钩子目标（126/126）、⑤ 钩子签名（99/99） |
| PASS | 门禁 47 条（含 ㉱ 版本差异有出处、㉲ dpsdk 检测面、㉓ 磁盘、㉤ 索引新鲜、㉦ 覆盖数） |
| **FAIL** | **⑬ 真机验证** —— 设备装的是 7.10.0（sha `51d7cabc…`），仓库分析的是 7.10.2（sha `31489f8d…`）|

**⑬ 为什么红，以及为什么不改门禁**：`check_device_matches_analysis.sh` 比的是"设备上装的 APK
与仓库里正在分析的那份是否**字节一致**"。本轮分析基线是 7.10.2（v7a 单 ABI 包），而本项目
AVD 是 64-only，**官方包装不上**，设备只能留在 7.10.0。这条红是**真的**：所有"目标存在/签名一致"
的结论只对仓库里那份 7.10.2 成立。要绿只有两条路 ——
(a) 拿到官方 **arm64** 的 7.10.2 包装进设备；或 (b) 把基线退回 7.10.0。
本轮不动门禁、也不伪造通过；收口条件写在 `work/reverse7102/REPORT-7102.md` §6 第 3 条。

设备侧另有一轮**兼容性**验证（与 ⑬ 互补）：把新编译的模块装到装着 7.10.0 的设备上，
`host com.kuaiduizuoye.scan 7.10.0 (1850)` **没有 drift 警告**、`hooks 101 ok / 0 failed`
⇒ 兼容集合（7.10.0/1850、7.9.0/1840）确实生效。
