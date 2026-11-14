import java.io.File
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// ── 发布签名 ────────────────────────────────────────────────────────────────
// signing/local.properties 只在本地与 CI 临时工作区存在：仓库是 public，keystore 和密码都不进 git。
// 该文件缺失或字段不全时回退 debug 签名并打印警告，保证普通构建不会因为签名缺失而中断。
val repoRootDir: File = rootProject.projectDir.parentFile
val signingPropsFile: File = repoRootDir.resolve("signing/local.properties")

val releaseSigning: Properties? = signingPropsFile
    .takeIf { it.isFile }
    ?.let { file -> Properties().apply { file.inputStream().use { load(it) } } }
    ?.takeIf { props ->
        listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
            .all { !props.getProperty(it).isNullOrBlank() }
    }

android {
    namespace = "dev.xalor.kdkit"
    compileSdk = 37

    defaultConfig {
        applicationId = "dev.xalor.kdkit"
        minSdk = 26
        targetSdk = 36
        versionCode = 3
        versionName = "1.2.0"
    }

    buildFeatures {
        compose = true
    }

    signingConfigs {
        if (releaseSigning != null) {
            create("release") {
                val rawStorePath = releaseSigning.getProperty("storeFile").trim()
                // storeFile 支持绝对路径，也支持相对仓库根目录的路径（CI 里写成 signing/kdkit-release.jks）
                storeFile = if (rawStorePath.startsWith("/")) {
                    File(rawStorePath)
                } else {
                    repoRootDir.resolve(rawStorePath)
                }
                storePassword = releaseSigning.getProperty("storePassword")
                keyAlias = releaseSigning.getProperty("keyAlias")
                keyPassword = releaseSigning.getProperty("keyPassword")
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (releaseSigning != null) {
                signingConfig = signingConfigs.getByName("release")
            } else {
                logger.warn(
                    "WARN: 未找到可用的 ${signingPropsFile.relativeTo(repoRootDir)}（需要 storeFile/storePassword/keyAlias/keyPassword），" +
                        "release 构建回退 debug 签名的 APK —— 不是正式发布产物。"
                )
                signingConfig = signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
    packaging {
        resources.excludes += setOf("META-INF/*", "META-INF/**")
    }
    lint {
        abortOnError = false
    }
}

dependencies {
    compileOnly(files("../libs/XposedBridgeApi-82.jar"))

    testImplementation("junit:junit:4.13.2")

    // JetBrains Compose Multiplatform 依赖（Android 端映射到 androidx.compose）。
    // 不走 BOM：miuix 0.9.x 是 CMP 产物，版本必须与它声明的 CMP 对齐，
    // 否则会同时解析出两套 compose runtime（表现为 NoSuchMethodError 或静默崩溃）。
    implementation("org.jetbrains.compose.ui:ui:1.11.1")
    implementation("org.jetbrains.compose.foundation:foundation:1.11.1")
    implementation("androidx.compose.material3:material3:1.4.0")
    implementation("androidx.compose.material:material-icons-extended:1.7.3")
    implementation("androidx.compose.ui:ui-graphics:1.7.3")
    // Miuix 0.9.3（新代拆分模块）：SwitchPreference / ArrowPreference / SmallTitle /
    // TopAppBar / Scaffold / NavigationBar。需要 Kotlin 2.3.21+ 与 compileSdk 37。
    implementation("top.yukonga.miuix.kmp:miuix-ui:0.9.3")
    implementation("top.yukonga.miuix.kmp:miuix-preference:0.9.3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
}
