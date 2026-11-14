package dev.xalor.kdkit.util;

/**
 * 家长模式的**闸门形状** → 一行抓取文本（纯逻辑，无 Android 依赖，可在 JVM 里单测）。
 *
 * ### 为什么单独一个文件
 *
 * `ParentCtrlProbe` 要钩 `dj.e.f()`，返回体是
 * `ParentCtrlData{aiwriting,book,correctsearch,picsearch}` 四个 `int`。
 * 这四个值的**语义**（哪个值代表"允许"）只能从服务端下发的 AB 配置里看，
 * 而抓取时拿不到服务端。所以这里只做一个**形状编码**，不下结论：
 *
 * * 每个字段原样写出（`?` = 读不到，不猜 0 —— `0` 是合法取值，猜它等于伪造数据）；
 * * 额外给一个 `mask`（四位十六进制），让"四个字段的组合"可以逐字节比对；
 * * **不**把任何取值翻译成"已解锁 / 已限制" —— 那需要服务端语义，标未验证。
 *
 * ### 为什么不用 Kotlin
 *
 * 与 {@link PageRequestOrigin} / {@link DecodeRequestShape} 一致：纯逻辑放 `util/`
 * 用 Kotlin/Java 都行，但这里用 Java 是因为**没有任何 Kotlin 特性能用上**
 * （无 `data class`、无 `when` 穷尽、无默认参数），用 Java 反而少一层编译期魔法。
 */
public final class ParentCtrlShape {

    /** 抓取行前缀。**独立前缀**，不复用 `VIP` / `POPWIN`（见 `capture_schema.py` 的 `setdefault` 约束）。 */
    public static final String PREFIX = "PCTRL";

    private ParentCtrlShape() {}

    /**
     * 四个闸门字段拼成一行。
     *
     * @param aiwriting     `ParentCtrlData.getAiwriting()`，读不到传 {@code null}
     * @param book          `getBook()`
     * @param correctsearch `getCorrectsearch()`
     * @param picsearch     `getPicsearch()`
     * @return {@code PCTRL aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x90}
     */
    public static String line(Integer aiwriting, Integer book,
                             Integer correctsearch, Integer picsearch) {
        return PREFIX
                + " aiwriting=" + field(aiwriting)
                + " book=" + field(book)
                + " correctsearch=" + field(correctsearch)
                + " picsearch=" + field(picsearch)
                + " mask=" + mask(aiwriting, book, correctsearch, picsearch);
    }

    /** 读不到写 `?`。**不能**写 `0`：`0` 是真实取值，混进来就分不清"关"和"没读到"。 */
    static String field(Integer v) {
        return v == null ? "?" : v.toString();
    }

    /**
     * 四位十六进制掩码：`bit0=aiwriting, bit1=book, bit2=correctsearch, bit3=picsearch`，
     * 某位为 1 当且仅当该字段**读到了且非 0**。
     *
     * <p>为什么还要一个掩码：四个独立字段的"组合"在日志里要逐字比对很难，
     * 一个 `mask=0x1` 就能看出"只有 aiwriting 开着"。读不到的字段不计入
     * （`null` 记 0），所以 `mask` 必须与四个字段一起读 —— 单看
     * `mask=0x0` 可能是"全关"，也可能是"全没读到"，两者**不可由掩码区分**。
     */
    public static String mask(Integer aiwriting, Integer book,
                              Integer correctsearch, Integer picsearch) {
        int m = 0;
        if (on(aiwriting)) m |= 1;
        if (on(book)) m |= 2;
        if (on(correctsearch)) m |= 4;
        if (on(picsearch)) m |= 8;
        return "0x" + Integer.toHexString(m);
    }

    /** 读到且非 0 才算"开"。读不到（`null`）**不计入**，与"读到 0"不同。 */
    private static boolean on(Integer v) {
        return v != null && v != 0;
    }
}
