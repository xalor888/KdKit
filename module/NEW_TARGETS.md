# 新功能钩子目标核实（2026-10-25）

目标 APK：`com.kuaiduizuoye.scan` 7.7.2 / 1811（`com.kuaiduizuoye.scan-7.7.2-1811-168194.apk`）
解包目录：`work/apktool_out/`（`smali` + `smali_classes2..7`，7 个 dex 根）
校验脚本：`kit/scripts/check_hook_targets.py`（只校验"类是否存在 + 方法名是否存在"，参数类型判 OK 时不参与比对）

**脚本认的格式（读源码确认）**

```python
CALL_RE = re.compile(r'Xp\.(hook|hookAll|clazzOrNull)\(\s*"([^"]+)"\s*(?:,\s*"([^"]+)")?')
```

- 第 1 个字符串参数 = 类名（`.a.b.C` 形式，内部类用 `$` 的**点号**写法，如 `a.b.C$D`）
- 第 2 个字符串参数 = 方法名
- 后面的参数类型只影响 `clazzOrNull` 的解析，**不参与状态判定**
- 类找不到且在 `android|java|javax|dalvik|libcore.` 前缀下 → `OK(platform)`；找不到否则 `MISSING-CLASS`
- 类找到但没写方法名 → `OK(load)`；写了方法名且 `.method` 里存在 → `OK`

所以只要"类名 + 方法名"真的存在，下面每条都能被判 **OK**。

---

## 结论摘要

| # | 候选功能 | 结论 | 类.方法 | 优先级 |
|---|---|---|---|---|
| 1 | 强制更新闸门 | **确认** | `com.kuaiduizuoye.scan.web.actions.HMSCheckUpdateWebAction.onAction`（华为 SDK，弱）<br>`ei.y.L()`（宿主真正闸门，强）<br>`xl.z2.k(CheckAppUpdate)`（判定核心，强） | 高 |
| 2 | PDF/打印去水印 | **部分确认**（机制确认，钩点非本地绘制） | `cu.l.m0()Z`（`clearWatermark` getter，宿主/共用层）<br>`cu.l` 构造器内 `p13 → 字段 r`<br>`cu.p.l(List,boolean,boolean)` | 中 |
| 3 | H5 桥：下载媒体 | **确认** | `com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction.onAction` | 高 |
| 4 | H5 桥：拿用户信息 | **确认** | `com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction.onAction` | 高 |
| 5 | VIP/会员状态 | **确认** | `bk.a.p()Z`（boolean 判定入口，已确认被 Web Action 当唯一来源）<br>`bk.a.f()I`（状态码 1=Vip） | 高 |

**重要前置结论（影响 2、5 的可行性判断）**

1. `com.byazt.*` 是**加固壳的运行时命名空间**（`smali_classes2` 有 1037 个、`smali_classes3` 有 6379 个 `com/byazt/*.smali`，带 `com.byazt.vqw.l` 注解 6710 处），**不是宿主业务代码**。候选清单里的 `BrushMaskView` 就在这里面。
2. `com.byazt.nd.BrushMaskView` **全 APK 零引用**（`rg -l 'BrushMaskView'` 只命中它自己），是死代码，钩它没有任何运行时效果。**排除。**
3. `ma/d` 是 **Gson 的 `TypeAdapterFactory`**（方法 `create(Lcom/google/jtm/f;...)`、`isMemberClass()`），`bf/b` 是网络/回调层（`vipStatus` 只是打点字符串），**两者都与 VIP 无关**，候选清单给的两条线索是误报。

---

## 1 强制更新闸门

### 1.1 线索辨析：`HMSCheckUpdateWebAction` 不是宿主逻辑

文件：`smali_classes5/com/kuaiduizuoye/scan/web/actions/HMSCheckUpdateWebAction.smali:1`

```
.class public Lcom/kuaiduizuoye/scan/web/actions/HMSCheckUpdateWebAction;
.annotation runtime Lcom/zybang/annotation/FeAction;
    name = "hms_check_update"
```

方法体（`:160-177`）只做三件事：判 `isFinishing()` → `Lcom/huawei/hms/jos/JosApps;->getAppUpdateClient(Activity)` → `checkAppUpdate(...)`。

**这是第三方（华为 HMS JOS）更新客户端的外壳**，钩它顶多跳过华为渠道的更新检查，对 App 自己的强制升级弹窗无效。列为**低优先**，可作为补充层。

### 1.2 确认的目标 A：宿主强制更新闸门（首选）

- **类**：`ei.y`（`smali_classes5/ei/y.smali`，`super Ljava/lang/Object;`，是 `Popwindow` 弹窗调度器）
- **方法**：`L()V` —— `private`，无参，返回 `void`
- **证据**：`smali_classes5/ei/y.smali:2113`（`.method private L()V`），关键方法体在 `:2166-2193`
- **为什么它是正确钩点**（读方法体确认）：

```smali
2166  sget-object v1, Lcom/kuaiduizuoye/scan/preference/CommonPreference;->FORCE_UPDATE:...
2170  invoke-static {v1}, Lcom/baidu/homework/common/utils/PreferenceUtils;->getBoolean(Ljava/lang/Enum;)Z
2181  if-eqz v1, :cond_1                 # FORCE_UPDATE == false → 走普通更新
2185  iget-object v1, v2, Lei/y;->a:Landroid/app/Activity;
2189  iget-object v4, v2, Lei/y;->h:Lci/a;
2193  invoke-static {v1, v3, v0, v4}, Lxl/z2;->t(Landroid/app/Activity;ZZLci/a;)V   # t(act, true, false, cb) → 强制更新流程
```

`L()` 是**唯一**读 `CommonPreference.FORCE_UPDATE` 并据此决定"走强制更新"的地方（全 APK `FORCE_UPDATE` 只有 3 处引用：`z2$b:222` 写入、`ei/y:2166` 读取、`CommonPreference:277/925` 定义）。`:1720` 显示它由 `H(String, Popwindow$ListItem)` 的 `pswitch_5` 分支调用，即服务端下发的 `Popwindow` 弹窗类型 5 = 强制更新弹窗。

- **钩法**：

```kotlin
Xp.hook(
    "ei.y", "L",
    onBefore = { it.result = null }   // 直接 return-void，整个强制更新弹窗不弹
)
```

- **风险**：
  - `ei.y` 是**混淆名**（单字母类名），随版本极可能变。升级后必须重跑 `check_hook_targets.py` 并重新定位（锚点是 `CommonPreference.FORCE_UPDATE` 的读取点，不是类名）。
  - `L()` 无返回值，`it.result = null` 即跳过整个方法；不影响 `z2` 的下载安装链路（那条链路只在 `forceUp==1` 时才被 `z2$b` 触发）。
  - 若只想"跳过弹窗但保留正常更新提示"，应改为在 `it.args` 侧不动、只跳过 `L()`；两者行为等价，因为 `L()` 是唯一的强制分支入口。

### 1.3 确认的目标 B：判定核心（更稳的锚点）

- **类**：`xl.z2`（`smali_classes5/xl/z2.smali`，宿主更新控制器）
- **方法**：`k(Lcom/kuaiduizuoye/scan/common/net/model/v1/CheckAppUpdate;)V` —— `private static`，返回 `void`
- **证据**：`smali_classes5/xl/z2.smali:248`（`.method private static k(...)V`），判定逻辑 `:316-410`
- **为什么**：整个"是否强制"的四象限判定都在这里，读 `CheckAppUpdate.updateType` 与 `forceUp`：

```
updateType==2 && forceUp==1 → j(6)   # 强制更新（下载型）
updateType==2 && forceUp==0 → j(5)   # 普通更新
updateType==1 && forceUp==1 → j(4)   # 强制更新（商店型）
updateType==1 && forceUp==0 → j(3)   # 普通更新
```

`j(I)` 是派发到 `u()`/`v()` 等具体弹窗的开关。所以"改判定"比"跳弹窗"更接近根因。

- **钩法**（把 `forceUp` 抹成 0，让其走"普通更新"分支，而不是完全不弹）：

```kotlin
Xp.hook(
    "com.kuaiduizuoye.scan.common.net.model.v1.CheckAppUpdate", "getForceUp",  // 不存在，见下
    onBefore = { it.result = 0 }
)
```

> ⚠️ **`CheckAppUpdate` 没有 getter**：字段 `forceUp` 是 `public`（`:20`），全 APK 都是 `iget` 直读，没有 `getForceUp()`。所以不能钩 getter。

正确写法是**在 `k()` 入口改实参对象字段**：

```kotlin
Xp.hook(
    "xl.z2", "k",
    CheckAppUpdateClass,          // 需 clazzOrNull 解析
    onBefore = {
        val arg = it.args[0]
        arg.javaClass.getField("forceUp").setInt(arg, 0)   // 强制 → 普通
    }
)
```

- **风险**：
  - `forceUp` 同时被 `z2$b:222/250` 读取用于**写入 `CommonPreference.FORCE_UPDATE`**。改字段会让偏好也变 0，下次冷启动 `ei.y.L()` 走进"普通更新"分支——这正是想要的效果，但意味着**改动是持久的**（写进 SharedPreferences）。要可逆就改钩 1.2 的 `L()`。
  - `xl.z2` 同样是混淆名，锚点是 `CheckAppUpdate` 模型类（该模型类名是**语义名，不会变**），比 `z2` 稳。
  - 这属于"改服务端下发的数据"，若服务端在别处（如退出登录/风控）二次校验版本，可能触发其他提示。未在静态层观察到该二次校验。

### 1.4 辅助锚点（语义名，跨版本稳定，适合做"存活探针"）

- `com.kuaiduizuoye.scan.common.net.model.v1.CheckAppUpdate` — 字段 `forceUp:I`、`updateType:I`、`apkUrl:String`、`vcname:String`（`:18-36`）
- `com.kuaiduizuoye.scan.preference.CommonPreference` — 枚举常量 `FORCE_UPDATE`（`:47`）
- `com.kuaiduizuoye.scan.common.net.model.v1.UpdateReport$Input.buildInput(JILjava/lang/String;)` — 更新上报（`xl/z2.s:1603` 调用）

### 1.5 另一个入口（H5 侧，可选）

`com.kuaiduizuoye.scan.web.actions.GoToUpdateHeaderNameWebAction`（`FeAction` 类）存在，但读其结构是"更新标题栏"UI 动作，不是强制升级闸门。**不作为强制更新钩点**。

---

## 2 PDF/打印去水印

### 2.1 先否掉候选清单给的两个线索

| 线索 | 核查结果 |
|---|---|
| `smali_classes3/com/byazt/nd/BrushMaskView.smali` | **加固壳命名空间**（`com.byazt.*`），且 `rg -l 'BrushMaskView'` 全 APK **只命中它自己** → 零引用死代码。有 `onDraw(Canvas)`、`setWatermark(I)`、`setMaskColor(I)`、`setEraserSize(F)`，但无任何调用方，**钩了不产生任何效果**。排除。 |
| `smali_classes5/fh/g.smali` | 是**埋点上报类**，`isClearWatermark` 只出现在 `:1017` 作为 `Map.put` 的 key，值来自 `cu.l.m0()` 的返回值转字符串。钩它只能改上报数据，**改不了水印**。排除。 |

### 2.2 确认的机制：水印是**服务端合成**的，不是本地绘制

这是本节最重要的结论，直接决定"能不能一个 before 钩子不画水印"。

**证据链**：

1. `cu/p.l(List,boolean,boolean)List` — `smali_classes6/cu/p.smali:2293`
   从 `ScanEntity.getClearWriting()` / `getClearWatermark()` 取出两个 `int`，转成两个 `boolean` 传给 `cu.l` 构造器：
   ```smali
   606  invoke-virtual {v4}, Lcom/zybang/doc_common/db/entity/ScanEntity;->getClearWatermark()I
   614  if-ne v4, v10, :cond_6      # == 1 → true
   622  invoke-virtual {v1, v0, v3, v9}, Lcu/p;->l(Ljava/util/List;ZZ)Ljava/util/List;
   ```
   三处调用方：`cu/p:622`、`cu/p:2876`、`DcScanEditorViewModel$c:1072`、`SortViewModel$d:775`。

2. `cu.l` 构造器 — `smali_classes6/cu/l.smali:286`
   `.method public constructor <init>(String;String;String;String;IIFLjava/lang/String;Ljava/lang/String;IIZZLjava/lang/String;)V`
   布尔落点已逐条核实（`:507`、`:512`）：
   ```smali
   504-507  move/from16 p1, p12 → iput-boolean p1, p0, Lcu/l;->q:Z    # clearWriting
   509-512  move/from16 p1, p13 → iput-boolean p1, p0, Lcu/l;->r:Z    # clearWatermark
   ```
   即 **`p13` = clearWatermark → 字段 `r`**。

3. `cu.l.m0()Z` — `smali_classes6/cu/l.smali:15077`，**就是 `clearWatermark` 的 getter**：
   ```smali
   15081  iget-boolean v0, p0, Lcu/l;->r:Z
   ```
   （紧邻的 `n0()Z` = `:15088` 读字段 `q` = clearWriting；`o0()Z` = `:15099` 读 `x`）

4. `cu.l.K(String,Lt10/f;)` — 关键：把两个标志编成**合成参数数组**发给服务端：

   ```smali
   3116-3165  若 filterType != yt.h.g0().e() → list.add("0")
   3171  iget-boolean v0, v1, Lcu/l;->q:Z          # clearWriting
   3179  const-string v0, "1"  → list.add("1")      # 去手写
   3189  iget-boolean v0, v1, Lcu/l;->r:Z          # clearWatermark
   3197  const-string v0, "2"  → list.add("2")      # 去水印
   3207  new-instance v0, Lcom/zybang/doc_common/common/model/net/v1/ImageCombineParamExt;
   3267  joinToString(list, ",", ...)                # → ext 字段
   3330  invoke-direct {v0, ...}, Lcu/l;->z0(ImageCombineParamExt,File,String,String,Lt10/f;)   # 上传合成
   ```

5. `ImageCombine$Input` — `smali_classes6/com/zybang/doc_common/common/model/net/v1/ImageCombine$Input.smali:18`
   ```smali
   18  .field public static final URL:Ljava/lang/String; = "/kdapi/image/combine"
   24  .field public ext:Ljava/lang/String;      # ← 上面 joinToString 的 "0,1,2" 落这里
   32  .field public sceneList:Ljava/lang/String;
   ```
   请求由 `cu/c:3352`、`cu/r:2805`、`cu/l:12161` 三处 `buildInput(...)` 构造。

**结论**：`clearWatermark` 不是"本地某个 Canvas 不画"，而是**作为字符串 `"2"` 拼进 `ext` 参数上传到 `/kdapi/image/combine`，由服务端做去水印合成**。因此候选清单设想的"一个 before 钩子让水印不绘制（onDraw / setMask / addWatermark）"**在本 App 里不存在对应实现**——没有本地水印绘制点可钩。`rg 'Landroid/graphics/Canvas;->drawText'` 在宿主包内命中的全是 `LoopView`/`InputVerifyCode` 之类无关控件。

### 2.3 那么能钩什么（按可行性排序）

**钩点 A（唯一真正可控的开关）：`cu.l.m0()Z`**

- **类**：`cu.l`
- **方法**：`m0()Z` —— `public final`，无参，返回 `boolean`
- **证据**：`smali_classes6/cu/l.smali:15077`
- **钩法**：
  ```kotlin
  Xp.hook("cu.l", "m0", onBefore = { it.result = true })  // 强制"已去水印"
  ```
- **为什么有效**：`m0()` 是 `clearWatermark` 的唯一读取入口（`K()` 在 `:3189` 直读字段 `r`，**绕过** getter —— 见风险）。若只钩 `m0()`，只影响 `fh/g` 的埋点和 UI 状态，**改不到 `ext` 参数**。
- **风险（重要）**：`K()` 在 `:3189` 用 `iget-boolean v0, v1, Lcu/l;->r:Z` **直读字段**，不调 `m0()`。所以：
  - 要让服务端真的按"去水印"合成，必须让**字段 `r` 为 true**，即钩 `cu.l` 构造器或 `p13` 传参侧，光钩 getter 不够。
  - 而在 `K()` 里把 `"2"` 塞进 list 属于改参数，需要 `hookAll` + 改局部集合，超出"一个 before 钩子"的范围。
  - 更重要：这等于**要求服务端给你无水印结果**。服务端是否校验 VIP/次数，静态层无法判定（`ImageCombine$Input` 里没有 `vip` 字段，风险中等但**未验证**）。

- **另一个更干净的做法**（推荐，属"客户端可选开关"）：直接在数据层把 `ScanEntity.clearWatermark` 置 1，让 `cu/p.l` 自己走 true 分支：
  ```kotlin
  // 钩点是 settable 字段，非方法，Xposed 需 hook ScanEntity.setClearWatermark(I) 或直接反射改实例
  ```
  `com.zybang.doc_common.db.entity.ScanEntity` — `getClearWatermark()I` (`:1262`)、`setClearWatermark(I)V` (`:1562`)，字段是 `int`（0/1），`ImageViewModel$i` (`:589`) 是唯一 setter 调用点。

**钩点 B（打印/导出动作层，仅确认存在，未确认能否去水印）**

以下 `FeAction` 动作类存在，但**读其结构未见 watermark 参数**（`rg -i 'watermark|水印'` 在这几个文件里零命中）：

| 类 | 说明 |
|---|---|
| `com.kuaiduizuoye.scan.web.actions.PdfPrintAction` | PDF 打印动作 |
| `com.kuaiduizuoye.scan.web.actions.GenerateAndPrintPdfAction` | 生成并打印 |
| `com.kuaiduizuoye.scan.web.actions.SharePdfAction` | 分享 PDF |
| `com.kuaiduizuoye.scan.web.actions.ZybDirectPrintAction` | 直连打印 |
| `com.kuaiduizuoye.scan.web.actions.OpenPdfPreviewAction` | PDF 预览 |

**未确认**：这些动作是否把水印作为参数透传。它们的方法体尚未逐行读完（只做了关键词检索），因此**不能断言"钩它们能去水印"**。

### 2.4 本节结论

- **"用一个 before 钩子让水印/遮罩不绘制" —— 未确认可行为**，因为本 App 的水印走**服务端 `/kdapi/image/combine` 合成**，客户端没有对应的本地绘制点。
- 唯一确认存在的客户端开关是 `clearWatermark`（`ScanEntity` 字段 `int` / `cu.l` 字段 `r` / getter `cu.l.m0()Z`），且它是 App **自带的用户功能**（`strings.xml:1528` `去除水印`、`:1617` `还原水印`），说明**产品设计上允许用户自己开关** —— 这降低了"钩它算不算越权"的不确定性，但不等于免费（服务端可能限次）。
- `BrushMaskView`（`setWatermark(I)`）是壳里的死代码，**排除**。

---

## 3 H5 桥：下载媒体

### 3.1 确认的目标

- **类**：`com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction`
  - smali 声明：`.class public Lcom/kuaiduizuoye/scan/web/actions/FeDownloadMediaAction;`
  - 父类：`.super Lcom/baidu/homework/activity/web/actions/WebAction;`
- **`@FeAction` 注解与名字**：`smali_classes5/com/kuaiduizuoye/scan/web/actions/FeDownloadMediaAction.smali:7-9`
  ```smali
  .annotation runtime Lcom/zybang/annotation/FeAction;
      name = "downloadMedia"
  .end annotation
  ```
- **dispatch 入口方法**：`onAction(Landroid/app/Activity;Lorg/json/JSONObject;Lcom/baidu/homework/common/ui/widget/HybridWebView$ReturnCallback;)V`
  - smali：`smali_classes5/com/kuaiduizuoye/scan/web/actions/FeDownloadMediaAction.smali:697`
  - `.annotation system Ldalvik/annotation/Throws; value = { Lorg/json/JSONException; }`
  - 返回 `void`
- **精确参数类型（Java 写法）**：`android.app.Activity`, `org.json.JSONObject`, `com.baidu.homework.common.ui.widget.HybridWebView$ReturnCallback`

### 3.2 为什么它是正确钩点（读方法体确认）

`:803-943` 的逻辑：

```
:803  if (activity == null || activity.isFinishing()) return
:819  if (json == null) return
:831  json.has("url")  ?: return
:847  json.has("type") ?: return
:863  url = json.getString("url"); if (TextUtils.isEmpty(url)) return
:887  type = json.getInt("type")
:895  if (type != 1) return                     # 1 = PIC_TYPE（:15 .field PIC_TYPE:I = 0x1）
:899  if (jj.i.a()) → downloadPicture(act,url)   # 有权限：直接下载
:911  else → new jj.h(act, lambda) .e()          # 无权限：申请权限后下载
```

即：**`type==1`（图片）才走下载**，URL 从 `json["url"]` 取，落盘由 `downloadPicture(Activity,String)`（`:179`）用 `FeDownloadMediaAction$1` 异步执行，之后 `updatePhotoAlbum(Activity)`（`:505`）触发 `MediaScannerConnection.scanFile`。

派生方法（可用于更细粒度钩子）：

| 方法 | 签名 | 位置 |
|---|---|---|
| `downloadPicture` | `private (Landroid/app/Activity;Ljava/lang/String;)V` | `:179` |
| `updatePhotoAlbum` | `private (Landroid/app/Activity;)V` | `:505` |
| `savePhotoErrorTips` | `private (Landroid/app/Activity;)V` | `:394` |
| `cancelOperation` | `private ()V` | `:83` |

### 3.3 钩法

**场景 1：拦截/改写下载 URL（最常用）**

```kotlin
Xp.hook(
    "com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction",
    "onAction",
    android.app.Activity::class.java,
    org.json.JSONObject::class.java,
    // HybridWebView$ReturnCallback 用 clazzOrNull 解析
    onBefore = {
        val json = it.args[1] as? org.json.JSONObject ?: return@hook
        if (json.optInt("type") == 1) {
            // 改写为原图 / 去掉服务端缩略参数
            val u = json.optString("url")
            if (u.isNotEmpty()) json.put("url", u.replace(THUMB_REGEX, ""))
        }
    }
)
```

**场景 2：完全接管下载（不让它自己写相册）**

```kotlin
Xp.hook(
    "com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction",
    "onAction", /* 同上三参 */
    onBefore = { it.result = null }   // 直接 return-void
)
```
→ 副作用：`ReturnCallback` 不会被调用，前端可能一直等回包。**仅在完全自定义实现时用**。

**场景 3：只改落盘提示/媒体库刷新** — 钩 `updatePhotoAlbum(Activity)`。

### 3.4 风险

- `onAction` 是 **7 个 `FeAction` 类共享的方法名**，且 `WebAction` 基类也声明了同名方法。用 `Xp.hook`（精确类）没问题；**不要用 `hookAllAfter("...WebAction", "onAction")`** 全局钩，会命中 397 个 action。
- `HybridWebView$ReturnCallback` 是内部类，Kotlin 里写 `clazzOrNull("com.baidu.homework.common.ui.widget.HybridWebView\$ReturnCallback")`。**注意脚本只校验类名/方法名**，参数写错不影响 `OK` 判定，但运行时 `Xp.hook` 会返回 false —— 这正是本脚本的盲区，需真机验证。
- `jj.i.a()` / `jj.h` 是权限封装（`com.tbruyelle.rxpermissions` 风格），非宿主业务类。
- 类名是**语义名**（`FeDownloadMediaAction`），跨版本稳定性很高；`@FeAction(name="downloadMedia")` 的字符串也是稳定锚点（可做启动期自检）。

---

## 4 H5 桥：拿到用户信息

### 4.1 确认的目标

- **类**：`com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction`
- **`@FeAction` 名字**：`smali_classes5/com/kuaiduizuoye/scan/web/actions/GetUserInfoWebAction.smali:7-9`
  ```smali
  .annotation runtime Lcom/zybang/annotation/FeAction;
      name = "getuserinfo"
  .end annotation
  ```
- **dispatch 入口**：`onAction(Landroid/app/Activity;Lorg/json/JSONObject;Lcom/baidu/homework/common/ui/widget/HybridWebView$ReturnCallback;)V`
  - smali：`smali_classes5/com/kuaiduizuoye/scan/web/actions/GetUserInfoWebAction.smali:132`
  - 返回 `void`
- **精确参数类型**：`android.app.Activity`, `org.json.JSONObject`, `com.baidu.homework.common.ui.widget.HybridWebView$ReturnCallback`

### 4.2 为什么它是正确钩点（读方法体确认）

`:229-336` 的组装逻辑（`try` 块内）：

```
:240  json.put("identityName", qh.n.h())          # 身份名（学生/家长…）
:257  boolean logged = qh.o.w()                   # 是否登录
:267  "uname" / "uid" / ""
:279  if (!logged) {                              # 未登录
:284      json.put("uid",  "")
:289      json.put("uname","")
:294      callback.call(json)                     # 直接回空
:299      return
      }
:314  Userinfov3 u = qh.o.s()                    # 已登录取用户模型
:326  json.put("uid",   ...)
:331  json.put("uname", ...)
:336  callback.call(json)
```

另有私有方法 `getLoginType()I`（`:29`）。

**这是 H5 侧"取用户信息"的唯一实现**，回包通过 `HybridWebView$ReturnCallback.call(JSONObject)` 单次交出。

### 4.3 钩法

**读 H5 要什么（观察用）**

```kotlin
Xp.hook(
    "com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction",
    "onAction",
    android.app.Activity::class.java,
    org.json.JSONObject::class.java,
    onAfter = {
        val cb = it.args[2]
        Log.i("KdKit", "getuserinfo returned to H5")
    }
)
```

**改返回值（注入字段）** — 因为 `json` 是局部 `new JSONObject()`，`onAfter` 拿不到它。要改得钩 **`ReturnCallback.call(JSONObject)`** 并识别来源，或**钩 `onBefore` 并用 `XC_MethodHook` 的 `afterHookedMethod` 无济于事**。

**推荐做法：直接替换为自定义实现**（`it.result = null` + 自己 `callback.call(json)`）：

```kotlin
Xp.hook(
    "com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction", "onAction",
    /* 三参 */,
    onBefore = {
        val cb = it.args[2]
        // 反射调 cb.call(JSONObject) 交出自定义对象
        it.result = null
    }
)
```

**更省事的读法**：`onAfter` 时 H5 已收到；若要"在 H5 拿到前改"，必须挂 `HybridWebView$ReturnCallback.call`（`smali_classes2/com/baidu/homework/common/ui/widget/HybridWebView$ReturnCallback`），但那会命中所有 bridge 回包，需按调用栈过滤。

**取值侧锚点（语义名，稳定）**

| 类.方法 | 签名 | 证据 |
|---|---|---|
| `qh.o.s()` | `public static ()Lcom/kuaiduizuoye/scan/common/net/model/v1/Userinfov3;` | `smali_classes5/qh/o.smali:4033` |
| `qh.o.w()` | `public static ()Z` | `smali_classes5/qh/o.smali:4565` |
| `qh.n.h()` | `public static ()Ljava/lang/String;` | `GetUserInfoWebAction:244` 调用 |

### 4.4 风险

- `qh.o` / `qh.n` 是**混淆名**，但 `Userinfov3` 是语义名。
- `GetUserInfoWebAction` 只返回 `identityName` / `uid` / `uname` 三个字段——**不含 VIP、手机号、token**。想拿更多得走 `qh.o.s()` 的 `Userinfov3` 全模型（含 `vip`、`tbxVip`）。
- 若 H5 侧对 `uid` 做校验（非空即视为已登录），注入假 `uid` 会让前端进入"已登录"分支但后端仍 401 —— 属半成品状态。

---

## 5 VIP/会员状态

### 5.1 确认的目标（首选，已证明是 H5 的唯一来源）

- **类**：`bk.a`（`smali_classes5/bk/a.smali`，宿主工具类，含 `b/c/d/g/h/...` 一串静态方法）
- **方法**：`p()Z` —— `public static`，无参，返回 `boolean`
- **证据**：`smali_classes5/bk/a.smali:2139`（`.method public static p()Z`），体 `:2208-2227`
- **为什么它是正确钩点**：

```smali
2208  invoke-static {}, Lbk/a;->f()I       # 取 Vip.status
2213  move-result v1
2219  if-ne v1, v2 (v2=1) → return true     # status == 1 → 是会员
2227  return false
```

**关键旁证（这是最强证据）**：`VipCurrentStatusWebAction` 把 `bk.a.p()` 当作"是否 VIP"的**唯一来源**直接回给 H5：

`smali_classes5/com/kuaiduizuoye/scan/web/actions/VipCurrentStatusWebAction.smali:169`（`onAction`，`@FeAction(name="app_kdzy_vip_current_status")`）
```smali
:   invoke-static {}, Lbk/a;->p()Z
:   invoke-static {p1}, Ljava/lang/Boolean;->toString(Z)Ljava/lang/String;
:   invoke-direct {p0, p3, p1}, ...->call(ReturnCallback, String)V   # 回 "true"/"false"
```
→ **H5 页面判断会员与否，走的就是 `bk.a.p()`**。钩它一处，H5 侧全部生效。

- **钩法**：

```kotlin
Xp.hook("bk.a", "p", onBefore = { it.result = true })   // 恒为会员
```

### 5.2 确认的目标 B：状态码（更细粒度）

- **类**：`bk.a`
- **方法**：`f()I` —— `public static`，无参，返回 `int`
- **证据**：`smali_classes5/bk/a.smali:730`
- **为什么**：`p()` 和 `e()` 都委托给它；它是 `Vip.status` 的原始读取点：
  ```smali
  799   invoke-static {}, Lqh/o;->s()Lcom/kuaiduizuoye/scan/common/net/model/v1/Userinfov3;
  811   iget-object v1, v1, Lcom/kuaiduizuoye/scan/common/net/model/v1/Userinfov3;->vip:Lcom/kuaiduizuoye/scan/common/net/model/v1/Userinfov3$Vip;
  823   iget v0, v1, Lcom/kuaiduizuoye/scan/common/net/model/v1/Userinfov3$Vip;->status:I
  ```
  `Userinfov3$Vip.status:I`（`smali_classes5/com/kuaiduizuoye/scan/common/net/model/v1/Userinfov3$Vip.smali:38`），**`1` = 会员**（由 `p()` 的 `if-ne v1, 1` 反推）。
- **钩法**：
  ```kotlin
  Xp.hook("bk.a", "f", onBefore = { it.result = 1 })   // status 恒 1
  ```

### 5.3 确认的目标 C：`e()I`（归一化后的状态）

- **方法**：`e()I`，`public static`，返回 `int`，证据 `smali_classes5/bk/a.smali:639`
- 体：`f() == 1 → return 1; else return 0` —— 就是"是否会员"的 int 版。
- 钩它等价于钩 `f()`，但**语义已归一**，更安全（不会把 2/3 之类的中间态漏出去）。

### 5.4 另一条独立判定：`bk.a.n()Z`（`tbxVip`，可能是"同步/题库会员"）

- **方法**：`n()Z`，`public static`，返回 `boolean`，证据 `smali_classes5/bk/a.smali:1800`
- 体（`:1869-1900`）：
  ```smali
  1869  invoke-static {}, Lqh/o;->s()...               # Userinfov3
  1885  iget-object v2, v1, ...->tbxVip:...$TbxVip;    # 第二套会员体系
  1900  iget-wide v6, v2, ...$TbxVip;->status:J        # long 型 status
  ```
- **为什么单独列出**：`Userinfov3` 同时有 `vip`（`Userinfov3$Vip.status:I`）和 `tbxVip`（`Userinfov3$TbxVip.status:J`）两套会员字段（`Userinfov3.smali:143` 与 `:171`）。若要"全功能解锁"，**两个都要钩**。
- **钩法**：`Xp.hook("bk.a", "n", onBefore = { it.result = true })`

### 5.5 数据模型（语义名，跨版本稳定的自检锚点）

> ⚠️ **重要陷阱（已用脚本实测）**：`Userinfov3` **只有 1 个方法（构造器 `<init>()V`），没有任何 getter**。所有字段都是 `public`，全 APK 靠 `iget-object` / `iget` 直读。
> 实测 `check_hook_targets.py` 对 `Userinfov3.getVip`、`CheckAppUpdate.getForceUp` 均返回 **`MISSING-METHOD`** —— 这两个类**不能钩 getter**，只能：
> - 通过 `Xp.classLoader.loadClass(...)` + 反射 `getField`/`setField` 改 public 字段；或
> - 钩读该字段的**上游方法**（即 `bk.a.f()`、`xl.z2.k()`）。
>
> 同理 `CheckAppUpdate.forceUp` 也是 public 字段无 getter（`CheckAppUpdate.smali:20`，方法表仅 `<init>()V`）。

| 类 / 字段 | 类型 | 证据 |
|---|---|---|
| `com.kuaiduizuoye.scan.common.net.model.v1.Userinfov3.vip` | `Userinfov3$Vip` | `Userinfov3.smali:171` |
| `com.kuaiduizuoye.scan.common.net.model.v1.Userinfov3.tbxVip` | `Userinfov3$TbxVip` | `Userinfov3.smali:143` |
| `Userinfov3$Vip.status` | `int` | `Userinfov3$Vip.smali:38` |
| `Userinfov3$Vip.expireDay` | `int` | `Userinfov3$Vip.smali:32` |
| `Userinfov3$Vip.endDate` | `String` | `Userinfov3$Vip.smali:30` |
| `com.kuaiduizuoye.scan.common.net.model.v1.UserHome.isVip` | `boolean` | `UserHome.smali:54` |
| `com.kuaiduizuoye.scan.activity.vip.vipquestion.VipPrivilege` | 类（弹 VIP 特权 dialog） | `VipPrivilege.smali:1` |

### 5.6 风险

- **`bk.a` 是混淆名**（2 字符），升级后大概率变。稳定锚点是 **`Userinfov3$Vip.status` 字段名** 和 **`VipCurrentStatusWebAction` 的 `@FeAction(name="app_kdzy_vip_current_status")` 字符串**（语义名，不会混淆）。升级后用后两者反查 `bk.a` 的新名字。
- **`bk.a.p()` 只影响客户端判定**。真正的资源鉴权在服务端（`/kdapi/*`）。钩它之后：H5 页面会显示"会员"样式并放开前端入口，但**服务端仍可能拒绝实际资源请求**（如去水印合成、题库解析）。这属"服务端权威"，静态层无法绕过——**未验证**，需真机抓包确认哪些接口会 403。
- `bk.a.f()` 返回 `int` 而非 `boolean`，若服务端下发 `status=2` 表示"过期"，钩成 `1` 会让 `expireDay` 与实际不符，UI 可能显示"会员 0 天"。建议钩 `p()`（boolean）而非 `f()`（int）以免整数语义冲突。
- `MainActivity:2660` 也调用 `Lbk/a;->p()Z` 拼进 `isvip` 打点参数——钩 `p()` 会**污染埋点数据**（上报"会员"）。若在意数据，改为钩 `VipCurrentStatusWebAction.onAction`，只影响 H5 回包。

---

## 未确认项与查证过程

以下是**明确未确认**的项，附"查过什么关键词、看到什么"。不编造。

### U1 · "用一个 before 钩子让水印/遮罩不绘制" —— 未确认可行为

- **查过**：`rg -i 'watermark'` 扫全部 7 个 smali 根（命中 24 个文件）；`rg '水印' smali*/ res/`（只命中 `res/values/strings.xml` 两条）；`rg 'Landroid/graphics/Canvas;->drawText'` 在 `smali_classes5/com/kuaiduizuoye/` 与 `smali_classes6/com/zybang/`（命中全是 `LoopView`/`InputVerifyCode`/`CustomTextView` 等无关控件）；`rg 'ClearWatermark'`（命中 15 处，全部在 `ScanEntity` 字段读写 + `cu/l` + `fh/g` 埋点）。
- **看到什么**：客户端**没有**"给图片/PDF 画水印"的绘制代码。`clearWatermark` 只作为**字符串 `"2"` 拼进 `ext` 参数**，上传 `/kdapi/image/combine`（`ImageCombine$Input.URL`）由服务端合成。
- **为什么不能下结论**：不能排除水印在服务端返回的图片里已烘焙；也不能排除个别入口（如 `ZybDirectPrintAction`）另有本地打印水印。后者的方法体**未逐行读完**。

### U2 · `BrushMaskView` 是否可用于遮罩去除 —— 已排除（负结论，非"未确认"）

- **查过**：`rg -l 'BrushMaskView' smali*/` → **只命中 `BrushMaskView.smali` 自己**。
- **看到什么**：类存在（`onDraw(Canvas)`、`setWatermark(I)`、`setMaskColor(I)`、`setEraserSize(F)`、`onMeasure`、`onSizeChanged`），但**零引用**。所属 `com.byazt.*` 是加固壳命名空间（该命名空间在 dex 里共 7416 个类，带 `com.byazt.vqw.l` 注解 6710 处）。
- **结论**：**死代码，钩它无运行时效果**。候选清单把它当线索是误判。

### U3 · `ma/d` 与 `bf/b` 是否是 VIP 判定 —— 已排除（负结论）

- **`ma/d`**（`smali_classes4/ma/d.smali`，16365 B）：`rg -i 'vip'` **只命中 `:188 isMemberClass()Z`**（Java 反射 API，与会员无关）。方法表：`h(Class)Z`、`i(Class)Z`、`j(Class)Z`、`k(la/c)Z`、`l(la/d)Z`、`m(la/c;la/d)Z`、`create(Lcom/google/jtm/f;Loa/a;)Lcom/google/jtm/x;` —— 这是 **Gson 的 `TypeAdapterFactory`**。**与 VIP 无关。**
- **`bf/b`**（`smali_classes5/bf/b.smali`，18379 B）：`rg -i 'vip'` **只命中 `:627 const-string v8, "vipStatus"`**（打点 key）。方法表 `a(ICallback, qb/j)`、`c()Lrb/a;`、`b()V`、`d()V`、`e(ICallback)V` —— 网络/回调层。**与 VIP 判定无关。**
- **结论**：候选清单这两条线索均为误报，真正的入口是 `bk.a`。

### U4 · 打印动作是否透传水印参数 —— 未确认

- **查过**：`rg -i 'watermark|水印'` 针对 `PdfPrintAction.smali`、`GenerateAndPrintPdfAction.smali`、`SharePdfAction.smali`、`ZybDirectPrintAction.smali`、`OpenPdfPreviewAction.smali` → **零命中**。
- **看到什么**：这 5 个类存在且都是 `FeAction` 动作类，但结构里没出现 watermark 关键词。
- **为什么未确认**：零命中不等于"没有水印"，可能是参数名不同（如 `ext`、`flag`、`type`）。方法体未逐行读完，**不下结论**。

### U5 · `ei.y` 是否 100% 是"强制更新弹窗" —— 高置信但非绝对

- **查过**：`rg 'FORCE_UPDATE'` 全 APK → 3 处引用（`z2$b:222` 写、`ei/y:2166` 读、`CommonPreference` 定义）。`ei/y` 方法表含 `H(String, Popwindow$ListItem)` 的 `pswitch_5 → L()` 跳转表；类内还有 `A/B/C/D/E/F/G/I/J/K` 等并列分支，均从 `Popwindow$ListItem` 分派。
- **为什么不是绝对**：`Popwindow` 是服务端下发的"弹窗池"通用模型（含 `A/B/...+pswitch` 多分支），`pswitch_5` 对应 type 5 是我从分支位置推断，**没有服务端协议文档佐证**。但 `L()` 内**唯一**读 `FORCE_UPDATE` 且**唯一**调 `z2.t(act, true, false, cb)`，功能归属高置信。

### U6 · `Xp.hook` 参数类型写错时的盲区

- `check_hook_targets.py` 只比对类名与方法名，**不校验参数类型**。所以即使我给的 Java 参数类型有偏差，脚本仍会输出 `OK`。
- 这意味着"脚本判 OK" ≠ "运行时钩得住"。真正验证必须靠 LSPosed 日志里 `Xp.hook` 的返回值和一次功能点击。
- 本文件所有参数类型均从 `.method` 行的 descriptor 直接翻译（如 `Landroid/app/Activity;` → `android.app.Activity`，`Z` → `boolean`，`I` → `int`），未做猜测。

### U7 · 哪些类**不能**钩 getter（实测确认）

用脚本逻辑实跑 18 个候选，**16 个 `OK`，2 个 `MISSING-METHOD`**，两个失败项都是"误以为有 getter"：

```
MISSING-METHOD  com.kuaiduizuoye.scan.common.net.model.v1.CheckAppUpdate.getForceUp
MISSING-METHOD  com.kuaiduizuoye.scan.common.net.model.v1.Userinfov3.getVip
```

原因：这两个模型类**方法表里只有 `<init>()V`**，字段全 `public`，读靠 `iget` 直读。**不要写 `Xp.hook(..., "getForceUp")`，脚本会判 MISSING-METHOD，运行时也不会命中。**

通过实测的 16 条（可作为自检基线）：

```
OK  ei.y.L
OK  xl.z2.k
OK  cu.l.m0
OK  cu.p.l
OK  com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction.onAction
OK  com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction.onAction
OK  com.kuaiduizuoye.scan.web.actions.HMSCheckUpdateWebAction.onAction
OK  com.kuaiduizuoye.scan.web.actions.VipCurrentStatusWebAction.onAction
OK  bk.a.p    OK  bk.a.n    OK  bk.a.f    OK  bk.a.e
OK  com.zybang.doc_common.db.entity.ScanEntity.setClearWatermark
OK  com.zybang.doc_common.db.entity.ScanEntity.getClearWatermark
OK  com.zybang.doc_common.common.model.net.v1.ImageCombine$Input.buildInput
OK  com.byazt.nd.BrushMaskView.onDraw        # 存在但零引用，勿用
```

> `BrushMaskView.onDraw` 判 `OK` 是因为**类和方法确实存在**——脚本无法判断"有没有人调它"。这正是脚本的能力边界，也是本文件把 U2 单独列出的原因。

---

## 附：可直接进 `check_hook_targets.py` 的最小候选集

以下 6 条覆盖 4 项确认功能（水印项因机制原因不含），全部已核实类与方法存在：

```kotlin
// 1 强制更新
Xp.hook("ei.y", "L", onBefore = { it.result = null })
Xp.hook("xl.z2", "k", /* CheckAppUpdate */ arg, onBefore = { /* forceUp = 0 */ })

// 3 H5 下载媒体
Xp.hook("com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction", "onAction",
        android.app.Activity::class.java, org.json.JSONObject::class.java, /* ReturnCallback */ cb, onBefore = { })

// 4 H5 用户信息
Xp.hook("com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction", "onAction",
        android.app.Activity::class.java, org.json.JSONObject::class.java, /* ReturnCallback */ cb, onAfter = { })

// 5 VIP
Xp.hook("bk.a", "p", onBefore = { it.result = true })
Xp.hook("bk.a", "n", onBefore = { it.result = true })
```

自检锚点（语义名，可写进启动期断言，不怕混淆改名）：

```
com.kuaiduizuoye.scan.web.actions.HMSCheckUpdateWebAction      # @FeAction("hms_check_update")
com.kuaiduizuoye.scan.web.actions.FeDownloadMediaAction        # @FeAction("downloadMedia")
com.kuaiduizuoye.scan.web.actions.GetUserInfoWebAction         # @FeAction("getuserinfo")
com.kuaiduizuoye.scan.web.actions.VipCurrentStatusWebAction    # @FeAction("app_kdzy_vip_current_status")
com.kuaiduizuoye.scan.common.net.model.v1.CheckAppUpdate       # forceUp / updateType
com.kuaiduizuoye.scan.common.net.model.v1.Userinfov3           # vip / tbxVip
com.zybang.doc_common.common.model.net.v1.ImageCombine$Input   # URL = /kdapi/image/combine
com.kuaiduizuoye.scan.preference.CommonPreference              # FORCE_UPDATE
```
