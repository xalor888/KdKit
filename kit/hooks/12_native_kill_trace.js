/*
 * kuaidui-kit / 12_native_kill_trace.js
 *
 * Native-side killer tracing for 快对 (DProtect / libdpsdk.so).
 *
 * Java-side exits are covered by KdKit (ExitGuard) and by 00_no_selfexit.js, but
 * the process still disappears — with a *clean* status 0 and **no**
 * `aiduizuoye.scan: System.exit called` line in logcat, which means a native
 * `exit(0)` / `exit_group(0)`. `strace -i` showed the syscall but its reported IP
 * landed in an unmapped gap, so this script hooks the in-process teardown
 * functions and the /proc scanners that feed them, and prints ACCURATE
 * backtraces (module+offset → maps straight onto radare2 on libdpsdk.so).
 *
 * Born to run under frida **spawn** (no Java bridge needed):
 *   python3 kit/scripts/attach_probe.py --spawn ... (see its --spawn flag)
 */
var TAG = '[kill-trace]';

function bt(ctx) {
    try {
        return Thread.backtrace(ctx, Backtracer.ACCURATE)
            .map(function (a) { return String(DebugSymbol.fromAddress(a)); })
            .join('\n');
    } catch (e) {
        return '<no trace: ' + e + '>';
    }
}

function hookExport(mod, name, cb, kind) {
    var addr = null;
    try {
        addr = mod ? mod.getExportByName(name) : Module.getGlobalExportByName(name);
    } catch (e) { return false; }
    if (addr === null || addr === undefined) return false;
    try {
        Interceptor.attach(addr, {
            onEnter: function (args) {
                try { cb(args, this.context); } catch (e) { }
            }
        });
        console.log(TAG + ' hooked ' + (kind || '') + ' ' + name);
        return true;
    } catch (e) {
        console.log(TAG + ' hook failed ' + name + ': ' + e);
        return false;
    }
}

var libc = null, libart = null;
try { libc = Process.getModuleByName('libc.so'); } catch (e) { }

var proc_paths = /^\/(proc|sys)\//;

function notePath(args, ctx, name) {
    var p = null;
    try { p = (name === 'openat' || name === 'faccessat' || name === 'readlinkat') ? args[1] : args[0]; } catch (e) { }
    if (p === null) return;
    var s = null;
    try { s = p.readUtf8String(); } catch (e) { return; }
    if (!s || !proc_paths.test(s)) return;
    var interesting = /\/proc\/(self|\d+)\/(status|maps|task|comm|cmdline|mountinfo|mounts)/.test(s);
    if (!interesting) return;
    send({ ev: 'proc-read', fn: name, path: s, bt: bt(ctx) });
    console.log(TAG + ' ' + name + '(' + s + ')\n' + bt(ctx));
}

// 1) teardown entry points
['exit', '_exit', '_Exit', 'exit_group', 'quick_exit', 'abort'].forEach(function (n) {
    hookExport(libc, n, function (args, ctx) {
        var arg = (n === 'abort' || n === 'quick_exit') ? null : args[0].toInt32();
        send({ ev: 'kill-call', fn: n, arg: arg, bt: bt(ctx) });
        console.log(TAG + ' ' + n + '(' + arg + ')\n' + bt(ctx));
    });
});

// 2) process-killing syscalls, in case they skip libc exit()
['kill', 'tgkill', 'pthread_kill', 'raise', 'android_set_abort_message'].forEach(function (n) {
    hookExport(libc, n, function (args, ctx) {
        send({ ev: 'signal-call', fn: n, bt: bt(ctx) });
        console.log(TAG + ' ' + n + '()\n' + bt(ctx));
    });
});

// 3) the /proc scanners that feed the decision
['open', 'openat', 'fopen', 'fopen64', 'access', 'faccessat', 'readlinkat', 'stat', 'lstat', 'stat64'].forEach(function (n) {
    hookExport(libc, n, function (args, ctx) { notePath(args, ctx, n); });
});

// 4) raw syscall() — arm64 exit_group=94, exit=93, kill=129, tgkill=131
hookExport(libc, 'syscall', function (args, ctx) {
    var nr = args[0].toInt32();
    if (nr === 93 || nr === 94 || nr === 129 || nr === 131) {
        send({ ev: 'raw-syscall', nr: nr, bt: bt(ctx) });
        console.log(TAG + ' syscall(' + nr + ')\n' + bt(ctx));
    }
});

console.log(TAG + ' installed (libc=' + (libc ? libc.base : 'n/a') + ')');
