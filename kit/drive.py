#!/usr/bin/env python3
"""
kuaidui-kit / drive.py — headless Frida driver for spawn-time hooking.

Frida gives every script its own JS runtime, so helpers defined in
hooks/_ready.js are invisible to a separately-loaded hook. This driver
concatenates the given files into ONE script, keeping `KD` shared.

    python3 drive.py <package> <seconds> <out.jsonl> [--noscript] [--device ID] hook_a.js ...
        --noscript    : only launch, don't inject (startup / crash triage)
        --device ID   : target a specific device, e.g. emulator-5556
        --post-load N : resume, wait N seconds, then load the hook script

Prints a live console mirror and writes JSONL (level/message + console lines).
"""
import json
import sys
import time

try:
    import frida
except ImportError:
    sys.exit("pip3 install frida  (frida tools are installed but the module is missing)")


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 1
    pkg, secs, out = argv[1], float(argv[2]), argv[3]
    rest = argv[4:]
    noscript = '--noscript' in rest
    devid = None
    post_load = 0.0
    if '--device' in rest:
        i = rest.index('--device')
        devid = rest[i + 1]
        del rest[i:i + 2]
    if '--post-load' in rest:
        i = rest.index('--post-load')
        post_load = float(rest[i + 1])
        del rest[i:i + 2]
    files = [f for f in rest if f != '--noscript']

    dev = frida.get_device(devid, timeout=10) if devid else frida.get_usb_device(timeout=10)
    print(f"[drive] device  : {dev.name}")
    if not noscript:
        print(f"[drive] scripts : {', '.join(files)}")

    pid = dev.spawn([pkg])
    print(f"[drive] spawned {pkg} pid={pid}")
    session = dev.attach(pid)
    sink = open(out, 'w')

    def on_message(msg, data):
        line = json.dumps(msg, default=str)
        sink.write(line + '\n')
        sink.flush()
        t = msg.get('type')
        if t == 'send':
            print(f"[app] {msg['payload']}", flush=True)
        elif t == 'log':
            print(f"[log] {msg.get('payload')}", flush=True)
        elif t == 'error':
            print(f"[err] {msg.get('description')}", flush=True)
            print(msg.get('stack', ''), flush=True)

    dev.resume(pid)
    print("[drive] resumed", end='', flush=True)

    if post_load:
        # Spawn-gated loading has no live Java bridge (typeof Java === undefined
        # until the VM exists). Resuming first and only then creating the script
        # is what makes Java hooks work on this target.
        time.sleep(post_load)
        print(f", waited {post_load:.0f}s", end='', flush=True)
    print(f", loading script and capturing {secs:.0f}s ...")

    script = None
    if not noscript:
        src = '\n;\n'.join(open(f).read() for f in files)
        script = session.create_script(src)
        script.on('message', on_message)
        script.load()
    try:
        time.sleep(secs)
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()
        try:
            session.detach()
        except Exception:
            pass
    print(f"[drive] done -> {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
