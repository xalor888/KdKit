# APK 逆向作业规范（对齐 `apk-reverse` skill，2026-10-12）

本机工具链（实测 ✓）：

| 工具 | 本机版本 | skill 记录 | 备注 |
|---|---|---|---|
| `jadx` | **1.5.6** ✓ | 1.5.5 | 更新 ✓ |
| `apktool` | **3.0.3** ✓ | 3.0.2 | 更新 ✓ |
| `java` | OpenJDK **21** ✓ | — | |
| `frida-ps` | **17.23.3** ✓ | 17.9.6 | 更新 ✓ |
| `adb` | ✓（在 `$HOME/Library/Android/sdk/platform-tools/` ✓）| — | **不在 PATH 里** ✗ ⇒ 脚本里一律写全路径 ✓ |

## 与 skill 一致的（本项目已在做 ✓）

* **Triage 顺序**：先看 `AndroidManifest.xml` ✓、主 `package` ✓、入口组件 ✓、`lib/` 里有没有 `.so` ✓（`work/apktool_out/` ✓）；
* **工具分工**：`jadx` 读 Java ✓、`apktool` 看 smali/资源 ✓、`.so` 分流到 `radare2`/IDA ✓；
* **"禁止事项"四条** ✓：不盲目改 smali ✓、不先写 Hook 再看 manifest ✓、
  不把"反编译不完整"当成"逻辑不可分析" ✓、`.so` 明显承载核心逻辑时**不死磕 Java** ✓
  —— 本项目的 `.so`（`libdpsdk.so` ✓）正属最后一条 ✓（OLLVM 加固 ✓，已在 `DECISIONS` 里记为**不做函数级映射** ✓）。

## 与本项目的**三处刻意偏离**（都有理由 ✓）

1. **不用 Frida** ✗ —— skill 建议它做动态 Hook ✓，但本项目的设备**在 attach 时会自杀** ✗
   （native 反调试 ✓）。⇒ 动态观察**一律走 Xposed 模块** ✓（`module/` ✓）。
2. **不重打包 / 不重签名** ✗ —— skill 给了 `rebuild-sign-install` 流程 ✓，但本项目的
   **证书 + 设备绑定 token** ✓ 决定了重打包会破坏可复现性 ✗（见 `DECISIONS` ✓）。
3. **不做全量 `jadx -d`** ✗ —— 50 MB / 7 dex ✓；本项目改用
   **smali 定向读 ✓ + dex 字符串枚举 ✓**（`work/versions/strings/` ✓）——
   同样的"先高层后细节" ✓，但更省时间 ✓。

## skill 里值得补用的两点（已采纳 ✓）

* `jadx --single-class <类> -d out <apk>` ✓ —— **定向读单个类**，比全量便宜 ✓；
* `jadx --deobf` ✓ —— 混淆名还原 ✓（本项目目前主要靠 smali + 字符串 ✓，需要时可加 ✓）。

## 交付口径（skill 的"输出要求" ✓ 本项目已满足 ✓）

入口组件与关键类 ✓ / 关键逻辑在哪一层（Java ✓ / smali ✓ / `.so` ✓）/ 敏感点
（登录 ✓、签名 ✓、root ✓、SSL ✓、WebView ✓、JNI ✓）/ 改过什么 ✓ / Hook 了哪个类与方法 ✓
—— 对应 `REPORT.md` 的 §2（协议）✓、§4（接口面）✓、§5（数据流）✓ 与模块的 `VERIFICATION.md` ✓。
