package dev.xalor.kdkit.util;

/**
 * 家长模式**写入侧**的形状 → 一行抓取文本（纯逻辑，无 Android 依赖，可在 JVM 里单测）。
 *
 * ### 为什么要和 {@link ParentCtrlShape} 分开
 *
 * 两者看的是同一份数据的**两个方向**：
 *
 * | 方向 | 钩点 | 能回答什么 |
 * |---|---|---|
 * | 读 | `dj.e.f()` → {@link ParentCtrlShape} | 宿主**当前**认为四个闸门是什么 |
 * | 写 | `dj.e.l(ParentCtrlData,int,Callback)` → 本类 | 宿主**正在把**什么提交给服务端 |
 *
 * 只有读侧时，看到 `aiwriting=0` 无法区分两种情况：
 *
 * * 服务端下发的就是 0（策略如此）；
 * * 本地有人改成了 0，正等着提交（或提交失败了）。
 *
 * 写侧那行出现即证明确实发生过一次提交尝试，且六个字段是**提交时的快照**。
 * 两者时间戳一前一后，就能把"下发"与"提交"分开 —— 这是只钩读侧做不到的。
 *
 * ### 六个字段，比读侧多两个
 *
 * 读侧的 `ParentCtrlData` 只有四个闸门。写侧的 Input 还有两个（`from` / `userMode`），
 * 它们描述**这次提交的来源与模式**，不是闸门本身，所以不并进 `mask`。
 *
 * ### 它不下结论
 *
 * 每个字段原样写出（`?` = 读不到，**不猜 0** —— `0` 是合法取值，猜它等于伪造数据）。
 * **不**把任何取值翻译成"已开启 / 已关闭 / 提交成功"：服务端语义与返回值都不在这里，
 * 一律标未验证。
 */
public final class ParentModeWriteShape {

    /**
     * 抓取行前缀。**独立前缀** `PCTRLW`。
     *
     * 不复用读侧的 `PCTRL`：`capture_schema.PREFIX_FEATURE` 由 `setdefault` 派生，
     * 一个 token 只能归属一个功能。复用会让"读"与"写"在按功能统计时合并成一个数字，
     * 而这两个方向回答的是相反的问题（见类文档）。
     */
    public static final String PREFIX = "PCTRLW";

    private ParentModeWriteShape() {}

    /**
     * 六个字段拼成一行。
     *
     * @param aiwriting     `KdcoreUserSetParentMode$Input.aiwriting`
     * @param book          `book`
     * @param correctsearch `correctsearch`
     * @param picsearch     `picsearch`
     * @param from          `from` —— 本次提交的来源（枚举语义**未验证**）
     * @param userMode      `userMode` —— 提交时的模式（枚举语义**未验证**）
     * @return {@code PCTRLW aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x5 from=2 userMode=?}
     */
    public static String line(Integer aiwriting, Integer book,
                              Integer correctsearch, Integer picsearch,
                              Integer from, Integer userMode) {
        return PREFIX
                + " aiwriting=" + field(aiwriting)
                + " book=" + field(book)
                + " correctsearch=" + field(correctsearch)
                + " picsearch=" + field(picsearch)
                + " mask=" + mask(aiwriting, book, correctsearch, picsearch)
                + " from=" + field(from)
                + " userMode=" + field(userMode);
    }

    /** 读不到写 `?`。**不能**写 `0`：`0` 是真实取值，混进来就分不清"关"和"没读到"。 */
    static String field(Integer v) {
        return v == null ? "?" : v.toString();
    }

    /**
     * 四位十六进制掩码：`bit0=aiwriting, bit1=book, bit2=correctsearch, bit3=picsearch`，
     * 某位为 1 当且仅当该字段**读到了且非 0**。
     *
     * <p>`from` / `userMode` **不参与**：它们不是闸门，混进掩码会让
     * "四个闸门的组合"这个含义失效（读侧的同名掩码也因此可以直接对拍）。
     *
     * <p>读不到的字段不计入（`null` 记 0），所以 `mask` 必须与四个字段一起读 ——
     * 单看 `mask=0x0` 可能是"全关"，也可能是"全没读到"，两者**不可由掩码区分**。
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
