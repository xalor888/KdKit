/*
 * kuaidui-kit / 01_rc4_helper.js
 * Class yl.f = "RC4Helper" (deobf p1865yl.C28915f)
 *   g(String) decrypt : b64decode -> RC4(field b) -> [gunzip]
 *   h(String) encrypt : b64( RC4(field b, utf8) )
 *   y()       updateKey
 * Run: frida -U -f com.kuaiduizuoye.scan -l _ready.js -l 01_rc4_helper.js
 */
var TAG = '[rc4]';

KD.boot(function () {
    KD.whenReady('yl.f', function (Helper) {
        try {
            var inst = Helper.u();
            console.log(TAG + ' live RC4 key = ' + inst.b.value);
        } catch (e) { console.log(TAG + ' key read failed: ' + e); }

        try {
            Helper.y.implementation = function () {
                this.y();
                try { console.log(TAG + ' updateKey() -> key = ' + this.b.value); } catch (e) {}
            };
        } catch (e) {}

        try {
            Helper.g.overload('java.lang.String').implementation = function (s) {
                var r = this.g(s);
                console.log(TAG + ' DECRYPT in=' + KD.peek(s) + ' out=' + KD.peek(r));
                return r;
            };
        } catch (e) { console.log(TAG + ' g hook failed: ' + e); }

        try {
            Helper.h.overload('java.lang.String').implementation = function (s) {
                var r = this.h(s);
                console.log(TAG + ' ENCRYPT in=' + KD.peek(s) + ' out=' + KD.peek(r));
                return r;
            };
        } catch (e) {}

        try {
            Helper.l.overload('java.lang.String').implementation = function (s) {
                var r = this.l(s);
                console.log(TAG + ' b64-only out=' + KD.peek(r));
                return r;
            };
        } catch (e) {}

        console.log(TAG + ' hooks installed');
    }, TAG);
});
