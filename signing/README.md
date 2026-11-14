# 正式签名（release signing）

本目录是 KdKit 的正式（release）签名材料说明。**仓库是 public：keystore 本体与密码都不进 git。**

## 1. keystore 事实

| 项 | 值 |
|---|---|
| 路径（本地） | `signing/kdkit-release.jks` |
| 入库状态 | 被 `.gitignore` 排除（`signing/*`，仅放行 `README.md` 与 `release-keystore.sha256`） |
| 别名 | `kdkit` |
| 密钥库类型 | PKCS12 |
| 密钥算法 | RSA 4096，`SHA384withRSA` |
| 主体 DN | `CN=KdKit, O=xalor, C=CN` |
| 有效期 | 10,000 天（2026-11-14 → 2054-04-01） |
| 文件 SHA-256 | `291ae88046b9a6ff0cffc6a981a62500a867464a65f05333f05ddad8f6b6b8b4` |
| 证书 SHA-256 | `31fcbb1b32e019954b8d80f5837d64b8c15f1f78eaeba3400970c5092050cf37` |
| 证书 SHA-1 | `8ff210972acfc207a36ae964c98c1de2a81220ae` |
| 公钥 SHA-256 | `ee17247fd96bd153a9c0be2aa1bab608440d401d6a1d318cad9ac0fbe0ab262c` |

文件指纹同时写在 [`release-keystore.sha256`](release-keystore.sha256)（`sha256sum` 原生格式，内容为 `291ae8…b8b4  kdkit-release.jks`）。CI 在还原 keystore 后立刻 `shasum -c` 校验：还原成别的 keystore 会直接失败，不会静默签出错误产物（本地已实测 `kdkit-release.jks: OK`）。

## 2. 密码放在哪里（为什么不写在本文里）

密码是随机生成的 **24 位** 字母数字串，只存在于两处：

1. 本地 `signing/local.properties`（已被 `.gitignore` 排除；`local.properties` 本身也在忽略列表里）；
2. GitHub Actions Secrets：`KEYSTORE_BASE64` / `KEYSTORE_PASSWORD` / `KEY_ALIAS` / `KEY_PASSWORD`。

本地取用：

```bash
sed -n 's/^storePassword=//p' signing/local.properties
```

**本文没有收录明文密码，这是刻意的**：README 会进 public 仓库的 git 历史。一旦密码与 keystore 一起公开，任何拿到 keystore（本机副本、备份、CI 残留）的人都能签出被系统视为同一发布者的更新包 —— 密码泄露使 keystore 失去全部意义。密码与密钥必须分开保管，所以明文只留在被忽略的文件和 Secrets 里。

### 轮换建议

本仓库 public、CI 又会解出 keystore，因此把它当"可轮换的发布身份"而不是长期机密：

```bash
# 1) 生成新键（同样 4096/10000 天/同 DN）
/opt/homebrew/opt/openjdk@21/bin/keytool -genkeypair -keyalg RSA -keysize 4096 -validity 10000 \
  -alias kdkit -dname "CN=KdKit,O=xalor,C=CN" -storetype PKCS12 \
  -keystore signing/kdkit-release.jks -storepass "$NEW_PW" -keypass "$NEW_PW"
# 2) 更新 signing/local.properties 与 4 个 secret，重算 release-keystore.sha256 并提交
printf '%s  kdkit-release.jks\n' "$(shasum -a 256 signing/kdkit-release.jks | awk '{print $1}')" > signing/release-keystore.sha256
gh secret set KEYSTORE_BASE64   -R xalor888/KdKit < <(base64 -i signing/kdkit-release.jks | tr -d '\n')
gh secret set KEYSTORE_PASSWORD -R xalor888/KdKit --body "$NEW_PW"
gh secret set KEY_PASSWORD      -R xalor888/KdKit --body "$NEW_PW"
```

注意：换 key 后**已装机用户无法覆盖安装**（Android 拒绝签名不同的同包名 APK），需要卸载重装；因此只在泄露或轮换窗口才换。

`.gitignore` 里新增的规则：

```gitignore
signing/*
!signing/README.md
!signing/release-keystore.sha256
```

## 3. keystore 可用性验证（重签既有 debug 包）

用 `apksigner` 36.0.0 对 `module/app/build/outputs/apk/debug/app-debug.apk` 做 zipalign + 重签，产物 `module/app/build/outputs/apk/verify/app-resigned.apk`：

```
Verifies
Verified using v1 scheme (JAR signing): false
Verified using v2 scheme (APK Signature Scheme v2): true
Verified using v3 scheme (APK Signature Scheme v3): true
Number of signers: 1
Signer #1 certificate DN: CN=KdKit, O=xalor, C=CN
Signer #1 certificate SHA-256 digest: 31fcbb1b32e019954b8d80f5837d64b8c15f1f78eaeba3400970c5092050cf37
Signer #1 key algorithm: RSA
Signer #1 key size (bits): 4096
```

（v1 关闭、v2/v3 开启：minSdk 26，v2 已覆盖全部目标设备。）

## 4. 本地 release 构建验证

`module/app/build.gradle.kts` 里 `signingConfigs.release` 从本文件同目录的 `local.properties` 读取四项；路径支持绝对路径或"相对仓库根目录"。

```properties
storeFile=signing/kdkit-release.jks
storePassword=＜24 位密码＞
keyAlias=kdkit
keyPassword=＜24 位密码＞
```

`./gradlew assembleRelease`（JDK 21 / Gradle 8.14.5）实际结果：

```
> Task :app:validateSigningRelease
> Task :app:packageRelease
> Task :app:assembleRelease
BUILD SUCCESSFUL

$ apksigner verify --print-certs module/app/build/outputs/apk/release/app-release.apk
Signer #1 certificate DN: CN=KdKit, O=xalor, C=CN
Signer #1 certificate SHA-256 digest: 31fcbb1b32e019954b8d80f5837d64b8c15f1f78eaeba3400970c5092050cf37
```

产物：`module/app/build/outputs/apk/release/app-release.apk`，`sha256 99b02f877aed3087270f6028bdb917f59e204bdf1dc3c7c96162b53713c347ac`（本地构建，每次构建会变）。

缺失 `signing/local.properties` 时的回退（已实测）：

```
WARN: 未找到可用的 signing/local.properties（需要 storeFile/storePassword/keyAlias/keyPassword），release 构建回退 debug 签名的 APK —— 不是正式发布产物。
```

即本地无签名材料也能构建，但产物是 debug 签名，**不可用于发布**；CI 端 `assembleRelease` 之后有一步 `apksigner verify` 断言 `CN=KdKit` 与证书 SHA-256，回退成 debug 签名会让发布直接失败。

## 5. CI（`.github/workflows/release.yml`）

打 `v*` tag（或手动 `workflow_dispatch`）时：checkout → JDK 21 → `gradle/actions/setup-gradle` → `base64 -d` 还原 `signing/kdkit-release.jks` 并 `sha256sum -c` → 写 `signing/local.properties` → 单测 → `assembleRelease` → 校验签名 → 重命名 `KdKit-<tag>.apk`（附 `.sha256`）→ `softprops/action-gh-release` 发布。

Secrets 清单（已用 `gh secret set` 写入仓库）：

| Secret | 内容 |
|---|---|
| `KEYSTORE_BASE64` | `base64 -i signing/kdkit-release.jks \| tr -d '\n'`（5704 字节单行） |
| `KEYSTORE_PASSWORD` | keystore 口令（24 位） |
| `KEY_ALIAS` | `kdkit` |
| `KEY_PASSWORD` | key 口令（与 keystore 口令相同） |

`ci.yml` 保持原样：push/PR 只跑单测 + `assembleDebug`，不碰签名材料。

## 6. 首次 tag 发布验证（v1.2.1）

- 工作流运行：Release #43559855685（tag `v1.2.1`，commit `e06ca04`），结论 **success**，步骤 `Restore release keystore` → `Build release APK (release signing)` → `Verify release signature` → `Publish release` 全绿。
- Release：<https://github.com/xalor888/KdKit/releases/tag/v1.2.1>
- 附件：`KdKit-v1.2.1.apk`（10,792,543 B）+ `KdKit-v1.2.1.apk.sha256`
- 下载后复验（本机 apksigner 36.0.0）：

```
$ shasum -a 256 -c KdKit-v1.2.1.apk.sha256
KdKit-v1.2.1.apk: OK
$ apksigner verify --print-certs KdKit-v1.2.1.apk
Signer #1 certificate DN: CN=KdKit, O=xalor, C=CN
Signer #1 certificate SHA-256 digest: 31fcbb1b32e019954b8d80f5837d64b8c15f1f78eaeba3400970c5092050cf37
```

即 tag 发布包与本地 `assembleRelease` 产物使用同一把发布证书；`cn=KdKit` 断言让它不可能悄悄退回 debug 签名。
