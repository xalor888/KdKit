#!/usr/bin/env python3
"""
kuaidui-kit / inject_test.py — 给监控面做"故障注入"，验证它们**真的会报警**。

2026-10-12 的教训：客户端请求面的漂移门**能检测但退出码恒为 0**，帮助文本却承诺 exit 1。
那种缺陷最难发现 —— 报告页天天正常，直到出事那天。所以"监控会不会叫我"这件事必须能被例行验证。

对每张面做两件事（缺一不可）：
  1. **注入**：造一个合成漂移 → 期望退出码非 0 且报告里出现该漂移；
  2. **对照**：干净状态下 → 期望退出码 0。
只有"注入会响 + 干净不响"同时成立，这道门才算可信。

    python3 kit/scripts/inject_test.py --adb emulator-5558 [--only path_diff|verify_inputs|server_shape]

**安全**：真实基线一律先备份，结束后在 `finally` 里还原；`path_diff` 的那条用临时基线文件，不碰真的。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
B = os.path.join(ROOT, 'work', 'baselines')


def run(cmd, timeout=900):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors='replace',
                           timeout=timeout, start_new_session=True)
    except subprocess.TimeoutExpired:
        return 1, 'TIMEOUT'
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def with_backup(path, mutate, cmd):
    """备份 → 改 → 跑 `cmd` → **无论成败都还原**。

    2026-11-03 代码审查 P1：这个函数原来是**死代码** —— 它调用一个
    从未被定义的 `run_mutate()`，而两个真正需要它的测试
    （`test_verify_inputs` / `test_server_shape`）把同一套
    "备份 → 改 → 跑 → finally 还原" **各写了一遍**。

    于是"复用即崩"：下一个人照着 `with_backup` 用，立刻 `NameError`。

    修法不是删掉它，而是**让两个测试真的用它** —— 死代码通常说明
    有个模式重复出现了两次，而抽象没跟上。参数 `cmd` 是两条测试
    唯一不同的地方（跑哪个工具、带不带 `--adb`）。
    """
    bak = path + '.injecttest.bak'
    shutil.copy2(path, bak)
    try:
        mutate(path)
        return run(cmd)
    finally:
        shutil.move(bak, path)


# path_diff：用临时基线，绝不碰真文件
def test_path_diff(adb, steps, baseline_name):
    real = os.path.join(B, baseline_name)
    if not os.path.exists(real):
        return 'skip', f'{baseline_name} 不存在'
    tmp = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False)
    d = json.load(open(real, encoding='utf-8'))
    d['endpoints'] = sorted(set(d.get('endpoints') or []) | {'/injecttest/fake/endpoint'})
    json.dump(d, tmp, ensure_ascii=False)
    tmp.close()

    cmd = (f'python3 {HERE}/path_diff.py --adb-a {adb} --adb-b {adb} --steps "{steps}" --repeat 1 '
           f'--check-baseline {tmp.name} --out /tmp/_inject_path.md')
    rc_inj, out_inj = run(cmd)
    rc_clean, out_clean = run(cmd.replace(f'--check-baseline {tmp.name}',
                                          f'--check-baseline {real}'))
    os.unlink(tmp.name)
    # 断言看**机器可读行** `[diff] baseline check: +0 -1 params~0`，而不是报告文件里的中文
    # （第一版把断言写在报告内容上，而报告是写到 --out 文件的 —— 于是"门明明响了"却判成 FAIL）
    import re as _re
    m_inj = _re.search(r'baseline check: \+(\d+) -(\d+) params~(\d+)', out_inj)
    m_clean = _re.search(r'baseline check: \+(\d+) -(\d+) params~(\d+)', out_clean)
    # 对照组本身就有新增/消失 ⇒ 基线已漂，本轮**测不了**（不是 FAIL）
    # 2026-11-03 实测：对照组 rc=1、消失 32 个端点。
    clean_dirty = (rc_clean != 0 or (m_clean and (m_clean.group(1) != '0' or m_clean.group(2) != '0')))
    if clean_dirty:
        return ('skip', f'**对照组本身就在报警**（rc={rc_clean}，'
                        f'新增/消失={m_clean.group(1) if m_clean else "?"}/'
                        f'{m_clean.group(2) if m_clean else "?"}）⇒ 基线已漂，'
                        f'本轮无法证明"工具能发现我制造的变化"')
    ok = (rc_inj != 0 and m_inj and m_inj.group(2) == '1')
    return ('ok' if ok else 'FAIL',
            f'注入 rc={rc_inj}（应≠0）+ 消失端点={m_inj.group(2) if m_inj else "?"}（应=1）'
            f'；对照 rc={rc_clean}（应=0）+ 新增/消失={m_clean.group(1) if m_clean else "?"}/'
            f'{m_clean.group(2) if m_clean else "?"}（应=0/0）')


def test_verify_inputs():
    real = os.path.join(B, 'input_hashes.json')
    if not os.path.exists(real):
        return 'skip', 'input_hashes.json 不存在'

    def mutate(p):
        d = json.load(open(p, encoding='utf-8'))
        k = sorted(d)[0]
        h = d[k]['sha256']
        d[k]['sha256'] = ('0' if h[0] != '0' else '1') + h[1:]
        json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1)
        return k

    rc_inj, out_inj = with_backup(
        real, mutate, f'python3 {HERE}/verify_inputs.py')
    rc_clean, out_clean = run(f'python3 {HERE}/verify_inputs.py')
    # **三种结局，不许二选一**（2026-11-03 加）。
    #
    # 旧实现只有 ok / FAIL。而实测（2026-11-03 00:30）对照组本身就报警：
    # `path_diff` 的对照 rc=1、`server_shape` 的对照"形状变化 8 条"——
    # 因为**基线已经漂了**（游客态下 10 条接口有 8 条取不到形状）。
    #
    # 这时候正确结论是"**测不了**"，不是"FAIL"：注入测试证明的是
    # "工具能发现我制造的变化"，而基线本身不干净时，它证明不了任何事。
    # 报 FAIL 会让人去修一个没坏的工具；报 ok 则是撒谎。
    clean_alarms = rc_clean != 0 or '变化' in out_clean
    if clean_alarms:
        return ('skip', f'**对照组本身就在报警**（rc={rc_clean}）⇒ 基线已漂，'
                        f'本轮无法证明"工具能发现变化"。先核实基线再跑本测试')
    ok = rc_inj != 0 and '变化' in out_inj
    return ('ok' if ok else 'FAIL',
            f'注入 rc={rc_inj}（应≠0）且报告含"变化"：{"是" if "变化" in out_inj else "否"}')


def test_server_shape(adb):
    real = os.path.join(B, 'server_shape.json')
    if not os.path.exists(real):
        return 'skip', 'server_shape.json 不存在'
    def mutate(p):
        d = json.load(open(p, encoding='utf-8'))
        k = next(iter(d))
        if isinstance(d[k], dict):
            d[k]['keys_sha'] = 'deadbeefdeadbeef'
        json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1)

    rc_inj, out_inj = with_backup(
        real, mutate, f'python3 {HERE}/server_shape.py --adb {adb}')
    rc_clean, out_clean = run(f'python3 {HERE}/server_shape.py --adb {adb}')
    clean_line = [l for l in out_clean.splitlines() if '形状变化' in l][:1]
    inj_line = [l for l in out_inj.splitlines() if '形状变化' in l][:1]
    if clean_line and '形状变化 0 条' not in clean_line[0]:
        return ('skip', f'**对照组本身就在报警**："{clean_line[0]}" ⇒ 基线已漂'
                        f'（游客态下多数接口取不到形状），本轮无法证明"工具能发现变化"')
    ok = inj_line and '形状变化 0 条' not in inj_line[0]
    return ('ok' if ok else 'FAIL',
            f'注入报告："{inj_line}"；对照："{clean_line}"（形状面是报告，不是门）')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--only', default=None)
    a = ap.parse_args(argv[1:])

    tests = {
        'path_diff': lambda: test_path_diff(a.adb, '', 'path_home.json'),
        'verify_inputs': test_verify_inputs,
        'server_shape': lambda: test_server_shape(a.adb),
    }
    bad = skipped = 0
    for name, fn in tests.items():
        if a.only and a.only != name:
            continue
        status, detail = fn()
        print(f'[inject] {status:4s} {name}: {detail}')
        if status == 'FAIL':
            bad += 1
        elif status == 'skip':
            skipped += 1
    if bad:
        print(f'[inject] {bad} 张面没能正确报警'
              + (f'（另 {skipped} 张测不了）' if skipped else ''))
        return 1
    if skipped:
        # **全跳过 ≠ 通过**：不写出来就是"一轮全绿、其实什么都没验"
        print(f'[inject] {len(tests) - skipped} 张通过、{skipped} 张**测不了**（基线已漂）'
              f'⇒ 通过的那几张算数，测不了的那几张**不算**')
        return 2
    print('[inject] 全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
