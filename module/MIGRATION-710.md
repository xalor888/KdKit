# KdKit 7.9.0 → 7.10.0 适配记录

> 2026-11-08 · 宿主：`com.kuaiduizuoye.scan` **7.10.0 / versionCode 1850**
> 旧基线：7.9.0 / 1840（解包树以 `work/apktool_out_790.tar.gz` 保留）
> 更旧基线：7.7.2 / 1811（`work/apktool_out_772/`）

## 一句话结论

**7.10.0 是增量更新，混淆名没有重掷** —— 126 个钩子目标全部同名、方法签名 0 处变化、
方法体只差资源 ID 常量整体 `+0x16`，接口面与桥面一条没增没减。
⇒ 模块**不需要改任何钩子字面量**，只需要把版本基线推到 7.10.0/1850（同时保留 7.9.0/1840 兼容）。

## 1. 结构与体量

| 项 | 7.9.0 (1840) | 7.10.0 (1850) | 变化 |
|---|---|---|---|
| APK | 50,903,876 B | 51,289,446 B | +385,570 B |
| dex | 7 个 | 7 个 | 同 |
| smali 类文件 | 61,338 | 61,348 | +10 |
| 删除类 | — | 106 | — |
| 新增类 | — | 116 | — |
| 同名类 | 61,232 | 61,232 | — |
| 其中内容变化 | — | **6,674** | 见 §2 |
| arm64 native 库 | 34 | 34 | 33 逐字节相同 |

删除集中在 `com.zuoyebang.design`（badge / button / card 旧组件）；新增集中在
`com.kuaiduizuoye.scan.activity.settings.PersonalRecommendSettingActivity`（个性化推荐设置页，
两个类含内部类）与 `ri.*` / `tg.*` 少量混淆类。

## 2. 内容变化 = 资源 ID 常量平移，不是逻辑变化

6,674 个同名类"内容不同"，但逐方法比对（去 `.line` / `.local` 等调试指令后）显示：
**差异只有一条 `const/16` 的资源 ID**，且全部是同一个偏移量 `+0x16`（= +22 个新增资源 ID）。

实测样本（`work/method_diff_790_710.json` 全部 126 个目标方法的逐条判定）：

| 方法 | 7.9.0 | 7.10.0 | 差异 |
|---|---|---|---|
| `vm.g.h`（RC4Helper） | `const/16 v5, 0x5267` | `const/16 v5, 0x527d` | +0x16 |
| `aj.a.p`（VIP） | `const/16 v5, 0x3903` | `const/16 v5, 0x3919` | +0x16 |
| `kl.a.getBody`（HTTP body） | `const/16 v5, 0x4716` | `const/16 v5, 0x472c` | +0x16 |
| `ul.b.f`（家长模式） | `const/16 v5, 0x4914` | `const/16 v5, 0x492a` | +0x16 |
| `vm.g.t` / `dj.f.d` / `ov.l.<init>` | — | — | **零差异** |

这与 7.7.2→7.9.0 时那 2,383 个"只差资源常量"的类是同一种形态：
**R 表扩张导致 `const/16` 常量位移，代码结构不动**。

## 3. 钩子目标：126/126 全部同名可用

```bash
python3 kit/scripts/check_hook_targets.py --smali work/apktool_out --json work/hook_targets_710.json
```

```
[check] 126/126 resolved
[check] 46 个目标没有直接 invoke（REFLECTIVE=5, SUPER-SLOT=1, TYPE-ONLY=25, USED(self)=15）
```

`dead: 0`（没有任何目标在 7.10.0 的 61,348 个 smali 里消失）。

签名级与返回值级：

```bash
python3 kit/scripts/check_hook_result_types.py --smali work/apktool_out
# [result-types] 14 个重载全部相容 ✓
```

`work/method_diff_790_710.json` 的判定分布（126 个目标方法）：

| 判定 | 数量 | 含义 |
|---|---|---|
| `SAME` | 54 | 方法体逐字节相同 |
| `BODY_CHANGED` | 24 | 只差资源 ID 常量（§2），**签名未变** |
| `DEBUG_ONLY` | 0 | — |
| `SIG_CHANGED` | **0** | **没有任何方法签名变化** |
| 平台类 / `None`（类级钩子） | 48 | 平台类不在 APK 内；`None` 是 `hookAll`/构造器约定，不适用逐方法比对 |

**`SIG_CHANGED = 0` 是这次适配的核心判据**：钩子装得上、装得对，且不需要改一行字面量。

## 4. 接口面 / 桥面 / 机制标记：一条没动

```bash
python3 kit/scripts/version_diff.py --a <7.9.0.apk> --b <7.10.0.apk> --out work/DIFF-790-710.md
```

```
[vdiff] 前缀: 共同 15 / 新独有 0  |  桥动作: 共同 231 / 新增 0 / 淘汰 0  |  core_* 52→52
```

机制标记（`KEY_ANTISPAM_SIGN_A` 2/2、`kakorrhaphiophobia` 3/3 …）计数完全一致
⇒ 签名 token、热修、dpsdk、桥注册表、入口密钥片段都没有增删。

## 5. native：33/34 逐字节相同，`libdpsdk.so` 变了

| 项 | 7.9.0 | 7.10.0 |
|---|---|---|
| `lib/arm64-v8a/*.so` | 34 | 34（同名同集合） |
| 逐字节相同 | — | **33** |
| 变化 | — | **`libdpsdk.so`**：1,755,984 → 2,514,520 B（+43%） |
| 导出符号 | 1,956（含 C++ runtime） | **4**（`Java_com_dprotect_DpSdk_init` / `getTicket` / `raw_syscall` / 一个 codecvt） |
| 字符串 | 9,226 | 11,768（`detect` 0→9、`root` 1→9、`magisk` 2→3、`xposed` 2→2、`frida` 2→1） |

判定（`observed`，已在 A1 轮细化，见 `work/dpsdk/DELTA-710.md`）：dpsdk 做了**符号隐藏**
（导出 1956→4），但体积 +43% 的主因是 **QUIC(ngtcp2) + TLS 依赖扩张**（新增 10,820 条串里
656 条 QUIC、593 条 TLS/证书），**检测相关新增串只有 2 条**（`magisk`、`/sbin/su`），
而 7.9.0 本来就有等价项（`%s/magisk`、`/system/sbin/su`、Xposed 包名表、`TracerPid`）。
⇒ **检测面没有实质增强**。

**真机实测（`observed`）**：模块注入后进程存活、`HookCore ready (38 features)`、
`hooks 101 ok / 0 failed`，无新增击杀路径 —— 见 §6。

## 6. 真机验证（emulator-5558，Android 16 arm64，Magisk + LSPosed）

安装与配置：

```bash
adb install -r -g com.kuaiduizuoye.scan-7.10.0-1850-168194.apk      # Success, versionCode=1850
adb install -r module/app/build/outputs/apk/debug/app-debug.apk      # Success
adb root                                                              # set_config 需要读 /data/misc
bash kit/scripts/set_config.sh --adb emulator-5558 --profile regular   # 回读校验 7 条一致, 20/21 开
```

启动后日志（`observed`）：

```
[KdKit] HookCore start: process=com.kuaiduizuoye.scan classLoader=PathClassLoader[...base.apk]
[KdKit] AdSlotProbe installed (5 hooks, observe-only)
[KdKit] HookCore ready (38 features)
[KdKit] HookCore audit: ready 37/38 features, hooks 101 ok / 0 failed
[KdKit] host com.kuaiduizuoye.scan 7.10.0 (1850) sdk=36
```

`37/38` 的那一个与 7.9.0 时相同（`native_exit_guard` 需要 native 侧装载时机，不参与 audit 计数）。

## 7. 改了什么（3 处，都是版本基线）

| 文件 | 改动 |
|---|---|
| `module/.../HostVersion.kt` | `BASELINE_VERSION_NAME/CODE` → `7.10.0` / `1850`；新增 `COMPATIBLE_VERSIONS = {"7.9.0/1840"}` 与 `isSupported()`；注释里的示例行同步 |
| `README.md` | 顶部版本声明 → 7.10.0 / 1850，并记录两条历史基线（`apktool_out_790` / `apktool_out_772`） |
| `kit/scripts/{after_login,preflight}.sh` | 版本提示文案与安装目标 APK 改到 7.10.0 |

**钩子字面量：0 处改动**（本文件 §3 的 `SIG_CHANGED = 0` 是依据）。

## 8. 兼容性：同一个模块同时服务 7.9.0 与 7.10.0

因为 §3（名字与签名逐条相同）+ §2（方法体只差资源 ID），7.9.0/1840 与 7.10.0/1850
共用同一份模块产物。`HostVersion.isSupported()` 对两版都返回 `true`，
日志里两版都会写 `baseline=true`；其它版本仍然只警告、不阻止（便于灰度）。

## 9. 仍未做 / 边界

- **要复核的静态项**：`libdpsdk.so` 的 `detect`/`root` 字符串增量没有逐条定位到调用点
  （`unverified`：只知道字符串变多，不知道是否新增了对 Xposed/LSPosed 的检测路径）。
  真机 30 分钟运行未见击杀，但**不构成"没有新增检测"的证明**。
- **新增类未评估**：`PersonalRecommendSettingActivity`（个性化推荐设置页）是 7.10.0 的新功能面，
  本文件只记录它的存在（`observed`），没有做行为分析，也没有为它加功能。
- **7.9.0 树只留归档**：`work/apktool_out_790.tar.gz`（90 MB）仅作为历史证据；
  `check_hook_targets.py` 等工具的默认 `--smali work/apktool_out` 现指向 7.10.0。
</content>
</content>
</invoke>

## 10. 环境约束：一条必须每次起设备都补的 SELinux 规则

第一次真机验收时出现了与适配无关、但会让**所有配置项静默失效**的故障，记在这里：

**症状**：模块注入正常（`HookCore ready (38 features)`、`hooks 101 ok / 0 failed`），
但 `effective-on=13` 而不是 18–20，所有 `defaultOn=false` 的功能都按默认关。

**判据行**（宿主日志）：

```
[KdKit] xprefs published=/data/misc/<uuid>/prefs/dev.xalor.kdkit/kdkit.xml all={}
```

`all={}` = **读不到文件**，不是"没有配置"。同一时刻的 avc：

```
avc: denied { search } for name="<uuid>" tcontext=u:object_r:unlabeled:s0
    tclass=dir trawcon="u:object_r:xposed_data:s0" app=com.kuaiduizuoye.scan
```

宿主进程 domain `u:r:untrusted_app_30` 对 `/data/misc/<uuid>` 的 `search` 被拒绝 ⇒
LSPosed 的 `XSharedPreferences` 返回空 map ⇒ `KdConfig.isOn()` 一律回落 `defaultOn`。

**为什么难查**：`set_config.sh` 的**推送**与**回读校验**全部通过（文件内容确实写对了），
坏的只有读的那一头。这与 R119「关不掉的功能」是同一族、方向相反的静默失效。

**修法**（`kit/scripts/fix_xposed_prefs_selinux.sh`，`env_up.sh` 已在 set_config 之前调用）：

```bash
magiskpolicy --live \
  "allow untrusted_app_30 xposed_data dir { search read open getattr }" \
  "allow untrusted_app_30 xposed_data file { read open getattr }"
```

- `xposed_data` 在本 ROM 的 sepolicy 里是 **attribute**，不是 type ⇒ **不要写 `type xposed_data`**
  （那会报 `target type xposed_data does not exist`，让人误判成无解）。
- 规则是 live 的，**重启设备即失效** ⇒ 每次起设备都要补（已接进 `env_up.sh`）。
- 修好后实测：`all={h5_bridge_log=true, …, sign_observer=true}`、`effective-on=18`、
  `acceptance.py --live` **13/13**。

**判定链（可复跑）**：`all={}` ⇒ 断；`all` 有键 ⇒ 通。别用 `getenforce`/`ls -Z` 判
（两者都可能看起来正常：enforcing 不代表规则缺失，`ls -Z` 在 root 命名空间下显示的是
另一层的 label）。
