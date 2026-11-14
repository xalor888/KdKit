# Miuix / HyperChanger 调研笔记 —— 供 KdKit「Compose 设置页」改造使用

> 调研日期：2026-11-14 · 执行人：ref-study（子代理）
> 工作仓库：`/Users/xalor/Documents/kuaidui-kit`（**只读调研**：未改动 `module/`、`kit/` 下任何文件，未执行 git 操作）
> 参考目录：`reference/miuix`（git HEAD `19b5b83`，2026-11-14，shallow clone）、`reference/HyperChanger`（工作副本）
> 结论均给出可复现的证据（Maven POM / AAR 内 `AndroidManifest.xml` / `aar-metadata.properties` / `kotlin.Metadata mv` / 源码行号），第 8 节列出取证命令。

---

## 0. 结论速览（先看这 6 条）

1. **坐标**是 `top.yukonga.miuix.kmp`，当前有两代产物：
   * 旧代「单体 Android 库」`miuix-android`（0.0.1 → **0.8.8**）；
   * 新代「Compose Multiplatform 拆分模块」`miuix-ui-android` / `miuix-preference-android` / `miuix-icons-android` / `miuix-blur-android` …（0.9.0 → **0.9.4**，最新，2026-09-20 发布）。
2. **现在就用 0.9.4 是做不到的**：0.9.4 的类用 Kotlin **metadata 2.4.0** 编译，而本项目 Kotlin 2.1.20 的编译器**最多只读到 2.2.0**（下文有实测报错原文）；并且 0.9.4 的 AAR 声明 `minCompileSdk=37`，它带来的 Compose 1.12.x 又要求 `minAndroidGradlePluginVersion=9.1.0`（实测于 1.12.1）。
3. **不动 Kotlin 也有一条可用路**：`miuix-android:0.5.2`（metadata 2.2.0 / minSdk 26 / minCompileSdk 1 / Compose 1.9.0），配 Compose BOM `2025.09.00`（compose 1.9.1，minCompileSdk 35、minAGP 8.6.0）。设置页需要的 `Card`、`TopAppBar`、`Scaffold`、`SuperSwitch`、`SuperArrow`、`SuperDropdown` 都在这一代（`top.yukonga.miuix.kmp.extra`）。
4. **模糊/玻璃：有，但不在 0.9.4 的已发布产物里完整提供**。
   * 已发布：`miuix-blur-android:0.9.4`（`LayerBackdrop` / `drawBackdrop` / `textureBlur` / `progressiveTextureBlur` / `ProgressiveBlur`），**minSdk 33**；
   * 仅源码（`reference/miuix` main，未上 Maven）：`miuix-glass`（`Modifier.glassPanel` / `glass` / `GlassSurface` / `GlassTopAppBar` …）与 `miuix-material`（`EdgeStroke` / `GlassStyle(s)` / `GlassMaterial(s)`）；
   * 本项目 minSdk 26 的现实替代：`io.github.kyant0:backdrop:2.0.0`（HyperChanger 同款）或现有自绘 `GlassBackground` 渐变伪玻璃，API 31+ 可用 `Modifier.blur` 兜底。
5. **HyperChanger 的 OOBE** 是一个 **单 Activity 内的 4 页状态机**（`WELCOME → PREPARATION → AGREEMENTS → COMPLETE`，另有 3 个法务文本子页），入口在 `MainActivity` 根级 `AnimatedContent(showOobe)`，完成状态写 `SharedPreferences("oobe").completed`。可照抄的套路见第 4 节 10 条。
6. **推荐路径**：阶段一用 **0.5.2 + BOM 2025.09.00**（改动最小、当天可落地）；阶段二整体抬到 **Kotlin 2.3.21 + AGP 9.2.1 + compileSdk 37 + BOM 2026.09.00 + miuix 0.9.4**（与 HyperChanger 完全同栈，可对照调试）。版本矩阵见 5.2。

### 0.1 现状快照（重要：本仓库工作区在调研期间被并发修改）

* 调研开始时（13:00 左右）`module/app/build.gradle.kts` 是 `compose-bom:2024.09.02`、无任何 miuix 依赖——本文件第 5 节的「现状」指这个基线。
* 调研结束时（13:23）该文件已被**其他代理**改成 `compose-bom:2025.09.00` + `top.yukonga.miuix.kmp:miuix-android:0.5.2`，即**档 0 已在落地**（该改动不是 ref-study 做的；本次只新建了 `reference/NOTES.md`）。
* 因此：第 6 节草案 A 里 `SwitchPreference` 的示例，在当前工作区应改写成 `extra.SuperSwitch`（`miuix-android:0.5.2` 没有 `preference` 包）；若要直接用 `SwitchPreference`，需按 5.2 升到档 2。

---

## 1. 依赖坐标与版本

### 1.1 仓库里声明的版本（`reference/miuix`）

| 项 | 值 | 证据 |
|---|---|---|
| `groupId` | `top.yukonga.miuix.kmp` | `build-logic/src/main/kotlin/BuildConfig.kt` `LIBRARY_ID` |
| 库版本 | `0.9.4`（本地仓 HEAD 是 0.9.4 之后的 main，发布时会带 `-<gitshort>-SNAPSHOT`） | `BuildConfig.LIBRARY_VERSION = "0.9.4"`；`module.publication.gradle.kts` 的 `versionSuffix` |
| Kotlin | `2.4.21` | `gradle/libs.versions.toml` `kotlin` |
| Compose Multiplatform | `1.12.2`（示例/构建）/ 已发布 0.9.4 的 POM 里是 `1.12.0` | `libs.versions.toml`、0.9.4 POM |
| AGP | `9.5.1` | `libs.versions.toml` `agp` |
| compileSdk / targetSdk | `37` | `BuildConfig.COMPILE_SDK = 37` / `TARGET_SDK = 37` |
| minSdk | `24`（`miuix-blur` 单独 `33`） | `BuildConfig.MIN_SDK = 24`；`miuix-blur/build.gradle.kts` `minSdk = 33` |
| JDK | `21` | `BuildConfig.JDK_VERSION = 21` |
| 构建工具 | `37.0.0` | `BuildConfig.BUILD_TOOLS_VERSION` |

### 1.2 Maven Central 上的事实（联网确认）

* `miuix-ui-android` 的 `maven-metadata.xml`：`<latest>0.9.4</latest>`，`lastUpdated 20260920082407`；版本只有 `0.9.0 / 0.9.1 / 0.9.2 / 0.9.3 / 0.9.4-rc01 / 0.9.4`。
* 旧代 `miuix-android`：`<latest>0.8.8</latest>`，版本从 `0.0.1` 一路到 `0.8.8`（0.9.x 起不再更新，改为拆分模块）。
* 已发布模块（groupId 目录实测）：`miuix-core`、`miuix-ui`、`miuix-preference`、`miuix-icons`、`miuix-squircle`、`miuix-shader`、`miuix-blur`、`miuix-nav`、`miuix-shapes`、`miuix-wasm-js`；**`miuix-glass` / `miuix-material` 不在目录里**——0.9.4 的 `miuix-ui-android` 的 `classes.jar` 里 `kmp/glass/` 类数量为 **0**，它们只存在于本地 `reference/miuix` main（`miuix-glass/`、`miuix-material/` 模块）。

### 1.3 版本—约束对照表（全部实测，非推测）

| 版本 | artifact | Kotlin `Metadata mv` | minSdk | minCompileSdk | 依赖的 Kotlin stdlib | 依赖的 Compose | 包结构 |
|---|---|---|---|---|---|---|---|
| 0.4.0 | `miuix-android` | **2.1.0** | 26 | 1 | 2.1.20 | CMP 1.8.0-beta01 | basic / extra / theme / utils / anim / icon / interfaces |
| 0.5.0 | `miuix-android` | **2.2.0** | 26 | 1 | 2.2.0 | CMP 1.8.2 | 同上 |
| **0.5.2** | `miuix-android` | **2.2.0** | **26** | **1** | 2.2.20 | **CMP 1.9.0** | 同上（无 `icon.extended`） |
| 0.6.0 | `miuix-android` | **2.2.0** | 26 | 1 | 2.2.21 | CMP 1.9.3 | + `color` |
| 0.7.0 | `miuix-android` | **2.2.0** | 24 | 1 | 2.2.21 | CMP 1.9.3 | 同上 |
| 0.8.8 | `miuix-android` | **2.3.0** | 23 | **36** | 2.3.20 | CMP 1.10.3 | 同上 + `icon.extended` 进 `miuix-icons` |
| **0.9.4** | `miuix-ui-android` | **2.4.0** | **24** | **37** | 2.4.20 | **CMP 1.12.0**（→ `androidx.compose.foundation:foundation-android:1.12.0`） | ui / preference / menu / popup / window / overlay / icons / shader / blur / squircle / nav |
| 0.9.4 | `miuix-preference-android` | 2.4.0 | 24 | 37 | 2.4.20 | 同上 | `preference` / `menu` / `popup` |
| 0.9.4 | `miuix-blur-android` | 2.4.0 | **33** | — | 2.4.20 | 同上 | `blur`（+ `miuix-shader-android`） |
| 0.9.4 | `miuix-shader-android` | 2.4.0 | 24 | — | 2.4.20 | — | `shader`（`isRuntimeShaderSupported` 等） |
| 0.9.4 | `miuix-icons-android` | 2.4.0 | 24 | 37 | 2.4.20 | 同上 | `icon.extended` |

Compose 侧参照（Google Maven 实测）：

| Compose 版本（BOM） | minSdk | `Metadata mv` | minCompileSdk | minAGP |
|---|---|---|---|---|
| BOM 2024.09.02 → 1.7.2（**本项目现状**） | — | — | — | — |
| BOM 2025.09.00 → **1.9.1**（material3 1.3.2） | 21 | **2.0.0** | **35** | 8.6.0 |
| BOM 2025.10.00 → 1.9.3（material3 1.4.0） | — | — | — | — |
| BOM 2026.02.01 → 1.10.4（material3 1.4.0） | 23 | — | **35** | **8.6.0** |
| BOM 2026.09.00 → **1.12.1**（material3 1.4.0） | 23 | **2.1.0** | **37** | **9.1.0** |

> 注意：**Compose 本身不是 Kotlin 版本瓶颈**（1.12.1 的 metadata 仍只有 2.1.0）；真正的瓶颈是 miuix 自己的 `mv=2.4.0`，以及它连带要求的 `minCompileSdk=37` / `minAGP=9.1.0`。

### 1.4 本项目可用的三组坐标（按阶段；工作区当前已在用档 0 的两行依赖）

```kotlin
// 阶段一（立刻可落地，Kotlin 2.1.20 不动）
implementation("top.yukonga.miuix.kmp:miuix-android:0.5.2")
implementation(platform("androidx.compose:compose-bom:2025.09.00")) // compose 1.9.1 / material3 1.3.2

// 阶段二（推荐终态，与 HyperChanger 同栈）
implementation("top.yukonga.miuix.kmp:miuix-ui-android:0.9.4")
implementation("top.yukonga.miuix.kmp:miuix-preference-android:0.9.4")
implementation("top.yukonga.miuix.kmp:miuix-icons-android:0.9.4")
implementation("top.yukonga.miuix.kmp:miuix-shader-android:0.9.4")   // isRuntimeShaderSupported()
implementation("top.yukonga.miuix.kmp:miuix-squircle-android:0.9.4")  // 可选，圆角更 HyperOS
implementation(platform("androidx.compose:compose-bom:2026.09.00")) // compose 1.12.1 / material3 1.4.0

// 只在 API 33+ 生效的毛玻璃（minSdk 26 需要 overrideLibrary，见 3.5）
implementation("top.yukonga.miuix.kmp:miuix-blur-android:0.9.4")
```

---

## 2. 组件清单（与设置页直接相关的 15 个 + 扩展）

以 **0.9.4** 的包名为准（`miuix-ui` / `miuix-preference`）。旧代（≤0.8.8）的等价物在最后一列说明。

| # | 组件 | import 路径 | 作用 | 设置页里的用法 | 旧代（≤0.8.8）等价 |
|---|---|---|---|---|---|
| 1 | `Card` | `top.yukonga.miuix.kmp.basic.Card` | 圆角卡片容器，`cornerRadius` / `insideMargin` / `colors` | **一卡一组**；单行卡也用它 | 同（`basic.Card`） |
| 2 | `CardDefaults` | `top.yukonga.miuix.kmp.basic.CardDefaults` | 默认圆角 16dp、内边距 0、配色 | 统一设为 `22.5.dp` 复刻 HyperOS | 同 |
| 3 | `SmallTitle` | `top.yukonga.miuix.kmp.basic.SmallTitle` | 组标题（卡外的小字） | 每组卡上方一行 | 同 |
| 4 | `TopAppBar` | `top.yukonga.miuix.kmp.basic.TopAppBar` | 大标题栏（可折叠） | 设置页 `KdKit` 大标题 | 同 |
| 5 | `SmallTopAppBar` | `top.yukonga.miuix.kmp.basic.SmallTopAppBar` | 紧凑标题栏 | OOBE/二级页 | 同 |
| 6 | `MiuixScrollBehavior` | `top.yukonga.miuix.kmp.basic.MiuixScrollBehavior` | 大标题折叠的滚动状态 | `Scaffold` + `TopAppBar` 必备 | 同 |
| 7 | `Scaffold` | `top.yukonga.miuix.kmp.basic.Scaffold` | 页面骨架（`topBar`/`bottomBar`/`floatingToolbar`） | 页面容器；**Overlay 类组件必须被它包住** | 同 |
| 8 | `Button` / `TextButton` / `ButtonDefaults` | `top.yukonga.miuix.kmp.basic.Button` / `.TextButton` / `.ButtonDefaults` | 主/次按钮（`ButtonDefaults.buttonColors()` / `buttonColorsPrimary()` / `textButtonColors()`） | 底部浮动主按钮（推荐配置 / 恢复默认） | 旧代只有 `Button` |
| 9 | `Switch` | `top.yukonga.miuix.kmp.basic.Switch` | 开关本体 | 一般不用它，用第 10 行的 `SwitchPreference` | 同 |
| 10 | `SwitchPreference` | `top.yukonga.miuix.kmp.preference.SwitchPreference` | 标题+摘要+右侧开关的整行 | **38 个功能开关的主力**（替代现有 `FeatureRow`） | `top.yukonga.miuix.kmp.extra.SuperSwitch` |
| 11 | `ArrowPreference` | `top.yukonga.miuix.kmp.preference.ArrowPreference` | 标题+摘要+右箭头的可点行 | 「关于」「诊断」「二级页」入口 | `top.yukonga.miuix.kmp.extra.SuperArrow` |
| 12 | `OverlayDropdownPreference` | `top.yukonga.miuix.kmp.preference.OverlayDropdownPreference` | 行内下拉选择（弹层版） | 主题模式、宿主版本选择 | `top.yukonga.miuix.kmp.extra.SuperDropdown` |
| 13 | `CheckboxPreference` | `top.yukonga.miuix.kmp.preference.CheckboxPreference` | 勾选行 | 「我已阅读并同意」类条款 | `basic.Checkbox` 手拼 |
| 14 | `TextField` | `top.yukonga.miuix.kmp.basic.TextField` | HyperOS 风格输入框（`label` / `useLabelAsPlaceholder` / `cornerRadius`） | 搜索功能、子选项里的字符串键 | 同 |
| 15 | `OverlayDialog` / `WindowDialog` | `top.yukonga.miuix.kmp.overlay.OverlayDialog` / `top.yukonga.miuix.kmp.window.WindowDialog` | 弹窗（页面级 / 窗口级） | 诊断弹窗、关于弹窗、验证码弹窗 | 旧代 `extra.SuperDialog` / `extra.WindowDialog`（0.9 起改名并分 overlay/window 两套） |
| 16 | `NavigationBar` | `top.yukonga.miuix.kmp.basic.NavigationBar` | 底部导航（HyperOS 胶囊样式） | 若设置页要分「功能 / 诊断 / 关于」三 Tab | 同 |
| 17 | `TabRow` | `top.yukonga.miuix.kmp.basic.TabRow` | 顶部 Tab | 页内分段（如「选项 / 信息」） | 同 |
| 18 | `MiuixTheme` / `ThemeController` | `top.yukonga.miuix.kmp.theme.MiuixTheme` / `.ThemeController` | 主题、色板（`lightColorScheme()`/`darkColorScheme()`/Monet） | 包住整个设置页；替换现有 `KdKitTheme` 的配色层 | 同（`theme.MiuixTheme`） |
| 19 | `MiuixIcons` + 扩展图标 | `top.yukonga.miuix.kmp.icon.MiuixIcons`、`top.yukonga.miuix.kmp.icon.extended.*` | 图标集（`ChevronBackward`/`ChevronForward`/`Close`/`Check`/`Search`…） | 返回箭头、勾/叉状态 | 扩展图标仅 0.8.3+ 的 `miuix-icons` 有；0.5.2 只有基础集 |
| 20 | `SuperSwitch` / `SuperArrow` / `SuperDropdown` | `top.yukonga.miuix.kmp.extra.SuperSwitch` 等 | **旧代**的设置行三件套（0.9 起被 `SwitchPreference`/`ArrowPreference`/`OverlayDropdownPreference` 取代） | 阶段一必用 | 仅 ≤0.8.8 |

补充：`miuix-glass`（源码）另有一整套玻璃组件：`GlassSurface`、`GlassTopAppBar`、`GlassNavigationBar`、`GlassDialog`、`GlassBottomSheet`、`GlassIconButton`、`GlassTabRow`、`GlassPopup`、`GlassDropdownPreference`（路径 `top.yukonga.miuix.kmp.glass.*`）；**0.9.4 未发布，暂不可用**。

### 2.1 两代 API 的对应关系（改造时最容易踩的坑）

```
0.4 ~ 0.8.8（单体 miuix-android）
  top.yukonga.miuix.kmp.basic.*    Card / Switch / Checkbox / TextField / TopAppBar / Scaffold / SmallTitle
  top.yukonga.miuix.kmp.extra.*    SuperSwitch / SuperArrow / SuperDropdown / SuperDialog
                                   （0.5.2 实测还有 SuperCheckbox / SuperSpinner / SuperBottomSheet；
                                     0.8.8 另有 SuperRadioButton / SuperListPopup / WindowDialog / WindowBottomSheet / WindowDropdown / WindowListPopup / WindowSpinner）
  top.yukonga.miuix.kmp.theme.*    MiuixTheme
  top.yukonga.miuix.kmp.icon.*     MiuixIcons（基础集）

0.9.x（拆分模块）
  miuix-ui-android        basic / overlay / window / layout / theme / utils / icon
  miuix-preference-android preference / menu / popup   ← SuperSwitch → SwitchPreference 等
  miuix-icons-android      icon.extended                 ← 0.5.2 及以前没有扩展图标
  miuix-blur-android       blur
  miuix-shader-android     shader（isRuntimeShaderSupported）
```

**结论**：如果只做「设置页外观改造」，阶段一（0.5.2）的 `extra.SuperSwitch` / `SuperArrow` 已经够用，且视觉与 0.9 的 `SwitchPreference` 同源（都是 HyperOS 设置行）。

---

## 3. 模糊 / 玻璃能力

### 3.1 有：`miuix-blur`（已发布，minSdk 33）

`miuix-blur` 是独立模块（`miuix-blur-android:0.9.4`，185 KB，`minSdk 33`），基于 `RuntimeShader`（Android 13+）。核心 API 实测存在于 AAR 中：

| 类/函数 | import | 说明 |
|---|---|---|
| `LayerBackdrop` / `rememberLayerBackdrop` / `Modifier.layerBackdrop` | `top.yukonga.miuix.kmp.blur.*` | 先把背景内容录进一层，再在浮层上取样 |
| `Modifier.drawBackdrop(backdrop, shape, effects)` | `top.yukonga.miuix.kmp.blur.drawBackdrop` | 低层管线：`blur(radius)` / `colorControls(...)` / `colorFilter(...)` / `runtimeShaderEffect(...)` |
| `Modifier.textureBlur(backdrop, shape, blurRadius, colors, …)` | `top.yukonga.miuix.kmp.blur.textureBlur` | 一把梭的毛玻璃（半径 0–150dp） |
| `Modifier.progressiveTextureBlur(..., gradient = ProgressiveBlur.Top)` | `top.yukonga.miuix.kmp.blur.progressiveTextureBlur` | 渐变模糊，适合「顶栏/底栏边缘」 |
| `BlurColors` / `BlendColorEntry` / `BlurBlendMode` | `top.yukonga.miuix.kmp.blur.*` | 40+ 混合模式、亮度/对比/饱和度 |
| `isRenderEffectSupported()` / `isRuntimeShaderSupported()` | `top.yukonga.miuix.kmp.material.*`（源码）/ **0.9.4 实为** `top.yukonga.miuix.kmp.shader.*` | 运行时能力探测：API 32+/33+ |

### 3.2 仅源码：`miuix-material`（边缘光/材质定义）

`top.yukonga.miuix.kmp.material`：`EdgeStroke`、`EdgeStrokes`、`GlassEdgeStrokes`、`GlassStyle`/`GlassStyles`、`GlassMaterial`/`GlassMaterials`、`GlassShape`、`GlassShadow`/`GlassShadows`、`GlassDefaults`。
用法（`docs/guide/blur.md` 末尾）：

```kotlin
Modifier
    .drawBackdrop(backdrop, shape = { shape }, effects = { blur(20.dp.toPx()) })
    .edgeStroke(shape = shape, stroke = EdgeStrokes.MiddleLight, alpha = 1f)
```

> 0.9.4 只发布了 `miuix-shader-android`（`RuntimeShader`/`RenderEffect` 封装 + 能力探测，6 KB），`EdgeStroke` 这套还没上 Maven。

### 3.3 仅源码：`miuix-glass`（玻璃面/玻璃组件，minSdk 24 + 需 overrideLibrary）

`top.yukonga.miuix.kmp.glass`：`Modifier.glassPanel` / `Modifier.glass` / `Modifier.glassSurface` / `Modifier.glassShadow`，以及 `GlassSurface`、`GlassTopAppBar`、`GlassNavigationBar`、`GlassDialog`、`GlassBottomSheet`、`GlassIconButton`、`GlassTabRow`。

官方用法（`docs/guide/glass.md`）：

```kotlin
val backdrop = rememberLayerBackdrop()
Box(Modifier.matchParentSize().layerBackdrop(backdrop).background(MiuixTheme.colorScheme.background)) { /* 页面内容 */ }

Box(
    Modifier.glassPanel(
        backdrop = backdrop,
        shape = GlassShape(24.dp),
        style = GlassDefaults.style(isDark),
        material = GlassMaterials.puredThinGlass(isDark),
        stroke = GlassEdgeStrokes.forTheme(isDark),
        shading = false,
    )
)
```

文档同时写明：`miuix-glass` 自身 `minSdk` 24，但依赖 `miuix-blur`（`minSdk 33`），所以 **API < 33 必须加 `tools:overrideLibrary="top.yukonga.miuix.kmp.blur"`，并接受模糊层被跳过**（回退为不透明 `containerColor`）。

### 3.4 0.9.4 时代的替代（面向 minSdk 26）

1. **`io.github.kyant0:backdrop:2.0.0`**（HyperChanger 实际在用）：`rememberLayerBackdrop` / `layerBackdrop` / `Modifier.drawBackdrop` / `effects.vibrancy()` / `effects.blur()` / `effects.lens()` / `Highlight` / `Shadow`。配合 `isRuntimeShaderSupported()` 做 API 分支。HyperChanger 的工具栏、玻璃按钮、玻璃页签全是这一套（`Oobe.kt:67-73`、`MainActivity.kt:14105` `UpdateToolbarButton`、`MainActivity.kt:7492` `SoftGlassHeaderTabs`）。
2. **`Modifier.blur(radius)`**（`androidx.compose.ui.draw.blur`）：API 31+ 有 `RenderEffect`，31 以下自动退化为不模糊。适合「降级也要有层次」的场景。
3. **现有 `ui/Glass.kt` 的自绘渐变**（`GlassBackground` + 玻璃卡）：零依赖、全 API 可用、性能稳，是低端机的最终兜底。项目 `module/UI.md` 已把「不采样壁纸、只画柔和渐变」写进设计决定。

### 3.5 推荐的三档降级策略（minSdk 26）

```kotlin
val shaderReady = remember { isRuntimeShaderSupported() }   // API 33+ / 桌面/iOS 恒 true
when {
    shaderReady -> GlassPanel(backdrop)        // miuix-blur / kyant backdrop：真模糊 + 边缘光
    Build.VERSION.SDK_INT >= 31 -> BlurFallback // Modifier.blur + 半透明色罩
    else -> GradientFallback                     // 现有 GlassBackground 渐变（零成本）
}
```

> 注意 `miuix-blur` 的 AAR `minSdk=33`：若 app `minSdk=26`，manifest 必须
> `<uses-sdk tools:overrideLibrary="top.yukonga.miuix.kmp.blur"/>`，
> 且**所有** blur 调用都要被 `isRuntimeShaderSupported()` 包住，否则 API 26-32 设备上会 `NoClassDefFoundError`/`NoSuchMethodError`。

---

## 4. HyperChanger 的 OOBE 解剖

### 4.1 文件与入口

| 内容 | 路径 / 行号 |
|---|---|
| OOBE 全部实现（707 行） | `reference/HyperChanger/app/src/main/java/btm/m/os4/systemuihook/Oobe.kt` |
| 入口判断与根级切换 | `.../MainActivity.kt:872`（读 `SharedPreferences("oobe")`）、`:1380-1415`（`AnimatedContent(showOobe)` + 模糊交接） |
| 再次进入 OOBE 的按钮 | `.../ModuleSafetyPage.kt:86`（`ArrowPreference("进入 OOBE", onClick = onEnterOobe)`） |
| 设置页壳 `AppPage` / 列表 `AppList` / 分组 `Group` | `MainActivity.kt:14642` / `:15583` / `:5979` |
| 玻璃工具条按钮 `UpdateToolbarButton` | `MainActivity.kt:14105` |
| 状态机 | `Oobe.kt:87` `OobeFlow` |

**入口逻辑**（`MainActivity.kt:872-882`）：

```kotlin
val oobePreferences = remember { context.getSharedPreferences("oobe", Context.MODE_PRIVATE) }
var showOobe by remember {
    mutableStateOf(
        !oobePreferences.getBoolean("completed", false) &&
            !oobePreferences.contains("completed_version"), // 兼容旧版的版本号标记
    )
}
```

**根级切换**（`MainActivity.kt:1380-1415`）：外层 `AnimatedContent(targetState = showOobe)`，两侧各带 `slideInHorizontally/fadeIn/scaleIn`，并在过渡中用 `Modifier.blur(rootBlurRadius.dp)` 把「旧界面」逐渐糊掉（`PostExit` 14dp / `PreEnter` 14dp）。

### 4.2 页面结构与状态

```kotlin
private enum class OobePage { WELCOME, PREPARATION, AGREEMENTS, COMPLETE }
internal enum class LegalPage { AGREEMENT, DISCLAIMER, PRIVACY }
private data class OobeDestination(val page: OobePage, val legalPage: LegalPage? = null)
```

`OobeFlow(serviceConnected, onLanguageChanged, onFinished)` 内的状态（`Oobe.kt:95-118`）：

| 状态 | 类型 | 作用 |
|---|---|---|
| `page` | `rememberSaveable { mutableStateOf(OobePage.WELCOME) }` | 当前页（配置变更后保留） |
| `legalPage` | `LegalPage?` | 覆盖在页面之上的法务文本子页；非空即优先渲染 |
| `agreementsAccepted` | `Boolean` | 协议勾选 |
| `captchaVerified` / `showCaptcha` / `captcha` | `Boolean`/`String` | 6 位动态码（`(100000..999999).random()`，显示在协议正文页，回到列表页输入） |
| `completionVisit` | `Int` | 每次进完成页 +1，用作彩带动画 key |
| `navigatingForward` | `Boolean` | 决定 `AnimatedContent` 的正/反向动画 |
| `predictiveHandoffDestination` | `OobeDestination?` | 预测性返回提交后「不要二次动画」的交接标记 |

导航只有两个函数：

```kotlin
val go: (OobePage) -> Unit = { next ->
    if (next == OobePage.COMPLETE && page != OobePage.COMPLETE) completionVisit++
    navigatingForward = next.ordinal >= page.ordinal
    predictiveHandoffDestination = null
    page = next
}
val navigateBack: () -> Unit = { navigatingForward = false; if (legalPage != null) legalPage = null else go(page.ordinal - 1) }
```

页面渲染是一个 `when`（无导航库、无 Fragment、无 NavHost）：

```kotlin
renderDestination = { dest -> dest.legalPage?.let { LegalDocumentPage(it, captcha) { … } }
    ?: when (dest.page) {
        WELCOME -> WelcomePage { go(PREPARATION) }
        PREPARATION -> PreparationPage(serviceConnected, { go(WELCOME) }, onLanguageChanged) { go(AGREEMENTS) }
        AGREEMENTS -> AgreementsPage(..., next = { go(COMPLETE) })
        COMPLETE -> CompletePage(completionVisit, { go(AGREEMENTS) }, onFinished)
    } }
```

`onFinished`（`MainActivity.kt:1408`）= `oobePreferences.edit().putBoolean("completed", true).apply(); showOobe = false`。

### 4.3 各页的组件用法

| 页 | 壳 | 关键组件 | 行号 |
|---|---|---|---|
| `OobeFrame`（欢迎页专用壳） | `Scaffold(containerColor = background)` | 76dp 固定行放返回箭头（`MiuixIcons.Regular.ChevronBackward` 38dp）；可选 36sp 居中大标题；`weight(1f)` 内容区；`bottom` 参数放主按钮 | `Oobe.kt:290` |
| Welcome | `OobeFrame(backgroundBackdrop = backdrop)` | 3 段 `Spacer(weight .37/.63)` 排版；`Text` 36sp/39sp；一个 **65dp 玻璃圆按钮**：`drawBackdrop + vibrancy + blur + toolbarGlassLens + Shadow`，点击进下一步 | `:308-370` |
| Preparation | `AppPage(compactTopBar = true, floatingToolbar = { OobeButton(...) })` + `AppList` | 4 张 `StatusCard`（标题 + 摘要 + 右侧 ✓ / ? / ✗）+ `LanguageCard`（`Card` 包一个 `OverlayDropdownPreference`）；检测在 `LaunchedEffect + Dispatchers.IO`（`ProcessBuilder("su","-c","id")`），结果决定底部按钮 `enabled` | `:372-449` |
| Agreements | 同上 | `Card { ArrowPreference×3 }`（用户协议/免责声明/隐私政策）+ `Card { ArrowPreference(输入动态验证码) }` + `Checkbox(state = ToggleableState)` 同意行 + `CaptchaDialog` | `:451-507` |
| CaptchaDialog | `WindowDialog(show, onDismissRequest, imeBottomSafetyFraction = .175f)` | `TextField`（`cornerRadius = 999.dp`、数字键盘、只留 6 位）+ 两个 `GlassDialogButton`（确认 `enabled = input == captcha`） | `:514-549` |
| LegalDocumentPage | `AppPage(title, back)` | 正文来自 `assets/legal/zh/*.txt`；末尾一张 `LegalReadingCard` 显示「本次验证码」 | `:551-576` |
| Complete | `AppPage` + 全屏 `CompletionConfetti` | 36sp 文案 + `Canvas` 彩带（54 片、3.8s、带停留/旋转/落点） | `:578-618` / `:620-698` |
| 主按钮 | `OobeButton` → `UpdateToolbarButton(primary = true)` | 58dp 高、胶囊、蓝色 `0xFF0088FF`、玻璃底 + 拖拽回弹 | `:707`、`MainActivity.kt:14105` |

### 4.4 动效与预测性返回

* **页面切换**（`Oobe.kt:232-290`）：前进 = `slideInHorizontally(it/7) + fadeIn(420) + scaleIn(.985)` ↔ `slideOut(-it/3, scale .975)`；后退镜像。时长 460–560ms，`FastOutSlowInEasing`。
* **过渡期的「离场模糊」**：用 `transition.animateFloat`，离场后 `PostExit` 12dp、入场前 `PreEnter` 12dp，其余 0dp。
* **预测性返回**（`Oobe.kt:183-260`）：`PredictiveBackHandler` 收集 `progress`（封顶 0.8），同时把「上一页」渲染成预览：`translationX = -方向 * 宽度 * (1-p)/7`、`scale .975→1`、`alpha p`、`blur 14dp → 4dp`；松手后 240ms 补齐进度、交接时把 `EnterTransition.None togetherWith ExitTransition.None` 交给 `AnimatedContent`，避免二次动画。

### 4.5 可直接照抄的「OOBE/设置页布局套路」10 条

1. **一次性标记 + 根级整屏切换**：`SharedPreferences("oobe").completed` + 外层 `AnimatedContent(showOobe)`，不要新开 Activity；卸载/升级判断与 OOBE 生命周期解耦（`MainActivity.kt:872, 1380`）。
2. **枚举状态机 + 单一 `go()/back()`**：`enum class OobePage` + `rememberSaveable`，页面用 `when` 渲染；不要引入 NavHost（HyperChanger 451 个 Kotlin 文件也不用导航库，见 `Oobe.kt:95-140`）。
3. **统一页壳**：`Scaffold(containerColor = 深/浅底)` + 固定 76dp 顶行（返回 + 可选标题）+ `weight(1f)` 内容 + 底部主按钮；`windowInsetsPadding(WindowInsets.safeDrawing)`（`Oobe.kt:290-306`）。
4. **「准备/自检」页 = 状态卡清单**：每项一张 `Card(cornerRadius = 22.5.dp)`，标题 `body1 + Bold`、摘要 `body2 + onSurfaceVariantSummary`，右侧三态图标（蓝 ✓ / 灰 ? / 红 ✗），检测放 `LaunchedEffect + withContext(IO)`（`Oobe.kt:372-431`）。
5. **「协议」页 = 一张卡三行箭头 + 单独验证卡 + 勾选行**：勾选行用 `Checkbox(ToggleableState)` + 手写条款文案，`enabled` 由验证码状态决定；主按钮 `enabled = accepted`（`Oobe.kt:451-500`）。
6. **验证码/输入类弹窗**：`WindowDialog` + `TextField(cornerRadius = 999.dp, keyboardType = Number, useLabelAsPlaceholder = true)` + 两个等宽 `GlassDialogButton`（`Oobe.kt:514-548`）。
7. **设置页统一骨架 `AppPage`**：`Scaffold` + `TopAppBar(title, largeTitle, scrollBehavior)` + `MiuixScrollBehavior` + `floatingToolbar`；大标题折叠时另叠一层 52dp 居中标题，避免再加一行高度（`MainActivity.kt:14642-14780`）。
8. **列表统一为 `AppList`**：`LazyColumn` + `contentPadding(16dp, top+4, 16dp, bottom+112)` + `spacedBy(12.dp)`；`nestedScroll(scroll.nestedScrollConnection)` 让滚动驱动大标题折叠（`MainActivity.kt:15583`）。
9. **分组 = `SmallTitle` + `Card(22.5dp)` + 偏好行（默认**不画分隔线**，靠行内 `insideMargin` 留白；要 hairline 时才加 `basic.Divider` 并左右内缩 16dp）**；组级批量操作放在组头（HyperChanger 的 `Group`，`MainActivity.kt:5979`；对应本项目现有 `GroupHeader` 的「全开/全关」）。
10. **玻璃动效统一走两个工具函数**：`UpdateToolbarButton`（胶囊主按钮）与 `SoftGlassHeaderTabs`（分段页签）；都是 `drawBackdrop + vibrancy + blur + lens/highlight + DampedDragAnimation`，能力不足时 `Modifier.background(surface)` 兜底（`MainActivity.kt:14105, 7488-7545`）。

---

## 5. 兼容性风险与版本矩阵

### 5.1 硬约束（实测证据，不是推测）

**证据 A：Kotlin 2.1.20 编译器读不了 0.8.8 / 0.9.4 的类**

用本机 Gradle 缓存里的 `kotlin-compiler-embeddable-2.1.20` 直接对 `miuix-ui-android-0.9.4/classes.jar` 做最小编译（`T.kt` 只引用一个 miuix 符号）：

```
error: incompatible classes were found in dependencies. Remove them from the classpath or use '-Xskip-metadata-version-check' to suppress errors
.../top.yukonga.miuix.kmp_miuix-ui.kotlin_module: error: module was compiled with an incompatible version of Kotlin.
  The binary version of its metadata is 2.4.0, expected version is 2.1.0.
T.kt:2:8: error: class 'top.yukonga.miuix.kmp.utils.PressFeedbackType' was compiled with an incompatible version of Kotlin.
  The actual metadata version is 2.4.0, but the compiler version 2.1.0 can read versions up to 2.2.0.
```

同一编译器对 `miuix-android:0.8.8/classes.jar`（`mv=2.3.0`）给出同型报错：

```
.../META-INF/miuix.kotlin_module: error: module was compiled with an incompatible version of Kotlin.
  The binary version of its metadata is 2.3.0, expected version is 2.1.0.
T.kt:2:8: error: class 'top.yukonga.miuix.kmp.utils.PressFeedbackType' was compiled with an incompatible version of Kotlin.
  The actual metadata version is 2.3.0, but the compiler version 2.1.0 can read versions up to 2.2.0.
```

而 `0.5.2 / 0.6.0 / 0.7.0`（`mv=2.2.0`）**通过前置解析**（只剩一个与 Metadata 无关的 IR backend 异常，原因是这条临时 CLI classpath 缺构件，不是版本兼容问题）。
→ **规则**：Kotlin N 能读 `mv ≤ N+1`；所以

| 目标 miuix | 最低 Kotlin |
|---|---|
| 0.4.0（mv 2.1.0） | 2.1.x 即可 |
| 0.5.x / 0.6.x / 0.7.x（mv 2.2.0） | **2.1.20 可用（上限 2.2.0）** |
| 0.8.8（mv 2.3.0） | ≥ 2.2.x |
| 0.9.4（mv 2.4.0） | **≥ 2.3.x**（HyperChanger 用 Kotlin 2.3.21 跑 0.9.4，正好卡在上限） |

**证据 B：AGP / compileSdk 的硬门槛**

| 依赖 | `minCompileSdk` | `minAndroidGradlePluginVersion` |
|---|---|---|
| `miuix-ui-android:0.9.4` / `miuix-preference-android:0.9.4` | **37** | 1.0.0 |
| `miuix-android:0.8.8` | **36** | 1.0.0 |
| `miuix-android:0.5.2` | 1 | 1.0.0 |
| `androidx.compose.foundation:foundation-android:1.12.1`（BOM 2026.09.00） | **37** | **9.1.0** |
| `androidx.compose.foundation:foundation-android:1.9.1`（BOM 2025.09.00） | 35 | 8.6.0 |

→ 用 0.9.4 = 必须 **compileSdk ≥ 37 且 AGP ≥ 9.1.0**（当前 AGP 8.13.2 会在依赖检查阶段直接报错）。

**证据 C：minSdk**

* 0.9.4 ui/preference/icons `minSdk 24` ≤ 本项目 26 ✅；`miuix-blur` **33** > 26 ❌（需 `tools:overrideLibrary` + 运行时 gate）。
* 0.5.2 `minSdk 26` = 本项目 26 ✅（无 overrideLibrary 需求）。

**证据 D：Kotlin stdlib / Compose 冲突**

* 0.9.4 依赖 `kotlin-stdlib 2.4.20`、`androidx.compose.foundation 1.12.0` → 项目 BOM 2024.09.02（compose 1.7.2）会被 Gradle 抬到 1.12.x，同时带上 stdlib 2.4.20（与 Kotlin 2.1.20 编译器不一致，需显式对齐）。
* 0.5.2 依赖 `kotlin-stdlib 2.2.20`、`foundation 1.9.0` → 只抬到 compose 1.9.x，风险最小。

### 5.2 版本矩阵（三档，全部可执行）

| | **档 0（最小改动）** | **档 1（中间档）** | **档 2（推荐终态，与 HyperChanger 同栈）** |
|---|---|---|---|
| Kotlin | **2.1.20（不变）** | 2.2.20 | **2.3.21**（或 2.4.21） |
| KGP / compose 插件 | 2.1.20（不变） | 2.2.20 | 2.3.21 |
| AGP | **8.13.2（不变）** | 8.13.2（不变） | **9.2.1** |
| Gradle | **8.14.5（不变）** | 8.14.5 | **9.6.1** |
| JDK | 17（不变） | 17 | 21（AGP 9 建议） |
| compileSdk / targetSdk | **36 / 36（不变）** | 36 / 36 | **37 / 37** |
| Compose BOM | **2025.09.00**（compose 1.9.1 / material3 1.3.2） | 2026.02.01（compose 1.10.4） | **2026.09.00**（compose 1.12.1 / material3 1.4.0） |
| miuix | **`miuix-android:0.5.2`**（mono，`extra.*`） | `miuix-android:0.8.8`（mono + `miuix-icons-android:0.8.8`） | **`miuix-ui-android:0.9.4` + `miuix-preference-android:0.9.4` + `miuix-icons-android:0.9.4`**（+ `shader`，blur 可选） |
| 玻璃/模糊 | 自绘渐变 + `Modifier.blur`(31+) | 同左 | `miuix-blur`(33+) / kyant backdrop；`miuix-glass` 需自建源码 |
| 组件形态 | `extra.SuperSwitch/SuperArrow/SuperDropdown` | 同左 + 扩展图标 | `preference.SwitchPreference/ArrowPreference/OverlayDropdownPreference` |
| 改动面 | `app/build.gradle.kts` 两行 + 设置页 UI 文件 | 同左 + Kotlin 2.2 | 全量（Kotlin/AGP/Gradle/JDK/compileSdk + 设置页重写） |
| 主要风险 | 无 Kotlin 风险；API 略旧（无 0.9 的新玻璃/分模块） | 需验证 compose 1.10.4 与 Kotlin 2.2 的组合 | AGP 9 迁移成本（Kotlin 内置、DSL 变更）、compileSdk 37、Xposed 打包规则 |
| 适用时机 | **现在就做**（先落地视觉） | 想拿扩展图标/0.8 组件时 | 与 HyperChanger 对齐、要 0.9 组件与后续 glass |

> 档 0 的坐标与约束已逐项核对（`miuix 0.5.2`: mv 2.2.0 / minSdk 26 / minCompileSdk 1；`compose 1.9.1`: minCompileSdk 35 / minAGP 8.6.0）→ **在现有 AGP 8.13.2 + compileSdk 36 + Kotlin 2.1.20 下应当可以直接编译**（仍需一次真机 `assembleDebug` 验证）。

### 5.3 各档要改的文件（逐条）

**档 0（只改 1 个构建文件 + UI）**
```
module/app/build.gradle.kts
  dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.09.00"))   // 原 2024.09.02
    implementation("top.yukonga.miuix.kmp:miuix-android:0.5.2")
  }
  // 其余（AGP/Kotlin/compileSdk/minSdk/JDK）全部不动
```

**档 1（新增 Kotlin 升级）**
```
module/build.gradle.kts        kotlin("android") 2.1.20 → 2.2.20；compose 插件同步
module/app/build.gradle.kts    BOM 2026.02.01；miuix-android:0.8.8 + miuix-icons-android:0.8.8
```

**档 2（对齐 HyperChanger）**
```
module/build.gradle.kts        com.android.application 8.13.2 → 9.2.1
                              删除 org.jetbrains.kotlin.android（AGP 9 内置 Kotlin）
                              org.jetbrains.kotlin.plugin.compose 2.1.20 → 2.3.21
module/gradle/wrapper/…        8.14.5 → 9.6.1
module/app/build.gradle.kts    compileSdk/targetSdk 36 → 37
                              JDK 17 → 21（compileOptions / jvmTarget）
                              BOM 2026.09.00；miuix ui/preference/icons/shader(+blur)
                              packaging：若启用 blur，`tools:overrideLibrary`
```

**不要碰**：`minSdk 26` 可以保留（0.9.4 的 ui/preference 是 24）。`module/app/src/main/AndroidManifest.xml` 只在启用 blur 时加 `tools:overrideLibrary`。

### 5.4 其它风险清单

| 风险 | 影响 | 处理 |
|---|---|---|
| `packaging { resources.excludes += setOf("META-INF/*", "META-INF/**") }`（现有配置） | 会剥掉所有 `META-INF` 资源；miuix 自身不依赖这些，但若以后接 `kotlinx-serialization`/ServiceLoader 类库会踩坑 | 保持现状可，新增库时逐项核对 |
| Xposed 模块包体 | `miuix-ui` 1.9 MB + `preference` 0.25 MB + `icons` 1.88 MB + `blur` 0.19 MB（未 shrink） | `isMinifyEnabled = false` 时 APK 会长约 2–4 MB；可只引 ui+preference，不引 icons |
| `WindowInsets` / 刘海 | miuix `Scaffold` 自带 insets 处理，但项目 `enableEdgeToEdge()` + 自绘背景需复查 | 用 `windowInsetsPadding(WindowInsets.safeDrawing)`（HyperChanger OobeFrame 同款） |
| Compose 1.9+ 的 `Modifier.blur` 行为 | API < 31 无模糊 | 见 3.5 三档降级 |
| AGP 9 迁移 | Kotlin 内置、`com.android.application` 不再搭配 `kotlin-android` 插件、DSL/属性变更 | 参照 HyperChanger `app/build.gradle.kts`（只有 `com.android.application` + `org.jetbrains.kotlin.plugin.compose` 两个插件） |
| `-Xskip-metadata-version-check` | 能让 2.1.20 编过 0.9.4，但 `@Composable` 签名可能被错误反序列化 | **不要用**；走档 0 或档 2 |
| 版本漂移 | 本地 main 已包含 glass/material 源码（版本号仍是 0.9.4，非 release 构建产出 `0.9.4-<gitshort>-SNAPSHOT`，未上 Maven） | 锁定版本号，不用 `+`/SNAPSHOT；升级前跑一遍 `assembleDebug` + 真机 |

---

## 6. 三个可直接落地的设置页布局草案

> 下面代码按**档 2（0.9.4）**写；括号里标注档 0/1 的等价写法（`extra.SuperSwitch` / `extra.SuperArrow` / `extra.SuperDropdown`）。
> 落点建议：新增 `module/app/src/main/java/dev/xalor/kdkit/ui/miuix/`（**本次调研不创建**，留给实施者）。
> 现有 `MainActivity.kt` 的 `SettingsScreen`/`FeatureCard`/`FeatureRow`/`OptionsSection` 保持数据与业务调用不变，只换「壳 + 行」。

### 草案 A（P0，最小改造）：miuix 分组卡版设置页

**目标**：把现有「M3 + 自绘 GlassCard」的分组卡换成 HyperOS 原生的 `Card + SwitchPreference`，视觉一步到位，逻辑零改动。

**结构**：

```
MiuixTheme(darkColorScheme()/lightColorScheme())
└ Scaffold(topBar = TopAppBar("KdKit", largeTitle, scrollBehavior))
  └ LazyColumn(16dp 边距, 12dp 间距)
    ├ StatusCard（配置通道健康 → 点开诊断弹窗）
    ├ TextField（搜索：标题/说明/标识）
    ├ for (g in Group.values()) {
    │    SmallTitle(g.label)
    │    Card(cornerRadius = 22.5.dp, insideMargin = PaddingValues(0.dp)) {
    │        features.forEach { f ->
    │            SwitchPreference(title = copy.label, summary = copy.blurb,
    │                             checked = KdConfig.isOn(f.id, f.defaultOn),
    │                             onCheckedChange = { KdConfig.setApp(ctx, f.id, it); version++ })
    │            // 不加分隔线：miuix 的偏好行走自己的 insideMargin，HyperChanger 的 Group 也不画线
    │            // 需要一条 hairline 时用 top.yukonga.miuix.kmp.basic.Divider，左右各留 16.dp
    │        }
    │    }
    │  }
    ├ BulkActions（推荐配置 / 恢复默认）
    └ FooterNote
```

**关键代码**（新增文件 `ui/miuix/SettingsCards.kt`；⚠️ 工作区当前是 `miuix-android:0.5.2`，落地时把下面的 `SwitchPreference` 换成 `extra.SuperSwitch` 即可，其余结构不变）：

```kotlin
import top.yukonga.miuix.kmp.basic.Card
import top.yukonga.miuix.kmp.basic.SmallTitle
import top.yukonga.miuix.kmp.preference.SwitchPreference
import top.yukonga.miuix.kmp.theme.MiuixTheme

@Composable
fun KdGroupCard(
    title: String,
    features: List<BaseFeature>,
    version: Int,
    onChange: () -> Unit,
) {
    val ctx = LocalContext.current
    Column(Modifier.fillMaxWidth()) {
        SmallTitle(title, insideMargin = PaddingValues(start = 12.dp, top = 4.dp, end = 12.dp, bottom = 4.dp))
        Card(Modifier.fillMaxWidth(), cornerRadius = 22.5.dp, insideMargin = PaddingValues(0.dp)) {
            features.forEach { f ->
                val copy = SettingsCopy.of(f.id)
                val checked = remember(f.id, version) { KdConfig.isOn(f.id, f.defaultOn) }
                SwitchPreference(
                    title = copy?.label ?: f.title,
                    summary = copy?.blurb ?: f.summary,
                    checked = checked,
                    onCheckedChange = { v -> KdConfig.setApp(ctx, f.id, v); onChange() },
                )
            }
        }
    }
}
```

档 0/1 等价写法：

```kotlin
// ≤0.8.8
import top.yukonga.miuix.kmp.extra.SuperSwitch
SuperSwitch(checked = checked, onCheckedChange = { … }, title = copy.label, summary = copy.blurb)
```

**成本**：改 1 个文件（`SettingsScreen` 的卡片层）+ 新增 1 个组件文件；`OptionEditors.kt` 里的 `Switch`/`OutlinedTextField` 换成 `Switch`(miuix)/`TextField`(miuix) 即可。
**风险**：低。行高会从现有 ~64dp 变为 miuix 默认（约 56–60dp），首屏能看到的行数增加，符合 `module/UI.md` 的目标。

### 草案 B（P1，新增）：OOBE 式「模块就绪」流程

**目标**：首次打开/点「检查环境」进入 4 步，替用户完成「装模块 → 激活 → 读通道 → 同意条款」，对齐 HyperChanger 的 OOBE 手感。

**结构**（照抄 HyperChanger 的 `OobeFrame` + 状态卡）：

```
enum class KdOobeStep { WELCOME, CHECKUP, TERMS, DONE }
OobeFlow(health, hostVersion, onFinish)
├ WELCOME   : 大标题 + 说明 + 65dp 主按钮（glass 可选）
├ CHECKUP   : StatusCard×4
│             1) Xposed 激活（FeatureRegistry/HookCore 是否能读到宿主）
│             2) 配置通道（复用 MainActivity 的 channelHealth()：文件存在 + mode=644）
│             3) 宿主版本（HostVersion.BASELINE_VERSION_NAME vs 实机）
│             4) 存储/通知权限（可选）
│             + Card { OverlayDropdownPreference("主题模式", …) }
├ TERMS     : Card { ArrowPreference×3 } + Checkbox 同意行 + 主按钮 enabled = accepted
└ DONE      : 完成文案 + 「开始使用」→ prefs.putBoolean("kdkit_oobe", true)
```

**关键代码**：

```kotlin
@Composable
fun KdOobeFrame(
    back: (() -> Unit)? = null,
    bottom: (@Composable () -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val bg = MiuixTheme.colorScheme.background
    Scaffold(containerColor = bg) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding)
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = 28.dp),
        ) {
            Row(Modifier.fillMaxWidth().height(76.dp), verticalAlignment = Alignment.CenterVertically) {
                if (back != null) {
                    Image(MiuixIcons.Regular.ChevronBackward, null,
                        Modifier.size(38.dp).clickable(onClick = back),
                        colorFilter = ColorFilter.tint(MiuixTheme.colorScheme.onBackground))
                }
            }
            Column(Modifier.weight(1f).fillMaxWidth(), content = content)
            bottom?.let { Box(Modifier.fillMaxWidth().padding(bottom = 18.dp)) { it() } }
        }
    }
}

@Composable
fun KdStatusCard(title: String, summary: String?, status: Int) {   // 1=OK 0=未知 -1=失败
    Card(Modifier.fillMaxWidth(), cornerRadius = 22.5.dp,
         insideMargin = if (summary == null) PaddingValues(0.dp) else PaddingValues(18.dp)) {
        Row(Modifier.fillMaxWidth().then(if (summary == null) Modifier.height(64.dp) else Modifier)
                .padding(horizontal = 18.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MiuixTheme.textStyles.body1, fontWeight = FontWeight.Bold)
                summary?.let {
                    Text(it, style = MiuixTheme.textStyles.body2,
                         color = MiuixTheme.colorScheme.onSurfaceVariantSummary,
                         modifier = Modifier.padding(top = 3.dp))
                }
            }
            when (status) {
                1 -> Image(MiuixIcons.Regular.Check, null, Modifier.size(26.dp),
                           colorFilter = ColorFilter.tint(Color(0xFF0088FF)))
                -1 -> Image(MiuixIcons.Regular.Close, null, Modifier.size(26.dp),
                            colorFilter = ColorFilter.tint(Color(0xFFE53935)))
                else -> Text("?", color = MiuixTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
```

**成本**：新增 ~300 行 + 1 个 `SharedPreferences` 标记；不动现有设置页。
**风险**：低。注意 `channelHealth()` 目前是 `MainActivity` 的 `private fun`，要提到 `internal` 或搬到 `util/`。

### 草案 C（P2，外观升级）：大标题 + 玻璃工具条 + 浮动主按钮

**目标**：把设置页做成 HyperChanger 的 `AppPage` 观感：折叠大标题、滚动渐显的模糊顶栏、底部浮动工具条（推荐配置/恢复默认/关于）。

**结构**：

```
Scaffold(
  containerColor = Color.Transparent,
  floatingToolbar = { Row { Button("推荐配置"); TextButton("恢复默认") } },
  floatingToolbarPosition = ToolbarPosition.BottomCenter,
  topBar = {
    TopAppBar(title = "", largeTitle = "KdKit", scrollBehavior = scroll,
              navigationIcon = { GlassBack(...) }, actions = { 主题/玻璃/关于 })
    // 折叠态另叠 52dp 居中标题（抄 AppPage 的做法）
  }
) { padding ->
  Box(Modifier.fillMaxSize().layerBackdrop(backdrop)) { LazyColumn(...) }
}
// 顶栏材质：collapsedFraction = scroll.state.collapsedFraction
//   API 33+ → progressiveTextureBlur(backdrop, ProgressiveBlur.Top, blurRadius = 20f)
//   API 31+ → Modifier.blur(12.dp) + surface.copy(alpha)
//   <31     → 纯 surface 渐变
```

**关键代码**（顶栏材质 + 浮动工具条）：

```kotlin
val scroll = MiuixScrollBehavior()
val collapsed = scroll.state.collapsedFraction.coerceIn(0f, 1f)
val backdrop = rememberLayerBackdrop()
val shaderReady = remember { isRuntimeShaderSupported() }

Scaffold(
    containerColor = Color.Transparent,
    floatingToolbar = {
        Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = applyRecommended, modifier = Modifier.weight(1f)) { Text("推荐配置") }
            TextButton("恢复默认", onClick = resetAll, modifier = Modifier.weight(1f))   // miuix 的 TextButton 走 textButtonColors
        }
    },
    topBar = {
        Box(Modifier.fillMaxWidth()) {
            TopAppBar(
                title = "KdKit",
                largeTitle = "KdKit",
                scrollBehavior = scroll,
                color = Color.Transparent,
                navigationIcon = { /* 玻璃返回 */ },
                actions = { /* 主题 / 玻璃 / 关于 */ },
            )
            // 折叠后叠一层居中标题，避免多占一行高度（HyperChanger AppPage 同款）
            Box(Modifier.windowInsetsPadding(WindowInsets.statusBars).height(52.dp).fillMaxWidth()
                    .graphicsLayer { alpha = collapsed }
                    .padding(horizontal = 64.dp), contentAlignment = Alignment.Center) {
                Text("KdKit", style = MiuixTheme.textStyles.title3, maxLines = 1)
            }
        }
    },
) { padding ->
    LazyColumn(
        Modifier.fillMaxSize()
            .nestedScroll(scroll.nestedScrollConnection)
            .then(if (shaderReady) Modifier.layerBackdrop(backdrop) else Modifier)
            .padding(padding),
        contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 112.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) { /* 同草案 A 的分组卡 */ }
}
```

顶栏材质三档（照抄 HyperChanger 的 `ProgressiveTopBarMaterial` 思路，`MainActivity.kt:15244`）：

```kotlin
@Composable
fun KdTopBarMaterial(backdrop: LayerBackdrop, progress: Float, content: @Composable BoxScope.() -> Unit) {
    val shaderReady = remember { isRuntimeShaderSupported() }   // API 33+
    Box(Modifier.fillMaxWidth()) {
        if (progress > 0f) {
            val surface = MiuixTheme.colorScheme.surface
            val material = when {
                shaderReady -> Modifier.progressiveTextureBlur(
                    backdrop = backdrop,
                    shape = RectangleShape,
                    blurRadius = 20f,
                    gradient = ProgressiveBlur.Top,
                )
                Build.VERSION.SDK_INT >= 31 -> Modifier.blur(12.dp).background(surface.copy(alpha = .78f))
                else -> Modifier.background(surface)
            }
            Box(Modifier.matchParentSize().graphicsLayer { alpha = progress }.then(material))
        }
        content()
    }
}
```

**成本**：中（顶栏/滚动/insets 需要调；`floatingToolbar` 需要 miuix `Scaffold` 的 `ToolbarPosition`）。
**风险**：滚动 + 逐帧模糊在中低端机可能掉帧；`module/UI.md` 已否决「采样壁纸」，此处只模糊**自绘背景**，风险可控。建议加一个「液态玻璃」开关（项目已有 `UiPrefs.glass`），关掉直接走纯色。

---

## 7. 落地顺序与验收

1. **第 0 步（半天，已由并发改动完成）**：`module/app/build.gradle.kts` 已含 BOM 2025.09.00 + `miuix-android:0.5.2`；接着只需跑 `./gradlew :app:assembleDebug`，确认 miuix 0.5.2 与本项目 Kotlin 2.1.20 能一起编过（重点看是否只剩 compose 1.9.1 的解析告警）。
2. **第 1 步（1–2 天）**：草案 A（`KdGroupCard` + `SwitchPreference`/`SuperSwitch`），保留搜索/批量/诊断/关于；跑 `SettingsCopyTest` 确保文案契约不变。
3. **第 2 步（1 天）**：草案 B（OOBE 式自检），复用 `channelHealth()`，`SharedPreferences("kdkit_oobe").completed` 控制只显示一次；提供「设置 → 关于 → 重看引导」入口。
4. **第 3 步（按需）**：草案 C（大标题 + 玻璃工具条），先用 `UiPrefs.glass` 开关兜底；在 API 26 / 31 / 33 三档设备各截一次图做回归。
5. **第 4 步（可选）**：整体升档 2（Kotlin 2.3.21 / AGP 9.2.1 / compileSdk 37 / miuix 0.9.4），与 HyperChanger 保持同一套栈，方便对照其 25 个 `AppPage` 页面。

验收清单：

* [ ] `./gradlew :app:assembleDebug` 通过（档 0 与档 2 各一次）
* [ ] `SettingsCopyTest` / `CaptureSettingsTest` 全绿（分组与文案契约没动）
* [ ] API 26 设备：无 blur 相关 `NoClassDefFoundError`（若引入 miuix-blur，必须 gate）
* [ ] API 33+ 设备：玻璃/模糊正常，滚动 ≥50fps（`Settings` 打开 GPU 渲染条）
* [ ] 深色/浅色两套 `MiuixTheme` 配色下，`onSurfaceVariantSummary` 与分隔线对比度合格
* [ ] 首屏（1080×2400）能看到：大标题 + 状态行 + 搜索 + 「去广告」整组（与 `module/UI.md` 的目标对齐）

---

## 8. 证据索引（可复现）

**Maven / AAR 取证**

```bash
# 版本与发布时间
curl -s https://repo1.maven.org/maven2/top/yukonga/miuix/kmp/miuix-ui-android/maven-metadata.xml
curl -s https://repo1.maven.org/maven2/top/yukonga/miuix/kmp/miuix-android/maven-metadata.xml
# 依赖（Kotlin stdlib / Compose 版本）
curl -s https://repo1.maven.org/maven2/top/yukonga/miuix/kmp/miuix-ui-android/0.9.4/miuix-ui-android-0.9.4.pom
curl -s https://repo1.maven.org/maven2/top/yukonga/miuix/kmp/miuix-android/0.5.2/miuix-android-0.5.2.pom
# AAR 内 minSdk 与 minCompileSdk
unzip -p miuix-ui-android-0.9.4.aar AndroidManifest.xml
unzip -p miuix-ui-android-0.9.4.aar META-INF/com/android/build/gradle/aar-metadata.properties
# Kotlin metadata 版本（关键证据）
unzip -o -q miuix-ui-android-0.9.4.aar classes.jar && unzip -o -q classes.jar 'top/yukonga/miuix/kmp/basic/CardKt.class'
javap -v top/yukonga/miuix/kmp/basic/CardKt.class | grep -A3 'kotlin.Metadata'
# Compose BOM → 版本
curl -s https://dl.google.com/dl/android/maven2/androidx/compose/compose-bom/2026.09.00/compose-bom-2026.09.00.pom
curl -s https://dl.google.com/dl/android/maven2/androidx/compose/compose-bom/2025.09.00/compose-bom-2025.09.00.pom
```

**编译器兼容性实测**（Kotlin 2.1.20 直接编一个只引用 miuix 符号的 `T.kt`）

```bash
java -cp kotlin-compiler-embeddable-2.1.20.jar:kotlin-stdlib-2.1.20.jar:kotlinx-coroutines-core-jvm-1.9.0.jar:trove4j.jar \
     org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -nowarn \
     -classpath miuix-ui-android-0.9.4/classes.jar -d out T.kt
# → metadata is 2.4.0, but the compiler version 2.1.0 can read versions up to 2.2.0
```

**源码行号**

* `reference/miuix/gradle/libs.versions.toml`（Kotlin 2.4.21 / CMP 1.12.2 / AGP 9.5.1）
* `reference/miuix/build-logic/src/main/kotlin/BuildConfig.kt`（LIBRARY_VERSION 0.9.4 / COMPILE_SDK 37 / MIN_SDK 24 / JDK 21）
* `reference/miuix/miuix-blur/build.gradle.kts`（`minSdk = 33`）
* `reference/miuix/docs/guide/blur.md`、`docs/guide/glass.md`、`docs/guide/material.md`
* `reference/miuix/docs/components/basic/*.md`、`docs/components/extended/*.md`（每个组件的 import 与参数表）
* `reference/HyperChanger/app/src/main/java/btm/m/os4/systemuihook/Oobe.kt`（87 / 183 / 232 / 290 / 308 / 372 / 398 / 451 / 514 / 551 / 578 / 620 / 707）
* `reference/HyperChanger/app/src/main/java/btm/m/os4/systemuihook/MainActivity.kt`（872 / 1380 / 5979 / 7488 / 14105 / 14642 / 15244 / 15392 / 15583）
* `reference/HyperChanger/app/src/main/java/btm/m/os4/systemuihook/AppInterfaceComponents.kt:238`（`InterfaceArrowPreference`）
* `reference/HyperChanger/app/build.gradle.kts`（miuix 0.9.4 坐标、AGP 9.2.1、compileSdk 37、minSdk 35、Kotlin 2.3.21、Compose 1.11.0/1.12.0）
* 本项目：`module/app/build.gradle.kts`（AGP 8.13.2 / Kotlin 2.1.20 / compileSdk 36 / minSdk 26 / BOM 2024.09.02）、`module/UI.md`（分组与首屏目标）、`module/app/src/main/java/dev/xalor/kdkit/ui/{MainActivity,Glass,OptionEditors,SettingsCopy}.kt`

---

## 9. 参考：HyperChanger 的页面清单（可对照抄结构）

`AppPage(...)` 被 25 个文件引用（`grep -rln "AppPage("`），典型页面包括 `ModuleSafetyPage.kt`（开关组 + `SoftGlassHeaderTabs` 分段）、`EnvironmentDetectionPage.kt`（环境自检）、`SettingsEntryAppearancePage.kt`（外观）、`ModuleLogsPage.kt`（日志/导出）、`privacy/PrivacyGuardPage.kt`、`PortalPage.kt` 等。它们统一是：

```
AppPage(title, back, header = {…}, floatingToolbar = {…}) { padding, scroll ->
    AppList(padding, scroll) {
        item { Group("组名") { SwitchPreference…; ArrowPreference…; OverlayDropdownPreference… } }
        item { Group("另一组") { … } }
    }
}
```

其中 `Group` = `SmallTitle` + `Card(cornerRadius = 22.5.dp, insideMargin = 0)`（`MainActivity.kt:5979`），与草案 A 完全一致 —— 也就是说**草案 A 的形状就是 HyperChanger 的真实设置页形状**，不需要再发明。
