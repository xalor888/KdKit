package com.zuoyebang.baseutil;

import android.content.Context;
import java.lang.reflect.Method;

/**
 * kuaidui-kit harness: drive the real libbaseutil.so from a process we own.
 *
 * The app kills any process that ptrace-attaches to it (libdpsdk.so reads
 * TracerPid), so Frida is useless against the app itself. None of that applies
 * here: we dlopen the antispam library ourselves.
 *
 * nativeSetToken(env, klass, context, cuid, signA, signB) immediately calls a
 * helper that invokes a method on `context` (JNI aborts with "obj == null" if we
 * pass null), so we materialise a real Context through ActivityThread.
 *
 * usage: Harness <lib.so> [signA signB] [versionCode] [signParam]
 */
public class Harness {
    private static Context systemContext() throws Exception {
        android.os.Looper.prepareMainLooper();
        Class<?> at = Class.forName("android.app.ActivityThread");
        Method systemMain = at.getMethod("systemMain");
        Object thread = systemMain.invoke(null);
        return (Context) at.getMethod("getSystemContext").invoke(thread);
    }

    public static void main(String[] args) {
        String lib = args.length > 0 ? args[0] : "/data/local/tmp/libbaseutil.so";
        try {
            System.load(lib);
            System.out.println("loaded " + lib);
        } catch (Throwable t) {
            System.out.println("load failed: " + t);
            return;
        }

        Context ctx = null;
        try {
            Context sys = systemContext();
            // libbaseutil reads context.getPackageManager().getPackageInfo(
            //     context.getPackageName(), GET_SIGNATURES) and binds its state to
            // that result, so the Context must report the TARGET package.
            try {
                ctx = sys.createPackageContext("com.kuaiduizuoye.scan",
                        Context.CONTEXT_IGNORE_SECURITY | Context.CONTEXT_INCLUDE_CODE);
            } catch (Throwable t1) {
                System.out.println("createPackageContext(flags) failed: " + t1);
                ctx = sys.createPackageContext("com.kuaiduizuoye.scan", 0);
            }
            System.out.println("context = " + ctx + " pkg=" + ctx.getPackageName());
        } catch (Throwable t) {
            System.out.println("context failed: " + t);
            for (Throwable c = t; c != null; c = c.getCause()) {
                System.out.println("  cause: " + c);
                StackTraceElement[] st = c.getStackTrace();
                for (int i = 0; i < Math.min(6, st.length); i++) System.out.println("    at " + st[i]);
            }
        }

        String cuid = args.length > 5 ? args[5] : "cuid";
        if (args.length >= 3) {
            boolean ok = NativeHelper.nativeSetToken(ctx, cuid, args[1], args[2]);
            System.out.println("nativeSetToken(cuid=" + cuid + ") -> " + ok);
        }
        String ver = args.length > 3 ? args[3] : "1811";
        System.out.println("nativeGetKey(" + ver + ") -> " + NativeHelper.nativeGetKey(ver));
        System.out.println("nativeGetRandom() -> " + NativeHelper.nativeGetRandom());
        if (args.length > 6 && args[6].equals("sleep")) {
            System.out.println("pid=" + android.os.Process.myPid() + " sleeping");
            try { Thread.sleep(25000); } catch (Throwable t) {}
        }
        Dump.dump();
        if (args.length >= 5) {
            System.out.println("nativeGetSign(" + args[4] + ") -> " + NativeHelper.nativeGetSign(args[4]));
        }
    }
}
