package dev.xalor.kdkit

import dev.xalor.kdkit.util.RateLimit
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class RateLimitTest {
    private var now = 0L

    @Before fun setUp() {
        RateLimit.reset()
        RateLimit.clock = { now }
    }

    @After fun tearDown() {
        RateLimit.clock = { System.nanoTime() / 1_000_000L }
        RateLimit.reset()
    }

    @Test fun everyAllowsFirstThenBlocksUntilInterval() {
        assertTrue(RateLimit.every("k", 1_000))
        assertFalse(RateLimit.every("k", 1_000))
        now = 999
        assertFalse(RateLimit.every("k", 1_000))
        now = 1_000
        assertTrue(RateLimit.every("k", 1_000))
    }

    @Test fun everyKeysAreIndependent() {
        assertTrue(RateLimit.every("a", 1_000))
        assertTrue(RateLimit.every("b", 1_000))
        assertFalse(RateLimit.every("a", 1_000))
    }

    @Test fun firstNAllowsExactlyNLimit() {
        repeat(3) { assertTrue(RateLimit.firstN("x", 3)) }
        assertFalse(RateLimit.firstN("x", 3))
        assertFalse(RateLimit.firstN("x", 3))
    }

    @Test fun firstNIsPerKey() {
        assertTrue(RateLimit.firstN("x", 1))
        assertFalse(RateLimit.firstN("x", 1))
        assertTrue(RateLimit.firstN("y", 1))
    }
}
