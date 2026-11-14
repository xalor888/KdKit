# KdKit 7.7.2 → 7.9.0 适配记录

> 2026-11-01 · 宿主：`com.kuaiduizuoye.scan` **7.9.0 / versionCode 1840**
> 旧基线：7.7.2 / 1811（分析树保留在 `work/apktool_out_772/`）

## 为什么只需要改名字

7.9.0 把 R8 的混淆名**整体重掷**了一遍，方法体几乎原样（连 smali 行号都守恒）。
自动指纹统计：60,972 个旧类里 **42,906 个是"内容完全相同、只改了名"**，
另有 2,383 个只差资源常量（`const/16 0x434f → 0x39e3`）。算法链（RC4 / sign / token）**一条没变**，
34 个 arm64 native 库**逐字节相同**。

⇒ 模块的钩子只要换成新名字即可，逻辑一行不用动。

## 改了哪些（14 个文件，纯字面量）

| 功能 | 旧目标（7.7.2） | 新目标（7.9.0） | 证据 |
|---|---|---|---|
| `rm_splash` | `lk.a` | `dj.a` | 995 行对 995 行，方法行号全同 |
| `rm_adconfig` / `ad_probe` | `aj.a` | `di.a` | `d/f/h(I)` @624/1453/1653，`j/k()Z` @2998/3097 |
| `vip_unlock` | `bk.a` | **`aj.a`** ⚠️ 名字被复用 | 2347 行对 2347 行，`p()`@2139 `n()`@1800 |
| `watermark_off` | `cu.l` | `ov.l` | 18,506 行对 18,506 行，14 参 ctor 同在 @286 |
| `anti_detect` | `lk.f` | `dj.f` | `TracerPid`@413，四个方法行号全同 |
| `sign_observer` | `yl.f#g/h/y/j/s` | **`vm.g#h/i/z/k/t`** | 方法名整体后移一位（新插入一个方法），字段 `a/b/c` 全同 |
| `popwin_gate` / `skip_update` | `ei.y` | `hh.y` | `H(String,ListItem)` @1254 两版同 |
| `page_request_log` | `dr.f` / `dr.f$e` | `ps.f` / `ps.f$e` | 905 / 25 行两份全同 |
| `parent_ctrl_*` | `dj.e` | `ul.b` | 老 `dj.e` 3268 行 → 新 `ul.b:2144` |
| `skip_update`（第二入口） | `xl.z2` | `um.z2` | 2712 行两份全同 |
| `rm_popup`（模型） | `ci.a` | `fh.a` | 自动指纹精确命中 |
| `block_ad_sdk` | `xc.a` | `yc.a` | 同上 |
| `web_picture_watermark` | `CommonWebPictureBrowseActivity#c2 / #j2` | **`#o2 / #v2`** | 类名未混淆、方法改名；`q0:Z` 门控字段未变 |
| `http_body_probe` | `ql.a#getBody` | **`kl.a#getBody`** | 新 `ql.a` 继承 `Object`（名字被复用）；`kl.a` 的 `getBody()[B` 同在 @1459 |
| `bridge_action_log` | `web.actions.GetUserInfoWebAction` | `login.bridge.GetUserInfoWebAction` | 包重构（非混淆） |
| `parent_ctrl_probe`（模型） | `activity.parentmodel.util.ParentCtrlData` | `parentmode.api.ParentCtrlData` | 包重构 |

⚠️ **`aj.a` 这个名字新旧各占一次**：旧 `aj.a`（广告位配置）搬去了 `di.a`，而新 `aj.a` 是旧的 `bk.a`（VIP）。
`rm_adconfig` 与 `vip_unlock` 必须**同批**改，否则一个功能会钩到另一个功能的类上，而且 ④ 门禁还会报绿。

## 同时改的三处基础设施

1. `HostVersion.BASELINE_VERSION_{NAME,CODE}` → `7.9.0 / 1840`（版本守卫；否则每轮都会警告漂移）。
2. `HostVersion.read()`：`handleLoadPackage` 早于 Application 创建，`currentApplication()` 那一刻常为 null，
   旧实现直接放弃 ⇒ 抓取里永远没有版本行。改为后台最多轮询 3 s 再读。
   **设备实测**：`host com.kuaiduizuoye.scan 7.9.0 (1840) sdk=36`。
3. `kit/` 里 9 处 `RC4KEY b(1811)` 硬编码正则 → `RC4KEY b(\d+)`（版本换了不该让解密链断）。

## 验证（全部实跑，非推断）

| 门 | 结果 |
|---|---|
| ① 单元测试（JVM） | **119 / 0 失败** |
| ①b 抓取解析器（296 条 Python 单测） | **296 OK / 5 skipped** |
| ② assembleDebug | BUILD SUCCESSFUL |
| ③ 功能表一致 | 38 ↔ 38 ↔ 38 |
| ④ 钩子目标 | **124/124**（迁移前 99/124） |
| ⑤ 钩子签名 | **97/97**（迁移前 60/97） |
| ⑥ 钩子调用方 | **97/97**（迁移前 75/97） |
| ⑨ 热修复暴露面 / ⑩ 读预算 / ⑪ 解析往返 / ⑫ shell 边界 / ⑦ 假测试 / ⑧ 共享登记 | PASS |
| ⑬ 真机验证 | **12 PASS / 0 FAIL / 0 SKIP**（设备 APK 与分析的 APK 字节一致） |
| `acceptance.py --live` | **12/12**（含 live call HTTP 200 `errNo=0`、api rebuild 358/366 逐字节） |
| 设备运行时 | `HookCore ready (38 features)` · `HookCore audit: ready 37/38 features, hooks 94 ok / 0 failed` · 抓取 14,419 行 |

## 新增/修改的测试（契约随版本走）

4 个测试文件里钉住旧类名的断言已更新，并在注释里标注"7.7.2 里叫 X"：
`test_vip_call_sites.py`（`bk.a`→`aj.a`，三处真闸门换路径）、`test_super_slot_dispatch.py`（`ql.a`→`kl.a`）、
`test_web_picture_watermark.py`（`c2/j2/h2`→`o2/v2/t2`）、`test_smali_usage.py`（`cu.l`→`ov.l`、`yl.f`→`vm.g` 及方法移位）、
`test_robust_coverage.py`（`lk.f.d`→`dj.f.d`）。

## 回滚

```bash
# 模块源码（本轮改动前的快照）
rm -rf module/app/src/main/java && cp -R work/reverse790/java_backup_772 module/app/src/main/java
# 分析树（7.9.0 ↔ 7.7.2）
mv work/apktool_out work/apktool_out_790 && mv work/apktool_out_772 work/apktool_out
```

## 仍未验证

- **钩子是否真的拦住了行为**：门禁只证明类/方法/形参在、`HookCore` 只证明钩子装上了；
  "广告真的没了 / 会员真的解了"需要人工操作观察（本轮的抓取里能看到 `ADSLOT`/`GUARD`/`VIPLIMIT` 等行，但未逐功能验收）。
- `native_exit_guard` 的 `.so` 在宿主进程的 `loadLibrary` 解析（静态无法判定）。
- Robust 线上补丁是否改了被钩方法（抓取里的 `ROBUST` 行可查，本轮未逐条核）。
