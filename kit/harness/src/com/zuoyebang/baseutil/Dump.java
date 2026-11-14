package com.zuoyebang.baseutil;

import java.io.BufferedReader;
import java.io.FileReader;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** In-process memory access. libbaseutil keeps its runtime state in heap objects
 *  we cannot reach through /proc/self/mem, so we use Unsafe (available in
 *  libcore, reached by reflection) to read it directly. */
public class Dump {
    static Object unsafe;
    static Method mGetLong, mGetByte;

    static void initUnsafe() throws Exception {
        Class<?> u = Class.forName("sun.misc.Unsafe");
        Field f = u.getDeclaredField("theUnsafe");
        f.setAccessible(true);
        unsafe = f.get(null);
        mGetLong = u.getMethod("getLong", long.class);
        mGetByte = u.getMethod("getByte", long.class);
    }

    static long moduleBase(String name) throws Exception {
        BufferedReader r = new BufferedReader(new FileReader("/proc/self/maps"));
        String line;
        while ((line = r.readLine()) != null) {
            if (line.contains(name)) { r.close(); return Long.parseLong(line.split("-")[0], 16); }
        }
        r.close();
        return -1;
    }

    static long ld(long a) throws Exception {
        if (!mapped(a, 8)) return 0;
        return (Long) mGetLong.invoke(unsafe, a);
    }
    static int sb(long a) throws Exception { return (Byte) mGetByte.invoke(unsafe, a) & 0xff; }

    static long[][] maps;

    static void loadMaps() throws Exception {
        java.util.List<long[]> list = new java.util.ArrayList<long[]>();
        BufferedReader r = new BufferedReader(new FileReader("/proc/self/maps"));
        String line;
        while ((line = r.readLine()) != null) {
            String[] parts = line.split(" ");
            String[] rng = parts[0].split("-");
            if (parts.length > 1 && parts[1].indexOf('r') == 0) {
                list.add(new long[]{Long.parseLong(rng[0], 16), Long.parseLong(rng[1], 16)});
            }
        }
        r.close();
        maps = list.toArray(new long[0][]);
    }

    static boolean mapped(long a, int len) {
        if (maps == null) return true;
        for (long[] m : maps) if (a >= m[0] && a + len <= m[1]) return true;
        return false;
    }

    static String cstr(long a, int max) {
        if (!mapped(a, max)) return "<unmapped>";
        try {
            StringBuilder s = new StringBuilder();
            for (int i = 0; i < max; i++) {
                int b = sb(a + i);
                if (b == 0) break;
                s.append((b >= 32 && b < 127) ? (char) b : '.');
            }
            return s.toString();
        } catch (Exception e) { return "<err>"; }
    }

    public static void dump() {
        System.out.println("=== DUMP START ===");
        try {
            initUnsafe();
            loadMaps();
            System.out.println("unsafe ok, maps=" + (maps == null ? -1 : maps.length));
            long base = moduleBase("libbaseutil.so");
            System.out.println("base=0x" + Long.toHexString(base));
            for (long off : new long[]{0xa230L, 0xa238L, 0xa240L, 0xa248L, 0xa250L}) {
                long va = base + off;
                long q = ld(va);
                System.out.println("@" + Long.toHexString(off) + " q=0x" + Long.toHexString(q)
                        + " str='" + cstr(va, 48) + "'"
                        + (q > 0x10000 ? " deref='" + cstr(q, 96) + "'" : ""));
            }
            for (long off : new long[]{0xa238L, 0xa240L}) {
                long p = ld(base + off);
                System.out.println("--- struct @" + Long.toHexString(off) + " -> 0x" + Long.toHexString(p));
                for (int i = 0; i < 0x28; i += 8) {
                    long v = ld(p + i);
                    System.out.println("    +0x" + Integer.toHexString(i) + " = 0x" + Long.toHexString(v)
                            + (v > 0x10000 ? " str='" + cstr(v, 96) + "'" : ""));
                }
                System.out.println("    raw: " + cstr(p, 0x28));
            }
        } catch (Throwable t) { System.out.println("dump failed: " + t); }
        System.out.println("=== DUMP END ===");
    }
}
