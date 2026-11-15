package dev.xalor.kdkit.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.PredictiveBackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdConfigBridge
import dev.xalor.kdkit.ui.liquidglass.LocalLiquidGlassBlur
import dev.xalor.kdkit.ui.liquidglass.LocalLiquidGlassEnabled
import dev.xalor.kdkit.ui.theme.KdTheme
import dev.xalor.kdkit.ui.theme.UiPrefs
import top.yukonga.miuix.kmp.theme.MiuixTheme

/**
 * 唯一 Activity：路由（引导 / 设置 / 关于）+ 主题 + 液态玻璃的 backdrop 提供者。
 *
 * ### backdrop 接法（照本地 murexide-plus 的 `Theme.kt`）
 *
 * ```
 * val backdrop = rememberLayerBackdrop()
 * Box {
 *   Box(layerBackdrop(backdrop)) { page }   // 页面被记录成"可采样背景"
 *   dock(backdrop)                          // 玻璃在采样层之外 → 采到的是上面的列表
 * }
 * ```
 *
 * 玻璃**不能**放进它采样的那一层（自己采样自己 → 发黑/闪烁），这是 Kyant 那套的硬约束。
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        runCatching { KdConfig.attachApp(applicationContext) }
        runCatching { KdConfigBridge.startPublisher() }

        setContent {
            val ctx = LocalContext.current
            var mode by remember { mutableStateOf(UiPrefs.theme(ctx)) }
            var glass by remember { mutableStateOf(UiPrefs.glass(ctx)) }
            var oobeDone by remember { mutableStateOf(UiPrefs.oobeDone(ctx)) }
            var about by remember { mutableStateOf(false) }
            var backProgress by remember { mutableFloatStateOf(0f) }

            PredictiveBackHandler(enabled = true) { progress ->
                runCatching { progress.collect { backProgress = it.progress } }
                backProgress = 0f
                finish()
            }
            val scale by animateFloatAsState(1f - 0.04f * backProgress, label = "back")

            KdTheme(themeMode = mode) {
                CompositionLocalProvider(
                    LocalLiquidGlassEnabled provides glass,
                    LocalLiquidGlassBlur provides 1f,
                ) {
                    val page: @Composable () -> Unit = {
                        when {
                            !oobeDone -> OobeFlow(onDone = { oobeDone = true })
                            about -> AboutPage(onBack = { about = false })
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
                    // 根节点不再套 graphicsLayer：全屏 RenderNode + 小米的窗口打开模糊
                    // 会在 libhwui 的 MiBackgroundBlurBlend 里崩（见 LiquidGlassMaterial.kt）。
                    // 返回手势的形变改由内容层自己在内部处理（页面级 scale 已足够）。
                    Box(Modifier.fillMaxSize()) {
                        Box(Modifier.fillMaxSize().background(MiuixTheme.colorScheme.background)) { page() }
                    }
                }
            }
        }
    }
}

