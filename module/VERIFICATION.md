# 模块功能验证矩阵（自动生成）

* 来源：`FeatureRegistry.kt` + 模块日志/抓取（离线快照）+ `ROADMAP.md`
* 生成：`python3 kit/scripts/feature_matrix.py --offline --out module/VERIFICATION.md`
* **离线模式**：无设备 ⇒ "当前"列一律 `?`（不是 OFF）。**记录数**来自 `work/activity_inputs/` 的 5 份冻结抓取（与 `module/ACTIVITY.md` 同一批输入），按 `capture_schema.py` 的真实前缀解析计数，不是 substring 匹配。

| feature | 标题 | 分类 | 默认 | 当前 | 记录数 | 静态钩子 | 验证等级 | 真机 | 依据 | 代表证据 |
|---|---|---|---|---|---|---|---|---|---|---|
| `ad_probe` | 广告位读取观测 | ADS | false | ? | 34 | 5/5 | **强** | 未验证 | R37 以它为主题 + 证据文件 | `module/README.md` |
| `anti_detect` | 反调试检测绕过 | HOST | true | ? | 0 | 22/22 | **强** | 未验证 | R12 以它为主题 + 证据文件 | `module/README.md`<br>`work/dpsdk/FINDINGS.md` |
| `block_ad_sdk` | 广告 SDK 阻断 | ADS | false | ? | 0 | 4/4 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `bridge_guard` | 桥守卫（页面侧敏感 action） | HOST | false | ? | 14 | 2/2 | **强** | 未验证 | R20 以它为主题 + 证据文件 | `module/README.md`<br>`work/dpsdk/bridge_guard_r20.txt` |
| `exit_guard` | 退出守卫 | HOST | true | ? | 0 | 5/5 | **强** | 未验证 | R12 以它为主题 + 证据文件 | `module/README.md`<br>`work/dpsdk/FINDINGS.md` |
| `h5_bridge_log` | H5 桥调用记录 | HOST | false | ? | 707 | 3/3 | **强** | 未验证 | R14 以它为主题 + 证据文件 | `kit/README.md`<br>`module/README.md`<br>`work/TRIAGE.md` |
| `h5_debug` | H5 调试台 | HOST | false | ? | 0 | 共享:WebInjector | **强** | 未验证 | R50 以它为主题 + 证据文件 | `module/VERIFICATION.md`<br>`work/dpsdk/h5_debug_r50.txt`<br>`work/dpsdk/h5debug_r50.png` |
| `native_exit_guard` | 原生退出守卫（实验） | HOST | false | ? | 0 | 0/0 | **强** | 未验证 | R12 以它为主题 + 证据文件 | `module/README.md`<br>`work/dpsdk/FINDINGS.md` |
| `native_probe` | 签名公式探针 | MISC | false | ? | 360 | 1/1 | **强** | 未验证 | R7 以它为主题 + 证据文件 | `work/dpsdk/token_offline_r6.txt` |
| `page_js` | 页面脚本注入（page_js_script） | HOST | false | ? | 0 | — | **强** | 未验证 | R153 以它为主题 + 证据文件 | `kit/README.md`<br>`work/PAGE_API_SURFACE.md` |
| `pk_assist` | PK 自动作答 | PK | true | ? | 0 | 共享:WebInjector | **强** | 未验证 | R3 以它为主题 + 证据文件 | `work/dpsdk/R3_kd1_pk_mock.png` |
| `req_headers` | 宿主请求头观测 | HOST | false | ? | 0 | 3/3 | **强** | 未验证 | R172 以它为主题 + 证据文件 | `kit/ONBOARDING.md` |
| `rm_adconfig` | 广告配置拦截 | ADS | true | ? | 0 | 5/5 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `rm_feed_ad` | 信息流广告 | ADS | true | ? | 0 | 2/2 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `rm_main_banner` | 主页横幅广告 | ADS | true | ? | 0 | 2/2 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `rm_popup` | 弹窗广告 | ADS | true | ? | 0 | 1/1 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `rm_splash` | 开屏广告 | ADS | true | ? | 0 | 3/3 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `rm_tab_ad` | Tab 广告 | ADS | true | ? | 0 | 4/4 | **强** | 未验证 | R31 以它为主题 + 证据文件 | `work/TRIAGE.md`<br>`work/dpsdk/ad_ablation_r31.txt`<br>`work/dpsdk/ad_baseline_on.txt` |
| `sign_observer` | 签名 / 密钥观测 | MISC | false | ? | 10268 | 8/8 | **强** | 未验证 | R7 以它为主题 + 证据文件 | `work/dpsdk/token_offline_r6.txt` |
| `skip_onboarding` | 跳过首次启动引导 | HOST | false | ? | 0 | 2/2 | **强** | 未验证 | R11 以它为主题 + 证据文件 | `module/README.md`<br>`work/dpsdk/R11_skip_on.png` |
| `web_request_log` | 页面自有请求记录 | HOST | false | ? | 0 | 共享:WebInjector | **强** | 未验证 | R119 以它为主题 + 证据文件 | `work/TRIAGE.md` |
| `bridge_action_log` | 高价值桥 action 观测 | HOST | false | ? | 0 | 4/4 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `http_body_probe` | HTTP 请求/响应体观测 | HOST | false | ? | 0 | 5/5 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `log_sink` | App 日志收录 | MISC | true | ? | 3568 | 6/6 | **中** | 未验证 | 可计数记录（本轮 3568 条） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `md3_skin` | Material 3 简约皮肤 | HOST | true | ? | 0 | 2/2 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `nav_log` | 页面导航观测 | HOST | true | ? | 21 | 3/3 | **中** | 未验证 | 可计数记录（本轮 21 条） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `net_error_probe` | 网络失败原因观测 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `page_request_log` | 页面代发请求来源观测 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `parent_ctrl_probe` | 家长模式闸门观测 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `parent_ctrl_write` | 家长模式提交观测 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `popwin_gate` | 服务端弹窗总闸门 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `rc4_probe` | 解密观测 | HOST | true | ? | 1271 | 4/4 | **中** | 未验证 | 可计数记录（本轮 1271 条） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `rm_vip_promo` | 会员推广清理 | HOST | true | ? | 0 | 6/6 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `robust_probe` | 热修复补丁面观测 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `route_log` | 路由观测 | HOST | true | ? | 0 | 3/3 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `settings_entry` | 设置页 KdKit 入口 | HOST | true | ? | 0 | 2/2 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `skip_update` | 跳过强制更新 | HOST | false | ? | 0 | 2/2 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `vip_limit_probe` | 重练额度检查观测 | HOST | false | ? | 0 | 1/1 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `vip_unlock` | 会员状态解锁（客户端） | HOST | false | ? | 0 | 3/3 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `watermark_off` | 去水印（客户端开关） | HOST | false | ? | 0 | 2/2 | **中** | 未验证 | 前缀已声明、本批样本 0 条（样本可能早于该功能，见 ACTIVITY.md §四） | `kit/python/tests/fixtures/all_prefixes.txt`<br>`module/UI.md`<br>`work/dpsdk/FINDINGS.md` |
| `web_picture_watermark` | 大图浏览页水印（本地绘制） | HOST | false | ? | 0 | 2/2 | **弱** | 未验证 | 钩子目标 2/2 在 APK 中解析成功（含形参签名），但尚无真机/实验证据 | - |

**`真机` 列**：`未验证` = 本轮**没有**设备跑过这个功能。门禁能证明的是"钩得住、编译过、纯逻辑对"，不能证明"设备上行为真的变了"。

**读法**：`静态钩子` = 该功能的钩子目标在解码后的 APK 里解析成功数/总数（含形参签名，由 `check_hook_signatures.py` 给出）—— 它证明"钩得住"，**不**证明"跑起来有效"。等级只描述"我们现在能用什么证据说话"，不代表功能好坏；`弱` 的项要么补一个实验，要么承认它只能靠"安装 + 启用"作证。

### 为什么有"等级 `强`、记录数 `0`"的行

共 **16** 行是这种组合：
`anti_detect`, `block_ad_sdk`, `exit_guard`, `h5_debug`, `native_exit_guard`, `page_js`, `pk_assist`, `req_headers`, `rm_adconfig`, `rm_feed_ad`, `rm_main_banner`, `rm_popup`, `rm_splash`, `rm_tab_ad`, `skip_onboarding`, `web_request_log`。

两列回答的是**不同问题**，不矛盾：

| 列 | 回答什么 | 来源 |
|---|---|---|
| 等级 `强` | 历史上**有没有做过**以它为主题的实验 | `ROADMAP.md` 的轮次 + 落盘证据文件 |
| 记录数 `0` | **这 5 份冻结抓取里**有没有它写的行 | `work/activity_inputs/`（采样止于 2026-10-18） |

所以 `强 + 0` 的正确读法是：**实验做过（有证据文件），但这批样本里没有它的行** ——原因通常是"功能默认关"或"样本早于该功能"（见 `module/ACTIVITY.md` §四）。

**它不表示"已在真机上验证通过"。** 全表 36 行的 `真机` 列都是 `未验证` ——没有任何一行是设备上端到端跑通并前后对比过的。

