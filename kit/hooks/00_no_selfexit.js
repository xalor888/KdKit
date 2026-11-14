/*
 * kuaidui-kit / 00_no_selfexit.js
 * Load this FIRST when instrumenting after spawn.
 *
 * com.kuaiduizuoye.scan terminates and re-launches its own process during cold
 * start ("AndroidRuntime: VM exiting with result code 0"). When Frida spawn-gates
 * the first process that self-exit destroys the session, so nothing can be
 * hooked. Neutralising the exit calls keeps the original process alive.
 *
 * Since 2026-10-11 it also survives a plain attach: the DProtect detector calls
 * `System.exit(0)` ~1.5-4 s AFTER the agent is injected, so a script that wins
 * that race keeps the process alive. It therefore boots itself through KD.boot
 * when _ready.js is present (concatenate the two files) and falls back to a
 * bare Java.perform when it is not.
 */
var TAG = '[keepalive]';

function kdInstall() {
    function stack() {
        try {
            return Java.use('android.util.Log').getStackTraceString(Java.use('java.lang.Throwable').$new());
        } catch (e) { return '<no stack: ' + e + '>'; }
    }
    var S = Java.use('java.lang.System');
    S.exit.overload('int').implementation = function (c) {
        console.log(TAG + ' blocked System.exit(' + c + ')\n' + stack());
        return;
    };
    var R = Java.use('java.lang.Runtime');
    R.exit.overload('int').implementation = function (c) {
        console.log(TAG + ' blocked Runtime.exit(' + c + ')\n' + stack());
        return;
    };
    R.halt.overload('int').implementation = function (c) {
        console.log(TAG + ' blocked Runtime.halt(' + c + ')\n' + stack());
        return;
    };
    try {
        var P = Java.use('android.os.Process');
        P.killProcess.overload('int').implementation = function (pid) {
            console.log(TAG + ' blocked Process.killProcess(' + pid + ')\n' + stack());
            return 0;
        };
    } catch (e) {}
    console.log(TAG + ' self-exit blocked');
}

if (typeof KD !== 'undefined' && KD.boot) {
    KD.boot(kdInstall);
} else {
    Java.perform(kdInstall);
}
