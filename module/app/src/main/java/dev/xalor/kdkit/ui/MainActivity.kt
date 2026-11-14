package dev.xalor.kdkit.ui

import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.PredictiveBackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdConfigBridge
import dev.xalor.kdkit.ui.theme.KdTheme
import dev.xalor.kdkit.ui.theme.UiPrefs
import dev.xalor.kdkit.ui.theme.glassCapable

/**
 * 唯一 Activity：只做路由（引导 / 设置 / 关于）、主题、返回手势。
 *
 * 玻璃能力在这里算一次并往下传：`glassCapable()` 为假（模拟器、无 RuntimeShader 的设备）时
 * 一切玻璃渲染通道都不碰 —— glasmio-glass 的 native 路径在这些机器上会 SIGSEGV。
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
            // 能力判断 + 自愈：上次切液态界面崩过，就永久降级（UiPrefs.glassBroken 会顺手落盘）
            val broken = remember { UiPrefs.glassBroken(ctx) }
            val capable = glassCapable() && !broken
            val glassUsable = glass && capable

            PredictiveBackHandler(enabled = true) { progress ->
                runCatching { progress.collect { backProgress = it.progress } }
                backProgress = 0f
                finish()
            }
            val scale by animateFloatAsState(1f - 0.05f * backProgress, label = "back")

            KdTheme(themeMode = mode, glass = glassUsable) {
                Box(
                    Modifier.fillMaxSize().graphicsLayer {
                        scaleX = scale; scaleY = scale
                        alpha = 1f - 0.16f * backProgress
                    },
                ) {
                    when {
                        // 关于/更新页排在降级判断之前 —— 否则 !capable 分支永远先命中，点「关于」没反应
                        !capable && about -> LegacyAbout(onBack = { about = false })
                        Build.VERSION.SDK_INT < 33 -> LegacyPage(
                            mode = mode, glass = glassUsable,
                            onCycleTheme = {
                                val next = UiPrefs.next(ctx); UiPrefs.setTheme(ctx, next); mode = next
                            },
                            onToggleGlass = { val on = !glass; UiPrefs.setGlass(ctx, on); glass = on },
                            onOpenAbout = { about = true },
                        )
                        !capable -> LegacyPage(
                            mode = mode, glass = glassUsable,
                            onCycleTheme = {
                                val next = UiPrefs.next(ctx); UiPrefs.setTheme(ctx, next); mode = next
                            },
                            onToggleGlass = { val on = !glass; UiPrefs.setGlass(ctx, on); glass = on },
                            onOpenAbout = { about = true },
                        )
                        !oobeDone -> GlasmioGate(
                            { UiPrefs.markGlassPending(ctx) },
                            { UiPrefs.confirmGlass(ctx) },
                        ) {
                            OobeFlow(glass = glassUsable, onDone = { oobeDone = true })
                        }
                        about -> GlasmioGate(
                            { UiPrefs.markGlassPending(ctx) },
                            { UiPrefs.confirmGlass(ctx) },
                        ) { AboutPage(onBack = { about = false }, glass = glassUsable) }
                        else -> GlasmioGate(
                            { UiPrefs.markGlassPending(ctx) },
                            { UiPrefs.confirmGlass(ctx) },
                        ) {
                        SettingsPage(
                            mode = mode, glass = glassUsable,
                            onCycleTheme = {
                                val next = UiPrefs.next(ctx); UiPrefs.setTheme(ctx, next); mode = next
                            },
                            onToggleGlass = { val on = !glass; UiPrefs.setGlass(ctx, on); glass = on },
                            onOpenAbout = { about = true },
                        )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 液态界面护栏：进页面先落 `pending`，等真正画出两帧再落 `ok`。
 *
 * 下一次启动如果 `pending` 还在（说明上次正是在这里死掉的），[UiPrefs.glassBroken]
 * 会把它判成 `broken`，于是这台机器以后都走普通界面 —— 用户不需要手动处理。
 *
 * 为什么是"两帧"：Compose 的第一帧只做测量/布局，真正提交到 RenderThread 的是下一帧；
 * native 崩溃几乎都发生在提交阶段，所以必须等到第二帧再确认。
 */
@Composable
private fun GlasmioGate(
    onPending: () -> Unit,
    onConfirmed: () -> Unit,
    content: @Composable () -> Unit,
) {
    LaunchedEffect(onPending) { onPending() }
    LaunchedEffect(Unit) {
        withFrameNanos { }
        withFrameNanos { }
        onConfirmed()
    }
    content()
}
