package dev.xalor.kdkit

import de.robv.android.xposed.XposedHelpers
import dev.xalor.kdkit.util.Xp

/**
 * 宿主**混淆名映射** —— 一份模块源码，同时钩住两个混淆映射完全不同的快对。
 *
 * ### 为什么需要它（而不是把类名改成新的）
 *
 * 整套钩子建立在 **7.10.2 / 1860** 的混淆名上。内测包 **6.21.11 / 1865** 的 R8 映射是
 * 另一套：同一个原始类拿到的短名不同（`di.a` 在 1865 里变成了**另一个类**）。
 * 所以"把旧名直接替换成新名"会立刻打断 7.10.2 —— 那才是主基线。
 *
 * 正确做法是**保留基线字面量**（调用点仍写基线名 `"di.a"` + 方法名 `"d"`，静态门禁与文档
 * 都按基线名对齐），由本表在**运行时**把逻辑目标翻译成当前宿主的那一侧；钩子安装处则由
 * [Xp] 依次尝试候选名（见 `Xp.candidates`），所以"名字变了"退化成"换一个候选"，
 * 而不是"静默失效"。
 *
 * ### 表怎么读
 *
 * 三个名字：**逻辑 id**（稳定、与混淆无关，日志/文档用它）、**基线名**、**1865 名**。
 * 每一条都是实测出来的**等价类**，不是猜的（`work/compat1865/ADS.md` 有逐条证据）：
 *
 * | id | 7.10.2 / 1860 | 6.21.11 / 1865 | 判定依据 |
 * |---|---|---|---|
 * | `ads.splash` | `dj.a` | `bj.a` | 12 个方法**逐条描述符相同**、字段相同（`a/b/c/d` + `changeQuickRedirect`）、`j(Activity)`/`k()Z`/`g()Z` 同形；全 APK 调用数逐方法相同（1/1/1） |
 * | `ads.slot` | `di.a` | `bi.a` | 12 个方法逐条描述符相同（`d(I)`/`f(I)`/`h(I)` 返回 `InitAdConfig$ListItem$AdlistItem`，`j()Z`/`k()Z`）；调用数相同（`d` 12 / `j` 22 / `l` 18 / `f` 4 / `h` 4） |
 * | `ads.popup.showArg` | `fh.a` | `dh.a` | 3 个抽象方法完全相同（`a(String)`/`b(String)`/`c()Z`），`PopupAdvertisementDialog.g` 的第二个形参就是它 |
 * | `crypto` | `vm.g` | `tm.g` | 28 个方法逐条描述符相同（`h(String)`/`i(String)`/`k(Object)`/`t(Object,Z)`/`o`/`p`/`u`/`z()`）、字段相同（`d` 单例 / `a` 队列 / `b` 密钥 / `c`）；16 条 `RC4Helper` 字符串相同（`updateKey()  key : `、`RC4_DECRYPT_ERROR`） |
 *
 * 宿主角（`features/host/` 下的功能，逐条证据与两棵树的门禁输出在 `work/compat1865/HOST.md`）：
 *
 * | id | 7.10.2 / 1860 | 6.21.11 / 1865 | 判定依据 |
 * |---|---|---|---|
 * | `host.popwin` | `hh.y` | `fh.y` | 39 个方法逐条同名；10 个 `win*` 串同一行（`winVIPBottom` `:1520`）；`F()` 的销售页 URL `:898`；整文件 diff 只有 `.field h` 与内部类自引用 |
 * | `host.updateModel` | `um.z2` | `sm.z2` | 24 个方法逐条同名（唯一差异 `t()` 的 `fh/a→dh/a`）；`k(CheckAppUpdate)` `:248` 同号 |
 * | `host.parentmode` | `ul.b` | `sl.b` | 17 个方法逐条同名（唯一差异是 synthetic bridge 的首参）；`KdcoreUserSetParentMode` 唯一引用者 `$b` 同一行号组 |
 * | `host.pagehelper` | `ps.f` | `ns.f` | 19 个方法逐条同名；`a(...)` `:30` 同号；3 处调用点同文件同行（`EncryptDataRequestAction:190` / `CoreHttpRequestAction:905,960`） |
 * | `host.pagehelper.cb` | `ps.f$e` | `ns.f$e` | 同上（`a`/`b` 的首参接口） |
 * | `host.bodyClass` | `kl.a` | `il.a` | `:1524` 同一条指令 `HWRequest.getBody()[B`；19 个方法逐条同名；`.super Lcom/android/volley/d;` 同 |
 * | `host.antidetect` | `dj.f` | `bj.f` | 4 个方法逐条同名；`TracerPid` `:413` 同号；diff 只有 4 个 `const/16` 平移 |
 * | `host.vipGate` | `aj.a` | `yi.a` | 17 个方法逐条同名；`p()` `:2139` / `n()` `:1800` 同号；外部锚点 `VipCurrentStatusWebAction:290` 同一调用 |
 * | `host.scanPage` | `ov.l` | `mv.l` | 102 个方法；14 形参构造器 `:286` 同号同签名；字段 `q`/`r` `:70`/`:72`；差异只有 `g30/f→e30/f` |
 * | `fastad.initArg` | `yc.a` | `wc.a` | 两个抽象方法同名同签名（`fail(ILjava/lang/String;)V` + `success()V`）；4 个 `init*` `:242` 同号、只差形参 |
 *
 * **方法名在这十四对里一个都没变**（`descriptor-diff = EMPTY`，除 `ov.l` 的协程 `Continuation`
 * 包整体平移、`hh.y`/`um.z2` 的 `fh/a→dh/a`），变的只有类名，所以本表
 * 只映射类。哪天某个方法名也挪了，就在 [Rename] 里加方法名一侧，别在调用点写两套。
 *
 * **顺序不能反**：1865 里 `yc.a`/`aj.a`/`ul.b`/`kl.a`/`ov.l`/`fh.a` 这些基线短名**仍然存在**，
 * 只是指向了别的类（R8 名字回收）。所以 [candidates] 永远是"当前宿主那一侧排第一"，
 * 且 [is1865] 的三档判定不允许把"未知"当成"基线"。
 *
 * ### 谁来读这张表
 *
 * * 运行时：本对象（[Xp] 与功能代码都经过它）；
 * * 静态门禁：`kit/scripts/hook_vocab.py` 用 `Rename("id", "基线名", "1865 名")` 这一行的
 *   **字面格式**解析它，`check_hook_targets.py` / `check_hook_signatures.py` 因此能在
 *   **任意一棵树**上把基线字面量解析到该树里真实存在的那一侧。
 *   ⇒ **改这张表不用改门禁**，但改动格式会让门禁失去映射（`hook_vocab.HOSTMAP_RE`）。
 *
 * ### 版本怎么判（三档，不允许猜错）
 *
 * 1. `HostVersion.versionCode == 1865` ⇒ 1865 侧；
 * 2. 读过版本行且不是 1865 ⇒ 基线侧（未来版本也按基线走：与旧行为一致，只警告不崩）；
 * 3. **版本行还没读到**（`HostVersion.read` 在 `handleLoadPackage` 早期常常拿不到 Context，
 *    会退化成后台重试，此时 `versionCode == -1`）⇒ 用**类名指纹**判：`tm.g` 只存在于 1865、
 *    `vm.g` 只存在于基线。指纹判完缓存，不等那次重试。
 */
object HostMap {

    /** 1865 = 内测包 6.21.11（versionCode 比 7.10.2 的 1860 还大，但版本号更旧）。 */
    const val VERSION_CODE_1865 = 1865L

    /**
     * 一个"逻辑目标"在两个宿主里的混淆名。
     *
     * 文本格式被 `kit/scripts/hook_vocab.py::HOSTMAP_RE` 解析 —— 加条目照抄这一行的形状。
     */
    data class Rename(val id: String, val baseline: String, val v1865: String)

    // 表本体。顺序无关；id 唯一。**每加一行都要能在两棵树上验证**（ADS.md 的流程）。
    private val RENAMES = listOf(
        Rename("ads.splash", "dj.a", "bj.a"),
        Rename("ads.slot", "di.a", "bi.a"),
        Rename("ads.popup.showArg", "fh.a", "dh.a"),
        Rename("crypto", "vm.g", "tm.g"),
        // ── 宿主角（features/host 下；证据逐条见 `work/compat1865/HOST.md`） ─────────────
        // 服务端弹窗总闸门：`PopwinGate.H`（10 个 win* 分支）/ `SkipForceUpdate.L` / `VipPromo.F`。
        Rename("host.popwin", "hh.y", "fh.y"),
        // 强制更新的判定输入：`SkipForceUpdate.k(CheckAppUpdate)`。
        Rename("host.updateModel", "um.z2", "sm.z2"),
        // 家长模式门面：`ParentCtrlProbe.f()` 读侧 + `ParentModeWriteProbe.l(...)` 写侧。
        Rename("host.parentmode", "ul.b", "sl.b"),
        // 页面请求的 7 参发出点：`PageRequestLog.a(回调,url,params,type,method,headers,extra)`。
        Rename("host.pagehelper", "ps.f", "ns.f"),
        // 上面那条的首参接口（`ps.f$e` 的匿名实现是发起方 action）。
        Rename("host.pagehelper.cb", "ps.f\$e", "ns.f\$e"),
        // Compose 侧另一个 `d` 子类：`HttpBodyProbe` 钩它的 `getBody()`。
        Rename("host.bodyClass", "kl.a", "il.a"),
        // 反调试判定三件套：`AntiDetect` 的 `d()`/`a()`/`c(Context)`。
        Rename("host.antidetect", "dj.f", "bj.f"),
        // 会员判定类：`VipUnlock.p()`（vip）/ `.n()`（tbxVip）。
        Rename("host.vipGate", "aj.a", "yi.a"),
        // 扫描/合成页的会话对象：`WatermarkOff` 钩其 14 形参构造器置 `r`/`q` 字段。
        Rename("host.scanPage", "ov.l", "mv.l"),
        // 三方广告 SDK 四个 `init*` 的公共形参接口（`getSdk` 回调）。
        Rename("fastad.initArg", "yc.a", "wc.a"),
    )

    /** 基线名 / 1865 名 / id 三种写法都能查到同一条。 */
    private val BY_KEY: Map<String, Rename> = buildMap {
        for (r in RENAMES) {
            put(r.id, r)
            put(r.baseline, r)
            put(r.v1865, r)
        }
    }

    /** 1865 指纹：这个类名只在 1865 里存在（基线里没有 `tm.g`，1865 里没有 `vm.g`）。 */
    private const val FINGERPRINT_1865 = "tm.g"

    @Volatile
    private var cached1865: Boolean? = null

    /** 当前宿主是不是 1865（结果缓存；见类注释的三档判定）。 */
    fun is1865(): Boolean = cached1865 ?: detect().also { cached1865 = it }

    /** 仅供测试/诊断：丢掉缓存（宿主进程内不会用到）。 */
    fun forgetVersion() {
        cached1865 = null
    }

    private fun detect(): Boolean {
        val code = HostVersion.versionCode
        if (code == VERSION_CODE_1865) return true
        if (code > 0) return false
        // 版本行还没读到：用类名指纹。找不到指纹就按基线（与旧行为一致）。
        return fingerprintSays1865()
    }

    private fun fingerprintSays1865(): Boolean {
        val cl = Xp.classLoader ?: return false
        return try {
            XposedHelpers.findClass(FINGERPRINT_1865, cl) != null
        } catch (_: Throwable) {
            false
        }
    }

    /**
     * 某个逻辑目标的**候选名**，当前宿主的那一侧排第一。
     *
     * 表里没有的名字原样返回一条 —— 于是调用点对**未映射**的类保持旧语义（零风险）。
     */
    fun candidates(logicalOrObfuscated: String): List<String> {
        val r = BY_KEY[logicalOrObfuscated] ?: return listOf(logicalOrObfuscated)
        return if (is1865()) listOf(r.v1865, r.baseline) else listOf(r.baseline, r.v1865)
    }

    /** 当前宿主应该用的名字（表外的名字原样返回）。 */
    fun name(logicalOrObfuscated: String): String = candidates(logicalOrObfuscated).first()

    /**
     * 按候选顺序解析类，全部失败返回 null。
     *
     * 与 [Xp.clazzOrNull] 的区别：这里**不记账**（它可能被探测/诊断调用），
     * 记账只在钩子安装路径上做一次，否则"同一个缺失类"会被记成两条 skipped。
     */
    fun clazzOrNull(logicalOrObfuscated: String, cl: ClassLoader? = Xp.classLoader): Class<*>? {
        for (cand in candidates(logicalOrObfuscated)) {
            try {
                return XposedHelpers.findClass(cand, cl)
            } catch (_: Throwable) {
                // 试下一个候选
            }
        }
        return null
    }

    /** 一行诊断：把"这一侧用的是哪个名字"写进启动日志，换版排障时不用再猜。 */
    fun describe(): String {
        val side = if (is1865()) "1865" else "baseline"
        val mapped = RENAMES.joinToString(",") { "${it.id}=${if (is1865()) it.v1865 else it.baseline}" }
        return "HostMap side=$side host=${HostVersion.versionName}/${HostVersion.versionCode} $mapped"
    }
}
