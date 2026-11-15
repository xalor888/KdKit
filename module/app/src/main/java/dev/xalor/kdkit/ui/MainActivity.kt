package dev.xalor.kdkit.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.PredictiveBackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
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
import dev.xalor.kdkit.ui.theme.KdTheme
import dev.xalor.kdkit.ui.theme.UiPrefs

/**
 * 唯一 Activity：路由（引导 / 设置 / 关于）+ 主题 + 返回手势。
 *
 * 这里没有任何"玻璃能力"判断 —— 界面已经不依赖第三方渲染（Glasmio 那套在模拟器上
 * SIGSEGV、在真机上整页白屏，两次跨设备验证都失败，已整体移除）。
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        runCatching { KdConfig.attachApp(applicationContext) }
        runCatching { KdConfigBridge.startPublisher() }

        setContent {
            val ctx = LocalContext.current
            var mode by remember { mutableStateOf(UiPrefs.theme(ctx)) }
            var oobeDone by remember { mutableStateOf(UiPrefs.oobeDone(ctx)) }
            var about by remember { mutableStateOf(false) }
            var backProgress by remember { mutableFloatStateOf(0f) }

            PredictiveBackHandler(enabled = true) { progress ->
                runCatching { progress.collect { backProgress = it.progress } }
                backProgress = 0f
                finish()
            }
            val scale by animateFloatAsState(1f - 0.05f * backProgress, label = "back")

            KdTheme(themeMode = mode) {
                Box(Modifier.fillMaxSize().graphicsLayer {
                    scaleX = scale; scaleY = scale; alpha = 1f - 0.16f * backProgress
                }) {
                    when {
                        !oobeDone -> OobeFlow(onDone = { oobeDone = true })
                        about -> AboutPage(onBack = { about = false })
                        else -> SettingsScreen(
                            mode = mode,
                            onCycleTheme = {
                                val next = UiPrefs.next(ctx); UiPrefs.setTheme(ctx, next); mode = next
                            },
                            onOpenAbout = { about = true },
                        )
                    }
                }
            }
        }
    }
}
