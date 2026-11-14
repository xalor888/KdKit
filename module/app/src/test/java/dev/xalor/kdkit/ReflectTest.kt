package dev.xalor.kdkit

import dev.xalor.kdkit.util.Reflect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * `util.Reflect` 的行为测试。
 *
 * 守的是一个具体事故：`ReqHeaders.pidOf` 第一版写
 * `getField(name) ?: getDeclaredField(name)` —— 看着像"先 public 再宽松"，
 * 实际 `getField` 对 protected 字段**抛 `NoSuchFieldException` 而不是返回 null**，
 * 于是 elvis 右侧是死代码，pid 恒为 `-`。
 *
 * 这类 bug 编译期看不出来、运行期不报错，只有抓取里那一列一直是 `-`。
 */
class ReflectTest {

    // ── 夹具：protected 字段声明在父类（与真实链路同形）───────────────────────
    // 注意：`mInputBase` 的类型不能是 `Child` —— 那会 `Parent.<init>` → `new Child()`
    // → `Child.<init>` → `super()` → 无限递归（StackOverflowError）。
    // 真实链路里它装的是 `InputBase`，与 `HWRequest` 无继承关系，用独立类最贴近。
    class Payload { val __pid: String = "saas-passport" }

    @Suppress("unused")
    open class Parent {
        protected val mInputBase: Any = Payload()
        private val secret = "s3cr3t"
    }

    @Suppress("unused")
    class Child : Parent() {
        val __pid: String = "cube"
    }

    @Suppress("unused")
    class EmptyPid {
        val __pid: String = ""
    }

    @Test
    fun readsProtectedFieldDeclaredOnSuperclass() {
        // 这是关键一条：真实链路里 `mInputBase` 声明在 HWRequest（父类）且是 protected。
        val v = Reflect.field(Child(), "mInputBase")
        assertEquals(Payload::class.java, v!!.javaClass)
    }

    @Test
    fun walksUpTheInheritanceChain() {
        assertEquals("s3cr3t", Reflect.field(Child(), "secret"))
    }

    @Test
    fun missingFieldIsNullNotThrow() {
        assertNull(Reflect.field(Child(), "definitelyNotThere"))
        assertNull(Reflect.field(null, "anything"))
    }

    @Test
    fun stringFieldDistinguishesEmptyFromMissing() {
        // 空串是"已知但为空"，null 是"读不到" —— 两者不能混。
        assertEquals("", Reflect.stringField(EmptyPid(), "__pid"))
        assertNull(Reflect.stringField(EmptyPid(), "nope"))
    }

    @Test
    fun publicFieldAlsoWorks() {
        // getDeclaredField 对 public 成员同样有效，不需要先试 getField。
        assertEquals("cube", Reflect.stringField(Child(), "__pid"))
    }
}
