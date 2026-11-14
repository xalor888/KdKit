/*
 * kuaidui-kit / 02_net_sign.js
 * Target : com.kuaiduizuoye.scan 7.7.2 (1811)
 *
 * Request signature chain (see work/TRIAGE.md §3.1):
 *   Net.appendSign(InputBase)
 *     -> baseutil.a.d(List)  [adds _t_, kakorrhaphiophobia, sort, join, b64]
 *     -> NativeHelper.nativeGetSign  -> libbaseutil.so
 *   RC4 key: baseutil.a.b(versionCode) -> NativeHelper.nativeGetKey
 *
 * Run: frida -U -f com.kuaiduizuoye.scan -l _ready.js -l 02_net_sign.js
 */
var TAG = '[sign]';

KD.boot(function () {
    KD.whenReady('com.baidu.homework.common.net.Net', function (Net) {
        try {
            Net.appendSign.overload('com.baidu.homework.common.net.model.v1.common.InputBase')
                .implementation = function (input) {
                    var out = this.appendSign(input);
                    console.log(TAG + ' appendSign -> ' + out);
                    return out;
                };
            console.log(TAG + ' hooked Net.appendSign');
        } catch (e) { console.log(TAG + ' appendSign hook failed: ' + e); }
    }, TAG);

    KD.whenReady('com.zuoyebang.baseutil.a', function (BU) {
        try {
            BU.d.overload('java.util.List').implementation = function (list) {
                var snap = [];
                try { for (var i = 0; i < list.size(); i++) snap.push(String(list.get(i))); }
                catch (e) { snap = ['<unreadable>']; }
                var ret = this.d(list);
                console.log(TAG + ' SIGN PARAMS: ' + snap.join(' | '));
                console.log(TAG + ' SIGN RESULT: ' + ret);
                return ret;
            };
            console.log(TAG + ' hooked baseutil.a.d(List)');
        } catch (e) { console.log(TAG + ' d hook failed: ' + e); }

        try {
            BU.b.overload('java.lang.String').implementation = function (s) {
                var ret = this.b(s);
                console.log(TAG + ' *** RC4 KEY for "' + s + '" -> ' + ret);
                return ret;
            };
            console.log(TAG + ' hooked baseutil.a.b(String)');
        } catch (e) { console.log(TAG + ' b hook failed: ' + e); }

        try {
            BU.g.implementation = function () {
                var ret = this.g();
                console.log(TAG + ' baseutil isInitSuccess = ' + ret);
                return ret;
            };
        } catch (e) {}

        try {
            BU.f.implementation = function () {
                var ret = this.f();
                console.log(TAG + ' baseutil init() -> ' + ret);
                return ret;
            };
        } catch (e) {}
    }, TAG);
});
