/*
 * kuaidui-kit / module/native/kdhide.c
 *
 * Native companion for the KdKit feature `block_native_exit`.
 *
 * Why: the anti-instrumentation layer in `libdpsdk.so` does **not** go through libc when it
 * decides to die — Frida hooks on libc's exit/_exit/exit_group/abort never fire, `strace -f -i`
 * shows a bare `exit_group(0)` from a context whose reported IP lands in a non-executable
 * mapping (so it is a raw `svc` issued from its own trampoline / signal handler), and the
 * Java-side `System.exit` guard does not stop it either. A seccomp filter is the only place
 * left that can veto the syscall itself.
 *
 * What it does: installs a seccomp-bpf filter (after PR_SET_NO_NEW_PRIVS) that answers
 * `exit_group` / `exit` with EPERM instead of terminating the process. Everything else is
 * allowed. It is irreversible for the process — which is exactly why the feature that loads it
 * is off by default and marked "lab only".
 *
 * Build (see build.sh): aarch64-linux-android21-clang -shared -o libkdhide.so kdhide.c
 */
#include <errno.h>
#include <jni.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef __NR_exit
#define __NR_exit 93
#endif
#ifndef __NR_exit_group
#define __NR_exit_group 94
#endif

static int g_installed = 0;
static long g_blocked = 0;   /* 自证计数：每次"确认拦住一次 exit" +1；不是内核回报的命中数 */

/* Counters are read from Java, so keep them trivially readable. */
static int install_filter(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (offsetof(struct seccomp_data, nr))),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_exit_group, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_exit, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA)),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog prog = {
        .len = (unsigned short) (sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        return -(int) errno;
    }
    if (syscall(__NR_seccomp, SECCOMP_SET_MODE_FILTER, 0, &prog) != 0) {
        return -(int) errno;
    }
    g_installed = 1;
    return 0;
}

/* Control arm: install a filter that changes nothing the app relies on (`personality`), so a
 * death here means the app reacts to the *presence* of seccomp (the `Seccomp:` field in
 * /proc/self/status) rather than to our blocked syscalls. */
JNIEXPORT jint JNICALL
Java_dev_xalor_kdkit_features_host_NativeExitGuard_nativeInstallControl(JNIEnv *env, jclass clazz) {
    (void) env;
    (void) clazz;
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (offsetof(struct seccomp_data, nr))),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_personality, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA)),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog prog = {
        .len = (unsigned short) (sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) return -(int) errno;
    if (syscall(__NR_seccomp, SECCOMP_SET_MODE_FILTER, 0, &prog) != 0) return -(int) errno;
    g_installed = 1;
    return 0;
}

/* 装好过滤器后**亲自试一次** `exit_group`：
 *   * 过滤器生效 ⇒ 内核返回 EPERM，进程活着，`g_blocked++`；
 *   * 过滤器没生效 ⇒ 这条 syscall 会直接结束进程（所以调用方必须是"已经装上了"之后才试）。
 *
 * 为什么需要它：seccomp 的 `SECCOMP_RET_ERRNO` **不向用户态回报命中次数**，
 * 所以"运行时拦了几次"内核根本不说。旧实现的 `g_blocked` 全文没有自增点、恒为 0，
 * Kotlin 侧却把它当"拦了几次"打印 —— 那个数字从来没有含义（2026-11-01 审查 P1-5）。
 *
 * 改成"自证计数"之后，`g_blocked >= 1` 就是一个**可断言的活证据**：
 * 过滤器装了、而且真的拦住了。
 */
static int self_probe(void) {
    errno = 0;
    long r = syscall(__NR_exit_group, 0);
    if (r == -1 && errno == EPERM) {
        __atomic_add_fetch(&g_blocked, 1, __ATOMIC_RELAXED);
        return 1;                 /* 被拦住了 */
    }
    return 0;                     /* 没拦住 —— 但也说明我们没死，返回 0 让上层点名 */
}

JNIEXPORT jint JNICALL
Java_dev_xalor_kdkit_features_host_NativeExitGuard_nativeInstall(JNIEnv *env, jclass clazz) {
    (void) env;
    (void) clazz;
    if (g_installed) return 0;
    int rc = install_filter();
    if (rc == 0) {
        /* 自证：能走到下一行，说明 exit_group 被否决了。 */
        (void) self_probe();
    }
    return rc;
}

JNIEXPORT jint JNICALL
Java_dev_xalor_kdkit_features_host_NativeExitGuard_nativeSelfTest(JNIEnv *env, jclass clazz) {
    (void) env;
    (void) clazz;
    if (!g_installed) return -1;  /* 没装 */
    return self_probe();          /* 1 = 拦住，0 = 没拦住 */
}

JNIEXPORT jint JNICALL
Java_dev_xalor_kdkit_features_host_NativeExitGuard_nativeAbi(JNIEnv *env, jclass clazz) {
    (void) env;
    (void) clazz;
    /* 给 Kotlin 侧一条可打印的证据：这个 .so 真的被 dlopen 进来了，且知道自己在拦哪些号 */
    return (jint) (__NR_exit_group & 0xFFFF);
}

JNIEXPORT jboolean JNICALL
Java_dev_xalor_kdkit_features_host_NativeExitGuard_nativeIsInstalled(JNIEnv *env, jclass clazz) {
    (void) env;
    (void) clazz;
    return g_installed ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT jlong JNICALL
Java_dev_xalor_kdkit_features_host_NativeExitGuard_nativeBlockedCount(JNIEnv *env, jclass clazz) {
    (void) env;
    (void) clazz;
    return (jlong) g_blocked;
}
