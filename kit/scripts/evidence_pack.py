#!/usr/bin/env python3
"""
kuaidui-kit / evidence_pack.py — one command per round: collect every artifact the round needs.

The project's rule is "every round leaves verifiable evidence". This is the routine that makes it
cheap: it pulls the capture and produces the standard set under `work/packs/<tag>/`:

    capture.txt          raw module capture (the source of everything else)
    session_report.md    endpoints / bridge usage / guard blocks / decrypted plaintext
    module_report.md     per-feature runtime state (enabled? installed? evidence?)
    acceptance.txt|json  the 9-10 gate checks (add --live for the real API call)
    device_compare.md    optional: same kit on a second device (--adb-b)
    index.md             what this pack contains + the one-line result

    python3 kit/scripts/evidence_pack.py --adb emulator-5558 --tag r36 [--live] [--adb-b emulator-5556]
"""
import argparse
import json
import os
import re
import time
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'python'))
import textio
from device import PKG as PKG_CONST
try:
    from safe_io import write_verified
except Exception:      # 兜底：没有 safe_io 也不能让包挂掉
    def write_verified(path, text, must_contain=(), encoding='utf-8'):
        open(path, 'w', encoding=encoding).write(text)
        return len(text)

from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
def step_name(cmd):
    """从完整命令里取"步骤名"（脚本名）—— 必须在**记录时**算 ✓，
    因为存下来的是截断串 ✗（这正是 2026-10-13 那次"报警误报"的原因 ✓）。"""
    m = re.search(r'/([\w_]+\.(?:py|sh))', cmd) or re.search(r'\b([\w_]+\.(?:py|sh))', cmd)
    if m:
        return m.group(1)
    return cmd.strip().split()[0][-20:] if cmd.strip() else '?'


STEP_TIMES = []   # (秒, 步骤名) —— 2026-10-13：整包变慢时先"测"再"改"


def run(cmd, timeout=600):
    """单步限时：任何一步卡住都不该把整包拖死（2026-10-11 有一步挂了 20 分钟才发现）。
    超时返回 (1, 'STEP TIMEOUT')，调用方照常往下走，索引里会显示该步 failed。
    2026-10-13：同时记录每步耗时（见包内 timing.md 与末尾"最慢 5 步"）。"""
    import time as _t
    import os as _os
    import signal as _sig
    _t0 = _t.time()
    # 2026-10-13 修：原来用 subprocess.run(timeout=…)，超时只杀**直接子进程** ✗ ——
    # 而子进程若再 spawn 了 `adb exec-out`，孙进程会活着并**一直握住管道** ⇒ 父进程永远阻塞 ✗
    # （实测：extract_samples.py 因此挂了 50 分钟，且残留 4 个 adb 进程 ✗）。
    # 改法：新会话（进程组）+ 超时后杀**整个进程组** ✓
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace', start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            print(f'[pack] STEP TIMEOUT ({timeout}s)：杀进程组 {cmd[:80]}')
            try:
                _os.killpg(_os.getpgid(proc.pid), _sig.SIGKILL)
            except Exception:
                proc.kill()
            out, _ = proc.communicate(timeout=30)
            STEP_TIMES.append((timeout, 'TIMEOUT ' + step_name(cmd)))
            return 1, 'STEP TIMEOUT'
        STEP_TIMES.append((_t.time() - _t0, step_name(cmd)))
        return rc, out or ''
    except Exception as e:                      # 兜底：绝不因某步异常拖死整包
        STEP_TIMES.append((_t.time() - _t0, 'ERR ' + step_name(cmd)))
        return 1, 'STEP ERROR: ' + str(e)
    # **原来这里还有两行不可达代码**（2026-11-03 删）：
    #     STEP_TIMES.append(...); return r.returncode, (r.stdout or '') + ...
    # 它在 `except … return` 之后，永远走不到；而 `r` 这个名字在这段里
    # **从未被赋值** ⇒ 谁要是把上面那个 return 改掉，这两行立刻 NameError。
    # 规则 12（methodology_check）把它揪出来了。


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--adb-b', default=None, help='second device for the comparison sheet')
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--outdir', default=None)
    ap.add_argument('--with-race-test', action='store_true',
                    help='also cold-start the host and verify the read-after-restart races stay tolerant')
    ap.add_argument('--skip-baseline', action='store_true',
                    help='skip the endpoint-surface baseline check (it drives the path twice, ~2-3 min)')
    ap.add_argument('--skip-reverify', action='store_true',
                    help='skip the cross-round drift check (it takes a few minutes and ends by '
                         'letting Frida kill the host on purpose)')
    a = ap.parse_args(argv[1:])

    outdir = a.outdir or os.path.join(ROOT, 'work', 'packs', a.tag)
    os.makedirs(outdir, exist_ok=True)
    summary = {}

    # 0 device health first: a wedged display pipeline makes every later step hang (2026-10-11)
    rc, out = run(f'python3 {HERE}/device_health.py --adb {a.adb}')
    health_line = next((l for l in out.splitlines() if l.startswith('[health] ')), '')
    summary['device health'] = ('WARN: ' + out.strip().splitlines()[-1][:60]) if rc else health_line.replace('[health] ', '')

    # 1 acceptance first: with --ensure-flags it may restart the host, so every artifact below
    #   describes the same, post-restart state.
    live = ' --live' if a.live else ''
    rc, out = run(f'python3 {HERE}/acceptance.py --adb {a.adb}{live} --ensure-flags '
                  f'--json {outdir}/acceptance.json')
    write_verified(os.path.join(outdir, 'acceptance.txt'), out, must_contain=['[acceptance]'])
    tally = [l for l in out.splitlines() if 'checks passed' in l]
    summary['acceptance'] = tally[0].strip() if tally else 'failed'

    # 1b cross-round drift check (C1..C4). It deliberately lets Frida kill the host at the end,
    #    so the app is restarted right after — the capture step below then sees a live process.
    if not a.skip_reverify:
        rc, out = run(f'python3 {HERE}/reverify.py --adb {a.adb} --out {outdir}/reverify.md')
        tally = [l for l in out.splitlines() if re.search(r'\|\s*C[1-4]', l)]
        passed = sum(1 for l in tally if '✔' in l)
        summary['reverify (C1-C4)'] = f'{passed}/{len(tally) or 4} 通过' if tally else 'failed'
        run(f'adb -s {a.adb} shell am start -n {PKG}/.AliasActivityDefault')
        time.sleep(15)          # 等宿主把 feature on/off 行写进模块日志，否则 module_report 会读空

    # 1b2 endpoint-surface baseline check: catches "the app's request surface changed" (e.g. after
    # an app update) — the only gate that looks *forward* rather than at today's state.
    # 两个页面各一条基线：首页（无步骤）与 AI 写作（点进去）。扩展方式见 work/baselines/ 里的 steps 字段。
    baselines = [('首页', os.path.join(ROOT, 'work', 'baselines', 'path_home.json'), ''),
                 ('AI写作', os.path.join(ROOT, 'work', 'baselines', 'path_aiwriting.json'), '"AI写作"')]
    if not a.skip_baseline:
        for label, bl, steps in baselines:
            if not os.path.exists(bl):
                continue
            # 这一步要冷启两次宿主；紧接着 acceptance 重启过它，第一次常常还没就绪
            # ⇒ 输出里没有 `baseline check:` 行，被记成 failed。**重试一次**再判。
            m = None
            out = ''
            for attempt in range(2):
                rc, out = run(f'python3 {HERE}/path_diff.py --adb-a {a.adb} --adb-b {a.adb} '
                              f'--steps "{steps}" --repeat 2 --check-baseline {bl} '
                              f'--out {outdir}/baseline_{label}.md')
                m = re.search(r'baseline check: \+(\d+) -(\d+) params~(\d+)', out)
                if m:
                    break
                if attempt == 0:
                    run(f'adb -s {a.adb} shell am start -n {PKG}/.AliasActivityDefault')
                    time.sleep(20)
            summary[f'baseline {label} (接口面)'] = ((f'+{m.group(1)} -{m.group(2)} 参数变{m.group(3)}'
                                                     if m else 'failed')
                                                    + ('（一致）' if m and m.group(1) == '0' and m.group(2) == '0' else ''))

    # 1c tool smoke test: compile + --help/import + fixture runs for every kit tool
    rc, out = run(f'python3 {HERE}/selftest.py')
    tally = [l for l in out.splitlines() if '项通过' in l]
    summary['selftest (工具自检)'] = tally[0].strip() if tally else 'failed'

    # 1c1 cold-start behavioural snapshot (short window; gives a per-round comparable baseline)
    rc, out = run(f'python3 {HERE}/coldstart_snapshot.py --adb {a.adb} --seconds 15 '
                  f'--out {outdir}/coldstart.md')
    m = re.search(r'该窗口请求数（签名 URL） \| (\d+) \|', out)
    summary['coldstart（请求/桥/位读取）'] = (m.group(1) + ' 请求' if m else 'failed')

    # 1c2 session-state snapshot: keeps a per-round基线 so a future real login can be diffed
    rc, out = run(f'python3 {HERE}/session_snapshot.py --adb {a.adb} --out {outdir}/session_state.json')
    m = re.search(r'login prefs: (\d+)；cookie (\d+) B', out)
    summary['session_state.json'] = (f'登录相关 prefs {m.group(1)}；cookie {m.group(2)} B' if m else 'failed')

    # 1c2b 内容/配置基线：结构（CONFIG_DUMP）+ 内容明文（CONTENT_SAMPLES）每轮刷新。
    #        注意这里**不做**内容值的漂移门 —— 问题/书目本来就会变；漂移门只看**结构**（server_shape）。
    cap_r = os.path.join(outdir, 'reverify_capture.txt')
    a_r = os.path.join(outdir, 'reverify_signA.txt')
    b_r = os.path.join(outdir, 'reverify_signB.txt')
    if os.path.exists(cap_r) and os.path.exists(a_r) and os.path.exists(b_r):
        rc1, _o1 = run(f'python3 {ROOT}/kit/python/extract_config.py --adb {a.adb} --capture {cap_r} '
                       f'--sign-a {a_r} --sign-b {b_r} --out {ROOT}/work/CONFIG_DUMP.md')
        rc2, _o2 = run(f'python3 {ROOT}/kit/python/extract_samples.py --adb {a.adb} --capture {cap_r} '
                       f'--sign-a {a_r} --sign-b {b_r} --per 3 --path /kdchat/api/chatrecommendconf '
                       f'--path /kdcore/submit/homebookv2 --path /kdapi/conf/appbannersv3 '
                       f'--out {ROOT}/work/CONTENT_SAMPLES.md')
        summary['CONFIG_DUMP / CONTENT_SAMPLES'] = ('已刷新' if rc1 == 0 and rc2 == 0 else 'partial')

    # 1c2c 监控自检的"快档"：给两张不驱动设备的面做故障注入（path_diff 那条要跑路径，留给例行手动跑）
    rc, out = run(f'python3 {HERE}/inject_test.py --adb {a.adb} --only verify_inputs', timeout=600)
    ok_v = '[inject] ok' in out
    rc2, out2 = run(f'python3 {HERE}/inject_test.py --adb {a.adb} --only server_shape', timeout=900)
    ok_s = '[inject] ok' in out2
    summary['监控自检（注入）'] = ('verify_inputs ✓ + server_shape ✓' if (ok_v and ok_s)
                                   else f'verify_inputs {"✓" if ok_v else "✗"} + server_shape {"✓" if ok_s else "✗"}')

    # 1c2b2 "文档 ↔ 代码"这一类断言的清单与状态（R40 的教训：门禁表漂了 8 道没人发现，
    # 不是因为没人写断言，而是因为**没有一份清单**，于是"哪个断言该存在"本身没被审视）。
    rc, out = run(f'python3 {HERE}/check_doc_reality.py --out {outdir}/DOC_REALITY.md',
                  timeout=900)
    _l = [x for x in out.strip().splitlines() if '条断言' in x]
    summary['文档↔代码断言'] = (_l[-1].split('] ', 1)[-1] if _l else f'rc={rc}')

    # 1c2c1 四张验收面（C1/C3/C2/C5）—— 每轮都留一张，别靠"记得去跑"
    #
    # 四个面的判据各自是命令（`verify_membership.py` / `verify_face.py`），
    # 但**四条命令需要有人记得跑**，靠"记得"等于不存在。这里每轮无条件跑一次并把表落进包里，
    # 于是"这一轮到底验了什么"有据可查；退出码 2 = 有面无法验证（**不是失败**，
    # 但代码里必须和 0 分开，否则就会出现"一轮全绿、其实一个面都没验"）。
    rc, out = run(f'python3 {HERE}/face_board.py --adb {a.adb} '
                  f'--out {outdir}/FACE_BOARD.md', timeout=600)
    _l = [x for x in out.strip().splitlines() if '总判定' in x]
    summary['四张验收面'] = (_l[-1].split('：', 1)[-1] if _l else f'rc={rc}')
    if rc not in (0, 2):
        summary['四张验收面'] += '（**工具异常**，见 FACE_BOARD.md）'

    # 1c2c2 双设备对照（可选）——**这条以前是假的**：
    #   文件头写着 `device_compare.md  optional: same kit on a second device (--adb-b)`，
    #   `kit/README.md:19` 也把 `device_compare.md` 列进包产物，但 `--adb-b` 只被用来
    #   在 index 里多打一个设备名（`:626` / `:657`），**从来没有真的跑过 compare_devices**，
    #   那个文件也就从来没有被生成过（2026-11-02 审查发现）。
    #   现在：给了第二台就真跑；没给就明说"未跑"，而不是让文档继续承诺一个不存在的产物。
    if getattr(a, 'adb_b', None):
        rc, out = run(f'python3 {HERE}/compare_devices.py --adb-a {a.adb} --adb-b {a.adb_b} '
                      f'--out {outdir}/device_compare.md', timeout=600)
        summary['双设备对照'] = ('已生成 `device_compare.md`' if rc == 0
                              else '**失败**：' + (out.strip().splitlines()[-1][:100] if out.strip() else '?'))
    else:
        summary['双设备对照'] = '未跑（加 `--adb-b <serial>`）'

    # 1c2d 竞态容忍自检（可选：会冷启宿主，约 1.5 分钟）
    if getattr(a, 'with_race_test', False):
        rc, out = run(f'python3 {HERE}/race_test.py --adb {a.adb}', timeout=1800)
        summary['竞态自检（冷启后立刻读）'] = ('通过' if rc == 0 else '**未通过**')
    else:
        summary['竞态自检（冷启后立刻读）'] = '未跑（加 --with-race-test）'

    # 1c2e 桥面三张表（页面→能力 / 宿主通道取了什么）——都从抓取算，不需要额外设备操作
    rc, out = run(f'python3 {HERE}/bridge_page_map.py --adb {a.adb} --captures "{ROOT}/work/packs/*/capture*.txt" '
                  f'--out {ROOT}/work/BRIDGE_PAGE_MAP.md')
    pm = re.search(r'（(\d+) 页）', out)
    rc2, out2 = run(f'python3 {HERE}/core_http_paths.py --captures "{ROOT}/work/packs/*/capture*.txt" '
                    f'"{ROOT}/work/packs/*/capture*.txt.gz" --out {ROOT}/work/CORE_HTTP_REQUESTS.md')
    ch = re.search(r'（(\d+) 条 / (\d+) 个路径）', out2)
    summary['桥面两表'] = ((f'页面 {pm.group(1)} 个 / ' if pm else '页面 ? / ') +
                          (f'宿主通道 {ch.group(1)} 条·{ch.group(2)} 路径' if ch else '宿主通道 ?'))

    # 1c3 服务端形状比对（配置/内容结构的漂移监控；0 变化才算正常）
    rc, out = run(f'python3 {HERE}/server_shape.py --adb {a.adb}')
    m = re.search(r'形状变化 (\d+) 条', out)
    summary['server_shape（服务端形状）'] = (f'变化 {m.group(1)} 条' if m else 'failed')

    # 1c4 应用版本守卫：设备上装的目标应用若与基线不同 ⇒ **有新版本** ⇒ 自动拉下来跑一次跨版本对比
    base_path = os.path.join(ROOT, 'work', 'baselines', 'input_hashes.json')
    if os.path.exists(base_path):
        base = json.loads(textio.read_text(base_path, encoding='utf-8'))
        old_dev = {k: v.get('sha256') for k, v in base.items() if k.startswith('device-apk:')}
        rc, out = run(f'python3 {HERE}/verify_inputs.py --save')
        new_base = json.loads(textio.read_text(base_path, encoding='utf-8'))
        new_dev = {k: v.get('sha256') for k, v in new_base.items() if k.startswith('device-apk:')}
        changed = {k: (old_dev.get(k), new_dev.get(k)) for k in new_dev if old_dev.get(k) and old_dev[k] != new_dev[k]}
        if changed:
            # 只拉第一台设备的包做对比（两份安装包通常相同，省时间）
            k0 = sorted(changed)[0]
            serial0 = k0.split(':', 1)[1]
            apk_path = run(f'adb -s {serial0} shell pm path {PKG}')[1].split('package:', 1)[-1].split()[0]
            local_new = os.path.join(ROOT, 'work', 'versions', 'device_current.apk')
            run(f'adb -s {serial0} pull {apk_path} {local_new}')
            sample = next((os.path.join(ROOT, f) for f in os.listdir(ROOT)
                           if f.endswith('.apk') and f.startswith('com.kuaiduizuoye')),
                          os.path.join(ROOT, 'com.kuaiduizuoye.scan-7.7.2-1811-168194.apk'))
            run(f'python3 {HERE}/version_diff.py --a {sample} --b {local_new} '
                f'--out {ROOT}/work/versions/NEW_VERSION_DIFF.md')
            summary['应用版本守卫'] = f'**检测到新版本**（{k0}）→ 已跑跨版本对比：work/versions/NEW_VERSION_DIFF.md'
        else:
            summary['应用版本守卫'] = '设备上的目标应用与基线一致（无新版本）'

    # 1c5 页面内部结构快照（Vue 方法表）—— 驱动几个页面，出表并与上次比对
    rc, out = run(f'python3 {HERE}/page_internals.py --adb {a.adb}')
    m = re.search(r'（(\d+) 页）', out)
    ch = re.search(r'有变化的页面.*', out)
    summary['页面内部结构（Vue 方法表）'] = ((f'{m.group(1)} 页' if m else '已刷新')
                                            + ('；**有页面方法变化**' if ch else '；与上次一致'))

    # 1d refresh the module verification matrix (what evidence each feature can speak with)
    rc, out = run(f'python3 {HERE}/feature_matrix.py --adb {a.adb} '
                  f'--out {os.path.join(ROOT, "module", "VERIFICATION.md")}')
    tally = re.search(r'\[matrix\] (\{[^}]*\})', out)
    summary['module/VERIFICATION.md'] = tally.group(1) if tally else 'failed'

    # 2 capture
    rc, out = run(f'adb -s {a.adb} shell cat /data/data/{PKG}/files/kdkit_capture.txt')
    cap = os.path.join(outdir, 'capture.txt')
    open(cap, 'w').write(out)
    summary['capture'] = f'{len(out)} B'

    # 3 session report
    rc, out = run(f'python3 {HERE}/../python/session_report.py {cap} --out {outdir}/session_report.md')
    try:
        brief = next((l for l in open(os.path.join(outdir, 'session_report.md')).read().splitlines()
                      if l.startswith('* 签名 URL')), '')
        summary['session_report'] = brief.lstrip('* ') if brief else 'ok'
    except OSError:
        summary['session_report'] = 'failed'

    # 4 module report
    rc, out = run(f'python3 {HERE}/module_report.py --adb {a.adb} --out {outdir}/module_report.md')
    head = [l for l in out.splitlines() if l.startswith('* 打开的功能')]
    summary['module_report'] = head[0] if head else 'failed'

    # 4c 漂移面板（三张面）
    rc, out = run(f'python3 {HERE}/drift_report.py --adb {a.adb}')
    dm = re.search(r'\[drift\] 面状态: (.+)$', out, re.M)
    summary['漂移三面（客户端/服务端/输入）'] = dm.group(1) if dm else ('已刷新' if os.path.exists(
        os.path.join(ROOT, 'work', 'DRIFT.md')) else 'failed')

    # 5-0 roll today's packs up into a day view (pure file reading, no device work)
    rc, out = run(f'python3 {HERE}/daily_report.py')
    summary['work/DAILY-*.md'] = out.strip().splitlines()[0].replace('[daily] -> ', '') if out.strip() else 'failed'

    # 5a refresh REPORT.md's timeline from ROADMAP.md
    rc, out = run(f'python3 {HERE}/report_timeline.py')
    summary['REPORT.md 时间线'] = out.strip().splitlines()[-1] if out.strip() else 'failed'

    # 5a2 产出清单（按类型统计工作区；纯文件遍历 —— 顺手刷新以免 "1609 个文件" 那种数字过期）
    rc, out = run(f'python3 {HERE}/catalog.py')
    m = re.search(r'工作区总计：(\d+) 个文件、([\d.]+) MB', out)
    summary['work/CATALOG.md'] = (f'{m.group(1)} 个文件 / {m.group(2)} MB' if m else '已刷新')

    # 5a3 转折点页（从日志里挑"改变了认知或路线"的轮次）
    run(f'python3 {HERE}/milestones.py')
    summary['work/MILESTONES.md'] = '已刷新'

    # 5a4 页面地图（从各条基线自动合成；加基线即加一格）
    run(f'python3 {HERE}/page_map.py')
    summary['work/PAGE_MAP.md'] = '已刷新'

    # 1c9 八张面的**自动断言**（2026-10-12）：超过阈值 ⇒ 本轮判为失败 ✓（便于将来接 CI ✓）
    FAILS = []      # 硬失败：异常时让包非零退出 ✓
    NOTES = []      # **提示级**（2026-10-12 加 ✓）：值得看一眼，但**不判失败** ✗
    _snap_src = ''
    _sm = os.path.join(ROOT, 'work', 'SERVER_SNAPSHOT.md')
    if os.path.exists(_sm):
        _snap_src = open(_sm, encoding='utf-8', errors='replace').read()[:800]
    _sk = re.search(r'结构形态变化[:：]?\s*(\d+)', _snap_src)
    if _sk and int(_sk.group(1)) > 0:
        FAILS.append(f'结构形态变化 {_sk.group(1)}（服务端结构变了 ⇒ 真异常）')
    _ma = os.path.join(ROOT, 'work', 'MODULE_ACTIVITY.md')
    if os.path.exists(_ma):
        _mt = open(_ma, encoding='utf-8', errors='replace').read()
        # 这三条原本 grep `未触发 N 个` / `与上次相同 N 个` / `早早就停了 N 个` ——
        # 那是 2026-10-15 那版生成器的措辞，后来生成器改了格式，它们**永远匹配不到**
        # （代码审查 P0-2）。按**当前**格式重写：只要"有抓取行的功能"为 0，
        # 就说明模块没注入或抓取为空，那是硬失败。
        _with = re.search(r'有抓取行的功能 \*{0,2}(\d+) 个', _mt)
        _lines = re.search(r'共 \*{0,2}(\d+) 行', _mt)
        if _with and int(_with.group(1)) == 0:
            FAILS.append('模块触发面：0 个功能写出抓取行（模块没注入，或抓取是空的）')
        elif not _with:
            NOTES.append('模块触发面：`MODULE_ACTIVITY.md` 里找不到"有抓取行的功能 N 个" ⇒ 生成器措辞又变了，断言本轮空转')
    _sc = re.search(r'\*\*稳定集合变化\s*(\d+)\*\*', summary.get('服务端内容（值级）', '') or '')
    if _sc and int(_sc.group(1)) > 0:
        NOTES.append(f'稳定集合有 {_sc.group(1)} 条在变（值级信号 ⇒ 对照 work/VOLATILITY.md 判断是轮换还是异常 ✓）')
    _rr = re.search(r'\*\*(\d+)/(\d+)\*\*', summary.get('离线复现率', '') or '')
    _fa_val = summary.get('功能三方一致', '') or ''
    _fa = bool(_fa_val) and ('不一致' in _fa_val or '≠' in _fa_val)
    if _fa:
        FAILS.append('功能三方不一致（代码 ≠ module/VERIFICATION.md ⇒ 文档开始骗人 ✗）')
    if _rr and _rr.group(2) == '0':
        NOTES.append('离线复现率 **暂不可判** ✓（0/0 —— 本轮没抓到任何端点 ⇒ 无从判定 ✓，见规则 22 ✓）')
    elif _rr and _rr.group(1) != _rr.group(2):
        FAILS.append(f'离线复现率 {_rr.group(1)}/{_rr.group(2)}（有端点没回来）')
    # 再补三条"真异常"类断言（2026-10-12 ✓）
    _pi = os.path.join(ROOT, 'work', 'PAGE_INTERNALS.md')
    if os.path.exists(_pi):
        _pit = open(_pi, encoding='utf-8', errors='replace').read()
        _pn = re.search(r'(\d+)\s*页', _pit)
        if _pn and int(_pn.group(1)) == 0:
            NOTES.append('页面内部结构 **暂不可判** ✓（本轮没打开页面 ⇒ 无从判定 ✓，见规则 22 ✓）')
        elif '无变化' not in _pit:
            FAILS.append('页面内部结构变了（Vue 方法表有增删 ⇒ 页面改版）')
    _sd = os.path.join(ROOT, 'work', 'SWITCH_DIFF.md')
    if os.path.exists(_sd):
        _sdt = open(_sd, encoding='utf-8', errors='replace').read()
        _sdd = re.search(r'结构变化：新增 (\d+) / 消失 (\d+)', _sdt)
        if _sdd and (int(_sdd.group(1)) + int(_sdd.group(2))) > 0:
            FAILS.append(f'特性开关结构变化（新增 {_sdd.group(1)} / 消失 {_sdd.group(2)} ⇒ 功能上下线）')
    _av = summary.get('应用版本守卫', '')
    if _av and ('无新版本' not in _av and '与基线一致' not in _av):
        FAILS.append('应用版本变了（设备上的 App 与基线不一致）')

    if NOTES:
        summary['提示'] = '；'.join(NOTES[:3])
    if FAILS:
        summary['断言'] = '**失败 ' + str(len(FAILS)) + ' 条** ⇒ ' + '；'.join(FAILS[:3])
    else:
        summary['断言'] = '**全部通过 ✓**（结构形态 ✓ / 模块触发 ✓ / 离线复现率 ✓ / 页面结构 ✓ / 开关结构 ✓ / 应用版本 ✓）'

    # 1cI H5 页面导航观测（2026-10-12 ✓，规则 23 第 ④ 步）
    try:
        rcI, outI = run(f'python3 {HERE}/nav_log.py --adb {a.adb}')
        mN = re.search(r'H5 (\d+) 个 ✓ \+ 原生 (\d+) 个 ✓；H5 族 (\d+) 个 ⇒ \*\*对上 (\d+)\*\*', outI)
        if mN:
            summary['页面观测'] = (f'**H5 {mN.group(1)} 个 ✓ + 原生 {mN.group(2)} 个 ✓**；H5 族 {mN.group(3)} 个 ⇒ **对上 {mN.group(4)}** ✓'
                                   f'（`NavLog` 两侧都通 ✓）')
        elif '等页面加载' in outI:
            summary['H5 页面观测'] = '**暂无记录 ✓**（`NavLog` 已装 ✓，等页面加载 ✓）'
    except Exception as _e:
        print(f'[pack] 页面观测步出错: {type(_e).__name__}: {_e}')

    # 1cH 路由运行时观测（2026-10-12 ✓，规则 23 第 ④ 步）
    try:
        rcH, outH = run(f'python3 {HERE}/route_log.py --adb {a.adb}')
        mRo = re.search(r'去重 (\d+) ✓；静态全表 (\d+) 个 ⇒ \*\*见过 (\d+)\*\*', outH)
        if mRo:
            summary['路由观测'] = (f'去重 {mRo.group(1)} 条 ✓；**静态全表 {mRo.group(2)} 个 ⇒ 见过 {mRo.group(3)}** ✓'
                                   f'（两者互补 ✓）')
        elif '等触发' in outH:
            summary['路由观测'] = '**暂无记录 ✓**（功能已装 ✓，等触发 ✓）；静态全表见 work/exports/zyb_routes.csv ✓'
    except Exception as _e:
        print(f'[pack] 路由观测步出错: {type(_e).__name__}: {_e}')

    # 1cG 待触发清单（2026-10-12 ✓）：每轮带上"还差什么" ✓（与 §10.0 的"已尽"互补 ✓）
    try:
        _aw = open(os.path.join(ROOT, 'work', 'AWAITING.md'), encoding='utf-8').read()
        _aw_rows = re.findall(r'^\| [①②③④⑤⑥⑦⑧⑨] \|', _aw, flags=re.M)
        _aw_armed = len(_aw_rows)
        if _aw_armed:
            summary['待触发'] = f'**{_aw_armed} 项已就位、等条件** ✓ ⇒ 看 work/AWAITING.md ✓（各项的"触发条件"与"触发后看什么"都在里面 ✓）'
    except Exception as _e:
        print(f'[pack] 待触发步出错: {type(_e).__name__}: {_e}')

    # 1cF 功能三方一致（2026-10-12 ✓）：功能会随轮次增加 ⇒ **每轮必查** ✓
    try:
        rcF, outF = run(f'python3 {HERE}/feature_agreement.py --verbose')
        mF = re.search(r'代码 id (\d+) 个；文档 id (\d+) 个', outF)
        if mF:
            if rcF == 0:
                summary['功能三方一致'] = f'**代码 {mF.group(1)} = 文档 {mF.group(2)}** ✓（运行时另计 ✓）'
            else:
                summary['功能三方一致'] = f'**不一致** ✗（代码 {mF.group(1)} / 文档 {mF.group(2)}）⇒ 看 module/VERIFICATION.md'
    except Exception as _e:
        print(f'[pack] 一致性步出错: {type(_e).__name__}: {_e}')

    # 1cE RC4 明文（2026-10-12 ✓）：新功能抓到的明文落成导出 ✓（每轮刷新 ✓）
    try:
        rcE, outE = run(f'python3 {HERE}/rc4_plaintexts.py --adb {a.adb}')
        mR = re.search(r'去重 (\d+) ✓；密钥 (\d+) 把', outE)
        if mR:
            summary['RC4 明文'] = f'**{mR.group(1)} 条** ✓（去重 ✓；密钥 {mR.group(2)} 把 ✓）⇒ work/exports/rc4_plaintexts.csv ✓'
    except Exception as _e:
        print(f'[pack] RC4 明文步出错: {type(_e).__name__}: {_e}')

    # 1cD 交接说明表头/快照（2026-10-12 ✓）：**安全刷新**（只替换那一节 ✓，绝不跨节 ✓）
    try:
        rcD, outD = run(f'python3 {HERE}/handover_refresh.py')
        mH = re.search(r'已刷新 ✓（工具 (\d+) / 包 (\d+) / 导出 (\d+) / 枚举 (\d+) / 方法论 (\d+)）', outD)
        if mH:
            summary['交接说明'] = (f'已自动刷新 ✓（工具 {mH.group(1)} / 包 {mH.group(2)} / 导出 {mH.group(3)}'
                                   f' / 枚举 {mH.group(4)} / 方法论 {mH.group(5)}）')
    except Exception as _e:
        print(f'[pack] 交接刷新步出错: {type(_e).__name__}: {_e}')

    # 1cC 产物生命周期（2026-10-12）：本表自己也每轮刷新 ✓（进 ① 类 ✓）
    try:
        rcC, outC = run(f'python3 {HERE}/artifact_lifecycle.py')
        mLC = re.search(r'自动 (\d+) / 手工 (\d+)；共 (\d+)', outC)
        if mLC:
            summary['产物生命周期'] = f'活的 {mLC.group(1)} ✓ / 沉淀 {mLC.group(2)} ✓（共 {mLC.group(3)}）✓'
    except Exception as _e:
        print(f'[pack] 生命周期步出错: {type(_e).__name__}: {_e}')

    # 1cB 会话时间单一来源（2026-10-12）：每轮刷新 ✓，文档引用它 ✓
    try:
        rcB, outB = run(f'python3 {HERE}/session_time.py')
        mT = re.search(r'已运行 ([\d.]+) 小时（([\d.]+) 天）', outB)
        if mT:
            summary['会话时间'] = f'**{mT.group(1)} 小时**（{mT.group(2)} 天）✓'
    except Exception as _e:
        print(f'[pack] 时间步出错: {type(_e).__name__}: {_e}')

    # 1c8 八张面的历史趋势（2026-10-12）：把八张面排在一页 ✓
    run(f'python3 {HERE}/surface_trends.py --last 12')

    # 1c7 模块触发面：功能"装了" ≠ "在干活"。
    #
    # 旧实现 grep 的是 `未触发 N 个` / `与上次相同 N 个` / `早停 N 个` —— 那是
    # **2026-10-15 那版 MODULE_ACTIVITY.md 的措辞**。生成器后来改过格式，这三条 grep
    # 从此**永远匹配不到**，于是整段变成 `if md and ms:` 永远为假 ⇒ `summary` 里
    # 根本没有这个键，而断言表还显示"模块触发 ✓"（代码审查 P0-2，本次修）。
    #
    # 现在按生成器**当前**的措辞解析，并给一条可判定的断言：
    # "本轮抓取里至少有 1 个功能写出了自己的抓取行" —— 一条抓取里一个功能行都没有，
    # 那一定是模块没注入 / 抓取是空的，不该静静地过。
    try:
        _cap7 = os.path.join(outdir, 'capture.txt')
        rc7, out7 = run(f'python3 {HERE}/module_activity.py --capture {_cap7} '
                        f'--out {ROOT}/work/MODULE_ACTIVITY.md')
        md7 = re.search(r'有抓取行的功能 (\d+) 个', out7) or re.search(
            r'有抓取行的功能 \*\*(\d+) 个\*\*', out7)
        md0 = re.search(r'只写 logcat 的功能 (\d+) 个', out7) or re.search(
            r'只写 logcat 的功能 \*\*(\d+) 个\*\*', out7)
        if md7:
            _with = int(md7.group(1))
            _without = md0.group(1) if md0 else '?'
            if _with == 0:
                summary['模块触发面'] = '**0 个功能写出抓取行** ⇒ 模块没注入或抓取为空 ✗'
                FAILS.append('模块触发面 0 行')   # 2026-11-03 修：原来是 `fails`（小写）
                # ⇒ 这一行**只在出问题时才走到**，走到就 NameError。
                # 规则 12 把它揪出来的：import 时不炸，所以一直没人看见。
            else:
                summary['模块触发面'] = f'有抓取行 {_with} 个 ✓；只写 logcat {_without} 个 ✓'
        else:
            # 生成器又改措辞了 —— 说出来，别静默跳过。
            summary['模块触发面'] = '**解析失败**（`module_activity` 输出里找不到"有抓取行的功能 N 个"）⇒ 见 work/MODULE_ACTIVITY.md'
    except Exception as _e:
        summary['模块触发面'] = f'**出错**：{type(_e).__name__}: {_e}'

    # 1c0 抓取"合理性"检查：空抓取/极小抓取必须被看见（2026-10-13：r243 的抓取只有 89 字节却全绿 ✗）
    cap_now = os.path.join(outdir, 'capture.txt')
    if os.path.exists(cap_now):
        sz = os.path.getsize(cap_now)
        nlines = sum(1 for _ in textio.read_lines(cap_now, encoding='utf-8', errors='replace'))
        if sz < 4096 or nlines < 20:
            summary['抓取合理性'] = f'**可疑：{sz} 字节 / {nlines} 行**（空抓取？模块没写？）'
        else:
            summary['抓取合理性'] = f'{sz} 字节 / {nlines} 行 ✓'

    # 1c6 宿主请求头（req_headers 功能）：把"App 到底发什么头"记成产物 + 一行结论
    hdr_src = None
    for cand in (os.path.join(outdir, 'capture.txt'), os.path.join(ROOT, 'work', 'dpsdk', 'capture.txt')):
        if os.path.exists(cand):
            hdr_src = cand
            break
    if hdr_src:
        names, eps = {}, set()
        for ln in textio.read_lines(hdr_src, encoding='utf-8', errors='replace'):
            if 'HDR' not in ln:
                continue
            head, _, body = ln.partition('::')
            ep = head.split('HDR', 1)[1].strip().split(' ', 1)[-1].strip()
            if ep:
                eps.add(ep)
            for kv in body.split('|'):
                k = kv.split('=', 1)[0].strip()
                if k:
                    names[k] = names.get(k, 0) + 1
        if names:
            top = ', '.join(f'{k}×{v}' for k, v in sorted(names.items(), key=lambda kv: -kv[1])[:6])
            write_verified(os.path.join(ROOT, 'work', 'REQ_HEADERS.md'), 
                f'# 宿主请求头（`req_headers` 观测，{len(eps)} 个 endpoint）\n\n'
                f'* 出现的头名与次数：{top}\n* endpoint 数：{len(eps)}\n'
                f'* 说明：这是 App **实际发送**的头（Volley `com.android.volley.v.getHeaders()` 处观测）\n',
                must_contain=['宿主请求头'])
            summary['宿主请求头'] = f'{len(eps)} 个 endpoint；头名 {top}'
        else:
            summary['宿主请求头'] = '本轮抓取里没有 HDR 记录（`req_headers` 未开？）'

    # 5a4 待签表示检查（sign_representation）：URL 重算可不可信 —— 输入侧的常规观测
    cap_for_sign = os.path.join(outdir, 'capture.txt')
    if os.path.exists(cap_for_sign):
        rc, out = run(f'python3 {HERE}/sign_representation.py --capture {cap_for_sign}')
        m = re.search(r'配对 (\d+)：一致 (\d+) / 不一致 (\d+)', out)
        summary['待签表示（URL 重算可信度）'] = (f'配对 {m.group(1)}：一致 {m.group(2)} / 不一致 {m.group(3)}'
                                                if m else '已刷新（见 work/SIGN_REPRESENTATION.md）')

    # 5a3 服务端响应内容快照（值级漂移面）：批量 dump 全部 endpoint 的响应，与上一个包比较
    sign_a = os.path.join(outdir, 'reverify_signA.txt')
    sign_b = os.path.join(outdir, 'reverify_signB.txt')
    cap_for_dump = os.path.join(outdir, 'capture.txt')
    if os.path.exists(sign_a) and os.path.exists(cap_for_dump):
        dump_path = os.path.join(outdir, 'responses.json')
        rc2, out2 = run(f'python3 {ROOT}/kit/python/kd_api.py pull --adb {a.adb} --sign-a {sign_a} --sign-b {sign_b} '
                        f'--capture {cap_for_dump} --all-paths --auto-method --retime --insecure --dump {dump_path}')
        m2 = re.search(r'(\d+)/(\d+) endpoint', out2)
        summary['离线复现率'] = (f'**{m2.group(1)}/{m2.group(2)}** 个 endpoint 返回 200'
                                if m2 else '未取到（见 work/REPRODUCTION.md）')
        prev_dump = None
        packs_dir = os.path.join(ROOT, 'work', 'packs')
        cands = sorted((d for d in os.listdir(packs_dir) if os.path.isdir(os.path.join(packs_dir, d))),
                       key=lambda d: os.path.getmtime(os.path.join(packs_dir, d)), reverse=True)
        for d in cands:
            q = os.path.join(packs_dir, d, 'responses.json')
            if q != dump_path and os.path.exists(q):
                prev_dump = q
                break
        rc, out = run(f'python3 {HERE}/server_snapshot.py --current {dump_path}'
                      + (f' --previous {prev_dump}' if prev_dump else ''))
        snap_txt = ''
        snap_md = os.path.join(ROOT, 'work', 'SERVER_SNAPSHOT.md')
        if os.path.exists(snap_md):
            snap_txt = open(snap_md, encoding='utf-8', errors='replace').read()[:600]
        src = snap_txt or out
        m = re.search(r'稳定集合变化[:：]?\s*(\d+)', src)
        m2 = re.search(r'动态集合变化[:：]?\s*(\d+)', src)
        m3 = re.search(r'轮换集合变化[:：]?\s*(\d+)', src)
        # 特性开关漂移（同一份 responses.json ✓）：开关变化 = 功能上下线 ✓
        try:
            rc3, out3 = run(f'python3 {HERE}/switch_diff.py --current {dump_path}'
                            + (f' --previous {prev_dump}' if prev_dump else ''))
            m4 = re.search(r'取值变化 (\d+)', out3)
            m7 = re.search(r'结构变化 新增 (\d+) / 消失 (\d+)', out3)
            m5 = re.search(r'开 (\d+) / 关 (\d+)', out3)
            if m4 and m5:
                ch = int(m4.group(1))
                _struct = (f'｜**结构变化 新增 {m7.group(1)} / 消失 {m7.group(2)}**'
                           if (m7 and (m7.group(1) != '0' or m7.group(2) != '0')) else '')
                summary['特性开关'] = (f'开 {m5.group(1)} / 关 {m5.group(2)}'
                                       + (f'；**取值变化 {ch}** ⇒ 看 work/SWITCH_DIFF.md' if ch else '；取值无变化 ✓')
                                       + _struct)
        except Exception:
            pass

        summary['服务端内容（值级）'] = (
            f'**稳定集合变化 {m.group(1)}**（信号）｜动态 {m2.group(1)}｜轮换 {m3.group(1)}'
            + (f'｜**结构形态变化 {m6.group(1)}**' if (m6 := re.search(r'结构形态变化[:：]?\s*(\d+)', src)) else '')
            if m and m2 and m3 else '已刷新')

    # 5a5 体积审计（一行结论；历史落 work/audits/）
    rc, out = run(f'python3 {HERE}/disk_audit.py')
    m = re.search(r'\[disk\] (.+)$', out, re.M)
    summary['work 体积'] = m.group(1)[:90] if m else 'failed'

    # 5a7 趋势页（把历史排起来：有没有回退、体积怎么走）
    rc, out = run(f'python3 {HERE}/trend_report.py --last 40')
    m = re.search(r'回退 (\d+) 处；体积 (\S+?)→(\S+?) MB', out)
    summary['趋势（门与体积）'] = (f'回退 **{m.group(1)}** 处；体积 {m.group(2)}→{m.group(3)} MB' if m
                                  else '已刷新（见 work/TRENDS.md）')

    # 5b refresh the evidence index so the tree stays navigable after every round
    rc, out = run(f'python3 {HERE}/index_evidence.py')
    summary['work/INDEX.md'] = out.strip().splitlines()[-1] if out.strip() else 'failed'

    # 6 index
    # 1cA AB 表结构面（第九张面 ✓，2026-10-12）：新实验上线/下线 = 信号 ✓
    try:
        _prev_dump2 = ''
        _ds = [os.path.join(packs_dir, d, 'responses.json') for d in os.listdir(packs_dir)
               if os.path.exists(os.path.join(packs_dir, d, 'responses.json'))]
        _ds = sorted(_ds, key=os.path.getmtime)
        if len(_ds) >= 2:
            _prev_dump2 = _ds[-2]
        rcA, outA = run(f'python3 {HERE}/ab_diff.py --current {dump_path}'
                        + (f' --previous {_prev_dump2}' if _prev_dump2 else ''))
        mA = re.search(r'结构变化 新增 (\d+) / 消失 (\d+)', outA)
        mB = re.search(r'取值变化 (\d+)', outA)
        mC = re.search(r'(\d+) 条实验', outA)
        if mA and mB and mC:
            _struct = int(mA.group(1)) + int(mA.group(2))
            if int(mA.group(1)) > 0:
                NOTES.append(f'AB 新增实验 {mA.group(1)} 条（新功能/新策略上线 ⇒ 值得看一眼 ✓）')
            summary['AB 实验表'] = (f'{mC.group(1)} 条；' +
                                    (f'**结构变化 新增 {mA.group(1)} / 消失 {mA.group(2)}** ⇒ 看 work/AB_DIFF.md'
                                     if _struct else f'结构无变化 ✓；取值变化 {mB.group(1)}'))
    except Exception as _e:
        print(f'[pack] AB 面出错（不再静默 ✓）: {type(_e).__name__}: {_e}')

    # 2026-10-12：索引与健康页**写完立刻回读** ✓（safe_io ✓）—— 本会话三次"打印成功但没落盘"的教训
    # 2026-10-12 第三次修正：summary 的增补必须在 **lines 构造之前** ✓
    # （R224 记的是"index 写入之前" ✗ —— 那不够：lines 一旦构造完，之后再改 summary 就**看不见** ✗）
    lines = [f'# 证据包 {a.tag}', '',
             f'* 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
             f'* 设备：`{a.adb}`' + (f' / `{a.adb_b}`' if a.adb_b else ''),
             f'* 模式：验收 {"含真实调用" if a.live else "离线"}', '',
             '| 产物 | 一句话结果 |', '|---|---|']
    for k, v in summary.items():
        lines.append(f'| `{k}` | {v} |')
    lines += ['', '## 文件', '']
    for f in sorted(os.listdir(outdir)):
        lines.append(f'* `{f}`')
    lines += ['', '_由 `kit/scripts/evidence_pack.py` 生成；每个文件都可以单独复核。_', '']
    # 2026-10-13：把"每步计时"从"事后看"变成"当场报警"（基线见 work/timing_baseline.json / work/TIMING.md）
    try:
        _bl = json.load(open(os.path.join(ROOT, 'work', 'timing_baseline.json'), encoding='utf-8'))
    except Exception:
        _bl = {}
    _per, _def, _tot = _bl.get('per_step', {}), _bl.get('default_step', 5), _bl.get('total', 195)
    _slow, _total_s = [], sum(d for d, _c in STEP_TIMES)
    for _d, _k in STEP_TIMES:
        _base = _per.get(_k, _def)
        if _d > _base * 3:
            _slow.append(f'{_k}={_d:.0f}s(基线 {_base}s)')
    if _slow:
        summary['耗时异常'] = '**' + '；'.join(_slow[:3]) + '** ⇒ 检查设备（`device_health` / `recover_device.sh`）'
    elif _total_s > _tot * 2:
        summary['耗时异常'] = f'整包 {_total_s:.0f}s（基线 {_tot}s）⇒ 检查设备'
    else:
        summary['耗时'] = f'整包 {_total_s:.0f}s（基线 {_tot}s）✓'
    write_verified(os.path.join(outdir, 'index.md'), '\n'.join(lines), must_contain=[a.tag])

    # 7 一页健康快照：四道门的结论 + 关键计数（每轮覆盖，随时可看）
    health = ['# 项目健康快照', '',
              f'* 生成：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}（证据包 `{a.tag}`）',
              f'* 设备：`{a.adb}`' + (f' / `{a.adb_b}`' if a.adb_b else ''),
              f'* 轮次日志：`ROADMAP.md`；文件索引：`work/INDEX.md`；交接说明：`work/HANDOVER.md`', '',
              '| 门 | 结果 | 说明 |', '|---|---|---|']
    labels = {'acceptance': '验收（流水线健康）', 'reverify (C1-C4)': '跨轮漂移（早期结论重跑）',
              'baseline (接口面)': '接口面基线（朝前看）', 'selftest (工具自检)': '工具自检',
              'module/VERIFICATION.md': '模块功能证据强度',
              # 三张漂移面与四道门并列：它们回答的是"有没有什么东西变了"
              '漂移三面（客户端/服务端/输入）': '漂移三面（客户端 / 服务端 / 输入）',
              '监控自检（注入）': '监控自检（注入漂移，验证它们会报警）'}
    for k, v in summary.items():
        if k not in labels:
            continue
        health.append(f'| {labels[k]} | {v} | |')
    health += ['', '## 本轮产物与计数', '']
    for k, v in summary.items():
        if k in labels:
            continue
        health.append(f'* {k}：{v}')
    health += [f'* 证据包：`{os.path.relpath(outdir, ROOT)}`（含 `index.md` / `session_report.md` / '
               f'`module_report.md` / `acceptance.txt`）', '']
    write_verified(os.path.join(ROOT, 'work', 'HEALTH.md'), '\n'.join(health), must_contain=['项目健康快照'])

    print(f'[pack] {outdir}')
    for k, v in summary.items():
        print(f'  {k:16s} {v}')
    if FAILS:
        print(f'[pack] 断言失败 {len(FAILS)} 条 ⇒ 退出码 3')
        return 3
    top = sorted(STEP_TIMES, reverse=True)[:5]
    if top:
        print('[pack] 最慢 5 步：' + '；'.join(f'{d:.0f}s {c[:40]}' for d, c in top))
        _tm = '# 每步耗时（秒）\n\n' + ''.join(f'* {d:8.1f}  `{c}`\n' for d, c in sorted(STEP_TIMES, reverse=True))
        write_verified(os.path.join(outdir, 'timing.md'), _tm, must_contain=['每步耗时'])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
