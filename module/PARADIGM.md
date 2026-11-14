# 模块范式（KDKit ⇄ BCZKit 共用契约）

本文件是 **KDKit 的模块骨架契约**，`baicizhan-kit` 的 BCZKit 按同一份结构移植。
目标不是"目录长得像"，而是：**新增一个功能只改一个地方、文档/门禁能自动发现漂移、注入失败不会拖垮宿主**。

---

## 1. 目录骨架

```
module/
  app/src/main/java/dev/xalor/<kit>/
    <Kit>Entry.kt              Xposed 入口（IXposedHookLoadPackage），只做分发
    HookCore.kt                进程内 bootstrap：classLoader / config / 依次 enable 所有 feature
    config/<Kit>Config.kt      纯 app-ClassLoader 的配置读写（**不得引用 de.robv.xposed.***）
    config/<Kit>ConfigBridge.kt 框架侧：XSharedPreferences 读取 + 设置应用侧发布
    features/BaseFeature.kt    功能契约 + Category
    features/FeatureRegistry.kt 唯一功能清单（UI 顺序 = 文档顺序）
    features/<area>/...        按域分组：ads / pk / host / net / misc / web
    features/misc/LogSink.kt   把宿主自己的 logcat 行收进抓取文件（可选但推荐）
    ui/MainActivity.kt         Compose 设置页：**只读 FeatureRegistry**，不维护第二份清单
    util/Xp.kt                 Xposed 薄封装（hook / hookAll / hookAllBefore / hookAllAfter）
    util/<Kit>Log.kt           统一日志前缀（`[KdKit]` / `[BczKit]`）
    util/Capture.kt            抓取文件写入（活动 Context 自解析，带大小上限）
  scripts/check_feature_parity.py   代码 ↔ README 功能表门禁
  PARADIGM.md                 本文件
  README.md                   功能表（被门禁校验）
```

## 2. 功能契约（`BaseFeature`）

必守四条：

1. **`id` 是持久化 key，永不改名。** 改名 = 用户开关丢失。
2. **元数据只写一份**：`title` / `summary` / `category` / `defaultOn` 写在 feature 对象里，
   设置页从 `FeatureRegistry.all` 派生；README 表格由 `check_feature_parity.py` 校验。
3. **`install()` 只装钩子**：不读大文件、不发网络、不阻塞；失败必须抛出，由 `enable()` 记录。
4. **`enable()` 必须幂等**：`@Synchronized` + `installed` 标志，重复调用只装一次
   （HookCore 可能被诊断页/重入触发；重复 hook 会让一次调用记两遍日志、甚至改变行为）。

```kotlin
object Foo : SwitchFeature("foo", "标题", "一句话说明", Category.HOST, defaultOn = false) {
    override fun install() {
        Xp.hook("a.b.C", "d", String::class.java, onAfter = { p -> /* ... */ })
    }
}
```

**新增功能的标准动作**：

1. 选择域目录（ads/pk/host/misc/web）；
2. 写 `object`（id 小写下划线、标题中文、summary 说清"做什么/为什么"）；
3. 在 `FeatureRegistry.all` 里按 UI 顺序登记；
4. 在 `README.md` 功能表加一行（跑门禁会告诉你缺哪行）；
5. `./gw assembleDebug` + `python3 scripts/check_feature_parity.py`；
6. 有 hook 目标的，跑 `kit/scripts/check_hook_targets.py`（反编译 APK 校验类/方法存在）；
7. **要写抓取行的，必须在 `kit/python/capture_schema.py` 加规则**并补 fixture 一行
   （否则真实抓取里那几行会落 UNKNOWN，而所有离线门禁都是绿的 —— 2026-11-02 实测过一次：
   `blocked ad slot read` 改了写入格式没同步规则，7 行证据静默消失）；
8. **回调里对功能自己做开关判断时，用 `KdConfig.isOn(id, GatePolicy.defaultFor(id))`**，
   不要写字面量 `true`/`false`（门禁 ⑯ 会报；写错等于把默认关的功能变成默认开）；
9. 跑 `./scripts/verify.sh` 全量门禁（当前 19 条），不要只跑第 5 步那两个工具。

> 这份步骤本身由 `kit/scripts/check_procedure.py` 校验：提到的每个路径/命令/域目录
> 都必须真实存在，否则它报红 —— **流程文档过期时没有任何东西会自己响**，所以要有专门的一道。

## 3. 配置通道

- 设置应用与宿主是不同 uid、不同 mount namespace，**不能直接互读 prefs**。
- 写入：设置应用写自己的 `SharedPreferences`；`<Kit>ConfigBridge` 在**框架 ClassLoader** 里
  镜像到 framework-published 文件（chmod 644）。
- 读取：宿主进程里 `installHostReader()` 装 `XSharedPreferences` reader；
  `Config.isOn(id, default)` / `getString(key, default)` 内存缓存。
- 布尔值用 `isOn`；字符串（黑名单/白名单/脚本）用 `getString`，并给默认值常量。
- **改配置需要重启宿主进程生效**（当前设计）；设置页文案必须写明这一点。

## 4. 日志与抓取

- 日志统一走 `<Kit>Log`，前缀固定（`[KdKit]` / `[BczKit]`），方便 `grep` 与 `module_report`。
- 需要落盘的观测（签名、桥、广告位、路由）写入宿主 `files/<kit>_capture.txt`：
  - 每行带**固定前缀**（`SIGN` / `H5BRIDGE` / `ADSLOT` / `GUARD` / `ROUTE` / `NAV`），
    报告脚本按前缀统计；
  - 写入必须限长（单行截断 + 文件上限），否则长跑会把设备写满。
- **观测钩子必须先于拦截钩子注册**（KDKit 实测：blocker 短路后，后注册的 probe 一行都不会出）。

## 5. 门禁（缺一不可）

一条命令跑全部 **19 条**：`./scripts/verify.sh`（离线，不需要设备；⑬ 需要设备，无设备时 SKIP）。
`--deep` 额外跑 ⑥b（死代码枚举，~65s）。

| # | 门 | 命令 | 失败含义 |
|---|---|---|---|
| ① | 单元测试 | `./gw testDebugUnitTest` | 纯逻辑（过滤/限流/白名单/截断/路由）坏了 |
| ①b | 抓取解析器 | `python3 -m unittest discover -s ../kit/python/tests` | 模块写的前缀与解析器声明漂移 |
| ② | assembleDebug | `./gw assembleDebug` | Kotlin/资源错误 |
| ③ | 功能表/子选项一致 | `python3 scripts/check_feature_parity.py` | 代码 ↔ README ↔ `KdOption` ↔ `ACTIVITY.md`/`VERIFICATION.md` 漂移；幽灵键；死选项 |
| ④ | 钩子目标 | `../kit/scripts/check_hook_targets.py` | 宿主换版/混淆改名，功能会静默失效。**边界**：`android.*`/`java.*` 的平台类不在解包的 APK 里，只能按前缀放行（`OK(platform)`）⇒ 平台类名打错字 ④ 看不见 |
| ⑤ | 钩子签名 | `../kit/scripts/check_hook_signatures.py` | 形参类型写错（④ 的盲区：名字对、参数错 ⇒ 运行时静默返回 false） |
| ⑥ | 钩子调用方 | `../kit/scripts/check_hook_callers.py` | 目标是死代码（`BrushMaskView` 那类），钩了必空转 |
| ⑥b | 死代码枚举 | `../kit/scripts/check_hook_callers.py --dead-ui <pkg>` | **没钩到的**零引用 UI 子类（`BrushMaskView` 那类）—— 只报告 |
| ⑦ | 假测试扫描 | `../kit/scripts/check_fake_tests.py` | "看着通过、其实什么都没测"的测试（严格模式，命中即红） |
| ⑧ | 钩点共享登记 | `../kit/scripts/check_hook_sharing.py --strict` | 两个功能钩同一方法但没在 §10 写明相互作用（见 §10） |
| ⑨ | 热修复暴露面 | `../kit/scripts/check_robust_coverage.py --quiet --fail-over 60` | Robust 插桩覆盖超过 60 个目标 ⇒ 补丁一下发原方法体不执行（见 §11） |
| ⑩ | 读预算余量 | `../kit/scripts/check_usage_budget.py --strict` | 命中文件总量逼近 `read_budget`（余量 <25%）⇒ 目标会被静默降级成 `INCOMPLETE`，而判定结果取决于排序 |
| ⑪ | 解析规则往返 | `../kit/scripts/check_schema_roundtrip.py --strict` | 某条解析规则**从来没被任何样本命中过** ⇒ 它是死规则，或写入侧已经变了 |
| ⑫ | shell 变量边界 | `../kit/scripts/check_shell_vars.py --strict` | `$var` 紧跟全角字符 ⇒ bash 把变量名解析成 `RC<乱码>` ⇒ `unbound variable`（今天踩过 3 次） |
| ⑬ | 真机验证 | `./scripts/verify_on_device.sh` | APK 装得上、界面打得开、开关能留；无设备时 SKIP 而非失败 |
| ⑭ | 生成文档新鲜度 | `../kit/scripts/check_generated_fresh.py` | 自动生成的文档**不能由它的生成器复现** ⇒ 它过期了，却仍带着"自动生成"的可信度 |
| ⑮ | 钩子返回值类型相容 | `../kit/scripts/check_hook_result_types.py` | 在 before 钩里写 `param.result` 的目标，返回值类型与写入值不匹配 ⇒ 调用方拿到错值或崩溃 |
| ⑯ | 开关默认值一致 | `../kit/scripts/check_gate_defaults.py` | 回调里的字面量与功能声明的 `defaultOn` 相反，或 `HookCore` 灌默认值的来源被改 ⇒ 默认关的功能全部变开 |
| ⑰ | shell 管道陷阱 | `../kit/scripts/check_shell_pipes.py` | `\| tee f \| grep -q` 会因 SIGPIPE 让 tee 早死、日志被截断 ⇒ 门禁误判 FAIL |
| ⑱ | 门禁表一致 | `../kit/scripts/check_gate_table.py` | `verify.sh` 跑的门禁与本节表格不一致 ⇒ 新人会以为仓库只有 N 道保护 |
| ⑲ | 热路径重复计算 | `../kit/scripts/check_hot_path.py` | 钩子回调里现编正则，或 R9/R45/R46 修掉的三处"每次现算"被重构回去 |
| ⑳ | 写入前缀有解析规则 | `../kit/scripts/check_writer_prefixes.py` | 模块写下的前缀在 `capture_schema.py` 里没有规则 ⇒ 真实抓取里落 UNKNOWN，而夹具看不见 |
| ㉗ | 设备写入有回读 | `../kit/scripts/check_device_writes_readback.py` | 某个脚本 `adb push` / `cp` 之后不把它读回来 ⇒ 推送失败也会报告成功 |
| ㉘ | 签名请求体组装一致 | `../kit/scripts/check_sign_body_assembly.py` | 8 处重复同一约定，某处少排一个参数 ⇒ 服务端判 antispam sign error，而单看那一处像对的 |
| ㉙ | TLS 只有一个决定点 | `../kit/scripts/check_tls_default.py` | 某处又直接造不校验的 context ⇒ 同库两种默认，"服务端拒绝"与"证书环境不对"无法区分 |
| ㉚ | 验证链路吞噬有预算 | `../kit/scripts/check_silent_except.py` | 验证类文件里新增一处 `except Exception: pass` ⇒ 判据悄悄少一半输入，而报告看不出异常 |
| ㉛ | 源码快照够新 | `../kit/scripts/src_snapshot.py --verify --max-age-hours 48` | 手写源码没有 48 小时内的快照 ⇒ 误删一个文件就要“考古”（2026-11-03 真的发生过） |
| ㉜ | 默认设备号唯一来源 | `../kit/scripts/check_default_serial.py` | 某处又写死 `default='emulator-5558'` ⇒ 换设备时漏改一处，那个工具会静默操作另一台设备 |
| ㉝ | 没有过期的 pyc | `../kit/scripts/check_stale_pycache.py` | 源码比 `.pyc` 新而 Python 仍在用旧的 ⇒ “改过的代码看起来没改”，判据指向错误的对象 |
| ㉞ | gz 读取器唯一 | `../kit/scripts/check_dup_gz_reader.py` | 又复制出一份 `.gz` 文本读取器 ⇒ 漏改一处就静默少读一半抓取 |
| ㉟ | 签名公式唯一 | `../kit/scripts/check_sign_formula_dup.py` | 又复制出一份 md5 签名链 ⇒ 它没有测试，坏掉时症状是 errNo 6，与“参数集不对”无法区分 |
| ㉠ | SDK 路径唯一 | `../kit/scripts/check_sdk_path_dup.py` | 某处又写死 `$HOME/Library/Android/sdk` ⇒ 换机器时漏改一处，报的是 `adb: command not found`，指向错原因 |
| ㉡ | gz 抓取可解析 | `../kit/scripts/check_capture_gz_parse.py` | `iter_records` 又直接 `open()` ⇒ 891 份压缩抓取整份变成 UNKNOWN，按 kind 统计的工具只会显示“这个包里什么都没有” |
| ㉢ | 不直接 open 抓取 | `../kit/scripts/check_capture_open.py` | 又直接 `open(a.capture)` ⇒ 传 `.txt.gz` 时报告空白，而空白看起来像“这个包里没有这类行” |
| ㉣ | 同名同参不反序 | `../kit/scripts/check_same_name_contract.py` | 又出现前两参互为反序的同名函数 ⇒ 参数都是字符串时调换顺序不报错，只会解出垃圾 |
| ㉤ | 证据索引新鲜 | `../kit/scripts/index_evidence.py --check` | `work/INDEX.md` 过期 ⇒ 它点名 1332 个路径，其中 1212 个已被 pack_slim 压成 .gz |
| ㉥ | 跳过数在限内 | `../kit/scripts/check_skip_budget.py` | 出现没登记过的 skip 理由，或总数超限 ⇒ 套件腐烂的方式不是变红，是变绿但验得越来越少 |
| ㉦ | 覆盖数不缩水 | `../kit/scripts/check_coverage_floors.py` | Python 测试 / Kotlin 测试 / 负对照数低于下限 ⇒ 删掉一条测试或一条负对照，其余门禁照样全绿 |
| ㉧ | 循环里无裸 open | `../kit/scripts/check_open_in_loop.py` | 循环里的裸 `open()` 超过基线 61 ⇒ 依赖 CPython 引用计数才关闭，macOS `ulimit -n` 只有 256 而本仓库要扫 5 万个 smali |
| ㉨ | SIGN URL 只一处 | `../kit/scripts/check_sign_url_dup.py` | 出现第二处 `split(' SIGN URL: ')` 且没写 `# signurl-ok:` ⇒ 旧写法会把响应体里回显的 URL 当请求、也会拿被截断的 URL 发请求 |
| ㉩ | 无重复 kind 分支 | `../kit/scripts/check_dup_kind_branch.py` | 同一函数里两个 `if kind == 'X'` ⇒ 前一个先 return，后一个永远不执行 |
| ㉪ | hot 钩子可关闭 | `../kit/scripts/check_hook_gated.py` | `hot = true` 的功能既无 `gate =` 也无 `KdConfig.isOn` ⇒ 开关是关的但钩子照跑 |
| ㉫ | gate 判据只一处 | `../kit/scripts/check_hook_gate_predicate.py` | `Xp.kt` 里判据被抄开，或某个回调少判 gate ⇒ 那个回调永远按"开"处理 |
| ㉬ | 无静默 except | `../kit/scripts/check_silent_except.py` | 出现未登记的 `except Exception: pass`，或豁免表里有一条对不上代码（陈旧豁免 ⇒ 白通证） |
| ㉖ | 负对照总检 | `../kit/scripts/run_negative_controls.py` | 某道门禁注入已知故障后**仍然绿** ⇒ 它已经失效（正则变窄 / 判据恒真） |
| ㉕ | 文档命令可执行 | `../kit/scripts/check_doc_commands.py` | 本节"命令"列写的脚本/参数在仓库里不存在 ⇒ 照抄会跑错事 |
| ㉔ | --accept 守卫可触发 | `../kit/scripts/check_gate_accept_guard.sh` | 某道门禁写成 `--accept " 0 1 …"` 就永远不可能红；这道门禁证明那条守卫真的会拦 |
| ㉓ | 磁盘体积在限内 | `../kit/scripts/disk_audit.py` | 单项一轮内增长 >500MB，或整个仓库 >8GB ⇒ 可再生产物（`apktool_out` / `packs`）在无声长大 |
| ㉒ | 方法纪律（静态可查） | `../kit/scripts/methodology_check.py --paths kit module` | `shell=True` 配列表参数 / 没有 `timeout=` / `shell=True` 不带 `start_new_session`（超时只杀 shell，子进程泄漏） |
| ㉑ | 抓取行全部被认领 | `../kit/scripts/check_capture_claimed.py` | ⑳ 的动态一半：真实抓取里有行解析成 UNKNOWN ⇒ 写入格式变了而规则没跟上（没有近期抓取时是"无法验证"，`--accept 2`） |
| ㉰ | 负对照无残留 | `../kit/scripts/check_negctl_leftovers.py` | `kit/` 或 `module/` 里躺着一个 `*.negctl.bak` ⇒ 上一轮负对照没有善终，源文件**现在**是注入态（2026-11-05→09 这样假通过了三天）；备份在而源文件没了 ⇒ 源文件被吞，要从归档恢复 |
| ㉱ | 版本差异有出处 | `../kit/scripts/check_version_delta_documented.py` | `rename_match.json` 里的 `NEW`/`GONE` 类必须出现在 `MIGRATION-*.md` 或 `work/reverse*/*.md`；少一条 ⇒ 下一轮适配的人会去追"其实只是换了分包"的类（7.10.0：116→15） |
| ㉲ | dpsdk 检测面未漂 | `../kit/scripts/dpsdk_detect_baseline.py` | `libdpsdk.so` 的哈希/导出符号/检测串及其内联引用状态与 `work/baselines/dpsdk_detect.json` 不一致 ⇒ 检测面变了，必须重读 `work/dpsdk/DELTA-*.md` 并 `--save` |
| ㉵ | 配置双源一致 | `../kit/scripts/check_config_dual_source.py` | 发布目录（宿主读）与模块 App prefs（设置页读）的条目集合必须逐条相等；否则"设置页说 13/38、宿主说 18"这种差会一直存在而无人发现（无设备时退 2） |
| ㉳ | 套锁契约不破 | `../kit/scripts/check_lock_contract.py` | 跨进程锁必须可重入：`with_lock.py` 注入 `KD_LOCK_HELD`、重入分支在取锁循环之前、`verify.sh`/`run_negative_controls.py` 的自锁守卫都认它。缺一条 ⇒ 调用方套锁时**子进程等父进程的锁**，死锁无信号（2026-11-09 04:0x：`verify_r3.log` 只有一行 `[lock] 持有 …`，一道门都没跑） |

④⑤⑥ 必须**看到同一批目标** —— 这条由 `test_hook_gate_agreement.py` 断言。
2026-10-25 实测过三份清单互不相同（④ 73 / ⑤ 48 / ⑥ 48），根因是各自演一套正则；
现在调用形态的正则只在 `kit/scripts/hook_vocab.py` 定义一次。

**门禁的红必须永远意味着"真的坏了"。** 2026-10-26 第 31 轮 ④ 连续红了三次，
查下来不是钩点坏了，而是 `smali_usage.analyse()` 的读预算（96 MB）小于命中文件总量
（140.4 MB），而 `rg -l` 的返回顺序逐次不同 ⇒ 每次被丢掉的文件不同 ⇒
`resolved` 数在 96/107/112/116 之间跳。修法见 §10.5；结论是**同一批静态输入
必须给出同一批结论**，否则门禁会教人重跑碰运气。

### 5.1 门禁最常见的失效不是"判错"，是"没看"

2026-10-26 第 36 轮把 ③ 的计数校验拆开看，发现它漏了三处真实过期数字。
三次失效的形状完全一样：**正则（或文件清单）写窄了 ⇒ 那一整类声明不受保护，
而且看起来是绿的。** 没有报错、没有 warning、没有任何信号。

| 次 | 漏掉什么 | 当时文档写的 | 实际 |
|---|---|---|---|
| 1 | `**N 个热开关**`（无斜杠形态） | 32（热开关） | 33 |
| 2 | `（N 个热开关）`（括号形态） | 又一次过期 | — |
| 3 | `**N 功能**`（无「个」）、`模块有 N 个功能`、`N 个功能逐行`；**且 `module/PARADIGM.md` 从未被扫过** | 35 / 18 / 34（功能） | 36 / 36 / 36 |

> 表里第 1 行故意不写全 `N 个热开关` 那五个字：这条门禁现在也会读**本文件**，
> 而它分不清"记录历史"和"声称当前"。写成散文数字就不会把自己绊倒。
> 这是"文档被门禁读"之后出现的真实约束 —— 写记录也要顾着门禁的读法。

第 3 次尤其值得记住：**"哪些文件受检"本身也是会被写死的清单。**
`check_declared_counts` 只扫三份 README/OPTIMIZATION，于是本文件里那句
"模块有 34 个功能"在功能加到 36 之后没有任何门禁会说话 —— 它不在盲区之外，
它在扫描范围之外。

三条可移植的规则：

1. **收窄的正则 = 静默失效的豁免区。** 每加一种写法都要同时加一条测试钉住它；
   `test_declared_counts.py` 就是干这个的。
2. **受检文件清单同理会过期。** 新增文档时问一句"它会不会也声明数量"。
3. **不许一刀切。** "凡是 N 个功能都等于总数"会让 `这 12 个功能…`（子集）、
   `AdFeatures.kt 的 7 个功能`（单文件）、`第 29 个功能`（序数）全部误报。
   **喊狼来了的门禁会被关掉**，所以只认"声称模块总数"的句式；
   `SubsetsAndOrdinalsAreNotTotals` 专门钉住这四类不许红。

### 5.2 "引用哪一轮"是结论，不是排版

`feature_matrix.py` 的「依据」列原来取 `subject[-1]`（最后一个主题命中的轮次），
而关键词是**子串**匹配。结果三处引用指向了无关轮次：

| 功能 | 旧引用 | 那一轮在讲 | 真正建功能的是 |
|---|---|---|---|
| `skip_onboarding` | R501 | 「把"七步的**可跳过性**"统计出来」 | R11 |
| `pk_assist` | R28 | 「接口探测 —— 候选来自 A**PK** 字符串表」 | R3 |
| `web_request_log` | R134 | 「页面地图补上…」 | R119 |

`APK` 里有 `PK` —— 一个纯子串就把"接口探测"当成了 PK 助手的验证依据。
「依据」列是读者判断"这功能被证明到什么程度"的唯一入口；指向一轮方法论讨论，
等于给一个没做过实验的功能背书。

修法两条，缺一不可：**选轮次的排序**（优先"建功能"措辞、其次取最早）
与**关键词匹配的边界**（ASCII 词按词边界 + 大小写；中文无词边界只能保留子串，
属已知残留 —— 排序已使它们不会成为被引用的那一个）。

## 6. 移植到 BCZKit 的清单

1. 复制骨架文件并替换包名/前缀：`KdEntry→BczEntry`、`KdConfig→BczConfig`、`KdLog→BczLog`、`kdkit→bczkit`。
2. `config/*Config.kt` 里改 `MODULE_PKG` / `PREFS_NAME` / `TARGET_PKG`；**不要**复用 KDKit 的 prefs 名。
3. `AndroidManifest.xml` 的 `xposedsharedprefs`、`assets/xposed_init`、`res/values/arrays.xml` 同步改包名。
4. `FeatureRegistry` 只放 BCZKit 自己的功能；**不要**把快对的功能对象搬过去。
5. 复制 `scripts/check_feature_parity.py` 与 `README` 功能表结构，门禁命令写进 README。
6. 保留 `BaseFeature` 的四条契约与 `Xp` 的命名（`hookAllBefore` / `hookAllAfter`），不要各自发明一套。

## 7. 本轮修掉的范式缺陷（2026-10-18）

| 缺陷 | 后果 | 修法 |
|---|---|---|
| `BaseFeature.enable()` 无幂等 | 重复调用会重复安装钩子（日志翻倍/行为改变） | `@Synchronized` + `installed` 标志，新增 `isInstalled` |
| `Xp.hookAll` 有两个重载（`XC_MethodHook` / lambda） | 调用点语义靠猜，易误用 after 版 | lambda 版改名 `hookAllAfter`，与 `hookAllBefore` 成对 |
| README 功能表停在 17 项，代码 25 项 | 交付文档与真实能力不一致 | 重写 25 行功能表 + `check_feature_parity.py` 门禁 |

后续若再发现范式问题，**先改本文件与 KDKit 骨架，再让 BCZKit 跟进**，避免两边各长一套。

---

## 7 2026-10-25 增补：热开关、子选项 schema、可测化

这一节改的是**契约**，不只是实现；BCZKit 移植时应一并遵守。

### 7.1 钩子归属与门控（`Xp.under` / `Xp.hook(gate=)`）

```kotlin
override fun install() {                       // enable() 已经用 Xp.under(id) 包住
    Xp.hook("a.b.C", "d", String::class.java, gate = id, onBefore = { it.result = null })
}
```

* `gate = id` 让回调在**调用点**检查开关 ⇒ 该功能必须是 `hot = true`，否则
  "关着不装钩子、开着才装"与"装了但回调自检"两种语义会打架；
* 每条 hook 的成败记进 `HookAudit`，启动时输出 `hooks N ok / M failed`；
* **不要**在 `install()` 里自己调 `Xp.under`（会覆盖外层归属）。

### 7.2 热 vs 冷（`BaseFeature.hot`）

| | 钩子 | 改开关后 | 适用 |
|---|---|---|---|
| `hot = true` | **始终安装** | 1–2 秒生效（`KdConfig` TTL） | 绝大多数功能 |
| `hot = false` | 关着不装 | 需重启宿主 | 装了就撤不回来的（如 seccomp 过滤器） |

新增功能**默认写 `hot = true`**；只有当"安装动作本身有副作用且不可逆"时才用冷开关，
并在 KDoc 里写清为什么。

### 7.3 子选项：`KdOption` 是唯一声明处

```kotlin
override val options: List<KdOption> = listOf(
    KdOption("exit_guard_block", "真的拦下来", "关掉则只记录", KdOption.Kind.BOOLEAN, "true"),
)
```

* 设置页**通用渲染**（`ui/OptionEditors.kt`），不再为单个功能写界面；
* 门禁强制三件事：代码读的键必须有人声明（无幽灵键）、声明的必须有人读（无死选项）、
  README 的「选项」列必须与声明一致；
* `userEditable = false` 留给"由脚本写入"的键（目前只有 `page_js_script`）。

### 7.4 可测化纪律：钩子闭包里不写判断逻辑

**判据**：如果一段逻辑"改错了只能靠真机跑一轮才发现"，就把它抽成纯函数放进 `util/`，
并在 `app/src/test/` 里覆盖。

已有先例：`NavFilter`（哪个 URL 算页面）、`RouteFilter`（哪些字符串像路由）、
`HostAllowList`（同名子串绕过）、`TextHeuristic`（明文判定）、`CapturePolicy`（轮转边界）。
钩子闭包里只做"取参数 → 调纯函数 → 交结果"。

### 7.5 日志与抓取纪律

* 落盘**只**走 `Capture.append`（不要自己 `File.appendText`）—— 它是单写者 + 有界队列；
* 高频回调必须过 `RateLimit.firstN` / `RateLimit.every`；
* 行首 tag 是对外契约（`kit/python/` 的 6 个解析器按它切分），改名等于让脚本静默失败；
* 一条 KDoc 里想写路径通配时用 `…`，别写 `/*` —— **Kotlin 块注释可嵌套**，
  那会让整个注释永不闭合，而报错指向文件末尾。

### 7.6 新增功能的标准动作（更新版）

1. 选域目录，写 `object`（含 `hot`、`options`、KDoc 写清"为什么是这个钩点"）；
2. 在 `FeatureRegistry.all` 登记；
3. README 功能表加一行（含「热」「选项」两列）；
4. `./scripts/verify.sh` —— **十道门**全绿才算完成（见 §5「门禁」表）；
5. 钩子目标必须有**静态证据**（smali 文件:行号），并在 `NEW_TARGETS.md` 类文档里留证；
6. **先证明它不是死代码，再写功能**：`python3 ../kit/scripts/smali_usage.py --target a.b.C:m`
   必须给 `USED` / `USED(self)` / `REFLECTIVE` / `SUPER-SLOT` / `TYPE-ONLY` 之一。
   `DEAD` ⇒ 停下来换钩点（钩了必然空转，门禁之后也会红）；
7. 如果目标属于 **UI 类**（View/Activity/Dialog/Fragment）且你拿到的是 `DEAD` 或
   `TYPE-ONLY`，先跑 `--find-dead-ui <包>` 确认它不在"零引用 UI 子类"清单里 ——
   `BrushMaskView` 就是这样被误钩的。

### 7.6.1 钩子写成什么形态，决定门禁看不看得见

七道门里 ④⑤⑥ 靠**读 Kotlin 源码的字面量**工作，所以"怎么调 `Xp`"直接决定
这个钩子有没有被校验过。2026-10-25 第 8 轮把三条漏掉的形态补进了
`hook_vocab.py`（正则在词汇表里单点定义，三份清单共用）：

| 形态 | 之前 | 现在 |
|---|---|---|
| `Xp.hook("类", "方法", …)` | 已覆盖 | 已覆盖 |
| `Xp.hookAll*("类", "方法", …)` | 已覆盖（无形参可比） | 同 |
| `Xp.hookCtor("类", …)` | 已覆盖（方法名 `<init>`） | 同 |
| `hook("类","方法")` / `hookAll(…)` 本地包装 | 已覆盖 | 同 |
| **`XposedHelpers.findAndHookMethod("类", cl, "方法", …)`** | **完全不可见** | ✅ 已覆盖（`ReqHeaders` 3 个 + `WebRequestLog` 的 java 侧） |
| **方法名是循环变量**：`for (m in listOf(…)) Xp.hook("aj.a", m, …)` | **记成空方法名 `aj.a.`**，5 个真实钩子以 `OK(load)` 蒙过去 | ✅ 按**作用域**展开成字面量 |

第 8 轮实测：把这两条补上之后，④ 从 63 个目标变成 **92** 个，⑤ 从 42 变成 **81** 条钩子。
也就是说**三分之一的钩子此前从未被"目标在不在 / 签名对不对 / 有人调用吗"校验过**，
而门禁一直是绿的。

> 教训：门禁的输出"全绿"只能证明"我认识的那些写法没问题"。
> 每加一种调用形态，先问"门禁认不认得它"，再问"它对不对"。

### 7.6.4 门禁只覆盖"我钩了的"，覆盖不到"我该钩没钩"

④⑤⑥ 三层的输入都是**模块源码里的钩子声明**。它们能证明"钩住的都活着"，
但结构上无法回答"有没有该钩却没钩、或正在钩一个永远不执行的类"——
`BrushMaskView` 就是后者：它被钩了，⑥ 也确实把它判成了 `DEAD`（靠 `KNOWN_DEAD` 白名单），
但那份白名单是**人工侦察的产物**，不是可复跑的判据。

⑥b 把这件事反过来做（`smali_usage.find_dead_ui_classes`）：不问你钩了什么，
而是枚举"零引用 + UI 子类"的类。判据四条同时成立：

| 条件 | 为什么必须 |
|---|---|
| 是 UI 子类（`View`/`ViewGroup`/`Activity`/`Dialog`/`Fragment`） | 这类东西的正常入口是布局 inflate 或 `startActivity`，**不是** `invoke`。对普通类用同一判据会把 DTO/反射入口全报死 |
| 全 APK 零**外部**引用 | 自己文件里的字段/方法声明不算引用 |
| `res/` 布局与清单里也没有它 | 自定义 View 通常靠布局全名引用 |
| 类在解码目录里存在且非平台类 | 平台类不参与离线判定 |

实现必须是**单遍**：第一版对每个类调一次 `analyse()`（内部 grep 全量 smali），
在 7416 个类上跑 10 分钟没出结果 —— O(n²)。现在一次遍历建"描述符→外部出现次数"表，
7416 个类 77 秒。

> 铁律：**"零引用"要成为死代码的证明，必须先限定类族。** 对 UI 类成立，对普通类不成立。
> 这正是本仓库反复强调的"看不见 ≠ 不存在"的另一面 —— 对某些类族，"看不见"确实等于"不存在"。

### 7.6.2 循环展开必须带作用域

`AdFeatures.kt` 里有两个同名的 `m`：

```kotlin
for (m in listOf("d", "f", "h")) { Xp.hook("aj.a", m, Int::class.javaPrimitiveType, …) }  // 形参 (I)
for (m in listOf("j", "k"))       { Xp.hook("aj.a", m, …) }                                // 零形参
```

用"变量名 → 列表"的**全局字典**展开，后者会覆盖前者，于是 `("j","k")` 那两行被按
`("d","f","h")` 展开 → 得到 `aj.a.d()` / `aj.a.f()` / `aj.a.h()` 三条 **`SIGNATURE-MISMATCH`**
（真实签名是 `(I)`）。这是**假红**，而假红比漏报更危险：它教人无视门禁。

正确做法：`hook_vocab.loop_scopes(text)` 把每个 `listOf` 绑定到它自己的花括号块，
`loop_literals_at(scopes, var, pos)` 按**位置**取最内层作用域。

### 7.6.3 文档说"自动生成"，就必须真能重跑出同样的字

两份生成物都在本轮被查出与自己的生成器不一致：

* `ACTIVITY.md` 的「复现」命令拼的是前 3 个 `--capture <路径>`，其中
  `capture_kd1_r11.txt` **早已不存在** —— 照抄就 `FileNotFoundError`；
* 它的 `## 七、功能 ↔ 抓取前缀对照表` 是**手写**的（同时是 ③ 门禁的输入），
  生成器把整个文件当自己的领地 ⇒ "照文档说的重跑"会把门禁打红；
* `VERIFICATION.md` 的「静态钩子」列按**文件**归属钩子 —— `AdFeatures.kt` 的 7 个功能
  全都写 `12/12`，`page_js` 一个钩子都没有也写 `4/4`。

修法与它对应的断言（`kit/python/tests/test_doc_generators.py`，11 个测试）：

| 修法 | 断言 |
|---|---|
| 复现命令改成 `--dir`，逐条校验路径存在 | `test_repro_paths_all_exist` |
| 真的照它跑一遍，逐行比数字 | `test_repro_reproduces_the_same_numbers` |
| `--keep-section` 保留手工附录 | `test_regenerating_keeps_handwritten_section` |
| 按功能对象（行区间）归属钩子 | `test_same_file_features_get_different_numbers` |
| 共享钩子点标 `共享:WebInjector` 而不是 `0/0` | `test_shared_hook_owning_features_do_not_claim_their_own` |
| committed 文件必须等于生成器输出 | `test_committed_file_is_what_the_generator_produces` |

> 口径：**"自动生成"是一种承诺**（谁都能重跑出同样的字），不是一个标签。
> 承诺不成立时，文档就从"事实的记录"退化成"某个人的说法"。

### 7.6.5 一个功能名会掩盖它的**第二条**链路

2026-10-25 第 26 轮做"再找一个有静态证据的功能"时，最省事的读法是
"水印已经做了（`watermark_off`）"，于是往下跳过。实际情况是：

| 看起来是 | 实际是 |
|---|---|
| 一个"去水印" | **两条互不相干**的实现 |
| `cu.l` 构造器 → 字段 `r` → `ext="2"` 随 `/kdapi/image/combine` 上传 | **服务端合成**（导出的 PDF/图） |
| — | `CommonWebPictureBrowseActivity.c2(Bitmap)` → `Canvas.drawBitmap` 用 `Math.random()` 定位叠水印 → **纯本地绘制**（看大图） |

第二条**不经过 `cu.l`、不经过服务端、不发请求**，所以 `watermark_off` 结构上盖不到它。
判定方法不是"再读一遍文档"，而是问一个可机械回答的问题：

> **这个行为的判定输入从哪里来？** 只要它来自 `Intent` extra / 页面 JSON / 资源 id，
> 而现有钩子只改了某个单例字段或网络参数，那就是另一条链路。

上例里 `q0` 的输入来自 intent `INPUT_NEED_WATER`（`GotoPictureBrowseWebAction` 把页面给的
`needWatermark` 传下来），与 `cu.l` 没有任何数据依赖。

**这条推广开来是一个清单**：同名功能要按"判定输入来源"拆，而不是按功能名归并。
每个来源至少要有一条静态证据（文件:行号）说明它**真的**参与决策。

#### 附带教训：字面量会在一份文件里出现两次，方向相反

写"证明 extra 存在"的断言时用了 `re.search` 取第一处 `"INPUT_NEED_WATER"`，
命中 `:909` 的 **`putExtra`（写）**，而真正要证明的是 `:1292` 的
**`getBooleanExtra`（读）** —— 断言于是报"不再走 getBooleanExtra"，看起来像代码坏了，
其实是**测试读错了位置**。这与第 25 轮"`grep -A3 exit_guard` 命中了第 8 节"是同一个错。

现在的写法：**断言数量 + 断言方向**。

```python
self.assertEqual(self.text.count('"INPUT_NEED_WATER"'), 2)   # 写/读各一处，数目变了就重核
reads = [m for m in re.finditer(...) if 'getBooleanExtra' in self.text[m.start():m.start()+1200]]
self.assertEqual(len(reads), 1)                              # 恰好一处"读"
```

#### 反向验证的**验证**：先确认探针本身会失败

给新测试做反向验证时，第一版脚本把一个"改坏的文本"赋给 `tc.text`，
然后调 `tc.run()` —— 但 `setUp()` 会**重新读文件**，把注入的坏文本覆盖掉，
于是"注入破坏后仍然全绿"。差一点就把一个**没被验证过的测试**当成已验证。

正确做法：把 `ACT` 指向一个写坏的**临时副本**（让 `setUp` 读到坏数据），再跑。
改完后 3 条结构断言全部在注入破坏时精确报错、原样时通过。

> 铁律：**反向验证要先证明探针会失败。** 只有"注入破坏 → 精确报错"这一对都出现，
> 才说明这个测试真的在测东西。否则它只是一段打印 `ok` 的代码。

#### 再一条：别用前两个样本给 17 个调用点下结论

核 `bk/a;->p()Z`（VIP 布尔）的作用面时，我先看了 6 个调用点，发现结果都进
`Boolean.toString`，就写下"17 处全部只用于打点"。写成脚本全扫一遍之后是：

| 类别 | 数量 |
|---|---|
| 真闸门（`move-result` 后紧跟 `if-*`） | **3**（`aj/f:2305`、`oj/d:1038`、`xi/c:282`） |
| 只打点 | **14** |

`aj/f` 里 VIP 为真就 `return-void`，否则置标志再调 `u()` —— 是明确的早退分支。
**结论方向反了**，而且差一点就进了文档。

判据可以机械写成一句话：**"结果被谁消费"** ——
`move-result r` 之后 8 行内出现 `if-* r` ⇒ 闸门；只出现 `toString`/`append` ⇒ 埋点。

> 规矩：**枚举类结论必须来自全量脚本，不能来自抽样阅读。**
> 抽样只能生成假设；"全部/没有一处"这种量词必须先跑一遍全量再写。

## 8 找钩点：按调用量排序，别按名字猜

2026-10-25 第 7 轮，为了加一个 VIP 相关功能，我基于字符串搜查连续踩了三次空：

| 候选 | 看起来像什么 | 实际是什么 |
|---|---|---|
| `GetUserInfoVIPTextWebAction` → `t.c()` / `t.d()` | "VIP 文本/可见性"，像会员判定 | 只读 `VipPrivilegesTriggerPreference` 的**偏好开关**（控制标签显不显示）|
| `vipPrivilege`（`VipQuestionPrivilegeAction`） | 名字直译"会员特权" | 读 title/btnTxt/tips/jumpUrl，弹一个**营销窗** |
| `MyDownloadActivity` 的"剩余离线次数" | 用户可见的额度 | 纯 UI 格式化 `Resources.getString(0x7f10051e, O0)`，改它不增额度 |

三次都是**语义看起来对、实际与放行无关**。中文 UI 串尤其容易误导：它只说明
"用户看得见"，不说明"这是判定点"。

### 8.1 换方法之后就找到了

统计 `L*a*ip*;->*` 的调用点并按量排序：

```
com.kuaiduizuoye.scan.web.VipLimitViewModel.b(String, int, Function2)   3 处直接调用
```

形参 `(产品名, 已用次数, 回调)`，回调 `Function2<Boolean, Integer, Unit>` ——
**第一个参数就是"允许吗"**。这才是额度判定的真入口。

### 8.2 规则

1. **按调用量排序**：一个方法被 3 个不同业务入口调用，它比一个孤立的 `isVip()` 更可能是真闸门；
2. **看形参**：带 `int` 的"次数/额度"、带 `Function2<Boolean, …>` 的回调，比带 getter 名的更可信；
3. **看调用方是谁**：`PaperMainView`（答题主界面）、`fh/g`（H5）这种真实业务类，
   比 `*Activity`（纯展示）更可能是判定链路上的；
4. **中文 UI 串不算证据**：它只证明"用户看得见"；
5. **改之前先确定改什么**：`VipLimitViewModel.b` 能"看到"判定，但把回调改成 true 并不会
   真的放行（服务端下发时再校验）—— 那就只观测，别假装能改变结果。

### 8.3 与门禁的关系

找到候选后立刻用 ⑥ 验一遍：

```bash
python3 kit/scripts/smali_usage.py --smali work/apktool_out \
    --target com.kuaiduizuoye.scan.web.VipLimitViewModel:b
# USED  … 3 处直接调用，例: g.smali:1898 / PaperMainView.smali:1437 / :1557
```

`USED` 才算通过。`TYPE-ONLY` 的类只能钩构造器/字段读（`watermark_off` 就是这样选的），
钩方法体大概率空转。

---

## 9. 第 28 轮：**先证明缺口存在，再写功能**

这一节记一个被自己推翻的候选，因为它比成功的那个更有教学价值。

### 9.1 我差点写了一个重复功能

候选：`bridge_caller_log` —— "在 `HybridWebView.dispatchAction` 上记页面发起的每个
action 名，覆盖全部 225 个 `@FeAction`，不像 `bridge_action_log` 只钩两个"。

听起来很对：`bridge_action_log` 确实只钩了 `FeDownloadMediaAction` 与
`GetUserInfoWebAction` 两个精确类。我据此写了完整实现、注册了功能、加了
`BRIDGECALL` 前缀与三条用例，门禁 ④ 还把两个新目标判成 `USED`。

**然后我去读 `H5BridgeLog.kt`，发现它钩的就是这两个方法**：

```kotlin
n += Xp.hookAllBefore("…HybridWebView", "dispatchAction", …) { record(param) }
n += Xp.hookAllBefore("…HybridWebView", "dispatchActionToListeners", …) { record(param) }
```

而 `record()` 的第一行就是 `param.args.firstOrNull { it is String }` → **记 action 名**。
也就是说 `bridge_caller_log` 会产出与 `H5BRIDGE` 行**同样**的 action 名集合，
只是换个前缀。它是个更差的 `h5_bridge_log`，不是新能力。

> **铁律：写功能前先 grep 现有功能钩的类。**
> "`bridge_action_log` 只钩两个"是真的，但由此推出"桥没有覆盖面观测"是假的 ——
> 覆盖面观测一直由 `h5_bridge_log` 提供。**单个功能的局限 ≠ 模块的局限**，
> 而门禁不区分这两者：④ 只要目标存在且被调用就判 `OK`，它会为一个重复功能全绿。

已回滚（含前缀、用例、fixture）。回滚比留下更贵，但留下一个重复功能会永久污染
每次抓取分析。

### 9.2 真正缺口的判据

换判据后找到 `fetchPayInfos`（`FetchPayInfosAction`，`@FeAction(name="fetchPayInfos")`）：

```smali
:onAction   invoke-virtual {p2}, Lorg/json/JSONObject;->toString()Ljava/lang/String;
            invoke-static {p2}, L…/Scancodecreatepayorder$Input;->buildInput(…)…
            invoke-static {p1, p2, v0, v1}, Lcom/baidu/homework/common/net/Net;->post(…)
```

`Scancodecreatepayorder$Input` 的构造器把三个常量钉死：

| 字段 | 值 |
|---|---|
| `__url` | `/vippayui/clientpay/kdclientinnerpayorder` |
| `__pid` | `vip` |
| `__method` | `1`（POST） |

**页面能把任意 `payInfo` 串原样 POST 到 VIP 下单接口，再把回包交回页面。**

它符合"真缺口"的三条判据，缺一条都不该做：

1. **现有功能结构上够不到**：`h5_bridge_log` 只记 action 名 + 原始 JSON，
   `bridge_action_log` 的两个目标里没有它 —— 没有任何功能回答"页面在驱动下单"；
2. **有静态证据**：`smali_usage.py --target …FetchPayInfosAction:onAction` → `REFLECTIVE`
   （`@FeAction` 反射分发，静态 0 invoke 是设计如此，非死代码）；
3. **有明确的价值方向**：这是**支付**链路，而且方向是"页面 → 宿主 → 服务端"，
   与"宿主 → 页面"的只读观测不是一回事。

### 9.3 落地方式：扩展，不是新增

`fetchPayInfos` 与 `downloadMedia` / `getuserinfo` 是同一个问题的三个实例
（"页面在驱动宿主替它做什么"），所以它进 `bridge_action_log` 的第三个变体
`BRIDGE payorder`，而不是新功能。**判据：同类观测进同一个功能，除非它们的开关必须分开。**

**刻意不记 `payInfo` 的值**：

```
BRIDGE payorder submit len=48 keys=2:goodsId,price pid=vip
```

值里可能有订单号、金额、支付凭据，而抓取文件是明文落盘的。长度 + 键名已足够回答
"payload 多大、带哪些字段、什么时候发生"。

### 9.4 一个被新变体打破的消费端假设（本轮真 bug）

新变体首版 `fields` 里**没有 `action`**，而另外两个 `BRIDGE` 变体都有。于是：

```
bridge_inventory.py:78
  for action, n in sorted(semantic.items(), key=lambda kv: (-kv[1], kv[0]))
TypeError: '<' not supported between instances of 'NoneType' and 'str'
```

`sorted` 的 key 是元组，比较到第二项 `None < str` 直接抛。**整个统计工具崩掉**。

危险的地方在于 schema 侧测试**全绿**：三条 fixture 都解析成功、kind 对、variant 对、
字段也都取到了 —— 只是**少了一个别人要的键**。

两层修法，缺一不可：

| 层 | 修法 | 为什么不能只做一层 |
|---|---|---|
| schema | 补上 `action` | 消费端的假设本来就成立，不该为它改契约 |
| 消费端 | `action or f'(未知变体:{variant})'` | 统计工具崩掉会让"有多少条"这个本可回答的问题变得不可回答；新变体总会再来 |

新增 `KindFieldContract` 测试：每个 `(kind, variant)` 声明**消费端依赖的键**，
用 fixture + 全部用例行逐条断言。反向验证：去掉 `action` ⇒ 立刻红并指名
`BRIDGE/payorder 缺少消费端依赖的字段 action`。

### 9.5 契约要按 variant 写，不能按 kind 写

第一版把 `'VIPLIMIT': ('product',)` 写成 kind 级，结果 `VIPLIMIT result allowed=… remaining=…`
被判缺 `product` —— **假红**。

`VIPLIMIT` 有两种**不相交**的形状（`ask` 带 `product`/`used`，`result` 带
`allowed`/`remaining`），两个消费端（`capture_transcript` / `session_report`）也都按
variant 分支。所以契约必须是 `(kind, variant) -> keys`。

> 与 §7.6.1 同一条教训：**规则的粒度要匹配事实的粒度。**
> 粒度太粗 ⇒ 假红（本应放行的被判失败）；粒度太细 ⇒ 漏报。
> 这里"事实"是 variant —— 因为消费端就是按 variant 分支的。


## 10. 钩点共享：两个功能钩同一个方法时会怎样（2026-10-26）

### 10.1 为什么单独一节

模块有 41 个功能，各自装钩子。**钩点冲突不会让门禁变红、不会崩溃、不会打日志** ——
它只是让某个功能安静地少收数据。这类问题只能靠"主动列出来"发现。

实测当前有 2 处**跨文件**共享：

| 钩点 | 功能 A | 功能 B |
|---|---|---|
| `HybridWebView.dispatchAction` | `BridgeGuard.kt:69` | `H5BridgeLog.kt:39` |
| `HybridWebView.dispatchActionToListeners` | `BridgeGuard.kt:70` | `H5BridgeLog.kt:41` |
| `WebView.loadUrl`（两个重载） | `NavLog.kt:41`（before） | `WebInjector.kt:125`（after） |
| `android.app.Activity.onCreate` | `NavLog.kt:51`（after，只记一行 `NAVACT`） | `Md3Skin.kt:98`（after，设状态栏/窗口色） |

**`WebView.loadUrl` 的相互作用**（2026-11-02 补登记）：

* `NavLog` 用 **before**，只读 URL 不写 `param.result` ⇒ **不短路**；
* `WebInjector` 用 **after**，在真实加载之后注入脚本 ⇒ 依赖"这次加载真的发生了"；
* 二者互不依赖：`NavLog` 先跑只是记一行，`WebInjector` 照样能在 after 里注入；
* **但顺序有含义**：若将来有人给 `NavLog` 加 `param.result = null`（拦截加载），
  `WebInjector` 的 after 仍然会执行，而页面其实没加载 —— 注入会打在一个空页面上。
  这正是共享表要记下来的那种"没人记录过的耦合"。

（`AdFeatures.kt` 里两个 object 也钩了同样的 `aj.a.d/f/h`，但那是**同一文件内的
同一段逻辑**，不算跨功能共享，不在本节登记。）

**`Activity.onCreate` 的相互作用**（2026-11-14 补登记，MD3 皮肤引入）：

* 两个都用 **after**、都不写 `param.result` ⇒ **没有任何短路**，顺序只影响"谁先读 thisObject"；
* `NavLog` 只读类名（`NavFilter.isHostClass` 过滤），`Md3Skin` 只对**宿主包**的 Activity 改窗口色；
* **耦合点**：`Md3Skin` 的 `md3_native_window` 若关掉，`NavLog` 完全不受影响；
  反过来 `NavLog` 关掉，`Md3Skin` 的窗口配色照旧。**两功能互不依赖**；
* 但有一条真实顺序含义：`Md3Skin` 在 after 里设 `statusBarColor`，若宿主某个 Activity
  在 `onCreate` **之后**自己再设一次（沉浸式页面就是这么干的），皮肤会被覆盖 ——
  这不是钩点冲突，是 App 自己的后写赢，已记在 `UI.md` §11.2 的边界里。

**TYPE-ONLY 不算共享**：`HybridWebView$ReturnCallback` 在三个文件里都以**类型**出现
（字段/参数/new），但它不是被钩的方法 —— 真正被钩的是 `$ReturnCallback.call`，
而那个只被 `H5BridgeLog` 一个文件钩。共享表回答的是"两个功能钩同一个方法时会怎样"，
类型引用不影响执行，所以排除。

### 10.2 实测语义（`observed`，有代码依据；真机行为 `unverified`）

两者都用 `Xp.hookAllBefore`，而它的实现是（`util/Xp.kt:146`）：

```kotlin
XposedBridge.hookMethod(m, object : XC_MethodHook() {
    override fun beforeHookedMethod(param: MethodHookParam) {
        if (gate != null && !KdConfig.isOn(gate, true)) return
        cb(param)
    }
})
```

* **没有设 `priority`** ⇒ 全部走默认优先级；
* `BridgeGuard` 拦截时会写 `param.result = null`（`BridgeGuard.kt:113`），
  语义是"跳过原方法实现"；
* `H5BridgeLog` 只**读取** `param.args`，不写 `result`。

**Xposed 对多个 `beforeHookedMethod` 的处理**：同一个方法的多个 hook 回调都会被执行，
一个回调设置 `result` **不会中断**其余 before 回调（但会跳过原方法体与所有 after 回调）。
⇒ **被 `BridgeGuard` 拦下的那次调用，`H5BridgeLog` 仍然能记录到它。**

这个结论是本节最重要的内容：它意味着 `GUARD blocked=…` 与 `H5BRIDGE …` 两行
**可以同时出现在同一次调用上**，读抓取时不该认为"被拦了所以桥日志少一条"。

**`unverified`**：以上是代码语义推论，真机上未做过"拦截同时两行都在"的实测。

### 10.3 新增钩点时的规矩

1. 先跑 `python3 kit/scripts/check_hook_sharing.py` 看目标是否已被别人钩；
2. 若已共享，**在 10.2 的表里加一行**，写清：
   * 各自用 before 还是 after；
   * 谁会写 `param.result`（短路方）；
   * 短路后另一个还能不能读到这次调用；
3. 门禁 `check_hook_sharing.py --strict` 会拦住"共享了但没登记"的情况。

### 10.4 为什么这条检查不做成"禁止共享"

共享本身往往是对的：`BridgeGuard` 负责拦、`H5BridgeLog` 负责记，
两者职责不同、都需要在同一个入口工作。**要防的不是共享，是"共享了却没人知道语义"**。

### 10.5 判定的可复现性：一次"假红"暴露的真实缺陷（2026-10-26 第 31 轮）

门禁 ④ 连续跑了三次，三次都在 `118` 个目标里给出**不同的** `resolved` 数：
`96 / 107 / 112 / 116`。同一份静态输入、同一份代码，结论却不一样。

根因在 `smali_usage.analyse()`，两个条件叠在一起才出症状：

| 条件 | 事实 |
|---|---|
| 读预算 | `read_budget=96 MB`，而"提到任一目标描述符"的文件合计 **140.4 MB** ⇒ 必然有 44 MB 读不到 |
| 顺序 | 命中文件列表直接用 `rg -l` 的输出顺序，而 `rg` 多线程遍历 ⇒ **每次顺序不同** |

顺序一变，被预算挡在门外的文件就变 ⇒ `class_refs` 为 0 的目标也变 ⇒
`DEAD` 与 `TYPE-ONLY` 在两个运行之间来回翻转。

**这类缺陷比"判错"更坏**：判错可以定位、可以修；而"结论依赖遍历顺序"
会让人以为门禁本身就是噪声，于是学会"重跑一次看看"——那正是 `verify.sh`
里 `RETRY_GATES` 最危险的地方，所以那里坚持打印 `RETRY-PASS` 而不是静默吞掉。

两条修法同时做，缺一不可：

1. `hit_files = sorted(grep_files(...))` —— 同样输入必得同样文件集；
2. **证据不全时不许断言 `DEAD`**：新增 `INCOMPLETE` 结论。预算挡掉的文件里
   如果提到过某个目标，那它的"零引用"是**没看完**而不是**不存在**，
   必须降级并写明原因（用 `rg -o -I` 只回描述符名，不把 44 MB 再读一遍）。
   预算提到 320 MB（2× 余量）后实测 0 个 `INCOMPLETE`。

`INCOMPLETE` **不判红**：它描述的是"这次没算出结论"，不是"钩点坏了"。
和 §11 的 ⑨ 同一条原则 —— 一条无法被本地证伪的规则不能做成永久红灯，
否则它会教人忽略门禁。

离线回归测试：`kit/python/tests/test_smali_usage.py::ReadBudgetIsNotEvidence`。
其中 `test_same_verdicts_regardless_of_grep_order` 把 `grep_files` 换成
**反向排序**的版本，断言每个目标的结论逐字相同 —— 直接锁住"结论不得依赖遍历顺序"。
