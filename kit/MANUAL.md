# kuaidui-kit 使用手册（MANUAL）

面向"想接着干活的人"（或下一个 agent）：**从零到跑通**的最短路径、每个工具干什么、
哪些结论已经冻结可以直接用、哪些坑必须绕开。技术细节分别在
[`../work/TRIAGE.md`](../work/TRIAGE.md)（静态面）、[`../work/dpsdk/FINDINGS.md`](../work/dpsdk/FINDINGS.md)（反调试）、
[`../work/native_reversal.md`](../work/native_reversal.md)（native 算法）、[`../module/README.md`](../module/README.md)（模块）。

---

## 0. 30 秒速览

| 想做什么 | 一条命令 |
|---|---|
| 拉起本项目设备 | `./kit/scripts/env_up.sh kd1 5558` |
| 冷启动行为基线 | `python3 kit/scripts/coldstart_snapshot.py --adb emulator-5558 --seconds 30`（产出 `work/COLDSTART.md` + 原始切片） |
| 接口面健康度（多轮） | `python3 kit/scripts/api_health.py --adb emulator-5558 --runs 3 --out work/GUEST_API_HEALTH.md` |
| 下一步做什么（只读建议） | `python3 kit/scripts/next_round.py`（读四道门 + 未解清单 + 轮次历史排序；红门自动排 P0） |
| **跨版本对比（一条命令）** | `python3 kit/scripts/version_diff.py --a <旧 APK 或快照> --b <新 APK 或快照> --out work/versions/DIFF.md` |
| **AI 写作四步离线链路** | `python3 kit/python/composition_flow.py --adb emulator-5558 --title "SummerVacation"`（第五步在登录分支之后，脚本会明说） |
| **拿到账号后要跑的三步** | `python3 kit/scripts/after_login.py --adb emulator-5558`（自检：无账号时退出码 2 并打印清单；有账号时加 `--run` 真正执行并产出 `work/AFTER_LOGIN.md`） |
| 登录态快照 / 对照 | `python3 kit/scripts/session_snapshot.py --adb emulator-5558 --out work/session.json`（`--diff` 比对） |
| **一键恢复常规配置** | `./kit/scripts/set_config.sh --adb emulator-5558 --profile regular`（另有 `diag` / `min`；实测 13/17、14/17、10/17） |
| **工具自检（防止"看着在跑"）** | `python3 kit/scripts/selftest.py`（编译 + `--help`/import + 合成抓取跑一遍离线工具） |
| **跨轮漂移检查（一条命令）** | `python3 kit/scripts/reverify.py --adb emulator-5558 --out work/packs/<tag>/reverify.md`（重跑 R3/R7/R10/R12 四条结论） |
| **每轮证据包（一条命令）** | `python3 kit/scripts/evidence_pack.py --adb emulator-5558 --tag r57 --live --adb-b emulator-5556`（内含四道自动门：验收 / 跨轮漂移 / **接口面基线** / 工具自检；`--skip-baseline`、`--skip-reverify` 可关） |
| 路径基线回归（接口面漂移） | `python3 kit/scripts/path_diff.py --adb-a emulator-5558 --adb-b emulator-5558 --steps "AI写作" --repeat 2 --save-baseline work/baselines/path_aiwriting.json`（之后用 `--check-baseline` 复核） |
| 两台设备同路径差异 | `python3 kit/scripts/path_diff.py --adb-a emulator-5558 --adb-b emulator-5556 --steps "AI写作" --out work/path_diff.md` |
| 两台设备对照 | `python3 kit/scripts/compare_devices.py --adb-a emulator-5558 --adb-b emulator-5556 --out work/device_compare.md` |
| 模块功能运行报告 | `python3 kit/scripts/module_report.py --adb emulator-5558 --out work/module_report.md` |
| 把一次抓取变成报告 | `python3 kit/python/session_report.py cap.txt --out work/session_report.md` |
| 按文案点一串入口（驱动页面） | `python3 kit/scripts/tap_texts.py --adb emulator-5558 --steps "我的,搜作文" --wait 8` |
| **一键验收全部能力** | `python3 kit/scripts/acceptance.py --adb emulator-5558 --live --ensure-flags`（9 项检查，见 §9） |
| 静态解码（smali/java/so） | `./kit/scripts/recon.sh <apk>` |
| 检查模块钩子目标是否还在 | `python3 kit/scripts/check_hook_targets.py` |
| 抓签名 / 密钥 / 解密响应 | 模块功能 `sign_observer` → `adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt` |
| 把抓取变成可读时间线 | `python3 kit/python/capture_transcript.py cap.txt > t.md` |
| 验证离线 RC4 与实盘一致 | `python3 kit/python/verify_rc4_capture.py cap.txt` |
| 解出请求体（两套密钥） | `python3 kit/python/decrypt_capture.py cap.txt` |
| 读签名公式的两个运行时输入（内存侧） | `python3 kit/scripts/read_sign_inputs.py --adb emulator-5558 --pid $(adb -s emulator-5558 shell pidof com.kuaiduizuoye.scan)` |
| **仅凭 token 离线复现签名** | `python3 kit/scripts/decode_token_native.py --adb emulator-5558 --sign-a a.txt --sign-b b.txt --capture cap.txt` |
| **离线重建/调用 App 接口** | `python3 kit/python/kd_api.py verify … --capture cap.txt`（80 条实盘 URL 重建）；`… call --url "<捕获的URL>" --retime`（重新签名并真发出去） |
| 量化"附加后能活多久" | `python3 kit/scripts/attach_probe.py --adb emulator-5558 --seconds 25 --relaunch --settle 8 --out probe.json` |
| 在宿主里跑 native 算法 | `cd kit/harness && cat README.md` |

---

## 1. 环境（先做这个）

```bash
./kit/scripts/env_up.sh kd1 5558
```

它做的事：用**项目自己的 ramdisk**（`infra/ramdisk-magisk.img`）启动 AVD → root → `setenforce 0` →
推/起 frida-server（改名 `xdsvc`，端口 31337）→ 端口转发 → 打印 `magisk / vectord / frida / 包` 状态。

**两条硬约束**：

1. **必须带 `-ramdisk infra/ramdisk-magisk.img`**：不带的话 magiskd/vectord 起不来，KdKit 永远注不进去
   （脚本会显式告警）。
2. **别用共享的 `emulator-5556`**：本机别的项目也在用它，而且常以 `-writable-system` 无 ramdisk 的方式重启
   —— 那种实例看着正常，模块却永远不会生效。项目设备是 `kd1`（`:5558`）。

穿戴好的设备应该长这样：

```
sdk=36  magisk=30.7:MAGISK:R
vectord: running          # Vector(LSPosed) v2.2，模块框架
frida-server: running     # /data/local/tmp/xdsvc:31337
快对: installed           KdKit: installed
```

模块部署与开关：

```bash
adb -s emulator-5558 install -r module/app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5558 shell 'sh /data/adb/lspd/cli modules enable dev.xalor.kdkit'
adb -s emulator-5558 shell 'sh /data/adb/lspd/cli scope add dev.xalor.kdkit com.kuaiduizuoye.scan/0'
```

功能开关的第三种改法（前两种是设置界面、`KdConfig` 默认值）：直接写宿主读的那份发布配置（root）：

```bash
PUB=/data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml     # 路径见模块日志 "xprefs published="
adb -s emulator-5558 shell "cp /data/local/tmp/kdkit.xml $PUB; chmod 644 $PUB; restorecon $PUB"
```

---

## 2. 静态面

```bash
./kit/scripts/recon.sh com.kuaiduizuoye.scan-7.7.2-1811-168194.apk
# -> work/apktool_out (smali+资源) / work/jadx_out (java) / work/native (*.so)
```

* 找类/方法：优先 `grep` smali（`apktool_out/smali_classesN/…`），jadx 只是可读视图。
* 模块里每个钩子目标都能被静态校验：

```bash
python3 kit/scripts/check_hook_targets.py     # 24/24 resolved 才算通过
```

* 混淆与热补丁：宿主每个方法体都被 Robust `PatchProxy.proxy(...)` 包着；看 smali 时把
  `PatchProxy` 那几行跳过就是原逻辑。app 自有包名可读（`com.kuaiduizuoye.scan.*`、
  `lk.*`/`aj.*`/`yl.*`/`xl.*`），第三方层被改名成 `pXXXXX`。

---

## 3. 动态面（进程内观测，不需要 Frida）

宿主对 ptrace 极敏感（见 §5），所以**动态观测默认走 KdKit 模块**——它本来就在进程里。

| 功能 | 干什么 | 关键日志/产物 |
|---|---|---|
| `sign_observer` | 14 个钩子：签名参数与结果、`nativeGetKey` 的 RC4 密钥、`yl.f` 的响应/请求加解密、`RC4.encrypt/decrypt` 与 `workingKey` | 宿主 `files/kdkit_capture.txt`（完整、不截断） |
| `native_probe` | 记录 `NativeHelper.nativeGetSign(param, sign)`，并打印 `libbaseutil.so base` / `G` 地址 | 模块日志 + 抓取文件里的 `SIGNPARAM` |
| `anti_detect` | 中和宿主自带反调试看门狗（`lk.f`） | `AntiDetect: neutralised …` |
| `exit_guard` | 拦 `System.exit` 等并记调用栈 | `ExitGuard: exit blocked #n …` |
| `pk_assist` | PK H5 自动作答（`pk_mock=true` 可进页面自带 mock 对局做验收） | 页面控制台 `[KdKit] Q0..Qn` |
| `h5_debug` | 宿主 WebView 注入 eruda | `[KdKit] eruda ready` |

抓取→离线一条龙：

```bash
adb -s emulator-5558 shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > work/cap.txt
python3 kit/python/capture_transcript.py work/cap.txt > work/transcript.md   # RC4 行就地解密
python3 kit/python/decrypt_capture.py   work/cap.txt                          # 请求体（两套密钥都试）
python3 kit/python/verify_rc4_capture.py work/cap.txt                         # 离线 RC4 vs 实盘，逐字节
```

---

## 4. 已冻结的算法（可直接用，不必再逆）

| 项目 | 结论 | 出处/工具 |
|---|---|---|
| 负载 RC4 密钥 | `nativeGetKey(str(versionCode))`，128 个 hex 字符；**每安装**由 token/cuid/证书派生 | `work/native_reversal.md` §4；`sign_observer` 抓 |
| 负载编解码 | `base64(RC4(hexkey_bytes, data))`，Android `NO_WRAP` | `kit/python/kd_crypto.py` |
| 请求签名 | `sign = md5( A + "[" + md5hex(X) + "]@" + param )`，`param = base64_NO_WRAP(join(sorted(参数)))` | `work/native_reversal.md` §5；`read_sign_inputs.py`（内存）|
| **A / X 的离线来源** | `blobA = xform(expand(SIGN_A), "@fG2SuLA")` → `A = blobA[0:5]`；`key2 = blobA[7:12] + "#G4"` → `X = xform(expand(SIGN_B), key2)[0x0c:0x16]` | `work/native_reversal.md` §5.2；`kit/harness/native/decode_token.c` + `kit/scripts/decode_token_native.py` |
| 防重签/防伪绑定 | `blobA[0x13:0x33] == md5hex(证书派生串)`，`blobA[0x35:] == cuid` | 同上 |
| 响应体加密 | `data.encodeData` = base64( RC4(当前 `yl.f.b`, base64decode(密文) ) ) → 再 base64 解一层得 JSON；key 随 token 轮换，取同 epoch 的 capture 行 | `kit/python/kd_api.py call --rc4-key <KEY>`；证据 `work/dpsdk/kd_api_full_loop_r10.txt` |
| 请求组装 | `param = base64_NO_WRAP( join(sorted("<k>=<v>")) )`（**padding 保留**，去掉会算错）；URL = 原始顺序参数 + `&sign=…&_t_=<秒>&kakorrhaphiophobia=<ms>`；`kakorrhaphiophobia` 是防重放（服务端会校验时间窗） | `kit/python/kd_api.py`；实测 `?&…&sign=…` 调用返回 `errNo:0` |
| `X` 的位置 | `libbaseutil base + 0xa238` 处指针指向的 10 字符串（每安装不同） | 同上 |
| 设备身份加密 | `RC4Encrypt.encryptString(json, new RC4(PackageHelper.ENTRY_KEY))`，`ENTRY_KEY = "msyx6nw$jwk12.76alvkf"`（dex 内硬编码，还用来解 `IU.ud` 与加密包名表） | `work/TRIAGE.md` §3.3；`kit/python/device_entry_crypto.py` |
| H5 桥（选择性） | `encryptDataRequest` / `getRc4DecryptData` 等 215 个 `@FeAction` 清单 | `work/feactions.txt` |

---

## 4.1 离线客户端（能做到什么程度）

`kit/python/kd_api.py` 现在可以：

* **verify**：按类判定 —— 日志里带 `sign` 的 URL 必须**逐字节**重建一致
  （`rebuild: verified=173 excluded=4 unexpected=0 missing_sign=238 of 415`）；日志被截断、`sign`
  没写进去的 URL 报 `missing_sign`（不可重算），签名输入不是 URL query 的端点按名字列入
  `excluded`（附理由与"签名输入已抓到 N/N"的证据）。`unexpected > 0` 才判红 —— 只代表算法或
  接线出现真回归；
* **call**：把捕获 URL 的 `_t_` 换成当前时间、用 token 派生的 A/X **重新签名**后真的发出去 ——
  实测 `HTTP 200 {"errNo":0,"errstr":"success",…}`（证据 `work/dpsdk/kd_api_r9.txt`）；
* **pull**：按**路径**批量离线拉取（重签名 + 真发 + 解响应），
  `--post` 走表单 POST（很多业务接口是 POST，用 GET 打会 404）：

```
# 对"App 从未调用过"的接口发签名请求：参数集合自动从 capture 推（同一 host 下出现率 ≥80% 的参数名）
$ python3 kit/python/kd_api.py request --adb emulator-5558 --sign-a a.txt --sign-b b.txt \
      --common-from cap.txt --insecure --post --path /pluto/publish/checkappupdate
[api] host=pluto.zuoyebang.com common params=28 (>= 4/6 requests) + 0 supplied -> 28 total
[api] HTTP 200  {"errNo":0,"errstr":"success","data":{"md5":"","vcname":"","taskId":0,"apkUrl":"",
                "forceUp":0,"updateType":1,…}}          ← 服务端此刻并没有在推更新

# 单路径/多路径；--auto-method 会先 GET、404 再改 POST；--all-paths 直接把捕获里所有路径扫一遍
$ python3 kit/python/kd_api.py pull --adb emulator-5558 --sign-a a.txt --sign-b b.txt \
      --capture cap.txt --insecure --auto-method --all-paths
path                                         http  m     errstr    payload
/pluto/app/hotfix                            200   GET             {"md5":"","url":"","version":"","jarTime":0}
/kdapi/conf/abtest                           200   POST            {"ab":[]}
/kdcore/map/locationtree                     200   POST            {"userLoc":{"province":…}}
…   （本机实测 33/33 全部 200，见 work/API_SURFACE.md）
```

**响应体也能解**（R10）：`data.encodeData` 就是 `RC4(当前 yl.f.b)`，再 base64 解一层就是 JSON：

```
[api] HTTP 200 … {"errNo":0,…,"encodeData":"gMMz50ja…"}
[api] encodeData decrypted: {"md5":"","url":"","version":"","jarTime":0}
```

（`yl/f.java:1307`：`new String(rc4Take.decrypt(f(encodeData)))`，`rc4Take` 来自 4 个实例的池，key 是字段 `b`；
**这把 key 会随 token 轮换** —— 本机实测 `b2674b28…`(17:19) → `f42afd3c…`(17:25 起)，
所以要解哪一段响应就用**同一 epoch** 的 `RC4KEY b(1811)` 行，`--rc4-key` 直接喂进去即可。）

## 5. 反调试现状（重要）

| 层 | 机制 | 现状 |
|---|---|---|
| Java 看门狗 `lk.f` | `AntiDebugThread` 每 800 ms 查 `Debug.isDebuggerConnected()` 与 `TracerPid` → `System.exit(0)` | **已被 `anti_detect` 中和** |
| native `libdpsdk.so`（DProtect） | 读 `/proc/<self>/status` → 探 tracer → `exit_group(0)`（干净退出，无 ART 日志） | **未中和**：Frida 一触到进程即被杀；`spawn` 下 agent 自身崩 |

因此：**Frida 侧动态分析目前不可用**（`kit/hooks/01/02/03` 保留给"没有模块的场景"）。
要量化任何尝试，先用：

```bash
python3 kit/scripts/attach_probe.py --adb emulator-5558 --seconds 25 --relaunch --settle 8 --out probe.json
```

`--spawn` 模式也有（`device.spawn` → 载入 agent → `resume`），但当前会在 agent 内部 SIGSEGV。

---

## 6. 内存侧（root 读进程）

```bash
# 任意地址读 + 跟随指针（十六进制 + ASCII）
python3 kit/scripts/mem_read.py --adb emulator-5558 --pid <pid> --addr 0x72cc26c238 --len 96 --follow 1

# 直接读签名公式的两个输入并自检（会打印 A/X 与 md5(X)）
python3 kit/scripts/read_sign_inputs.py --adb emulator-5558 --pid <pid> --capture work/cap.txt

# 忘了地址时：从 G 结构体出发暴力找出能复现签名的字符串对
python3 kit/scripts/find_sign_strings.py --adb emulator-5558 --pid <pid> --base 0x… --capture work/cap.txt
```

`G = libbaseutil.so 基址 + 0xa238`；基址从 `/proc/<pid>/maps` 取。

---

## 7. 设备侧改 so（不重签名）

```bash
python3 kit/scripts/patch_device_lib.py --adb emulator-5558 \
    --lib /data/app/~~…/lib/arm64/libdpsdk.so \
    --patch 0x170978:TracerP!d --backup /data/local/tmp/libdpsdk.orig.so
```

等长字节补丁，带前后 sha256 与回滚备份。注意：重签 APK 会让 `libbaseutil` 读到的证书变化 →
签名/密钥全变，所以**优先改设备上已解包的 .so**，不要重打包。

---

## 8. 常见坑（都踩过）

| 症状 | 原因/处理 |
|---|---|
| 模块完全不注入、日志一片安静 | 设备是无 ramdisk 启动的（`magisk -v` 为空）→ 用 `env_up.sh` 重来 |
| `am start` 报 activity 不存在 | 用解析出来的入口：`cmd package resolve-activity --brief -c android.intent.category.LAUNCHER com.kuaiduizuoye.scan`（本机是 `.AliasActivityDefault`） |
| frida 报 `process not found` | 附加前让进程 settle 几秒；客户端用 `add_remote_device("127.0.0.1:31337")` |
| 截图不变化 / 一直同一张 | 模拟器把 `System UI ANR` 弹窗钉在最上层 → `adb shell killall com.android.systemui`，再确认 `dumpsys window \| grep mCurrentFocus` |
| 宿主界面点不动 | 先用 `uiautomator dump` 取真实 bounds，别按截图坐标猜 |
| 宿主里所有功能都变回默认值（日志 `xprefs published=… all={}`） | **发布配置的权限**：设置应用的 SharedPreferences 重写会把文件改成 `0660`，宿主不同 uid 读不到 → 解析出空 map。模块已内置 `chmod 644` + 看门狗（`repaired mode … -> 644`），设置页顶部**「配置通道」卡**会显示权限并给一键修复；手工排查：`stat -c %a /data/misc/*/prefs/dev.xalor.kdkit/kdkit.xml` |
| 抓取文件越来越大 | `sign_observer`/`native_probe` 自带 4 MB 上限与条数上限；要清就 `adb shell rm …/kdkit_capture.txt` |

---

## 9. 一键验收（`kit/scripts/acceptance.py`）

```
PASS  environment      sdk=36 magisk=yes vectord=1 frida=yes app=yes module=yes
PASS  module alive     HookCore ready (15 features)
PASS  config channel   mode=644 flags=N
PASS  capture          398808 B, 80 param list(s), 80 signed URL(s)
PASS  offline RC4      match=18 mismatch=0
PASS  offline sign     match=60 mismatch=0 | X='VzYfc94fbW'
PASS  api rebuild      verified 173/177 signed URL(s), 4 excluded (non-URL signing input), 238/415 URL(s) truncated -> not rebuildable
PASS  live call        HTTP 200 errNo=0          ← 需要 --live
PASS  hook targets     29/29 resolved
11/11 checks passed
```

会话报告（`session_report.py`）现在有 6 节：概览 / 接口面 / H5 桥调用 / **广告位读取（`ad_probe` 观测）** /
宿主解密明文 / 桥守卫拦截 —— 其中"广告位读取"那节会把 `ADSLOT call …`、`ADSLOT ret … -> null|类型`
聚合成"位号 → 次数 / 返回 → 次数"。

它逐条跑的就是各轮日志里用过的同一条命令；**任何一项变红，就说明那一环被改坏了**。
`--ensure-flags`：先把诊断功能（`sign_observer`/`native_probe`）写进发布配置并重启宿主，
避免"因为没开抓取而假红"。证据：`work/dpsdk/acceptance_live_r14.json` / `acceptance_r14.txt`。

## 10. 下一步（写在这里，免得忘）

1. ~~响应体密钥~~ → **已闭环**（R10）：`RC4(yl.f.b)`，key 随 token 轮换。
2. ~~`X` 的派生算法~~ → **已闭环**（`native_reversal.md` §5.2）：原生 oracle 解 token，离线 60/60 复算签名。
2. `libdpsdk.so` 原生退出路径（`dp_*` 段行为、`exit_group` 调用点）。
3. `work/feactions.txt` 里挑高价值 H5 桥接口做功能（打印 PDF / 下载 / 用户信息）。
4. 模块工程化：设置界面分组、抓取开关与导出、功能开关持久化校验。
