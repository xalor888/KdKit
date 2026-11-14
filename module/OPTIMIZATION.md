# KdKit 模块优化报告（2026-10-25）

一轮集中优化：**底座重构 → 热开关 → 补齐悬空配置 → 新增功能 → 门禁与测试 → 文档**。
全部改动都过五道门（`./scripts/verify.sh`），当前 **5/5 绿**。

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 功能数 | 25 | **28** |
| 可热切换（不必重启快对） | 0 | **27 / 28** |
| 悬空配置键（代码读、界面写不了） | 7 | **0** |
| JVM 单元测试 | 0 | **42** |
| 构建前门禁 | 2 | **5**（+ 钩子签名 + 幽灵键/文档列一致性） |
| 抓取写盘实现 | 4 份重复 | **1 份**（含异步写者、轮转、限流、统计） |
| 源码规模 | 29 文件 / 3 114 行 | **43 文件 / 4 454 行**（测试另 8 文件 / 328 行） |
| 钩子安装可审计 | 否（只有散落 warn） | **是**（`N ok / M failed` 一行结论 + 失败点名） |
| 宿主版本守卫 | 无 | **有**（启动写 `host 7.7.2/1811 sdk=36` + 漂移告警） |

---

## 1 底座重构（`util/`）

旧版有一个共同的形态问题：**每个观测功能自己写一份落盘逻辑**。
`SignObserver`、`NativeProbe`、`ReqHeaders` 各自维护 `File` + `SimpleDateFormat` + 4MB 判断；
`Capture` 自己又是一份。四份实现，四个 bug 面（其中"轮转直接 delete"曾经造成一轮假红）。

### 1.1 `Capture`：单写者线程 + 有界队列

* 调用线程只做一次 `queue.offer()`（内存操作），写盘在 `KdKit-capture` 守护线程；
* 队列满 ⇒ 丢弃并计数（`stats()` 里 `dropped`）。**宁可丢观测，不可拖慢宿主**；
* 写满 `maxBytes` 时**改名**为 `kdkit_capture.prev.txt` 而不是删除 —— kit 侧的 pull 若正好撞上轮转，
  旧行为会读到近空文件并误判"没数据"（2026-10-11 真实踩过）；
* `maxBytes = 0` 表示不限制（长取证场景）；
* 行格式保持不变：`HH:mm:ss.SSS <line>`，`kit/python/` 的 6 个解析器无需改动。
* 纯决策逻辑抽到 `CapturePolicy`（JVM 可测）：`shouldRotate` / `clamp` / `format`。

### 1.2 `RateLimit`：所有高频回调共用的节流层

* `every(key, ms)`：同一 key 每 N 毫秒放行一次（用于 800ms 轮询的反调试看门狗心跳）；
* `firstN(key, n)`：只记前 n 条（用于广告位、桥 action、日志行）；
* 时钟可注入（`clock`），测试不 sleep。

### 1.3 `HookAudit`：钩子安装台账

`Xp.hook` 失败时原本只写一行 `hook failed ...` 就返回 false，功能照旧"已启用" ——
最常见的故障形态是**模块报 ready、功能静默失效**。现在每条钩子都记账，启动时输出一行：

```
[KdKit] HookCore ready 28/28 features, hooks 96 ok / 0 failed
失败时：... hooks 93 ok / 3 failed -> RemoveSplashAd:lk.a.j, ...
```

### 1.4 `Xp`：门控 + 记账 + 归属

新增 `gate` 参数与 `under(ownerId)` 作用域：钩子归属明确，回调可在**调用点**判定开关（见 §2）。

### 1.5 纯逻辑外提（可测化）

把"只能靠真机跑一轮才知道对不对"的判断抽成纯函数：

| 新模块 | 原来在哪里 | 为什么值得抽出来 |
|---|---|---|
| `CapturePolicy` | `Capture` / `SignObserver` | 轮转与截断的边界条件（空文件、0 上限） |
| `NavFilter` | `NavLog` 钩子闭包 | 决定"某页面算不算被观测到"（`UNVISITED_PAGES.md` 的分母） |
| `RouteFilter` | `RouteLog` 钩子闭包 | `I(String)` 也被非路由字符串调用；调用方提取曾返回"KdKit 自己" |
| `LogFilter` | `LogSink` 热路径 | 全模块最热的一条钩子（`android.util.Log.*` 全进程） |
| `HostAllowList` | `BridgeGuard.httpAllowed` | 白名单的同名子串绕过（`evilkuaiduizuoye.com`） |
| `TextHeuristic` | `RC4Probe` 明文判定 | 旧判据只认 CJK ⇒ 纯英文/数字明文整类被丢 |

### 1.6 `LogSink` / `AntiDetect` / `H5BridgeLog` 的日志治理

| 位置 | 旧 | 新 |
|---|---|---|
| `LogSink` | 每行 `tag.lowercase()` + 线性扫 8 个 tag + 若干 `contains` | tag 集合预小写 + 关键词窗口剪枝 + 每 tag 预算 |
| `AntiDetect` | 看门狗每 800ms × 4 个判定点，每条都 `KdLog.i` | 前 6 条逐条 + 每 5 分钟一条心跳（证明"持续在工作"） |
| `H5BridgeLog` | 每 action 无限写抓取 | 每 action 上限 200 条（桥实测一页 139 次调用） |

---

## 2 热开关：从"装了就不能改"到"钩子常驻 + 调用点门控"

**旧语义**：关着的功能不装钩子；钩子只在进程启动时装一次 ⇒ 改开关必须**重启宿主**。
**新语义**：`hot = true` 的功能**始终安装**钩子，回调在调用点先问配置（`KdConfig` 带 2s TTL）。

* 关闭 = 回调不执行、原方法照走，行为可预测；
* 打开 = 1–2 秒内生效（TTL 到期）；
* **27/28** 个功能已切到热语义；唯一例外 `native_exit_guard` 保持冷开关 ——
  它装的是 seccomp 过滤器，**对进程不可撤销**，热切换没有意义（也没有安全的"卸载"路径）。

`KdConfig` 同时修掉一个真 bug：旧实现把每个 key 的**第一次**读取结果永久缓存，
这也是"必须重启"的根因之一（不只是钩子只在启动时装）。

---

## 3 补齐悬空配置（7 → 0）

以下键此前"代码在读、界面写不了"，只能靠 kit 脚本或手工改 prefs：

| 键 | 现在 |
|---|---|
| `pk_mock` / `pk_auto_answer` | `pk_assist` 的选项，设置页可见；另加 `pk_answer_delay_ms`（作答节奏） |
| `bridge_guard_list` / `bridge_guard_http_allow` / `bridge_guard_probe_remove_loading` | `bridge_guard` 的选项（黑名单/白名单/对照开关） |
| `native_exit_guard_control` | `native_exit_guard` 的选项（seccomp 对照组） |
| `page_js_script` | `page_js` 的选项（`userEditable = false`：由 `call_page_js.py` 写入） |
| 新增 | `exit_guard_block`（只记录 vs 真拦截）、`rc4_probe_uplink`、`route_log_dedupe`、`log_sink_per_tag`、`sign_observer_pairs`/`_logcat`、`native_probe_capture`、`web_request_log_bodies`、`update_force_neutralise`、`vip_unlock_tbx`/`_silent`、`bridge_action_log_url` |

设置页不再为每个功能写界面：`KdOption`（`BOOLEAN` / `STRING`）由功能自己声明，
`ui/OptionEditors.kt` 通用渲染。**门禁把两边钉死**（见 §5）。

---

## 4 新增功能（3）

全部基于静态侦察 `NEW_TARGETS.md` 的**可验证**目标；侦察同时否掉了 3 条误报线索。

### 4.1 `skip_update` 跳过强制更新

钩点 `ei.y.L()` —— 全 APK **唯一**读 `CommonPreference.FORCE_UPDATE` 并进入强制流程的地方：

```smali
:2166  sget-object v1, CommonPreference;->FORCE_UPDATE
:2181  if-eqz v1, :cond_1          # 不强制 → 普通更新
:2193  invoke-static {..}, Lxl/z2;->t(Activity;ZZLci/a;)V
```

* 默认档：只让 `L()` 直接 return ⇒ **不写任何偏好，完全可逆**；
* `update_force_neutralise` 打开后才改 `CheckAppUpdate.forceUp`（走"普通更新"而不是完全不提示），
  代价是该值会被 `z2$b` 写进偏好（持久）。

### 4.2 `vip_unlock` 会员状态解锁（客户端）

钩 `bk.a.p()`。**最强证据**：`VipCurrentStatusWebAction`（`@FeAction("app_kdzy_vip_current_status")`）
把 `bk.a.p()` 当作唯一来源直接回给 H5 ⇒ 钩一处，页面侧全部生效。

明确写入文档的限制：**只改客户端判定**，服务端鉴权（`/kdapi/…`、图片合成、题库解析）不受影响。
`vip_unlock_silent` 用于避开 `MainActivity` 的 `isvip` 埋点污染（改为只影响 H5 回包）。

### 4.3 `bridge_action_log` 高价值桥 action 观测

结构化记录两条有明确语义的 action：`downloadMedia`（页面往相册写哪张图、type 是否为 1）
与 `getuserinfo`（谁在打听身份）。刻意**按精确类**钩 —— 7 个 `FeAction` 共享方法名 `onAction`，
`hookAll` 会命中 397 个 action。

### 4.4 侦察否掉的三条线索（写进文档，避免后人重走）

| 线索 | 结论 |
|---|---|
| `BrushMaskView` 去水印 | **死代码**：全 APK 只命中自己，且在加固壳命名空间 `com.byazt.*`。钩了没有任何效果 |
| `ma/d` / `bf/b` 是 VIP 判定 | **误报**：前者是 Gson 的 `TypeAdapterFactory`（`vip` 只匹配到 `isMemberClass()`），后者是网络回调层 |
| "一个 before 钩子让水印不绘制" | **本 App 无对应实现**：水印是**服务端合成**，`clearWatermark` 被编成 `"2"` 拼进 `ext` 上传 `/kdapi/image/combine` |

另有一条**不可钩 getter** 的教训：`Userinfov3` / `CheckAppUpdate` 方法表里只有 `<init>()V`，
字段全 public 靠 `iget` 直读 ⇒ 只能反射改字段或钩上游方法。

---

## 5 门禁与测试

`module/scripts/verify.sh` 一条命令跑五道门（离线，不需要设备）：

```
① 单元测试            42 个 JVM 测试（纯逻辑：过滤/限流/白名单/截断/路由/文本）
② assembleDebug       含 Compose 设置页
③ 功能表/子选项一致    FeatureRegistry ↔ README ↔ KdOption schema
④ 钩子目标            每条 Xp.hook 的类/方法在解码后的 APK 里存在
⑤ 钩子签名            再比形参类型（④ 的盲区）
```

### 5.1 `③` 扩了三件事

1. **幽灵键**：代码 `KdConfig.isOn/getString` 读的每个键必须是 feature id 或某个 `KdOption`；
2. **死选项**：每个 `KdOption` 必须真的被读到（否则设置页出现"拨了没反应"的开关）；
3. **文档列一致**：README 的「热」「选项」两列必须与代码的 `hot` / `options` 完全一致。

三条都做了**反向验证**（故意写错 → 确认门禁报红 → 还原）。

### 5.2 `⑤` 是这次新加的门禁，而且**当场抓到了一个真 bug**

`check_hook_targets.py` 只比对"类名 + 方法名"。签名写错时它报 `OK`，运行时 `Xp.hook` 返回 false、
功能静默失效 —— 这是侦察报告 U6 指出的盲区。

新脚本 `kit/scripts/check_hook_signatures.py` 把 `String::class.java`、`a.b.C::class.java`、
`Xp.clazzOrNull("a.b.C")` 的本地别名都解析成 smali 描述符，与 APK 里**所有**同名重载逐一比对。
它第一次运行就抓到我自己刚写的错误：

```
SIGNATURE-MISMATCH  VipCurrentStatusWebAction.onAction(Landroid/app/Activity;Lorg/json/JSONObject;)
        APK 里实际是: (Landroid/app/Activity;Lorg/json/JSONObject;L...HybridWebView$ReturnCallback;)
```

—— 少写了第三个参数。写完即被拦下，而不是等到真机上"功能没反应"。
当前 **24/24 钩子签名吻合，0 无法判定**。

---

## 6 顺带修掉的真 bug

| # | 问题 | 影响 |
|---|---|---|
| 1 | `WebInjector` 对同一页面注入**两遍**（`loadUrl` 与 `onPageFinished` 都会调） | eruda / xhr recorder 各初始化两套 |
| 2 | 全功能关闭时仍会 post 一个空的 `evaluateJavascript` | 每个页面一次无意义跨进程调用 |
| 3 | `SignObserver` 的 4 类加解密共用**一个**预算计数器 | 先跑的类别吃光预算，其余永久静默 |
| 4 | `RC4Probe` 明文判定只认 CJK | 纯英文/数字明文整类丢失，且看不出"是被过滤了" |
| 5 | `WebInjector` 曾用 `WeakHashMap` 做注入去重 | 键是新建 String，弱引用永不回收 ⇒ 反而无界增长（写完自查时发现，改为有界 LRU 256） |
| 6 | KDoc 里写 `` `/kdapi/*` `` | Kotlin 块注释**可嵌套**，`/*` 让注释永不闭合，报错指向文件末尾，极难定位 |

第 6 条尤其值得记：它一开始表现为 `Syntax error: Unclosed comment` 指在第 101 行，
而真凶在第 29 行的一句路径文字里。

---

## 7 仍未做 / 做不到的（诚实清单）

> **状态（2026-10-25 第 8 轮）**：本表原始 5 条里有 2 条已在本文件更靠后的章节做完
> （去水印 → §10；`check_hook_targets.py` 的"有没有人调用" → §9 的第 ⑥ 道门），
> 但**表本身没跟着改**，于是它长期在说"未做"。这正是本项目反复踩的那种文档漂移：
> 结论被写进新章节，旧清单留在原处继续误导后来者。下表已按事实重写。

| 项 | 状态 | 原因 / 现在的证据 |
|---|---|---|
| 真机验证 | **仍未做** | 当前无连接设备（`adb devices` 为空）。所有结论只在**静态层**成立（目标存在 / 签名吻合 / 有调用方 / 编译过 / 单测过）。§10–§15 每节末尾都写了"仍未验证" |
| 去水印 | **已实现**（客户端开关） | `watermark_off` 钩 `cu.l` 构造器置 `r` 字段，让 `/kdapi/image/combine` 的 `ext` 带上 `"2"`。见 §10。**产物是否真无水印：未验证**（服务端合成） |
| VIP 服务端效果 | **未验证** | 客户端判定 ≠ 服务端授权。`vip_unlock` 只改客户端（§4.2）；`vip_limit_probe` 只观测（§14）。需要真机抓包看哪些接口会 403 |
| `native_exit_guard` 热切换 | 不做 | seccomp 过滤器对进程不可撤销 |
| `check_hook_targets.py` 的"有没有人调用" | **已覆盖** | 第 ⑥ 道门（`check_hook_callers.py` + `smali_usage.py`），五层判定、只对 `DEAD` 判红。`BrushMaskView` 现在是**可复跑的断言**（`test_smali_usage.py::RealApk`），不再靠人工侦察 |

### 2026-10-25 第 17 轮：核对任务清单里的 ①②③，逐条给出实证

上一轮之后，待办清单里仍挂着「扩充解析器前缀 / 重写 ACTIVITY+VERIFICATION / 给
`check_hook_targets.py` 加调用方判定」三件事。这轮**逐条去核**，结论是**三件都已落地**，
只是清单没有跟着改 —— 又一次"文档说未做、代码已做完"的漂移。证据如下（都可离线复跑）。

| 项 | 实际状态 | 证据（可复跑） |
|---|---|---|
| ① 11 个新前缀 | **已完成** | `capture_schema.py` 里 `PREFIX_FEATURE` 共 **36** 个 token，含 `EXITCALL`/`EXITSTACK`/`BRIDGE`/`VIP`/`UPDATE`/`ONBOARD`/`APPSIGN`/`RC4PT`/`GUARD`/`WEBREQ`/`HDR`。表驱动用例 **53** 条；`RC4PT(nontext)`/`RC4UP(nontext)` 由**最长前缀优先**认领（顺序是契约，见 `capture_schema` 模块文档 29–30 行）。`test_capture_schema.py::KotlinSideDrift` 从 Kotlin 源码反扫字面量，写出未登记前缀会红 |
| ② ACTIVITY/VERIFICATION 对齐 | **已按生成器口径重建** | 两份都由 `module_activity.py` / `feature_matrix.py` 生成，并由 ①b 断言「提交的文件 == 生成器的输出」。这轮发现该断言真的在生效：`VERIFICATION.md` 曾停在 `http_body_probe 4/4`，而 APK 实际是 **5/5**（`HttpBodyProbe.kt` 有 5 处 `Xp.hook`），已重新生成 |
| ③ 调用方判定层 | **已是第 ⑥ 道门** | `check_hook_callers.py` + `smali_usage.py`：五层证据（`USED`/`USED(self)`/`REFLECTIVE`/`SUPER-SLOT`/`TYPE-ONLY`/`DEAD`），只对 `DEAD` 判红。`BrushMaskView` 是 `test_smali_usage.py::RealApk` 里的可复跑断言 |

**这轮真正修掉的三个缺陷**（都不是"清单项"，是清单核对时撞出来的）：

| 缺陷 | 危害 | 修法 |
|---|---|---|
| `feature_matrix.static_hook_evidence()` 用固定临时文件 `/tmp/kdkit_sig_matrix.json` | 并发时读到半个 JSON ⇒ ①b **偶发红**（4 路并发稳定复现）；更坏的是旧代码 `if rc != 0 and not os.path.exists(out)` 在门禁**失败**时回落旧文件 ⇒ **陈旧证据通过门禁** | `mkstemp` 每次唯一；失败分支一律 `return {}`。用 AST 断言控制流（第一版用 grep 断言，被注释里的说明文字误伤，已改） |
| ④⑤⑥ 与 `smali_usage` 的 `--smali` 默认值是**相对路径** `'work/apktool_out'` | 命令行靠 `cd $ROOT` 兜住，但 `feature_matrix` **从 Python 里**调签名门禁时继承自己的 cwd ⇒ `FileNotFoundError` ⇒ 返回空 ⇒ `VERIFICATION.md` 的「静态钩子」**整列变 `-`**。不报错，只让文档看起来"没有静态证据" | `hook_vocab.repo_path()` 从**脚本位置**推导绝对路径；四个脚本改用之；加测试断言"从任意 cwd 解析结果逐字符相同" |
| `verify.sh --quiet` 在失败时**整段丢弃日志** | 上一轮那次 ①b 偶发红无法当场定位，只能靠重跑碰运气 | 失败原因**无条件打印**（quiet 只压成功时的啰嗦） |

**另外清掉一处真实泄漏**：`test_hook_gate_agreement.py:276` 在 5 万次循环里裸
`open().read()`，产出 **49931 条 `ResourceWarning`**，把 `-q` 的输出撑到 15 万行 ——
真失败被埋在噪声里；在 `ulimit -n` 低的终端还会撞 `Too many open files`。
已降到 36 条，并新增 `hook_vocab.read_text()` 作为唯一读文件入口。

### 2026-10-25 第 17 轮（续）：抓取样本里的凭证 —— 仓库里真实的泄露

在做第 ④ 项（找新功能）时换了信息来源，去读模块自己抓到的真数据。功能没找到，
但撞到一件比新功能重要得多的事。

**5 份抓取里，同一条登录 token 出现 1418 次。**

```
07:58:17.220 SIGN params: … | token=1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM | vc=1811
07:58:17.220 SIGN URL: https://…&token=1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM&sign=c41a117b…
```

`work/activity_inputs/` 是**原始 logcat**，而 `APPSIGN`/`SIGN params`/`SIGN URL` 这三类
记录会把 query 原样写下。于是凭证随样本进了仓库，并且一起进来的还有 `cuid` / `adid` /
`did` / `sign`。

**为什么这不是"看着不舒服"，而是真缺陷**：`sign=` 是 `f(params + secret)` 的结果，
而 `params` **含 token**。留着一份"输入 + 输出"的签名样本，配上本仓库已经还原的
签名算法，足以离线伪造请求。设备指纹三件套（`did`/`adid`/`cuid`）则足以冒充该设备。

**修法**：`kit/python/redact_capture.py`，三条硬约束（都有测试）：

| 约束 | 为什么 | 怎么保证 |
|---|---|---|
| 只动值，不动结构 | 样本的价值在结构：`_t_`/`abis`/`vc` 是签名复现的必需输入 | 键名与分隔符逐字节保留；**逐前缀统计完全一致**（5 份都核对过） |
| 空值保持空 | `did=REDACTED` 会让 `SIGN params` 的**键集合**凭空多一项，而它是统计输入 | 规则用 `*` 量词 + 显式短路 |
| 幂等 | "离线可重复"的前提 | 跑两次结果相同；`--check` 有残留退出 1 |

**门禁化**：`test_redact_capture.py::RealCapturesAreRedacted` 每次检查 `work/activity_inputs/`，
新增未脱敏抓取立刻红 —— 不靠"记得跑"。

**顺手抓到的第二个缺陷（更阴）**：`module_activity.py` 用 `os.path.getmtime` 当"最晚采样日期"。
脱敏就地改写后 mtime 全变成"今天"，于是 `ACTIVITY.md` 会写成"最晚一份是 2026-10-25"，
而真实采样日是 **2026-10-18**。后果不是措辞，而是**结论方向反了**：

* 正确读法：`skip_update` / `vip_unlock` / `bridge_action_log` 0 行 = **样本早于功能**；
* mtime 一漂：读成 **功能失效**。

`ACTIVITY.md` 第四节存在的全部理由就是防这个误读，而借文件系统的时间会把它整节作废。
已改为从 `work/activity_inputs/README.md` 的登记表读日期；查不到就写 `?`（不猜）。
守卫：`SampleDateComesFromDataNotFilesystem`，用 AST 断言没有 `getmtime` **调用**
（第一版用 grep 文本，被注释里"为什么不能用 getmtime"误伤 —— 同一个坑本文件已踩三次，
现在的规矩是：**断言行为用 AST，断言文本只在文本本身是契约时**）。

**这轮的第 ④ 项结论（诚实记）**：没有新增功能。扫过的候选与放弃理由：

| 候选 | 结论 |
|---|---|
| `ClearAppDataWebAction.onAction`（h5 `clearCacheData`，清空 App 数据） | **不采**。反编译看它在真正清除前会弹二次确认对话框（"撤销后您将退出登录且删除本地存储的数据"），破坏力受用户确认约束，不是静默接管 |
| `kit/python` 里 11 个新前缀（清单第 ① 项） | **已全部完成**。`PREFIX_FEATURE` 共 36 个 token，表驱动用例 53 条。清单过期，已就地更新 |
| `NEW_TARGETS.md` 的 5 条候选 | 均已落地（`skip_update` / `watermark_off` / H5 桥 / `vip_unlock`） |

**未验证**：脱敏后的样本在真机新抓取上是否仍逐字节可比（需新抓取）；`clearCacheData`
的二次确认是否可被页面脚本绕过（需真机 + 构造调用）。

### 仍然真的缺的三件事

| 项 | 状态 | 说明 |
|---|---|---|
| 抓取样本的时效 | **缺口** | `work/activity_inputs/` 最晚一份是 **2026-10-18**，而 `skip_update` / `vip_unlock` / `vip_limit_probe` / `watermark_off` 与 `EXITCALL` / `VIPLIMIT` / `RC4PT(nontext)` 等前缀都是 10-25 之后才加的 ⇒ 这批样本里它们必然 0 行。`ACTIVITY.md` §四逐条标注，不混进"失效" |
| 方法级可达性 | **不做** | ⑥ 只判**类级**零引用（`DEAD`）。方法级"不可达"要全程序可达性分析，静态证据不足；拿"看不见"当"不存在"正是 `NEW_TARGETS.md` 那三条误报的来源（见 README 门禁标签表） |
| 5 条钩子的形参 | **已覆盖（第二种子）** | ⑤ 仍报 `UNKNOWN`（`aj.a` 的 4 个 SDK init 形参是混淆类 `Lxc/a;`；`cu.l` 14 参构造器由 `declaredConstructors` 逐个比对，不是字面量）。**但已有自动的源码↔APK 交叉校验**：`test_smali_usage.py::DynamicParamCrossCheck`（从源码读 `ARG` 常量、与 APK 里四个 init 的真实形参比对）与 `SignatureCrossCheck`（从 Kotlin 解析硬编码的 14 参期望表、与 `cu.l` 真实构造器逐位比对）。两条都做过反向验证（把期望值改错 → 测试精确报错） |

### 2026-10-25 第 12 轮复核：本清单还剩什么

逐条核过，**能用工具关的都已关，剩下的都真的需要一台设备或做不了**：

| 曾经的"缺口" | 现在 | 靠什么 |
|---|---|---|
| 钩子目标存在性 | 关了 | ④ |
| 形参签名 | 关了（除 5 条混淆类，见下） | ⑤ |
| 有没有调用方（死代码） | 关了 | ⑥ + `smali_usage.py` |
| 5 条混淆类形参（`xc.a` ×4、`cu.l` 14 参） | 关了（第二种子） | ①b 的源码↔APK 交叉校验 |
| 动态类名钩子（`hookAllBefore(name, "…")`） | 关了 | ①b 的 `DynamicClassHooks` |
| 文档功能数漂移 | 关了 | ③ 的 `check_declared_counts` |
| 门禁标签不一致 | 关了 | `hook_vocab.py` + 14 个测试 |
| **抓取样本时效** | **仍缺** | 只能靠真机跑一轮新构建（见 `work/activity_inputs/README.md`） |
| **真机行为** | **仍缺** | 无设备 |
| 方法级可达性 | 不做 | 需全程序可达性分析 |

也就是说：**代码层、门禁层、文档层能自动化的都自动化了**。剩下的两项（样本时效、真机行为）
不是"没做"，是**没有设备就做不了**，且都已经写进文档而不是假装不存在。

写这一节的原因：本表上一版（第 8 轮）已经因为"结论写进新章节、旧清单没改"
漂移过一次。与其再等一轮，不如每次复核都把这行状态就地更新。

### 下一步（有设备时）

1. `./kit/scripts/env_up.sh kd1 5558` 起设备，装新包；
2. 看启动首三行：`host 7.7.2/1811 sdk=36` → `HookCore start` → `HookCore ready 30/30 features, hooks N ok / 0 failed`；
3. 逐个翻转热开关，确认 1–2 秒内日志出现 `feature on/off` 且**不需要重启**；
4. 重点验 `skip_update`（`ei.y.L`）、`vip_unlock`（`bk.a.p`）、`vip_limit_probe`（`VipLimitViewModel.b`）、
   `watermark_off`（`cu.l` 构造器）—— 全是混淆名，升级后最易失配；
5. **把新抓取放进 `work/activity_inputs/` 并在此登记来源与日期**，再重跑
   `python3 kit/scripts/module_activity.py --dir work/activity_inputs --out module/ACTIVITY.md`
   —— `ACTIVITY.md` §四那张"样本早于功能"的表会自动缩短，这是关闭该缺口的唯一办法；
6. 用 `kit/scripts/module_report.py` 与 `evidence_pack.py` 收证据。

---

## 8 第 1 轮续跑（2026-10-25 晚）：补完目标③的两个键 + 抓出五处门禁盲区

### 8.1 `log_level` / `capture_max_mb` 真正接线

目标③列的 7 个键里，这两个此前**只有字段、没人读**：
`capture_max_mb` 只在 `Capture.maxBytes` 的 KDoc 里被提到，`log_level` 完全没接线。

新增 `config/CaptureSettings.kt`：
* `mbToBytes` / `kbToChars` / `parseLevel` —— **纯函数**，5 个单测直接测真实代码
  （第一版测试在测试里抄了一遍公式，等于测测试自己，已改掉）；
* `apply()` 在 `HookCore.start()` 里调一次，把三个值写进 `Capture` / `KdLog`；
* 三个键由 `LogSink` 声明为 `KdOption`（它们都是"记录类"设置，这是最自然的归属），
  设置页自动出现，门禁自动校验。

### 8.2 五个门禁盲区（都是"钩子写了但从来没被校验过"）

起因：给 `VERIFICATION.md` 加"静态钩子"列时发现，`RouteLog` 那一格是 `-`
—— 说明它的 3 个钩子目标**从未被任何门禁看过**。顺着查下去，共五处：

| 位置 | 写法 | 后果 |
|---|---|---|
| `RouteLog` | `Xp.hook(cls.name, name, *types, ...)` | 3 个路由钩子全不校验 |
| `RC4Probe` | `Xp.hook(cls.name, "<init>"/"setKey"/"decrypt"/"encrypt", ...)` | **4 个全不校验**，其中 `decrypt` 是该功能的核心 |
| `NavLog` | `Xp.hook(CLS, ...)`（常量） | 2 个 loadUrl 钩子不校验 |
| `RemovePopupAd` | `Xp.hook(dialog.name, ...)` | 1 个不校验 |
| `BlockAdSdk` | `for ((cls, m) in listOf(...)) Xp.hook(cls, m, ...)` | 4 个 SDK init 全不校验 |

**修法**：门禁按**字面量**解析类名/方法名，所以全部改成字面量调用。
门禁覆盖 **24 → 40 条钩子**（36 条签名吻合 + 4 条形参为混淆类、只能人工核对）。

### 8.3 顺带抓到一个运行时必然失败的钩子

`RC4Probe` 用 `Xp.hook(cls, "<init>", ...)` 钩构造器 ——
而 `XposedHelpers.findAndHookMethod(类, "<init>", ...)` **永远返回 false**（构造器没有方法名）。
这条钩子从写下来那天起就是死的，只是没人校验过所以没人发现。

修法：`Xp` 新增 `hookCtor`（走 `findAndHookConstructor`，同样带 gate 与台账），
门禁也学会区分 `hook` 与 `hookCtor` 两种调用形态。

### 8.4 门禁增强

* **跨文件常量解析**：`KdOption(key = CaptureSettings.KEY_MAX_MB)` 这种写法现在能被幽灵键检查识别；
* **构造器签名比对**：`hookCtor` 的目标会真正比对参数列表（不再是"跳过"）；
* **UNKNOWN 时打印真实签名**：`(Lxc/a;)` 这种人工核对项，脚本直接把 APK 里的答案列出来；
* **`ACTIVITY.md` 覆盖门禁**：前缀表必须点名每个 feature，否则报告脚本会统计不到它、
  而"计数 0"会被误读成"功能没生效"；
* **README「热」「选项」两列校验**：与代码的 `hot` / `options` 逐项比对。

新门禁都做了**反向验证**（故意写错 → 确认报红 → 还原），不是只写不验。

### 8.5 `VERIFICATION.md` 改为离线可生成 + 增加"静态钩子"列

`kit/scripts/feature_matrix.py` 原来强依赖 `--adb`，无设备时根本生成不了文档。
现在 `--offline` 用工作区快照 + 纯静态事实生成，"当前"列为 `?`（不是 `OFF`，避免被读成"功能被关了"）。
新增 `静态钩子` 列回答"钩得住吗"，把 `弱` 拆成两种：
**"钩子 0/N，什么都没证明"** 与 **"钩子 N/N 解析成功，只是还没有真机证据"**。

### 8.6 本轮门禁结果

```
① 单元测试            47 个（+5：CaptureSettings）
② assembleDebug       通过
③ 功能表/子选项       31 个功能一致（+ ACTIVITY 覆盖 + README 列校验）〔当轮值〕
④ 钩子目标            通过
⑤ 钩子签名            40 条：36 吻合 / 0 不符 / 4 人工核对
```

**仍未验证**：一切真机行为。本轮所有结论都是静态的。

---

## 9 第 2 轮续跑：门禁从"存在"推进到"会被执行"

### 9.1 新的第 ⑥ 道门：钩子目标有没有调用方

前五道门都只能证明"钩得住"，不能证明"钩了会执行"。
`BrushMaskView.onDraw` 就是活例子：类在、签名对、`Xp.hook` 返回 true，
**全 APK 零引用** ⇒ 钩上去永远不会有第二行日志。

新增 `kit/scripts/smali_usage.py`（判定层）+ `check_hook_targets.py` 委派，
按四层取最强结论：

| 层 | 证据 | 结论 |
|---|---|---|
| ① 直接调用 | 别的文件 `invoke-* La/b/C;->m(` | `USED` |
| ② 类内调用 | 只有本类别的方法在调它 | `USED(self)`，仍算活（入口在别的方法上）|
| ③ 父类槽位 | 父类型声明同名同参且槽位有 `invoke-virtual` | `SUPER-SLOT`，可能经分派进入 |
| ④ 仅类型引用 | 字段/形参/`new`/`const-class`/`res/` 布局 | `TYPE-ONLY`（DTO 形态，不是死代码）|
| — 全无 | 本类之外零引用 | **`DEAD`** ≙ 钩了必空转 |

**只对 `DEAD` 报红**。方法级"不可达"需要全程序可达性分析，静态证据不足，
拿"看不见"当"不存在"正是这个项目反复踩的坑（`NEW_TARGETS.md` 那三条误报就是这么来的）。

### 9.2 判定结果（真实 APK）

```
48 个钩子目标：48 有使用证据 / 0 DEAD
  bk.a:p              USED          17 处直接调用
                     例: VipCurrentStatusWebAction.smali:290   ← 与人工侦察一致
                     例: MainActivity.smali:2660
  ei.y:L              USED(self)    只由本类 L() 的调用方进入
  com.byazt.nd.BrushMaskView:onDraw   DEAD   ← 加固壳残留，去水印线索的误报来源
```

最后那条现在是**可复跑的断言**（`kit/python/tests/test_smali_usage.py::RealApk`），
不再依赖"侦察时手工确认过"。

### 9.3 这一轮修掉的三个 bug（都是我自己或并行轮次引入的）

| bug | 表现 | 修法 |
|---|---|---|
| 继承索引 O(n²) | 每个目标都重建 6 万类的继承表（19s/次），脚本卡死 | 缓存 + 反向索引（父→子）BFS；`build_index` 只解析我们 hook 的那几十个类（529MB → 20s） |
| `MISSING` 被算成"有使用证据" | 类根本不在解码目录，却报 `3/3 有证据` | 单独统计并打印 `MISSING n 个（等于没有证据）` |
| 白名单按**类**匹配 | `com.byazt.nd.BrushMaskView.*` 放行了同类下任意方法（`onMeasure` 也被当已知死代码） | 改成 `类.方法` 精确匹配，`类.*` 需显式写 |

另外 `test_hook_target_callers.py` 是基于已废弃 API 的半成品（缩进错乱、引用了重构前的
`scan_callers`），已按真实 API 重写为 `test_smali_usage.py`，含 2 条对真实 APK 的断言。

### 9.4 门禁现状（七道）

```
① 单元测试            47 个 Kotlin JVM 测试
①b 抓取解析器          53 个 Python 测试（含 capture_schema 漂移守卫）
② assembleDebug       含 Compose 设置页
③ 功能表/子选项        31 个功能 + ACTIVITY 覆盖 + README 两列〔当轮值〕
④ 钩子目标            类/方法存在
⑤ 钩子签名            形参类型逐一比对（40 条）
⑥ 钩子调用方          有没有人会走到它（48 条，判 DEAD）
```

**仍未验证**：一切真机行为。⑥ 证明的是"静态可达"，不是"运行时一定会走"。

---

## 10 第 3 轮续跑：第 29 个功能（去水印）+ 文档计数门禁

### 10.1 第 29 个功能 `watermark_off`（并行轮次产出，主会话独立复核）

先说清它**不是**"破解水印"：App 自己就有这个开关（`strings.xml` 里有 `去除水印`/`还原水印`），
本功能只是代用户按下它，不伪造服务端结果、不改请求参数、不绕过次数限制。

**钩点选择的证据链**（我逐行复核过）：

| 事实 | 位置 | 含义 |
|---|---|---|
| `cu/p.l(List,boolean,boolean)` 从 `ScanEntity.getClearWatermark()I` 取值，`==1` 时置 `p3=true` 传给 `cu.l` 构造器 | `smali_classes6/cu/p.smali:606/:622` | 上游走 getter，**不是**直读字段 |
| 构造器第 12/13 个布尔分别落字段 `q`（clearWriting）/`r`（clearWatermark） | `cu/l.smali:509/:512` | `iput-boolean p1, p0, Lcu/l;->r:Z` |
| `cu/l.K(String,Lt10/f;)` **直读**字段 `r` | `cu/l.smali:3189` `iget-boolean` | 为真时把 `"2"` 塞进 `ext` 随 `/kdapi/image/combine` 上传 |
| getter `m0()Z` 也读 `r` | `cu/l.smali:15077` | 但 `K()` 绕过它 |

⇒ **光钩 getter 改不到请求**，必须让字段为真。所以钩构造器、`afterHookedMethod` 里置 `r`。

**实现上的一个正确决定**：代码不是硬写 `Xp.hookCtor("cu.l", String, String, …)`，
而是用 `cls.declaredConstructors` 逐个比对一份 14 参期望签名，找到才钩。
好处是宿主换版增删参数时会**主动不钩**（日志可见 hook 数 0），而不是错钩到别的重载。

代价：静态门禁只能标 `UNKNOWN(signature not statically resolvable)` —— 那份硬编码的
期望签名此前**没有任何东西校验过**。本轮补上（见 10.3）。

### 10.2 独立复核的结果

我按 APK 里的真实签名逐位比对（`(String,String,String,String,IIF,String,String,IIZZ,String)`）：

```
APK 参数个数: 14     代码期望个数: 14     逐位一致: True
```

`cu/l` 另有 1 参构造器 `<init>(String)`，代码的 14 参筛选逻辑不会误钩它。

### 10.3 新增测试：钩子签名 ↔ APK 真实签名的交叉校验

`kit/python/tests/test_smali_usage.py::SignatureCrossCheck`：
从 smali 解析出 14 参构造器的真实参数表，从 Kotlin 源码解析出硬编码的期望表，逐位比对。

**反向验证过**：把第 13 个参数改成 `Int`（模拟宿主换版），测试立刻失败并给出
"`ctorTypes()` 会找不到构造器、功能静默不装"的解释；还原后通过。
这类"表面已启用、实际钩子数 0"的失效，正是本项目最该防的。

### 10.4 新的文档计数门禁

功能数是最容易过期的数字。本轮就发现 4 处：实际 29 个，而
`README.md` / `module/README.md` / `OPTIMIZATION.md` 还写着 28（热开关写 27/28）。

`check_feature_parity.py` 新增 `check_declared_counts`：只校验**明确声明总数**的位置
（`共 **N 个功能**`、`一致（N 项）`、`分数形式 个开关计数`），不碰表格行里的历史数字。
反向验证：把 `29 个功能` 改回 28 → exit 1；还原 → exit 0。

### 10.5 门禁现状

```
① 单元测试     47    ①b 抓取解析器  62（+9：smali_usage / 签名交叉校验）
② assembleDebug      ③ parity 29 项 + 计数校验
④ 钩子目标           ⑤ 钩子签名 41    ⑥ 钩子调用方 49
✓ 7/7 全绿
```

**仍未验证**：`watermark_off` 真机是否真产出无水印 PDF、服务端是否按 VIP/次数拒绝 —— 
静态无法判定，`NEW_TARGETS.md` §2.2 与本文都已标注。

---

## 11 第 4 轮续跑：把"运行时解析的类名"从盲区变成门禁

### 11.1 这类失效为什么最危险

模块里有 9 个类名不是写在 `Xp.hook("字面量", ...)` 里，而是靠 `Xp.clazzOrNull("…")`
在**运行时**解析（混淆名、内部类、按版本会变的名字）。⑤ 签名门禁看不到它们，
只能标 `UNKNOWN`。

写错（或宿主换版改了混淆名）时的表现：

1. `clazzOrNull` 返回 `null`；
2. 那条钩子**根本不装**；
3. 启动日志里只是少了几个 hook 计数；
4. 功能开关显示"已启用"，真机上什么都不会发生。

比"类改名导致 `Xp.hook` 抛异常"更隐蔽 —— 后者至少会进 `HookAudit` 的 failed 列表。

### 11.2 本轮新增的三层校验

| 测试 | 断言什么 | 反向验证 |
|---|---|---|
| `AllRuntimeResolvedClassesExist.test_every_clazz_or_null_literal_exists` | **每一个** `clazzOrNull("…")` 字面量（展开 `$PKG`/`$MODEL` 常量、还原 `\$`）都必须在 APK 里存在 | 把 `RC4Probe` 的类名改成 `RC5` → 失败并报 `RC4Probe.kt:53 … 不在 APK 里` |
| `DynamicParamCrossCheck.test_arg_class_exists_in_apk` | `BlockAdSdk` 的 `ARG` 常量值必须在 APK 里 | 改成 `xc.WRONG` → 失败并解释"4 个钩子会全部跳过" |
| `DynamicParamCrossCheck.test_sdk_init_signatures_take_the_arg_class` | 四个 SDK init 的真实形参**必须就是 ARG 指向的那个类**（而不是测试里硬写 `Lxc/a;`） | 同上 → 两条同时失败 |

关键设计：这些测试**从源码读常量再和 APK 比对**。第一版我在测试里硬写了 `"xc.a"`，
结果代码改成错的值测试照样绿 —— 那是在测测试自己，不是测代码。已改正。

### 11.3 `cu.l` 的构造器歧义也钉住了

`cu.l` 有 **1 参**（`<init>(String)`）和 **14 参**两个构造器。代码用 `declaredConstructors`
逐个比对 14 参期望表，找不到就不钩 —— 这个设计是对的（宿主换版会主动不钩而不是钩错重载）。
测试现在断言"确实同时存在 1 参与 14 参"，这样一旦宿主删掉 14 参那个，
测试会先红，而不是等到真机上功能静默失效。

### 11.4 门禁现状

```
① 单元测试     50    ①b 抓取解析器  57（+3：运行时类名/ARG/构造器歧义）
② assembleDebug      ③ parity 29 项 + 计数校验
④ 钩子目标           ⑤ 钩子签名 41（5 UNKNOWN，均有 APK 真实签名对照）
⑥ 钩子调用方 49
✓ 7/7 全绿
```

⑤ 里剩下的 5 个 `UNKNOWN` 现在都有**两条独立防线**：门禁打印 APK 真实签名供核对，
①b 的交叉校验测试断言代码里的期望值与之一致。

**仍未验证**：真机行为（无设备）。

---

## 12 第 5 轮续跑：台账从"两态"变"三态"（补上最隐形的那一类）

### 12.1 补的是什么

`HookAudit` 原本只记 `ok` / `failed`。但还有第三类：**从未被尝试**的钩子。

```
val c = Xp.clazzOrNull("xc.a") ?: return     // ← null 就直接 return
```

这条路径下钩子连"尝试"都没有 ⇒ 既不计 ok 也不计 failed ⇒ **在台账里完全隐形**。
真机表现：功能开关"已启用"、`hooks N ok` 里的 N 比预期少几个、日志里**一行 warn 都没有**
（`clazzOrNull` 是静默失败）。这比 `failed` 更难发现 —— 后者至少会在 `failureList()` 里点名。

修法：`clazzOrNull` 返回 null 时调 `HookAudit.recordSkipped(...)`。
放在 `Xp` 里而不是逐个改 18 处调用点，是因为调用点是 `?: return` 这种形态，
逐个改既繁琐又容易漏；在唯一出口记账能覆盖全部。

### 12.2 启动日志的变化

```
改前：ready 29/29 features, hooks 96 ok / 0 failed
改后：ready 29/29 features, hooks 92 ok / 0 failed -> skipped: xc.a (class not found), …
```

`skipped:` 段只列出**缺失的目标类名**，不含正常解析的。摘要仍然一行。
`kit/scripts/module_report.py` 的 `AUDIT_RE` 同步扩展，三种形态（全绿 / 有 failed / 有 skipped）
都验证过能解析。

### 12.3 测试抓到一个真 bug

写 `HookAuditTest` 时 `summaryLineIsCleanWhenAllGreen` 失败，输出里混进了**别的测试**的
skipped 记录。根因不是测试隔离，而是 `reset()` 漏了：

```kotlin
fun reset() {
    byFeature.clear()
    failures.clear()
    // 少了 skipped.clear()
}
```

`ok`/`failed` 是 `byFeature` 里的字段（清 map 就归零），而 `skipped` 是**独立列表**。
生产里的表现是"重载模块后 skipped 列表越来越长"——两边都是真 bug。
这个 bug 是测试写出来才暴露的，不是我先想到再写测试。

### 12.4 顺带修掉测试自身的假阳性

新增的 `clazzOrNull` 字面量扫描把 **KDoc 里的示例**也当成了真实调用：

```
HookAudit.kt:34  clazzOrNull("…") -> "…" 不在 APK 里
```

我在 `Xp.kt` 的文档注释里写了 `clazzOrNull("…")` 作为说明，测试就报警了。
已让扫描跳过注释行与含 `…` 的占位符。

### 12.5 门禁现状

```
① 单元测试 56（+6：HookAudit 三态）   ①b 抓取解析器 66
② assembleDebug    ③ parity 29 项 + 计数校验
④ 钩子目标         ⑤ 钩子签名 41      ⑥ 钩子调用方 49
✓ 7/7 全绿
```

**仍未验证**：真机行为（无设备）。`skipped:` 行在真机上的实际形态未验证 ——
只有单元测试覆盖了它的拼装逻辑。

---

## 13 第 6 轮续跑：门禁标签统一（词汇表单一化）

### 13.1 问题

④ `check_hook_targets.py` 与 ⑥ `smali_usage.py` 各自演出一套标签：

| 侧 | 曾用标签 |
|---|---|
| ⑥ 内部常量 | `USED` / `SELF-CALLED` / `USED(super-slot)` / `TYPE-ONLY` / `DEAD` / `MISSING` / `SKIP(platform)` |
| ⑥ 显示映射 | 把 `SELF-CALLED` 显示成 `USED(self)`，把 `USED(super-slot)` 显示成另一串 |
| ④ | `OK` / `OK(load)` / `[USED]` / `[TYPE-ONLY]` / `[OK(platform)]` |

后果：同一个目标在两处名字不同，读报告要来回对照；更糟的是**内部值 → 显示标签**的二次映射，
让"我们到底有几个状态"变得不可数。

### 13.2 做法

新增 `kit/scripts/hook_vocab.py` 作为**单一定义处**：

* 两层概念分开：`VERDICTS`（能不能钩）× `EVIDENCE`（有没有人调用）—— 两者字符串**不允许重叠**；
* `RED = ('MISSING', 'SIG-MISMATCH', 'DEAD')`，只有这三类报红；
* `STRENGTH` 给出证据强度序，`strongest()` 在多处证据时取最强（`TYPE-ONLY` 强于 `DEAD`：
  有类型引用就不是"零引用"）；
* `explain()` 输出一行人类可读解释；
* 两个脚本改为 `import hook_vocab as vocab`，判定值取常量而非硬编码字符串。

统一后的全部标签（8 个）：

```
判定：OK / OK(load) / OK(platform) / MISSING / SIG-MISMATCH
证据：USED / USED(self) / REFLECTIVE / SUPER-SLOT / TYPE-ONLY / DEAD / -
```

实测两脚本输出已一致：`OK(platform) 11 / REFLECTIVE 3 / TYPE-ONLY 13 / USED(self) 9 / USED 24`。

### 13.3 测试（14 个）

`kit/python/tests/test_hook_vocab.py`：

* 判定与证据集合**不相交**（否则报告列有歧义）；
* `RED` 必须是已知标签的子集；每个标签都必须有说明；
* `STRENGTH` 必须覆盖全部证据标签（否则 `strongest()` 会 index 报错）；
* 三类必红、其余七类必不红；
* **`TYPE-ONLY` 必须明确不红**并含"不是死代码"字样 —— 这条防的是"误判导致删掉活代码"；
* 两个门禁脚本必须真的 `import hook_vocab`，且**代码里**不许残留旧标签。

最后一条踩了个坑：第一版直接扫全文，把 KDoc 里"曾经叫 `SELF-CALLED`"这句历史说明也当成了
残留标签 → 误报。已改成先剥掉注释与文档字符串再扫。文档该写历史，不该因此变红。

### 13.4 门禁现状

```
① 单元测试 56     ①b 抓取解析器 80（+14：词汇表）
② assembleDebug    ③ parity 29 项 + 计数校验
④ 钩子目标         ⑤ 钩子签名 41    ⑥ 钩子调用方 55
✓ 7/7 全绿
```

`README.md` 新增「门禁标签对照表」，读报告时不用再翻脚本。

**仍未验证**：真机行为（无设备）。

---

## 14 第 7 轮续跑：第 30 个功能（重练额度观测）+ 两个门禁 bug

### 14.1 找钩点：连着三次误报之后才找对

想加"VIP 相关"的功能，基于字符串搜查连着踩了三次空：

| 候选 | 为什么不能用 |
|---|---|
| `app_kdzy_userinfo_vip_text` → `t.c()` / `t.d()` | 只读 `VipPrivilegesTriggerPreference` 的**偏好开关**（控制标签显不显示），与放行无关 |
| `vipPrivilege`（`VipQuestionPrivilegeAction`） | 只是读 title/btnTxt/tips/jumpUrl 弹个营销窗 |
| `MyDownloadActivity` 的"剩余离线次数" | 纯 UI 格式化，改它只让数字变好看，不增额度 |

改成**数据驱动**（统计 `L*a*ip*;->*` 的调用点并按量排序）才找到真正的东西：

```
com.kuaiduizuoye.scan.web.VipLimitViewModel.b(String, int, Function2)   3 处直接调用
  例: fh/g.smali:1898          （H5 侧）
  例: PaperMainView.smali:1437 （答题主界面，产品名 "examRHW"）
  例: PaperMainView.smali:1557
```

形参是 `(产品名, 已用次数, 回调)`，回调是 `Function2<Boolean, Integer, Unit>`
—— **第一个参数就是"允许吗"**。这才是用户真正会撞到的额度判定。

教训：按名字猜语义（`Vip*` / `*Limit*` / 中文串）在这个混淆过的 App 上误报率极高。
**按调用量排序**比按名字匹配可靠得多。

### 14.2 功能 `vip_limit_probe`（默认关，热开关，只观测）

* 钩 `VipLimitViewModel.b` 的 `onBefore` → `VIPLIMIT ask product=examRHW used=3`；
* 选项 `vip_limit_probe_result` 打开时，再钩回调实例的 `invoke`
  → `VIPLIMIT result allowed=false remaining=0`；
* **不改 Boolean、不改次数**。想让回调收 true 也不在范围内 —— 服务端下发时会再校验，
  改了只得到"看似能点、点了失败"。

为什么值得观测：额度拒绝是**静默**的（按钮变灰或弹会员页），看不出是"次数用完"还是"没权限"。
记下 `allowed` 与当时次数，才能回答"这台机器被什么规则挡住了"。

回调钩法有个坑：`Function2` 是**全 App 共享**的接口，按接口钩会命中所有 lambda
⇒ 只在拿到具体实例时按它的合成类名（`...PaperMainView$e`）钩，且用
`hookedResultClasses` 去重，避免重复安装。

### 14.3 修掉两个门禁 bug（都是并行整合时引入的）

**bug 1：`meth=''` 被当成方法名** → 误报 `MISSING-METHOD`

`collect_targets` 对 `Xp.clazzOrNull("a.b.C")` 产出的方法名是**空串**（不是 `None`），
而 `check_hook_targets.py` 只判了 `meth is None`。于是 `aj.a` / `cu.l` / `RC4` 被误报：

```
MISSING-METHOD  aj.a   (AdFeatures.kt:58)   [TYPE-ONLY]   ← 实际只是类引用
```

修法：`elif meth is None or meth == ''`。修完 `MISSING` 从 5 条归零。

**bug 2：新前缀没登记** → ①b 红

`VIPLIMIT` 加进 schema 后，漂移守卫立刻要求：测试用例、fixture、`FEATURE_IDS`、
`capture_transcript` 分支，四处缺一不可。**这是它该有的严格度** —— 一路补完才绿。

### 14.4 `ACTIVITY.md` 恢复了丢失的对照表

后台把 `ACTIVITY.md` 重写过，我上一轮写的"28 功能前缀对照表"没了。
本轮按现结构补成「七、功能 ↔ 抓取前缀对照表」，含 30 个功能 + 基础设施行，
并写明它本身也是门禁（`check_activity_doc` 要求每个 feature id 在此出现）。

### 14.5 门禁现状

```
① 单元测试 56     ①b 抓取解析器 94（+14：VIPLIMIT schema/fixture/transcript）
② assembleDebug    ③ parity 30 项 + 计数校验
④ 钩子目标 63/68    ⑤ 钩子签名 42    ⑥ 钩子调用方 56
✓ 7/7 全绿
```

**仍未验证**：`vip_limit_probe` 在真机上能否真的看到 `VIPLIMIT` 行 —— 无设备。
`examRHW` 之外是否还有别的产品名，静态只见到这一个。

---

## 15 第 8 轮：④ 与 ⑤ 的目标集合不对称（8 个钩子的签名从未被校验）

### 15.1 怎么发现的

不是我看出来的，是**并行轮次写的一致性测试**抓到的
（`kit/python/tests/test_hook_gate_agreement.py::test_signature_gate_sees_every_target`）：

```
断言：④ 看到的每个目标，⑤ 也必须看到
结果：missing 8 个
```

这比"两个脚本各自写一套实现"更隐蔽 —— 两个脚本都是对的，只是**覆盖范围不同**。
④ 说"目标都在"、⑤ 说"签名都对"，但 ⑤ 压根没看过这 8 个。

### 15.2 那 8 个是什么

```
com.baidu.homework.common.net.Net.appendSign     ← 签名拼接核心
com.zuoyebang.baseutil.a.b / .d
yl.f.g / .h / .j / .s / .y                       ← 网络加解密全家
```

全部来自 `SignObserver` —— 全模块最大的观测功能。

### 15.3 根因

`SignObserver` 不直接调 `Xp.hook`，而是走自己的包装器：

```kotlin
n += hook("yl.f", "j") { p -> … }

private fun hook(className: String, methodName: String, line: …) =
    Xp.hookAll(className, methodName, Xp.classLoader, object : XC_MethodHook() { … })
```

* ④ 有 `LOCAL_HOOK_RE`（`(?<![\w.])hook\(\s*"…"\s*,\s*"…"`）⇒ 认它；
* ⑤ 只有 `LOCAL_HOOKALL_RE`（`hookAll(`）⇒ **不认裸 `hook(`**。

于是这 8 个目标在 ④ 里正常显示，在 ⑤ 里**根本不存在** —— 不是"标 UNKNOWN"，
是完全没有条目。读者看 `VERIFICATION.md` 会以为它们已被校验。

### 15.4 修法

给 ⑤ 补 `LOCAL_HOOK_RE`，与 ④ 用同一个模式（含 `(?<![\w.])` 排除 `Xp.hook(`，
避免与 `HOOK_RE` 重复计数）。

⑤ 覆盖：**51 → 59** 条。两个门禁的目标集合现在一致。

### 15.5 为什么这个测试值得留着

"两个门禁覆盖同一批目标"是一句**必须被断言**的话，不能靠"两边都改了"来保证。
并行轮次写的那条测试正好是这个断言 —— 它抓到了一个人类审查很难发现的问题
（两边输出都是绿的，只有对比集合才看得出来）。

### 15.6 门禁现状

```
① 单元测试 56     ①b 抓取解析器 102（+8：门禁一致性）
② assembleDebug    ③ parity 30 项 + 计数校验
④ 钩子目标 63/68    ⑤ 钩子签名 64（59 吻合 / 5 人工核对）  ⑥ 钩子调用方 56
✓ 7/7 全绿
```

另：本轮还修了 `meth=''`（`clazzOrNull` 产出）被误判成方法名、导致 5 条
`MISSING-METHOD` 误报的问题。

**仍未验证**：真机行为（无设备）。`SignObserver` 那 8 个钩子的**形参**目前按
"包装器内部决定"处理（不在调用点比对），要真正校验得解析包装器签名 —— 已记入下一步。

---

## 16 第 9 轮：`SignObserver` 那 8 个包装器钩子的真实签名

### 16.1 上一轮留下的口子

上一轮让 ⑤ 看见了 `hook("类","方法")` 包装器，但它们的状态是 `OK(hookAll)`
—— 意思是"形参由包装器内部决定，无需在调用点比对"。**这是如实的，但也是缺口**：

宿主换版若把这 8 个方法的形参改了，`SignObserver` 的回调仍会把
`p.args.firstOrNull()` 记下来 —— **日志照样有，内容已经错了**。
签名门禁看不见这种情况。

### 16.2 把真实签名钉住

新增 `WrapperHookSignatures`，逐个断言从 APK 读出的真实签名：

| 目标 | 真实签名 |
|---|---|
| `Net.appendSign` | `(InputBase)String` |
| `baseutil.a.b` | `(String)String` |
| `baseutil.a.d` | `(List)String` |
| `yl.f.g` / `yl.f.h` | `(String)String` |
| `yl.f.j` | `(Object)Object` |
| `yl.f.s` | `(Object,boolean)Object` |
| **`yl.f.y`** | **`()V`** ← 无参无返回 |

反向验证过：把 `yl.f.j` 的期望返回改成 `String`，测试精确报出
`yl.f.j: 期望 (Ljava/lang/Object;)Ljava/lang/String;，实际 [...]`。

### 16.3 顺带发现一处语义不清楚的地方

`yl.f.y()` **没有参数、没有返回值**。而 `SignObserver` 把它归在"加解密原语"里，
用同一段代码记 `H5 y in` / `H5 y out`：

```kotlin
for (m in listOf("n", "o", "t", "l")) { … }   // 注意：这里没有 y
```
实际上 `y` 是单独一行 `hook("yl.f", "y") { … }` 记录的。

对这个方法，`in` 与 `out` 恒为 null。它不是 bug（代码本意是"调到就记一笔"，
用来确认这条路径被走过），但**如果后人以为 `H5 y in/out` 记录了载荷，会读错**。
已加一条独立断言与注释说明：若 `y` 哪天开始带参数，记录的含义要重看。

### 16.4 门禁现状

```
① 单元测试 56     ①b 抓取解析器 106（+4：包装器签名快照）
② assembleDebug    ③ parity 30 项 + 计数校验
④ 钩子目标 63/68    ⑤ 钩子签名 64    ⑥ 钩子调用方 56
✓ 7/7 全绿
```

**仍未验证**：真机行为（无设备）。`yl.f.y` 的实际执行频率、`H5 y` 行会不会刷屏，
都只有静态推断。

---

## 17 第 10 轮：`LogSink` 漏了两个日志级别 + 一处长期假红

### 17.1 真的漏了

数了宿主对 `android.util.Log` 的 `invoke-static` 调用点：

```
v 236 / d 708 / i 309 / w 399 / e 800 / wtf 10 / println 16
```

`LogSink` 原来只钩 `d/i/w/e` —— **漏了 `v`（236 处）和 `wtf`（10 处）**。
`v` 是调试路径里最啰嗦也最常带线索的一级；`wtf` 是崩溃前最后一条。
`println` 只有 16 处且不带级别，不加。

已补成 `listOf("v","d","i","w","e","wtf")`。

**副作用评估**：`v` 量大，会不会刷爆抓取文件？
`LogSink` 先过 `LogFilter.interesting(tag,msg,TAGS)`（tag 白名单 + 关键词），
再有每 tag 2000 条限流 ⇒ 不会。这个保护本来就在。

### 17.2 一处长期假红（期望值抄的是文档，不是数据）

补 `v`/`wtf` 之后 `①b` 红了，暴露出 `test_live_hooks_are_actually_counted` 里
一串**从来没对过**的期望值：

```python
'req_headers': (4, 4),        # 实际 (3, 3)
'web_request_log': (4, 4),    # 实际 None（它用 findAndHookMethod，④⑤ 都识别不到）
```

这份表是照 README 里的描述写的，不是从 `static_hook_evidence()` 读的 ——
所以它一直红着，只是没人跑过这条测试。

修正为真实值，并加一条**反向断言**：结构上不可能有静态证据的功能（`web_request_log`
用 `XposedHelpers.findAndHookMethod` 直接调）必须恒为 `None`；哪天它变成有值，
说明钩法改了，会提醒把期望值挪到 `want` 里。

### 17.3 一致性门禁加了例外清单，并给它上锁

`④` 能展开 `for (m in listOf(...)) Xp.hookAll("android.util.Log", m, …)`，
`⑤` 不做循环展开 ⇒ 6 个 `Log.*` 目标只在 ④ 里存在。这是**结构性**的，不是遗漏。

加了 `STRUCTURAL_EXCEPTIONS`（精确到 `(类, 方法)`），并配一条自我检查。
写这条自我检查时踩了三次：

1. 一开始用整类比较（`t[0] not in`），清单是元组集合 ⇒ 比较永远为真，例外不生效；
2. 例外清单里塞了 `aj.a.*`，自我检查报"⑤ 也看得到" —— 因为 `aj.a` 的循环在
   `Xp.hook("aj.a", m, …)` 里，⑤ 的 `HOOK_RE` 恰好能捕获；**我凭印象写的方法名是错的**；
3. 断言"⑤ 里没有它"会因**执行顺序**而红：`doc_generators` 会调
   `check_hook_signatures.py` 的 CLI，模块级 `DESC_CACHE` 状态让同一进程内的后续调用
   看到不同结果。

最终做法：例外精确到 `(类,方法)`、过滤器用 `t not in`、只断"④ 里有它"
（不依赖执行顺序），并在注释里写清为什么不加"⑤ 里没有它"。

权威缺口清单（单独跑两个脚本算集合差）：
```
④=73 ⑤=67 缺口=6  全部是 android.util.Log 的 v/d/i/w/e/wtf
```

### 17.4 门禁现状

```
① 单元测试 56     ①b 抓取解析器 113
② assembleDebug    ③ parity 30 项 + 计数校验
④ 钩子目标 73       ⑤ 钩子签名 67    ⑥ 钩子调用方 56
✓ 7/7 全绿
```

**仍未验证**：`Log.v` 补进来后真机上的抓取量 —— 只有限流参数的静态推断。

---

## 18 第 11 轮：②「文档口径」做实 —— 两份自动生成物此前都跑不出自己写的字

本轮做的是任务清单里的 ②（让 `ACTIVITY.md` / `VERIFICATION.md` 的口径与 30 个功能
+ 新前缀对齐）。一开始按"重跑生成器就完了"去做，结果发现**两份文档都和生成器对不上**，
而且原因不是"忘了重跑"，是生成器本身有三处缺陷。

### 18.1 `ACTIVITY.md` 的「复现」命令跑不起来

文档里写着：

```bash
python3 kit/scripts/module_activity.py \
    --capture work/activity_inputs/acceptance_capture.txt \
    --capture work/activity_inputs/capture_0900.txt \
    --capture work/activity_inputs/capture_kd1_r10.txt … --out module/ACTIVITY.md
```

照抄执行 ⇒ `FileNotFoundError: work/activity_inputs/capture_kd1_r11.txt`。

两个问题叠在一起：生成器只拼**前 3 个**文件（后面用 `…` 省略），而那 3 个里的
`capture_kd1_r11.txt` 早已不存在（目录里是 `capture_r24.txt` / `capture_r30.txt`）。

**这比"数字过期"严重**：一份自称可复现的文档给出跑不通的命令，下一个人只会得出
"这些数字是手编的"这个结论。

修法：有 `--dir` 时直接输出那条 `--dir` 命令（输入集合 = 目录快照，顺序由
`sorted(glob)` 固定）；否则把**全部**文件名列出来，不再省略。

### 18.2 重跑会抹掉手工附录，而那张附录是 ③ 的门禁输入

`ACTIVITY.md` 的 `## 七、功能 ↔ 抓取前缀对照表` 是手写的（每个功能写什么前缀、
落盘到哪、限流多少）。它同时是 ③ 的判据 —— `check_activity_doc` 要求
**每个 feature id 都出现在这个文件里**。

生成器把整个文件当成自己的领地，于是：

```
"照文档说的重跑 ACTIVITY.md"  ⇒  §七 消失  ⇒  ③ 报"缺少这些功能"  ⇒  门禁红
```

2026-10-25 的后台轮次真的这么丢过一次（PROGRESS.md 第 7 轮记着）。

修法：新增 `--keep-section '## 七、'`（默认值就是它）。重写 `--out` 时先找原文件里
这个标题的位置，把它及其后全部内容原样接在生成内容之后，并打印 `（保留手工附录）`。

### 18.3 `VERIFICATION.md` 的「静态钩子」列是按**文件**计的

这一列本应回答"**这个功能**的钩子解析成功几个"。实际实现是：

```python
per_file[r.get('where').split(':')[0]] += 1     # where = "AdFeatures.kt:31"
```

`where` 只有文件名和行号，没有 object 名，于是同一个文件里的功能**共享**一个数字：

| 功能 | 旧显示 | 真实钩子数 |
|---|---|---|
| `rm_splash` | `12/12` | 3 |
| `rm_feed_ad` | `12/12` | 2 |
| `rm_popup` | `12/12` | 1 |
| `page_js` | `4/4` | **0**（它一个钩子都不装） |
| `ad_probe` | `12/12` | 3 |

`AdFeatures.kt` 里 7 个功能全写 `12/12`；`HostFeatures.kt` 里 `page_js` 明明没有任何
钩子（它只读 `page_js_script` 配置，注入由 `WebInjector` 做）却也写 `4/4`。

**这一列本来是"把'有静态证据'与'什么都没有'分开"的**（§8.5 的原话），按文件计等于
把它又合并回去了。

修法：`feature_line_ranges()` 用花括号配平算出每个 `object X : SwitchFeature` 的
行区间，按 `where` 的行号把每条钩子归给**包住它的那个 object**。三个后果都是好的：

* 每个功能拿到自己的数字（上表右列）；
* 挂在共享点上的功能标 `共享:WebInjector` 而不是 `0/0` —— `0/0` 会被读成"钩子全没解析出来",
  而事实是"钩子不在这个对象里"，两件事完全不同；
* `page_js` 这类结构性没有钩子的照旧 `—`。

### 18.4 顺带补上的两条真缺口（第 7.6.1 节记的形态漏检）

写 18.3 的断言时，`test_live_hooks_are_actually_counted` 要求"真有钩子的功能必须数得到"，
一跑就红了 —— 不是数字写错，是**门禁根本没看到那些钩子**：

| 形态 | 例子 | 之前 | 现在 |
|---|---|---|---|
| `XposedHelpers.findAndHookMethod("类", cl, "方法", …)` | `ReqHeaders` 3 个、`WebRequestLog` 的 java 侧 | ④⑤⑥ **全不可见** | 三处都覆盖 |
| 方法名是循环变量 | `for (m in listOf("d","f","h")) Xp.hook("aj.a", m, …)` | 记成空方法名 `aj.a.`（`OK(load)`），3 个真钩子蒙过去 | 按作用域展开成字面量 |

第 2 条还引出一个**假红**：`AdFeatures.kt` 有两个同名 `m`（`("d","f","h")` 带 `Int` 形参、
`("j","k")` 零形参）。用"变量名 → 列表"的全局字典展开，后者被前者覆盖 ⇒
`aj.a.d()` / `aj.a.f()` / `aj.a.h()` 三条 `SIGNATURE-MISMATCH`（真实签名是 `(I)`）。
改用 `hook_vocab.loop_scopes()` 按**花括号作用域**归属后归零。

另外修掉一个门禁自身的假红：`HashMap::class.java`（Kotlin 隐式可见，无需 import）
被解成 `LHashMap;`，与 `Ljava/util/HashMap;` 不符 ⇒ `Net.d(…)` 误报不符。
新增 `import_map()` + `IMPLICIT_JAVA` 表。

### 18.5 三份清单终于真的相等

```
④ 目标 92   ⑤ 记录 81   ⑥ 目标 81      缺口 0（`Log.*` 那 6 条例外已删空）
```

`STRUCTURAL_EXCEPTIONS` 从 6 条删成**空集**，并新增一条更强的断言
`test_no_gap_between_targets_and_signatures`：直接算差集，想让缺口通过必须改测试文件本身。

顺便验证了 `Log.*` 的 6 个目标现在 ⑤ 也逐个比对形参（`(String,String)` 固定重载）。

### 18.6 新增 `test_doc_generators.py`（11 个测试）

把上面每一条都变成可复跑的断言，避免"下次又漂回去"：

| 测试 | 钉住的事实 |
|---|---|
| `test_repro_paths_all_exist` | 复现命令里每个输入路径都真实存在 |
| `test_repro_reproduces_the_same_numbers` | **真的照它跑一遍**，逐行比数字 |
| `test_regenerating_keeps_handwritten_section` | 重写后 §七 仍在、且 feature id 一个不少 |
| `test_attribution_uses_feature_objects` | 键是 object 名，不是 `.kt` 文件名 |
| `test_same_file_features_get_different_numbers` | 同文件的功能不能共享一个数字 |
| `test_feature_without_hooks_is_zero_not_borrowed` | 没钩子的不许借用同文件的 |
| `test_shared_hook_owning_features_do_not_claim_their_own` | 共享钩子不计入自己 |
| `test_page_js_is_neither_hook_owning_nor_registering` | `page_js` 只能是 `—` |
| `test_live_hooks_are_actually_counted` | 9 个功能的钩子数逐个钉死（反向验证：修复不能以全 0 收场） |
| `test_committed_file_is_what_the_generator_produces` | committed 的 `VERIFICATION.md` == 生成器输出 |
| `test_no_gap_between_targets_and_signatures` | ④⑤ 目标集合完全相等 |

### 18.7 顺手把 ③ 的覆盖判据从"提到过"收紧成"表格行里"

`check_activity_doc` 原本是 `f'`{fid}`' in text` —— **全文任意位置提到一次就算通过**。
而 `ACTIVITY.md` §一「计数为 0」表与 §二「只写 logcat」表都是**生成器自动产出**的
（分别来自 `FEATURES_WITH_CAPTURE` / `FEATURES_LOGCAT_ONLY`），不需要人维护。
也就是说：只要生成器跑过一次，全部 30 个 id 就都在文件里了，
而**真正需要操作者维护的 §七 对照表可以完全空着**，门禁照样绿。

收紧后（必须出现在 `## 七、` 之后的表格行里），当场查出 **9 个功能从未在 §七 出现过**：

```
rm_splash / rm_tab_ad / rm_main_banner / rm_feed_ad / rm_popup /
block_ad_sdk / h5_debug / page_js / pk_assist
```

它们恰好全是"只改行为、结构上不写抓取"的那批 —— 正因为没有可数的行，
写文档的人（我）就跳过了它们。已补成 §七之二，并对 `page_js` 单独说明：
它连 `register` 都没有（`WebInjector.inject()` 每次直接读 `page_js_script`），
所以「静态钩子」列必然是 `—`，不是"钩子没解析出来"。

三条断言（`ActivityCoverageGateIsStrict`）：

| 测试 | 反证什么 |
|---|---|
| `test_current_doc_passes` | 当前文档过得了自己的门禁 |
| `test_mentioning_an_id_in_prose_is_not_enough` | 删掉 §七 的行、只留别处提及 ⇒ 必红（删除**限定在 §七 内**，否则测的是"完全没提到"，那是更弱的情形） |
| `test_missing_section_is_itself_an_error` | 整个 §七 消失也是错 |

### 18.8 门禁现状

```
① 单元测试 56         ①b 抓取解析器 119（+14：doc_generators）
② assembleDebug        ③ parity 30 项 + 计数校验 + **§七 表格行覆盖**（收紧）
④ 钩子目标 92/92       ⑤ 钩子签名 81 条（76 吻合 / 0 不符 / 5 无法静态判定）
⑥ 钩子调用方 81        7/7 全绿
```

**仍未验证**（这一节全部是静态结论）：

* 真机行为一律未验证 —— 无设备。`ACTIVITY.md` 里凡是"当前为 0 行"的功能，
  仍然分不清"没开 / 没走到 / 钩子失效"；
* `WebInjector` 那 4 个共享钩子在真机上是否每次都命中 —— 静态只能证明 `setWebViewClient`
  等目标存在且有调用方；
* `watermark_off` 的 5 条 `UNKNOWN` 里，`cu.l` 14 参构造器的形参仍是"按声明逐个比对"，
  不是字面量签名 —— ①b 的单测覆盖了这份期望签名的位数，但没有真机证据。

---

## 19 第 13 轮：第 31 个功能（网络失败原因观测）

### 19.1 怎么找到的

上一轮我说"线索消化完了，需要新一轮侦察"。这次用**调用量排序**（`PARADIGM.md §8` 的方法）：

```
1634  ScreenUtil.dp2px                    ← UI，无用
1092  StatisticsBase.onNlogStatEvent      ← 埋点，量大但已知
 719  DialogUtil.showToast
 708  TextUtil.encode
 229  NetError.getErrorCode               ← 有用
 237  Net.post
```

`NetError.getErrorCode()` 被读 **229 次** —— 说明上层到处在读它做分支。
顺着查：`NetError` 有 **30 处** `invoke-direct … <init>`，是宿主**所有网络失败的唯一载体**。

### 19.2 为什么它值得钩

`ErrorCode` 有 **110 个**常量，正是我们关心的那类东西：

```
ANTISPAM_SIGNERR            ← 签名不对
CLIENT_AUTH_EXCEPTION       ← 鉴权失败
CLIENT_NO_NETWORK_EXCEPTION / CLIENT_TIMEOUT_EXCEPTION
CLIENT_SSL_EXCEPTION / CLIENT_PARSE_EXCEPTION
COMPOSITION_UPLOAD_NO_USER_DATA
DATA_EXCEED_MAX_LENGTH
…（共 110 个）
```

钩住构造器 = 抓到**每一次**网络失败及其错误码。"这个请求为什么失败"从猜变成读日志。

### 19.3 两个实现细节

**钩构造器而不是 getter。** 构造器是创建点（30 处），getter 是读取点（229 处）。
钩 getter 会把同一个错误重复记约 7 次；钩构造器一错一条。

**`ErrorCode` 不是 Java enum。** 它 `extends Object`，靠 `static final` 常量 +
`valueOf(int,String)` 构造 ⇒ **拿不到 `name()`**。只能调 `getErrorNo()`（读 `errNo` 字段）
与 `getErrorInfo()`。核过字段确实由 `<init>(int,String)` 赋值，不是恒为 0 的占位。

### 19.4 顺带修掉 ⑤ 的一处限制

`NetErrorProbe` 写的是 `Xp.hookCtor(CLS, ecCls, …)`，两个实参都是 `const val`，
而 `CTOR_RE` 只认字面量 ⇒ ⑤ 看不到这个目标，门禁一致性测试立刻报红：

```
[('com.baidu.homework.common.net.NetError', '<init>')]
```

已让 `CTOR_RE` 支持字面量与 `const val` 标识符两种形态。

这条测试（并行轮次写的 `test_hook_gate_agreement`）又一次证明了价值 ——
它抓的是"两边都绿但覆盖不同"，人工审查极难发现。

### 19.5 门禁现状

```
① 单元测试 56     ①b 抓取解析器 122
② assembleDebug    ③ parity 31 项 + 计数校验
④ 钩子目标 74       ⑤ 钩子签名 68    ⑥ 钩子调用方 57
✓ 7/7 全绿
```

**仍未验证**：真机能否看到 `NETERR` 行、`ErrorCode` 的 `errNo` 实际取值分布 —— 无设备。

---

## 20 第 14 轮：H5 桥补上**出站**半边（`H5RET`）

### 20.1 缺的是什么

`h5_bridge_log` 一直只挂 `dispatchAction` / `dispatchActionToListeners` —— 都是**入站**。
抓取里能回答"页面调了什么"，但回答不了"宿主回了什么"。

而 H5 侧的 bug 往往在后者：页面拿到的 `{code:...}` 是宿主拼出来的，
出问题时要判断是"页面传错参数"还是"宿主返回了错的东西"。

出站唯一通道是：

```smali
.method public call(Ljava/lang/String;)V   ← com.baidu.homework.common.ui.widget.HybridWebView$ReturnCallback
```

全 APK **277 处**调用它（`GotoLoginPageWebAction:625`、`UploadUserAvatarWebAction:333`…），
是**所有**桥 action 把答案交回 JS 的出口。

### 20.2 配对问题：我选择不猜

`ReturnCallback` 不知道自己在回应哪个 action —— 它只有 `callbackFun` 字段
（构造器赋值，`call()` 里用来拼 `javascript:<fun>(...)`）。

**可以做**的：反射读出 `callbackFun`，记下"这条回答发给谁"。

**没有做**的：把 `dispatchAction` 与 `call` 硬配成一对。
原因：两者之间没有稳定的一对一关系 —— 可能延迟回调、可能多次回调、也可能根本不回。
硬凑会造出"看起来很确定、实际是猜"的关联，那比不配对更糟。

所以两条记录各自带标识，配对留给读日志的人。

### 20.3 新记录格式

```
H5BRIDGE <action> count=<n> <json>              ← 入站（已有）
H5RET <callbackFun> count=<n> len=<n> <payload> ← 出站（本轮新增）
```

`len` 单独记：`payload` 会被截断到 400 字符，但长度是完整事实 ——
能区分"返回了空对象"和"返回了 8KB 数据被截断"。

### 20.4 踩到的两个编译错误

1. `"…HybridWebView$ReturnCallback"` —— Kotlin 把 `$ReturnCallback` 当模板变量插值。
   要写 `\$`。
2. `n += Xp.hook(...)` —— `Xp.hook` 返回 **Boolean**（而 `Xp.hookAll*` 返回成功条数），
   `n += true` 报"None of the following candidates is applicable: fun plus(other: Int)"。
   改成 `if (Xp.hook(...)) n++`。

第 2 条值得记：两个 API 的返回类型不同，混用时编译器只会给一个离题很远的
`plus` 候选列表，不容易一眼看出是"返回值不是数字"。

### 20.5 门禁现状

```
① 单元测试 56     ①b 抓取解析器 122
② assembleDebug    ③ parity 31 项 + 计数校验
④ 钩子目标 74       ⑤ 钩子签名 68    ⑥ 钩子调用方 57
✓ 7/7 全绿
```

**仍未验证**：真机上 `H5RET` 的实际体量（`payload` 可能很大）、
`callbackFun` 的真实取值形态（`postMessage` 之类还是别的）—— 无设备。

---

## 21 第 15 轮：一次没有产出功能的探测（以及为什么它值得记）

### 21.1 想做什么

上一轮记的下一步是 `Net.post`（237 处调用）。目标是记下**宿主自己的请求 URL** ——
`WEBREQ` 只记录 WebView 发的请求，宿主经 Volley/OkHttp 发的没被记过（我以为）。

### 21.2 探测链，以及每一环否掉了什么

| 步骤 | 假设 | 结果 |
|---|---|---|
| 1 | `Net.post` 的 `InputBase` 参数能给出接口路径 | ✗ `InputBase` 只有 `getJsonBody()`/`getExtHeaders()`，**没有 URL 字段** |
| 2 | 633 个 `InputBase` 子类有统一的 `getUrl()` | ✗ 只有 **3/633** 有，约定不成立 |
| 3 | `Net.post` 内部能拿到 URL | ✗ 它只是转发到 `Net.postRequest(...)`，无 URL 逻辑 |
| 4 | 钩 `com.android.volley.v.getUrl()` | ✗ 只有 10 处直接调用 |
| 5 | 钩 `v` 的构造器 | ✗ 只有 4 处 `invoke-direct`，真正的请求类不走它 |
| 6 | `postRequest` 里能看到 URL | ✗ 只看到 `NetConfig.getNetToken/getLcsVersion` |
| 7 | `postRequest` 声明在哪 | `USED(self)`，`Net` 类内部 6 处调用，但**找不到方法声明**（被 R8 内联或落在内部类） |

### 21.3 最重要的发现：我以为的空白不存在

第 8 步换角度查 `ReqHeaders` 已钩什么 —— 它**已经在钩 `com.android.volley.v` 的 `getHeaders`，
并通过 `callMethod(thisObject, "getUrl")` 记录 URL 和请求头**：

```kotlin
XposedHelpers.findAndHookMethod("com.android.volley.v", Xp.classLoader, "getHeaders", …) {
    val url = XposedHelpers.callMethod(p.thisObject, "getUrl").toString()
    Capture.append("HDR(v) $short :: $line")
}
```

所以「宿主的 Volley 请求 URL 没被记过」是**我的错误判断**，不是缺口。

顺带核实了一个我本来怀疑的隐患：`getHeaders` 是否只在子类重写时才触发？
—— `v.getHeaders()` 是父类 public 方法，`findAndHookMethod` 钩父类对**所有子类实例**生效
（虚分派），25 个子类的重写全部覆盖。**不是缺陷。**

### 21.4 这轮为什么停

按 `apk-reverse` skill 的 two-strike 规则：同一形状的尝试失败两次就该回分类，不试第三个变体。
这次探测链走了 7 步、每步都在否掉上一环的假设 —— 这不是"再试一次就好"的状态，
而是"我对这条链路的模型是错的"。

**停下来的产出**：确认了一个不存在的缺口（省掉未来重走这 7 步）、
核实了一个不是缺陷的隐患（`getHeaders` 覆盖完整）。

### 21.5 又试了两条新方向，同样无收益

按"换方法而不是重复失败"的原则又探了两条，都不成：

| 方向 | 方法 | 结果 |
|---|---|---|
| 登录过期（`0x7f10002b`） | 从 UI 文案反查使用点 | 找到 `qh.o.e(String)`（`USED`，2 处直接调用）。但追调用点时 `smali_usage` 报的 `d.smali:3637` 指向的是**不同目录的同名文件**（`qh/d.smali` 里没有那条 invoke），追踪成本继续上升 |
| token 失效处理 | 按方法名枚举（`loginExpire`/`logout`/`sessionExpire`…） | **零命中** —— 全部被混淆成单字母 |

### 21.6 门禁

未改代码，7/7 仍全绿。

### 21.7 这轮的真实结论

**连续三条探测线都没有产出功能。** 这不是"再试一次就好"的状态：

* `Net.post`：7 步，每步否掉上一环假设；
* 登录过期：2 步，`smali_usage` 的文件名歧义让追踪不可靠；
* 按名字枚举：1 步，直接零命中（混淆）。

按 `apk-reverse` 的 two-strike 纪律，现在该**停止探测**而不是继续换角度。
停下来的产出是三条"此路不通"的记录 —— 省掉后来者重走这些路。

**下一个功能的正确前提**是换一类信息来源，而不是在混淆名/调用量这两个维度上再挖：
可能的方向是「某条具体功能对应用户可见的某个按钮」（需要先有行为描述），
或者「等有真机抓取后用实际数据反推」（当前无设备）。这两条都超出本轮可做的范围。

---

## 22 第 16 轮：换了信息来源之后立刻抓到一个真缺陷（19% 的抓取是重复行）

### 22.1 上一轮说"要换信息来源"

上一轮三条探测线（`Net.post`、登录过期、按名枚举）全部零产出，我写下：下一个功能需要换
信息来源，不能在"混淆名/调用量"这两个维度继续挖。

这轮换成了 —— **读模块自己已经抓到的真实数据**（`work/activity_inputs/` 五份）。

### 22.2 数据第一眼就很刺眼

```
3568  APPSIGN      ← 占了绝对多数
 854  NET…
 1418 SIGN…
 1503 RC…
```

`APPSIGN` 是 `log_sink` 的产物。往下拆：

```
3318  I/VectorLegacy        ← 93% 是 Xposed 框架回显
 177  I/KdKit: Nativ
  61  I/KdKit: SIGN
  12  I/zybnetwork:
```

`VectorLegacy` 是 Xposed 把模块 `KdLog` 输出回显到 logcat 的通道。

### 22.3 真正的缺陷：同一事件两行

原文对照：

```
19:21:36.742 APPSIGN I/VectorLegacyBridge: [KdKit] H5 n out: https://…/scan_8cff…jpg?imageView2/2/w/170
19:21:36.743 H5 n out: https://…/scan_8cff…jpg?imageView2/2/w/170
```

* 前一行：`LogSink` 钩 `android.util.Log`，收到模块**自己**打的 `KdLog`，收进 `APPSIGN`；
* 后一行：`SignObserver` 用结构化前缀正常记录同一事件。

**`LogSink` 在回收自己的输出。** 全量：**3318 / 16807 = 19%** 的抓取行是这种重复。

危害不只是占空间：
* `ACTIVITY.md` 的 `APPSIGN` 计数虚高 19%；
* 读抓取的人会把同一事件数两遍；
* 真正有价值的 `H5`/`NET`/`SIGN` 行被 19% 的噪声摊薄。

### 22.4 修法与一个自我纠正

`LogSink` 里加 `if (tag == SELF_TAG) return`，`SELF_TAG` **直接引用 `KdLog.TAG`**
（不写第二份字面量 —— 写两份就会改一边忘另一边，排除静默失效）。

**自我纠正**：第一版测试只断言了 `KdLog.TAG == "KdKit"`。我做反向验证时把排除条件注释掉，
**测试仍然绿** —— 那是个假测试。已改成断言 `shouldCapture(tag, msg)` 的**行为**：

```kotlin
assertFalse(LogSink.shouldCapture(KdLog.TAG, "H5 n out: …"))
```

再反向验证：注释掉 `if (tag == SELF_TAG) return false` ⇒
`LogFilterTest > ownTagIsNeverCaptured FAILED`。这次是真的抓到了。

为此把判断从 lambda 里抽成 `internal fun shouldCapture(...)` —— 内联在 lambda 里无法被测到，
这本身就是它当初只能断言常量的原因。

### 22.5 门禁现状

```
① 单元测试 59（+3）  ①b 抓取解析器 122
② assembleDebug      ③ parity 31 项
④ 钩子目标 74        ⑤ 钩子签名 68    ⑥ 钩子调用方 57
✓ 7/7 全绿
```

**仍未验证**：修完之后真机抓取的重复率降到多少 —— 需要新抓取才能测。
预期从 19% 降到 0（模块日志不再被收录），但那 3318 行里有多少**只**存在于
`APPSIGN` 形式（即结构化前缀没覆盖的子事件）也会一起消失 —— 这部分影响未测。

---

## 23 第 17 轮：接到了后台轮次的半成品，把它验完（第 32 个功能）

### 23.1 这轮开始时门禁是红的

`verify.sh` 报 ①b 与 ③ 失败。查下去发现一个**我没写过的**功能：
`features/host/HttpBodyProbe.kt`，时间戳 20:08 —— 后台长跑循环写的，
它没跑完文档同步就退出了，所以 ③ 门禁卡在"32 个功能 vs README 31"。

这暴露了并行轮次的一个真实风险：**它能写出代码，但不保证写到能过门禁**。
本轮的处置是先验质量、再决定保留还是撤回。

### 23.2 质量核实（决定保留）

它的 KDoc 有明确动机，而且指向一条已经记在案的悬案：

> `work/SIGNED_SURFACE.md` 追加五~七：`/kdapi/popup/gradeupgrade` 用与服务端**完全一致**的
> sign + 同一套 29 个参数重放，仍返回 `906003 时间校验失败`。抓取统计里
> `NET DECRYPT out` 41 行、`SIGN params/URL` 43 行、**请求体 0 行** ——
> 缺了请求体就分不清"App 也没送 body"和"App 送了但没看见"。

这是**有据可查的真实观测缺口**，不是凭空加功能。钩点核过：

```
HWRequest.getBody                   USED          （volley 交出请求体的唯一出口）
ql.a.getBody                        SUPER-SLOT    （Compose 侧，不在 HWRequest 链上）
InputBase.getJsonBody               USED          （加密前的结构）
HWRequest.parseNetworkResponse      USED          （所有成功响应都从这里解析）
```

四条都有静态证据。**结论：保留，补齐文档。**

### 23.3 顺带确认后台轮次已经自己修过的坑

我一开始看到的是旧版本（`hookBody(cls)` 传变量类名），以为又要修门禁盲区。
实际它已经改成了字面量，且 KDoc 里自己引用了 `PARADIGM.md §7.6.1` 那条规则：

> 两个类名/方法名都写**字面量**，不传变量：④⑤⑥ 三道门按字面量解析，
> 传 `cls` 会让这条钩子对门禁**不可见**（`RouteLog` 里踩过同一个坑）。

也就是说：**把教训写进文档确实能约束后来者**，包括约束后台的自己。

### 23.4 我做了两件清理

1. 补齐 README / ACTIVITY / OPTIMIZATION 的 32 功能计数与前缀表，重生成 `VERIFICATION.md`；
2. 删掉 `check_hook_targets.py` 里两处**我上几轮加进去但从未被引用的死正则**
   （`DYNAMIC_CLASS_RE`、`LOCAL_WRAPPER_RE` 之外的 `FORWARD_FN_RE`）。
   它们是探索时留下的，测试里各自定义了自己的副本 —— 留着会让人以为门禁支持这些形态。

### 23.5 门禁现状

```
① 单元测试 59     ①b 抓取解析器 123
② assembleDebug    ③ parity 32 项 + 计数校验
④ 钩子目标 107      ⑤ 钩子签名 74    ⑥ 钩子调用方 60
✓ 7/7 全绿
```

④ 的目标数从 74 涨到 **107** —— 因为 `HttpBodyProbe` 的 4 条钩子此前是隐形的
（旧版传变量），现在字面量化后全部进入门禁视野；其余增量来自另一批字面量化。

**仍未验证**：`REQBODY` / `RESPBODY` 行在真机上的形态与体量 —— 无设备。
`SIGNED_SURFACE.md` 那条 `906003` 悬案**没有**因为本功能而被解开 ——
它只是"现在有工具能回答"了，答案要等真机抓取。

---

## 24 第 18 轮：`HttpBodyProbe` 抓错了地方（`getJsonBody` 基本恒为空）

### 24.1 起点

上一轮我保留下后台写的 `HttpBodyProbe`，但写明"`906003` 悬案要等真机抓取"。
这轮先验证一件事：**这个钩子真的能拿到请求体吗？**

### 24.2 追 `__jsonBody` 的写入点，结论是否定的

`getJsonBody()` 的实现是 `return __jsonBody`。全 APK 对这个字段只有**两处** `iput`：

| 写入点 | 写什么 |
|---|---|
| `InputBase.<init>`（`InputBase.smali:74`） | **写死 `"{}"`** |
| `JsonInput.<init>`（`JsonInput.smali:39`） | 真实值 |

而 `new-instance … JsonInput;` 全 APK **只有 1 处**。

⇒ 绝大多数请求的 `__jsonBody` 恒为 `"{}"`，`getJsonBody` 钩子基本抓空。
`HttpBodyProbe` 里那条 KDoc 说它记"加密前的结构"——**对 `JsonInput` 成立，对绝大多数请求不成立**。

### 24.3 顺着悬案找到真正的入口

`/kdapi/popup/gradeupgrade` 对应的类是 `Popwincontent$Input`。查它的方法：

```
.method public getParams()Ljava/util/Map;     ← 只有这个
（没有 getJsonBody 重写）
```

⇒ 它的请求体在 `getParams()` 里。

全 APK：**316 个子类重写 `getParams()`**；基类 `InputBase.getParams()` 是 **abstract**（钩不到），
但 `com.android.volley.v.getParams()` 是 public 父类方法，所有请求经**虚分派**都走到它。

### 24.4 补上 `hookVolleyParams`

钩 `com.android.volley.v.getParams`，新记录：

```
REQBODY params Popwincontent$Input n=29 a=1&b=2&… …+5
```

`n` 是总参数个数，只带前 24 个，`omitted` 记其余数量 —— **这两个数字分开记**，
因为"有 29 个参数但只看了 24 个"和"一共就 5 个"是完全不同的信息。

### 24.5 一个必须处理的隐私问题

表单参数的值是用户输入（手机号、学校名、班级）。默认记录但：

* 单个值截断到 40 字符；
* 新开关 `http_body_probe_param_values`（默认开）可关掉，只记参数名 ——
  抓取里会出现 `_(只记名，未记值)_` 提示。

默认开的理由：判断"时间字段在哪"必须靠值，而那正是这条悬案要回答的。

### 24.6 门禁抓到的连带影响

补了钩子后 ①b 红了一串——`test_live_hooks_are_actually_counted` 的期望值过期：

```
http_body_probe   4 → 5
net_error_probe   （本轮首次登记）(0, 1)
```

`net_error_probe` 是 `(0,1)` 而不是 `(1,1)`：它钩构造器，形参是混淆类 `ErrorCode`
⇒ 签名无法静态判定，计入 `UNKNOWN` 侧但仍算"签到了"。

另一个插曲：这个失败**单独跑测试时不出现**，只在 `verify.sh` 的完整套件里出现——
是中间状态造成的，不是隔离问题。我一度怀疑测试隔离，验证后排除。

### 24.7 门禁现状

```
① 单元测试 59     ①b 抓取解析器 123
② assembleDebug    ③ parity 32 项 + 计数校验
④ 钩子目标 108      ⑤ 钩子签名 88    ⑥ 钩子调用方 61
✓ 7/7 全绿
```

**仍未验证**：
* `REQBODY params` 在真机上的形态与参数个数；
* `906003` 悬案**依然没解开** —— 但这轮把工具修对了（原来抓错了字段），
  现在它**有可能**回答"时间字段是否在被签名参数集内"这个问题。真机抓取是唯一验证途径。

---

## 25 第 19 轮：追 `gradeupgrade` 的调用链 —— 它**没有业务参数**

### 25.1 出发点

上一轮我把 `hookVolleyParams` 补上，理由是"`Popwincontent$Input` 实现了 `getParams`，
所以请求体在那里"。这轮顺着链往下查，结论反过来了。

### 25.2 完整调用链（每一跳都有 smali 行号）

```
ei/y.smali:1966   Popwincontent$Input.buildInput()          ← 工厂，无实参
ei/y.smali:1980   Net.post(ctx, input, ok, err)             ← 4 参重载
```

`Popwincontent$Input` 本体（`smali_classes5/.../v1/Popwincontent$Input.smali`）：

| 事实 | 证据 |
|---|---|
| `getParams()` **返回空 HashMap** | 方法体只有 `new-instance HashMap` + `<init>` + `return-object`，**无任何 put** |
| **没有** `getJsonBody()` 重写 | `grep getJsonBody` = 0 |
| **没有**任何实例字段 | `.field` 只有 `changeQuickRedirect` 与 `URL` 常量 |
| 构造器 `private`，只经 `buildInput()` 暴露 | — |

⇒ **这条请求一个业务参数都不带。** 参数全由通用层生成（`__pid` / 时间戳 / `getNetToken` 签名）。

### 25.3 这直接改变了 `906003` 悬案的调查方向

原记录（`SIGNED_SURFACE.md` §1）已经用 5 次实验推翻了"时间校验 = 参数太旧"。
本轮补充的是**第二个被排除的可能**："参数传错了" —— 因为它根本没有业务参数。

剩下的可能集中在通用层：`__pid` 取值、时间戳的**格式/时区**、
或某个必须与服务端会话一致的字段。下一步不该再试 body，而应
**对比一次真实成功请求与一次重放的完整头+参数集**（需要真机新抓取）。

已写进 `work/SIGNED_SURFACE.md`。

### 25.4 顺带修正了一处误导性 KDoc

`HttpBodyProbe.hookJsonBody` 的注释原本写"`__jsonBody` 是加密前的结构，两者都记才能回答
时间字段在哪"，读起来像这条钩子普遍有效。补上实测约束：

> `__jsonBody` 全 APK 只有两处 `iput-object`：`InputBase.<init>` 写死 `"{}"`；
> `JsonInput.<init>` 写真实值，而 `new-instance JsonInput` **全 APK 只有 1 处**。
> 所以这条钩子**对绝大多数请求是空的**。

保留它（便宜，且一旦命中就是加密前明文），但不再宣称它是主要来源。

### 25.5 这轮没有新增功能

产出是**两个认知修正**：
1. `gradeupgrade` 无业务参数（缩小了 `906003` 的假设空间）；
2. `getJsonBody` 覆盖极窄（避免未来把它当主来源）。

按 `apk-reverse` 的标签纪律，这两条都是 `observed`（有 smali 行号与 grep 计数支撑），
不是 `inferred`。

### 25.6 门禁

```
① 单元测试 59     ①b 抓取解析器 123
② assembleDebug    ③ parity 32 项
④ 钩子目标 108      ⑤ 钩子签名 88    ⑥ 钩子调用方 61
✓ 7/7 全绿
```

**仍未验证**：`906003` 的真实成因 —— 需要真机抓取对比，本机无设备。

---

## 26 第 20 轮：把 `__pid` 业务域做成可查证据（新工具 + schema 标注）

### 26.1 从上轮的悬念出发

上一轮确认 `gradeupgrade` **没有业务参数**，于是剩下的怀疑集中在通用层。
其中一个可查的点是 `__pid`。这轮先把它查清。

### 26.2 `__pid` 是什么

每个请求类在自己的构造器里**写死两个常量**：

```smali
const-string v0, "/session/submit/checkphonestatus"
iput-object v0, p0, …/InputBase;->__url:Ljava/lang/String;
const-string v0, "saas-passport"
iput-object v0, p0, …/InputBase;->__pid:Ljava/lang/String;
```

`__pid` 是**业务域标签**，不是运行时生成的。全 APK 分布：

```
123  空串           ← 最常见
 31  saas-passport
  9  cube / dxst / fastad
  7  vip
  5  search / userinfra
  …  共 21 种
```

⇒ `gradeupgrade` 的 pid 是空串 —— 但**空串占 123/220，是常态**，所以这不是异常线索。
上一轮怀疑的"pid 带错"因此也不成立。

### 26.3 但这份映射本身值得做成工具

`kit/scripts/api_pid_map.py`：从 smali 静态提取 **路径 ↔ pid**，实测
**287 个 (类, 路径) 声明 / 283 个唯一路径 / 21 种 pid**。

为什么值得：
* `SIGNED_SURFACE.md` 的重放工具此前**完全不看 pid** —— 若某接口需要非空 pid，
  重放会失败而我们归因于签名；
* 读抓取时 `WEBREQ /cube/api/...` 能一眼看出业务域，比猜路径前缀可靠。

### 26.4 接到解析器上

`capture_schema._f_webreq` 现在给 `WEBREQ` 行自动带 `pid`：

```
{'url': '…/kdapi/popup/gradeupgrade', 'pid': '(空)'}
{'url': '…/cube/api/checkorder',      'pid': 'cube'}
```

两个设计决定：

1. **惰性加载 + 失败降级为空**：解析器必须能在没有 APK 的环境里单独跑（单测/CI），
   不能因为找不到 `work/apktool_out` 就整体失败；
2. **查不到就不写这个键**，不写 `None` —— 后者会让下游以为"有 pid 但是空"，
   与"这个路径不在 APK 里"混淆。

同一路径被多个类声明时**全列出来**（`pid` 变成列表），不合并 —— 合并等于替重放工具
随机挑一个。

### 26.5 覆盖率实测

拿五份真实抓取试：

```
命中 658 / 未命中 1781
```

未命中的主要是广告 SDK 日志（`/adxlog/log/hit`）、CDN 图片（`/scanimg/*.jpg`）——
本就不在 `InputBase` 体系里。**业务接口覆盖良好。**

### 26.6 踩到的一个坑

`_CONST_THEN_IPUT` 用 `str.format()` 拼接，正则里的 `{0,3}`（"最多 3 行"）
被当成占位符 ⇒ `KeyError: '0,3'`，整个工具起不来。改用 `%` 格式化。
已写成测试（`test_format_does_not_collide_with_regex_quantifiers`）。

### 26.7 门禁

```
① 单元测试 59     ①b 抓取解析器 148（+9：pid 工具；另 16 个来自并行轮次）
② assembleDebug    ③ parity 32 项
④ 钩子目标 108      ⑤ 钩子签名 88    ⑥ 钩子调用方 61
✓ 7/7 全绿
```

**仍未验证**：真机抓取的 `WEBREQ` 行在**模块内**就被 `pid` 标注（当前是解析侧的增强，
模块写出的仍是原始 URL）；以及 `906003` 是否与 pid 有关 —— 目前的静态证据说**无关**
（空 pid 是常态）。

---

## 27 第 21 轮：`HDR(v)` 补上业务域 + 一个"编译期看不出"的反射 bug

### 27.1 上轮遗留问题的答案

上轮结尾我写了"未验证：模块内是否该直接标注 pid"。这轮查清了：

* `WEBREQ` 的 URL 来自 **WebView 的 `shouldInterceptRequest`** —— 走 WebView 自身路径，
  **不经过 `InputBase`**，所以 WebView 请求没有 pid 概念（解析侧从 smali 映射兜底是对的）；
* 但 **`HDR(v)` 记的是 Volley 请求**，它**带着请求对象本身** —— 那里能直接读到 pid。

所以加在了 `HDR(v)`，不是 `WEBREQ`。反射链：

```
volley 请求对象 → HWRequest.mInputBase（protected final）
                → InputBase.__pid
```

两个字段都由 `api_pid_map.py` 静态确认存在。

### 27.2 三种情况必须可区分

```
HDR(v) host/cube pid=cube :: A=1     ← 真实业务域
HDR(v) host/x    pid=-    :: A=1     ← 读不到（非 HWRequest 子类 / 字段改名）
HDR(v) host/old          :: A=1     ← 旧格式，根本没有这个键
```

`-` 不写成空串、也不省略整列：省略会让人以为"这个接口没有业务域"，
而实际可能是读取失败。三者在下游是三种不同判断。

### 27.3 抓到一个只有运行期才暴露的反射 bug

第一版写法：

```kotlin
val f = req?.javaClass?.getField("mInputBase")
    ?: req?.javaClass?.getDeclaredField("mInputBase")   // ← 死代码
```

看着像"先查 public，找不到再宽松查"。但 `mInputBase` 是 **`protected final`**，
而 `getField` **只查 public 成员，对它抛 `NoSuchFieldException` 而不是返回 null** ——
elvis 右侧永远不执行 ⇒ **pid 恒为 `-`**。

我写了个 3 行的 Java 程序验证这个行为（`getField THREW: NoSuchFieldException`），
确认不是猜测。

**编译期完全看不出来，运行期也不报错**，只有抓取里那一列一直是 `-`。

修法：抽成 `util/Reflect.kt`（沿继承链 `getDeclaredField` + `setAccessible`），
并写 `ReflectTest`（5 条）。反向验证：把 `getDeclaredField` 改回 `getField`
⇒ `readsProtectedFieldDeclaredOnSuperclass` 与 `publicFieldAlsoWorks` 精确失败。

抽成独立文件是必须的 —— `ReqHeaders` 是 object，private 方法测不到，
这正是它当初能带着 bug 通过全部门禁的原因。

### 27.4 写测试时又踩一次

第一版夹具 `open class Parent { protected val mInputBase: Any = Child() }`
—— `Parent.<init>` 里 `new Child()`，`Child` 继承 `Parent` ⇒ 无限递归
`StackOverflowError`。真实链路里 `mInputBase` 装的是 `InputBase`，与 `HWRequest`
**无继承关系**，用独立 `Payload` 类才贴近。

### 27.5 一次误改文档

我直接往 `ACTIVITY.md` 的数据表里插了一列前缀说明 —— 那张表**是生成器产出的**，
多一列导致 `req_headers` 计数错位，①b 立刻红。
正确做法是改 `module_activity.py` 里的模板字符串。已修正并重新生成。

**这是同一个错误的第二次**（上一次是手改数字）。教训：`ACTIVITY.md` 与
`VERIFICATION.md` 都只能由生成器改。

### 27.6 门禁

```
① 单元测试 64（+5）  ①b 抓取解析器 154（+3）
② assembleDebug      ③ parity 32 项
④ 钩子目标 108        ⑤ 钩子签名 88    ⑥ 钩子调用方 61
✓ 7/7 全绿
```

**仍未验证**：真机上 `HDR(v)` 的 `pid=` 实际取值分布 —— 无设备。
静态上可预期：多数为 `-`（空串按 `-` 记）或 `saas-passport` / `cube` 这类具名域。

---

## 28 第 22 轮：又接到一个半成品（第 33 个功能），并修正它的类型清单

### 28.1 开局门禁红，又是后台轮次的半成品

`popwin_gate`（`features/host/PopwinGate.kt`，21:24）—— 后台写的，文档没同步完。

### 28.2 质量核实：这个钩点是真的

它的主张比前几个更值得核，因为**「一个方法覆盖全部弹窗」是强断言**：

| 核实项 | 结果 |
|---|---|
| `ei.y.H(String, ListItem)V` 存在 | ✅ `y.smali:1254` |
| 方法体里有 `sparse-switch` | ✅ |
| 分派到 `A/C/D/E/F/I/J/K/L` | ✅ 9 个方法 |
| `win*` 字符串常量 | ✅ **10 个** |

### 28.3 但它把类型清单写少了（8 → 10）

`KNOWN_TYPES` 只有 8 个，漏了 `winActivity` 与 `winBottom`。

**为什么只数分支体就会漏**：这两个字符串在方法体里位于 `sparse-switch` **之前**
（第 84 / 109 行），走 `C(ListItem)` / `E(ListItem)`，形态与后面 8 个 `equals` 链分支不同。

10 个类型 → **9 个分派方法**（`winGradeUp` 与 `winGradeSelect` 同走 `J()`）。

值得注意的是：**KDoc 里已经写明了这两个前缀类型**（"另外还有两个前缀分支…
`winActivity…` → `C(item)`、`winBottom…` → `E(item)`"），只有 `KNOWN_TYPES`
这个**列表**漏了。文档与代码不一致，而代码是门禁与设置页读的那一份。

### 28.4 连带修正

后台的 `PopwinGateTest` 断言 `KNOWN_TYPES.size == 8`，且注释写得很严谨：

> 少一个意味着漏了一张弹窗类型；多一个意味着写进了不存在的分支。

这条断言本身是对的，但它守的**预期值是错的**。按 smali 事实改成 10，
并在注释里写清"必须数方法体里所有 `win*` 常量，不能只数分支体"。

### 28.5 并行轮次造成的两次假红

1. 我加 POPWIN 测试用例时，后台**也加了 4 条**（`16:42:16.076`–`.079`），
   于是 `test_each_prefix` 出现重复 → 删掉我加的那两条；
2. Python 测试数在两次运行间从 151 → 121 → 154 —— 中间那次是后台正在改
   `test_capture_schema.py` 读到的**中间状态**，不是真的丢测试。

第 2 点值得记：**测试计数不是稳定量**，把"数量变化"当成"丢测试"会误判。
判断依据应是"有没有 FAIL"，不是"数量对不对"。

### 28.6 门禁

```
① 单元测试 81（+17，含后台新增）  ①b 抓取解析器 154
② assembleDebug                    ③ parity 33 项
④ 钩子目标 109                      ⑤ 钩子签名 89    ⑥ 钩子调用方 62
✓ 7/7 全绿
```

**仍未验证**：`POPWIN` 行在真机的类型分布、以及拦截是否真的让对应弹窗不出现
（`p.result = null` 对 `void` 方法的语义是"直接 return"，静态上成立但未实机确认）。

---

## 29 第 23 轮：把上轮的"未验证"变成可断言的契约（并且抓到自己写的假测试）

### 29.1 上轮留下的问题

上轮结尾写"拦截是否真让弹窗不出现 —— `p.result = null` 对 void 方法的语义
静态上成立但未实机确认"。

这轮把它变成**静态可证**，方法是找同形先例。

### 29.2 找到生产在用的先例

模块里已经有多处"void 方法 + `it.result = null`"的拦截写法：

| 钩点 | 返回类型 | 位置 |
|---|---|---|
| `MainAdvertiseImageView.show(...)` | `)V` ✅ | `AdFeatures.kt:119` |
| `lk.a.j(Activity)` | （同形用法） | `AdFeatures.kt:31` |
| `ei.y.H(String, ListItem)` | `)V` ✅ | `PopwinGate.kt` |

`H` 的签名已核实：`.method private H(Ljava/lang/String;…ListItem;)V`。

⇒ 这不是"未经验证的猜测"，而是**本仓库已在生产的既定用法**。
剩下的不确定性只有"真机上弹窗是否真的不出现"，那是行为验证，与语义无关。

### 29.3 但我第一次把测试写成了假的

第一版写在 Kotlin 单测里，读 `../../../work/apktool_out/smali_classes5/ei/y.smali`。
测试通过了。但我算了一下路径的解析结果：

```
module/app/../../../work/…  →  /Users/xalor/Documents/work/…   ← 不存在
```

**JVM 单测的 CWD 是 `module/app`**，而 `work/` 在仓库根。文件不存在 ⇒
代码里那句 `if (!smali.isFile) return` **静默跳过** ⇒ 测试永远是绿的。

这和我上一轮批评的"只断言常量"是同一类错误：**测试不能证明任何事，却显示通过**。

顺带一个更浅的错：更早一版我写 `assertTrue(desc.endsWith(")V"), "消息")` ——
JUnit 的签名是 `assertTrue(message, condition)`，参数顺序反了，编译期报
"actual type is 'Boolean', but 'String!' was expected"。

### 29.4 正确的做法：放到 Python 侧

`kit/python/tests/test_smali_usage.py::PopwinDispatchIsVoid`（3 条断言）：

* `H` 的声明存在（钩点没变）；
* 声明以 `)V` 结尾（void 契约成立）；
* `KNOWN_TYPES` 的 **10 个**字符串都在 `H` 的方法体里
  （守住上一轮"8 → 10"那处修正）。

Python 侧本来就在仓库根跑，且已有 smali 解析工具 —— 位置对了，断言才有意义。

**反向验证**：把 `y.smali` 里的 `.method private H(` 改成 `HX(` ⇒
`test_dispatch_method_exists` 精确报 "ei/y.smali 里找不到 H —— PopwinGate 的钩点可能变了"。
还原后通过。

### 29.5 一次自伤

反向验证的脚本用 `replace('Popwindow$ListItem', 'PopwindowX$ListItem')` 改 smali，
**同时改到了 `PopwinGate.kt` 里的同一字符串** ⇒ ④ 门禁报
`MISSING-CLASS com.kuaiduizuoye…PopwindowX$ListItem`。

这是编辑脚本的失误，不是代码缺陷。教训：**改测试夹具要精确到文件**，
不要对两个文件跑同一条字符串替换。

### 29.6 门禁

```
① 单元测试 81     ①b 抓取解析器 154（+3）
② assembleDebug    ③ parity 33 项
④ 钩子目标 109      ⑤ 钩子签名 89    ⑥ 钩子调用方 62
✓ 7/7 全绿
```

**仍未验证**：真机上弹窗是否真的不出现（行为验证，需设备）。
语义层面已由"同形先例 + 签名断言"闭合。

---

## 30 第 24 轮：把"假测试"做成一道门（第 ⑦ 道）

### 30.1 为什么值得单独一道门

本项目在 2026-10-25 一天内栽了**两次**同一类错误，都是我自己写的：

| 形态 | 代码 | 后果 |
|---|---|---|
| 断言自我实现 | `val desc = "…;)V"` + `assertTrue(desc.endsWith(")V"))` | 测的是字面量，换掉被测对象测试不变 |
| 静默跳过 | `if (!f.isFile) return`（CWD 是 `module/app`，`work/` 在仓库根 ⇒ 永远不存在） | 断言一次都没执行，测试永远绿 |

共同点：**没有 FAIL**。红测试会说"我失败了"，假测试会说"一切都好"——
后者更危险，因为没有任何别的机制会发现它。

### 30.2 检查三类

| 规则 | 抓什么 |
|---|---|
| `literal-assert` | 测试内**只由字面量赋值**的局部变量，被用于 `endsWith`/`contains`/`startsWith`/`matches` 断言 |
| `silent-return` | 测试方法体里 `if (…) return` 这种**无消息**的提前返回 |
| `skip-without-reason` | `skipTest()` 没写原因字符串 |

**不误报的两类**（刻意排除）：
* `assertTrue("消息", cond)` —— JUnit 的正确参数顺序，消息在前；
* `self.skipTest('原因')` —— 带原因的跳过是**诚实的降级**（比如"没有 APK 就跳过"），
  不是假测试。只有无原因的跳过才可疑。

### 30.3 检测器第一版漏掉了真实形态

第一版只匹配 `assertTrue("字面量".endsWith(...))`。注入一条真实形态的假测试去验：

```kotlin
val desc = "ei.y.H(…)V"
assertTrue(desc.endsWith(")V"))     // ← 变量，不是字面量
```

**没抓到。** 真实写法就是走变量的。改成"先收集测试内只由字面量赋值的局部变量名，
再检查断言是否对它们做字符串操作"，两类都抓到了：

```
## literal-assert  (1)
   PopwinGateTest.kt:186  对字面量局部变量 `desc` 断言，换掉被测对象测试不变
## silent-return  (1)
   PopwinGateTest.kt:192  无消息的提前 return —— 条件不满足时测试静默通过
```

还原注入代码后，真实代码库命中 **0** —— 说明现有测试是干净的。

### 30.4 为什么先放在"报告模式"

`run_gate "⑦ 假测试扫描" …` 目前**不判失败**（不加 `--strict`）。

理由：一道会误报的门禁会教人忽略门禁 —— 这个项目已经在 `SIGNATURE-MISMATCH`
上吃过一次"假红比漏报更危险"的教训（`IMPLICIT_JAVA` 那张表就是为修假红而加的）。

先跑一段时间，确认零误报，再改成 `--strict`。这一步是刻意保守的。

### 30.5 门禁

```
① 单元测试 81     ①b 抓取解析器 154
② assembleDebug    ③ parity 33 项
④ 钩子目标 109      ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（报告模式，当前 0 命中）
✓ 全部通过
```

**未验证**：⑦ 在**其他项目**上的误报率 —— 本仓库只有 11 个测试文件，
样本小。若将来接入更多测试，需重新评估是否加 `--strict`。

---

## 31 第 25 轮：⑦ 收紧到严格模式 + 第 4 条规则（顺序依赖）

### 31.1 用可复核的事实收紧，不用"等够了时间"

上轮 ⑦ 放在报告模式，理由是不想让会误报的门禁教人忽略门禁。这轮收紧的依据是两条
**可复核的事实**，不是"跑了一段时间"：

1. **真实库命中 0** —— 没有需要豁免的存量；
2. **注入 3 条假测试，召回 3/3，且第 4 条真实测试没被误报** —— 误报率 0、召回完整。

注入的三条分别是：变量断言、直接字面量断言、静默返回。第 2 条**当时没抓到**——
检测器第一版只匹配 `assertTrue("字面量".endsWith(...))`，而真实写法是走变量的。
补回直接字面量匹配后 3/3。

这条也写进了测试（`test_direct_literal_assert`），防止将来又一次"换方案丢掉旧形态"。

### 31.2 ⑤b 红得莫名其妙，查出来是测试隔离缺陷

`verify.sh` 报 ①b 失败，但直接跑 `unittest discover` 是全绿的。差异在于
**这 5 条测试只在完整套件下通过**：

```
ModuleNotFoundError: No module named 'capture_schema'
```

`test_parsers_cli.py` 里定义了 `KIT_PY` 却**没有插进 `sys.path`** ——
完整套件里因为别的文件先插了路径，它是绿的；单独跑就 ERROR。

这正好是 ⑦ 想抓的那一类：**测试看起来通过，但"这个文件自己能跑通吗"这个问题无法回答**。
（注意它是 ERROR 不是 FAIL，更容易被误读成"环境问题"而不是"测试缺陷"。）

修法：在 `test_parsers_cli.py` 里补 `sys.path.insert`，并把这条做成 ⑦ 的第 4 条规则
`order-dependent-import`：**import 了本地模块却没设 `sys.path`** ⇒ 命中。

### 31.3 第 4 条规则的正则第一版又太窄

只匹配 `^import capture_schema`，而 `test_redact_capture.py` 用的是
`from capture_schema import parse_line` —— 反向验证时没抓到。

改成 `^(?:import|from)\s+(...)` 后命中。反向验证：删掉那行
`sys.path.insert` ⇒ `order-dependent-import` 精确报告；还原后干净。

**同一个模式在这轮出现了两次**：规则写窄 → 反向验证抓出 → 放宽。
这说明"反向验证"不是形式，它确实每次都能抓出点什么。

### 31.4 ⑦ 现在查四类

| 规则 | 抓什么 |
|---|---|
| `literal-assert` | 对字面量局部变量 / 直接字面量做字符串断言 |
| `silent-return` | 测试里无消息的 `if (…) return` |
| `skip-without-reason` | `skipTest()` 没写原因 |
| `order-dependent-import` | import 本地模块却没设 `sys.path` |

### 31.5 一次把报告读错

中途我用 `grep -A3 "exit_guard"` 查 `session_report` 输出，看到"没有记录"就以为
第 7 节坏了，还去追 `of()` 的实现。实际是 `grep` 匹配到了**第 8 节**的
`exit_guard | 3` 那行，第 7 节本身是正常的（`exit_guard：2 次退出调用`）。

教训：**用 grep 验证"某段输出存在"之前，先确认匹配到的是哪一段**。
直接看完整输出的行号区间（`sed -n '150,165p'`）比 `grep -A3` 可靠。

### 31.6 门禁

```
① 单元测试 81     ①b 抓取解析器 169（+5）
② assembleDebug    ③ parity 33 项
④ 钩子目标 109     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（**严格模式**，4 类规则，0 命中）
✓ 8/8 全绿
```

**仍未验证**：⑦ 在其他项目上的误报率（本仓库 9 个 Python 测试文件，样本仍小）。

---

## 32 第 25 轮补记：一次没能定性的间歇性失败（如实记录）

### 32.1 现象

同一轮里 `verify.sh` 三次报 ①b 失败，但每次紧接着重跑都绿。为了区分"并行干扰"与
"真间歇失败"，做了两轮统计：

```
5 次连跑：失败数 0, 0, 1, 1, 0     ← 3/5 次有 1 个失败
12 次连跑：全部通过
6 次连跑：全部通过
```

⇒ 间歇性失败**确实出现过**（5 次里 2 次），但之后 18 次连跑都没能复现。

### 32.2 没能定性的原因

* `verify.sh` 的 ①b 用 `python3 -m unittest discover … -q`，失败时日志存在临时文件里，
  门禁会打印，但我在前几次用了 `grep -A6 "①b"` 过滤，把真正的 FAIL 行滤掉了 ——
  等我想抓完整输出时，它已经不红了。
* 期间有 headless 后台轮次在改 `kit/python/` 与 `module/` 下的文件，
  所以"并行写入导致的中间状态"是一个**无法排除**的候选解释。

### 32.3 找到了一半原因：`verify.sh` 的注释里有反引号

后来 `verify.sh` 直接报出：

```
./scripts/verify.sh: line 128: syntax error near unexpected token `!file.isFile'
./scripts/verify.sh: line 128: `# `if (!file.isFile) return` 的静默跳过（…'
```

我在第 ⑦ 道门的说明注释里写了 `` `if (!file.isFile) return` `` —— 反引号在 shell 里
是**命令替换**的定界符，于是那句被当成命令解析，`(` 与 `!` 触发语法错误。

**这解释了"时红时绿"的一半**：语法错误发生在脚本**读入阶段**，而失败点取决于
当时的解析状态；但要说清"为什么 12 次连跑全绿、5 次里却红 2 次"，我验证不了 ——
我在 bash 里单独试了「注释中的反引号在正常位置不会求值」，所以不能断言这就是全部原因。

**修法**：把反引号去掉（`# if (!file.isFile) return 的静默跳过…`），`bash -n` 通过，
门禁 8/8 全绿。

### 32.4 仍未定性的部分

* 那 2/5 次的具体失败行始终没抓到（被自己的 `grep -A6 "①b"` 过滤掉了）；
* 期间有 headless 后台轮次在改 `kit/python/` 与 `module/`，
  "并行写入的中间状态"仍是**无法排除**的候选解释。

### 32.4 后来定性的：是并行轮次写文件的中间状态

第 26 轮做了一次 20 次连跑（每次保存完整输出），抓到 **1/20 次失败**，失败方是：

```
ERROR: test_super_slot_dispatch.SuperSlotClassification.test_super_slot_classification
ERROR: test_no_review_leftovers (…)
ERROR: test_negative_control_not_every_target_is_a_slot (…)
```

而 `test_super_slot_dispatch.py` 的文件时间戳是 **23:03:42** —— 正是那轮循环开始（23:03）
的时刻。也就是说：**那份文件当时正被后台轮次写入**，测试过程读到了半成品，
于是 3 条 `ERROR`（不是 `FAIL`）同时出现。

**结论**：间歇性失败 = 并行轮次写文件的中间状态 + 反引号语法错误（两者独立，
都已消除）。剩下 19/20 全绿。

这条值得记的不是"修好了"，而是**判据**：
* `ERROR` 而非 `FAIL` + **多条同时出现** + 集中在同一个文件 ⇒ 优先怀疑"文件正在被写"；
* 对照 `stat -f "%Sm"` 的时间戳与循环开始时刻，能直接证实或排除；
* 连跑 ≥5 次并计数才能看到它 —— 单次跑大概率全绿（本轮 20 次里只红 1 次）。

### 32.5 下次该怎么做（写给自己与后来者）

* 看到门禁红，**先完整保存失败输出**再重跑。用 `grep` 过滤门禁输出最容易滤掉 FAIL 行。
  正确做法是 `./scripts/verify.sh 2>&1 | tee /tmp/gate.log`，然后再看。
* 判断"是否并行干扰"要看 `ps aux | grep "[d]sh --profile headless"`，
  而不是靠"重跑就好了"。
* 统计要连续跑 ≥5 次并计数，不要用单次结果下结论（本轮 5 次里 2 次失败，
  单次跑很可能看到的全是绿）。

---

## 33 第 26 轮：把"覆盖率为 0"的三种原因拆开

### 33.1 起因

统计真实抓取的覆盖情况时看到一个刺眼的对比：

```
33 个功能里，**真实样本只覆盖 8 个**
而 fixture（人工构造 66 行）覆盖 22 个
```

这两组数字都"对"，但读的人很容易把真实样本的 25 个 0 读成"功能都没工作"。
根因是第 8 节原来的措辞：

> **本抓取里没有行**（功能可能没开 / 没触发 / 钩子失效）

三种原因挤在一句话里，实际是三件不同的事：

| 原因 | 该做什么 |
|---|---|
| 功能没开（`defaultOn=false`） | 去设置页打开 |
| 开了但路径没走到 | 复现对应操作 |
| 钩子失效（类/方法改名） | 去查 smali |
| **样本早于功能**（第四种，原来没写） | 什么都别做，重新抓 |

第四种是这个项目**反复踩**的误读点 —— `ACTIVITY.md` §四 那张日期表就是为它存在的，
但报告里没提，于是读报告的人不会去看那张表。

### 33.2 改法

第 8 节现在分四条列出，并给出样本时间：

```
* **本抓取里没有行**（三种原因，本报告无法区分是哪一种）：`bridge_action_log`, …
  * 功能没开（`defaultOn=false` 的默认就没开）；
  * 开了但这条路径没被走到；
  * 钩子失效（类/方法改名）。
  * 若样本采集时间（19:22:37.548）早于该功能的加入时间，则为**结构性 0**，
    不是失效。对照 `module/ACTIVITY.md` §四 的日期表。
```

拿不到时间时**不假装知道**规则 —— 只说"无法区分"，不猜。

### 33.3 顺手查实的一件事

`log_sink` 在真实样本里是 **3568 行**，看着很健康。但实际上：

```
APPSIGN 里含 KdKit 自身日志：3556 / 3568 = 99.7%
```

这正是第 22 轮修掉的重复（`SELF_TAG` 排除）。这些样本是**修复前**采集的，
所以数字是历史值不是回归 —— 但它现在会误导人（"3568 行，工作得很勤"）。

在 `ACTIVITY.md` 的那一行加了标注，说明这个数字的历史含义。

### 33.4 一个差点误判的地方

我以为 `rm_adconfig` 在样本里是 0 行但我看到了 14 行 `GUARD`，怀疑统计错了。
实际是我 `grep -c "GUARD|AD_BLOCK"` 把两个前缀一起数了 —— 14 行全是 `GUARD`，
`AD_BLOCK` 确实是 0。**报告是对的。**

`rm_adconfig` 需要 `AD_BLOCK` 前缀（`blocked ad slot read`），那份样本里广告位读取
没有被拦（可能功能没开）。

### 33.5 生成器的 `--keep-section` 是对的，是我的用法错了

中途我以为重新生成会丢掉 `ACTIVITY.md` 后面 74 行手工维护的前缀表。实测：

```bash
python3 kit/scripts/module_activity.py --dir work/activity_inputs --out module/ACTIVITY.md
# 重生成后 214 行，手工表在，新标注也在
```

它默认 `--keep-section '## 七、'`。我之前的测法有误 —— `--out /tmp/xxx.md`
指向**新文件**，没有原内容可保留，所以当然没有表。

**教训：测试"重生成是否安全"必须对着真实目标文件跑**，不能指向空路径。

### 33.6 门禁

```
① 单元测试 81     ①b 抓取解析器 170（+1）
② assembleDebug    ③ parity 33 项
④ 钩子目标 109     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
✓ 8/8 全绿
```

**仍未验证**：真实样本覆盖的 8 个功能之外，其余 25 个在真机上是否工作 —— 无设备。
本轮的产出只是让"读报告的人不会误判"，不是让功能变得可验证。

---

## 34 第 26 轮续：间歇失败的完整定性 + 第 34 个功能接手

### 34.1 间歇失败至此完全定性

20 次连跑（每次保存完整输出）抓到 **1/20 次失败**：

```
ERROR: test_super_slot_dispatch.SuperSlotClassification.test_super_slot_classification
ERROR: test_no_review_leftovers (…)
ERROR: test_negative_control_not_every_target_is_a_slot (…)
```

`test_super_slot_dispatch.py` 的文件时间戳 **23:03:42**，而那轮循环正是 23:03 开始的
—— 后台轮次当时正在写这个文件，测试过程读到半成品。

**所以间歇失败有两个独立来源，都已消除**：
1. `verify.sh` 注释里的反引号（shell 语法错误）；
2. 并行轮次写文件的中间状态。

**判据（比结论更有用）**：
* `ERROR` 而非 `FAIL` + **多条同时出现** + 集中在同一文件 ⇒ 优先怀疑"文件正在被写"；
* 对照 `stat -f "%Sm"` 与循环开始时刻，能直接证实或排除；
* 连跑 ≥5 次并计数 —— 单次跑大概率全绿（本轮 20 次里只红 1 次）。

### 34.2 第 34 个功能 `web_picture_watermark`

后台 23:15 写的。它的主张具体到 smali 行号，值得核：

| 核实项 | 结果 |
|---|---|
| `CommonWebPictureBrowseActivity.c2(Landroid/graphics/Bitmap;)Landroid/graphics/Bitmap;` | ✅ 存在 |
| `j2(ZLandroid/widget/RelativeLayout;)V` | ✅ 存在 |
| 两者都是 `private`（`Xp.hook` 能钩到） | ✅ |
| 文档声明 `USED(self)`（不是死代码） | ✅ 与 `smali_usage.py` 一致 |

钩法是 `c2` 的 `onAfter` 把返回值换回入参（"合成器返回原图"），`j2` 把第一个布尔置 false
（页面自己决定不显示水印 View）。**两个钩点都不依赖私有字段名** —— 比改 `q0`
（那个 intent extra）更耐宿主混淆改名。这是个好设计，保留。

### 34.3 同步文档时踩的两个坑

**坑 1：新增功能要改的数字有 5 处**
`README.md` 的"34 个功能"、"33/34 个是热开关"、`一致（36 项）`、
`VERIFICATION.md`（生成）、`ACTIVITY.md`（生成 + 手工附录）。漏一个 ③ 就红。

**坑 2：`ACTIVITY.md` 的 `§七` 对照表是手工附录，位置必须在 `## 七、` 之后**
我第一次把新行插在 `WATERMARK` 后面 —— 那是 **114 行**，而 `§七` 从 **150 行**才开始，
于是门禁报"对照表缺少该功能"。正确做法是插在 `§七` 表格的最后一行之后（202 行）。

门禁的正则也说明了格式契约：
```
^\|\s*(?:\*\*)?`([a-z0-9_]+)`(?:\*\*)?\s*\|
```
行首必须是 `` | `feature_id` `` —— 我第一版写成 `| —（无前缀） | \`web_picture…\``
就被判成缺失。

**坑 3：`FEATURE_IDS` 要显式加**
`FEATURES_WITH_CAPTURE` 从规则自动推导，但 `FEATURE_IDS` 是**手写元组**。
不加就 `test_feature_ids_match_the_registry` 红。新功能不写抓取行 ⇒ 只进
`FEATURE_IDS`，自动落到 `FEATURES_LOGCAT_ONLY`。

### 34.4 门禁

```
① 单元测试 81     ①b 抓取解析器 170
② assembleDebug    ③ parity **34** 项
④ 钩子目标 109     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
✓ 8/8 全绿
```

**仍未验证**：真机上大图是否真的不带水印（无设备）。静态只能证明"这段代码会画水印、
且我们能在返回值处截住它"。

---

## 35 第 27 轮：门禁的正则写窄 = 一整类声明失去保护

### 35.1 起因：一个"应该被校验却没人管"的数字

上轮同步功能数要手改 5 处。这轮去查为什么这么麻烦，发现 `README.md:10` 写着
**"34 个功能、三十二个热开关"** —— 实际是 **33** 个热开关。

奇怪的是：`check_declared_counts()` **早就存在**，它专门校验"共 N 个功能 / N 个热开关"
这类声明。查它的正则：

```python
hot_pat = re.compile(r'\*\*(\d+)/(\d+) 个开关计数\*\*|(\d+)/(\d+) 个开关计数')
```

只认 `分数形式 个开关计数` 这一种写法。而根 `README.md` 用的是简写
`**N 个热开关**` —— **不在覆盖范围内**。

### 35.2 放宽后一口气抓出 3 处过期

```
✗ README.md: 声明 "三十二比三十四 个开关计数"，代码里实际 33/34
✗ README.md: 声明「二十七比三十四」的开关计数，代码里实际 33/34
```

以及顺着查出的第三处：`HookCore ready 28/28 features`（实际 34）。

**这三处都不是新退化，是长期过期**，因为没有任何门禁看它们。
其中 `28 功能（二十七个热开关）` 那行还在"状态"节 —— 读的人会以为那是当前状态。

### 35.3 这条教训比修复本身重要

**门禁的正则写窄，等于那一整类声明不受保护 —— 而且看起来是绿的。**

这已经是本项目**第三次**遇到同一模式（前两次都在 ⑦ 假测试检测器：只匹配变量断言、
只匹配 `import X` 不匹配 `from X import`）。三次的共同点：**规则的覆盖面比规则的
存在感更值得怀疑**。

对策：给每条规则补一个"**每种合法写法都要被认出**"的测试。
本轮新增 `kit/python/tests/test_declared_counts.py`（8 条）：

| 测试 | 形态 |
|---|---|
| `test_slash_form` | 分数形式（`a/b`），无加粗 |
| `test_slash_form_bold` | 分数形式，`**` 加粗 |
| `test_bare_hot_count_form` | `加粗的简化开关计数` ← 本轮补的 |
| `test_bare_hot_count_without_bold` | `简化开关计数` ← 本轮补的 |
| `test_wrong_*` ×3 | 写错必须报错 |
| `test_repo_passes` | 真仓库必须自洽 |

反向验证：把热开关数从 33 改成 30 ⇒ 门禁精确报出"声明与代码不符，实际 33/34"。
（这里刻意**不照抄**门禁的原始报错串。它匹配的是"分数形式的开关计数"，
而那句话本身就符合该形态 —— 写进文档会被门禁当成一处真声明。
规则无法区分"声明"与"引用"，这是已知局限，见 §35.5。）

### 35.4 门禁

```
① 单元测试 81     ①b 抓取解析器 178（+8）
② assembleDebug    ③ parity 34 项
④ 钩子目标 109     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
✓ 8/8 全绿
```

**仍未验证**：无（本轮是纯文档/门禁一致性修复，不涉及设备行为）。

### 35.5 这条规则的已知局限（本轮撞了 4 次）

放宽正则后，它开始误报**文档里引用示例**的地方：

* 我在 OPTIMIZATION 里照抄门禁的报错串（"三十二比三十四"那种形态）⇒ 被当成真声明；
* 我写测试形态表的示例（分数形式带具体数字）⇒ 同上；
* 我写"它匹配 `N 个开关计数` 这种简写" —— 那句话本身又符合简写形态 ⇒ 第三次。

最后把 4 处示例改成不含"数字 + 个开关"连写的形式才通过。

**这是规则的真实局限：它无法区分"声明当前值"与"引用/示例"。**

要不要收紧？我选择**不收紧**，理由：

* 误报的代价是**改文档措辞**（几分钟）；
* 漏报的代价是**一个数字静静过期几个月**（本轮抓到的那三处就是这样活下来的）；
* 而且误报会**立刻**暴露 —— 门禁红了就知道，不会静默。

换句话说：这条规则偏向"宁可我改措辞，也别让数字骗人"。这是一个刻意的取舍，
不是疏忽。如果将来误报变得频繁到影响写作，正确的修法是让它只在特定小节里生效
（例如"状态"节），而不是把正则收窄回去 —— 收窄就等于重新放弃保护。

---

## 33 第 26 轮（2026-10-25 晚）：绿门禁里的问号 + 第二条水印链路

### 33.0 先核清单，四项①②③④的实际状态

任务清单里的 ①②③ 三项，上一轮已写"完成"。本轮**不采信文档**，逐条跑实证：

| 项 | 清单说 | 实测 | 判据 |
|---|---|---|---|
| ① 11 个新前缀 | 已做 | **确实已做** | `PREFIX_FEATURE` 37 项；11 个 token 全部 `known_token=True`；`RC4PT(nontext)`/`HDR(v)` 走**正则 + 最长前缀**（`known_token` 返回 False 是设计如此，不是漏登记）。fixture 66 行解析出 53 种 `(kind, variant)`，11 个前缀的 feature 归属逐个正确 |
| ② ACTIVITY/VERIFICATION 对齐 | 已做 | **确实已做** | 两份都由生成器产出；重跑后 `diff` 为空（幂等）；`ACTIVITY.md` §七覆盖全部功能 |
| ③ 调用方判定层 | 已做（第 ⑥ 道门） | **做了，但缺一层** | 见 33.1 |
| ④ 继续找功能 | — | **本轮完成** | 见 33.2 |

① 的测试强度也核过了：`ParseEveryPrefix.CASES` 不是"某个前缀有一行"，而是**逐字段**断言
（`test_each_prefix` 对 `kind`/`feature`/`variant`/**每个字段值**四项同时比），
且 `EveryPrefixHasATest` 要求**每条规则**都有用例、`FixtureCoverage` 要求**每个
`(kind,variant)`** 都有样本。这比"前缀出现过"强得多。

### 33.1 ⑥ 号门的真实缺陷：只有"向下"，没有"向上"

`check_hook_callers.py` 长期输出 89 个目标全绿，末尾却挂着一行问号：

```
? ql.a.getBody  (features/host/HttpBodyProbe.kt:142) —— 0 个调用点，需确认是反射/JS 入口还是真死代码
```

绿门禁 + 悬案 = 最坏的组合：它既不会红，也不会消失。查下去是**工具缺一层判定**：

* `ql.a` 声明 `getBody()[B`，全 APK **没有**任何 `invoke-* ->Lql/a;->getBody` ⇒ "直接调用"为 0；
* 旧逻辑随后只做**向下**判定（`subclasses_of` ⇒ `OK(polymorphic)`），
  而 `ql.a` 的子类 `rl.a` 不调它 ⇒ 掉进 `NEEDS-REVIEW`；
* 真槽位在**祖父类** `com.android.volley.v`：`ZybHurlStack.smali:159` 与 `lk/l0.smali:146`
  各有一处 `invoke-virtual {..}, Lcom/android/volley/v;->getBody()[B`。

**关键细节**：直接父类 `com.android.volley.d` 是 `abstract` 但**不声明** `getBody`。
所以"只看直接父类"在这里必然漏判 —— 必须走**整条祖先链**。

修法（三层）：

| 改动 | 为什么必须 |
|---|---|
| `INVOKE_RE` 保留 **opcode**（`virtual`/`interface`/`direct`…） | "有调用方"不够；还要知道**怎么调的**。只有虚分派/接口分派才可能把子类覆写带进来 |
| 新增 `ancestors_of()` + `super_slot_sites()`（③ 层向上） | 沿整条链找"声明了这个方法名"的那一层，并要求该槽位有 `invoke-virtual`/`invoke-interface` 调用点 |
| 把判定主体从 `main()` 抽成 `classify()` | 以前整段写在 `main()` 里，测试只能起子进程抓 stdout；"某目标被降级"这种事实只能靠人眼看输出 |

结果：`? ql.a.getBody` → `OK(super-slot)`，并附槽位与两个分派调用点。
89 个目标现在 **89 有外部调用 / 0 无调用方 / 0 待核查**。

**新层必须窄**，否则会把真死代码洗白。断言写死：`OK(super-slot)` 在 89 个目标里
**只**命中 `ql.a.getBody`（`test_negative_control_not_every_target_is_a_slot`）。

顺带修掉一处**文件句柄泄漏**：我新写的代码用了裸 `open().read()`，复现了本项目
2026-10-25 已修过的 `ResourceWarning` 问题（5 万个 smali ⇒ 可能撞 `Too many open files`）。
已统一改走 `hook_vocab.read_text()`，并让 `json.dump` 用 `with`。
用 `python3 -W error::ResourceWarning` 验证为 0。

### 33.2 第 ④ 项：找到并落地 `web_picture_watermark`

**为什么能找得到**：没有按功能名猜，而是问"这个行为的判定输入从哪来"。
`watermark_off` 覆盖的是 `cu.l` → `ext="2"` → **服务端合成**。
但浏览大图的水印是**本地 Canvas 画的**，输入来自 `Intent` extra：

```smali
CommonWebPictureBrowseActivity.smali:119   c2(Bitmap) -> Bitmap
  :209   const v3, 0x7f080335              ← 水印位图（decodeResource）
  :271   createScaledBitmap(watermark, 287dpi, 88dpi)
  :352   Canvas.drawBitmap(src, 0, 0, paint)      ← 先画原图
  :393   Math.random()  :410 Math.random()        ← 位置随机
  :593   Canvas.drawBitmap(watermark, x, y, paint) ← 再叠水印
  :695   .end method

:1711  iget-boolean v0, …->q0:Z      ← 门控
:1735  invoke-direct …->c2(Bitmap)
:1292  "INPUT_NEED_WATER" → :1296 getBooleanExtra → :1304 iput-boolean q0
```

页面侧入口：`GotoPictureBrowseWebAction.smali:408 optBoolean("needWatermark")` → `:420 createIntent(…Z)`。

**钩法与理由**：钩 `c2` 的 `onAfter`，把返回值换回入参 —— 这是该方法的**纯函数语义**
（`Bitmap→Bitmap`），不依赖私有字段名 `q0`，宿主混淆改名时更耐改。
次钩点 `j2(boolean, RelativeLayout)` 把第一个布尔改 false（`:1963 if-eqz p1` →
`:1967 setVisibility(0)` / `:1980 setVisibility(8)`），关掉同页的水印 View。

**按 §7.6 第 6 条先证不死**：`smali_usage` 判 `c2`/`j2` 均 `USED(self)`
（自调 1/2 处，外部入口 `GotoPictureBrowseWebAction:420`）。

**踩到并修掉的两个坑**（都记进 PARADIGM §7.6.5）：

1. **KDoc 里先写错了行号**：我凭 grep 的**相对**偏移写了 `:1781/:1815/:1855`，
   实际是 `:209/:271/:352`。文档里的"静态证据"一旦是错的，比没有更坏。
   现在每条行号都用 `grep -n` 的**绝对**行号核对过。
2. **写了一个未登记前缀**：先用 `WATERMARK pic off …`，而 schema 的规则是
   `^WATERMARK (off .*)$`。①b 的漂移门禁本会红，我在它红之前就改成了
   `WATERMARK off applied | scope=webpic`。

### 33.3 门禁

**8/8 全绿**：Kotlin 188（+19）· 解析器 · assembleDebug · parity 34 · 目标 · 签名 · 调用方 89 · 假测试

新增两个离线测试文件，共 **13** 个测试：

| 文件 | 测什么 |
|---|---|
| `test_super_slot_dispatch.py`（5） | 祖先链跨抽象中间类 / 槽位真有分派调用点 / `ql.a.getBody` 判 `OK(super-slot)` / **新层只命中这一条** / 门禁不再挂问号 |
| `test_web_picture_watermark.py`（8） | `c2` 真的合成水印位图 / 受 `q0` 门控 / `q0` 来自 `INPUT_NEED_WATER` / `j2` 切 View / 两目标非死代码 / 钩点是字面量 / `gate = id` / 文档写了"未验证" |

**反向验证（本轮的重点）**：3 条结构断言在"注入破坏"时全部精确报错、原样时全过
（3/3 召回、0 误报）。但第一版反向验证脚本**自己是错的** —— 它给 `tc.text` 赋值后
调 `run()`，而 `setUp()` 会重新读文件覆盖掉注入内容，于是"破坏后仍全绿"。
改成把 `ACT` 指向写坏的临时副本才真正测到。**先证明探针会失败**，已写进 PARADIGM §7.6.5。

### 33.4 仍未验证（不许写成已验证）

| 项 | 状态 | 为什么 |
|---|---|---|
| `web_picture_watermark` 真机效果 | **未验证** | 无设备。静态只证明"这段代码会画水印、且返回处能截住" |
| 资源 `0x7f080335` 是否**只**用于水印 | **未验证** | 我们不改资源、只跳过合成，所以即便它同时用于别处也不受影响；但不声称"它是水印专用" |
| 服务端已下发的水印 | **不在范围内** | 那是另一条路径，本功能结构上不碰 |
| ④ 第 2 轮的候选 | **待做** | 见下一节 |
| ⑥ 新层在其他 APK 上的误报率 | **未验证** | 目前只有这一个样本；`test_negative_control_*` 是唯一的守门断言 |

### 33.5 下一步（按顺序）

1. **`check_hook_callers.py` 的 ③ 层还有一个已知边界**：接口方法（祖先链上找不到声明）
   走的是"同名 + `invoke-interface`"保守兜底，**没有验证参数形状**。
   当前样本里没有触发，但它会把"同名不同参"的接口方法误判成活代码。
   修法：把 `_defined_cached` 升级为"方法名 → 参数描述符集合"，兜底时比对形状。
2. **`vip_unlock` 的作用面需要按实测重新表述**（本轮核过，之前的直觉是错的）。
   `bk/a;->p()Z` 一共 **17 处**调用点，逐个看"结果被谁消费"得到：

   | 类别 | 数量 | 判据 | 例 |
   |---|---|---|---|
   | **真闸门**（结果直接进 `if-*`） | **3** | `move-result r` 后紧跟 `if-eqz/if-nez r` | `aj/f:2305`（VIP 直接 return，否则置标志后 `u()`）、`oj/d:1038`（VIP return，否则再判 `d()`）、`xi/c:282`（拼 `is_vip` 上报值） |
   | **只打点**（进 `Boolean.toString` / `StringBuilder.append`） | **14** | 结果只被拼成统计事件 | `MainActivity:2660/2716`、`BookComplete…:734/1687/4433/12209/13820`、`BaseAnswerCompleteFragment:9197/10120`、`VipCurrentStatusWebAction:290`、`oj/u1:514`、`rj/e:364`、`oj/t0:721` |

   也就是说：**3 处真的会改变行为，14 处纯粹是埋点。**
   我最初写下的是"17 处全部只用于打点" —— 那是**错的**，`aj/f` 与 `oj/d` 明确用 VIP 布尔
   做了提前返回。发现方式是把"有没有 `if-*` 消费 `move-result` 的寄存器"写成脚本跑一遍，
   而不是靠读前两处下结论。

   要做的是把 3 处逐个读清"拦掉的是什么行为"，只有读清的才写进"能改变行为"；
   `vip_unlock` 现有描述若声称覆盖了全部 VIP 分支，应据实收窄。
   **未验证**：这 3 处是否就是全部服务端授权点 —— 客户端判定 ≠ 服务端授权（§7 已记）。
3. 继续按"判定输入来源"找第 ④ 项的下一个：优先 `app_kdzy_getAbTest`（AB 实验开关，
   输入来自服务端 JSON、直接决定 UI 分支）与 `PdfPrintAction` 系（打印闸门）。

---

## 36 第 28 轮：把"正则写窄"的教训推广到 ⑦，并处理一次幽灵功能

### 36.1 推广上轮的教训：`silent-return` 也只认一种写法

上轮发现 `check_declared_counts` 的正则写窄，导致一整类声明没人校验。
这轮拿同一把尺子量 ⑦ 的规则，第一个就中：

```python
SILENT_RETURN_KT = re.compile(r'if\s*\([^)]*\)\s*return\s*$', re.M)
```

只认 `if (...) return`（单行无花括号）。实测漏掉三种：

| 写法 | 第一版 | 现在 |
|---|---|---|
| `if (x) return` | ✅ | ✅ |
| `if (x) { return }` | ❌ | ✅ |
| `if (x) {\n return\n }` | ❌ | ✅ |
| `if (x) return@test` | ❌ | ✅ |

修的时候还撞出一个反向问题：放宽后 `if (x) return 1`（**带返回值**，不是静默跳过）
被误报。加了"`return` 后不能跟表达式"的判据后，4 种目标写法全中、3 种非目标写法零误报。

### 36.2 这条模式的完整清单（三次 + 这次）

| 位置 | 写窄的是什么 | 后果 |
|---|---|---|
| `check_declared_counts` | 只认分数形式的开关计数 | 3 处数字过期数月无人管 |
| ⑦ `literal-assert` | 只认变量、丢了直接字面量 | 召回 2/3 |
| ⑦ `order-dependent-import` | 只认 `import X`，不认 `from X import` | 反向验证抓不出来 |
| ⑦ `silent-return` | 只认单行无花括号 | 3 种写法漏掉 |

**结论：每加一条文本规则，必须同时问"这种语义还有别的写法吗"，并给每种写法一条测试。**
这是本项目的第 N 次同类教训，值得当成一条固定习惯。

### 36.3 一次幽灵功能：`bridge_caller_log`

中途 ③ 报"代码里实际 35 个功能"，而我只看到 34 个。查下去发现：

* `features/host/BridgeCallerLog.kt` 存在过（内容质量不错：钩 `HybridWebView.dispatchAction`
  分发器，一次覆盖 225 个 `@FeAction`，解决 `bridge_action_log` 只钩 2 个的结构性盲区）；
* 但它**没有注册进 `FeatureRegistry`**；
* 而在我准备注册它的时候，**文件被后台轮次删掉了**（`find` 已找不到）。

于是我做了一次完整的"接半成品 → 回滚"：改 README 数字 → 加注册 → 编译报
`Unresolved reference` → 发现文件没了 → 回滚数字与注册 → 门禁恢复全绿。

**这轮没有产出新功能，产出的是两个认知**：
1. ⑦ 的 `silent-return` 从 1 种写法扩到 4 种（零误报）；
2. 后台轮次会**撤销**自己写的东西 —— 接到半成品时不能假设"文件存在且会被保留"，
   注册前先 `find` 一次确认它还在。

### 36.4 一个被修掉的真实门禁盲区

在核查 `BridgeCallerLog` 时发现它的钩子写成：

```kotlin
private const val CLASS = "com.baidu.homework.common.ui.widget.HybridWebView"
Xp.hookAllAfter(CLASS, "dispatchAction", …)      // ← 类名走常量
```

④⑤ 只按**字符串字面量**解析，于是这两条钩子对门禁**完全不可见** ——
④ 看到 116 个目标却一条都不含那个功能。这正是 `PARADIGM.md §7.6.1` 记的规则
（`RouteLog`、`HttpBodyProbe` 都踩过）。

虽然该文件后来被删了，但**这个盲区是真实存在的**：如果它留下来，就会是一条
"装了但门禁看不见"的钩子。本轮把它改成字面量后，④ 立刻列出两条
（`dispatchAction` = `USED(self)`、`dispatchActionToListeners` = `USED`）。

### 36.5 门禁

```
① 单元测试 81     ①b 抓取解析器 179（+1）
② assembleDebug    ③ parity 34 项
④ 钩子目标 116     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
✓ 8/8 全绿
```

**仍未验证**：无（本轮为门禁规则与文档一致性）。

## 36 第 28 轮：先证明缺口存在（一次自我否决 + 一个真缺口）

### 36.1 本轮结论

| 项 | 结果 |
|---|---|
| `fetchPayInfos` 观测 | **已实现**（`bridge_action_log` 的第三个变体 `BRIDGE payorder`） |
| 一个被自己否决的候选 | `bridge_caller_log` —— 与 `h5_bridge_log` 重复，**已回滚**，记在 `PARADIGM.md` §9.1 |
| 一个新变体打破的消费端假设 | **已修**（`bridge_inventory.py` 因缺 `action` 抛 `TypeError` 崩掉） |
| 两处"文档自己和自己矛盾"的计数 | **已修**（生成器硬写"11 个"实际 12 行；附录硬写"9 个"实际 10 行） |
| 新增不可静默退化的测试 | 2 条（`KindFieldContract` 2 个 + `CountsDerivedNotTyped` 3 个） |
| 真机验证 | **仍未做**（无设备） |

### 36.2 为什么这一轮先做"否决"

上一轮的教训是"规则的覆盖面比规则的存在感更值得怀疑"。这一轮遇到的是它的兄弟：
**候选的独特性比候选的可行性更值得怀疑。**

`bridge_caller_log` 的论证听起来无懈可击 —— "`bridge_action_log` 只钩 2 个精确类，
而 APK 里有 225 个 `@FeAction`，所以模块看不见覆盖面"。前半句是真，后半句是假：
`H5BridgeLog` 钩的就是那两个分发器方法，且第一行就记 action 名。

门禁 ④ 为此判了 `USED`、⑥ 判了 0 死代码 —— **它们没有错，它们只是不回答"这是不是新的"**。
499 行实现 + 1 个前缀 + 4 条用例全部回滚。

### 36.3 真缺口：`fetchPayInfos`

`FetchPayInfosAction`（`@FeAction(name="fetchPayInfos")`）把页面传来的 `payInfo`
原样塞进 `Scancodecreatepayorder$Input`，后者在构造器里钉死：

```
__url    = /vippayui/clientpay/kdclientinnerpayorder
__pid    = vip
__method = 1   (POST)
```

即**页面可直接驱动 VIP 下单请求**。静态证据：`smali_usage.py --target
com.kuaiduizuoye.scan.web.actions.FetchPayInfosAction:onAction` → `REFLECTIVE`
（`@FeAction` 反射分发；静态 0 invoke 是设计如此，不是死代码）。

落成 `BRIDGE payorder submit len=<n> keys=<k>:<键名> pid=vip`。
**不记 `payInfo` 的值** —— 抓取是明文落盘，值里可能有订单号/金额/支付凭据。
长度 + 键名足以回答"payload 多大、带哪些字段、何时发生"。

### 36.4 新变体打破的消费端假设

首版 `fields` 漏了 `action`（另两个 `BRIDGE` 变体都有），于是
`bridge_inventory.py` 的 `sorted(..., key=(-n, action))` 撞上 `None < str`，
**整个统计工具崩掉**。而 schema 侧测试当时**全绿**：fixture 解析正常、kind/variant 都对、
字段也都取到 —— 只是少一个**别人依赖的**键。

修法两层（缺一不可）：schema 补 `action`（消费端假设本来就成立）；
消费端 `action or '(未知变体:…)'` 兜住（新变体总会再来，统计工具不该崩）。

新增 `test_capture_schema.py::KindFieldContract`：按 `(kind, variant)` 声明消费端依赖的键，
用 fixture + 全部用例行逐条断言。反向验证：去掉 `action` ⇒ 立刻红并指名
`BRIDGE/payorder 缺少消费端依赖的字段 action`。

第一版按 **kind** 写契约，`VIPLIMIT result` 被判缺 `product` —— **假红**，
因为 `ask`/`result` 是两种不相交形状。契约粒度必须匹配消费端分支的粒度。

### 36.5 两处"同一页上的两个数字互相矛盾"

| 位置 | 写的 | 实际 | 性质 |
|---|---|---|---|
| `module_activity.py:199` | "这 **11** 个功能…只走 KdLog" | 表由 `FEATURES_LOGCAT_ONLY` 生成，**12** 行 | 生成器硬写 |
| `ACTIVITY.md` §七之二 | "下面 **9** 个功能钩的是广告视图" | 表 **10** 行 | 手工附录硬写 |

两处都不是新退化：功能数从 11→12、9→10 时没人注意到同一屏的两个数字。
**没有任何 FAIL**（生成成功、表格渲染正常），所以只能靠断言抓。

修法：生成器改 `len(FEATURES_LOGCAT_ONLY)`；附录改 10；新增
`test_doc_generators.py::CountsDerivedNotTyped`（3 条）——
判据是"文档声称的 N == 实际行数"，**不是**"N 等于某个常量"（那会变成又一个要手改的数字）。

### 36.6 门禁结果

八道门全绿：Kotlin 81、Python **211**（+2）、parity 34、目标 **115**（+1）、
签名 89、调用方 92（0 死代码）、假测试 0。

**未验证**：真机行为。`fetchPayInfos` 是否真被页面调用、`payInfo` 的真实形状，
都需要设备侧 `H5BRIDGE fetchPayInfos` / `BRIDGE payorder` 行才能确认。
本轮所有结论只在静态层成立（目标存在 / 反射分发 / 常量 URL 已核对 / 编译过 / 单测过）。

---

## 37 第 28 轮续：给门禁加"并发重试"，它当场抓出一个真问题

### 37.1 为什么要加重试

本仓库有并行轮次在改 `kit/python/` 与 `module/`。门禁读到的可能是**写了一半的文件**，
于是偶发失败 —— 第 26 轮的 20 次连跑实测：红 1 次，定位到
`test_super_slot_dispatch.py` 的时间戳正好落在循环开始那一刻。

一直靠"重跑一下就好了"不是办法，因为**它把真问题也一起糊过去了**。

### 37.2 实现：只对并发敏感的门禁重试，且**必须显式说出来**

```bash
RETRY_GATES=" ①b 抓取解析器 ⑦ 假测试扫描 "
```

* 只给读取源文件/生成器输出的门禁加重试；①②③ 那类跑编译的不加（它们要么快要么真错）；
* 重试成功打印 **`RETRY-PASS（首次失败，重试通过 —— 大概率是并行写入的瞬时状态）`**，
  **不静默**。静默重试会让"偶发"变成没人知道的常态；
* 重试仍失败 ⇒ 判 `FAIL（重试仍失败 ⇒ 真问题）`，照常红。

保留失败日志（不 `rm`），便于日后判断"这种事是否越来越频繁"。

### 37.3 它第一次运行就证明了价值

加完重试后跑门禁：①b 首次失败 → 重试 → **仍然失败** ⇒ 判真问题。

原因查出来是：我改了文档但没重新生成 `VERIFICATION.md`，
`test_committed_file_is_what_the_generator_produces` 报不一致。

**这正是重试机制想要的效果**：
* 瞬时失败会被重试吸收，不再浪费一轮；
* 真失败不会被重试掩盖，而是明确标注"重试仍失败"。

如果当初只是"再跑一遍"，这次的真问题就会在下一次偶然通过时被忘掉。

### 37.4 顺带发现：Python 测试耗时涨了 4 倍

```
之前：约 35 秒（179 条）
现在：约 146 秒（211 条）
```

后台轮次新增了 32 条测试，其中一些跑 smali 解析。这本身不是缺陷，
但它让门禁从"随手跑"变成"要等两分半"——**这会改变人的使用习惯**（少跑）。

记下来，暂不处理。若将来超过 5 分钟，就该考虑：
* 把 smali 解析结果缓存到一次进程内（`setUpClass` 而非每方法重解析）；
* 或把慢测试移到 `--slow` 分组，日常门禁只跑快的。

### 37.5 门禁

```
① 单元测试 81     ①b 抓取解析器 211
② assembleDebug    ③ parity 34 项
④ 钩子目标 116     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
✓ 8/8 全绿
```

**仍未验证**：无（本轮为门禁机制与文档一致性）。

---

## 38 第 29 轮：把门禁跑时从 146s 压到 72s（"太慢的门禁等于没有门禁"）

### 38.1 为什么这件事优先级不低

上一轮记录了一个副作用：

```
Python 测试：35s（179 条）→ 146s（211 条）
```

当时写的是"暂不处理，若超 5 分钟再说"。但这轮回头想，**它已经在改变行为了**：
我自己上一轮就因为等不及而把门禁丢到后台，然后靠"稍后看结果"推进。

一道"太慢所以懒得跑"的门禁，等于没有门禁。

### 38.2 先量，再改

按文件计时（13 个文件）：

```
54.39s  test_vip_call_sites
40.00s  test_super_slot_dispatch
22.86s  test_parsers_cli
 5.78s  test_hook_gate_agreement
 4.82s  test_smali_usage
 …
合计 136.2s
```

前三名占 **86%**。所以只修这三个就够，不用碰其余十个。

### 38.3 两处都是同一个错误：把"重活"放在 `setUp` 里

| 文件 | 错在哪 | 单次成本 | 重复次数 | 改进后 |
|---|---|---|---|---|
| `test_vip_call_sites` | `setUp` 里 `classify(APK)` | ~13s | 4 个测试方法 | **54s → 12s** |
| `test_super_slot_dispatch` | `setUp` 里 `self.rows = None` 重置实例缓存 | ~9s | 5 个测试方法 | **40s → 16s** |

**`setUp` 每个测试方法跑一次，`setUpClass` 每个类跑一次。**
把"扫全 APK"这种重活放 `setUp`，成本就是 `O(方法数 × 单次)`。

第二个更隐蔽：代码里明明写了惰性缓存

```python
def setUp(self):
    self.rows = None          # ← 每个方法重置
def _rows(self):
    if self.rows is None: …
```

缓存写法是对的，但**存在实例属性上**，而 unittest 每个测试方法新建一个实例 ⇒
缓存永远不跨方法生效。改到类属性后立刻生效。

### 38.4 结果

```
单文件：54s → 12s、40s → 16s
总计：  146s → 72s（-51%），214 条测试全绿
```

剩余最大项是 `test_parsers_cli`（26s）—— 它靠 `subprocess` 逐个跑 CLI 脚本，
13 次进程启动本身就是成本。这条**不再压**：继续优化要么改测试形态（减少真实性），
要么引入进程复用（增加复杂度），收益不足以抵消风险。

### 38.5 教训写成一条可复用的判据

> **测试慢的时候，先看"重活是在 `setUp` 还是 `setUpClass` 里"，再看"缓存挂在实例还是类上"。**
> 这两处能解释大部分"测试无故很慢"，而且修起来是纯机械的，不改变任何断言。

顺带记一条纪律：README 与文档里的**测试耗时数字不要写死**（本轮只在 OPTIMIZATION
的历史记录里出现，属于"当时的观测值"）。ACTIVITY / VERIFICATION 那类由生成器产出的
文档不该带易变数字。

### 38.6 门禁

```
① 单元测试 81     ①b 抓取解析器 214
② assembleDebug    ③ parity 34 项
④ 钩子目标 116     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
✓ 8/8 全绿（整轮约 100 秒，其中 Python 侧 72 秒）
```

**未验证**：无（本轮是测试性能与结构，不涉及设备行为）。

---

## 39 第 30 轮：第 ⑧ 道门 —— 钩点共享登记

### 39.1 一个从没被系统检查过的风险

34 个功能各自装钩子。**当两个功能钩住同一个方法时会发生什么？**
这个问题此前没有任何地方回答过，也没有门禁会问。

实测当前有 6 个方法被 2 个"功能"指向，其中：

| 钩点 | 归属 | 性质 |
|---|---|---|
| `aj.a.d` / `.f` / `.h` | `AdFeatures.kt:58` 与 `:201` | **同一文件内的两个 object**，不算跨功能 |
| `HybridWebView.dispatchAction` | `BridgeGuard.kt:69` + `H5BridgeLog.kt:39` | **跨文件，真共享** |
| `HybridWebView.dispatchActionToListeners` | `BridgeGuard.kt:70` + `H5BridgeLog.kt:41` | 同上 |

### 39.2 为什么这类问题难发现

**它不会让任何门禁变红**：不崩溃、不打日志、钩子数照常记 2 个。
唯一症状是"某个功能安静地少收数据"，而那要等到有人拿抓取逐条对照才发现。

这正是本项目反复强调的那一类缺陷：**没有 FAIL 的错误比红着的错误更危险。**

### 39.3 实测语义：被拦的调用，另一个功能还能不能看到

查了 `util/Xp.kt:146` 的实现：

```kotlin
XposedBridge.hookMethod(m, object : XC_MethodHook() {
    override fun beforeHookedMethod(param: MethodHookParam) {
        if (gate != null && !KdConfig.isOn(gate, true)) return
        cb(param)
    }
})
```

* **没有设 `priority`** ⇒ 两者同优先级；
* `BridgeGuard` 拦截时写 `param.result = null`（`BridgeGuard.kt:113`）；
* `H5BridgeLog` 只读 `param.args`，不写 `result`。

结论：**`BridgeGuard` 拦下的那次调用，`H5BridgeLog` 仍然记得到。**
⇒ `GUARD blocked=…` 与 `H5BRIDGE …` 两行**可以同时出现**，读抓取时不该认为
"被拦了所以桥日志少一条"。

这条是 `observed`（有代码依据）；真机上未做过"两行同时出现"的实测，标 `unverified`。

### 39.4 门槛设计：不禁止共享，只要求**写明语义**

`kit/scripts/check_hook_sharing.py --strict`：列出跨文件共享的钩点，
要求它们在 `PARADIGM.md §10` 登记（写清谁用 before/after、谁可能短路、短路后的影响）。

**刻意不做成"禁止共享"**：共享本身往往是对的 —— `BridgeGuard` 负责拦、
`H5BridgeLog` 负责记，职责不同却都需要在同一个入口工作。
要防的不是共享，是**"共享了却没人知道语义"**。

### 39.5 三次修工具的过程（也是一种模式）

1. 节标题写死 `## 钩点共享`，而实际是 `## 10. 钩点共享` ⇒ 登记全部失效；
   改成按关键字正则匹配；
2. 登记写短名（`HybridWebView.x`）但工具要求全等 ⇒ 报"未登记"。
   改成后缀匹配。**这个错很危险**：它会让人去重复登记，而不是怀疑工具；
3. 测试里三个 TestCase 各自调一次 `shared_targets()`（8 秒/次）⇒ 34 秒。
   加类级缓存 → 23.8 秒，再加模块级缓存 → **10.6 秒**。

第 3 条正好复用了上一轮刚总结的判据（"重活在 `setUp` 还是 `setUpClass`"），
只不过这次多了一层：**跨类的重复要模块级缓存**。

### 39.6 门禁

```
① 单元测试 81     ①b 抓取解析器 218
② assembleDebug    ③ parity 34 项
④ 钩子目标 116     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（严格模式，4 类规则，0 命中）
⑧ 钩点共享登记（2 处跨文件共享，均已登记）
✓ 9/9 全绿
```

**仍未验证**：真机上"被拦截的调用同时出现 `GUARD` 与 `H5BRIDGE` 两行" —— 无设备。

---

## 40 第 31 轮：④ 门红了，查出来是"结论依赖于目标在列表里的位置"

### 40.1 症状

④ 钩子目标门禁报红，说 `NativeHelper.nativeGetSign` 是"死目标"：

```
✗ com.zuoyebang.baseutil.NativeHelper.nativeGetSign  (NativeProbe.kt:64)
  本类之外没有任何字节提到它，res/ 与清单里也没有 ⇒ 钩它必然空转
```

但同一时间单独查这个目标却是有引用的：

```
$ python3 kit/scripts/smali_usage.py --smali work/apktool_out \
    --target com.zuoyebang.baseutil.NativeHelper:nativeGetSign
USED   …  直接 1  例: a.smali:658
```

而且 `a.smali:658` 确实有一行 `invoke-static {p0}, Lcom/zuoyebang/baseutil/NativeHelper;->nativeGetSign(...)`。

**同一个目标，单跑说"有人用"，批量跑说"没人用"。**

### 40.2 根因：读预算耗尽，排在后面的目标系统性缺证据

`smali_usage.analyse()` 的实现是：

1. 一次 grep 拿到"提到任一目标描述符"的所有文件；
2. **按路径排序**后逐个读进内存；
3. 读入总量超过 `read_budget`（原来 **96 MB**）就停下；
4. 没读到的文件里的目标，结论降级为 `INCOMPLETE`。

109 个目标需要的字节数超过 96 MB ⇒ **排在列表后段的 11 个目标被判 `INCOMPLETE`**。

这个降级本身是**对的设计**（"看不见"≠"不存在"，宁可说证据不完整也不断言 DEAD）。
问题在于 ④ 的映射：它把 `INCOMPLETE` 也归进了"死目标"区打印，于是读起来像判了死刑。

### 40.3 但这比"判错"更坏

真正要紧的不是那 11 个目标少了证据，而是：

> **判定结果取决于目标在排序列表里的位置。**

同一份静态输入，只因为批量里多加了几个目标，某个目标的结论就从 `USED` 变成
`INCOMPLETE` —— 这让"这条结论可复现吗"变成碰运气，而本项目所有结论都建立在
"离线可复跑"上。

（`smali_usage.py` 的注释里早就记过一次同类教训：`DEAD` 与 `TYPE-ONLY` 在两次运行间
来回翻转，resolved 数在 96/107/112/116 之间跳。当时的修法是 `sorted()` +
`INCOMPLETE` 降级。这轮暴露的是同一问题的另一半：**降级保护了正确性，却留下了不可比性**。）

### 40.4 修法：把预算提到够用

`read_budget: 96 MB → 320 MB`。实测：

| | 96 MB | 320 MB |
|---|---|---|
| `INCOMPLETE` | **11** | **0** |
| `USED` | 36 | **49** |
| `USED(self)` | 6 | **13** |
| `TYPE-ONLY` | 29 | 21 |

**20 个目标恢复了完整证据**（其中 13 个从 INCOMPLETE 变成 USED/USED(self)）。
内存代价可接受 —— 这是离线脚本，不是模块运行时。

④ 随即转绿。

### 40.5 顺带处理掉的三件事

1. **新功能 `robust_probe` 接手**：后台写了 `RobustProbe.kt`（Robust 补丁面观测，
   全 APK 7594 类 / 35784 方法带插桩），但没注册进 `FeatureRegistry`。
   注册时撞到一个编译错误：`Array<Class<*>>::class.java` —— **泛型不能做 class literal**，
   改用 `java.lang.reflect.Array.newInstance(Class::class.java, 0).javaClass`。

2. **一个"假开关"的误判与纠正**：门禁报 `robust_probe_all` "声明了但没人读"。
   我先把声明删了，结果门禁立刻改口报"代码读了没人声明的键" —— 说明它**确实有实现**
   （控制"只记 supported=true 还是记全部"）。恢复声明，把它补进 README 选项列。
   **教训：门禁说"没人读"时，先 grep 读取点再决定删不删。**

3. **`（N 个热开关）` 括号形态补进计数校验**：根 README 的"状态"节用这个写法，
   而 `check_declared_counts` 的正则只认 `**N 个热开关**` 与纯文本两种
   ⇒ 又一次"规则写窄 = 整类声明不受保护"（同类问题**第二次**）。
   加正则后反向验证：改成 28 ⇒ 精确报错。

### 40.6 门禁

```
① 单元测试 81     ①b 抓取解析器 218
② assembleDebug    ③ parity 35 项
④ 钩子目标 116（0 INCOMPLETE）
⑤ 钩子签名 89      ⑥ 钩子调用方 62
⑦ 假测试扫描（4 类规则，0 命中）
⑧ 钩点共享登记（2 处跨文件共享，均已登记）
⑨ 热修复暴露面（后台新增）
✓ 10/10 全绿
```

**仍未验证**：`robust_probe` 与真实补丁的关系（需要服务端下发过补丁的真机环境）。

---

## 41 第 32 轮：12% 的余量不叫余量，它是定时器

### 41.1 上轮的修复其实只治了症状

上一轮把 `read_budget` 从 96 MB 提到 320 MB，`INCOMPLETE` 从 11 降到 0。
但这个数字是**估**的，没人量过实际用了多少。

这轮量了一下：

```
目标 109 个 → 命中 16242 个 smali 文件，合计 279.9 MB
read_budget = 320 MB  ⇒  余量 +12%
```

**12% 的余量不叫余量。** 宿主 APK 只要稍微长大一点（新版本、多一个功能模块），
就会重新开始静默降级 —— 而且降级的表现是"某个目标的结论从 `USED` 变 `INCOMPLETE`"，
不是任何可读的错误。

这正是上一轮那个缺陷的本质：**它会自己回来，而且回来时无声。**

### 41.2 修法：给足余量 + 把余量做成可观测

**① 预算提到 640 MB**（留 56% 余量）。离线脚本的内存不心疼。

**② 新增第 ⑩ 道门 `check_usage_budget.py`**：

```
[budget] 目标 109 个 → 命中 16242 文件，需 279.9 MB
[budget] read_budget = 640 MB ⇒ 余量 +56.3%
[budget] 余量充足
```

余量 < 25% 就判红，并给出建议值。反向验证：把预算临时改成 300 MB ⇒

```
[budget] read_budget = 300 MB ⇒ 余量 +6.7%
[budget] **余量低于 25%**：宿主 APK 一变大就会静默降级。建议把 read_budget 提到 373 MB 以上。
strict exit=1
```

它防的不是当前错误，而是**"宿主下次变大时同一个坑再踩一次且没人发现"**。

### 41.3 实现细节：一处防漂移

预算值从函数签名里取，不硬编码：

```python
def current_budget() -> int:
    import inspect
    return inspect.signature(su.analyse).parameters['read_budget'].default
```

否则"改了 `analyse` 的预算但自检还看着老数字"——那会让这道门变成装饰。

### 41.4 一个手误

加门禁时 shell 引号没闭合（`--strict` 后面少了一个 `"`），
表现是 `verify.sh: unexpected EOF while looking for matching '"'`，
而且是在**所有门跑完之后**才报语法错 —— 前 10 道门都显示 PASS，最后才炸。

`bash -n` 这次没提前发现（我是在改完后才跑的），教训照旧：
**改 `verify.sh` 后立刻 `bash -n`，不要等门跑完。**

### 41.5 门禁

```
① 单元测试 81     ①b 抓取解析器 218
② assembleDebug    ③ parity 35 项
④ 钩子目标 116（0 INCOMPLETE）
⑤ 钩子签名 89      ⑥ 钩子调用方 62
⑦ 假测试扫描（4 类规则，0 命中）
⑧ 钩点共享登记（2 处，已登记）
⑨ 热修复暴露面
⑩ 读预算余量（279.9 MB / 640 MB，余量 56%）
✓ 11/11 全绿
```

**仍未验证**：无（本轮是工具可靠性，不涉及设备行为）。

---

## 42 第 33 轮：注释也是断言，而它从不失效

### 42.1 起点：核对 ④ 的 21 个 TYPE-ONLY

`TYPE-ONLY` 的意思是"这个类被大量当作类型使用，但没有任何 `invoke-*` 直接调用"。
它可能是正常形态（形参类型、泛型参数），也可能是分类不够细的托词。

逐个量了它们的类引用数：

| 目标 | class_refs |
|---|---|
| `androidx.fragment.app.Fragment` | 3746 |
| `com.baidu.homework.common.net.model.v1.common.InputBase` | 3313 |
| `HybridWebView$ReturnCallback` | 2341 |
| `ci.a` | 121 |
| `HWRequest` | 76 |
| `xc.a` | 98 |
| …（21 个） | 最少 **35** |

**没有一个是零引用的。** 所以 ④ 的分类是健康的，这 21 个都不是死代码。

### 42.2 但核对过程中撞到一条过期注释

`AdFeatures.kt:158` 当时写着：

> 第二个形参 `ci.a` 只能在运行时解析……所以仍用 clazzOrNull ——
> **门禁会如实标 UNKNOWN**，而不是假装校验过。

而门禁实际标的是 **`TYPE-ONLY`**。查证：`smali_usage` 早已细分出
`TYPE-ONLY` / `SUPER-SLOT` / `REFLECTIVE-ENTRY` 三层，注释描述的是一年前的判定体系。

**注释比代码更容易过期，而且过期后不会有人发现** —— 它不会编译失败、不会让测试变红。

这在本项目已经出现三次：
1. 本条（`UNKNOWN` vs `TYPE-ONLY`）；
2. `check_hook_targets.py` 里 `FORWARD_FN_RE` / `DYNAMIC_CLASS_RE` 的说明段，
   函数删掉后还留着；
3. `module_activity.py` 注释说某张表是手写的，实际已由生成器产出。

### 42.3 工具：把散落的断言集中起来

`kit/scripts/check_comment_claims.py` 扫描模块源码注释，揪出"**谁 会 怎样**"
这种断言门禁行为的句子：

```
[claims] 9 处注释断言了门禁/脚本行为 —— 逐条核对它们是否仍成立：

  features/ads/AdFeatures.kt
    :156  门禁按字面量解析（用 `dialog.name` 会让这条钩子失去校验）。
    :164  门禁会标 UNKNOWN"，那是**过期的**…
  features/host/VipUnlock.kt
    :68  check_hook_signatures.py 会报 SIGNATURE-MISMATCH —— 这正是它存在的理由
  features/host/RC4Probe.kt
    :59  门禁按字面量解析，用 `cls.name` 会整块失去校验
  …
```

**它不自动判定**（判断"这条注释是否仍成立"需要理解语义，自动判定会误报）。
价值在于把核对从"想不起来要查"变成"照单核对"。

### 42.4 两条被实测验证的注释

不再靠读代码猜，直接做实验：

**① `VipUnlock.kt:68`** — 断言"少写第三个参数会报 `SIGNATURE-MISMATCH`"。
删掉第三个参数后：

```
SIGNATURE-MISMATCH  …VipCurrentStatusWebAction.onAction(
    Landroid/app/Activity;Lorg/json/JSONObject;)   (VipUnlock.kt:71)
```

**精确命中，还指出了缺哪个参数。** 注释准确。

**② `RC4Probe.kt:59`** — 断言"用 `cls.name` 会整块失去校验"。
把其中一条的类名换成变量后：

```
改前：check_hook_targets 看到 5 个 RC4 目标
改后：4 个                         ← 确实"整块失去校验"
```

**两条都成立**，已在行尾标注 `2026-10-26 已核对` 与验证方法。

### 42.5 这条工具该不该进门槛

**不进。** 理由与 ⑦ 不同：

* ⑦ 抓的是"测试假装自己测了"，那是**可机器判定**的（断言自我实现、静默跳过）；
* ⑫ 抓的是"注释可能过期"，机器**无法判定**真伪 —— 它只能列出候选。

一道无法判定的门禁，红与绿都不承载信息。它更适合当成**定期审计的清单**。

### 42.6 门禁

```
① 单元测试 81     ①b 抓取解析器 218
② assembleDebug    ③ parity 35 项
④ 钩子目标 116（0 INCOMPLETE，21 个 TYPE-ONLY 全部有 35+ 类引用）
⑤ 钩子签名 89      ⑥ 钩子调用方 62
⑦ 假测试扫描（4 类规则，0 命中）
⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面    ⑩ 读预算余量（余量 56%）
✓ 11/11 全绿
```

**仍未验证**：无（本轮为代码注释与判定体系的核对）。

---

## 43 第 34 轮：第 ⑪ 道门 —— 每条解析规则是否真被触发过

### 43.1 起因：一个我没系统查过的方向

门禁 ①b 一直在跑解析器测试，但从来没人问过：

> `capture_schema.py` 声明的那堆规则，**每一条都真的被数据触发过吗**？

两个方向都会出问题：

* **规则有、没人写** ⇒ 死规则（前缀改了没人更新，或功能删了规则留着）；
* **有人写、没规则** ⇒ 那行落到 `UNKNOWN`，读报告的人分不清"新前缀"与"解析器漏了"。

### 43.2 第一次查就用了错的方法，误判 15 条

我的第一版做法：把模块里 `Capture.append("XXX…")` 的首个词当"前缀"，
和 `RULES` 的 kind 名比对。结果报出 15 条"schema 有规则但模块没写"：`AD_BLOCK`、
`FORMULA`、`RC4UP`、`SIGN_PARAMS`…

抽样核对后发现全错：

```
kind = AD_BLOCK  →  实际行是 "blocked ad slot read: aj.a.d(3) -> null"
kind = ADSLOT_CALL → 实际行是 "ADSLOT call aj.a.d(3) #1"
```

**`kind` 名 ≠ 行前缀。** 按前缀比对当然得出一堆假缺口。

差点因此删掉几条好规则 —— 这正是"规则写窄/查法想窄"的同一个毛病，
只是这次发生在**审工具的方法**上，而不是工具本身。

### 43.3 换成正法：把样本喂进解析器，看每条 kind 是否命中

`kit/scripts/check_schema_roundtrip.py`：

```
[roundtrip] 样本 6 份，规则 53 条
[roundtrip] 命中过的 kind 53 个
[roundtrip] 全部规则都被真实样本触发过
[roundtrip] 样本里 565 行落在 UNKNOWN，原因：{'legacy-wrap': 560, 'truncated': 4, 'unknown': 1}
[roundtrip] 其中 1 处需人工看：
    all_prefixes.txt [fixture（负样本）] ts=16:42:16.200
```

**53 条规则全部被触发过** —— schema 是健康的。

那 565 行 UNKNOWN 也不是缺陷：
* `legacy-wrap` 560 行 —— 旧抓取里被换行撑开的残留；
* `truncated` 4 行 —— 被截断；
* `unknown` 1 行 —— fixture 里**故意放**的负样本 `this line has no known prefix at all`，
  用来证明解析器不会瞎认领。

工具现在会**区分这三种**，并指出 `unknown` 来自 fixture 还是真实抓取。

### 43.4 又撞到一个错误假设：`MARK`

我一开始把 `MARK` 写进 `INTERNAL`（"解析器自产品，不在规则表里"）。
实测：

```
规则总数: 53    MARK 在规则表里: True
```

`=== KdKit host=…/ sdk=36` 这行**有真实规则**。错误假设的代价是：
规则覆盖率少算一条 + 反向检查误报"解析器产出了表外 kind"。

这是本轮第二次"先假设、后被数据推翻"。两次都不是代码 bug，是**我对系统的理解与系统本身不符**。

### 43.5 反向验证

往规则表里塞一条永不匹配的死规则：

```
[roundtrip] **从未命中过的规则（1）**：
    DEAD_RULE_TEST ^ZZZ never matches
strict exit=1
```

还原后 exit=0。同时补了 5 条测试，其中一条专门钉住"`MARK` 是规则不是内部项"。

### 43.6 门禁

```
① 单元测试 81     ①b 抓取解析器 223
② assembleDebug    ③ parity 35 项
④ 钩子目标 116     ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（4 类规则，0 命中）
⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面    ⑩ 读预算余量（56%）
⑪ 解析规则往返（53/53 规则全被触发）
✓ 12/12 全绿
```

**仍未验证**：无（本轮为解析器与规则的对应关系）。

---

## 44 第 35 轮：接手第 36 个功能时撞到三处"两段拼接"的隐患

### 44.1 第 36 个功能 `page_request_log`

后台写的：钩 `dr.f.a`（7 个参数）—— 页面给 URL+params、**宿主用自己的签名器**发出的
公共出口。它一次覆盖 `encryptDataRequest` / `core_httpRequest` 等 3 个 action，
**新加 action 不必改代码**。这个设计比逐个钩 action 好，保留。

核实：`work/apktool_out/smali_classes6/dr/f.smali` 里
`.method public static a(Ldr/f$e;Ljava/lang/String;Ljava/util/Map;Ljava/lang/Class;ILorg/json/JSONObject;Lorg/json/JSONObject;)Lcom/android/volley/v;`
—— 7 个参数与代码完全一致。

### 44.2 隐患①：钩点用 `const val`，④ 完全看不见

文件里写的是：

```kotlin
private const val CLS = "dr.f"
private const val METH = "a"
Xp.hook(CLS, METH, ...)
```

④ 只按字面量解析，于是**完全看不到 `dr.f.a`**（只看到 `clazzOrNull("dr.f$e")` 那条）。
改成字面量后立刻列出 `OK dr.f.a [USED]`。

这是 `PARADIGM.md §7.6.1` 记过的规则。**同一个盲区已经出现三次**
（`RouteLog`、`HttpBodyProbe`、这次 `PageRequestLog`）。

### 44.3 隐患②：孤儿注释

我把 `CLS`/`METH` 内联后，它们的 KDoc 留下了：

```kotlin
/** `dr.f.a` 的类与方法。混淆名，升级后最可能失配 —— 启动日志会点名。 */

/** 单进程最多记这么多条… */
private const val MAX = 500
```

第一段注释描述的常量**已经不存在**。这正是第 33 轮"注释也是断言"的一个实例 ——
只不过这次是我自己刚制造的。

### 44.4 隐患③：`line()` 与调用方两段拼接，漏一段就静默变 UNKNOWN

`PageRequestOrigin.line()` 原本只输出 `PAGEREQ from=… url=… params=…`，
`method=` 由调用方另拼：

```kotlin
Capture.append(PageRequestOrigin.line(from, shownUrl, shape) + " method=$method")
```

而 schema 的正则**要求 `method=` 必须存在**：

```python
re.compile(r'^PAGEREQ from=(?P<from>\S+) url=(?P<url>\S*) '
           r'params=(?P<params>\S+) method=(?P<meth>-?[0-9]+|\?)\s*$')
```

**任何一处漏拼，整行就落 UNKNOWN**，而 UNKNOWN 在报告里只显示"一行没有规则认领"，
看不出是这里漏的。

实测确认了这个落差：

```
代码 shape（无 method）  → kind=UNKNOWN
schema 期望（带 method） → kind=PAGEREQ
```

修法：把 `method` 收进 `line()` 自己拼，`null` 时写 `?`（schema 的正则接受 `?`）。

```kotlin
fun line(from: String, url: String, params: String, method: Int? = null): String {
    val m = method?.toString() ?: "?"
    return "PAGEREQ from=$from url=$url params=$params method=$m"
}
```

**"方法未知"变成一个显式状态（`?`），而不是靠省略字段表达。**
这是本轮最有价值的一条 —— 省略字段是静默失败，写 `?` 是可观测的未知。

### 44.5 两处测试过期

**① `PageRequestOriginTest` 断言 `BRIDGE pageRequest`**，而实现已改成独立前缀 `PAGEREQ`。
实现的理由充分（`PREFIX_FEATURE` 由 `setdefault` 派生，一个 token 只能归属一个功能，
`BRIDGE` 已属于 `bridge_action_log`；复用会让 `grep BRIDGE` 失去意义）。
⇒ 更新测试，并在注释里写清"红的原因是实现更新、测试过期"。

**② `test_declared_counts` 里硬编码 `35`**：

```python
self.assertEqual(len(ids), 35, f'功能表行数与注册表不符：{len(ids)}')
```

加第 36 个功能时它必红，而红的原因是**测试过期**而不是代码有问题。
改成从 `parse_registry_objects()` 取真实数量。

**这类"写死数字的测试"和"写死标题的检查"是同一个毛病**（第 30 轮
`check_hook_sharing` 就栽在写死 `## 钩点共享` 上）。

### 44.6 门禁

```
① 单元测试 110（+1）   ①b 抓取解析器 253
② assembleDebug         ③ parity 36 项
④ 钩子目标 117          ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（4 类规则，0 命中）
⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面         ⑩ 读预算余量（56%）
⑪ 解析规则往返（53/53 规则全被触发）
✓ 12/12 全绿
```

**仍未验证**：`page_request_log` 在真机上是否真能抓到"哪个 action 让宿主发了请求"
（需要真机跑一轮带桥请求的页面）。

---

## 45 第 36 轮：一条从未执行过的代码路径

### 45.1 症状

门禁跑到 ①b 时首次失败、重试成功，然后脚本崩了：

```
▶ ①b 抓取解析器 ... RETRY ... PASS（首次失败，重试通过 …）
./scripts/verify.sh: line 89: name�: unbound variable
```

### 45.2 根因：全角括号被当成变量名的一部分

```bash
RESULTS+=("PASS  $name（重试）")      # ← `（` 是全角括号
```

Bash 解析变量名时，`（`（U+FF08）**不是**它认识的边界字符，于是 `$name（重试）`
被当成一个变量名 `name（重试`（后半截因编码问题显示成 `name�`），报 unbound。

修法是加花括号明确边界：

```bash
RESULTS+=("PASS  ${name}（重试）")
```

### 45.3 值得记的不是 bug 本身

这个 bug **只在"首次失败、重试成功"这一条路径上触发**。

自从第 28 轮加重试机制以来，这条路径**从未被执行过** —— 那段时间里门禁要么全绿
（走不到重试），要么重试后仍失败（走另一条 `FAIL` 分支）。

所以它是一个**潜伏了三轮、只在特定时序下才现形**的错误。这轮恰好同时满足了两个条件：
并行轮次正在写文件（触发首次失败）+ 重试时写完（重试成功）。

### 45.4 教训：新分支写完要立刻逼它执行一次

加 `RETRY` 那段代码时，我只验证了"全绿时它不碍事"，没验证"重试成功时它做什么"。

这条和前面几轮的教训是同一条（"规则写窄"、"测试假装测了"）的不同侧面：

> **代码路径的可信度不取决于它是否存在，而取决于它是否被执行过。**

本轮补做了反向验证 —— 用状态文件构造"首次失败、重试成功"：

```
▶ ①b 抓取解析器 ... RETRY ... PASS（首次失败，重试通过 …）
  PASS  ①b 抓取解析器（重试）
```

崩错消失，分支正常工作。

### 45.5 门禁

```
① 单元测试 110      ①b 抓取解析器 253
② assembleDebug      ③ parity 36 项
④ 钩子目标 117       ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（53/53）
✓ 12/12 全绿
```

**仍未验证**：无（本轮为门禁脚本自身的缺陷）。

## 45 第 36 轮：任务清单的 ①②③ 其实都做完了 —— 真正坏的是**校验它们的那道门**

### 45.1 先修红：接手时 ① 是红的，两个原因都不是逻辑 bug

本轮开局 `./scripts/verify.sh --quiet` 是**红的**：

| 现象 | 根因 | 性质 |
|---|---|---|
| `e: PageRequestLog.kt:136 Argument type mismatch: String vs Int?` | 调用方把 `method` 先 `.toString() ?: "?"` 再传给 `line(Int?)` | 并行轮次的半成品，与 `line()` 自己的注释直接冲突 |
| `e: PageRequestOriginTest.kt:172 Missing '}'` | 测试函数缺一个 `}` | 同上，写了一半 |

两条都在我读文件的过程中被并行轮次自己修好了（时间戳对得上）。
记录这一点是因为**"红"本身不区分"别人正在写"和"真的坏了"** ——
下次遇到同样的红，先看 mtime 与文件的完整度，别急着改别人的半成品。

修完后 **12/12 全绿**。

### 45.2 任务清单 ①②③ 逐条复核：都已完成，且都能复跑

| 任务 | 结论 | 复跑证据 |
|---|---|---|
| ① 解析器识别新前缀 + 离线单测 | **已完成** | `RULES` 54 条，11 个新前缀全部有 `CASES` 行；`test_capture_schema.py` 39/39 kind 被引用；门禁 ①b 223 项 |
| ② 重写 ACTIVITY / VERIFICATION 对齐口径 | **已完成**（但**校验它的门禁**有洞，见 §45.3） | `ACTIVITY.md` 24+12=36 与 `FEATURES_WITH_CAPTURE`/`FEATURES_LOGCAT_ONLY` 一致；`VERIFICATION.md` 36 行由生成器产出；`module_activity.py --dir ... --out` 重跑只有我本轮新增的一节差异 |
| ③ `check_hook_targets.py` 加"有没有调用方" | **已完成** | 该脚本已有 `--no-callers` 开关 + `LIVE/SELF-ONLY/…` 分层，且**独立成第 ⑥ 道门**（`check_hook_callers.py`）；`BrushMaskView` 是可复跑断言（`test_smali_usage.py::RealApk`） |

**这已经是第三次**「清单说未做、代码早做完」（前两次见 §7 与 §9）。
所以本轮不重做它们，而是去查**为什么它们能被做完了却没人发现**。

### 45.3 真问题：③ 这道门自己有三个盲区，三处过期数字一直亮绿灯

把 `check_declared_counts` 拆开看，它只认 4 种句式、只扫 3 个文件。
实测漏掉三处**真实过期**的声明：

| 位置 | 原文 | 实际 | 为什么没被抓 |
|---|---|---|---|
| `README.md:86` | `**35 功能**（35 个热开关）` | 36 | 正则只认带「个」的 `**N 个功能**` |
| `module/README.md:283` | `18 个功能逐行给出` | 36 | 这个句式不在表里（矩阵实际 36 行） |
| `module/PARADIGM.md:569` | `模块有 34 个功能` | 36 | **这个文件根本不在扫描清单里** |

第三处最值得记：**"哪些文件受检"本身也是会被写死的清单。**
另外 `README.md:86` 同句里的 `116 条可校验钩子目标 + 24 条签名级校验` 也过期了
（实测 `check_hook_targets` = **121**，`check_hook_signatures` = **95**）。

修法：补 3 种句式（`**N 功能**` / `模块有 N 个功能` / `N 个功能逐行`）+ 扩到 6 个文件
+ 修正全部 5 个数字。**同时加 12 条测试**钉住每种句式，其中 5 条专门钉"子集/单文件/序数
**不许**误报"（`这 12 个功能` / `AdFeatures.kt 的 7 个功能` / `第 29 个功能`）——
喊狼来了的门禁会被关掉。

### 45.4 修的过程中被自己的门禁绊了两次，两次都记进文档

**第一次**：我把"当时文档写的 34 个功能"写进 PARADIGM 的记录表格里，
门禁立刻报红 —— 它分不清**引用旧值**和**声称当前值**。
修法：反引号 / 直引号 / 书名号里的内容替换成等长空白，不参与匹配（6 条测试钉住）。
表格里第 1 行也因此改成散文数字 `32（热开关）`，不然它会一直绊自己。

这是"文档被门禁读"之后出现的**真实写作约束**：越诚实地记录历史，越容易误伤。

**第二次**：`check_verification_doc` 用 `cells[8]` 定位「真机」列。
插一列之后，它会认真地校验**另一列**，而且照样返回空错误 —— 与 §40
"结论依赖于目标在列表里的位置"同源。改成按表头名定位，并加 3 条测试。

### 45.5 `VERIFICATION.md` 的「依据」列一直指向无关轮次

生成器取 `subject[-1]`（**最后一个**主题命中的轮次），而关键词是**子串**匹配。
三处引用因此指向了完全不讲这个功能的轮次：

| 功能 | 旧引用 | 那一轮实际在讲 | 真正建功能的是 |
|---|---|---|---|
| `skip_onboarding` | R501 | 「把"七步的**可跳过性**"统计出来」（方法论） | **R11** 模块新功能 —— 跳过首次启动引导（含对照验收） |
| `pk_assist` | R28 | 「接口探测 —— 候选来自 A**PK** 字符串表」 | **R3** PK 自动作答实机复核（10/10 mock 命中） |
| `web_request_log` | R134 | 「页面地图补上…」 | **R119** 给模块加第 19 个功能 |

`APK` 里有 `PK` —— 一个纯子串把"接口探测"当成了 PK 助手的验证依据。
「依据」列是读者判断"这功能被证明到什么程度"的唯一入口，
指向一轮方法论讨论等于给没做过实验的功能背书。

修法两层（缺一不可）：**选轮次排序**（优先"建功能"措辞、其次取最早）+
**关键词边界**（ASCII 按词边界且区分大小写）。另修 `rid` 提取：
`R3 追加（同轮下半场）…` 这种没有 `·` 的标题原来会让整条标题当成轮次号。

### 45.6 `强 + 0 条` 这个看起来矛盾的组合，从来没人解释过

21 个「强」里有 **16 个**记录数是 0。两列回答不同问题：

* `强` = ROADMAP 有一轮以它为主题、且留了证据文件 ⇒ **历史做过实验**；
* `0` 条 = 这 5 份冻结抓取（采样止于 2026-10-18）里没有它写的行。

不解释就会读出两种相反的错结论：「强 ⇒ 已验证」或「0 条 ⇒ 坏了」。
已在 `VERIFICATION.md` 末尾加一节逐条列出并说明，并加机器守卫：
**任何一行的 `真机` 列被改成非「未验证」，测试就红**。

### 45.7 `MARK` 被静默排除：0 行这件事本身就没人看得见

`module_activity.py` 里写着 `k not in ('MARK',) and kinds.get(k, 0) == 0` ——
`MARK`（`=== KdKit host=…` / `=== HookCore start …`）在 5 份抓取里是 **0 行**，
而这一行把它从"没有样本"的表里硬编码剔除了：不说原因，也不在输出里提一句。
于是"这批抓取连一行启动标记都没有"在 `ACTIVITY.md` 里**完全没有痕迹**。

这与本项目修过的几次同类：**不是判错了，是根本没让它进入判定**。
改成从 `PREFIX_FEATURE[k] is None` 派生（新加无主前缀自动落入，不需改代码），
并新增 §四之二 显式列出，写明"不能据此说模块没启动过，标未验证"。

### 45.8 门禁

```
① 单元测试 110        ①b 抓取解析器 285（含 1 skip）
② assembleDebug         ③ parity 36 项
④ 钩子目标 121/121      ⑤ 钩子签名 95（86 吻合 / 0 不符 / 9 无法静态判定）
⑥ 钩子调用方 95（95 有外部调用 / 0 死代码）  ⑦ 假测试扫描（4 类规则，0 命中）
⑧ 钩点共享登记（2 处）   ⑨ 热修复暴露面
⑩ 读预算余量（56%）     ⑪ 解析规则往返（54/54 规则全被触发）
⑫ shell 变量边界（本轮由并行轮次新增）
✓ 13/13 全绿
```

新增测试 22 条：`test_declared_counts` +20（34 条）、`test_doc_generators` +12（34 条）。
（`test_doc_generators` 本轮之前是 26 条，现 34 条。）

### 45.9 仍未验证

* **真机全表未验证**：36 个功能的 `真机` 列一律 `未验证`，无设备。
  本轮新增的守卫保证它不会被悄悄改成别的值，但**守卫不产生证据**。
* **`MARK` 为什么 0 行未验证**：可能是采集时只截业务行，也可能是别的。
  需要重新 pull 一份完整抓取才能确定，本轮只把结论显式化，没有下判断。
* **中文关键词的子串误命中未根除**（`跳过` 仍匹配"可跳过性"）。
  排序已使它们不会成为被引用的那一轮，但匹配本身仍有假阳性。

---

## 46 第 37 轮：同一个 bug 连犯两次 ⇒ 做成门禁

### 46.1 第二次犯

第 36 轮刚修完 `$name（重试）` 的全角括号问题（`name（重试` 被当成变量名）。
五分钟后，我在写 ④⑤⑥ 的 SKIP 分支时**又写了一遍**：

```bash
for g in "④ 钩子目标" ...; do
  RESULTS+=("SKIP  $g（--no-apk）")     # ← 同样的问题
done
```

跑起来立刻炸：`line 153: g�: unbound variable`。

**同一个错误连犯两次，说明"下次注意"不管用。**

### 46.2 为什么要做成门禁而不是靠小心

这个错误有三个特点，全都指向"必须机检"：

| 特点 | 后果 |
|---|---|
| 只在**走到那条分支**时才炸 | 第一次潜伏了三轮才现形 |
| 报错是 `name�: unbound variable` | `�` 是编码替身，看不出是变量名边界问题 |
| `bash -n` **不报** | 语法合法，是运行时展开问题 |

尤其第三条：`bash -n` 是我改完脚本后必跑的自检，而**它对这个 bug 完全无效**。
我一直以为"跑过 `bash -n` 就安全了"，这轮证明不是。

### 46.3 `check_shell_vars.py`

找 `$var` 后面**直接**跟非 ASCII 字符的地方（`${var}` 已加花括号的不报）。
反向验证：

```
[shell-vars] 1 处 `$var` 后面直接跟了非 ASCII 字符 —— 会 unbound variable：
  module/scripts/verify.sh:89  $name 后跟 '（'（U+FF08）
      RESULTS+=("PASS  $name（重试）")
      修法：${name}（…
strict exit=1
```

**报错带行号、变量名、字符码位、修法** —— 看到就能改，不用再想一遍为什么。

### 46.4 顺带修掉的另一个"消失 vs 跳过"

查 `--no-apk` 分支时发现：④⑤⑥ 在同一个 `if` 块里，跳过时**只写 ④ 一条 SKIP**，
⑤⑥ 直接从报告里**消失**。

读报告的人会以为"这轮只有 10 道门"，而不是"3 道没跑"。

> **消失与跳过是不同的：跳过的会让人问"为什么跳过"，消失的连问都不会问。**

修成三条都显式 SKIP：

```
SKIP  ④ 钩子目标（--no-apk）
SKIP  ⑤ 钩子签名（--no-apk）
SKIP  ⑥ 钩子调用方（--no-apk）
```

### 46.5 门禁

```
① 单元测试 110      ①b 抓取解析器 253
② assembleDebug      ③ parity 36 项
④ 钩子目标 117       ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（53/53）  ⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：无（本轮为门禁脚本自身）。

---

## 47 第 38 轮：第 37 个功能暴露了生成器的一个正则缺陷

### 47.1 接收第 37 个功能

`parent_ctrl_probe`（03:51 由后台写入）：钩 `dj.e.f()` 拿 `ParentCtrlData`，
记录家长模式四个子项的服务端下发形状。核实通过：

* `.method public final f()Lcom/kuaiduizuoyе/scan/activity/parentmodel/util/ParentCtrlData;` ✅ 存在；
* 钩点**用了字面量** `Xp.hook("dj.e", "f", …)` —— 这次没踩 `const val` 盲区。

### 47.2 但它让 `VERIFICATION.md` 少了一行

③ 报 `VERIFICATION.md 缺少 parent_ctrl_probe`。重新生成后**仍然缺**。

查 `feature_matrix.py`：

```python
re.finditer(r'object\s+(\w+)\s*:\s*SwitchFeature\(([^)]*?)\)\s*\{', body, re.S)
```

`[^)]*?` 会在**第一个右括号**处停下。而 `ParentCtrlProbe` 的构造参数里写着：

```kotlin
summary = "钩 dj.e.f()（家长控制数据的唯一汇聚点…）"
```

那个 `f()` 的右括号让正则提前收尾 ⇒ 整个 object 解析失败 ⇒ 该功能在
`VERIFICATION.md` 里**直接消失**。

**这是本项目第一次出现"新功能让生成器解析失败"**。之前的 36 个功能都没在
`summary` 里写括号，所以这个缺陷潜伏至今。

### 47.3 修法与它的代价

改成允许一层括号嵌套：

```python
r'object\s+(\w+)\s*:\s*SwitchFeature\(((?:[^()]|\([^()]*\))*)\)\s*\{'
```

扫全模块验证：**36 个解析成功，1 个失败** → 修复后 37 个全部成功。

代价记录：只支持一层嵌套。若将来有人在 summary 里写 `f(g(x))`，会再断一次。
真出现时改成小型的括号平衡扫描，而不是继续加嵌套层数 ——
**正则套正则的尽头是解析器**。

### 47.4 一个"看起来是内容问题、其实是解析问题"的诊断教训

③ 的报错是：

> `VERIFICATION.md 缺少这些功能行：parent_ctrl_probe`

这条信息指向的是**文档内容**（"是不是生成器没跑？文档没更新？"），
而真正的原因是**生成器读不到这个功能**。

诊断路径走对了是因为做了一步"手动跑生成器到 /tmp 看输出里有没有"——
如果不做这步，就会一直在文档层面找问题。

**记下这条**：当"生成器产物缺一行"时，先确认**生成器自己是否认识这个输入**，
再怀疑"产物是否过期"。

### 47.5 三处计数需要同步（每次加功能都要）

这次漏了两个：

| 位置 | 类型 |
|---|---|
| `README.md` / `module/README.md` 的功能数与热开关数 | 手写 |
| `module/PARADIGM.md` §10 "模块有 N 个功能" | 手写 |
| `module/ACTIVITY.md` §七之二 "下面 N 个功能…" | 手写 |
| `kit/python/capture_schema.py` 的 `FEATURE_IDS` | 手写元组 |

其中最后一条这次我**改错了位置**（以为 `page_request_log` 在某行的中间，
实际它单独占一行），改完 `grep` 一下才发现没生效。

§七之二 那条正文计数由测试 `test_appendix_claim_matches_table_rows` 守着 ——
**这次正是它抓到了"正文说 10 个、表里 11 行"**。手写数字 + 测试强制相等，
这个设计是对的。

### 47.6 门禁

```
① 单元测试 110      ①b 抓取解析器 253
② assembleDebug      ③ parity 37 项
④ 钩子目标 117       ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（53/53）  ⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：`parent_ctrl_probe` 在真机上是否真能读到四个闸门的服务端取值
（需要家长模式被服务端开启的账号）。

---

## 48 第 39 轮：同一类正则缺陷的第三处，以及一次自我更正

### 48.1 上轮的缺陷可能有兄弟，于是全扫一遍

第 38 轮 `feature_matrix.py` 的 `([^)]*?)` 让第 37 个功能从文档消失。这轮的起点是：
**还有别的地方用 `[^)]*` 解析 Kotlin 吗？**

扫出来 6 处，其中值得处理的是 `LOOP_LIST_RE`（出现在两个文件里）：

```python
LOOP_LIST_RE = re.compile(r'for\s*\(\s*(\w+)\s+in\s+listOf\(([^)]*)\)\s*\)')
```

它负责识别 `for (x in listOf("a","b")) { Xp.hook(x, …) }` 这种写法 ——
**门禁靠它才能追踪循环里的钩子**。

实测脆弱性：

| 写法 | 旧正则 |
|---|---|
| `listOf("a.b.C", "d.e.F")` | ✅ 匹配 |
| `listOf(clazzOrNull("x.Y").name, "d.e.F")` | ❌ **整段失配** |

失配的后果是循环里的**所有**钩子对门禁隐形，而门禁保持绿色。

### 48.2 但当前没有真实影响 —— 以及一次自我更正

我改完正则后看到目标数从 `117` 变成 `123`，一度想记成"修复让 6 个钩子重见天日"。

**做了 A/B 对比才发现不是**：

```
旧正则 → [check] 123 hook target(s) declared in the module
新正则 → [check] 123 hook target(s) declared in the module
```

**完全一样。** 那个 `117` 是并行轮次正在写文件时的中间读数，
不是"修复前"的真实值。

扫全模块也确认：现有 12 处 `listOf` 全是纯字符串列表，**没有一处嵌套**。

所以这次的加固**不改变任何现有解析结果**，它防的是"以后有人这么写"。

> **教训：看到数字变化时，先做 A/B 对比再归因。**
> 这个仓库有并行写入者，任何"改完数字涨了"都可能只是抓到了不同的时序快照。

### 48.3 两份实现必须一致

`LOOP_LIST_RE` 在 `check_hook_targets.py`（④）和 `check_hook_signatures.py`（⑤）
各有一份。分开维护会漂移 —— 一处加固、另一处没加固，于是**两道门对同一份源码
得出不同的钩子集合**，那种不一致极难查。

补了一条测试直接比 `pattern`：

```python
self.assertEqual(ht.LOOP_LIST_RE.pattern, hs.LOOP_LIST_RE.pattern, '…已漂移')
```

反向验证：把其中一份改回旧写法 ⇒ 精确报"已漂移"。

### 48.4 同类缺陷的完整清单（三处）

| 位置 | 写窄的是什么 | 症状 |
|---|---|---|
| `feature_matrix.py` | `SwitchFeature(...)` 的参数 | 第 37 个功能从文档消失 |
| `check_declared_counts` | 只认分数形式的开关计数 | 3 处数字过期数月 |
| `LOOP_LIST_RE` | `listOf(...)` 的参数 | 循环里的钩子对门禁隐形（**当前无实例**） |

三处共性是：**用 `[^X]*` 匹配"可能有嵌套的结构"**。这不是偶然 ——
它在简单输入上永远工作，只在嵌套时静默失败。

### 48.5 门禁

```
① 单元测试 110      ①b 抓取解析器 256（+3）
② assembleDebug      ③ parity 37 项
④ 钩子目标 123       ⑤ 钩子签名 89    ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（53/53）  ⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：无（本轮为解析器健壮性）。

---

## 49 第 40 轮：清单①的"最后一层" —— 前缀认得，字段却不认得

### 49.1 清单①实际早就做完了，那这一轮在修什么

任务清单 ① 写的是"扩充解析器以识别 11 个新前缀，并补各自的离线单测"。
本轮先逐条去核，结论是**这一层确实已经在早前轮次落地**：

| 判据 | 实测 |
|---|---|
| 11 个 token 都登记 | `EXITCALL`/`EXITSTACK`/`BRIDGE`/`VIP`/`UPDATE`/`ONBOARD`/`APPSIGN`/`RC4PT`/`GUARD`/`WEBREQ`/`HDR` 全部在 `PREFIX_FEATURE` 里，feature 归属逐个正确 |
| 每条规则都有逐字段用例 | `ParseEveryPrefix.CASES` 共 **72** 条，11 个 kind 全部命中；`EveryPrefixHasATest` 强制"每条规则都要有用例" |
| 真实产出格式能解析 | 把 Kotlin 侧的真实字面量（`BRIDGE downloadMedia type=$type url=$shown`、`HDR(v) … pid=cube :: …`、`EXITSTACK #1 … ⏎ …`）逐条喂进去，`kind`/`variant`/字段全部正确 |
| Kotlin→schema 方向有漂移门禁 | `KotlinSideDrift.test_every_literal_prefix_is_declared` 从现在源码反扫字面量 |

所以"再加一遍前缀"只会制造重复。**真正的缺口在更细的一层**：

> 门禁只校验**行前缀 token**，从不校验**行内字段名**。

`BRIDGE downloadMedia type=$type url=$shown` 里的 `type=` 改成 `kind=`，
前缀还在、行还是那一行、`test_every_literal_prefix_is_declared` 照旧全绿，
但规则正则不再匹配 ⇒ **整行落到 `UNKNOWN`**，按功能统计直接少一类事件，
而且没有任何门禁会红。它的症状与"宿主把这个字段改名了"完全一样，
排查得翻 smali 才能区分。

### 49.2 先修一个真实丢字段的地方：`WATERMARK` 的 `scope`

`WATERMARK off applied | scope=webpic` 这一行由 `web_picture_watermark` 写，
`WatermarkOff` 写的是无后缀的 `WATERMARK off applied`。两者**共用同一前缀、
同一 variant** —— 因为 `PREFIX_FEATURE` 由 `setdefault` 派生，一个 token 只能
归属一个功能。

于是 `scope` 是**唯一能把两条链路分开的字段**。而旧解析器把它整个并进
`note` 字符串：

```python
# 旧
return {'note': m.group(1).strip()}
# 'off applied | scope=webpic'  ← 要拿 scope 只能再 split 一次，没人会这么做
```

后果：按功能统计时"导出合成"与"浏览页本地绘制"永远合成一个数字，
而这两件事的生效条件完全不同（前者看服务端是否重新合成，后者看本地是否绘制）。

改成结构化键，并**不补默认值**：

```python
{'note': 'off applied', 'scope': 'webpic'}   # 写了
{'note': 'off applied', 'scope': None}       # 没写 —— 不猜成 'export'
```

"没写"与"写了 `export`"是两件事，猜一个值就等于伪造来源。

### 49.3 把这一层做成两道可判定的断言

新增 `KotlinFieldNamesAreRecognised`（两个用例）：

| 用例 | 方向 | 判定方式 |
|---|---|---|
| `test_kotlin_field_names_are_all_produced` | Kotlin → schema | 抽 Kotlin 字面量里的 `name=`，要求该 kind 的解析器**产出**同名键（或大小写等价），否则报"字段被吞" |
| `test_regex_named_groups_reach_fields` | schema 内部 | 正则命名分组捕获到的**值**必须出现在 `fields` 里（键名可比、值不能丢），否则报"白抓了，列恒为 None" |

两个都做了**注入式反向验证**（不做就是又一条假测试）：

```
注入 POPWIN 丢掉 group('type')   → 精确报红：POPWIN.type ← /^POPWIN seen type=(?P<type>\S+)…/
注入 Kotlin 把 type= 改成 kind=  → 精确报红：BridgeActionLog.kt [BRIDGE] kind= ← …
恢复后                          → 全绿
```

第二道检查判定的是**值**而不是键名，因为 builder 会改名
（`len`→`length`、`ver`→`version`、`sd`→`shouldDecode`、`cut`→`truncated`）。
按名字比对会把 4 个正确实现判成缺陷。

### 49.4 覆盖边界（实测，不是估计）

54 条规则里 **21 条用命名分组、33 条只用位置分组**。第二道检查只覆盖前者。

试过把位置分组也按"值是否落进 fields"一起查，得到 **14 条假阳性**，
因为它们全是**有意转换**：

| 样本 | 转换 | 为什么按值比对会误报 |
|---|---|---|
| `SIGN params: _t_=1 \| abis=1` | `_kv_pairs()` 拆成 3 个键 | 整串不可能出现在任何单值里 |
| `HDR … Content-Type=x \| User-Agent=y` | 同样拆进 `fields` 字典 | 同上 |
| `EXITCALL … (stack suppressed)` | 转布尔 `stack_suppressed` | 文本变布尔 |
| `REQBODY … …+5` | 转 `omitted=5` | 文本变计数 |

一个按值比对的检查**分不清"合并/拆分/布尔化"与"白抓了"**。所以：

* 能判定的只有命名分组那一半 —— **就把这一半判死**；
* 另一半靠 `EveryPrefixHasATest` 兜底：它要求每条规则都有用例，而用例里写的就是
  **完整的期望字段字典**，位置分组漏返回同样会红（`EXITSTACK` 丢 `stack` 会被抓到）。

这不是"降低标准"，是把检查放在**它真的成立**的位置上。假装全覆盖比承认边界更危险。

### 49.5 门禁

```
① 单元测试 110      ①b 抓取解析器 287（+2，含 1 skip）
② assembleDebug      ③ parity 37 项
④ 钩子目标 121       ⑤ 钩子签名 95    ⑥ 钩子调用方 95（0 死代码）
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（54/54）  ⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：`scope=` 两条链路在真机上的实际产出比例（无设备）。
本轮只保证"写出来的能被原样拆开"，不保证"宿主一定会写"。

---

## 50 第 41 轮：⑪ 逐条正则检查第一次抓到真问题，以及一条装不上的钩子

### 50.1 ⑪ 的逐条正则层立刻发挥了作用

上轮刚加的"逐条正则"层，这轮就抓到并行轮次新增的 `PCTRL` / `PCTRLW`
（第 37/38 个功能）没有样本：

```
[roundtrip] **4 条正则从未被样本命中**：
  [44] PCTRLW  ^PCTRLW aiwriting=… book=… mask=0x… from=… userMode=…
  [45] PCTRL   ^PCTRL aiwriting=… book=… mask=0x…
  [46] PCTRL/unavailable   ^PCTRL unavailable reason=(?P<reason>\S+)\s*$
  [47] PCTRLW/unavailable  ^PCTRLW unavailable reason=(?P<reason>\S+)\s*$
```

补了 4 条 fixture 后 58 条正则全部命中。

### 50.2 但同一批里有个真 bug：钩子装不上

⑤ 报：

```
SIGNATURE-MISMATCH  dj.e.l()  (ParentModeWriteProbe.kt:89)
```

查 smali：

```
.method private final l(Lcom/kuaiduizuoye/scan/activity/parentmodel/util/ParentCtrlData;ILcom/baidu/homework/base/Callback;)V
```

**真实签名是 3 个参数**，而模块写的是 `Xp.hook("dj.e", "l", gate = id, …)` —— 一个都没传。

更值得注意的是 `record()` **完全按 3 个参在写**：

```kotlin
val data = args[0] ?: …          // ParentCtrlData
val from = args.getOrNull(1) as? Int   // from
// args[2] 是 Callback，不读
```

也就是说：**实现逻辑假设有 3 个实参，钩子声明却一个都没有。**
如果就这么发出去，Xposed 会因为形参数不匹配而拿不到 `args`，
表现为"功能装了、日志正常、但永远没有抓取行" —— 典型的静默失效。

⑤ 门禁（比对形参类型）正是为这种情形存在的，这次抓得很准。

### 50.3 修的时候踩了两次

**第一次**：补了两个形参但用变量传：

```kotlin
val cb = Xp.clazzOrNull("…Callback")
val dataCls = Xp.clazzOrNull("…ParentCtrlData")
Xp.hook("dj.e", "l", dataCls, Int::class.javaPrimitiveType, cb, …)
```

⑤ 仍然报 MISMATCH，而且这次它拼出的是 `l(LParentCtrlData;I)` —— **少了一个**。
原因：⑤ 只按**字面量**拼签名，变量它看不见。

**第二次**：改成 `Xp.clazz("…")`（返回 `Class<*>` 的工厂函数，参数仍是字面量）：

```kotlin
Xp.hook("dj.e", "l",
    Xp.clazz("…ParentCtrlData"), Int::class.javaPrimitiveType, Xp.clazz("…Callback"), …)
```

⑤ 通过，签名完整：`l(LParentCtrlData;ILCallback;)V`。

**教训**：⑤ 的"只认字面量"不是缺陷，是设计 —— 它要求钩子声明**在源码里可静态读出**。
任何包装（常量、变量、工厂函数的返回值）都会让它失明。这条已记在 `PARADIGM.md §7.6.1`，
但这次连"工厂函数里传字面量"都会被它识别（因为它扫的是整行的字面量序列），
边界值得记住。

### 50.4 报告脚本的"每个 kind 都要有分支"

①b 另外两条失败指向 `capture_transcript.py` 与 `session_report.py`：
测试要求**每个 kind 都产生实际正文**，不能只被计数。

这条约束很实在 —— 它防的是"规则加了、报告没跟上，于是那个前缀在新报告里等于不存在"。

补了两处：

* `capture_transcript.py`：`PCTRL`/`PCTRLW` 的读侧/写侧/`unavailable` 三种渲染；
* `session_report.py`：同样三态，外加"其中 N 条读不到（reason=…）"的汇总 ——
  这比只报总数有用：**"钩到了但读不到"和"根本没有这一行"是完全不同的结论**。

### 50.5 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity **38** 项
④ 钩子目标 123       ⑤ 钩子签名 90    ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（**58 条正则全部命中**）
⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：`PCTRL`/`PCTRLW` 只在 fixture 与单测里验证过；真实抓取需要家长模式
被服务端开启的账号，且走一次"读设置 + 提交设置"。

---

## 51 第 42 轮：⑤ 因为"一个形参读不到"就放弃了整条校验

### 51.1 一个对不上的覆盖数

对比 ④ 与 ⑤ 的覆盖：

```
④ 钩子目标：124 个目标
⑤ 钩子签名：只校验了 53 个
```

差的 71 个里，有 21 个是 `OK(platform)`（android/java 平台类，无 smali 可比）、
14 个是 `OK(hookAll)`（钩全部重载，形参无需比对）—— 这两类都是**合理豁免**。

真正的问题在 **7 个 `UNKNOWN(signature not statically resolvable)`**。

### 51.2 根因：`ok = False; break`

```python
else:
    ok = False          # 变量 / 常量 / 三元表达式：静态不定
    break
...
'sig': '(' + ''.join(desc) + ')' if ok else None,
```

**只要有一个形参读不到，整条签名就被丢弃。** 看 `dr.f.a` 的实例：

```kotlin
Xp.hook("dr.f", "a",
    callback,                  // ← dr.f$e，运行时解析的变量
    String::class.java,        // 后面 6 个都是字面量
    ...)
```

7 个形参里 6 个是字面量，完全可以校验 —— 但第一个读不到，于是 ⑤ 说"全都不知道"。

**这是"全有或全无"的设计缺陷**：它把"部分未知"当成了"完全未知"。

### 51.3 改成 `*` 通配占位

读不到的形参写 `*`（匹配任意一项），**其余仍然逐位比对**：

```
dr.f.a(DLdr/f$e;…)                      →  dr.f.a(*Ljava/lang/String;Ljava/util/Map;…)
```

结果：

| | 改前 | 改后 |
|---|---|---|
| 校验数 | 53 | **62** |
| `UNKNOWN(signature…)` | 7 | **0** |
| `MISMATCH` | 0 | **0** |

### 51.4 但先撞出三个"门禁自己造的假红"

改完立刻冒出 8 个 MISMATCH，逐个查**全是解析 bug**，不是真实错误：

**① 行尾注释被当成形参名**

```
SIGNATURE-MISMATCH  dr.f.a(Ldr/f$e;L// dr/f$e  —— 网络回调
```

签名里出现了中文 —— `split_args` 没剥 `//` 注释。

**② Kotlin 的 `Array<T>` 没映射成 JVM 数组**

```
LArray<Any>;   ← 应为 [Ljava/lang/Object;
```

**③ Kotlin 的 `Any` 没映射**

```
LAny;          ← 应为 Ljava/lang/Object;
```

三条都是 `to_desc` / `split_args` 的缺口。修完后 MISMATCH 归零。

**这个顺序值得记**：先改逻辑（通配），再修新暴露的解析缺口 ——
因为**旧代码从没走到那些分支**（它在第一个未知形参就 break 了）。
通配让解析器第一次真正读完整个形参列表，于是把它一直没处理的语法暴露出来。

### 51.5 关键验证：通配没有削弱检错能力

改通配最容易出的问题是"太松，什么都能匹配"。所以必须反向验证：

删掉 `VipUnlock` 钩子的第三个形参 ⇒

```
MISMATCH 数 = 1     ← 仍然精确报出
还原后 exit=0
```

**已知部分仍然逐位比对**，`*` 只吃它自己那一位，不会顺带放过相邻的错误。

### 51.6 一处期望值也要跟着改

`test_doc_generators` 里 `net_error_probe` 期望 `(0, 1)`（"静态可解析 0 个"），
现在变成 `(1, 1)` —— **这是改进**：它那条 `(*Ljava/lang/String;)` 真的被校验了。

改的时候在注释里写清了"为什么变"，避免下次有人以为是被改坏了。

### 51.7 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity 38 项
④ 钩子目标 124       ⑤ 钩子签名 **62 条（+9）、0 UNKNOWN**    ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（58 条正则全部命中）
⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：`dr.f.a` / `ei.y.H` / `PatchProxy.proxy` 这三条的签名比对依赖
`*` 占位，真机上形参类型是否真如 smali 所示（混淆类可能被壳运行时改写）未实测。

---

## 52 第 43 轮：一次"没找到新功能"的排查，以及它排除掉的东西

### 52.1 出发点

38 个功能覆盖了广告、桥、网络、签名、家长模式、水印、退出守卫……要说空白，
最像的是"崩溃观测"和"下载观测"。这轮去查了，两个都**没有走通**，但排除过程有价值。

### 52.2 排除项一：崩溃入口找不到宿主自己的

`UncaughtExceptionHandler` 全 APK 只有 3 处，全在**广告 SDK** 内部
（`com.baidu.mobads.*`），宿主自己不用这个机制。搜
`CrashHandler|CrashReport|catchException` 也没有独立的宿主类。

**结论**：崩溃观测只能钩 `Thread.setDefaultUncaughtExceptionHandler` 这个平台方法 ——
但那已经属于"框架级"而非"宿主特有"，且 `exit_guard` 已经在拦退出路径。
收益不足以开一个新功能。**放弃。**

### 52.3 排除项二：作业提交没有可识别的命名

`submitHomework|SubmitHomework|uploadAnswer` 在 220 个 smali 里零命中。
混淆后这类业务方法名不会保留语义 —— 靠名字找必然失败，
而靠"从 UI 反推"需要真机，当前没有。

**结论**：这条路在无真机条件下成本过高。**放弃。**

### 52.4 排除项三：重试逻辑存在，但不构成独立观测点

`Net.smali` / `HWRequest.smali` 确有 3–4 处 `retry` 相关引用，
但方法名里没有 `retry*`，`RetryPolicy` 也没在这些类里被调用 ——
真正的重试在 Volley 内部（`com.android.volley.*`）。

**结论**：钩 Volley 的重试等于钩第三方库的内部实现，版本一变就废；
而 `net_error_probe` 已经记了错误码，重试次数对诊断的边际价值低。**放弃。**

### 52.5 顺手核实的三个"看着像缺陷"的地方 —— 都不是

扫"既无钩子也无 `Capture.append`"的文件，出来 5 个：

| 文件 | 实际情况 |
|---|---|
| `NativeExitGuard.kt` | 走 **seccomp**（加载 `libkdhide.so` 装过滤器），本来就不用钩子 |
| `HostAllowList.kt` | **纯匹配逻辑**，无 android/Xposed 依赖，可在 JVM 里精测 |
| `PkAssist.kt` / `PkScript.kt` / `WebScripts.kt` | 注入页面 JS，不经过钩子 |

五个全部**名副其实**。这条排查没抓到缺陷，但把"为什么它们没有钩子"记下来了 ——
否则下次还会有人重新查一遍。

### 52.6 一个数字的澄清：热开关是 37/38，不是 33/38

`hot` 在 `BaseFeature` 里的默认值是 **`false`**（`val hot: Boolean = false`）。
全模块有 37 处显式写了 `hot = true`，**只有 `NativeExitGuard` 没写** ——
它就是那唯一的冷开关，且理由是"seccomp 过滤器对该进程不可撤销，装了就一直在"。

所以 37/38 是正确的，`module/README.md` 里写的也是 37/38。

### 52.7 顺便量了一下"证据强度"的真实分布

```
强 21 / 中 16 / 弱 1
```

唯一的"弱"是 `web_picture_watermark`（第 34 个功能）：**钩子 2/2 在 APK 里解析成功，
但没有真机抓取证据**（0 行）。它第 34 轮才加，到现在还没上过真机。

这不是"文档偷工"，是**如实标注**：`ACTIVITY.md` 38 处"未验证"、
`VERIFICATION.md` 40 处，都在说同一件事 ——
**这个项目的静态证据链很完整，真机证据链还差得远。**

### 52.8 本轮产出

没有新功能。产出是三份"不要再查一遍"的排除记录 + 一处数字澄清。

> **排除也是结论。** 把"为什么这条路不通"写下来，
> 比把同一条路重走一遍更有价值。

### 52.9 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity 38 项
④ 钩子目标 124       ⑤ 钩子签名 62（0 UNKNOWN）  ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（58 条全命中）  ⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：`web_picture_watermark`（唯一的"弱"）—— 需要真机浏览大图确认水印未叠加。

---

## 53 第 44 轮：四次误报，零个真问题 —— 以及为什么这不算白干

### 53.1 起因

第 41 轮撞到过真问题：`robust_probe_all` 声明了却没人读（设置页会出现拨了没反应的开关）。
这轮想把同类问题扫干净。

### 53.2 第一层扫描：30 个选项全部有读取点

```
声明了 30 个选项
只出现 1 次（只有声明，没人读）: 0
```

干净。但这层太粗 —— "有读取点"不等于"读取结果真的被用"。

### 53.3 第二层扫描：我自己写出了一个全是误报的检查

想找"读了但结果被丢弃"的地方，写了个正则判据：

```python
if re.match(r'\s*\n', after) and not re.search(r'(=|if|return|\(|,)\s*$', before):
    count_unused += 1
```

报出 4 处"疑似丢弃"：

| 位置 | 我的结论 | 实际 |
|---|---|---|
| `RobustProbe.kt` | 疑似丢弃 | 第 167 行赋值后使用，**正常** |
| `RouteLog.kt` | 疑似丢弃 | `val dedupe = KdConfig.isOn(...)`，**正常** |
| `VipUnlock.kt` | 疑似丢弃 | 80/95 两处使用，**正常** |
| `NativeExitGuard.kt` | 疑似丢弃 | `val control = KdConfig.isOn(...)`，**正常** |

**4/4 全是误报。** 我判据的问题：`val x = KdConfig.isOn(...)` 这种"赋值后换行"被当成了"结果被丢弃"。

这和前面几轮反复出现的是同一个毛病 —— **静态正则看不出语义**。第 40 轮我已经在
"把 Kotlin 模板插值换成 X"上栽过一次，这次又栽在同类假设上。

### 53.4 于是放弃自己造检查，去验证已有的那道门

门禁 ③ 早就有这条检查（第 29 轮加的"幽灵键门禁"），而且第 41 轮它真的抓到过
`robust_probe_all`。所以这轮的正事变成：**反向验证它还灵不灵**。

把 `RouteLog` 里唯一的读取点改成常量：

```kotlin
val dedupe = dev.xalor.kdkit.config.KdConfig.isOn("route_log_dedupe", true)
        ↓
val dedupe = true
```

门禁立刻报：

```
✗ 声明了但代码里没人读的子选项（设置页会出现拨了没反应的开关）：`route_log_dedupe`(RouteLog.kt)
```

还原后 `✓ 功能表一致`。**这道门的判断是可靠的。**

### 53.5 这轮的方法论结论

> **当自己造的检查连续误报时，先怀疑检查，再怀疑代码。**
> 如果项目里已经有一道门在管这件事，正确的做法是**反向验证那道门**，
> 而不是再造一个更聪明的。

我这轮造的那个两层扫描，第二层 4/4 误报、零召回 —— 它唯一的价值是让我确认
"已有那道门是必要的"。

### 53.6 顺手记一个数字

`BaseFeature.hot` 的默认值是 `false`，全模块 37 处显式 `hot = true`，
只有 `NativeExitGuard` 没写 ⇒ **37/38 是热开关**。它冷的理由是
"seccomp 过滤器对该进程不可撤销，装了就一直在"。

### 53.7 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity 38 项
④ 钩子目标 124       ⑤ 钩子签名 62（0 UNKNOWN）  ⑥ 钩子调用方 62
⑦ 假测试扫描（0 命中）  ⑧ 钩点共享登记（2 处）
⑨ 热修复暴露面       ⑩ 读预算余量（56%）
⑪ 解析规则往返（58 条全命中）  ⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：无（本轮为检查方法的自我修正）。

---

## 54 第 45 轮：`(*)` 混在 `OK` 里 —— 5 条钩子其实一条都没受检

### 54.1 上轮加的通配，反过来要查它被滥用没有

第 42 轮给 ⑤ 加了 `*` 通配（一个形参读不到时占位，其余仍比对）。
这轮去量它的使用比例，找"通配过多"的地方：

```
8 / 62 条签名含 `*`
```

逐条看下去，发现其中 **5 条是纯 `(*)`** —— 而 `(*)` 匹配**任意个数的参数**，
等于这条签名什么都没比对。

### 54.2 其中 4 条是可修的：形参传了变量

`HostFeatures` 里四个广告 SDK 的 init：

```kotlin
val arg = Xp.clazzOrNull(ARG) ?: run { … }
Xp.hook("com.fastad.csj.FastAdCsjManager", "initCsjSDK", arg, …)
```

⑤ 按**整行的字面量序列**拼签名，`arg` 是变量 ⇒ 拼成 `(*)`。

我先试了 `Xp.clazz(ARG)`（常量间接），**仍然 `(*)`** —— ⑤ 不跟这层调用。
最后改成直接写 `Xp.clazz("xc.a")`：

```
OK  com.fastad.csj.FastAdCsjManager.initCsjSDK(Lxc/a;)
```

真实受检了。先核对了 smali，四条都是 `(Lxc/a;)`：
`initCsjSDK` / `initYlhSDK` / `initKsSdk` / `initBaiduSDK`。

**钩子本身一直是对的 —— 是门禁瞎了。** 修复的是"看得见"，不是"能用"。

### 54.3 剩下 1 条是结构性的：形参在运行时构造

```kotlin
Xp.hookCtor("cu.l", *ctorTypes(cls), …)     // ← 展开运算
```

`ctorTypes()` 里写死了 14 个类型（与 smali 完全一致），但它们在函数体里，
⑤ 看不到。这条**没法改成字面量**（构造器有 15 个形参，且是动态选的）。

所以它应当是"无从校验"，而不是"校验通过"。

### 54.4 于是给 `OK` 加了第三档

原先只有 `OK` / `UNKNOWN`。但 `(*)` 混进 `OK` 里会让"62 条通过"这个数字虚高。
加一档：

| 状态 | 含义 |
|---|---|
| `OK` | **逐个形参比对过** |
| `OK(opaque)` | 形参动态构造，无从校验（当前 1 条：`cu.l.<init>(*)`） |
| `OK(hookAll)` | 钩全部重载，形参无需比对（14 条） |
| `OK(platform)` | 平台类，无 smali 可比（21 条） |

### 54.5 这个判据我第一版写错了

第一版：

```python
status = 'OK(opaque)' if r['sig'].strip('();').strip('*') == '' else 'OK'
```

它把**零参数**的 `lk.a.k()` 也算成 opaque —— 报出 18 条，其中 17 条是误判。
零参数的 `()` 是**真正校验过的**（没有形参可以写错）。

改成"含 `*` 且除占位符外一个形参都没有"：

```python
inner = r['sig'][1:-1]
status = 'OK(opaque)' if ('*' in inner and inner.strip('*') == '') else 'OK'
```

结果精确为 1 条。**又是我自己造的判据第一次就错** —— 和上轮那个"4/4 误报"同一个毛病。

### 54.6 现在的真实数字

```
OK              61     ← 真正逐位校验过
OK(opaque)       1     ← 无从校验（cu.l 构造器）
OK(hookAll)     14
OK(platform)    21
MISMATCH         0
UNKNOWN          0
```

比第 42 轮的"62 条 OK"更诚实：那不是 62 条都受检，是 61 条受检 + 1 条瞎的。

### 54.7 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity 38 项
④ 钩子目标 124       ⑤ 钩子签名 **61 真校验 + 1 opaque，0 MISMATCH**
⑥ 钩子调用方 62      ⑦ 假测试扫描（0 命中）
⑧ 钩点共享登记（2 处）  ⑨ 热修复暴露面
⑩ 读预算余量（56%）   ⑪ 解析规则往返（58 条全命中）
⑫ shell 变量边界
✓ 13/13 全绿
```

**仍未验证**：`cu.l` 构造器的 14 个动态形参只在源码里与 smali 对过，
⑤ 无法自动比对 —— 这条只能靠人工核对（本轮已做，一致）。

---

## 55 第 46 轮：第一次拿到真机证据 —— 第 ⑬ 道门

### 55.1 七天内第一次出现设备

`adb devices` 回来一台 `emulator-5554`（Android SDK 36，`ro.kernel.qemu=1`）。
目标 App 没装、LSPosed 没装，所以**端到端仍然做不了** —— 但有一件此前从没验证过的事可以做了：

> **这个 APK 到底装不装得上、界面打不打得开？**

### 55.2 十二道门全都回答不了这个问题

回头看这十二道门：①①b 跑单测、② 编译、③ 对文档、④⑤⑥ 读 smali、
⑦ 扫假测试、⑧ 查钩点共享、⑨ 查暴露面、⑩ 查预算、⑪ 查规则、⑫ 查 shell 变量。

**全部是静态的。** 没有一道能发现"APK 装不上"或"一启动就崩"。

这不是疏漏 —— 静态门禁本来管的就是源码层面。但它意味着：
**在这个项目里，"能编译"和"能用"之间一直没有证据。**

### 55.3 实测结果

```
① APK 已构建（16M）                                    PASS
② 安装成功                                              PASS
③ 包已安装 / 启动入口可解析                              PASS
④ 启动成功（TotalTime 788ms）/ 无 FATAL                 PASS
⑤ 界面报告：已启用 14 / 38 项功能                        PASS
   界面总数 38 与 FeatureRegistry 条目数一致              PASS
⑥ LSPosed 未安装 ⇒ 跳过                                 SKIP
                                   合计：9 PASS / 0 FAIL / 1 SKIP
```

**最有价值的是第 ⑤ 条**：从系统无障碍树里读到 `已启用 14 / 38 项功能`，
并用它与 `FeatureRegistry.kt` 的实际条目数比对 —— 38 = 38。

这条断言补上了一个此前完全空白的验证：
**代码里注册的 38 个功能，是不是真的都渲染到界面上了？**
之前只能靠"gate ③ 说 README 和注册表一致"，而那只证明文档和代码数据一致，
不证明 UI 真的把它们画出来了。

### 55.4 还验证了持久化

点开关 → 计数 `13/38` → `14/38`，配置通道 `0 项` → `1 项`；
`force-stop` 后重启 → 仍是 `14/38`。

这说明整条链路是通的：点击 → 写 prefs → 重新统计 → UI 刷新 → 落盘。

**但这只证明"开关能读写"，不证明"功能生效"。** 后者要 LSPosed + 目标 App。

### 55.5 脚本化：`module/scripts/verify_on_device.sh`

四件事（装 / 开 / 读 / 崩）固化成脚本，接成第 ⑬ 道门。

**没有设备时跳过而非失败** —— 否则这个仓库在没有手机的环境里永远是红的，
而"永远红"等于"没人看"。

两个实现细节值得记：

* **UI 用文件 dump 而不是 `/dev/tty`**：实测 `/dev/tty` 读不到中文计数（输出被截断），
  写到 `/sdcard/*.xml` 再 `cat` 就能读到；
* **只把 `FATAL EXCEPTION` / `has died` 算崩**：普通的 `warn` 不算 ——
  否则一个 `ProfileInstaller` 的提示就能让门变红。

### 55.6 顺手被自己抓了一次

写完脚本跑门禁，**⑫ 立刻红了**：

```
module/scripts/verify_on_device.sh:68  $APK 后跟 '（'（U+FF08）
    else bad "APK 不存在：$APK（先跑 assembleDebug）"
    修法：${APK}（…
```

这正是第 36/37 轮连犯两次的那个 bug。**这次是写下去的当下就被拦住**，
而不是等它潜伏三轮再炸。

第 37 轮做那道门的理由是"同一个错误连犯两次说明下次注意不管用" ——
这轮给了它第一个真实回报。

### 55.7 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity 38 项
④ 钩子目标 124       ⑤ 钩子签名 61 真校验 + 1 opaque
⑥ 钩子调用方 62      ⑦ 假测试扫描（0 命中）
⑧ 钩点共享登记（2 处）  ⑨ 热修复暴露面
⑩ 读预算余量（56%）   ⑪ 解析规则往返（58 条）
⑫ shell 变量边界     ⑬ **真机验证（9 PASS / 0 FAIL / 1 SKIP）**
✓ 14/14 全绿
```

### 55.8 仍然未验证的（这条要说清楚）

真机证据只到"设置界面"这一层。以下**全部未验证**：

* 任何钩子是否真的拦住了宿主行为；
* `ACTIVITY.md` 里 38 处"未验证"标记的实质内容；
* `VERIFICATION.md` 里那个"弱"（`web_picture_watermark`）。

原因只有一个：**模拟器上没有目标 App，也没有 LSPosed。**
拿到真机 + 框架后，`verify_on_device.sh` 的第 ⑥ 段会自动升级为可跑状态。

---

## 56 第 47 轮：目标 App 真的跑起来了 —— 以及一条最隐蔽的失效被堵住

### 56.1 从"装得上"到"目标真的在跑"

上轮验证了模块自己装得上、界面打得开。这轮往前推了一步：**把目标 App 装上、启动、跑到隐私页之后。**

```
adb install com.kuaiduizuoye.scan-7.7.2-1811-168194.apk   → Success
am start -n com.kuaiduizuoye.scan/.AliasActivityDefault   → Status: ok, 1091ms
ps -A | grep kuaiduizuoye                                 → 进程存活
```

顺带纠正一个我原本会搞错的细节：启动入口**不是** `activity.main.MainActivity`
（那个不存在，`Error type 3`），而是 `.AliasActivityDefault` —— 宿主用了 activity-alias。

**这是七天内第一次看到宿主本身跑起来。** 前 46 轮所有关于宿主的结论都来自 smali 静态阅读。

### 56.2 一条静态门禁**永远**发现不了的失效

分析用的 APK 在仓库根目录：`com.kuaiduizuoye.scan-7.7.2-1811-168194.apk`。
设备上装的可能**不是同一份**：

* 渠道包不同（同一个 `versionName` 可以是不同字节）；
* 别人换过；
* 我拉错了文件。

如果设备上跑的是另一份，那么 **124 个钩子目标的"存在性"、89 条签名的"一致性"、
全部 smali 结论，都只对仓库里那份成立，对真实环境无效** —— 而十二道静态门禁
全都会是绿的。它们绿得理直气壮，因为它们比对的就是仓库里那份。

### 56.3 补上这条：比对设备上已安装 APK 的字节

`module/scripts/check_device_matches_analysis.sh`：

```
pm path com.kuaiduizuoye.scan   → /data/app/…/base.apk
adb pull                        → work/installed/base.apk
shasum -a 256 两边的 APK 比对
```

实测结果：

```
仓库: a4007a8d23365224…  (com.kuaiduizuoye.scan-7.7.2-1811-168194.apk)
设备: a4007a8d23365224…
PASS  设备上运行的就是我们分析的那份字节
```

**这条通过，意味着前面 46 轮的所有静态结论对真实环境成立。**

它现在是第 ⑬ 道门的第 ⑦ 段。没有设备 / 没装目标 App 时跳过而非失败。

### 56.4 三处"差一步"要说清楚

现在的真机状态是：

| 条件 | 状态 |
|---|---|
| 模拟器 | ✅ Android 36, arm64-v8a, `adb root` 可用 |
| 模块 APK | ✅ 装得上、界面正常、开关持久化 |
| 目标 App | ✅ 装上了、能启动、跑到隐私页之后 |
| **LSPosed/Vector** | ❌ **没装** |

`infra/` 里有全套材料（`Magisk-v30.7.apk`、`Vector-v2.2.zip`、`ramdisk-magisk.img`），
但搭起来要改 boot 镜像、重启、刷模块 —— 会让模拟器处在"可能起不来"的状态。

**这不值得在自动轮次里做。** 一次失败就丢掉整个可用的验证环境，
而现在的环境已经能给出 10 条真实证据。

所以第 ⑬ 道门现在的 ⑥ 段会明确输出：
`目标 App 已装、LSPosed 未装 ⇒ 差框架这一步；钩子无法生效`。

**"差一步"和"全都不会"是两种状态，报告里必须能分开。**

### 56.5 门禁

```
① 单元测试 110      ①b 抓取解析器 264
② assembleDebug      ③ parity 38 项
④ 钩子目标 124       ⑤ 钩子签名 61 真校验 + 1 opaque
⑥ 钩子调用方 62      ⑦ 假测试扫描（0 命中）
⑧ 钩点共享登记（2 处）  ⑨ 热修复暴露面
⑩ 读预算余量（56%）   ⑪ 解析规则往返（58 条）
⑫ shell 变量边界     ⑬ 真机验证（**10 PASS / 0 FAIL / 1 SKIP**）
✓ 14/14 全绿
```

### 56.6 仍然未验证的（精确边界）

* **任何钩子是否真的拦住了宿主行为** —— 差 LSPosed 这一步；
* `ACTIVITY.md` 38 处"未验证"的实质内容 —— 同上；
* `web_picture_watermark` 那个"弱" —— 同上。

**但现在可以确认的是：这些"未验证"不是因为环境缺太多，
而是精确地缺一样东西 —— 框架。** 这比上轮的"什么都没有"清晰得多。
