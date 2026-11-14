package dev.xalor.kdkit.util

import android.util.Log
import de.robv.android.xposed.XposedBridge

object KdLog {
    /** logcat tag。**`LogSink` 用它排除自身输出**（见那里的 `SELF_TAG` 注释）。 */
    const val TAG = "KdKit"
    @Volatile var debug: Boolean = true
    /** Level 0: silent, 1: normal, 2: verbose */
    @Volatile var level: Int = 2

    fun v(msg: String) { if (level >= 2) emit(msg) }
    fun d(msg: String) { if (level >= 1) emit(msg) }
    fun i(msg: String) = emit(msg)
    fun w(msg: String) = emit("W: $msg")
    fun e(msg: String, t: Throwable? = null) {
        emit("E: $msg" + (t?.let { " | ${it}" } ?: ""))
    }

    private fun emit(msg: String) {
        val line = "[KdKit] $msg"
        try { XposedBridge.log(line) } catch (_: Throwable) {}
        try { Log.i(TAG, msg) } catch (_: Throwable) {}
    }
}
