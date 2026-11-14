#!/usr/bin/env python3
"""
kuaidui-kit / run_negative_controls.py — 每一道门禁都必须被证明**有能力变红**。

### 为什么需要它

今天（2026-11-02）在 `STATE.md` 里写了 **44 处"负对照"** —— 每一处都是
"故意注入一个故障，看门禁是否真的红"。这些验证是今天最有价值的工作：
它们证明了门禁不是装饰。

但它们全是**手工跑的**，跑完只留在文字里。后果：

* 没有人在下一轮再跑一遍；
* 门禁被改坏（比如正则的范围变窄、判据被换成"永远成立"）时，
  **没有任何东西会报警** —— 因为门禁自己还是绿的；
* 今天已经抓到两次"检查在错误环境下仍然通过"（`test_acceptance_skip_state`
  没设 `cwd`、`check_doc_commands` 把 `.py` 换成解释器后不再查脚本路径）。

**"一道永远不可能红的门禁，比没有门禁更糟"** —— 这句今天写了不止一次，
那就该让它可执行。

### 它做什么

对每一道门禁：注入一个**已知的、对应的**故障 ⇒ 断言退出码非 0 ⇒ 还原。
任何一道"注入了故障却仍然绿"，就是那道门禁已经失效。

    python3 kit/scripts/run_negative_controls.py            # 跑全部
    python3 kit/scripts/run_negative_controls.py --only ⑱   # 只跑一道
退出码：0 = 每一道都被证明能红；1 = 有门禁注入了故障却不红。
"""
import glob
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import atexit
import negctl_state
import argparse
import json
import os
import shutil
import time
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PASS_CACHE = os.path.join(ROOT, 'work', 'negctl_last_pass.json')
PASS_CACHE_HOURS = 24


def src_fingerprint():
    """负对照会改这些文件 ⇒ 它们的内容就是"要不要重跑"的判据。"""
    import hashlib
    h = hashlib.sha256()
    # 只覆盖**门禁判据**本身：负对照证明的是"这些脚本能红"。
    # 早先把 `kit/**/*.py` 全含进去，于是改任何分析工具（`bridge_shape_diff.py`）都会让
    # 2 小时的全量作废 —— 那是把无关变动当成了"判据可能变了"（2026-11-09 实测：一次
    # verify 因此跑了 9 分钟还没到 ㉖，把整条链堵死）。
    # **只看"门禁判据本身"**：CASES 里被跑的那些脚本（`check_*.py` / `*.sh`）+ 本文件。
    #
    # 两轮试错的结论（2026-11-09）：
    # ① 含 `module/scripts/*.sh` ⇒ 改 `verify.sh`（编排，不是判据）就让 2 h 全量作废；
    # ② 改成"CASES 的**注入目标**"（`c[2]`）也不行 —— 那里面混着 `work/INDEX.md`、
    #    `module/README.md`、`module/PARADIGM.md`、`work/CORE_HTTP_REQUESTS.md`，
    #    每次重建索引/改文档都会变 ⇒ 缓存永远失效，㉖ 永远跑满 2 h（本轮实测）。
    # 注入目标变了只会让"锚点失配"，那由工具自己报 `?`；**判据脚本变了才需要重新证明**。
    cmds = []
    for c in CASES:
        if len(c) >= 6 and isinstance(c[5], list):
            cmds.extend(x for x in c[5] if isinstance(x, str) and x.endswith(('.py', '.sh')))
    targets = sorted({x for x in cmds if x.startswith(('kit/', 'module/'))})
    paths = [os.path.join(ROOT, 'kit/scripts/run_negative_controls.py')] + \
            [os.path.join(ROOT, x) for x in targets]
    for f in paths:
        if not os.path.exists(f):
            continue
        rel = os.path.relpath(f, ROOT)
        h.update(rel.encode())
        with open(f, 'rb') as fh:
            h.update(fh.read())
    return h.hexdigest()


def _unused_pat_loop():
    for pat in ():
        for f in sorted(glob.glob(os.path.join(ROOT, pat), recursive=True)):
            rel = os.path.relpath(f, ROOT).replace('\\', '/')
            if '__pycache__' in rel or '/build/' in rel:
                continue
            h.update(rel.encode())
            with open(f, 'rb') as fh:
                h.update(fh.read())
    return h.hexdigest()


def read_pass_cache():
    try:
        with open(PASS_CACHE, encoding='utf-8') as f:
            d = json.load(f)
        return float(d.get('ts', 0)), int(d.get('passed', 0)), d.get('fingerprint')
    except Exception:
        return 0.0, 0, None


def write_pass_cache(fp, passed, total):
    try:
        os.makedirs(os.path.dirname(PASS_CACHE), exist_ok=True)
        with open(PASS_CACHE, 'w', encoding='utf-8') as f:
            json.dump({'fingerprint': fp, 'ts': time.time(), 'passed': passed,
                       'total': total}, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f'[negctl] 缓存写入失败（不影响结论）：{e}', file=sys.stderr)

PY = sys.executable

#: (门禁名, 说明, 要改的文件, 原串, 替换串, 检查命令)
#:
#: 每个注入都对应**今天真实踩过或真实防住**的那个故障。
#: 文件改动一律"改一个字符串再改回来"，且有 try/finally 保证还原。
CASES = [
    ('⑱ 门禁表一致', '文档里少一行',
     'module/PARADIGM.md', '| ⑲ | 热路径重复计算 |', '| ⑲x | 热路径重复计算 |',
     [PY, 'kit/scripts/check_gate_table.py']),
    ('⑫ shell 变量边界', '${var} 退回 $var',
     'module/scripts/verify.sh', 'FAIL  ${name}（--accept 里含 1', 'FAIL  $name（--accept 里含 1',
     [PY, 'kit/scripts/check_shell_vars.py', '--strict']),
    ('⑰ shell 管道陷阱', 'tee 与 grep -q 同管',
     'kit/scripts/after_login.sh', 'say "· 会员面：',
     'x=$(bash y.sh 2>&1 | tee /tmp/z.log | grep -q "^  PASS")\nsay "· 会员面：',
     [PY, 'kit/scripts/check_shell_pipes.py']),
    ('⑲ 热路径（正则在热路径）', '正则退回现算',
     'module/app/src/main/java/dev/xalor/kdkit/util/NavFilter.kt',
     'fun isAsset(url: String): Boolean = ASSET_RX.containsMatchIn(url)',
     'fun isAsset(url: String): Boolean =\n        Regex("a").containsMatchIn(url)',
     [PY, 'kit/scripts/check_hot_path.py']),
    ('⑲ 热路径（记忆点退化）', 'listMemo 被改名',
     'module/app/src/main/java/dev/xalor/kdkit/features/host/BridgeGuard.kt',
     'listMemo', 'someOtherThing',
     [PY, 'kit/scripts/check_hot_path.py']),
    ('⑳ 写入前缀有规则', '新前缀没有解析规则',
     'module/app/src/main/java/dev/xalor/kdkit/util/Capture.kt',
     'fun mark(line: String) = append("=== $line")',
     'fun mark(line: String) = append("=== $line")\n\n    fun zz(l: String) = append("ZZFAULT $l")',
     [PY, 'kit/scripts/check_writer_prefixes.py']),
    ('㉑ 抓取行全部认领', '一行没有规则',
     None, None, None,
     [PY, 'kit/scripts/check_capture_claimed.py', '--capture', 'ZZCAPZZ']),
    ('㉔ --accept 守卫', '守卫被删掉',
     'module/scripts/verify.sh',
     '  if [[ "$accept" == *" 1 "* ]]; then',
     '  if false; then',
     ['bash', 'kit/scripts/check_gate_accept_guard.sh']),
    ('㉕ 文档命令可执行', '脚本名写错',
     'module/PARADIGM.md', '`../kit/scripts/check_shell_pipes.py`',
     '`../kit/scripts/check_shell_pipes_typo.py`',
     [PY, 'kit/scripts/check_doc_commands.py']),
    ('㉒ 方法纪律', 'shell=True 不带进程组',
     'kit/scripts/server_shape.py', 'start_new_session=True).stdout', ').stdout',
     [PY, 'kit/scripts/methodology_check.py', '--paths', 'kit', 'module']),
    # 新增（2026-11-04）：`kd_api._need_printable` 变成"永远放行" ⇒
    # `test_kd_api_blob_shape` 必须红。证明的是**那条新测试不是摆设**。
    ('①b 抓取解析器', 'blob 字符类校验被关掉',
     'kit/python/kd_api.py',
     "    bad = [(i, b) for i, b in enumerate(raw) if not (0x20 <= b <= 0x7e)]",
     "    bad = []   # 负对照：故意永不报错",
     [PY, 'kit/scripts/test_run.py', '--ensure', '--quiet']),
    # 2026-11-04：SIGN URL 提取收敛后，再加一处未标注的写法必须变红
    # 2026-11-04：把 capture_transcript 里那个死掉的 POPWIN 分支加回去 ⇒ 必须红
    # 2026-11-04：把 AntiDetect 的 gate 去掉 ⇒ ㉪ 必须红
    # 2026-11-04：删掉 `Xp.hook` 一个回调里的 gate 判据 ⇒ ㉫ 必须红
    ('㉫ gate 判据只一处', '删掉一个回调里的 gate 判据',
     'module/app/src/main/java/dev/xalor/kdkit/util/Xp.kt',
     "                override fun beforeHookedMethod(param: MethodHookParam) {\n"
     "                    if (!gateOpen(gate)) return\n"
     "                    onBefore?.invoke(param)\n"
     "                }",
     "                override fun beforeHookedMethod(param: MethodHookParam) {\n"
     "                    onBefore?.invoke(param)\n"
     "                }",
     [PY, 'kit/scripts/check_hook_gate_predicate.py']),
    ('㉪ hot 钩子可关闭', '去掉 AntiDetect 的 gate',
     'module/app/src/main/java/dev/xalor/kdkit/features/host/AntiDetect.kt',
     "        if (Xp.hook(\"dj.f\", \"d\", cl = Xp.classLoader, gate = id, onBefore = {",
     "        if (Xp.hook(\"dj.f\", \"d\", cl = Xp.classLoader, onBefore = {",
     [PY, 'kit/scripts/check_hook_gated.py']),
    # 2026-11-06：新加一处完全静默的 except ⇒ ㉬ 必须红
    ('㉬ 无静默 except', '新加一处 except Exception: pass',
     'kit/scripts/catalog.py',
     "def main(argv):",
     "def _negctl_probe():\n    try:\n        raise ValueError('x')\n"
     "    except Exception:\n        pass\n\n\ndef main(argv):",
     [PY, 'kit/scripts/check_silent_except.py']),
    ('㉩ 无重复 kind 分支', '把死掉的 POPWIN 分支加回去',
     'kit/python/capture_transcript.py',
     "    if kind == 'WATERMARK':",
     "    if kind == 'POPWIN':\n"
     "        return f'- `{ts}` **POPWIN** `{f.get(\"type\")}`'\n\n"
     "    if kind == 'WATERMARK':",
     [PY, 'kit/scripts/check_dup_kind_branch.py']),
    ('㉨ SIGN URL 只一处', '再加一处未标注的 split',
     'kit/scripts/path_diff.py',
     "    urls = capture_schema.sign_urls(text.splitlines())",
     "    urls = capture_schema.sign_urls(text.splitlines())\n"
     "    _ = [x.split(' SIGN URL: ', 1)[1] for x in text.splitlines() if ' SIGN URL: ' in x]",
     [PY, 'kit/scripts/check_sign_url_dup.py']),
    ('㉓ 磁盘体积在限内', '上限故意调低',
     'kit/scripts/disk_audit.py',
     "MAX_TOTAL_MB = 8192",
     "MAX_TOTAL_MB = 1000   # 负对照：故意调到 1 GB，当前仓库 2.6 GB ⇒ 必红",
     [PY, 'kit/scripts/disk_audit.py']),
    ('⑦ 假测试扫描', '加一条恒真断言',
     'kit/python/tests/test_activity_counts.py',
     'class CountsComeFromTheCapture(unittest.TestCase):',
     'class CountsComeFromTheCapture(unittest.TestCase):\n\n'
     '    def test_negctl_tautology(self):\n'
     '        self.assertTrue(True)',
     [PY, 'kit/scripts/check_fake_tests.py', '--strict']),
    ('⑩ 读预算余量', '预算设为 0',
     None, None, None,
     [PY, 'kit/scripts/check_usage_budget.py', '--strict', '--read-budget', '1024']),
    ('⑨ 热修复暴露面', '阈值设为 0',
     None, None, None,
     [PY, 'kit/scripts/check_robust_coverage.py', '--quiet', '--fail-over', '0']),
    ('⑮ 钩子返回值类型', '允许的返回类型改错',
     'kit/scripts/check_hook_result_types.py',
     "        'a': ('false', {'Z'}),", "        'a': ('false', {'I'}),",
     [PY, 'kit/scripts/check_hook_result_types.py']),
    ('⑯ 开关默认值一致', '回调里的字面量与 defaultOn 相反',
     'module/app/src/main/java/dev/xalor/kdkit/features/misc/LogSink.kt',
     'if (!KdConfig.isOn(id, true)) return', 'if (!KdConfig.isOn(id, false)) return',
     [PY, 'kit/scripts/check_gate_defaults.py']),
    ('⑭ 生成文档新鲜度', '往自动生成的文档里塞一行',
     'work/CORE_HTTP_REQUESTS.md', '\n', '\n* 负对照塞的一行\n',
     [PY, 'kit/scripts/check_generated_fresh.py']),
    ('⑧ 钩点共享登记', '表里少登一个参与者',
     'module/PARADIGM.md',
     '| `HybridWebView.dispatchActionToListeners` | `BridgeGuard.kt:70` | `H5BridgeLog.kt:41` |',
     '| `HybridWebView.dispatchActionToListeners` | `BridgeGuard.kt:70` | （未登记） |',
     [PY, 'kit/scripts/check_hook_sharing.py', '--strict',
      '--targets-json', 'work/.hook_targets.json']),
    ('③ 功能表一致', 'README 里多一个不存在的功能',
     'module/README.md', '| `rm_splash` | 开屏广告 |',
     '| `rm_splash_negctl` | 负对照 |',
     [PY, 'module/scripts/check_feature_parity.py']),
    ('①b 抓取解析器', '让一个测试断言失败',
     'kit/python/tests/test_activity_counts.py',
     'class CountsComeFromTheCapture(unittest.TestCase):',
     'class CountsComeFromTheCapture(unittest.TestCase):\n\n'
     '    def test_negctl_fails(self):\n'
     '        self.assertEqual(1, 2)',
     [PY, '-m', 'unittest', 'discover', '-s', 'kit/python/tests']),
    # **只对非平台类注入**：`android.*` / `java.*` 的目标不在解包的 APK 里，
    # ④ 只能按前缀放行（`OK(platform)`）—— 那意味着平台类名打错字**④ 看不见**。
    # 这是 ④ 的已知边界（已在下面记录），所以负对照选一个能在 smali 里查到的目标。
    ('④ 钩子目标存在', '把一个非平台钩子目标的类名改错',
     'module/app/src/main/java/dev/xalor/kdkit/features/misc/NativeProbe.kt',
     '"com.zuoyebang.baseutil.NativeHelper", "nativeGetSign"',
     '"com.zuoyebang.baseutil.NativeHelperXX", "nativeGetSign"',
     [PY, 'kit/scripts/check_hook_targets.py']),
    # **只对非平台类注入**：⑤ 与 ④ 一样，`android.*`/`java.*` 的目标按前缀放行
    # （`OK(platform)`），形参类型**不校验**。这是已知边界（已写进 PARADIGM §5），
    # 所以负对照选一个能在 smali 里查到签名的目标。
    ('⑤ 钩子签名', '形参类型写错',
     'module/app/src/main/java/dev/xalor/kdkit/features/host/RouteLog.kt',
     '"h" -> if (Xp.hook("com.zuoyebang.router.r0", "h", String::class.java, gate = id,',
     '"h" -> if (Xp.hook("com.zuoyebang.router.r0", "h", Int::class.java, gate = id,',
     [PY, 'kit/scripts/check_hook_signatures.py', '--quiet']),
    ('⑥ 钩子调用方', '方法名写错 ⇒ 类在方法不在',
     'module/app/src/main/java/dev/xalor/kdkit/features/misc/NativeProbe.kt',
     '"com.zuoyebang.baseutil.NativeHelper", "nativeGetSign"',
     '"com.zuoyebang.baseutil.NativeHelper", "nativeGetSignXX"',
     [PY, 'kit/scripts/check_hook_callers.py', '--quiet']),
    ('② assembleDebug', '往 Kotlin 里塞一个语法错误',
     'module/app/src/main/java/dev/xalor/kdkit/util/NavFilter.kt',
     '}', '}\n\nprivate val negctlSyntaxError: Int = "not an int"',
     ['bash', '-c', "cd '$ROOT/module' && JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gw assembleDebug"]),
    ('㉗ 设备写入有回读', '造一个只推不读回的脚本',
     'kit/scripts/zz_negctl_probe.sh', None,
     '#!/usr/bin/env bash\nadb -s "$SER" push "$TMP" /data/local/tmp/negctl.xml\necho "[negctl] 已写入"\n',
     [PY, 'kit/scripts/check_device_writes_readback.py']),
    ('㉘ 签名请求体组装一致', '一处少排一个参数',
     'kit/python/probe_paths.py',
     "                        if not f.startswith(('_t_', 'kakorrhaphiophobia')))",
     "                        if not f.startswith('_t_'))",
     [PY, 'kit/scripts/check_sign_body_assembly.py']),
    ('㉙ TLS 只有一个决定点', '再造一处无条件跳',
     'kit/python/pageapi.py',
     '        with urllib.request.urlopen(req, timeout=25, context=net.ssl_context()) as r:',
     "        with urllib.request.urlopen(req, timeout=25, context=__import__('ssl')._create_unverified_context()) as r:",
     [PY, 'kit/scripts/check_tls_default.py']),
    ('㉚ 验证链路吞噬有预算', '在验证类文件里加一处静默吞噬',
     'kit/scripts/verify_membership.py',
     "    _ad_read = sum(len(rx.findall(text)) for rx in AD_RX)",
     "    try:\n        _ad_read = sum(len(rx.findall(text)) for rx in AD_RX)\n    except Exception:\n        pass\n    _ad_read = 0",
     [PY, 'kit/scripts/check_silent_except.py']),
    # 这条要**改文件系统的 mtime** 再跑检查，跑完再把快照刷回来 ——
    # 所以它是个“改状态”的用例，不是“改代码”的用例（`path` 为 None）。
    # 第一版把整条写成 `bash -c "... $ROOT ..."`，而 harness 用
    # `subprocess.run(cmd)` **不过 shell** ⇒ `$ROOT` 没人展开 ⇒ 注入没发生。
    ('㉛ 源码快照够新', '把快照的 mtime 推到 30 天前',
     None, None, None,
     [PY, '-c',
      "import os,sys,datetime,subprocess;"
      "p=os.path.join(os.getcwd(),'work','src_backups','latest');"
      "os.utime(p,(datetime.datetime(2026,10,1).timestamp(),)*2);"
      "rc=subprocess.run([sys.executable,'kit/scripts/src_snapshot.py',"
      "'--verify','--max-age-hours','48']).returncode;"
      "subprocess.run([sys.executable,'kit/scripts/src_snapshot.py'],"
      "stdout=subprocess.DEVNULL);"
      "sys.exit(rc)"]),
    # 这条改的是**文件系统的 mtime**，不是代码 —— 所以 `path` 为 None。
    # 2026-11-03：一个过期的 `.pyc` 让“改过的代码看起来没改”，
    # 负对照因此跑出假绿，我差一点把“这个 bug 测不出来”写进 STATE。
    ('㉝ 没有过期的 pyc', '把源码 mtime 推到 60 秒后',
     None, None, None,
     [PY, '-c',
      "import os,time,sys,subprocess;"
      "p=os.path.join(os.getcwd(),'kit','python','device_entry_crypto.py');"
      "os.utime(p,(time.time()+60,time.time()+60));"
      "rc=subprocess.run([sys.executable,'kit/scripts/check_stale_pycache.py']).returncode;"
      "n=time.time();os.utime(p,(n,n));"
      "sys.exit(rc)"]),
    ('㉞ gz 读取器唯一', '再造一处逐字相同的读取器',
     'kit/scripts/bridge_urls.py',
     "    return textio.read_lines(path)      # 2026-11-03：四份逐字相同的读取器收敛成 `textio`",
     "    import gzip\n    if path.endswith('.gz'):\n        with gzip.open(path, 'rt', encoding='utf-8', errors='replace') as f:\n            return f.read().splitlines()\n    return textio.read_lines(path)",
     [PY, 'kit/scripts/check_dup_gz_reader.py']),
    ('㉟ 签名公式唯一', '再造一处 md5 签名链',
     'kit/scripts/read_sign_inputs.py',
     "            got = kd_api.sign_digest(a_str, x, param)   # 2026-11-03：公式收敛到 kd_api",
     "            got = hashlib.md5((a_str + '[' + hashlib.md5(x.encode()).hexdigest() + ']@' + param).encode()).hexdigest()",
     [PY, 'kit/scripts/check_sign_formula_dup.py']),
    ('㉞ gz 读取器唯一', '再造一处 root 读内存',
     'kit/scripts/find_sign_strings.py',
     "    return memread.read_mem(serial, pid, addr, length)   # 2026-11-03：三份收敛成一处",
     "    return subprocess.run(['adb','-s',serial,'shell','su','-c',\n        '\"dd if=/proc/%d/mem bs=1 skip=%d count=%d\"'%(pid,addr,length)],\n        capture_output=True).stdout",
     [PY, 'kit/scripts/check_dup_gz_reader.py']),
    ('㉠ SDK 路径唯一', '再造一处写死的 SDK 路径',
     'kit/scripts/checkup.sh',
     'source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"',
     'source "$(dirname "${BASH_SOURCE[0]}")/sdk_paths.sh"\n'
     '# 负对照：又写死一处\n'
     'export PATH="$HOME/Library/Android/sdk/platform-tools:$PATH"',
     [PY, 'kit/scripts/check_sdk_path_dup.py']),
    ('㉞ gz 读取器唯一', '把 --captures 默认值里的 .gz 删掉',
     'kit/scripts/bridge_page_map.py',
     "                    default=[os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt'),\n                             os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt.gz')])",
     "                    default=[os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt')])",
     [PY, 'kit/scripts/check_dup_gz_reader.py']),
    ('㉡ gz 抓取可解析', '让 iter_records 不认 .gz',
     'kit/python/capture_schema.py',
     "    from textio import read_text\n    for line in read_text(path).splitlines():",
     "    for line in open(path, encoding='utf-8', errors='replace'):",
     [PY, 'kit/scripts/check_capture_gz_parse.py']),
    ('㉢ 不直接 open 抓取', '把 --capture 退回 open()',
     'kit/scripts/read_sign_inputs.py',
     "        text = textio.read_text(a.capture)   # 2026-11-03：--capture 可给 .txt.gz",
     "        text = open(a.capture, encoding='utf-8', errors='replace').read()",
     [PY, 'kit/scripts/check_capture_open.py']),
    ('㉣ 同名同参不反序', '再造一处反序同名函数',
     'kit/python/kd_crypto.py',
     "def decrypt(cipher_b64, key):",
     "def decrypt_with_key(cipher, key):\n    return decrypt(cipher_b64, key)\n\n\ndef decrypt(cipher_b64, key):",
     [PY, 'kit/scripts/check_same_name_contract.py']),
    ('㉤ 证据索引新鲜', '往索引里塞一行假的',
     'work/INDEX.md',
     '_由 `kit/scripts/index_evidence.py` 生成；`--check` 可用于判断索引是否过期。_',
     '_由 `kit/scripts/index_evidence.py` 生成；`--check` 可用于判断索引是否过期。_\n| 假的一行 |',
     [PY, 'kit/scripts/index_evidence.py', '--check']),
    ('㉥ 跳过数在限内', '加一条没登记过的 skip',
     'kit/python/tests/test_device_backup.py',
     'class ShAcceptsListAndString(unittest.TestCase):',
     'class UnregisteredSkip(unittest.TestCase):\n\n'
     '    def test_i_skip_for_no_reason(self):\n'
     "        self.skipTest('今天懒得跑')\n\n\n"
     'class ShAcceptsListAndString(unittest.TestCase):',
     [PY, 'kit/scripts/check_skip_budget.py']),
    # 2026-11-09 04:35：曾有两个 ㉦ 负对照（"删一条测试" vs "把静态下限抬到
    # 99999"），两个会话同时改过这一段 ⇒ 留下一段无主注释（已清）。保留
    # 99999 这一版：负对照跑的时候，别的控制也在动测试文件，条数会漂
    # （实测删 1 条后 `test_run` 报 510，比之前 504 还多），"少一条"这个判据不成立。
        # 2026-11-09 修：原注入是"删掉一条测试"，而**测试条数在负对照期间不稳定**
    # （实测删 1 条后 `test_run` 报 510 条，比之前 504 还多 —— 别的注入会同时改动收集数），
    # 于是这道负对照自己失效（报"注入后仍绿"）。改成注入**静态下限**：
    # 判据只看 `got < max(FLOORS, 基线)`，不依赖条数波动。
    ('㉦ 覆盖数不缩水', '把静态下限抬到不可能达到',
     'kit/scripts/check_coverage_floors.py',
     "    'python 测试': 489,",
     "    'python 测试': 99999,",
     [PY, 'kit/scripts/check_coverage_floors.py']),
    ('㉧ 循环里无裸 open', '在循环里加一处裸 open',
     'kit/scripts/page_internals.py',
     "        for m in re.finditer(r'\\| `([^`]+)` \\| (\\d+) \\| ([^|]*)\\|', textio.read_text(a.out, encoding='utf-8')):",
     "        for _zz in [1]:\n            _x = open('/dev/null').read()\n"
     "        for m in re.finditer(r'\\| `([^`]+)` \\| (\\d+) \\| ([^|]*)\\|', textio.read_text(a.out, encoding='utf-8')):",
     [PY, 'kit/scripts/check_open_in_loop.py']),
]


def run(cmd, timeout=300):
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode
    except subprocess.TimeoutExpired:
        return 124





def heal_leftovers():
    """还原上次被强杀留下的 `.negctl.bak`，返回被还原的相对路径列表。

    抽成独立函数是为了**能被单独调用与验证**：这段逻辑 2026-11-05 加入后从未被
    单独跑过，于是"它到底有没有生效"一直没有证据（2026-11-09 实测发现
    `kit/python/kd_api.py.negctl.bak` 从 11-05 一直躺到 11-09 都没被吃掉，
    而 `kd_api.py` 一直是注入态 ⇒ 那条 P1 校验三天都在假通过）。
    """
    healed = []
    # **另一条链正在跑 ⇒ 不许自愈**（2026-11-09 加）。
    # `.bak` 在"正在注入"的窗口里是**正常中间状态**，不是残留；此时还原会
    # 把别人的用例内容换回干净版，那条负对照就变成"注入没到位 ⇒ 门禁仍然绿"的假结论。
    owner = negctl_state.active_pid()
    protected = set()
    if owner and owner != os.getpid():
        protected = set((negctl_state.read_marker() or {}).get('paths') or [])
        print(f'[negctl] **另一条链正在跑（pid={owner}）⇒ 自愈只跳过它的 {len(protected)} 个文件**'
              '（那几对 .bak 是它的中间状态，不是残留）')
    for pat in ('kit/**/*.bak', 'module/**/*.bak'):
        for bak in glob.glob(os.path.join(ROOT, pat), recursive=True):
            if not bak.endswith('.negctl.bak'):
                continue
            if os.path.relpath(bak[:-len('.negctl.bak')], ROOT) in protected:
                continue
            live = bak[:-len('.negctl.bak')]
            shutil.copy2(bak, live)
            os.remove(bak)
            healed.append(os.path.relpath(live, ROOT))
    return healed


def main(argv):
    # ── **自愈：上次被强杀留下的 `.negctl.bak`**（2026-11-05 加）──────────────
    #
    # 负对照会"改一个字符串再改回来"，还原写在 `finally` 里。
    # 但 `finally` **不覆盖 SIGKILL/SIGTERM**（`timeout`、Ctrl-C、断电都算）——
    # 2026-11-05 实测有一次被 `timeout` 打断，`kit/python/kd_api.py` 停在
    # `bad = []   # 负对照：故意永不报错` 的状态，而 `.negctl.bak` 还在旁边。
    #
    # 后果很隐蔽：**注入态变成了"正常态"**，于是那条 P1 校验永久失效，
    # 而唯一的症状是四个单测红 —— 人会去查校验代码，查不出所以然
    # （因为校验代码"看起来是对的"，只是被换成了 `bad = []`）。
    #
    # 修法：**每次启动先扫 `.negctl.bak`，有就还原并大声报出来。**
    # 备份存在 = 有一轮没走完 ⇒ 当前源码不可信 ⇒ 必须先修再跑。
    # ── 互斥：负对照**会改源码**，绝不能再与门禁/验收并发 ───────────────
    # 注入态被别的门读到 ⇒ 假红（2026-11-09 实测 6~9 道门）。
    # **重入**：外层（`with_lock.py`）已经持锁时不再 exec 第二层 ——
    # 否则子进程重新 open 同一个锁文件 ⇒ flock 自己挡住自己 ⇒ 永久等待
    # （2026-11-09 实测：`verify.sh` 套锁后 ㉖ 卡住，直到被 `timeout` 杀掉）。
    if (not os.environ.get('KD_NEGCTL_LOCKED')
            and not os.environ.get('KD_LOCK_HELD')
            and os.path.exists(
                os.path.join(ROOT, 'kit', 'scripts', 'with_lock.py'))):
        os.environ['KD_NEGCTL_LOCKED'] = '1'
        os.execv(sys.executable, [sys.executable,
                 os.path.join(ROOT, 'kit', 'scripts', 'with_lock.py'),
                 '--label', 'negctl', '--timeout', os.environ.get('KD_LOCK_TIMEOUT', '7200'),
                 '--', sys.executable, os.path.abspath(__file__), *argv[1:]])

    healed = heal_leftovers()
    if healed:
        # **残留被还原后，"倒在中途"这件事已经处理完** ⇒ 标记也该清掉。
        # 不清的话，㉰ 会一直报"标记还在但持有者已死"，把一次已修好的事故
        # 变成永远的噪声（而噪声会训练人忽略门禁）。
        negctl_state.clear_marker()
        print('[negctl] **上次被强杀，已从 .negctl.bak 还原**：')
        for h in healed:
            print(f'[negctl]   ↺ {h}')
        print('[negctl]   这些文件的当前内容在上一轮是"注入态" —— '
              '还原之后才可信。请重跑本工具确认。')

    # **告诉 `test_run.py`：现在是负对照，别写缓存。**
    # 负对照会临时删测试来证明"㉦ 能红"；那期间跑出的 445 条
    # 若被写进缓存，㉦ 就会读到 445 < 下限 ⇒ 负对照把自己的门禁毒死。
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default=None, help='只跑名字里含这个字符串的那几道')
    ap.add_argument('--heal-only', action='store_true',
                    help='只做自愈（还原 .negctl.bak）并退出；用来验证自愈本身')
    ap.add_argument('--force', action='store_true',
                    help='忽略"全量通过缓存"，无条件重跑（源码没变也跑）')
    ap.add_argument('--no-cache', action='store_true', help='不读也不写缓存（调试用）')
    ap.add_argument('--cache-check', action='store_true',
                    help='只检查"全量结果是否还新鲜"：0=可复用/1=已失效/2=没有基线；不跑任何用例')
    a = ap.parse_args(argv[1:])

    # ── 全量通过缓存（2026-09 加）────────────────────────────────
    # 成本问题：48 道 × 每道跑一遍套件 ≈ 2 小时，而 6 天要跑几十轮。
    # 判据必须强到不会掩盖回归：指纹覆盖**全部会被负对照修改的源码**。
    fp0 = src_fingerprint()
    if not (a.force or a.no_cache or a.only):
        ts, passed, fp = read_pass_cache()
        age_h = (time.time() - ts) / 3600 if ts else None
        if fp == fp0 and age_h is not None and age_h < PASS_CACHE_HOURS and passed >= len(CASES):
            print(f'[negctl] 复用 {age_h:.1f} 小时前的全量结果：{passed}/{len(CASES)} 道（源码指纹未变）')
            print(f'[negctl]   指纹 {fp0[:12]}；无条件重跑用 --force')
            return 0
        if fp is not None and fp != fp0:
            print('[negctl] 源码指纹变了 ⇒ 全量重跑（缓存不适用）')

    if a.cache_check:
        fp = src_fingerprint()
        ts, passed, cfp = read_pass_cache()
        if not cfp:
            print('[negctl] 没有全量通过记录 ⇒ 需要跑一次 `--force`（这道门没有基线，不算通过）')
            return 2
        age_h = (time.time() - ts) / 3600
        if cfp != fp:
            print(f'[negctl] **全量结果已失效**：判据源码变了（{cfp[:12]} → {fp[:12]}）')
            print('[negctl] 跑 `python3 kit/scripts/run_negative_controls.py --force` '
                  '证明每道门禁仍能变红')
            return 1
        if age_h >= PASS_CACHE_HOURS or passed < len(CASES):
            print(f'[negctl] **全量结果过期**：{age_h:.1f} h 前 / {passed}/{len(CASES)} 道 ⇒ 需要 --force 重跑')
            return 1
        print(f'[negctl] 全量结果新鲜 ✓（{age_h:.1f} h 前，{passed}/{len(CASES)} 道，指纹 {fp[:12]}）')
        return 0

    if a.heal_only:
        print(f'[negctl] heal-only：自愈 {len(healed)} 项；'
              f'残留 .negctl.bak {0 if not healed else "已处理"}')
        return 0

    # **告诉 `test_run.py`：现在是负对照，别写缓存。**
    # 负对照会临时删测试来证明"㉦ 能红"；那期间跑出的 445 条
    # 若被写进缓存，㉦ 就会读到 445 < 下限 ⇒ 负对照把自己的门禁毒死。
    os.environ['KD_NEGCTL'] = '1'

    cases = [c for c in CASES if not a.only or a.only in c[0]]
    if not cases:
        print(f'[negctl] 没有匹配 "{a.only}" 的用例（共 {len(CASES)} 道）')
        return 1

    # **写"正在跑"标记**（2026-11-09 加）。
    # 没有它，别的进程只能看到"一对 .bak + 活文件"，于是把**正在跑**误判成**崩了** ——
    # 2026-11-09 02:25 实测：另一条链的 ㉖ 正在注入，此时扫残留会假红 40 秒。
    # `atexit` 覆盖正常退出与异常退出；`SIGTERM`/`SIGKILL` 不执行它 ⇒ 标记留下，
    # 那正是"真崩了"应当留下的证据（`finally` 同样不执行）。
    negctl_state.write_marker(
        [c[0] for c in cases],
        paths=[c[2] for c in cases if c[2]])
    atexit.register(negctl_state.clear_marker)

    # ㉑ 需要一份"有一行没有规则"的抓取
    cap = os.path.join(tempfile.mkdtemp(), 'cap.txt')
    with open(cap, 'w', encoding='utf-8') as f:
        f.write('20:00:00.000 ZZNOTAPREFIX foo=1\n')

    bad, stale, ok = [], [], 0
    # **逐条计时**（2026-11-06 加）。㉖ 是本仓库最慢的单项（~730s / 全量 1050s），
    # 而"哪几条最贵"一直是猜的。没有数据就只能靠感觉优化 ——
    # 今天已经因为"凭感觉"改错过一次（把需要跑套件的负对照也套了 timeout）。
    TIMINGS = []
    for name, why, path, old, new, cmd in cases:
        cmd = [cap if c == 'ZZCAPZZ' else c for c in cmd]
        backup = None
        created = False
        # **记住原文件的 mtime，还原时一起还原**（2026-11-04 修）。
        #
        # `shutil.copy2` 会保留 mtime，`shutil.move`（同盘 rename）也会保留 ——
        # 但那只在"原文件还在"时成立。实测 `device_entry_crypto.py` 在一次
        # negctl 之后 mtime 跳到了"现在"，于是 `test_run.py` 的缓存判据
        # （"源码比缓存新 ⇒ 重跑"）被触发 ⇒ 紧跟着的 ㉥ 又跑了一遍 150 秒的套件。
        #
        # **内容还原了，mtime 没还原 —— 在下游看来这就是"文件被改了"。**
        st = None
        try:
            if path:
                full = os.path.join(ROOT, path)
                if old is None:
                    # **新建一个文件**（㉗ 那一类：判据是"多了个坏东西"，
                    # 不是"改坏一个已有东西"）。
                    #
                    # **`old is None` 只许用于本来就不该存在的文件**
                    # （2026-11-03 差点因此毁掉一个真文件）：
                    # 我给 ㉚ 写用例时对 `verify_membership.py` 用了 `old=None`，
                    # 于是 harness 把它**覆盖成注入文本、跑完又删掉** ——
                    # 一个真的源码文件被负对照毁了。与 R75 那次
                    # "为了测一个修复而弄坏了被测对象之外的东西"是同一类失误。
                    #
                    # 现在：文件已存在就**拒绝**这一条用例，并提示改用
                    # "改一个字符串"的形态（那才会备份、才会还原）。
                    if os.path.isfile(full):
                        print(f'  !   {name:24s} {path} 已存在 ⇒ 拒绝用"新建"形态'
                              f'（会覆盖并删掉真文件）；请给它一个 old/new 对')
                        bad.append(name)
                        continue
                    with open(full, 'w', encoding='utf-8') as f:
                        f.write(new)
                    created = True
                else:
                    if not os.path.isfile(full):
                        # 文件被改名/搬走 ⇒ **负对照过期**，不是门禁失效。
                        print(f'  ?   {name:24s} 文件不在了：{path}（负对照过期）')
                        stale.append(name)
                        continue
                    if old not in textio.read_text(full, encoding='utf-8'):
                        # **这一条曾是 ㉖ 最贵的误诊来源**（2026-11-09 04:2x）：
                        # 锚点漂了 ⇒ 注入是空操作 ⇒ 门禁当然还是绿 ⇒ 报"门禁失效"。
                        # 两种病的修法完全不同（修锚点 vs 修门禁），必须分开报。
                        print(f'  ?   {name:24s} **锚点过期**（代码已变）：{old[:40]}')
                        stale.append(name)
                        continue
                    backup = full + '.negctl.bak'
                    st = os.stat(full)
                    shutil.copy2(full, backup)
                    with open(full, encoding='utf-8') as f:
                        src = f.read()
                    with open(full, 'w', encoding='utf-8') as f:
                        # **替换全部出现处**：只换第一处时，若第一处是 import 或注释，
                        # 后面真正用的地方还在 ⇒ 检查器仍然绿，于是这一条负对照
                        # 报"门禁失效"，而事实是注入没到位（第一版就这样误报过）。
                        f.write(src.replace(old, new))
            _t0 = time.time()
            rc = run(cmd)
            _dur = time.time() - _t0
            TIMINGS.append((_dur, name))
            if rc == 0:
                print(f'  ✗   {name:24s} 注入"{why}"后**仍然绿** ⇒ 这道门禁已经失效')
                bad.append(name)
            else:
                print(f'  ✓   {name:24s} 注入"{why}" ⇒ rc={rc}')
                ok += 1
        finally:
            if created:
                try:
                    os.remove(os.path.join(ROOT, path))
                except OSError:
                    pass
            elif backup and os.path.isfile(backup):
                dst = os.path.join(ROOT, path)
                shutil.move(backup, dst)
                if st is not None:
                    # 内容回到原样 ⇒ mtime 也必须回到原样。
                    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))

    shutil.rmtree(os.path.dirname(cap), ignore_errors=True)

    # 落账到 `work/negctl_times.tsv`（一行：耗时 + 用例名），按耗时降序打印前几条。
    TIMINGS.sort(reverse=True)
    if TIMINGS:
        out_tsv = os.path.join(ROOT, 'work', 'negctl_times.tsv')
        try:
            with open(out_tsv, 'w', encoding='utf-8') as f:
                for d, nm in TIMINGS:
                    f.write(f'{d:.1f}\t{nm}\n')
        except OSError:
            pass
        total = sum(d for d, _ in TIMINGS)
        print(f'\n[negctl] 逐条耗时（合计 {total:.0f}s，最贵的 5 条）：')
        for d, nm in TIMINGS[:5]:
            print(f'[negctl]   {d:7.1f}s  {100*d/total:5.1f}%  {nm}')
    print(f'\n[negctl] {ok}/{len(cases)} 道被证明能红')
    if stale:
        # 与"门禁失效"分开报：判据是 `ok + len(stale) + len(bad) == len(cases)`。
        print('[negctl] **负对照过期（注入是空操作，不是门禁失效）**：' + '、'.join(stale))
        print('[negctl]   修法：把这一条的锚点/文件名更新到当前代码；'
              '若它测的测试已被删除，就换成一条还在的。')
    if bad:
        print('[negctl] **失效的门禁**：' + '、'.join(bad))
        print('[negctl]   这些门禁现在无论代码怎样都返回 0 —— 修它们，或者从表里删掉。')
    if not bad and not stale and not a.only and not a.no_cache:
        write_pass_cache(fp0, ok, len(cases))
        print(f'[negctl] 全量通过已记入 {os.path.relpath(PASS_CACHE, ROOT)}（指纹 {fp0[:12]}）')
    if bad or stale:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
