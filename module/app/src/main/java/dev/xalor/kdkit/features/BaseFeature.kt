package dev.xalor.kdkit.features

import dev.xalor.kdkit.features.web.WebInjector
import dev.xalor.kdkit.config.KdConfig
import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.util.HookAudit
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.Xp

/** Category ids shown in the settings UI. */
object Category {
    const val ADS = "ads"
    const val PK = "pk"
    const val HOST = "host"
    const val MISC = "misc"
}

/**
 * A user-toggleable behaviour. [id] is the config key and must stay stable forever.
 *
 * 范式约定（KDKit / BCZKit 共用，见 module/PARADIGM.md）：
 *  - `id` 是持久化 key，改名等于丢掉用户开关，永不修改；
 *  - `title` / `summary` / `category` 是设置页的唯一展示来源，文档表格由脚本对齐；
 *  - [install] 只能安装钩子，**不要**在这里读文件/发网络/等锁；失败必须抛出，由 [enable] 兜底；
 *  - [enable] 是幂等的：同一进程内重复调用只安装一次（HookCore 可能被多处触发）；
 *  - [options] 声明本功能读的**所有**非开关键，否则门禁会把它算成"幽灵键"。
 *
 * ### 2026-10-25：钩子常驻 + 调用点门控（热开关）
 *
 * 旧语义是"关着就不装钩子"，而钩子只在进程启动时装一次 ⇒ 改开关必须**重启宿主**。
 * 现在 [hot] 为 true 的功能，钩子**始终安装**，回调在调用点用
 * `Xp.hook(..., gate = id)` 先问配置 ⇒ 关闭即"回调不执行、原方法照跑"，
 * 开启即时生效，不必重启。默认值仍是 `hot = false`（保守），逐个功能验证后再打开。
 */
abstract class BaseFeature(
    val id: String,
    val title: String,
    val summary: String,
    val category: String,
    val defaultOn: Boolean = true,
    /** 钩子常驻、开关在调用点判定（可热切换，无需重启宿主）。 */
    val hot: Boolean = false,
) {
    @Volatile
    private var installed = false

    /** 是否已成功安装（供诊断/测试读取）。 */
    val isInstalled: Boolean
        get() = installed

    /** 本功能读写的非开关配置项（设置页据此渲染，门禁据此校验）。 */
    open val options: List<KdOption> = emptyList()

    /** True when the feature should be active in this process. */
    open fun shouldRun(): Boolean = KdConfig.isOn(id, defaultOn)

    /** Install hooks. Called at most once per host process. */
    abstract fun install()

    /**
     * 安装入口：关闭时跳过、已安装时跳过、失败只记录不抛出。
     * `@Synchronized` 保证并发重复调用（诊断页/重入）不会装两遍钩子。
     *
     * [hot] 功能即使关闭也会安装（见类注释），因此这里的 `shouldRun()` 只决定
     * "冷功能"是否安装。
     */
    @Synchronized
    fun enable() {
        if (installed) {
            KdLog.d("feature already installed: $id")
            return
        }
        if (!hot && !shouldRun()) {
            KdLog.d("feature off: $id")
            return
        }
        try {
            Xp.under(id) { install() }
            installed = true
            val (ok, failed) = HookAudit.perFeature()[id] ?: (0 to 0)
            // **注册型功能没有钩子，这是对的**（2026-11-03 修）。
            //
            // 旧判据只看 `ok == 0`，于是 `pk_assist` / `h5_debug` / `page_js`
            // 这些"只往 WebInjector 注册一个 provider"的功能**每轮都被点名**：
            // 实测 32 次 `feature hot but installed no hooks`，其中绝大多数是注册型。
            //
            // 一条在正确代码上也响的警告，比没有警告更糟 —— 它训练人忽略这一行，
            // 而真正"挂了 0 条钩子"的功能（`exit_guard` 2026-11-03 之前就是）会被一起忽略。
            //
            // 现在：注册型功能按 `WebInjector.providerNames()` 对账，
            // 那条路径也有自己的可见结论（provider 注册了几个）。
            val registered = WebInjector.providerNames().size
            if (hot && ok == 0 && registered == 0) {
                KdLog.w("feature hot but installed no hooks and registered no provider: $id")
            }
            KdLog.i("feature on: $id (hooks $ok ok / $failed failed${if (hot) ", hot" else ""})")
        } catch (t: Throwable) {
            KdLog.e("feature failed: $id", t)
        }
    }
}

/** Simple on/off feature. */
abstract class SwitchFeature(
    id: String,
    title: String,
    summary: String,
    category: String,
    defaultOn: Boolean = true,
    hot: Boolean = false,
) : BaseFeature(id, title, summary, category, defaultOn, hot)
