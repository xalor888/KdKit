# kit/harness — drive the real libbaseutil.so

`libdpsdk.so` (DProtect) kills the app on any ptrace attach, so Frida cannot
instrument `com.kuaiduizuoye.scan`. `libbaseutil.so` (the antispam/crypto
library) has no such protection, so we load it into **our own** process and call
`nativeGetSign` **by offset**（不走 JNI，也不走 `JNI_OnLoad`）。

Findings: [`../../work/native_reversal.md`](../../work/native_reversal.md)
Ground truth: [`../../work/native_groundtruth.md`](../../work/native_groundtruth.md)

```
src/com/zuoyebang/baseutil/NativeHelper.java   must keep this exact FQN —
                                               JNI_OnLoad registers onto it
src/com/zuoyebang/baseutil/Harness.java        main(): setToken → getKey → getRandom → getSign
src/com/zuoyebang/baseutil/Dump.java           in-process memory probing (Unsafe + /proc/self/maps)
```

## Build

```bash
AJ=~/Library/Android/sdk/platforms/android-36/android.jar
javac -source 8 -target 8 -bootclasspath "$AJ" -d build/classes src/com/zuoyebang/baseutil/*.java
~/Library/Android/sdk/build-tools/35.0.0/d8 --min-api 23 --output build $(find build/classes -name '*.class')
(cd build && zip -q harness.jar classes.dex)
```

## Inputs

| arg | where to get it |
|---|---|
| `libbaseutil.so` | `unzip -j <apk> lib/arm64-v8a/libbaseutil.so` |
| `signA` / `signB` | `<app>/shared_prefs/com.baidu.homework.Preference.LibPreference.xml` → `KEY_ANTISPAM_SIGN_A` / `_B` |
| `cuid` | `<app>/shared_prefs/…CommonPreference.xml` → `KEY_CUID`, normalised to `<hex>|0` |
| versionCode | `1811` |

## Run

```bash
adb push build/harness.jar /data/local/tmp/harness.jar
adb push libbaseutil.so    /data/local/tmp/libbaseutil.so

adb shell "cd /data/local/tmp && CLASSPATH=/data/local/tmp/harness.jar \
  app_process /system/bin com.zuoyebang.baseutil.Harness \
  /data/local/tmp/libbaseutil.so '<signA>' '<signB>' 1811 '<param>' '<cuid>'"
```

Prints, in order:

```
nativeSetToken(cuid=…) -> true|false
nativeGetKey(1811)     -> <128 hex chars>          <- the RC4 key
nativeGetRandom()      -> <10 chars>
nativeGetSign(<param>) -> <32 hex chars>
```

## Requirements

* the Context must report package `com.kuaiduizuoye.scan` (the library reads the
  APK signature) — handled by `ActivityThread.systemMain()` +
  `createPackageContext(...)`, needs root;
* `Looper.prepareMainLooper()` before `systemMain()`, otherwise
  `Can't create handler inside thread that has not called Looper.prepare()`;
* `cuid` must be the app's real `KEY_CUID`, otherwise `nativeSetToken` returns
  false and `nativeGetKey` yields the literal `error`.
