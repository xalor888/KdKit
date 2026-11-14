# KdKit — 快对增强模块

A WeKit-style module for **`com.kuaiduizuoye.scan`（快对）**: ad removal plus a 口算/语文/单词 PK
assistant, with a Material 3 settings UI.

**范式**：模块骨架（入口 / HookCore / FeatureRegistry / 配置通道 / 日志 / 抓取）与
[`PARADIGM.md`](PARADIGM.md) 一致；`baicizhan-kit` 的 BCZKit 按同一份契约移植。

```
module/
  app/src/main/java/dev/xalor/kdkit/
    KdEntry.kt                     Xposed entry (IXposedHookLoadPackage)
    HookCore.kt                    per-process bootstrap + feature dispatch
    config/KdConfig.kt             flags shared with the UI (no Xposed references)
    config/KdConfigBridge.kt       framework-side prefs plumbing (framework ClassLoader only)
    features/BaseFeature.kt        feature contract + categories
    features/FeatureRegistry.kt    the feature list
    features/ads/AdFeatures.kt     去广告
    features/host/AntiDetect.kt    反调试检测绕过（宿主自带 AntiDebugThread）
    features/host/ExitGuard.kt     退出守卫（拦 System.exit / killProcess 并记调用栈）
    features/host/HostFeatures.kt  广告 SDK 阻断 / H5 调试台
    features/misc/SignObserver.kt  签名 / 密钥观测（进程内版 kit 钩子）
    features/misc/NativeProbe.kt   签名公式探针（读 libbaseutil 运行时字符串并当场验证）
    features/pk/PkAssist.kt        WebView JS injection
    features/pk/PkScript.kt        the PK userscript
    ui/MainActivity.kt             Compose settings UI
    ui/theme/Theme.kt              Material 3 theme
```

## Build

```bash
./scripts/verify.sh                 # 一键十道门（单测 / 解析器 / 编译 / 功能表 / 钩子目标 / 签名 / 调用方 / 假测试 / 共享登记 / 热修复面）
./scripts/verify.sh --no-apk        # 改 UI 或纯逻辑时跳过钩子门（更快）
./scripts/verify.sh --deep          # 额外跑 ⑥b 死代码枚举（~65s，发布前跑一次）
JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gw assembleDebug      # -> app/build/outputs/apk/debug/
```

> 本机默认的 Homebrew JDK 是 27，**Gradle 8.14.5 只支持 17–21**，直接跑会得到一行几乎无法定位的错误
> （`27.0.1.0.3`）。`verify.sh` 会自动挑一个受支持的 JDK；手工跑 `./gw` 时记得自己设 `JAVA_HOME`。

门禁失败时**一定会打印原因**（含 `--quiet`）。这条不是礼貌问题：2026-10-25 一次偶发红
因为 `--quiet` 把日志整段吞掉，只能靠重跑碰运气才定位到。quiet 只该压掉成功时的啰嗦。

### 抓取样本与凭证

`work/activity_inputs/` 的 5 份抓取是原始 logcat，**曾原样包含登录 token**（同一条出现
1418 次）。已由 `kit/python/redact_capture.py` 脱敏，且：

* 只替换值，键名/分隔符/非敏感值逐字节保留 ⇒ 逐前缀统计完全一致；
* 空值保持为空（否则 `SIGN params` 的键集合会凭空多字段）；
* 幂等，`--check` 有残留退出 1；
* 门禁 ①b 每次检查该目录 —— 新增未脱敏抓取立刻红。

采样日期以 `work/activity_inputs/README.md` 的登记表为准，**不看 mtime**（就地改写会让
"样本早于功能"被误读成"功能失效"）。

`./gw` runs the cached Gradle 8.14.5 distribution; `libs/XposedBridgeApi-82.jar` is the
compile-only Xposed API (API 82). Repositories fall back to the aliyun mirror because
`maven.google.com` is not reachable from this network (see `settings.gradle.kts`).

## Install

1. `adb install -r app/build/outputs/apk/debug/app-debug.apk`
2. Enable the module and add the target scope (Vector/LSPosed CLI):
   ```bash
   adb shell 'sh /data/adb/lspd/cli modules enable dev.xalor.kdkit'
   adb shell 'sh /data/adb/lspd/cli scope add dev.xalor.kdkit com.kuaiduizuoye.scan/0'
   ```
3. Launch 快对 once, then open `dev.xalor.kdkit` to configure.

## Architecture notes

* **Loading.** The module is a standard Xposed/Vector module; `xposed_init` names `KdEntry`.
  `handleLoadPackage` runs from `Instrumentation.newApplication`, so hooks land before the app
  touches ads or creates a WebView. (`Application.attachBaseContext` has already run by then —
  do not rely on hooking it.)
* **Config channel.** The settings app cannot read the host's data dir and the host cannot read
  the app's (per-app mount namespaces), so flags are published through the framework:
  the module declares `xposedsharedprefs`; `KdConfigBridge` runs on the framework ClassLoader in
  *both* processes — it installs an `XSharedPreferences` reader in the host and mirrors the app's
  preferences into the framework-published file (chmod 644) in the settings app.
  `KdConfig` itself must never reference `de.robv.android.xposed.*`, or the UI process crashes.
* **热开关.** `BaseFeature.hot = true` 的功能**始终安装**钩子，回调在调用点用
  `KdConfig.isOn(...)` 判定（带 2 秒 TTL 缓存）⇒ 改开关 1–2 秒生效，不必重启宿主。
  冷开关（`hot = false`）保持"关闭就不装"的旧语义，只用于安装本身不可逆的功能。
* **抓取.** 所有观测行只走 `util/Capture`（单写者线程 + 有界队列 + 轮转改名 + 限流），
  行格式 `HH:mm:ss.SSS <line>` 是 `kit/python/` 六个解析器的契约。
* **广告.** Blocking happens at the app's own ad-slot accessor (`aj.a.d/f/h`, `aj.a.j/k`) plus the
  splash controller (`lk.a.j/k`), the tab/banner/popup views, so no mediation SDK ever gets a
  chance to render.
* **口算PK.** The PK screens are H5 (`ptactivity.zuoyebang.com/static/hy/kd-pk/`). The round state
  keeps the correct answer for every question (`questions[ownerIndex].answer`; 口算 answers are
  `<`, `>` or `=`), so the userscript reads it and activates the matching option element.
  Injection hooks the *concrete* `WebViewClient` subclass captured from `setWebViewClient`,
  because the host's client overrides `onPageFinished` without calling super.

## Feature set

共 **41 个功能**（`FeatureRegistry.all` 是唯一事实源；下表由 `scripts/check_feature_parity.py` 与代码校验）。
`热` 列 = 钩子常驻、开关在调用点判定 ⇒ **改完即时生效，不必重启快对**；空白表示冷开关（需重启宿主）。
`选项` 列 = 该功能在设置页展开后可见的子选项（由代码里的 `KdOption` 声明，门禁校验）。
`默认` 列就是 `BaseFeature.defaultOn`，设置页首次打开时的状态。

| id | 名称 | 类别 | 默认 | 实现要点 | 热 | 选项 |
|---|---|---|---|---|---|---|
| `rm_splash` | 开屏广告 | 广告 | 开 | 启动/切回前台时不再展示开屏广告 | 是 | — |
| `rm_adconfig` | 广告配置拦截 | 广告 | 开 | 拦截广告位配置读取，从源头禁用全部内置广告位 | 是 | — |
| `rm_tab_ad` | Tab 广告 | 广告 | 开 | 移除首页 / 我的 等页签内嵌广告卡片 | 是 | — |
| `rm_main_banner` | 主页横幅广告 | 广告 | 开 | 移除主页顶部的横幅广告图片 | 是 | — |
| `rm_feed_ad` | 信息流广告 | 广告 | 开 | 清空 Adx 下发的自渲染广告（答案页、详情页等） | 是 | — |
| `rm_popup` | 弹窗广告 | 广告 | 开 | 拦截广告弹窗的展示 | 是 | — |
| `ad_probe` | 广告位读取观测 | 广告 | 关 | 只记录不拦截：把 App 对 `aj.a` 各广告位的调用与返回写进抓取文件 | 是 | — |
| `block_ad_sdk` | 广告 SDK 阻断 | 广告 | 关 | 不初始化第三方广告 SDK，从进程内彻底断开广告请求 | 是 | — |
| `pk_assist` | PK 自动作答 | 口算PK | 开 | 在口算 / 诗词 / 成语 / 单词 PK 中自动提交正确答案 | 是 | `pk_mock` `pk_auto_answer` `pk_answer_delay_ms` |
| `log_sink` | App 日志收录 | 其他 | 开 | 把 App 自己打的关键日志行收进**共享抓取文件** `kdkit_capture.txt`（前缀 `APPSIGN <级别>/<tag>:`） | 是 | `capture_max_mb` `capture_max_line_kb` `log_level` `log_sink_per_tag` |
| `sign_observer` | 签名 / 密钥观测 | 其他 | 关 | 记录签名参数、`nativeGetKey` 的 RC4 密钥、H5 负载加解密（进程内版 kit 钩子） | 是 | `sign_observer_pairs` `sign_observer_logcat` |
| `native_probe` | 签名公式探针 | 其他 | 关 | 读取 `libbaseutil.so` 运行时字符串并当场验证签名公式 | 是 | `native_probe_capture` |
| `robust_probe` | Robust 热修复补丁面观测 | 宿主 | 关 | 观测 `PatchProxy.proxy` 调用：哪些方法被插桩（静态 7594 类 / 35784 方法）、运行时补丁是否生效；只观测不改行为 | 是 | `robust_probe_all`、`robust_probe_stack` |
| `route_log` | 路由观测 | 宿主 | 开 | 记录 `zyb://` 路由的实际跳转（path + 调用方） | 是 | `route_log_dedupe` |
| `web_picture_watermark` | 大图浏览页水印（本地绘制） | 宿主 | 关 | **另一条**水印链路：`CommonWebPictureBrowseActivity.c2` 用 Canvas 把水印位图叠进位图（位置 `Math.random`），本功能让它返回原图，并关掉同页水印 View（`j2`）；只影响本页渲染，不碰 `cu.l`/服务端/网络/DB/导出链路；热开关；**真机未验证** | 是 | — |
| `popwin_gate` | 服务端弹窗总闸门 | 宿主 | 关 | 钩 `ei.y.H(String,ListItem)`——服务端下发弹窗的**唯一**分派点（10 个类型 / 9 个分支）；按类型拦广告与销售类，默认不拦；热开关 | 是 | `popwin_block` `popwin_observe_only` |
| `http_body_probe` | HTTP 请求/响应体观测 | 宿主 | 关 | 记录宿主请求体（`getBody` 编码后 + `getParams` 表单参数 + `__jsonBody` 加密前）与响应原始字节，补上「URL 之外还剩 body」这一格；二进制只记长度；只观测不改行为 | 是 | `http_body_probe_response` `http_body_probe_full` `http_body_probe_param_values` `http_body_probe_binary` |
| `net_error_probe` | 网络失败原因观测 | 宿主 | 关 | 钩 `NetError` 构造器，记录每次失败的 `ErrorCode`（110 种：签名错/鉴权失败/超时…）与错误号；只观测不改行为 | 是 | `net_error_probe_stack` |
| `nav_log` | 页面导航观测 | 宿主 | 开 | 记录每一次 H5 页面加载（`WebView.loadUrl`） | 是 | — |
| `skip_onboarding` | 跳过首次启动引导 | 宿主 | 关 | 自动点掉隐私同意 / 青少年守护 / 身份选择（自动化验收用） | 是 | — |
| `exit_guard` | 退出守卫 | 宿主 | 开 | 拦 `System.exit` / `Process.killProcess`，进程不再自杀，便于动态分析 | 是 | `exit_guard_block` |
| `h5_bridge_log` | H5 桥调用记录 | 宿主 | 关 | 记录网页调用的原生 action（名字/参数/次数） | 是 | — |
| `native_exit_guard` | 原生退出守卫（实验） | 宿主 | 关 | 用 seccomp 否决 `exit_group`/`exit`，测试原生自杀路径（不可撤销） |  | `native_exit_guard_control` |
| `bridge_guard` | 桥守卫（页面侧敏感 action） | 宿主 | 关 | 拦 `core_showDebuger` / 登出类 `core_login`，含 HTTP 域名白名单 | 是 | `bridge_guard_list` `bridge_guard_http_allow` `bridge_guard_probe_remove_loading` |
| `h5_debug` | H5 调试台 | 宿主 | 关 | 在网页里注入 eruda 控制台 | 是 | — |
| `req_headers` | 宿主请求头观测 | 宿主 | 关 | 记录请求构造时的头（名与值，值截断） | 是 | — |
| `page_js` | 页面脚本注入（`page_js_script`） | 宿主 | 关 | 执行配置通道里的 `page_js_script` 字符串（给 `kit` 的 `call_page_js.py` 用） | 是 | `page_js_script` |
| `web_request_log` | 页面自有请求记录 | 宿主 | 关 | 记录 WebView 自己发出的请求（不经过宿主 OkHttp 的那批） | 是 | `web_request_log_bodies` |
| `anti_detect` | 反调试检测绕过 | 宿主 | 开 | **反调试**：`AntiDebugThread` 的 4 个判定点（`isDebuggerConnected` / `TracerPid` / `FLAG_DEBUGGABLE` / bridge）全部返回"干净"，Frida 可附加。**环境探测面**（2026-11-14 新增，宿主里的快手 Weapon / KSAd / 百度 MobAds 都在查）：① 包名——`getInstalledPackages`/`getInstalledApplications` 里删掉 `dev.xalor.kdkit` 与常见框架包，`getPackageInfo`/`getApplicationInfo` 对它们抛 `NameNotFoundException`；② 文件——`File.exists/isFile/isDirectory` 对含 `kdkit`/`xposed`/`de.robv`/`magisk`/`/data/adb` 的路径返回 false，`list`/`listFiles` 过滤同一批条目；③ `su` 探测——`Runtime.exec`/`ProcessBuilder.start` 命中 root 探测命令时返回退出码 1 的空进程（只认 su/magisk/`which su` 白名单）；④ Xposed 类——`ClassLoader.loadClass` 解析 `de.robv.android.xposed.*` 抛 `ClassNotFoundException`（模块自身 loader 豁免）；`Class.forName` 同规则但**延后 15 秒装**（加固宿主在 `InitializationProvider` 期间会反射重入 `forName`，启动路径上直接钩必崩，见 `work/anti_detect_audit.md`）；⑤ `/proc/self/maps`——`BufferedReader.readLine` 丢掉含 `Xposed`/`frida`/`magisk` 的行（只过滤读，不动进程）。每条都有 `gate=id` 热开关与白名单，异常只降级为限流日志 | 是 | `anti_detect_vectors` |
| `rc4_probe` | 解密观测 | 宿主 | 开 | 记录 Baidu RC4 的密钥与解密结果（解 `homeRecentList` 等加密字段） | 是 | `rc4_probe_uplink` |
| `bridge_action_log` | 高价值桥 action 观测 | 宿主 | 关 | 结构化记录 `downloadMedia`（页面往相册写哪张图）、`getuserinfo`（谁在打听身份）、`fetchPayInfos`（页面在驱动下单：payload 长度 + 键名，不落值）、`decodeHttpRequest`（页面借宿主签名手代发请求：URL 已剥 query、params 只记键名） | 是 | `bridge_action_log_url` |
| `parent_ctrl_write` | 家长模式写侧形状观测 | 宿主 | 关 | 钩 `dj.e.l(ParentCtrlData,int,Callback)`，记录提交快照（四个闸门 + from + userMode）；只观测不改行为 | 是 | — |
| `parent_ctrl_probe` | 家长模式闸门形状观测 | 宿主 | 关 | 钩 `dj.e.f()` 拿 `ParentCtrlData`，记录四个子项开关的服务端下发形状；只观测不改行为 | 是 | — |
| `page_request_log` | 页面代发请求来源观测 | 宿主 | 关 | 钩宿主**唯一**的“页面代发请求”出口 `dr.f.a(…)`，记录是哪个 action 让宿主把请求打到哪（URL 剥 query、params 只记键名、method 只记 0/1）；覆盖 `encryptDataRequest` / `core_httpRequest` 等 3 个 action，**新加 action 不必改代码**；只观测不改行为。**真机未验证** | 是 | `page_request_log_url` |
| `skip_update` | 跳过强制更新 | 宿主 | 关 | 服务端下发"必须升级"时不再弹强制更新窗（钩 `ei.y.L()`，可逆）；可选连 `forceUp` 判定一起改（会写偏好） | 是 | `update_force_neutralise` |
| `vip_limit_probe` | 重练额度检查观测 | 宿主 | 关 | 记录 App 对 `examRHW` 等产品的额度判定（允许吗、已用几次）；只观测不拦截 | 是 | `vip_limit_probe_result` |
| `rm_vip_promo` | 会员推广清理 | 宿主 | 开 | 关掉底部会员支付弹窗（`MainBottomPayDialog` 两个 public 入口 + `DialogFragment.show` 兜底）、服务端 `winVIPBottom` 分支（`hh.y.F`）与页面内的开通入口（JS 内容级过滤）；**不改会员判定** | 是 | `rm_vip_promo_h5` |
| `vip_unlock` | 会员状态解锁（客户端） | 宿主 | 关 | 让客户端判定为会员（`bk.a.p/n`）；**服务端鉴权不受影响**，见 `NEW_TARGETS.md` §5.6 | 是 | `vip_unlock_tbx` `vip_unlock_silent` |
| `md3_skin` | Material 3 简约皮肤 | 宿主 | 开 | H5 注入中性配色/16 圆角/去重阴影/统一字体（`WebInjector` provider 不占钩子）；原生只改窗口级颜色（`Activity.onCreate` 后设状态栏、导航栏、窗口底色） | 是 | `md3_native_window` `md3_native_bg` `md3_h5` `md3_theme` `md3_glass` `md3_level` `md3_primary` |
| `watermark_off` | 去水印（客户端开关） | 宿主 | 关 | 代用户打开 App 自带的「去除水印」（钩 `cu/l` 构造器置字段 `r`，`ext` 里带 `"2"`）；服务端计次/鉴权不变 | 是 | `watermark_off_writing` `watermark_off_entity` |
| `settings_entry` | 设置页 KdKit 入口 | 宿主 | 开 | 在快对「设置」页注入一行「KdKit 模块设置」（`zyb://app-vue/page/newSetUp` 是 Vue H5 页，`WebInjector` provider 注入 DOM）；点击走 `kdkit://open-settings`，由 `com.zuoyebang.common.web.WebViewClient.shouldOverrideUrlLoading` 消费并启动模块设置页 | 否 | — |


### 门禁标签对照表

④ 与 ⑥ 共用一套词汇（单一定义处：`kit/scripts/hook_vocab.py`，有 14 个测试钉住）。
两层概念不要混：

**判定** = 能不能钩（类/方法在不在、参数对不对）

| 标签 | 含义 |
|---|---|
| `OK` | 类与方法都存在，参数类型吻合 |
| `OK(load)` | 只校验了类（`clazzOrNull` 用法），方法不在本次判定范围 |
| `OK(platform)` | 平台类（`android.*`/`java.*`），在 framework 里，不参与离线判定 |
| `MISSING` | 类或方法不存在 —— **必红** |
| `SIG-MISMATCH` | 参数类型不符 —— **必红** |

**使用证据** = 有没有人调用它（钩上去会不会执行），按强度从强到弱

| 标签 | 含义 |
|---|---|
| `USED` | 别的文件里有 `invoke` 指向它 |
| `USED(self)` | 只有本类**别的方法**在调它（入口在别处，仍算活）|
| `REFLECTIVE` | 注解/框架按名字反射调用（`@FeAction`、JS bridge）⇒ 静态 0 调用方是设计如此 |
| `SUPER-SLOT` | 父类型槽位有 `invoke-virtual`，可能经虚表进入 |
| `TYPE-ONLY` | 只作为类型出现（字段/形参/`new`/`const-class`/`res` 布局）—— DTO 形态，**不是**死代码 |
| `DEAD` | 本类之外零引用 ⇒ 钩方法体必空转 —— **必红** |
| `-` | 没有证据可谈（判定已 `MISSING`）|

**反向枚举（⑥b，`--deep`）**：上面两层都只检查"模块**钩了**的目标"。`BrushMaskView` 那次
失效的根因不是判定错，是**没人想到要把它列为目标**。⑥b 正向扫一遍，找出"零引用 + UI 子类"
的类（UI 子类的正常入口是布局 inflate / `startActivity`，不是 `invoke`）⇒ 无路径可实例化
⇒ **可证明的死代码，别去钩**。只报告、不判红（这些类本来就没钩）。

2026-10-25 实测在 `com.byazt`（加固壳）下找出 **9 个**，其中 `com.byazt.nd.BrushMaskView`
与它的兄弟 `com.byazt.nd.ShadowImageView` 都在内 —— 即那次靠人眼侦察出来的结论，
现在是 `test_smali_usage.py::DeadUiDiscovery` 里的可复跑断言（合成夹具 1s；
真实 APK 那条 77s，用 `KDKIT_SLOW_TESTS=1` 才跑）。

**只对 `MISSING` / `SIG-MISMATCH` / `DEAD` 报红。**

一条钩子的完整结论 = 判定 + 证据，两者独立的典型例子：
`OK` + `TYPE-ONLY` —— 类和方法都在、只看类型位置出现。这时钩**方法体**很可能永远不执行，
但钩**构造器/字段读**是有效的（`watermark_off` 就是这样选钩点的）。

为什么不报"方法级不可达"：那需要全程序可达性分析（接收者、动态代理、反射、加固壳自修改），
静态证据不足。把"看不见"当"不存在"是这个仓库反复踩过的坑 ——
`NEW_TARGETS.md` 里那三条误报线索就是这么来的。

## 2026-10-25 优化要点

一轮底座重构 + 热开关 + 三个新功能，详见 [`OPTIMIZATION.md`](OPTIMIZATION.md)。最该知道的三件事：

1. **改开关不用再重启快对**：39/41 个功能是热开关（钩子常驻、调用点判定，1–2 秒生效）。
   唯一例外是 `native_exit_guard`（seccomp 过滤器不可撤销）。
2. **悬空配置清零**：此前有 7 个键"代码在读、界面写不了"，现在每个键都是功能自己声明的
   `KdOption`，设置页通用渲染；门禁强制"无幽灵键、无死选项、README 与代码一致"。
3. **启动第一行就能判断模块是否真的装上了**：

   ```
   [KdKit] host com.kuaiduizuoye.scan 7.10.2 (1860) sdk=36
   [KdKit] HookCore ready (38 features) · HookCore audit: hooks N ok / 0 failed
   ```

   失败会点名（`-> RemoveSplashAd:lk.a.j`），不再只有一行淹没在日志里的 warn。

## Pre-deploy gate

Every hook target of every feature is checked against the decoded APK before deploying —
a renamed/removed host class otherwise fails *silently* (`Xp.hook` returns false and logs
"hook failed …", the feature just stops working):

```bash
./scripts/verify.sh                                   # 十道门一次跑完（推荐，约 2 分钟）
python3 ../kit/scripts/check_hook_targets.py           # ④ 类 + 方法名全部解析
python3 ../kit/scripts/check_hook_signatures.py        # ⑤ 再比形参类型（④ 报 OK 也可能运行时失效）
python3 ../kit/scripts/smali_usage.py --smali ../work/apktool_out --from-module app/src/main/java/dev/xalor/kdkit --summary
                                                       # ⑥ 有没有人**调用**它（DEAD = 钩了必空转）
python3 scripts/check_feature_parity.py                # ③ 功能表 + 子选项 schema + README 列
```

### 为什么"存在且签名对"还不够

`check_hook_targets.py` 和 `check_hook_signatures.py` 都只证明"**钩得住**"。
真实反例：`com.byazt.nd.BrushMaskView.onDraw` 类在、签名对、`Xp.hook` 返回 true，
但**全 APK 零引用** —— 钩上去永远不会有第二行日志。

`smali_usage.py` 就是补这一层的：它按四层证据（直接调用 / 类内调用 / 父类槽位 /
仅类型引用）给结论，只对**类级零引用**报 `DEAD`。方法级的"不可达"需要全程序可达性分析，
静态证据不足，所以不报 —— 把"看不见"当"不存在"是本仓库反复踩过的坑。

## Verification status

| item | evidence |
|---|---|
| injection into 快对 | `[KdKit] injected: com.kuaiduizuoye.scan (first=true)` |
| all features install | `HookCore ready (25 features)` + per-feature `hooked …` / `installed (n hooks)` lines；旧轮次日志里的 9/12 是当时的功能数 |
| 开屏广告 removed | `ResumeSplashActivity` never starts (`grep -c` = 0) |
| config round-trip | toggle in UI → host logs `feature off: rm_splash` |
| WebView injection | `[KdKit] injected into …/pk-home.html` in the WebView console |
| **PK 自动作答（端到端）** | mock 对局：脚本依次解出 10 题并通过 `checkResult` 提交 → 界面 **我方 10/10、对手 0/10**，角标 `KdKit · 已完成 10 题`。**2026-10-11 在独立设备 kd1 复核**：`[KdKit] entering mock match: …pk-room.html?mock=1` → `Q0..Q9` 逐题命中（`work/dpsdk/logcat_R3_kd1_pk.txt`、截图 `work/dpsdk/R3_kd1_pk_mock.png`） |
| H5 调试台 | WebView console 出现 `[KdKit] eruda ready`（eruda 已从 APP 自有 CDN 加载并初始化） |
| 广告 SDK 阻断 | `BlockAdSdk installed (4 hooks)` |
| **最新构建复核**（2026-10-11 08:30，07:25 构建） | 重装后 `injected (first=true)` → `HookCore ready (9 features)`；运行中 `blocked ad slot read: aj.a.d(501) -> null`；`ResumeSplashActivity` 0 次；首页 / 我的 无广告截图 `work/verify_0830_home.png`、`work/verify_0832_mine.png` |
| **12 功能构建**（2026-10-11 16:32） | `HookCore ready (12 features)`；`AntiDetect installed (3 direct hooks + 1 bridge)`、`ExitGuard installed (5 hooks)`、`SignObserver installed (6 hooks)` |
| 反调试看门狗被中和 | `AntiDetect: neutralised Debug.isDebuggerConnected / lk.f.a bridge` 每 800 ms 持续输出，进程不再自杀（对照：未开该功能时 Frida 一接触即死，`work/dpsdk/FINDINGS.md` §3） |
| 签名 / 密钥在线抓取 | `RC4KEY b(1811): b2674b28…`、`SIGN result: 16310f96…&_t_=…&kakorrhaphiophobia=…`、完整签名 URL；抓取文件 `work/dpsdk/kdkit_capture_r1.txt` |
| 抓取离线解密 | `kit/python/decrypt_capture.py` 解出 `getdid` 请求体 JSON（第三套硬编码密钥 `PackageHelper.ENTRY_KEY`，见 `work/dpsdk/FINDINGS.md` §5） |
| **广告位观测（含注册顺序坑）**（2026-10-11 19:5x） | 观测开 + blocker 关：`ADSLOT call aj.a.d(501)` / `ret -> null`（2 次）；**只把观测钩子注册在后面时**：0 行（被 blocker 短路吞掉）→ 调换注册顺序后 `call/ret` 各 2 行，同时 blocker 仍拦下 5 次。副产物：**本机 App 自己的位读取本来就返回 null**（`/init/ad/config` 空表），"看不到广告"里有一段与模块无关 |
| **拦截报表（kit 侧）**（2026-10-11 19:2x） | `BridgeGuard` 把每次拦截写进同一个抓取文件（`GUARD blocked=… reason=… url=… #n`）；`kit/python/guard_report.py` 汇总成"按 action / 按原因 / 按 host"。实测：白名单=example.com 时 7 条 `host_not_allowed`（`core_httpRequest`，宿主 4 条 `/kdchat`、各 1 条 `/kdcore`、`/init`、`/kdapi`），还原默认后新增 0。证据 `work/dpsdk/guard_r23.txt` |
| **HTTP 域名白名单（三臂）**（2026-10-11 19:1x） | A 默认白名单：走页面 0 拦截（无误报）；B 白名单=`example.com`：实测 `blocked core_httpRequest (host not allowed: /kdchat/writing/confdetailv2)`；C 还原默认：0 拦截。并修正语义：相对路径解析成宿主域名再判定（旧语义下白名单对 100% 相对路径的真实桥流量完全不起作用）。证据 `work/dpsdk/http_allow_r22.txt` |
| **字符串型配置通道（端到端）**（2026-10-11 19:0x） | 设置页把黑名单改成 `core_showDebuger,core_getStorage,core_login` → 发布文件出现 `<string name="bridge_guard_list">…` → 重启宿主后日志 `BridgeGuard installed (… blacklist=[core_showDebuger, core_getStorage, core_login])`；期间修掉一个真 bug：publisher 原本从"发布目标"读字符串（恒为空），改为读应用活 store。证据 `work/dpsdk/string_config_r21.txt` |
| **桥守卫（实验组/对照组）**（2026-10-11 19:0x） | 实验组（黑名单含 `core_removeLoading`）：驱动页面后日志 `BridgeGuard: blocked core_removeLoading #1`，页面仍正常（同页 139 条桥调用）；对照组（黑名单只留 `core_showDebuger`）：同样驱动后 blocked 计数保持 1 不新增，而桥日志显示该 action 仍被页面正常调用 → 差异只来自黑名单这一变量（`work/dpsdk/bridge_guard_r20.txt`） |
| **H5 桥实盘调用图**（2026-10-11 18:4x） | 打开首页 + PK 页后抓到 43 次调用 / 16 个 action；与静态清单（214 个 `@FeAction`）对照**只有 6 个重合** → 发现第二层"核心桥"（`core_httpRequest`/`core_storage`/`core_isLogin`…）。证据 `work/dpsdk/bridge_inventory_r14.txt` |
| **seccomp 否决退出（实验 + 对照）**（2026-10-11 18:3x） | 守卫臂（拦 exit/exit_group）：冷启 **0.28 s 死于 SIGILL**（两次复现）；对照臂（只拦 personality）：**正常存活**。结论：seccomp 存在本身不是检测信号，而"否决退出"只会把干净退出换成崩溃 —— 详见 `work/dpsdk/FINDINGS.md` §7 |
| **跳过引导（端到端 + 对照）**（2026-10-11 18:2x） | `pm clear` 后冷启：`clicked '同意并使用' #1` → `'已满14岁' #2` → `'暂不设置' #3` → **10 秒内到 MainActivity**（截图 `work/dpsdk/R11_skip_on.png`）；对照（功能关）同样清数据后**停在隐私弹窗**（`R11_skip_off.png`，无 clicked 日志） |
| **配置通道诊断卡 + 一键修复**（2026-10-11 18:0x） | 界面显示 `已发布 3 项 · 权限 644（宿主可读）`＋路径/时间；root 把权限改坏成 600 后：看门狗自动 `repaired mode 600 -> 644`，点「重新发布」→ `publisher: republish requested (…)` → 状态卡时间刷新（截图 `work/dpsdk/R8_diag_expanded2.png`） |
| **配置通道修复 + 端到端验收**（2026-10-11 17:5x） | 发现宿主读到的发布配置恒为空（`all={}`），根因是**设置应用自己的 SharedPreferences 用 AtomicFile 重写该文件、权限回落 0660**，而宿主是另一个 uid → 解析出空 map → 所有功能退回默认值。修复：`KdConfigBridge.publish()` 用 `Os.chmod 0644` + 启动一个 2 秒周期的模式修复看门狗（日志 `repaired mode 660 -> 644`）。验收：界面切开关 → 文件 `rm_adconfig=false` → 重启宿主 → `feature off: rm_adconfig`（默认是开的，证明文件被真的读到了） |
| **签名公式冻结**（2026-10-11 17:3x） | `native_probe` + `kit/scripts/read_sign_inputs.py`：`sign = md5("8&%d*" + "[" + md5hex(X) + "]@" + param)`，对抓取到的真实签名两次全量复算命中：**40/40**（`work/dpsdk/sign_inputs_r4.txt`）与 **60/60**（`work/dpsdk/sign_inputs_r4c.txt`） |
| **PK 页面真机复核**（2026-10-11 16:51） | 进入 `CommonCacheHybridActivity` 加载 `ptactivity.zuoyebang.com/static/hy/kd-pk/pk-home.html`：`[KdKit] page: …pk-home.html` → `[KdKit] injected into …pk-home.html` → `[KdKit] eruda ready`，截图 `work/dpsdk/R3_pk_try2.png`（右下角 eruda 悬浮球） |
| **离线 RC4 逐字节对齐**（8/8） | `kit/python/verify_rc4_capture.py work/dpsdk/kdkit_capture_r3.txt` → `match=1 mismatch=0`，解出 `Pluto_app_hotfix` 响应 `{"md5":"","url":"","version":"","jarTime":0}`（密钥即 nativeGetKey 的 128 字节串） |

Testing environment: AVD `test1` (Android 16, arm64) + Magisk v30.7 with a patched ramdisk
(`-ramdisk infra/ramdisk-magisk.img`, without it magiskd/vectord never start) + Vector v2.2
(`libzygisk.so`), SELinux permissive.

## 产物身份（免得"设备跑的是旧包"）

模块的可安装产物是 `module/app/build/outputs/apk/debug/app-debug.apk`。装到设备后**必须核对哈希**——
同名不同构建是最经典的假结论来源（设备跑旧包，我们却在解释新代码）：

```bash
shasum -a 256 module/app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5558 shell 'sha256sum $(pm path dev.xalor.kdkit | sed "s/package://")'
python3 kit/scripts/acceptance.py --adb emulator-5558     # 其中一项就是这两者的比对
```

## 每个功能"能拿什么证据说话"：`VERIFICATION.md`

[`VERIFICATION.md`](VERIFICATION.md) 是**自动生成**的验证矩阵（来源：功能注册表 + 当前模块日志/抓取 + 轮次日志），
41 个功能逐行给出：分类 / 默认 / 当前开关 / 本轮记录数 / **验证等级（强·中·弱）** / 依据 / 代表证据文件。

等级只表示"我们现在能用什么证据说话"：`强` = 有专门轮次 + 轮次证据；`中` = 有可计数记录；
`弱` = 只能说"已安装/已启用"。

**两个容易读错的格子**（这两处历史上都读错过）：

* **`强` 与 `记录数 0` 不矛盾。** `强` 说的是"ROADMAP 里有一轮以它为主题、且留了证据文件"——
  是**历史做过实验**；`0` 条说的是"这 5 份冻结抓取（采样止于 2026-10-18）里没有它的行"。
  两者回答不同问题。当前有 16 行是这种组合，`VERIFICATION.md` 末尾有一节逐条列出并解释。
* **`真机` 列全表都是 `未验证`。** 没有任何一行是设备上端到端跑通、做过前后对比的。
  `强` 不是"已验证"。这条有机器守卫：`test_doc_generators.py::StrongZeroIsExplainedNotSilent`
  会在任何一行的 `真机` 列被改成非 `未验证` 时变红。

生成命令：

```bash
python3 kit/scripts/feature_matrix.py --adb emulator-5558 --out module/VERIFICATION.md
```

## 现在到底在跑什么：`kit/scripts/module_report.py`

功能长到 25 个之后，"逐个回忆哪个开了、哪个这轮生效过"很容易出错。一条命令从**日志 + 抓取**里读出：

```
$ python3 kit/scripts/module_report.py --adb emulator-5558 --out work/module_report.md
| feature              | 状态 | 有安装日志 | 本轮证据条数 |
| rm_adconfig          | ON   | yes        | 72           |
| sign_observer        | ON   | yes        | 2160         |
| bridge_guard         | ON   | yes        | 7            |
| pk_assist            | ON   | yes        | 0            |   ← 本轮没触发到它的路径
…
* 打开的功能：13/17
* 打开但本轮没有证据：rm_tab_ad, pk_assist
```

**报告只认证据**：`0` 不等于"没生效"，只表示这一轮没走到那条路径 —— 这条纪律写进了报告尾部，
免得以后拿"没看到"当"没问题"。

## 配置类型

除布尔开关外，`KdConfig` 还支持**字符串**配置（第一个使用者是桥守卫黑名单）：

| 侧 | 机制 |
|---|---|
| 设置页 | `KdConfig.setAppString(ctx, key, value)` 写应用自己的 prefs |
| 发布器（框架侧，同一进程） | 每次变更把布尔 + 字符串一起写进发布文件（`<string name="…">…</string>`）；字符串必须从**应用活 store**（`publishPrefs`）取，不能从发布目标回读 |
| 宿主（快对进程） | `KdConfigBridge.installHostReader()` 同时装 `hostReader`（布尔）与 `hostStringReader`（字符串），先于各功能 `enable()` |

抓取文件（`files/kdkit_capture.txt`）由 `util/Capture.kt` 写入（`HH:mm:ss.SSS` 前缀）；**超过 4 MB 时轮换**：
老文件被**改名**成 `kdkit_capture.prev.txt` 而不是删除，并在模块日志里记一行 `capture rotated (> 4 MB) -> …`
（2026-10-11 之前是直接 `delete()`，导致 kit 若正好在轮换后拉取会看到"空抓取"，白红过一轮）。
另外：
观察类（`h5_bridge_log`）与防护类（`bridge_guard`）共用同一个文件，kit 侧一次 pull 就能出全部报表。

## 设置界面（v1.1.0 重做，设计见 [`UI.md`](UI.md)）

首屏是**分组列表**（一卡一组 + 行内分隔线），不是 38 张独立卡：

| 元素 | 说明 |
|---|---|
| 折叠大标题 | `KdKit` + `已启用 18 / 38 · 快对 7.10.2`，滚动时收成一行 |
| 状态行 | `✓ 设置已同步到快对 · N 条`；异常时变红并给「修复」入口 |
| 分组 | 去广告(7) / 内容与会员(4) / 省心开关(3) / 答题助手(1) / 诊断与抓取(23，默认折叠) |
| 行 | 人话标题 + 一句话说明 + 开关；**点行**展开「标识 · 即时生效或需重启 · 技术说明 · 子选项」 |
| 批量 | 组头「全开 / 全关」；底部「开启推荐配置 / 恢复默认 / 关闭全部诊断」 |
| 关于 | 模块版本、适配基线、兼容版本、注入方式 |

文案纪律（`ui/SettingsCopyTest` 7 条）：文案恰好覆盖 38 个 id；副标题 ≤ 22 字且不含类名/括号里的实现细节；
标题 ≤ 8 字；「去广告」组不混入非广告功能；分组计数与 `UI.md` §3 一致。

点状态行右侧的「诊断」打开**配置通道对话框**（原顶部那张技术卡）：显示发布文件的实际路径、权限、
已发布条目数与时间戳，并提供**一键「重新发布（修复权限）」**；权限不是 644（宿主读不到）时提示
"设置没送到快对，开关可能不生效"。

两端是不同 ClassLoader（UI 不能碰 Xposed 类），也可能持有**不同的 SharedPreferences 实例**，
所以按钮不是改 prefs，而是往应用自己的目录丢一个请求文件（`files/kdkit_repair.request`），
框架侧的 publisher 看门狗每 2 秒轮询并执行重发 + `chmod 644`。实测日志：

```
publisher: repaired mode 600 -> 644
publisher: republish requested (1791712849186)
published 3 flag(s) mode=644 -> /data/misc/<uuid>/prefs/dev.xalor.kdkit/kdkit.xml
```

（`_` 前缀的键是模块内部 meta，不会发布给宿主。）

## 已知坑：发布配置的权限

宿主（快对）与模块设置应用是**不同 uid**，宿主通过 `XSharedPreferences` 读
`/data/misc/<uuid>/prefs/dev.xalor.kdkit/kdkit.xml`，因此该文件**必须 world-readable**。
设置应用自己写 SharedPreferences 时会用 AtomicFile 重建文件，权限会回到 `0660`
（宿主随后解析出空 map，所有功能静默回退到默认值——2026-10-11 实测并修复）。
`KdConfigBridge` 现在每次发布都会 `chmod 644`，并有一个看门狗兜底；
排查时可看模块日志里的 `published N flag(s) mode=…` 与 `repaired mode … -> 644`。

## Debugging

The host-side log is written to the framework's module log, not logcat:

```bash
adb shell 'tail -100 /data/adb/lspd/log/modules_*.log' | grep KdKit
adb logcat -d | grep 'chromium.*KdKit'      # userscript console output
```

If the module stops injecting after a bad emulator boot: check `pm path dev.xalor.kdkit` — when it
prints nothing the install state is broken, so `adb install -r` the APK and re-run
`modules enable` + `scope add` (Vector's config keeps the old, dead code path otherwise).

---

## 2026-10-25 优化轮：验收状态

| 门 | 结果 | 命令 |
|---|---|---|
| 单元测试 | **42/42** | `./gw --offline testDebugUnitTest` |
| 编译（含 Compose 设置页） | **通过** | `./gw --offline assembleDebug` |
| 功能表 / 子选项 schema / README 列 | **一致（41 项）** | `python3 scripts/check_feature_parity.py` |
| 钩子目标（类+方法） | **36/36** | `python3 ../kit/scripts/check_hook_targets.py` |
| 钩子签名（形参类型） | **24/24 吻合，0 无法判定** | `python3 ../kit/scripts/check_hook_signatures.py` |

**这一轮全部验证都是离线的**：当前没有连接设备（`adb devices` 为空），
所以"钩子目标和 APK 对得上"是静态结论，"热开关真的 1 秒生效"仍需真机确认。
真机步骤见 [`OPTIMIZATION.md`](OPTIMIZATION.md) §7。

静态侦察的完整记录在 [`NEW_TARGETS.md`](NEW_TARGETS.md)：它给出了 3 个新功能的钩点证据
（smali 文件:行号），也明确否掉了 3 条误报线索（`BrushMaskView` 死代码、`ma/d` / `bf/b` 与 VIP 无关、
"客户端钩一个方法就能去水印"在本 App 无对应实现）。
