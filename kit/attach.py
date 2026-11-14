#!/usr/bin/env python3
"""
kuaidui-kit / attach.py — poll-and-attach loop with auto re-attach.

Why not `frida -U -p PID`:
  * the CLI needs 2-4 s to boot, and this app self-restarts on cold start, so
    by the time the CLI is up the pid is already gone ("process not found");
  * spawn gating is unusable here: the Java bridge is not live when the script
    is loaded into a spawn-gated process.

So: start this first, let it poll, and launch the app afterwards. It attaches
within ~300 ms of the process appearing and re-attaches across the app's
self-restart.

    python3 attach.py <device> <package|pid> <seconds> <out.jsonl> [--adb SERIAL] hook1.js ...
        --adb SERIAL : poll `adb shell pidof` (survives the app's self-restart)
"""
import json
import sys
import time

import frida


def main(argv):
    if len(argv) < 5:
        print(__doc__)
        return 1
    devid, target, secs, out = argv[1], argv[2], float(argv[3]), argv[4]
    files = argv[5:]
    # target is either a package name (poll + attach) or an explicit pid.
    # NOTE: the frida CLI can't attach here — it validates the pid through
    # device.enumerate_processes(), which is unreliable on this emulator and
    # reports "process not found". attach(pid) directly works fine.
    pinned_pid = int(target) if target.isdigit() else None
    pkg = None if pinned_pid else target
    # --adb <serial>: track the pid through `adb shell pidof`, which stays
    # correct across the app's self-restart. A pinned pid goes stale the moment
    # the app restarts, which is the normal case here.
    adb = None
    if '--adb' in files:
        i = files.index('--adb')
        adb = files[i + 1]
        del files[i:i + 2]

    dev = frida.get_device(devid, timeout=10)
    src = '\n;\n'.join(open(f).read() for f in files)
    sink = open(out, 'w')

    def on_message(msg, data):
        sink.write(json.dumps(msg, default=str) + '\n')
        sink.flush()
        t = msg.get('type')
        if t == 'send':
            print('[app] ' + str(msg['payload']), flush=True)
        elif t == 'log':
            print('[log] ' + str(msg.get('payload')), flush=True)
        elif t == 'error':
            print('[err] ' + str(msg.get('description')), flush=True)

    print(f"[attach] device={dev.name} target={target} ...", flush=True)
    live = {}
    deadline = time.time() + secs
    while time.time() < deadline:
        try:
            allprocs = dev.enumerate_processes()
        except Exception as e:
            allprocs = []
            print('[attach] enumerate failed: ' + str(e), flush=True)
        if adb is not None:
            import subprocess
            out = subprocess.run(['adb', '-s', adb, 'shell', 'pidof', pkg],
                                 capture_output=True, text=True, timeout=300).stdout.split()
            procs = [type('P', (), {'pid': int(x), 'name': pkg})() for x in out if x.isdigit()]
        elif pinned_pid is not None:
            procs = [p for p in allprocs if p.pid == pinned_pid] or [type('P', (), {'pid': pinned_pid, 'name': str(pinned_pid)})()]
        else:
            procs = [p for p in allprocs if p.name == pkg or pkg in str(p.name)]
        for p in procs:
            if p.pid in live:
                continue
            try:
                ses = dev.attach(p.pid)
                sc = ses.create_script(src)
                sc.on('message', on_message)
                sc.load()
                live[p.pid] = (ses, sc)
                print(f"[attach] attached pid={p.pid} ({time.strftime('%H:%M:%S')})", flush=True)
            except Exception as e:
                print(f"[attach] pid={p.pid} attach failed: {e}", flush=True)
        time.sleep(0.3)

    sink.close()
    print(f"[attach] done, sessions={list(live)} -> {out}", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
