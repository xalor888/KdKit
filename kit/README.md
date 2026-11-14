# kuaidui-kit

Static + dynamic analysis kit for **`com.kuaiduizuoye.scan` 7.10.0 (1850)**
(7.7.2/1811 kept as the historical baseline under `work/apktool_out_772/`)
(快对 / 作业帮; 50.3 MB APK, 7 dex, compileSdk 35).

**New here? Start with [`ONBOARDING.md`](ONBOARDING.md)** — the 30-minute path that re-runs every conclusion.

Findings and evidence: [`../work/TRIAGE.md`](../work/TRIAGE.md) ·
Full usage manual: [`MANUAL.md`](MANUAL.md)

**One command per round: collect the whole evidence pack** — it runs four gates (acceptance,
cross-round drift, endpoint-surface baseline, tool selftest) and then writes capture + reports +
the module matrix under `work/packs/<tag>/` with an index:

```bash
python3 kit/scripts/evidence_pack.py --adb emulator-5558 --tag r37 --live --adb-b emulator-5556
#  -> work/packs/r37/{capture.txt,session_report.md,module_report.md,acceptance.{txt,json},
#                    device_compare.md,index.md}
```

**One command that turns a capture into a review document** (sections: endpoints, H5 bridge usage,
guard blocks, decrypted plaintext samples):

```bash
adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
python3 kit/python/session_report.py cap.txt --out work/session_report.md
```

**One command that re-checks everything this kit claims** (run it after any change):

```bash
python3 kit/scripts/acceptance.py --adb emulator-5558 --live
# PASS environment / module alive / config channel / capture / offline RC4 / offline sign /
#      api rebuild / live call / hook targets   ->  11/11 checks passed
#      (api rebuild asserts every URL whose `sign` reached the log rebuilds byte-exactly;
#       truncated URLs and non-URL signing inputs are listed as excluded, not passed silently)
```

```
kit/
  scripts/recon.sh           decode + .so extract + manifest/inventory summary (macOS)
  scripts/attach_probe.py    attach (or frida-spawn) the app and measure survival + death signature
  scripts/patch_device_lib.py  equal-length, in-place patch of an app's extracted .so (root, with backup)
  scripts/check_hook_targets.py  static gate: every KdKit hook target exists in the decoded APK
  scripts/env_up.sh          boot the project AVD correctly (magisk ramdisk!) + root + frida-server + status
  scripts/set_config.sh      put a device into a named module config (regular / diag / min)
  scripts/acceptance.py      ONE COMMAND end-to-end acceptance: env → module → capture → offline RC4/sign → live call
  scripts/tap_texts.py       drive a screen by visible text (uiautomator bounds, shortest-label match)
  scripts/module_report.py   per-feature runtime report: enabled? installed? how much evidence?
  scripts/compare_devices.py same kit on two devices: what is per-device vs per-app
  scripts/path_diff.py       same path on two devices (--repeat N) and as a baseline regression
                             (--save-baseline / --check-baseline)
  scripts/index_evidence.py  index work/ by topic -> work/INDEX.md (--check detects a stale index)
  scripts/report_timeline.py keep REPORT.md's per-round timeline in sync with ROADMAP.md
  scripts/daily_report.py    roll the round packs up into a day view (work/DAILY-<date>.md)
  scripts/session_snapshot.py freeze login/session state, and diff it after a real login
  scripts/next_round.py      read-only advisor: ranks the next actions from the current state
  scripts/tool_sanity.sh     rule 18 as a script: injects deliberate anomalies and checks the tools report them
  scripts/checkup.sh         one-command checkup (device + module + 8 surfaces + gates) — run this first in a new session
  scripts/recover_device.sh   the three-step device recovery (kill qemu -> clear AVD locks -> relaunch w/ ramdisk);
                              auto-detects and does nothing when the framework is healthy
  scripts/after_login.py     the three steps for the day an account exists (self-checks, exits 2 without one)
  scripts/call_page_js.py    make the host's pages run arbitrary JS (writes page_js_script; needs the page_js feature)
  scripts/page_internals.py  per-page Vue method-name snapshot (decides "page-side vs native-side";
                             the pack runs it every round -> a drift surface for page internals)
  scripts/host_pairing.py    given path candidates, try every known host -> hit matrix
                             (404 often just means "wrong host" -- see work/PARTNER_HOSTS.md)
  APK_REVERSE_NOTES.md        toolchain + the three deliberate deviations from the generic apk-reverse playbook
  scripts/switch_diff.py      feature-switch drift (45 flags): a flip = a feature went live/retired
  scripts/server_snapshot.py  value-level server drift: normalise each response, hash, compare with last pack
  scripts/sign_representation.py  is a request's signed representation the same as its URL form?
                                  (needs sign_observer; tells you whether verify/pull can be trusted)
  (the pack also writes work/REQ_HEADERS.md from req_headers: what the host actually sends)
  scripts/trend_report.py   all gates + disk size over time; flags regressions (green -> red)
  scripts/bridge_urls.py     classify every URL the H5 bridge carried (relative vs absolute)
  scripts/api_login_map.py   split the endpoint surface into guest-reachable vs never-seen
  scripts/api_health.py      run the guest sweep N times: which endpoints are actually stable
  scripts/catalog.py         what kinds of artifacts exist, how many, and which are generated
  scripts/coldstart_snapshot.py  behavioural baseline for the app's first 30 s (diff it later)
  scripts/verify_inputs.py   pin every conclusion to its inputs: sample APK / extracted .so / harness / module
  scripts/server_shape.py    server-side shape drift monitor (field sets + list sizes per endpoint)
  scripts/version_diff.py    compare two builds (mechanisms / path prefixes / bridge actions) from dex strings
                             (the pack runs it automatically when the device's installed app changes)
  scripts/drift_report.py    one page for all three drift surfaces (client / server / inputs)
  scripts/inject_test.py     do the monitors actually alarm? injects synthetic drift and checks
  scripts/race_test.py       cold-start the host and verify read-after-restart races stay tolerant
  scripts/reverify.py        one-command drift check: re-runs four early conclusions today
  scripts/selftest.py        smoke-test every kit tool (compile / --help / fixture run)
  scripts/feature_matrix.py  per-feature evidence strength -> module/VERIFICATION.md
  scripts/mem_read.py        read a live process's memory through root (hex + pointer follow)
  scripts/read_sign_inputs.py  read nativeGetSign's two runtime inputs (A/X) from a live install
  scripts/find_sign_strings.py brute-force which harvested strings reproduce a captured sign
  scripts/decode_token_native.py  offline sign reproduction from the two stored tokens (via the native oracle)
  harness/native/decode_token.c   tiny NDK oracle: calls libbaseutil's internal decode helpers (0x41e8/0x5ea0)
  drive.py                   spawn (optionally --post-load), capture messages to JSONL
  attach.py                  poll & attach, survives the app's self-restart
  hooks/
    _ready.js                shared helpers: KD.boot / KD.whenReady / KD.peek
    00_no_selfexit.js        block System.exit/Runtime.halt (app self-restart + attach-kill)
    01_rc4_helper.js         app-side crypto: yl.f (RC4Helper) decrypt/encrypt + live RC4 key
                           （H5 与 App 共用同一套 Java 实现 —— 钩的是 App 侧那一份，不是 H5 独有）
    02_net_sign.js           sign chain + RC4 key extraction
    03_native_baseutil.js    RegisterNatives hook into libbaseutil.so
    09_diag_exit.js          who calls exit / finish (stack traces)
    10_zygote_stealth.js     fake TracerPid for every app forked from zygote64
    11_native_exit_diag.js   libc exit/exit_group hooks + backtraces (observe or block)
    12_native_kill_trace.js  spawn-safe native tracer: teardown calls + /proc scanners
  python/kd_crypto.py        offline RC4 + Android-NO_WRAP base64 (nativeGetKey scheme)
  python/device_entry_crypto.py  the *static* device-id scheme (PackageHelper.ENTRY_KEY)
  python/decrypt_capture.py  offline decryptor for a KdKit SignObserver capture
  python/capture_transcript.py  capture -> readable timeline (RC4 lines decrypted in place)
  python/verify_rc4_capture.py  regression test: offline RC4 vs the app's own live RC4 calls
  python/safe_io.py           write-then-read-back helper (write_verified / append_verified) — turns "verify your writes"
                              from a discipline into a mechanism
  python/kd_api.py           rebuild signatures, call the real API, and batch-pull endpoints offline (verify/call/pull)
  python/bridge_inventory.py aggregate the H5BridgeLog capture into a live JS-bridge usage map
  python/guard_report.py     summarise what the module's bridge guard blocked (action / reason / host)
  python/session_report.py   ONE capture in, ONE markdown review out (endpoints / bridge / ad slots / guard / decrypted plaintext)
  python/extract_config.py   pull the config endpoints offline and render their structure (work/CONFIG_DUMP.md)
  python/extract_samples.py  show what *content* the guest state can actually fetch (work/CONTENT_SAMPLES.md)
  python/decrypt_strings.py  decrypt field-level strings (yl.f.n) — self-checks against the capture
  python/export_content.py   export guest-reachable content to structured files (work/exports/)
  python/probe_paths.py      probe endpoints mined from the APK's own string table (works per host, see docstring)
  harness/                   Java harness that drives the real libbaseutil.so
                             (bypasses the anti-debug entirely — see below)
```

Loading order matters — `_ready.js` must be in the *same* script as the hook
(Frida gives each script its own runtime). `drive.py` and `attach.py`
concatenate the files you pass for exactly that reason.

## 1. Static

```bash
./kit/scripts/recon.sh com.kuaiduizuoye.scan-7.10.0-1850-168194.apk
```

Decodes into `work/apktool_out` (smali + resources) and `work/jadx_out` (java),
extracts `lib/*/*.so` into `work/native`.

## 2. Dynamic — read this before fighting the emulator

**Updated 2026-10-11 (`work/dpsdk/FINDINGS.md`):** the app self-terminates on any Frida
contact through two layers — a readable Java watchdog (`lk.f` / `AntiDebugThread`,
neutralised by the KdKit `anti_detect` feature) and a native DProtect layer in
`libdpsdk.so` that is *not* neutralised (it exits the process cleanly with no Java
`System.exit` line, and under `spawn` the Frida agent itself dies). **Consequence: run
dynamic observation from inside the process with the KdKit module** (`sign_observer`
already ports hooks 01/02); the Frida hooks below remain for setups without the module.
Measure any attempt with `kit/scripts/attach_probe.py` — never trust "the log looked clean".

The app is **anti-instrumented**: libdpsdk.so (DProtect) reads `TracerPid` and
scans for `frida_server`, Xposed/Magisk and automation packages, and terminates
its own process on any attach. Verified: an attach with an *empty* script kills
it. Nothing in this kit can attach successfully until that detector is patched
(see TRIAGE.md §7).

What does work, and what the environment must look like:

```bash
export PATH="$HOME/Library/Android/sdk/platform-tools:$PATH"

# 1) emulator with real resources, otherwise the app misses its 10 s init
#    watchdog and self-restarts in a loop.
#    -ramdisk is REQUIRED: the stock ramdisk has no Magisk, so magiskd/vectord
#    never start and the module cannot inject.
emulator -avd test1 -port 5556 -no-window -no-audio -no-snapshot \
         -gpu swiftshader_indirect -no-boot-anim -memory 4096 -cores 4 \
         -ramdisk infra/ramdisk-magisk.img

# 2) root + permissive SELinux, or frida cannot see app processes at all
adb -s emulator-5556 root && adb -s emulator-5556 shell setenforce 0

# 3) frida-server under a non-default name/port
adb -s emulator-5556 push frida-server /data/local/tmp/xdsvc
adb -s emulator-5556 shell 'chmod 755 /data/local/tmp/xdsvc; nohup /data/local/tmp/xdsvc -l 0.0.0.0:31337 &'
adb -s emulator-5556 forward tcp:31337 tcp:31337

# 4) install with permissions pre-granted, then accept the in-app consent
adb -s emulator-5556 install -r -g com.kuaiduizuoye.scan-7.10.0-1850-168194.apk
```

Then, once the detector is patched:

```bash
frida -H 127.0.0.1:31337 -p "$(adb -s emulator-5556 shell pidof com.kuaiduizuoye.scan)" \
      -l <(cat kit/hooks/_ready.js kit/hooks/02_net_sign.js) -q
```

Gotchas baked into the scripts:

* `frida-ps` reports the app's **label** (`快对AI`), not the package, and
  `/proc/<pid>/comm` is truncated to `aiduizuoye.scan` — match by pid.
* the frida CLI validates pids through process enumeration, which is unreliable
  here; `attach.py --adb <serial>` uses `adb shell pidof` instead.
* spawn-gated scripts have **no Java bridge** (`typeof Java === 'undefined'`):
  load the agent at spawn, then `%resume` and only then load the hook
  (or use `drive.py --post-load N`).
* the app forks a fresh process on cold start; `attach.py` re-attaches to the new
  pid automatically.

## 3. Native: call the real antispam library

The app cannot be instrumented (libdpsdk.so kills it on attach), but
`libbaseutil.so` can be driven from our own process:

```bash
cd kit/harness && cat README.md      # build + run instructions
```

It returns, for a given install, the real **RC4 key** (`nativeGetKey`), the
random token (`nativeGetRandom`) and valid **request signatures**
(`nativeGetSign`). Details and the reconstructed algorithm:
[`../work/native_reversal.md`](../work/native_reversal.md).

## 4. Offline crypto

The RC4 key is produced in `libbaseutil.so` from the app versionCode plus device
state — capture it per install (printed by `02_net_sign.js`), then:

```bash
python3 kit/python/kd_crypto.py decrypt '<KEY>' '<base64 payload>'
python3 kit/python/kd_crypto.py encrypt '<KEY>' '{"hello":"world"}'
```

## Constraints worth remembering

* The RC4 key is **live data**, not a constant: it is derived inside
  `libbaseutil.so` from `signA`/`signB` (server challenge), `cuid`, the APK
  signing certificate and the versionCode. Use `kit/harness` to obtain it per
  install, or read it from a captured run.

* Request signatures (`sign=`, `_t_`, `kakorrhaphiophobia`) come from
  `libbaseutil.so nativeGetSign` and are bound to a server-issued challenge
  (`signA`/`signB` from `/pluto/app/antispam`); a pure-Java replay patch does not
  survive. Hook or reuse the real library.
* The app ships Robust hot-patching (`com.meituan.robust`): every app method body
  is wrapped in `PatchProxy.proxy(...)`, so if a patch has been applied at
  runtime the original body is not what executes.
