package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.config.KdOption
import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 去水印开关（**客户端自带的用户功能**，默认关闭，热开关）。
 *
 * ### 先说清楚它是什么（避免被当成"破解水印"）
 *
 * App 自己就有这个开关：`res/values/strings.xml` 里有 `去除水印` / `还原水印` 两条文案，
 * 用户点一下就会走同一条链路。本功能只是**代用户按下这个开关**，不伪造服务端结果、
 * 不改请求参数、不绕过次数限制 —— 服务端仍按它自己的规则合成并计次。
 *
 * ### 为什么钩 `cu.l` 的构造器（而不是 getter）
 *
 * 静态证据链（`NEW_TARGETS.md` §2.2 已逐行核对）：
 *
 * 1. `cu/p.l(List,boolean,boolean)List` — `smali_classes6/cu/p.smali:2293`
 *    从 `ScanEntity.getClearWatermark()I` 取值，`== 1` 时把 `p3` 置 true 再传给 `cu.l` 构造器
 *    （`:606` 取值、`:622` 传参）。同文件还有两处（`:694/:710`、`:2834/:2860`），
 *    `cu/o` 另有两处（`:4803/:4828`），`DcScanEditorViewModel$c`、`SortViewModel$d`
 *    各有一处 —— **全部走 getter**，不是直读字段。
 * 2. `cu/l.<init>(…ZZ…)` — `cu/l.smali:286`。第 12 个布尔落字段 `q`（clearWriting），
 *    第 13 个落字段 `r`（clearWatermark）：`:509` `move/from16 p1, p12` → `iput-boolean … q`，
 *    `:512` `move/from16 p1, p13` → `iput-boolean … r`。
 * 3. `cu/l.K(String,Lt10/f;)` — `cu/l.smali:3189` **直读字段** `r`（`iget-boolean`），
 *    为真时把字符串 `"2"` 塞进 `ext` 列表，最后随 `ImageCombine$Input`
 *    （`/kdapi/image/combine`）上传。⇒ **光钩 getter `m0()` 改不到请求**，必须让字段为真。
 *
 * 所以钩点是**构造器**：在 `afterHookedMethod` 里把字段 `r` 置 true。
 * 这样 `K()` 后面读字段时拿到的就是"用户已开启去水印"，请求参数与服务端行为都不被篡改。
 *
 * ### 为什么不用 `setClearWatermark`
 *
 * `ScanEntity.setClearWatermark(I)` 也可钩（`smali_classes6/…/ScanEntity.smali:1562`），
 * 但它只影响"这次编辑的实体"；`cu/l` 是**每次合成前现建**的对象，钩构造器覆盖面更完整，
 * 且不写数据库（不改用户数据）。要改数据库语义请用 `watermark_persist` 选项。
 *
 * ### 限制（写进文档，别当成已验证）
 *
 * * 服务端是否按 VIP/次数拒绝"去水印合成" —— **静态无法判定，未验证**；
 * * 真机是否真的产出无水印 PDF/图片 —— **未验证**（本轮无设备）。
 */
object WatermarkOff : SwitchFeature(
    id = "watermark_off",
    title = "去水印（客户端开关）",
    summary = "把 App 自带的「去除水印」开关代用户打开（钩 cu.l 构造器置字段 r）；服务端计次与鉴权不受影响",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    /** 构造器签名（14 个形参）—— 与 `cu/l.smali:286` 逐一对应。 */
    private const val CTOR_DESC =
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;" +
            "IIFLjava/lang/String;Ljava/lang/String;IIZZLjava/lang/String;)V"

    override val options: List<KdOption> = listOf(
        KdOption(
            key = "watermark_off_writing",
            title = "同时去掉手写笔迹",
            summary = "同一构造器的另一个布尔（字段 q，ext 里对应 \"1\"）；默认只去水印（\"2\"）",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
        KdOption(
            key = "watermark_off_entity",
            title = "同时改数据库里的标记",
            summary = "钩 ScanEntity.setClearWatermark 把落库值改成 1；会写用户数据，默认关",
            kind = KdOption.Kind.BOOLEAN,
            default = "false",
        ),
    )

    override fun install() {
        var n = 0
        // ① 主钩点：cu.l 构造器 → 置字段 r（clearWatermark），可选字段 q（clearWriting）
        val cls = Xp.clazzOrNull("ov.l")
        if (cls != null) {
            val ctor = runCatching { cls.getDeclaredConstructor(*ctorTypes(cls)) }.getOrNull()
            if (ctor != null) {
                val ok = Xp.hookCtor(
                    "ov.l",
                    *ctorTypes(cls),
                    gate = id,
                    onAfter = { p ->
                        val self = p.thisObject ?: return@hookCtor
                        if (!force(self, "r")) return@hookCtor
                        if (dev.xalor.kdkit.config.KdConfig.isOn("watermark_off_writing", false)) {
                            force(self, "q")
                        }
                        note()
                    },
                )
                if (ok) n++
            } else {
                KdLog.w("WatermarkOff: cu.l 构造器签名没找到（$CTOR_DESC），本钩点跳过")
            }
        } else {
            KdLog.w("WatermarkOff: 找不到 cu.l（宿主换版？）")
        }

        // ② 可选：落库标记（默认关；打开后每次编辑都会把 clearWatermark 写成 1）
        if (dev.xalor.kdkit.config.KdConfig.isOn("watermark_off_entity", false)) {
            if (Xp.hook("com.zybang.doc_common.db.entity.ScanEntity", "setClearWatermark",
                    Int::class.javaPrimitiveType, gate = id, onBefore = { p ->
                        p.args[0] = 1
                    })
            ) n++
        }
        KdLog.i("WatermarkOff installed (hooks=$n, writing=" +
            dev.xalor.kdkit.config.KdConfig.isOn("watermark_off_writing", false) + ")")
    }

    /** 反射置布尔字段为 true；字段不存在/不可写都只记一条日志（不抛给宿主）。 */
    private fun force(target: Any, field: String): Boolean = try {
        val f = target.javaClass.getDeclaredField(field)
        f.isAccessible = true
        f.setBoolean(target, true)
        true
    } catch (t: Throwable) {
        KdLog.w("WatermarkOff: 置字段 $field 失败: $t")
        false
    }

    /** 构造器形参类型：优先用**描述符**精确匹配，避免 `Class` 解析失败时退化成"任意构造器"。 */
    private fun ctorTypes(cls: Class<*>): Array<Class<*>> {
        val wanted: Array<Class<*>> = arrayOf(
            String::class.java, String::class.java, String::class.java, String::class.java,
            Int::class.javaPrimitiveType!!, Int::class.javaPrimitiveType!!,
            Float::class.javaPrimitiveType!!,
            String::class.java, String::class.java,
            Int::class.javaPrimitiveType!!, Int::class.javaPrimitiveType!!,
            Boolean::class.javaPrimitiveType!!, Boolean::class.javaPrimitiveType!!,
            String::class.java,
        )
        // 逐个比对真实构造器，确保我们钩的就是 14 参那一个（宿主换版可能增删参数）。
        val hit = cls.declaredConstructors.firstOrNull { c ->
            val ps = c.parameterTypes
            ps.size == wanted.size && ps.indices.all { i ->
                ps[i] == wanted[i] || ps[i].name == wanted[i].name
            }
        }
        return hit?.parameterTypes ?: wanted
    }

    /** 只记前几条 + 每分钟一条心跳：每次合成都会走构造器，量可能不小。 */
    private fun note() {
        if (RateLimit.firstN("watermark.note", 5) || RateLimit.every("watermark.heartbeat", 60_000)) {
            Capture.append("WATERMARK off applied")
        }
    }
}
