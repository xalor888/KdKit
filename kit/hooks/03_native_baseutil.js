/*
 * kuaidui-kit / 03_native_baseutil.js
 * Target : libbaseutil.so  (JNI class com/zuoyebang/baseutil/NativeHelper)
 *
 * Why this file: the JNI methods are registered dynamically via
 * RegisterNatives, so they have NO exported symbol in the ELF and cannot be
 * reached with Module.getExportByName. We intercept art::JNI::RegisterNatives
 * instead, keep the pointers registered from libbaseutil.so, and attach to
 * them so the original implementation is still called.
 *
 * Native API
 *   nativeInitBaseUtil(Context, cuid)                  -> signA (server challenge seed)
 *   nativeSetToken(Context, cuid, signA, signB)        -> bool  (antispam ready)
 *   nativeGetKey(String: versionCode)                  -> RC4 key
 *   nativeGetSign(String: base64(sorted params))       -> request signature
 *   nativeGetRandom()                                  -> random token
 *
 * Run : frida -U -f com.kuaiduizuoye.scan -l 03_native_baseutil.js
 *       (needs qemu/arm64 device; works on emulator too)
 */
var TAG = '[native]';
var wanted = {
    'nativeInitBaseUtil': true,
    'nativeSetToken': true,
    'nativeGetKey': true,
    'nativeGetSign': true,
    'nativeGetRandom': true
};

function readJString(env, jstr) {
    if (jstr.isNull()) return null;
    try {
        return Java.vm.getEnv().getStringUtfChars(jstr, null).readCString();
    } catch (e) {
        return '<unreadable>';
    }
}

function findRegisterNatives() {
    var libart = Process.findModuleByName('libart.so');
    if (!libart) return null;
    var hit = null;
    libart.enumerateExports().forEach(function (e) {
        // _ZN3art3JNI15RegisterNativesEP7_JNIEnvP7_jclassPK15JNINativeMethodi
        if (!hit && e.name.indexOf('RegisterNatives') !== -1 && e.name.indexOf('JNI') !== -1) {
            hit = e.address;
        }
    });
    return hit;
}

function main() {
    var reg = findRegisterNatives();
    if (!reg) {
        console.log(TAG + ' art::JNI::RegisterNatives not found — is Frida talking to ART?');
        return;
    }
    console.log(TAG + ' RegisterNatives @ ' + reg);

    Interceptor.attach(reg, {
        onEnter: function (args) {
            var caller = Process.findModuleByAddress(this.returnAddress);
            if (!caller || caller.name.indexOf('libbaseutil.so') === -1) return;

            var env = args[0];
            var klass = args[1];
            var methods = args[2];
            var count = args[3].toInt32();
            this.pending = [];
            for (var i = 0; i < count; i++) {
                var base = methods.add(i * 3 * Process.pointerSize);
                var name = base.readPointer().readCString();
                var sig = base.add(Process.pointerSize).readPointer().readCString();
                var fn = base.add(2 * Process.pointerSize).readPointer();
                if (!wanted[name]) continue;
                this.pending.push({ name: name, sig: sig, fn: fn });
            }
        },
        onLeave: function () {
            var self = this;
            (self.pending || []).forEach(function (m) {
                console.log(TAG + ' registering ' + m.name + m.sig + ' @ ' + m.fn);
                try {
                    Interceptor.attach(m.fn, {
                        onEnter: function (a) {
                            this.fn = m.name;
                            this.a0 = readJString(a[0], a[2]); // note: arg order varies, logged raw
                            this.a1 = readJString(a[0], a[3]);
                            this.a2 = readJString(a[0], a[4]);
                        },
                        onLeave: function (ret) {
                            console.log(TAG + m.name + ' args=[' + this.a0 + ', ' + this.a1 + ', ' + this.a2 + '] ret=' + ret);
                        }
                    });
                } catch (e) {
                    console.log(TAG + ' attach failed for ' + m.name + ': ' + e);
                }
            });
        }
    });
    console.log(TAG + ' waiting for libbaseutil.so to self-register ...');
}

setImmediate(main);
