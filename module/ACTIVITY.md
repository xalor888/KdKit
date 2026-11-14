# 模块功能的实际触发面

* 输入：**1 份抓取**，共 **3779 行**
* 复现：`python3 kit/scripts/module_activity.py --capture work/packs/r793/capture.txt --out module/ACTIVITY.md`
* 口径来源：`kit/python/capture_schema.py`（前缀表的唯一声明处，被 6 个解析器 + 门禁 ①b 共用）

## 判据（这一节是"怎么读"，不是结论）

* **有抓取行的功能 30 个**：数它们自己写的前缀行数 —— 这是"确实执行过"的硬证据；
* **只写 logcat 的功能 11 个**：结构上不写抓取，本表给 `—`，不代表没工作；
* **出现份数**：在多少份输入里出现过。只在 1 份里出现 = 那一轮跑过，不能推断"一直在跑"；
* 计数为 0 的**不等于失效** —— 默认关的功能没触发、或该轮没走到那条业务路径，都是 0。要区分"没开"与"钩子失效"，看 `module_report.py` 的 audit 行。

## 一、有抓取证据的功能

| feature | 抓取行数 | 出现份数 | 上一轮 | 变化 |
|---|---|---|---|---|
| `log_sink` | 1551 | 1/1 | — | — |
| `sign_observer` | 1364 | 1/1 | — | — |
| `rc4_probe` | 488 | 1/1 | — | — |
| `h5_bridge_log` | 188 | 1/1 | — | — |
| `http_body_probe` | 105 | 1/1 | — | — |
| `native_probe` | 40 | 1/1 | — | — |
| `nav_log` | 12 | 1/1 | — | — |
| `popwin_gate` | 8 | 1/1 | — | — |
| `page_request_log` | 7 | 1/1 | — | — |
| `ad_probe` | 4 | 1/1 | — | — |
| `parent_ctrl_probe` | 4 | 1/1 | — | — |
| `bridge_action_log` | 2 | 1/1 | — | — |
| `rm_adconfig` | 2 | 1/1 | — | — |
| `skip_update` | 2 | 1/1 | — | — |
| `bridge_guard` | 0 | 0/1 | — | — |
| `exit_guard` | 0 | 0/1 | — | — |
| `md3_skin` | 0 | 0/1 | — | — |
| `native_exit_guard` | 0 | 0/1 | — | — |
| `net_error_probe` | 0 | 0/1 | — | — |
| `parent_ctrl_write` | 0 | 0/1 | — | — |
| `req_headers` | 0 | 0/1 | — | — |
| `rm_vip_promo` | 0 | 0/1 | — | — |
| `robust_probe` | 0 | 0/1 | — | — |
| `route_log` | 0 | 0/1 | — | — |
| `settings_entry` | 0 | 0/1 | — | — |
| `skip_onboarding` | 0 | 0/1 | — | — |
| `vip_limit_probe` | 0 | 0/1 | — | — |
| `vip_unlock` | 0 | 0/1 | — | — |
| `watermark_off` | 0 | 0/1 | — | — |
| `web_request_log` | 0 | 0/1 | — | — |

## 二、只写 logcat 的功能（本表结构上无法计数）

这 11 个功能改变行为或只走 `KdLog`，**不写抓取文件**。它们的"是否在工作"只能由模块日志的安装行 + 行为差异判断，不能由本表判断：

| feature | 为什么没有抓取行 |
|---|---|
| `anti_detect` | 反调试：只 `KdLog`（前 6 条 + 5 分钟心跳） |
| `block_ad_sdk` | 广告 SDK 阻断：同上 |
| `h5_debug` | H5 调试台：注入 eruda，按需手动打开 |
| `page_js` | 页面脚本注入：注入动作本身不落盘（页面侧结果走 `WEBREQ`/`NAV`） |
| `pk_assist` | PK 自动作答：行为改变 + `KdLog` |
| `rm_feed_ad` | 移除信息流广告：同上 |
| `rm_main_banner` | 移除主页横幅：同上 |
| `rm_popup` | 移除弹窗：同上 |
| `rm_splash` | 移除开屏广告：钩子改返回值，不落盘 |
| `rm_tab_ad` | 移除 Tab 广告：同上 |
| `web_picture_watermark` | 行为改变类，不落盘 |

## 三、需要解释的三类读数

### 3.1 计数为 0 的

| feature | 读法 |
|---|---|
| `bridge_guard` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `exit_guard` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `md3_skin` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `native_exit_guard` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `net_error_probe` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `parent_ctrl_write` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `req_headers` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `rm_vip_promo` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `robust_probe` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `route_log` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `settings_entry` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `skip_onboarding` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `vip_limit_probe` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `vip_unlock` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `watermark_off` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |
| `web_request_log` | 默认关 / 本轮没走到 / 钩子失效 —— 三者不可由本表区分，要看 `module_report.py` 的 `HookCore ready` 与 `hooks N ok / M failed` |

### 3.2 只在 1 份输入里出现的

无。

### 3.3 比上一轮少的

无（或缺 `--prev`）。

## 四、没有任何运行时样本的前缀

这些前缀在**全部 1 份输入里都是 0 行**。本批抓取最晚一份的日期是 **?**。2026-10-25 一轮新增/改写的功能（`skip_update` / `vip_unlock` / `bridge_action_log`，以及 `EXITCALL` / `RC4PT(nontext)` / `EXITSTACK` 等行）都在这个日期之后，因此它们没有样本属于"**样本早于功能**"，不能当成"功能失效"读。要关闭这个缺口，只能拿 2026-10-25 之后构建的模块在真机上跑一轮再 pull。

| 前缀 | 归属功能 | 静态层证据 | 运行时 |
|---|---|---|---|
| `ADBLOCK` | `rm_adconfig` | 见功能源码 | **未验证** |
| `EXITCALL` | `exit_guard` | `ExitGuard.hookAll` — `module/README.md` 功能表 | **未验证** |
| `EXITSTACK` | `exit_guard` | 同上（同一处两行） | **未验证** |
| `FORMULA` | `native_probe` | `NativeProbe` | **未验证** |
| `GUARD` | `bridge_guard` | 见功能源码 | **未验证** |
| `HDR` | `req_headers` | `ReqHeaders` 三处钩子（静态/每请求/Volley）；volley 侧 2026-10-25 起带 `pid=<业务域>`（`-` = 读不到） | **未验证** |
| `MD3` | `md3_skin` | 见功能源码 | **未验证** |
| `NETERR` | `net_error_probe` | 见功能源码 | **未验证** |
| `NEXIT` | `native_exit_guard` | 见功能源码 | **未验证** |
| `ONBOARD` | `skip_onboarding` | `SkipOnboarding.click` | **未验证** |
| `PCTRLW` | `parent_ctrl_write` | 见功能源码 | **未验证** |
| `PROMO` | `rm_vip_promo` | 见功能源码 | **未验证** |
| `RC4UP` | `rc4_probe` | `RC4Probe.encrypt` 钩子 | **未验证** |
| `ROBUST` | `robust_probe` | 见功能源码 | **未验证** |
| `ROUTE` | `route_log` | `RouteLog` 钩子 | **未验证** |
| `SETTINGS` | `settings_entry` | 见功能源码 | **未验证** |
| `VIP` | `vip_unlock` | `module/NEW_TARGETS.md` §3（`bk.a.p` / `VipCurrentStatusWebAction`） | **未验证** |
| `VIPLIMIT` | `vip_limit_probe` | 见功能源码 | **未验证** |
| `WATERMARK` | `watermark_off` | `WatermarkOff`（`cu/l` 构造器，`NEW_TARGETS.md` §2.2） | **未验证** |
| `WEBREQ` | `web_request_log` | `WebInjector.shouldInterceptRequest` | **未验证** |

> 这些行的**格式**由门禁 ①b 用构造样本证明（`kit/python/tests/fixtures/all_prefixes.txt`），但"设备上真的会写出这些行"仍然**未验证**。


## 五、按前缀的分布（用来发现"某类记录突然消失"）

| 前缀 | 行数 |
|---|---|
| `APPSIGN` | 1551 |
| `H5` | 902 |
| `RC4PT` | 484 |
| `NET` | 139 |
| `H5BRIDGE` | 137 |
| `SIGN_PARAMS` | 85 |
| `SIGN_RESULT` | 85 |
| `SIGN_URL` | 85 |
| `RC4` | 60 |
| `RESPBODY` | 54 |
| `H5RET` | 51 |
| `REQBODY` | 51 |
| `SIGNPARAM` | 40 |
| `RC4KEY` | 10 |
| `POPWIN` | 8 |
| `NAV` | 7 |
| `PAGEREQ` | 7 |
| `NAVACT` | 5 |
| `PCTRL` | 4 |
| `ADSLOT_CALL` | 2 |
| `ADSLOT_RET` | 2 |
| `AD_BLOCK` | 2 |
| `BRIDGE` | 2 |
| `MARK` | 2 |
| `RC4KEYSTR` | 2 |
| `UPDATE` | 2 |

## 六、这份表**不能**证明的事

* 不能证明**行为改变**真的生效（广告是否消失、会员是否解锁）—— 那需要真机前后对比；
* 不能证明**热开关**在 1–2 秒内生效 —— 需要真机翻转开关；
* 不能证明这些行对应的功能**已经**被用户打开 —— 抓取只记"执行过"，不记"为什么执行"；
* 本表全部数字来自**离线抓取文件**，可重复；真机行为一律标"未验证"。


## 七、功能 ↔ 抓取前缀对照表

`五` 那节是按前缀统计的分布；这一节反过来：**每个功能写什么前缀**。
扩 `kit/python` 解析器、写报告脚本、或看到一行陌生的抓取记录时查这里。

`落盘`：`cap` = 宿主 `files/kdkit_capture.txt`（唯一的共享抓取文件）；
`log` = logcat / XposedBridge 的 `[KdKit]` 行；`inject` = 注入页面的 JS。

| 功能 (id) | 前缀 / 形态 | 落盘 | 限流 |
|---|---|---|---|
| `settings_entry` | `SETTINGS entry opened` | cap | 每次打开 1 条 |
| `rm_adconfig` | `blocked ad slot read:` | log+cap | 前 20 条 |
| `ad_probe` | `ADSLOT call` / `ADSLOT ret` | cap | 每 key 12 条 |
| `log_sink` | `APPSIGN <级别>/<tag>:`；**2026-10-25 前采集的样本里 99.7% 是模块自身日志的重复行**（`SELF_TAG` 排除是之后才加，见 `OPTIMIZATION.md` §22） | cap | 每 tag 2000 |
| `sign_observer` | `SIGN URL:` / `SIGN params:` / `SIGN result:` / `RC4KEY b(…)` / `RC4KEY refreshed` / `H5 DECRYPT in|out` / `H5 ENCRYPT in|out` / `NET DECRYPT in|out` / `NET ENCRYPT in|out` | cap | 每类 30（`sign_observer_pairs`）|
| `native_probe` | `SIGNPARAM param=… sign=…` / `FORMULA A=… X=…` | cap | 20 |
| `route_log` | `ROUTE <方法> <路由> \| from=<调用方>` | cap | 去重 + 1000 |
| `nav_log` | `NAV <文件名> \| <url>` / `NAVACT <Activity>` | cap | 去重 + 2000 |
| `skip_onboarding` | `ONBOARD clicked='<文案>' label=… #n ok=…` | cap+log | 每次点击 1 条 |
| `exit_guard` | `EXITCALL #n <类.方法>(args) blocked=<bool>` / `EXITSTACK #n …` | cap+log | 前 40 条带栈 |
| `native_exit_guard` | `NativeExitGuard: seccomp rc=…` | log | 启动 1 次 |
| `h5_bridge_log` | `H5BRIDGE <action> count=<n> <json>`（入站）/ `H5RET <callbackFun> count=<n> len=<n> <payload>`（**出站**）| cap | 每 action 200 |
| `web_request_log` | `WEBREQ <url>` / `WEBREQ <url> \| <头摘要>` | cap | 3000 |
| `req_headers` | `HDR(static) …` / `HDR <host> :: …` / `HDR(v) <host> :: …` | cap+log | 400 |
| `rc4_probe` | `RC4KEYSTR <key> \| len=` / `RC4KEY <hex>` / `RC4PT <明文>` / `RC4UP <明文>` / `RC4PT(nontext) len=… b64=…` / `RC4UP(nontext) len=… b64=…` | cap | 每类 2000 |
| `bridge_guard` | `GUARD blocked=<action> reason=<why> url=<url> #n` | cap+log | 5000 |
| `anti_detect` | `AntiDetect: neutralised <判定点> (#n)` → 之后 `AntiDetect: heartbeat #n` | log | 前 6 条 + 5 分钟心跳 |
| `bridge_action_log` | `BRIDGE downloadMedia type=<n> url=…` / `BRIDGE getuserinfo asked identity=…` / `BRIDGE payorder submit len=<n> keys=<k>:<键名> pid=vip`（**只记长度与键名，不记 `payInfo` 的值**） / `BRIDGE decodeHttpRequest url=<host+path> shouldDecode=<0\|1\|?> params=keys=<n>:<键名>`（**URL 已剥 query/fragment；`?` = 页面没传该键，与传 `0` 不是同一条路径**） | cap | 每类 200 |
| `page_request_log` | `PAGEREQ from=<action> url=<host+path> params=keys=<n>:<键名> method=<0\|1\|?>`（**钩 `dr.f.a` 单一汇聚点** ⇒ 覆盖宿主全部“页面代发请求”的 action，新加 action 不必改代码；`from` 是发起方的 action 类名，剥掉了 `$1` 这类匿名编号；`method` 0=GET / 1=POST，`?` = 取不到；URL 已剥 query） | cap | 500 |
| `skip_update` | `UPDATE suppressed force-update popup` / `UPDATE forceUp <a> -> 0` | cap+log | 每次 1 条 |
| `vip_unlock` | `VIP unlock applied` | cap | 前 5 条 + 1 分钟心跳 |
| **`net_error_probe`** | `NETERR no=<号> code=<信息> \| <消息>` | cap | 500 条 |
| **`http_body_probe`** | `REQBODY text <类> len=<n> <body>` / `REQBODY bin <类> len=<n>` / `REQBODY json len=<n> <body>` / `REQBODY params <类> n=<n> <k=v …>` / `RESPBODY text status=<n> len=<n> <body>` / `RESPBODY bin status=<n> len=<n>` / `RESPBODY unreadable fields=…` | cap | 请求 400 / 响应 400 |
| **`vip_limit_probe`** | `VIPLIMIT ask product=<名> used=<n>` / `VIPLIMIT result allowed=<bool> remaining=<n>` | cap | 各 200 |
| `watermark_off` | `WatermarkOff: …`（构造器 after 钩子，`WATERMARK off applied` 落抓取） | cap+log | 见实现 |
| `rm_vip_promo` | `PROMO blocked dialog show` / `PROMO blocked winVIPBottom`（`VipPromo: …` 同步进 log）；页面内推广入口由注入 JS 隐藏，不落抓取 | log+cap | 去重 |
| `md3_skin` | `MD3 window themed`（原生窗口配色）；H5 侧注入样式不落抓取 | log+cap | 每个 Activity 1 条 |
| **`robust_probe`** | `ROBUST patch <类> #<序号> supported=<true\|false\|?> redirect=<bool>` / `ROBUST stack <类> #<序号> <调用方>`。`redirect=false` ⇒ 该类未被补丁涉及；`supported=true` ⇒ 原方法体没执行。**只观测，不拦截补丁** | cap+log | 单进程 400 条；`supported=true` 另进 logcat |
| **`popwin_gate`** | `POPWIN seen type=<类型> block=<bool> action=<PASS\|OBSERVE\|BLOCK>` | cap+log | 每类型 60 条 |
| 基础设施 | `=== KdKit host=<版本>/<code> baseline=<bool>` / `=== HookCore start process=…` / `=== HookCore audit: ready n/m features, hooks N ok / M failed -> skipped: …` | cap | 启动各 1 行 |
| `parent_ctrl_write` | `PCTRLW aiwriting=… book=… mask=0x… from=… userMode=…` | cap | 见功能源码 |

### 七之二、只改行为、**结构上不写抓取**的功能

下面 11 个功能钩的是广告视图/弹窗/引导，效果是"让它别显示"，因此**没有可数的行**。
它们必须在这张表里出现（③ 门禁要求），但 `落盘` 列只能写 `log` 或 `—` ——
写 `cap` 会让人去抓取文件里找一个永远不会存在的记录。

| 功能 (id) | 形态 | 落盘 | 怎么判断它在工作 |
|---|---|---|---|
| `rm_splash` | 钩 `lk.a.j/k/g` 把结果置 `null`/`false` | log | 开屏广告是否还出现（**未验证**） |
| `rm_tab_ad` | 钩 `TabAdvertisementView.isInitDataSuccess` 等 4 处 | log | Tab 页广告卡片是否消失（**未验证**） |
| `rm_main_banner` | 钩 `MainAdvertiseImageView.show/showOrHideAdvertise` | log | 主页横幅是否消失（**未验证**） |
| `rm_feed_ad` | 钩 `DetailSellAdxContainerAdView.setAdData` 等 2 处 | log | 信息流广告是否消失（**未验证**） |
| `rm_popup` | 钩 `PopupAdvertisementDialog.g` 置 `false` | log | 弹窗是否还弹（**未验证**） |
| `block_ad_sdk` | 钩 4 个 `FastAd*Manager.init*SDK` 直接返回 | log | 广告 SDK 是否未初始化（**未验证**） |
| `h5_debug` | 往 `WebInjector.register("eruda")` 注册调试台脚本 | inject | 页面里 eruda 是否出现（**未验证**） |
| `page_js` | **不注册、不装钩**：`WebInjector` 每次注入都读 `page_js_script` 配置 | inject | 注入的脚本是否执行（**未验证**） |
| `pk_assist` | 往 `WebInjector.register("pk")` 注册作答脚本 | inject | 页面是否自动作答（**未验证**） |
| `web_picture_watermark` | `web_picture_watermark`（**无前缀**：只改本页渲染，不写抓取行） | `CommonWebPictureBrowseActivity.c2` / `j2` | **未验证** |
| `parent_ctrl_probe` | `parent_ctrl_probe`（**无前缀**：只观测，不写抓取行） | `dj.e.f()` → `ParentCtrlData` | **未验证** |
| —（`unavailable` 变体） | `PCTRL unavailable` / `PCTRLW unavailable` —— 拿不到家长模式数据时写 `reason=`，区分"没开启"与"读取失败" | cap | 见功能源码 |

> `page_js` 是唯一一个连 `register` 都没有的：`WebInjector.inject()` 每次都直接读
> `page_js_script`。所以它在 `VERIFICATION.md` 的「静态钩子」列必然是 `—`，
> 不是"钩子没解析出来"。

**这条表也是门禁**：`check_feature_parity.py` 的 `check_activity_doc` 要求每个 feature id
出现在**本节的表格行**里（`| `id` |` 开头），不是"全文任意位置提到过"。
2026-10-25 第 11 轮把它从"全文提到即通过"收紧成"必须在表格行里"，当场查出
9 个功能此前只在上面的「计数为 0」表里出现过（那张表是生成器自动产的，
不需要人维护），§七 里从来没有它们的行。

新增功能忘了登记 → 报告脚本统计不到它 → 计数恒为 0 → 被误读成"功能没生效"。
这条门禁就是为了防这种假红。
