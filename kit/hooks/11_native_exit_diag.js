/*
 * kuaidui-kit / 11_native_exit_diag.js
 *
 * Who actually kills the 快对 process when DProtect sees an attached debugger?
 *
 * The Java-side `System.exit` guard (KdKit feature `exit_guard`, and
 * `00_no_selfexit.js`) does not save the process on its own, so a second,
 * native path exists. This script hooks the process-teardown entry points in
 * libc and prints an ACCURATE backtrace for each — the module+offset in the
 * trace is what maps back to libdpsdk.so in radare2.
 *
 *   BLOCK=false  observe only (process still dies, we get the trace)
 *   BLOCK=true   swallow exit/_exit/exit_group so the process survives
 *
 * No Java bridge needed: load it into a running process with
 *   python3 kit/scripts/attach_probe.py --adb emulator-5556 \
 *       --script kit/hooks/11_native_exit_diag.js --seconds 20
 */
var BLOCK = true;
var TAG = '[native-exit]';

function trace(ctx) {
    try {
        return Thread.backtrace(ctx, Backtracer.ACCURATE)
            .map(function (a) { return '    ' + DebugSymbol.fromAddress(a); })
            .join('\n');
    } catch (e) {
        return '    <no trace: ' + e + '>';
    }
}

var targets = ['exit', '_exit', 'exit_group', 'quick_exit', 'abort', '_Exit'];
var libc = null;
try { libc = Process.getModuleByName('libc.so'); } catch (e) { libc = null; }
if (libc === null) {
    console.log(TAG + ' libc.so not found — falling back to Module.findGlobalExportByName');
}

var installed = 0;
targets.forEach(function (name) {
    var addr = null;
    try {
        addr = libc ? libc.getExportByName(name) : Module.getGlobalExportByName(name);
    } catch (e) { addr = null; }
    if (addr === null || addr === undefined) return;

    if (BLOCK && name !== 'abort') {
        try {
            Interceptor.replace(addr, new NativeCallback(function (code) {
                console.log(TAG + ' BLOCKED ' + name + '(' + code + ')');
                send({ event: 'blocked', fn: name, code: code });
            }, 'void', ['int']));
            installed++;
            console.log(TAG + ' replace ' + name + ' @ ' + addr);
            return;
        } catch (e) {
            console.log(TAG + ' replace failed for ' + name + ': ' + e);
        }
    }

    Interceptor.attach(addr, {
        onEnter: function (args) {
            var code = (name === 'abort' || name === 'quick_exit') ? '(no arg)' : args[0].toInt32();
            console.log(TAG + ' ' + name + '(' + code + ') from:\n' + trace(this.context));
            send({ event: 'called', fn: name, code: code, trace: trace(this.context) });
        }
    });
    installed++;
    console.log(TAG + ' hook ' + name + ' @ ' + addr);
});

// syscall-level escape hatch: exit_group via raw syscall(2 / SYS_exit_group)
try {
    var sce = Module.getGlobalExportByName('syscall');
    if (sce !== null) {
        Interceptor.attach(sce, {
            onEnter: function (args) {
                var nr = args[0].toInt32();
                if (nr === 94 || nr === 93) { // arm64: 94 = exit_group, 93 = exit
                    console.log(TAG + ' raw syscall(' + nr + ') from:\n' + trace(this.context));
                    send({ event: 'syscall', nr: nr });
                }
            }
        });
        installed++;
        console.log(TAG + ' hook syscall @ ' + sce);
    }
} catch (e) { console.log(TAG + ' syscall hook failed: ' + e); }

console.log(TAG + ' installed ' + installed + ' hook(s), BLOCK=' + BLOCK);
