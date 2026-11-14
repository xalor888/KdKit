package dev.xalor.kdkit.features.host

import dev.xalor.kdkit.features.Category
import dev.xalor.kdkit.features.SwitchFeature
import dev.xalor.kdkit.util.Capture
import dev.xalor.kdkit.util.KdLog
import dev.xalor.kdkit.util.RateLimit
import dev.xalor.kdkit.util.Xp

/**
 * 图片浏览页的水印（**客户端画上去的那一层**）—— 与 [WatermarkOff] 是**两条不同**的路径。
 *
 * ### 为什么需要它：`watermark_off` 盖不到这里
 *
 * `WatermarkOff` 钩的是 `cu.l` 构造器 → 字段 `r` → 随 `/kdapi/image/combine` 上传的
 * `ext="2"`。那条链路负责**导出 PDF/合成**，是服务端合成。
 *
 * 但 App 还有一个**看大图**的页面，水印是**本地用 Canvas 画进位图**的，
 * 完全不走 `cu.l`、不走服务端。静态证据（`work/apktool_out`，逐行可复查）：
 *
 * ```smali
 * CommonWebPictureBrowseActivity.smali:343   .method private o2(Landroid/graphics/Bitmap;)Landroid/graphics/Bitmap;
 *   :209   const v3, 0x7f080335                    ← 水印位图（decodeResource）
 *   :271   Bitmap.createScaledBitmap(watermark, 287dpi, 88dpi, true)
 *   :352   Canvas.drawBitmap(src, 0, 0, paint)     ← 先把原图画进新位图
 *   :393   Math.random()  ← 位置随机，所以"擦掉某一块"永远追不上
 *   :410   Math.random()
 *   :593   Canvas.drawBitmap(watermark, x, y, paint)  ← 再叠水印
 *   :695   .end method
 * ```
 *
 * 调用方 `t2(File, TouchImageView)`（`:1565`）在 `:1735` 调它，**受 `q0:Z` 门控**：
 *
 * ```smali
 * :1711  iget-boolean v0, …, ->q0:Z
 * :1713  if-eqz v0, :cond_1          ← q0 为假就整段跳过，不合成
 * :1735  invoke-direct {p0, p1}, …->o2(Landroid/graphics/Bitmap;)Landroid/graphics/Bitmap;
 * ```
 *
 * 而 `q0` 来自 intent：`:1292 const-string "INPUT_NEED_WATER"` → `:1296 getBooleanExtra`
 * → `:1304 iput-boolean … q0:Z`。这个 extra 由页面给的 `needWatermark`
 * 决定（`GotoPictureBrowseWebAction.smali:408 optBoolean("needWatermark")` → `:420 createIntent(…Z)`）。
 *
 * ### 钩法与"为什么钩 c2 而不是改 q0"
 *
 * 1. **主钩点 `o2`**：`onAfter` 把返回值换成入参（原始位图）。等价于"合成器返回原图"，
 *    屏幕上的大图就不带那一层水印。这是**该方法的纯函数语义**（Bitmap→Bitmap），
 *    不依赖任何私有字段名，宿主混淆改名时比写 `q0` 更耐改。
 * 2. **次钩点 `v2`**（`:1867`，默认开）：同一页还有一个**水印文字 View**，
 *    `v2(boolean, RelativeLayout)` 里 `:1963 if-eqz p1` → `:1967 setVisibility(0)`（显示）
 *    / `:1980 setVisibility(8)`（隐藏）。把第一个布尔改成 false 就等于"页面自己决定不显示"。
 *    两处都关掉才算这一页干净。
 *
 * 两个钩点都**只改本页的渲染**：不碰网络、不碰数据库、不碰 `cu.l` 那条导出链路。
 *
 * ### 静态证据强度 / 未验证
 *
 * * 目标**不是死代码**：`smali_usage.py` 判 `USED(self)`（`o2` 自调 1 处、`v2` 自调 2 处，
 *   外部入口 `GotoPictureBrowseWebAction.smali:420`）。断言在
 *   `kit/python/tests/test_web_picture_watermark.py`。
 * * **未验证**：真机上大图是否真无水印（本轮无设备）。静态只能证明"这段代码会画水印、
 *   且我们能在返回值处截住它"。
 * * **未验证**：`0x7f080335` 是否**只是**水印资源（我们不改资源，只跳过合成，所以
 *   即便它同时用于别处也不受影响）。
 * * 服务端下发的图片本身若已带水印，本功能**不会**去掉 —— 那是另一条路径。
 */
object WebPictureWatermark : SwitchFeature(
    id = "web_picture_watermark",
    title = "大图浏览页水印（本地绘制）",
    summary = "钩 CommonWebPictureBrowseActivity.o2 让它返回原图，并关掉同页水印文字 View；只影响本页渲染",
    category = Category.HOST,
    defaultOn = false,
    hot = true,
) {
    private const val CLS =
        "com.kuaiduizuoye.scan.activity.common.CommonWebPictureBrowseActivity"

    override fun install() {
        var n = 0
        val bmp = Xp.clazzOrNull("android.graphics.Bitmap")
        val rl = Xp.clazzOrNull("android.widget.RelativeLayout")

        // ① 主钩点：o2(Bitmap) -> Bitmap，把返回值换回入参（= 不合成水印）
        if (bmp != null) {
            val ok = Xp.hook(
                CLS, "o2", bmp,
                gate = id,
                onAfter = { p ->
                    val src = p.args.getOrNull(0)
                    if (src != null) {
                        p.result = src
                        note()
                    }
                },
            )
            if (ok) n++
        } else {
            KdLog.w("WebPictureWatermark: 取不到 android.graphics.Bitmap，主钩点跳过")
        }

        // ② 次钩点：v2(boolean, RelativeLayout) —— 第一个布尔是"要不要显示水印 View"
        if (rl != null) {
            val ok = Xp.hook(
                CLS, "v2",
                Boolean::class.javaPrimitiveType, rl,
                gate = id,
                onBefore = { p ->
                    if (p.args.isNotEmpty()) p.args[0] = false
                },
            )
            if (ok) n++
        } else {
            KdLog.w("WebPictureWatermark: 取不到 RelativeLayout，次钩点跳过")
        }

        KdLog.i("WebPictureWatermark installed (hooks=$n)")
    }

    /**
     * 每个浏览页每张图都会走 `o2`（ViewPager 预加载时一次能走三四张），所以只记前若干条。
     * 用 `firstN` 而不是 `every`：这是"看几眼确认生效就够"的事件，不该随翻页无限增长。
     *
     * 行格式**必须**以 `WATERMARK off ` 开头：`capture_schema` 的规则是
     * `^WATERMARK (off .*)$`（variant 固定 `off`、feature 是 `watermark_off`）。
     * 写成 `WATERMARK pic …` 会落到 UNKNOWN —— ①b 的漂移门禁会红，这是它该红。
     * 尾部注明是哪条链路，好把"导出合成"与"浏览页本地绘制"分开看。
     */
    private fun note() {
        if (!RateLimit.firstN("webpic_watermark", 5)) return
        Capture.append("WATERMARK off applied | scope=webpic")
    }
}
