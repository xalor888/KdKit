#!/usr/bin/env python3
"""
kuaidui-kit / check_usage_budget.py — "读预算还够用吗？"

## 为什么需要它

`smali_usage.analyse()` 会把"提到任一目标描述符"的 smali 文件读进内存，总量超过
`read_budget` 就停下，没读到的文件里的目标结论降级成 `INCOMPLETE`。

2026-10-26 实测过一次它的后果：预算 96 MB 时，109 个目标里有 **11 个**被降级 ——
而它们单独跑时证据是完整的。更坏的是**判定结果取决于目标在排序列表里的位置**，
同一份输入多加点目标就某个目标从 `USED` 变 `INCOMPLETE`。

把预算调到 320 MB 后降级归零，但实测用量 279.9 MB ⇒ **只剩 12% 余量**。
12% 的余量不叫余量，它是"宿主下次改版就踩"的定时器。

## 它检查什么

量"当前目标集实际需要多少字节"，与 `read_budget` 比，余量低于阈值就报警。

**只报警、不判红**（默认）：余量变小是宿主 APK 变大的自然结果，不是代码缺陷。
需要它拦门禁时用 `--strict`。

## 用法

```bash
python3 kit/scripts/check_usage_budget.py            # 人读
python3 kit/scripts/check_usage_budget.py --strict   # 余量 < 25% 就 exit 1
```
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

sys.path.insert(0, HERE)
import smali_usage as su  # noqa: E402

#: 余量低于这个比例就值得看。不是"会立刻出错"，而是"下次改版很容易出错"。
WARN_RATIO = 0.25


def current_budget() -> int:
    """从函数默认值里取，避免两处硬编码各自漂移。"""
    import inspect
    return inspect.signature(su.analyse).parameters['read_budget'].default


def main(argv):
    ap = argparse.ArgumentParser(description='量 smali_usage 的读预算余量')
    ap.add_argument('--smali', default=os.path.join(ROOT, 'work', 'apktool_out'))
    ap.add_argument('--strict', action='store_true',
                    help=f'余量低于 {int(WARN_RATIO*100)}%% 就 exit 1')
    ap.add_argument('--module', default=os.path.join(ROOT, 'module'))
    a = ap.parse_args(argv[1:])

    if not os.path.isdir(a.smali):
        print(f'[budget] {a.smali} 不存在（未解码 APK）—— 跳过')
        return 0

    # 拿当前目标集：直接用 smali_usage 的 CLI，避免重复实现"从模块抽目标"的逻辑。
    tmp = os.path.join(os.path.dirname(a.smali), '.budget_targets.json')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'smali_usage.py'),
                        '--smali', a.smali, '--from-module', a.module, '--json', tmp],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    if r.returncode != 0 or not os.path.isfile(tmp):
        print('[budget] 取目标失败：', (r.stdout + r.stderr)[-400:])
        return 0          # 取不到目标不是"预算不够"，别误判

    data = json.load(open(tmp, encoding='utf-8'))
    rows = data if isinstance(data, list) else data.get('rows', [])
    os.unlink(tmp)

    cls = [x.get('target') for x in rows if x.get('target')]
    if not cls:
        print('[budget] 目标集为空 —— 跳过')
        return 0

    descs = sorted({su.to_desc(c) for c in cls})
    files = sorted(su.grep_files(a.smali, su._alt(descs)))
    need = sum(os.path.getsize(f) for f in files)
    budget = current_budget()
    ratio = (budget - need) / budget

    print(f'[budget] 目标 {len(cls)} 个 → 命中 {len(files)} 文件，需 {need/1048576:.1f} MB')
    print(f'[budget] read_budget = {budget/1048576:.0f} MB ⇒ 余量 {ratio*100:+.1f}%')

    if ratio < 0:
        print('[budget] **预算已不够**：会有目标被降级成 INCOMPLETE —— 必须提高 read_budget')
        return 1 if a.strict else 0
    if ratio < WARN_RATIO:
        print(f'[budget] **余量低于 {int(WARN_RATIO*100)}%**：宿主 APK 一变大就会静默降级。'
              f'建议把 read_budget 提到 {int(need / (1 - WARN_RATIO) / 1048576)} MB 以上。')
        return 1 if a.strict else 0
    print('[budget] 余量充足')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
