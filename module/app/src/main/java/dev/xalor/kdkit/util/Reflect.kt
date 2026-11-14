package dev.xalor.kdkit.util

/**
 * 沿继承链读字段 / 调用方法的安全封装。
 *
 * ### 为什么单独成文件
 *
 * 这类代码最容易写错，而写错的后果是**静默返回默认值**，不是崩溃 ——
 * 抓取里那一列会一直显示 `-`，没有任何报错提示。
 *
 * 具体遇到过的坑（2026-10-25，`ReqHeaders.pidOf` 第一版）：
 *
 * ```kotlin
 * val f = req?.javaClass?.getField("mInputBase")
 *     ?: req?.javaClass?.getDeclaredField("mInputBase")   // ← 永远不执行
 * ```
 *
 * `mInputBase` 是 `protected final`，而 `getField` **只查 public 成员**，
 * 对它**抛 `NoSuchFieldException` 而不是返回 null**。所以 elvis 右侧是死代码，
 * pid 恒为 `-`。这个错误编译期完全看不出来。
 *
 * 抽成独立文件后才能写单元测试守住（见 `ReflectTest`）。
 */
object Reflect {

    /** 沿继承链找字段（含 private/protected），读不到返回 null。 */
    fun field(obj: Any?, name: String): Any? {
        if (obj == null) return null
        var c: Class<*>? = obj.javaClass
        while (c != null) {
            try {
                val f = c.getDeclaredField(name)
                f.isAccessible = true
                return f.get(obj)
            } catch (_: NoSuchFieldException) {
                c = c.superclass
            } catch (_: Throwable) {
                return null
            }
        }
        return null
    }

    /** 读一个 String 字段，空串视为"已知但为空"，与"读不到"区分开。 */
    fun stringField(obj: Any?, name: String): String? =
        field(obj, name) as? String
}
