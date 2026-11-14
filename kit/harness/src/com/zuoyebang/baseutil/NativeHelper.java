package com.zuoyebang.baseutil;

/* Must be declared with exactly this class name: libbaseutil.so's JNI_OnLoad
 * does FindClass("com/zuoyebang/baseutil/NativeHelper") and RegisterNatives on
 * it. Declaring the same FQN here makes the real .so bind its natives to our
 * harness class. */
public class NativeHelper {
    static native String nativeGetKey(String str);
    static native String nativeGetRandom();
    static native String nativeGetSign(String str);
    static native String nativeInitBaseUtil(android.content.Context context, String str);
    static native boolean nativeSetToken(android.content.Context context, String str, String str2, String str3);
}
