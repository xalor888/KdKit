/*
 * kuaidui-kit / 09_diag_exit.js
 * Diagnostics: who terminates the process / finishes the activity.
 * The app exits itself ~28 s after a cold start on a fresh emulator, so this
 * prints the Java stack for every exit-ish call.
 */
var TAG = '[diag]';
KD.boot(function () {
    function stack() {
        try {
            return Java.use('android.util.Log').getStackTraceString(Java.use('java.lang.Throwable').$new());
        } catch (e) { return '<no stack: ' + e + '>'; }
    }
    var S = Java.use('java.lang.System');
    S.exit.overload('int').implementation = function (c) {
        console.log(TAG + ' System.exit(' + c + ')\n' + stack());
        return this.exit(c);
    };
    var R = Java.use('java.lang.Runtime');
    ['exit', 'halt'].forEach(function (m) {
        try {
            R[m].overload('int').implementation = function (c) {
                console.log(TAG + ' Runtime.' + m + '(' + c + ')\n' + stack());
                return this[m](c);
            };
        } catch (e) {}
    });
    var P = Java.use('android.os.Process');
    ['killProcess', 'killProcessQuiet'].forEach(function (m) {
        try {
            P[m].overload('int').implementation = function (pid) {
                console.log(TAG + ' Process.' + m + '(' + pid + ')\n' + stack());
                return this[m](pid);
            };
        } catch (e) {}
    });
    try {
        var A = Java.use('android.app.Activity');
        A.finish.overload().implementation = function () {
            console.log(TAG + ' Activity.finish() ' + this.getClass().getName());
            return this.finish();
        };
    } catch (e) {}
    console.log(TAG + ' exit diagnostics installed');
});
