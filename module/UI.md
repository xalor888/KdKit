# KdKit 设置界面重设计（发版前）

> 2026-11-14 · 目标：38 个功能在**一屏内看得懂**，不再需要读技术说明才知道该不该开。
> 参照 [`WeKit`](../../../WeKit) 的设置页范式：**分段卡片（SegmentedColumn）+ 折叠大标题 + 一行一项**。

## 1. 现状的问题（对着当前截图逐条数）

| # | 问题 | 具体表现 |
|---|---|---|
| 1 | **结构不可见** | 38 项做成 38 张独立大卡，一路滚到底；"广告"和"诊断"在视觉上一样重，用户分不清"我该开哪些" |
| 2 | **文案是技术说明** | 副标题写的是实现细节：`钩 dj.e.f()`、`7.7.2 里这个类是 aj.a`、`BK.a.p / n`、`服务端计次` —— 对一个只想关广告的人全是噪音 |
| 3 | **信息密度低** | 每项 ~120dp，一屏只看得到 4 项；判断"我开了几项"要翻到顶 |
| 4 | **热/冷矛盾** | 卡片里写"改开关即时生效"，页底又写"改动后请完全结束并重新打开快对"，两句直接打脸 |
| 5 | **诊断卡抢戏** | "配置通道 / 权限 644 / 原子重写"占掉首屏一整张卡，而它对普通用户零价值 |
| 6 | **没有批量** | 想"只留去广告"要一格一格拨 38 次 |
| 7 | **没有关于页** | 发版后用户问"这模块装了没、走的哪条注入链路"，界面里没有答案 |

## 2. 参照 WeKit 的范式（只借这三件事）

WeKit 的设置页不是"很多卡片"，而是：

1. **一卡一组**：同一类的行合进一张圆角卡，行间用内缩分隔线（`SegmentedColumn` + `BaseItemContainer`）；
2. **折叠大标题**：滚动时标题收起成一行，首屏留给内容；
3. **一行一件事**：左侧标题 + 一行副标题，右侧控件；细节进二级页/展开区，不在列表里堆字。

## 3. 新的信息架构（按"用户想做的事"分组，不按代码分类）

| 组 | 名称 | 项数 | 默认 | 一句话 |
|---|---|---|---|---|
| `ads` | 去广告 | 7 | 展开 | 开屏、横幅、页签、弹窗、信息流，一次关干净 |
| `content` | 内容与会员 | 4 | 展开 | 会员标识、水印、服务端弹窗 |
| `ease` | 省心开关 | 4 | 展开 | 强制更新、首次引导、退出守卫、设置页入口 |
| `pk` | 答题助手 | 1 | 展开 | 口算 / 诗词 / 成语 / 单词 PK 自动作答 |
| `diag` | 诊断与抓取 | 23 | **收起** | 观测数据写文件，排障时才开 |

合计 38 = 7 + 4 + 3 + 1 + 23（与 `FeatureRegistry.all` 一致，门禁校验）。

**首屏**（1080×2400 实测）应能看到：标题 + 状态行 + 搜索 + 「去广告」整组 7 行 + 「内容与会员」组头。

## 4. 每一行长什么样

```
┌───────────────────────────────────────────────┐
│ 开屏广告                              [ 开关 ] │
│ 打开 App 时那张全屏广告，不再出现               │   ← 一行、省略号截断
└───────────────────────────────────────────────┘
   ↓ 点击行（不是点开关）展开
   技术名：RemoveSplashAd · 标识 rm_splash · 即时生效
   （原有技术说明：钩 dj.a 的 j/k/g …）
   [子选项]
```

* **标题**（人话，≤ 8 字）与**副标题**（≤ 22 字，一行）来自新增的 `ui/Copy.kt`；
* 原来那串技术说明**不删**，降级到展开区，标题旁不再出现类名/旧版本名；
* 徽标只在展开区显示"即时生效 / 需重启"，顶部统一说一次，**不再自相矛盾**；
* 关着的项副标题变灰但不消失（用户仍要知道它是什么）。

## 5. 顶部与底部

* 顶部：折叠大标题 `KdKit`，副标题 `已启用 18 / 38 · 快对 7.10.2`；
* 状态行（一行 chips）：`注入 ✓` · `配置通道 ✓` · `宿主 7.10.2`；异常时变红并可点开诊断；
* 搜索框（跨组过滤，命中时自动展开所有组）；
* 组头右侧：`全开 / 全关` 小按钮（只作用于该组）；
* 底部：`推荐配置（去广告 + 内容 + 省心 全开，诊断全关）` · `恢复默认` · `复制诊断信息` · `关于`。

## 6. 验收（可测，不靠"看着还行"）

| 检查 | 判据 |
|---|---|
| 覆盖性 | `Copy.kt` 恰好覆盖 `FeatureRegistry.all` 的 38 个 id（多一个少一个都红）—— 见 `SettingsCopyTest` |
| 文案纪律 | 副标题 ≤ 22 个字符、不含 `钩`/`()`/`aj.a`/`7.7.2`/`RS4` 这类技术词 —— 同一份单测里查 |
| 首屏密度 | 1080×2400 截图里首屏 ≥ 9 行可见（当前 4 行） |
| 不回归 | `module/scripts/verify.sh` 全绿（除既有的 ⑬ 真机验证：设备装的是 7.10.0 而分析基线是 7.10.2） |
| 真机 | 装到 `emulator-5558`，切换一项 → 抓取文件里对应 key 变化；组级"全关"后 38 项全部 false |

## 7. 不改什么（发版纪律）

* **不动** `BaseFeature.id`（持久化 key，改了等于丢用户开关）；
* **不动** 钩子、`FeatureRegistry` 顺序、`README` 功能表（门禁 `check_feature_parity` 校验 id/热/选项三列）；
* 技术说明留在 `BaseFeature.summary`（机器可读、README 对齐），**只新增 UI 层展示映射** ——
  这样"改文案"不会牵动任何钩子门禁。

## 8. 落地（文件与契约）

| 文件 | 作用 | 门禁 |
|---|---|---|
| `ui/SettingsCopy.kt` | 38 条「人话标题 + 一句说明」+ 5 个分组的元数据 + `recommendedOn` | `SettingsCopyTest`（7 条） |
| `ui/MainActivity.kt` | 折叠大标题 + 分段组卡 + 行内开关 + 点击展开详情 + 组级全开/全关 + 全局推荐配置/恢复默认 + 诊断对话框 + 关于 | `② assembleDebug` |
| `ui/OptionEditors.kt` | 未改（子选项仍由功能自己的 `KdOption` 声明） | 原有门禁 |

**没有动**的：`BaseFeature` / `FeatureRegistry` / 任何钩子 / `README` 功能表。
模块版本顺带升到 **1.1.0（code 2）**。

## 9. 实测（2026-11-14，`emulator-5558`，1080×2400）

| 判据 | 结果（observed） |
|---|---|
| 首屏密度 | **7 行功能可见**（重做前 4 行）+ 组头 + 状态行 + 搜索，一屏读完"去广告"整组 |
| 状态行 | `✓ 设置已同步到快对 · 5 条`（重做前是"已发布 5 项 · 权限 644"，要读权限数字） |
| 组结构 | `去广告 6/7` + `全开 / 全关`；`诊断与抓取 10/23` 默认折叠 |
| 展开详情 | `标识 rm_main_banner · 即时生效` + 技术说明（尾部"（改开关即时生效）"已剥掉，不再重复） |
| 开关链路 | 拨 `rm_popup` → `shared_prefs/kdkit.xml` 写入 `rm_popup=false` → 发布文件 `flags=5→6`、`mode=644` ✅ |
| 单测 | `SettingsCopyTest` **7/7**；Kotlin 合计 **172** 条 |
| 截图 | 前：`work/ui_before_flat.png` · 后：`work/ui_after_top.png`（首屏）、`work/ui_after_group.png`（滚动）、`work/ui_after_detail.png`（展开） |

## 10. 发版清单（界面侧）

1. `versionCode 2 / versionName 1.1.0` —— 已改。
2. 设置页首屏不再出现任何类名、旧版本号、权限数字（`SettingsCopyTest` 拦回归）。
3. 「关于」里给出模块版本、适配基线（7.10.2 / 1860）、兼容版本、注入方式 —— 用户能自助判断"装没装上"。
4. 诊断信息仍可一键复制（设置页 → 诊断 → 复制；或 `kit/scripts/module_report.py`）。

## 11. 会员推广清理与 MD3 皮肤（v1.2 新增）

这两件事都是"**用户看得见**"的需求，但它们跨了三个层 —— 这也是它们应该各自有开关的原因。

### 11.1 `rm_vip_promo`：关掉"劝你开会员"

| 层 | 拦在哪 | 证据 |
|---|---|---|
| 底部支付弹窗 | `MainBottomPayDialog.Q/P` 短路 + `DialogFragment.show` 按类型兜底 | 静态：`MainBottomPayDialog.smali` |
| 服务端弹窗 | `hh.y.F()`（`winVIPBottom` 分支 → VIP 购买页） | **真机**：日志 `VipPromo: blocked winVIPBottom` |
| 「我的」页会员卡（**原生**） | `MineMembershipCardsView.bindView` 之后整块 `GONE` | **真机**：截图 `work/ui_mine_nopromo.png`（VIP 卡 + ¥1.9 特惠整块消失） |
| 页面内开通入口（H5） | 注入 JS：短文本 + 含「立即开通 / 限时特惠 / 首月 / 续费」→ 隐藏最近的容器 | 可关（`rm_vip_promo_h5`）；不做请求拦截 |

**为什么"我的"页要单独一条钩子**：它不是 WebView，JS 碰不到 —— 一开始只做 H5 时，
真机截图里那张 VIP 卡原样躺着。**"整页去推广"必须原生与 H5 两条路都做。**

### 11.2 `md3_skin`：Material 3 简约皮肤

| 层 | 做什么 | 边界 |
|---|---|---|
| H5 | 注入 CSS：中性背景 `#F6F4F9`、卡片 16 圆角 + 极淡投影、按钮胶囊化、统一字体；`full` 档额外把「面积 > 120000 px² 且高饱和」的色块中性化 | 页面首帧仍是原样式，约 0.3s 后切换 |
| 原生窗口 | `Activity.onCreate` 后设状态栏/导航栏/窗口底色 | 部分页面会自己再改一次（如沉浸式页） |
| 原生控件 | `View.setBackground` 后，若**面积大 + 高饱和**则换成中性色（取色只认 ColorDrawable / BitmapDrawable / GradientDrawable） | 按钮、图标、角标在面积阈值以下，不会被误伤；取不到颜色的图片背景不动 |

**实测（`emulator-5558`，1080×2400）**：首页那块品牌黄大色块 → 中性底色，图标与文字保留
（`work/ui_md3_home.png`）；抓取里 `MD3 window themed` / `MD3 native bg neutralised` 各命中多次。

**做不到的部分（诚实边界）**：完整的"MD3 重绘"（控件形状、间距、字体层级）需要改布局或做
RRO 资源覆盖，风险是崩溃面 —— 本模块只做**看感四件套**（颜色/圆角/阴影/字体），
所以叫"简约皮肤"而不是"重做 UI"。

### 11.3 发版前的取舍

* `rm_vip_promo` **默认开**（纯推广，无副作用；不碰会员判定）；
* `md3_skin` **默认开**，但 `md3_level=light` 可回到"只改圆角阴影"的保守档；
* 两个功能都是热开关 —— 关掉立刻回到原样，不需要重装。

## 12. 深色模式 · 液态玻璃 · 预见性返回（v1.3）

参照对象：`~/Documents/proxyui`（用 Glasmio 做真·背景采样模糊的那套 iOS 风玻璃）与 WeKit 的
`ui/content/liquid` + `ui/animation/predictiveback`。

### 12.1 设置模块（KdKit 设置页）—— 三件全做了

| 件 | 实现 | 判据 |
|---|---|---|
| 深色模式 | 三档 `跟随系统 / 浅色 / 深色`（`UiPrefs`，顶栏月亮按钮循环切换）；配色走 `GlassColors` 双板（light/dark） | 截图 `work/ui_glass_light.png`（浅）/ `work/ui_glass_dark.png`（深） |
| 液态玻璃 | 背景是**自绘 mesh 渐变**（两层纵向渐变 + 两块柔光斑）+ 卡片半透明填充 + 1dp 高光描边 + 柔和外阴影（`ui/Glass.kt`） | 同上；关掉玻璃开关 → 卡片退回不透明，布局不变 |
| 预见性返回 | `Manifest` 开 `enableOnBackInvokedCallback` + `PredictiveBackHandler`，跟手缩放 0.94 / 淡出 0.82，松手 finish | API 33 以下自动退回系统默认返回 |

**为什么没用 Glasmio**：proxyui 的玻璃依赖 `io.github.neoruaa.glasmio:0.1.2`（minSdk 33、compileSdk 37、
真·backdrop 采样 + 逐帧重模糊）。设置模块 minSdk 26、且是 Xposed 模块（依赖越少越好），
所以走"**自绘柔和背景 + 半透明卡片**"的等价做法：视觉上是同一个透光效果，
代价是**透不出桌面壁纸**（设置页本来就是全屏不透明场景，这个代价可以接受）。

### 12.2 快对 App

| 件 | 做到了 | 边界（实测踩过） |
|---|---|---|
| 液态玻璃（H5） | 卡片半透明 + `backdrop-filter: blur(16px) saturate(1.25)` + 高光描边，浅色/深色两套填充色 | WebView 不支持 blur 时退化成半透明（仍然好看）；截图 `work/ui_glass_light_home.png` |
| 深色（原生） | 状态栏 / 导航栏 / 窗口底色按 `md3_theme` 切深色，状态栏图标跟着变白 | **只到窗口级**；原生控件（列表、按钮）仍是 App 自己的浅色 |
| 深色（H5） | **不做**（深色下 `md3_skin` 不注入页面） | 见下 |
| 预见性返回 | **做不到** | 宿主 App 的转场是它自己的 `OnBackInvokedCallback` + 预测性返回动画；模块只能改"它加载了哪个页面"，改不了它怎么动画 |

**H5 深色为什么收敛成"不做"**（两次尝试都坏，记录在这）：

1. **逐块改色**（大亮块压深 + 近黑文字提亮）：页面白底可能来自父层、`background-image` 或伪元素，
   逐块只能改到"自己带 `backgroundColor` 的那一层" ⇒ 真机上是**白卡 + 白字**，读不出来
   （`work/ui_md3_dark_home3/4/5.png` 三次现场）。
2. **整页反色**（`filter: invert(1) hue-rotate(180deg)` + 媒体再反色）：卡片与文字对了，
   但**页面底色不跟**（html/body 的背景是否参与 filter 在 WebView 里不稳定），
   4 次尝试后仍是浅底 + 深卡（`work/ui_md3_dark_home6/7/8.png`）。

⇒ 与其交付一个"看起来深了但读不清"的皮肤，不如只做原生窗口。等快对的 H5 自己支持
`prefers-color-scheme`（或做 Dark Reader 级别的引擎）再回来接这一层。

### 12.3 发版取舍

* 设置模块：三件默认开；顶栏两个按钮（主题 / 玻璃）即时切换，不重启。
* 宿主：`md3_skin` 的玻璃与浅色归一默认开；深色跟随系统但**只影响窗口配色**；
  `md3_theme` 可强制 light/dark。

## 13. 稳定化与 Miuix 化（v1.4）

一轮真机反馈引发的返工：**界面再好看，白屏和 ANR 都是致命的**。这一版先修稳定性，再换视觉。

### 13.1 三个真问题（都有现场证据）

| 问题 | 根因 | 修法 |
|---|---|---|
| **拍题答疑 / 口算 PK 白屏** | `md3_skin` 的 H5 注入（背景覆盖 + `backdrop-filter`）在"容器内再渲染"的页面上会让内层不可见 | ① H5 注入默认**关**（`md3_h5`），只有主动开启才注入；② 注入后 1.2s / 3s 各做一次**白屏自愈**：检测不到文字与图片就把自己的 style 与标记全部撤掉（`REVERT_IF_BLANK_JS`） |
| **快对 ANR（"快对AI isn't responding"）** | `KdConfigBridge` 的配置读取在**调用方线程**上 `XSharedPreferences.reload()`，而调用方常是主线程（Activity.onCreate / View 背景钩子）—— 主线程停在 `startLoadFromDisk` | 读配置只读内存；磁盘刷新挪到后台 `HandlerThread("kdkit-prefs")`，按文件 mtime 变化节流（500ms） |
| **原生背景中性化拖慢页面** | 每个 `View.setBackground` 都 `post` 一个主线程任务 | 默认关（`md3_native_bg`）+ 每个 View 只排队一次 + 单进程 200 次预算 |

`kit/scripts/smoke_pages.py` 把这三件事变成可一键回归的命令：启动 → 首页 / 拍题答疑 / AI 写作 / 我的 / 设置页，逐页数文本节点，低于阈值判红；遇到系统弹窗（崩溃 / 权限）自动点掉再判。

### 13.2 视觉：Miuix + 液态玻璃 + 悬浮底栏

- 组件库：`miuix-ui:0.9.3` + `miuix-preference:0.9.3`（新代拆分模块，`SwitchPreference` / `ArrowPreference` /
  `SmallTitle` / `TopAppBar` / `Scaffold` / `NavigationBar`）。代价是整栈上抬：Kotlin **2.3.21**、
  compileSdk **37**、Compose 走 **CMP 1.11.1**（不再用 androidx BOM，避免两套 runtime）。
  AGP 8.13 对 compileSdk 37 只告警，已在 `gradle.properties` 显式压掉。
- 行：`SwitchPreference`（HyperOS 开关与行排版），不再画分隔线。
- 材质：`GlassCard` 三层 —— 彩色晕染底层 → `BlurEffect(26px)` 模糊 → 上亮下暗的高光边；背景加细噪点，否则"糊与不糊"看不出差别（上一版被评价"和没有区别"的直接原因）。
- 底栏：`GlassBottomBar`，浮在内容上方的玻璃胶囊，四个入口（去广告 / 内容 / 外观 / 诊断）一键滚到对应分组。

### 13.3 取舍

- 0.9.4 仍被 AGP 9.1 门槛挡住（`checkDebugAarMetadata` 实测），因此停在 **0.9.3**（PoC 里 0.9.3 + Kotlin 2.3.21 +
  CMP 1.11.1 + compileSdk 37 实测 `BUILD SUCCESSFUL`）。
- `miuix-blur` / `miuix-glass` 未在 Maven 发布（或 minSdk 33），所以玻璃仍是自绘 —— 但这次是**真模糊**（`RenderEffect`），不是纯半透明。


## 14. 黑屏与 miuix 落地（v1.5）

### 14.1 「打开就黑屏」的机制（真机反馈后定位）

两个原因叠在一起，恰好都在**新系统**上暴露：

1. `Surface(color = Color.Transparent)` + 自绘背景 `Canvas`：只要背景那一层没画出来
   （新系统渲染后端差异 / `RenderEffect` 不可用），整页就是纯黑 —— 因为窗口本身没有底色。
2. 玻璃卡里的 `BlurEffect`（`RenderEffect`）是唯一"平台差异大"的绘制特性。

修法：

* 根节点先铺**不透明**底色（`Scaffold containerColor` 与 `Surface color` 都给了实色），
  任何绘制失败都退化成"纯色页面"而不是黑屏；
* **移除 `BlurEffect`**，玻璃改用"晕染渐变 + 高光边"表达（视觉差异小，稳定性差异大）。

### 14.2 真正的 miuix（不是只换开关）

换的是**整套骨架**，不是只把 `Switch` 换成 `SwitchPreference`：

| 位置 | 组件 |
|---|---|
| 页面骨架 | `top.yukonga.miuix.kmp.basic.Scaffold` |
| 列表行 | `top.yukonga.miuix.kmp.preference.SwitchPreference` |
| 分组卡 | `top.yukonga.miuix.kmp.basic.Card`（`cornerRadius = 22.dp`，与 HyperOS 一致） |
| 主题/色板 | `top.yukonga.miuix.kmp.theme.MiuixTheme` + `lightColorScheme/darkColorScheme` |

`TopAppBar` 试过但**没有采用**：无 `scrollBehavior` 时它只渲染 subtitle，大标题整块不显示
（实测截图 `work/mx_light2.png`），所以大标题改为列表首项 + 右上三个操作按钮，更可靠。

### 14.3 深色模式

三档（跟随系统 / 浅色 / 深色）由 `UiPrefs` 持久化，`MiuixTheme` 随之切 `darkColorScheme`。
实测：`主题：跟随系统` + 系统 `cmd uimode night no` → 浅色（`work/mx_light_true.png`）；
`主题：深色` → 深色（`work/mx_final_light.png`）。


## 15. 液态玻璃（H5 层）做到哪一步（v1.6）

| 手段 | 说明 |
|---|---|
| `backdrop-filter: blur(18px) saturate(160%) brightness(1.04)` | 只施加在"被判定为玻璃卡"的块上（面积 ≥2 万 px²、亮度 >232），不是全页 |
| 三层渐变填充 | `冷白 → 冷蓝 → 暖白`（深色为 `深灰蓝 → 深蓝 → 紫灰`）——**玻璃必须自带颜色层次**，纯白半透明叠纯白页面等于没做 |
| 双层高光边 | 顶部 1.5px 白 0.92 + 底部 1px 白 0.45（深色反过来），模拟玻璃厚度 |
| 柔和外阴影 | `0 12px 32px rgba(31,36,58,.14)` |
| 20px 圆角 | 与 miuix/HyperOS 的卡圆角对齐 |

**做不到的部分（诚实边界）**：给页面 `body` 铺的柔和彩色光斑**看不见** —— 因为页面根容器
（`#app` / `page`）是不透明白色，盖住了 body 的背景层。要让光斑透出来，就得把根容器改成半透明，
而那正是 2026-11-14 白屏事故的现场。所以现在的"液态"来自**卡片自身的折射渐变 + 高光边**，
不是"隔着玻璃看到背景色散"。要后者，只能等页面自己做，或整页换成原生实现。

**白屏回归**：`smoke_pages.py` 五页全绿（首页 / 拍题答疑 / AI 写作 / 我的 / 设置页）。


### 15.1 液态玻璃的性能红线（v1.7）

第一版把 `backdrop-filter` 加到了 120 块上，真机出现 **"快对AI isn't responding"**：
主线程在 `nativePollOnce`（idle），但 `stm` 高达 688ms —— 渲染线程被大面积模糊压垮，不是死锁。

修法：**真模糊只给最大的 6 块**（面积 >120000 px²），其余块只有渐变填充 + 高光边 + 阴影。
扫描上限从 260 降到 120，定时从 3 次降到 2 次。改完五页 smoke 全绿、无 ANR。
