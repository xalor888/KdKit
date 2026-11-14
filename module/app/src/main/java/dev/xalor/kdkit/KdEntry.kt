package dev.xalor.kdkit

import de.robv.android.xposed.IXposedHookLoadPackage
import de.robv.android.xposed.XC_MethodHook
import de.robv.android.xposed.XposedBridge
import de.robv.android.xposed.callbacks.XC_LoadPackage
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/**
 * Xposed entry point.
 *
 * `handleLoadPackage` is called from `Instrumentation.newApplication`, i.e. *after*
 * `Application.attachBaseContext` has already executed, so hooking that method never fires.
 * The host ClassLoader is complete by this point and the module's hooks land well before the
 * app touches ads or creates a WebView, so we initialise immediately.
 */
class KdEntry : IXposedHookLoadPackage {

    override fun handleLoadPackage(lpparam: XC_LoadPackage.LoadPackageParam) {
        when (lpparam.packageName) {
            TARGET -> {
                KdLog.i("injected: ${lpparam.processName} (first=${lpparam.isFirstApplication})")
                Xp.classLoader = lpparam.classLoader
                HookCore.start(lpparam.classLoader, null, lpparam.processName)
            }
            // The framework also injects this module into its own settings app so the two sides
            // can share preferences. Publish the app's flags into the framework directory so the
            // hooked host (which cannot read another app's private dir) sees them.
            MODULE -> {
                // The framework injects this module into its own settings app too. The settings
                // app cannot reach the daemon-owned publish directory itself (per-app mount
                // namespaces) and the host cannot read the app's private dir, so mirror the app's
                // flags into the framework-published file from here.
                KdLog.d("module app process: starting prefs publisher")
                runCatching {
                    XposedBridge.hookAllMethods(
                        lpparam.classLoader.loadClass("android.app.Application"),
                        "onCreate",
                        object : XC_MethodHook() {
                            override fun afterHookedMethod(param: MethodHookParam) {
                                runCatching { dev.xalor.kdkit.config.KdConfigBridge.startPublisher() }
                                    .onFailure { KdLog.e("publisher failed", it) }
                            }
                        },
                    )
                }.onFailure { KdLog.e("publisher hook failed", it) }
            }
        }
    }

    private companion object {
        const val TARGET = "com.kuaiduizuoye.scan"
        const val MODULE = "dev.xalor.kdkit"
    }
}
