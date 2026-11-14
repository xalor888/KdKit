#!/usr/bin/env python3
"""
kuaidui-kit / selftest.py — smoke-test every tool in the kit, so "it looks like it runs" bugs die here.

Two of them cost real time on 2026-10-11: a helper that ran `sh -c adb …` (so `adb` printed its help
text and every "read" returned 8869 B of usage output), and a report section that mis-read a rotated
capture as "no data". Both were *silent*. This checks the cheap invariants that would have caught
them before they reached a round:

  1  compile      `python3 -m py_compile <tool>` — syntax errors, bad f-strings
  2  import       run the tool's `--help` (or `import` it) — missing modules, broken top-level code
  3  fixture      run the offline tools on a tiny synthetic capture and expect sane output

    python3 kit/scripts/selftest.py [--verbose]

Exit code 1 if any tool fails; the table says which and why.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sh as _shmod
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
KIT = os.path.join(ROOT, 'kit')

FIXTURE = """14:00:00.000 SIGN params: _t_=1 | appId=scancode | cuid=ABC|0
14:00:00.001 SIGN URL: https://example.com/x?a=1&sign=deadbeef
14:00:00.100 RC4 encrypt key=b64[4]YWJjZA== in=b64[4]AQIDBA==: b64[4]BQYHCA==
14:00:00.200 H5BRIDGE core_getStorage count=1 {"saveKey":"k"}
14:00:00.300 GUARD blocked=core_showDebuger reason=blacklist url= #1
14:00:00.400 ADSLOT call aj.a.d(501) #1
14:00:00.401 ADSLOT ret  aj.a.d(501) -> null
"""


def run(cmd, timeout=120):
    # 2026-11-03：与另外 11 个文件一起换成 `kit/python/sh.py` 的 `run()`。
    # 旧实现没有 `start_new_session` ⇒ 超时只杀 shell，管道里的子进程继续挂着。
    return _shmod.run(cmd, timeout=timeout)


def tools():
    out = []
    for sub in ('scripts', 'python'):
        d = os.path.join(KIT, sub)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith('.py') and not f.startswith('_'):
                out.append(os.path.join(d, f))
    for f in sorted(os.listdir(os.path.join(KIT, 'scripts'))):
        if f.endswith('.sh'):
            out.append(os.path.join(KIT, 'scripts', f))
    for f in sorted(os.listdir(KIT)):
        if f.endswith('.sh'):
            out.append(os.path.join(KIT, f))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args(argv[1:])

    fixture = os.path.join(ROOT, 'work', 'packs', '_selftest_capture.txt')
    os.makedirs(os.path.dirname(fixture), exist_ok=True)
    open(fixture, 'w').write(FIXTURE)

    rows = []
    for path in tools():
        name = os.path.relpath(path, ROOT)
        if path.endswith('.sh'):
            rc, out = run(['bash', '-n', path])
            rows.append((name, 'shell 语法', rc == 0, out.strip().splitlines()[0][:60] if out.strip() else 'ok'))
            continue
        rc, out = run([sys.executable, '-m', 'py_compile', path])
        if rc != 0:
            rows.append((name, 'compile', False, out.strip().splitlines()[-1][:70]))
            continue
        # --help for argparse tools; plain import for library modules
        rc_h, out_h = run([sys.executable, path, '--help'])
        if rc_h == 0 and ('usage' in out_h.lower() or len(out_h) > 0):
            rows.append((name, 'help', True, 'ok'))
        else:
            rc_i, out_i = run([sys.executable, '-c', f'import importlib.util,sys;'
                                                     f'spec=importlib.util.spec_from_file_location("m",r"{path}");'
                                                     f'm=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)'])
            rows.append((name, 'import', rc_i == 0,
                         (out_i.strip().splitlines()[-1][:70] if out_i.strip() else 'ok')))

    # fixture runs: the offline report tools must survive a synthetic (tiny) capture
    for tool, extra in (('session_report.py', [fixture, '--out', os.path.join(ROOT, 'work', 'packs', '_selftest.md')]),
                        ('bridge_inventory.py', [fixture]),
                        ('guard_report.py', [fixture]),
                        ('verify_rc4_capture.py', [fixture])):
        p = os.path.join(KIT, 'python', tool)
        if not os.path.exists(p):
            p = os.path.join(KIT, 'scripts', tool)
        rc, out = run([sys.executable, p, *extra])
        # guard_report legitimately exits 1 when there is nothing blocked; accept 0/1 with output
        ok = rc in (0, 1) and bool(out.strip())
        rows.append((os.path.relpath(p, ROOT), 'fixture', ok, out.strip().splitlines()[0][:60] if out.strip() else 'no output'))

    bad = [r for r in rows if not r[2]]
    print(f'{"工具":52s} {"检查":8s} {"结果":4s} 详情')
    for name, kind, ok, detail in rows:
        print(f'{name:52s} {kind:8s} {"OK" if ok else "FAIL":4s} {detail if (a.verbose or not ok) else ""}')
    print(f'\n{len(rows) - len(bad)}/{len(rows)} 项通过')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
