package dev.xalor.kdkit.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsControllerCompat
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdConfigBridge
import dev.xalor.kdkit.ui.liquidglass.LocalLiquidGlassBlur
import dev.xalor.kdkit.ui.liquidglass.LocalLiquidGlassEnabled
import dev.xalor.kdkit.ui.theme.KdTheme
import dev.xalor.kdkit.ui.theme.LocalKdDark
import dev.xalor.kdkit.ui.theme.UiPrefs
import top.yukonga.miuix.kmp.theme.MiuixTheme

/**
 * 唯一 Activity：路由（引导 / 设置 / 关于）+ 主题 + 系统栏适配。
 *
 * ### 状态栏 / 导航栏
 *
 * `enableEdgeToEdge()` 把内容铺到全屏，然后用 **`WindowInsetsControllerCompat`** 按主题
 * 切换状态栏与导航栏图标明暗（浅色主题→深色图标，深色主题→浅色图标）。
 * 每一页自己用 `statusBarsPadding()` / `navigationBarsPadding()` 让出安全区 ——
 * 之前"状态栏没适配"就是只做了前者、忘了后者。
 *
 * ### 启动速度
 *
 * `onCreate` 里只做两件事：读主题偏好、装 Compose。发布器（要扫目录、读 XML、chmod）
 * 丢到后台线程，不挡首帧。
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        // 首帧之后再做重活：KdConfig.attachApp 只读一个 SharedPreferences（快），
        // 发布器要扫目录 + 读写文件（慢），放到后台线程。
        runCatching { KdConfig.attachApp(applicationContext) }
        Thread({
            runCatching { KdConfigBridge.startPublisher() }
        }, "kdkit-publisher").start()

        setContent {
            val ctx = LocalContext.current
            var mode by remember { mutableStateOf(UiPrefs.theme(ctx)) }
            var glass by remember { mutableStateOf(UiPrefs.glass(ctx)) }
            var oobeDone by remember { mutableStateOf(UiPrefs.oobeDone(ctx)) }
            var about by remember { mutableStateOf(false) }

            KdTheme(themeMode = mode) {
                val dark = LocalKdDark.current
                // 系统栏图标明暗跟随主题；每次主题切换都会重新执行
                SideEffect { applyBarIcons(dark) }

                CompositionLocalProvider(
                    LocalLiquidGlassEnabled provides glass,
                    LocalLiquidGlassBlur provides 1f,
                ) {
                    val page: @Composable () -> Unit = {
                        when {
                            !oobeDone -> OobeFlow(onDone = { oobeDone = true })
                            about -> AboutPage(
                                onBack = { about = false },
                                onReplayOobe = {
                                    UiPrefs.resetOobe(ctx)
                                    about = false
                                    oobeDone = false
                                },
                            )
                            else -> SettingsScreen(
                                mode = mode,
                                onCycleTheme = {
                                    val next = UiPrefs.next(ctx)
                                    UiPrefs.setTheme(ctx, next)
                                    mode = next
                                },
                                onOpenAbout = { about = true },
                            )
                        }
                    }
                    // 根节点不再套 graphicsLayer：全屏 RenderNode + 小米窗口打开模糊
                    // 会在 libhwui 的 MiBackgroundBlurBlend 里崩（见 LiquidGlassMaterial.kt）。
                    Box(Modifier.fillMaxSize()) {
                        Box(Modifier.fillMaxSize().background(MiuixTheme.colorScheme.background)) { page() }
                    }
                }
            }
        }
    }

    /** 浅色主题 → 深色图标；深色主题 → 浅色图标。 */
    private fun applyBarIcons(dark: Boolean) {
        val w = window ?: return
        val c = WindowInsetsControllerCompat(w, w.decorView)
        c.isAppearanceLightStatusBars = !dark
        c.isAppearanceLightNavigationBars = !dark
        WindowCompat.getInsetsController(w, w.decorView).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }
}
