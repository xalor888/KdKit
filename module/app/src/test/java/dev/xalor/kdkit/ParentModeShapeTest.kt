package dev.xalor.kdkit

import dev.xalor.kdkit.util.ParentCtrlShape
import dev.xalor.kdkit.util.ParentModeWriteShape
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * 家长模式的**两侧**形状编码（读 `PCTRL` / 写 `PCTRLW`）。
 *
 * 这两个类是纯逻辑，所以它的"对不对"可以完全离线判定 —— 这正是它值得单测的理由：
 * 抓取行一旦写错，真机上表现为"功能在跑但数据是错的"，而错的数据看起来和
 * 真数据一模一样（都是 `int`）。没有断言就只能靠人盯日志。
 *
 * 三条规则在这里被钉死：
 *
 * 1. **读不到写 `?`，不写 `0`** —— `0` 是合法取值，混进来就分不清"关"和"没读到"；
 * 2. **掩码只含四个闸门** —— `from` / `userMode` 不是闸门，混进去会让"组合"失去意义；
 * 3. **两个前缀必须不同** —— 否则按功能统计时读侧与写侧会合成一个数字。
 */
class ParentModeShapeTest {

    // ── 读侧 `PCTRL` ────────────────────────────────────────────────────────

    @Test fun readLinePutsAllFourGates() {
        assertEquals(
            "PCTRL aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x5",
            ParentCtrlShape.line(1, 0, 1, null),
        )
    }

    @Test fun unreadableIsQuestionMarkNotZero() {
        // 这一条是整个类存在的核心理由：`?` 与 `0` 必须可区分。
        val line = ParentCtrlShape.line(null, null, null, null)
        assertEquals("PCTRL aiwriting=? book=? correctsearch=? picsearch=? mask=0x0", line)
        // 全 `?` 与全 `0` 的掩码相同，但**字段**不同 —— 所以掩码不能单独读。
        assertNotEquals(line, ParentCtrlShape.line(0, 0, 0, 0))
    }

    @Test fun maskCountsOnlyTruthyGates() {
        assertEquals("0x0", ParentCtrlShape.mask(0, 0, 0, 0))
        assertEquals("0x1", ParentCtrlShape.mask(1, 0, 0, 0))
        assertEquals("0x2", ParentCtrlShape.mask(0, 1, 0, 0))
        assertEquals("0x4", ParentCtrlShape.mask(0, 0, 1, 0))
        assertEquals("0x8", ParentCtrlShape.mask(0, 0, 0, 1))
        assertEquals("0xf", ParentCtrlShape.mask(1, 1, 1, 1))
    }

    @Test fun negativeAndLargeValuesAreTruthy() {
        // 宿主这里是 `int`，不是 `boolean`。任何非 0 都算"开"。
        // 写这个断言是为了防"以为只有 1 算开"的误读 —— 那会让 mask 少一位。
        assertEquals("0x1", ParentCtrlShape.mask(-1, 0, 0, 0))
        assertEquals("0x1", ParentCtrlShape.mask(2, 0, 0, 0))
    }

    // ── 写侧 `PCTRLW` ───────────────────────────────────────────────────────

    @Test fun writeLineCarriesTwoExtraFields() {
        assertEquals(
            "PCTRLW aiwriting=1 book=0 correctsearch=1 picsearch=? mask=0x5 from=2 userMode=?",
            ParentModeWriteShape.line(1, 0, 1, null, 2, null),
        )
    }

    @Test fun writeMaskIgnoresNonGateFields() {
        // `from` / `userMode` 变化**不能**改变 mask：它们不是闸门。
        assertEquals(
            ParentModeWriteShape.mask(1, 0, 1, 0),
            ParentModeWriteShape.mask(1, 0, 1, 0),
        )
        val a = ParentModeWriteShape.line(1, 0, 1, 0, 0, 0)
        val b = ParentModeWriteShape.line(1, 0, 1, 0, 9, 9)
        assertEquals(
            "mask 必须与 from/userMode 无关",
            a.substringAfter("mask=").substringBefore(" from="),
            b.substringAfter("mask=").substringBefore(" from="),
        )
    }

    @Test fun writeMaskMatchesReadMaskForSameGates() {
        // 两侧的 mask 语义必须一致，否则"读侧写侧对拍"这件事就不成立 ——
        // 而对拍正是加写侧观测的全部理由。
        assertEquals(
            ParentCtrlShape.mask(1, 0, 1, null),
            ParentModeWriteShape.mask(1, 0, 1, null),
        )
        assertEquals(
            ParentCtrlShape.mask(null, null, null, null),
            ParentModeWriteShape.mask(null, null, null, null),
        )
    }

    @Test fun theTwoPrefixesAreDifferent() {
        // 若相同，`capture_schema.PREFIX_FEATURE` 的 setdefault 会让读写两侧
        // 归到同一个功能，按功能统计时合成为一个数字。
        assertNotEquals(ParentCtrlShape.PREFIX, ParentModeWriteShape.PREFIX)
        assertEquals("PCTRL", ParentCtrlShape.PREFIX)
        assertEquals("PCTRLW", ParentModeWriteShape.PREFIX)
    }

    @Test fun writePrefixIsNotAPrefixCollision() {
        // `PCTRLW` 以 `PCTRL` 开头 —— 解析器按"整 token 精确匹配"认领，
        // 不是前缀匹配，所以不会互相抢占。这条断言把那个前提写下来：
        // 它一旦被改成 startsWith，`PCTRLW …` 会被读成 `PCTRL` 的行。
        val write = ParentModeWriteShape.line(1, 0, 1, 0, 2, 3)
        assertEquals("PCTRLW", write.substringBefore(' '))
        // 前缀后面的第一个字符是空格，保证 token 边界清晰。
        assertEquals(' ', write[ParentModeWriteShape.PREFIX.length])
    }
}
