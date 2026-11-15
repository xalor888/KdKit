# 提交到 LSPosed 官方模块仓库（Xposed-Modules-Repo）

> 说明：仓库里的 `docs/repo.json` / `docs/modules.json` 是**自建仓库**，
> 谁都能在 LSPosed 里手动填 `https://xalor888.github.io/KdKit/repo.json` 添加，
> **不需要审核**。而「官方模块库」（`modules.lsposed.org`，在 LSPosed 管理器里默认
> 就能搜到的那个列表）**要审核**，流程如下。

## 一、官方仓库的硬性要求

来源：<https://github.com/Xposed-Modules-Repo> 的 README

| 要求 | 我们是否满足 |
|---|---|
| 仓库名 = 模块包名 | `dev.xalor.kdkit` ✅ |
| 仓库必须有非空 description，作为模块显示名 | 提交时填 `KdKit` |
| 至少一个**有效 release** | 发版即可 |
| release 的 tag 必须是 `VersionCode-VersionName` | 当前是 `v1.4.2`，**需要改成 `10-1.4.2`**（见下） |
| release 里至少一个 `.apk` 资产 | ✅ `KdKit-v1.4.2.apk` |

## 二、提交入口

1. 打开 <https://modules.lsposed.org/submission>
2. 选 **Submit a new package**，它会预填一个 issue 到
   <https://github.com/Xposed-Modules-Repo/submission>
3. 填的内容（可直接复制）：

```
Package name: dev.xalor.kdkit
Module name: KdKit
Description: 快对（com.kuaiduizuoye.scan）的去广告 / 界面 / 稳定性增强模块：
             去掉开屏、横幅、页签、弹窗、信息流与会员推销，统一 Material 3 界面
Source code: https://github.com/xalor888/KdKit
License: MIT
```

4. 提交后**等人工/机器人审核**（这一步我做不了，只能你去点，而且必须用你的 GitHub 账号）。

## 三、审核通过后

机器人会在 `Xposed-Modules-Repo` 组织下建一个 `dev.xalor.kdkit` 仓库，
之后**发版要发到那个仓库**（不是个人仓库），并且 tag 用 `版本号-版本名`：

```bash
# 在那个由机器人创建的仓库里
git tag 10-1.4.2
git push origin 10-1.4.2
gh release create 10-1.4.2 KdKit-v1.4.2.apk \
  --title "1.4.2" --notes "…"
```

机器人会读 release 的 tag 与 APK 资产来更新模块详情页。
**注意**：只改 release 资产不会触发机器人，必须动 release 本身（改标题/说明都行）。

## 四、为什么我们不写 `META-INF/xposed/*`

本模块是**经典 Xposed 模块**：入口 `dev.xalor.kdkit.KdEntry` 实现
`de.robv.android.xposed.IXposedHookLoadPackage`，靠 `assets/xposed_init` 声明入口。

`META-INF/xposed/java_init.list` 的存在会被框架判定为「现代 libxposed 模块」，
而现代模块要求入口实现 libxposed 的 `XposedModule`。我们放个 legacy 类进去，
只会让框架按现代路径加载然后静默跳过 —— 表现就是"装上了但不起作用"。
所以这两个文件刻意不加，保持 legacy 路径。
（`scope.list` 也一并去掉了，避免误导；作用域在管理器里手动勾 `com.kuaiduizuoye.scan`。）
