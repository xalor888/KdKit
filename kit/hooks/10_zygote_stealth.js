/*
 * kuaidui-kit / 10_zygote_stealth.js
 *
 * WHY: com.kuaiduizuoye.scan kills its own process the moment anything ptrace-
 * attaches to it. libdpsdk.so contains the literal "TracerPid", i.e. it reads
 * /proc/self/status and exits if TracerPid != 0. Instrumenting the app directly
 * is therefore a chicken-and-egg problem: attach triggers the check, the app
 * exits, and the session dies before any Java hook can run.
 *
 * THIS FILE: run it on **zygote64** (native only, no Java). Every app process
 * forked afterwards inherits the Interceptor hooks, so the app's own status
 * read returns "TracerPid:\t0" and it never notices the debugger.
 *
 *   frida -H 127.0.0.1:31337 -p $(adb shell pidof zygote64) -l 10_zygote_stealth.js
 *
 * Revert by restarting the emulator / zygote. Affects every app forked from
 * this zygote until then.
 */
var TAG = '[zygote-stealth]';
var libc = Process.getModuleByName('libc.so');
var watched = {};
var installed = [];

function hookOpen(name, pathArg) {
    var p = libc.findExportByName(name);
    if (!p) return;
    Interceptor.attach(p, {
        onEnter: function (a) {
            try {
                var q = a[pathArg];
                this.path = q.isNull() ? null : q.readCString();
            } catch (e) { this.path = null; }
        },
        onLeave: function (ret) {
            var fd = ret.toInt32();
            if (fd >= 0 && this.path && this.path.indexOf('/proc/') === 0 && this.path.indexOf('status') >= 0) {
                watched[fd] = 1;
                console.log(TAG + ' watching fd ' + fd + ' <- ' + this.path);
            }
        }
    });
    installed.push(name);
}

function hookRead() {
    var p = libc.findExportByName('read');
    if (!p) return;
    Interceptor.attach(p, {
        onEnter: function (a) {
            this.fd = a[0].toInt32();
            this.buf = a[1];
        },
        onLeave: function (ret) {
            var n = ret.toInt32();
            if (n <= 0 || !watched[this.fd]) return;
            try {
                var s = this.buf.readUtf8String(n);
                var i = s.indexOf('TracerPid:');
                if (i < 0) return;
                var nl = s.indexOf('\n', i);
                var line = s.substring(i, nl < 0 ? s.length : nl);
                var clean = line.replace(/[0-9]/g, '0');   // same length, in-place
                // **必须逐字节写回，不能用 `writeUtf8String`**（2026-11-03 修）。
                //
                // `writeUtf8String(s)` 写的是 `s` **再加一个 NUL 终止符**。
                // 于是 `i + clean.length` 那一字节 —— 原本是这一行结尾的 `\n` ——
                // 被 NUL 覆盖，`/proc/self/maps` 变成：
                //     TracerPid:\t0\0Uid:\t…
                // 应用按 `\n` 切行时，会把这两行**并成一行**。
                // 有些解析器无所谓，有些会连 `Uid` 都读不出来 ——
                // 于是“TracerPid 伪造成功”这件事变得**不可靠**，
                // 而现象是偶发的退出，与“没伪装住”一模一样。
                //
                // `writeByteArray` 写**正好**这些字节，一个不多。
                var bytes = [];
                for (var k = 0; k < clean.length; k++) bytes.push(clean.charCodeAt(k) & 0xFF);
                this.buf.add(i).writeByteArray(bytes);
            } catch (e) {}
        }
    });
    installed.push('read');
}

hookOpen('open', 0);
hookOpen('openat', 2);
hookRead();
console.log(TAG + ' installed: ' + installed.join(',') + ' — apps forked from here on report TracerPid: 0');
