/*
 * kuaidui-kit / _ready.js — shared helpers for every hook in this directory.
 *
 * Frida gives each script its own runtime, so helpers must live in the SAME
 * script as the hook (drive.py concatenates them).
 *
 * boot() exists because `Java` does not exist yet when a script is loaded into
 * a spawn-gated process: touching the identifier at top level throws
 * "ReferenceError: 'Java' is not defined". boot() polls until the bridge is
 * there, then hands control to the hook.
 */
var KD = {
    MAX: 200,
    peek: function (s) {
        if (s === null || s === undefined) return String(s);
        s = String(s);
        return s.length > KD.MAX ? s.substring(0, KD.MAX) + ' ...(' + s.length + ')' : s;
    },
    boot: function (fn, tries) {
        tries = tries || 0;
        if (typeof Java === 'undefined') {
            if (tries > 600) { console.log('[kd] Java bridge never appeared'); return; }
            setTimeout(function () { KD.boot(fn, tries + 1); }, 250);
            return;
        }
        Java.perform(function () {
            try {
                fn();
            } catch (e) {
                console.log('[kd] hook crashed: ' + e);
            }
        });
    },
    whenReady: function (className, cb, tag, tries) {
        tries = tries || 0;
        try {
            var C = Java.use(className);
            if (tries) console.log(tag + ' ' + className + ' appeared after ' + tries + ' polls');
            cb(C);
            return;
        } catch (e) {
            if (tries && tries % 20 === 0) console.log(tag + ' waiting for ' + className + ' (poll ' + tries + ')');
            if (tries > 1200) { console.log(tag + ' giving up on ' + className + ': ' + e); return; }
            setTimeout(function () { KD.whenReady(className, cb, tag, tries + 1); }, 500);
        }
    }
};
