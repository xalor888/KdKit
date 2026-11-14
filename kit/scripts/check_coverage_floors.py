#!/usr/bin/env python3
"""
kuaidui-kit / check_coverage_floors.py — **测试数与负对照数只许涨，不许跌**。

### 为什么需要

今天有三道门禁在盯“覆盖率会不会缩水”，但都只盯了一半：

| 门禁 | 盯什么 | 盯不到什么 |
|---|---|---|
| ㉖ 负对照总检 | 每一条登记过的负对照**有能力变红** | 有人**删掉**一条负对照 |
| ③ 功能表一致 | README 的功能数与注册表一致 | 某个功能的测试被删 |
| ㉥ 跳过数在限内 | 跳过的测试登记过、有上限 | 测试被**整个删掉** |

删掉一条测试，套件照样全绿 —— 只是验得少了。
删掉一条负对照，㉖ 照样全绿 —— 只是那道门禁重新变成“可能永远不红”。

**变红会叫人，变绿也会叫人，只有“少了一个数”不叫人。**

### 判据

| 量 | 下限 |
|---|---|
| Python 测试条数 | 见下方 `FLOORS`（当前 **489**） |
| Kotlin 测试条数 | 见下方 `FLOORS`（当前 **165**） |
| 负对照条数 | 见下方 `FLOORS`（当前 **40**） |

**下限必须贴着"当前条数"**（2026-11-09 修）：`487` 对上 `489` 时，删掉 1~2 条测试
㉦ 仍然是绿的 —— 而"少了一两个数不叫人"正是这道门禁存在的理由（2026-11-09
㉖ 的 `㉦` 负对照就是这样失效的：注入"删一条测试"后门禁仍然绿）。

低于下限 ⇒ 红，并说明“要么是误删，要么是有意缩减 —— 有意缩减要改这里的下限并写清理由”。

### 退出码

0 = 三项都在下限之上；1 = 有低于下限的。
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

#: 下限。**改这个数字必须同时写清为什么可以少验。**
FLOORS = {
    # 贴住当前实测条数：留任何余量都等于"允许悄悄删掉那么多条测试"。
    # **但静态下限本身会松**（今天 487 对上 489 时，删 1~2 条仍然绿 ——
    # 2026-11-09 ㉖ 的 `㉦` 负对照正是这样失效的）。所以真正的下限是
    # `max(FLOORS, 基线)`，基线由本脚本自己往上棘轮（见 `decide`）。
    'python 测试': 489,
    'kotlin 测试': 165,
    '负对照': 40,
}

#: 棘轮基线：**历史最大值**。只由本脚本往上写，永不自动往下调。
#:
#: 为什么必须存在：静态 `FLOORS` 只能钉住一个数，而"当前条数 > 下限"的那段余量
#: 就是**可以悄悄删掉的数目** —— 2026-11-09 实测下限 487 而实际 499：删掉 12 条
#: 测试，㉦ 全绿。而㉦ 存在的唯一理由就是"少了一个数不叫人"。
BASELINE = os.path.join(ROOT, 'work', '.coverage_baseline.json')


def in_negctl():
    """负对照进行中？口径只在 `test_run.NEGCTL_ENV` 一处（不在这里再写第二遍）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        '_test_run', os.path.join(ROOT, 'kit', 'scripts', 'test_run.py'))
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    return tr.in_negctl()


def _negctl_inflight():
    """跨进程的"负对照正在跑"判据（`work/.negctl.inflight` + pid 存活）。

    为什么不能只信 `KD_NEGCTL`：那个环境变量要穿过 `verify.sh` → `with_lock.py`
    → python 子进程才能到这道门禁；哪天某层没传，这道门禁就会在注入窗口里
    **写下一个错的基线**（2026-11-09 就是 504）。
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            '_negctl_state', os.path.join(ROOT, 'kit', 'python', 'negctl_state.py'))
        st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(st)
        return st.active_pid() is not None
    except (OSError, ImportError) as e:
        print(f'[floor] 读不到 negctl_state（{e}）⇒ 按"正在跑"保守处理', file=sys.stderr)
        return True


def read_baseline(path=BASELINE):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_baseline(data, path=BASELINE):
    """写棘轮：**只升不降**，且负对照在跑时一概不写。

    2026-11-09 04:30 实测基线被写成 **504**，而当时树上真实条数是 **508** ——
    那个 504 是在"有几条测试暂时不被收集"的窗口里算出来的（另一条链正在注入）。
    基线一旦被压低，就有 4 条测试可以被悄悄删掉而 ㉦ 全绿 —— 这道门禁的全部
    意义（"少了一个数会叫人"）当场归零，而且它**看起来是绿的**。

    所以把"只升不降"从 `decide()` 的口头承诺挪到**写盘这一处**兜底：
    外部窗口算错的低值写不进来；负对照期间（标记文件在、pid 活着）直接拒写。
    """
    cur = read_baseline(path)
    merged = dict(cur)
    for k, v in data.items():
        merged[k] = max(int(cur.get(k, 0) or 0), int(v))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return merged


def decide(got, floors=FLOORS, baseline=None):
    """**纯判据**（可单测）：返回 `(bad, raised)`。

    * `want = max(静态下限, 基线)` —— 基线是"历史最大值"，所以任何减少都可见；
    * `raised` = 需要抬到基线的项（只升不降）。
    """
    baseline = baseline or {}
    bad, raised = [], {}
    for k, want_static in floors.items():
        if k not in got:
            continue
        n = got[k]
        want = max(want_static, int(baseline.get(k, 0) or 0))
        if n < want:
            bad.append((k, n, want))
        elif n > want:
            raised[k] = n
    return bad, raised


def count_python():
    """从**测试运行缓存**里读条数（2026-11-03 改）。

    原来这道门禁自己跑一遍套件（150 秒），而 ①b / ㉥ 也各跑一遍 ——
    同一天里同一个套件跑了三遍，只为读三个数。
    现在统一走 `test_run.py` 的缓存。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        '_test_run', os.path.join(ROOT, 'kit', 'scripts', 'test_run.py'))
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    return int(tr.ensure_suite(quiet=True).get('count', 0))


def count_kotlin():
    n = 0
    for f in glob.glob(os.path.join(ROOT, 'module', 'app', 'build',
                                    'test-results', 'testDebugUnitTest', '*.xml')):
        try:
            n += int(ET.parse(f).getroot().get('tests', 0))
        except Exception as e:                                    # noqa: BLE001
            # ㉬：静默的 except 会让"读不到"与"本来就是 0 条"长得一样。
            # 这里说一句就够 —— 解析失败几乎总是"那轮没跑 Kotlin 测试"。
            print(f'[floor] kotlin 测试结果解析失败 {os.path.basename(f)}: {e}', file=sys.stderr)
    return n


def count_negctl():
    src = open(os.path.join(ROOT, 'kit', 'scripts', 'run_negative_controls.py'),
               encoding='utf-8').read()
    # 每条用例是一个四/五元组的首元素 '门禁名' —— 数 CASES 列表里的字符串字面量
    m = re.search(r'^CASES[^=]*=\s*\[(.*?)^\]', src, re.M | re.S)
    if not m:
        return 0
    return len(re.findall(r"^\s{4}\('", m.group(1), re.M))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--no-kotlin', action='store_true',
                    help='跳过 Kotlin 计数（没有构建产物时用）')
    a = ap.parse_args(argv[1:])

    got = {
        'python 测试': count_python(),
        '负对照': count_negctl(),
    }
    if not a.no_kotlin:
        got['kotlin 测试'] = count_kotlin()

    base = read_baseline()
    bad, raised = decide(got, FLOORS, base)
    for k in FLOORS:
        if k not in got:
            continue
        n = got[k]
        want = max(FLOORS[k], int(base.get(k, 0) or 0))
        src = '基线' if int(base.get(k, 0) or 0) >= FLOORS[k] else 'FLOORS'
        mark = '✓' if n >= want else '✗'
        print(f'  {mark}   {k:12} {n:5}  （下限 {want}，来自{src}）')

    # **抬棘轮**：只升不降；负对照期间不写（删测试的临时条数不许变成新基线）。
    if raised and (in_negctl() or _negctl_inflight()):
        print(f'[floor]   负对照进行中 ⇒ 不抬基线（{raised}）')
    elif raised:
        merged = write_baseline({**base, **raised})
        print(f'[floor]   基线抬到：{merged}（只许涨；写入时再兜一次 max）')

    if bad:
        for k, n, want in bad:
            print(f'[floor]   ✗   {k}：{n} < 下限 {want}')
        print('[floor]   要么是误删，要么是有意缩减。**有意缩减要改 FLOORS '
              '并写清为什么可以少验** —— 否则这就是套件在腐烂。')
        return 1
    if a.verbose:
        print('[floor] 三项都在下限之上 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
