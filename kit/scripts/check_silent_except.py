#!/usr/bin/env python3
"""
kuaidui-kit / check_silent_except.py — **不许有"完全静默"的 `except Exception: pass`**。

### 为什么需要

2026-11-06 代码审查 P1：非测试代码里 **16 处** `except Exception:` 的函数体
**只有一个 `pass`** —— 异常被完全吞掉，不打印、不记录、不改变任何结果。

这一类最危险的形态：

```python
try:
    d = json.loads(rc4(key, b64decode(d['encodeData'])))
except Exception:
    pass
```

解密失败 ⇒ `d` 保持原样 ⇒ 报告里只剩 `errNo`，
**读报告的人会以为"这个接口本来就只返回 errNo"**。
而真相是"密钥不对 / 载荷坏了"。

第二种形态更隐蔽：

```python
try:
    if decrypt_with_key(key, c).strip() == p.strip(): ok += 1
except Exception:
    pass
```

"解密抛异常"和"解出来但对不上"混成同一件事 ——
两个都只是"少算一个 ok"，而 `ok/总数` 那个比例**看不出是哪一种**，
但两者的排查方向完全相反（密钥错 vs 样本不是同一份）。

### 判据

AST 扫 `kit/python/*.py` + `kit/scripts/*.py`（不含 tests）：

* `except` 的类型里含 `Exception` / `BaseException`；
* handler 的函数体（去掉 docstring）**只有一个 `pass`**；

⇒ 报出来。

**豁免**：下面两类是**合法**的静默，必须登记在 `ALLOW` 里并写清理由：

* 清理路径（`os.killpg` 之后 `communicate` 失败 —— 进程已经死了，收不收输出无所谓）；
* 探测路径（"试一下，不行就算了"）。

⇒ **豁免必须逐条写理由**，不能只按文件名放行。

### 退出码

0 = 没有未登记的完全静默；1 = 有。
"""
import argparse
import ast
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

SCAN = (os.path.join(ROOT, 'kit', 'python', '*.py'),
        os.path.join(ROOT, 'kit', 'scripts', '*.py'))

#: 逐条豁免（`相对路径:行号` → 理由）。**逐条**是为了让理由在 diff 里可见。
ALLOW = {
    'kit/python/sh.py:78': '清理路径：进程已被 SIGKILL，`communicate` 收不到输出也无妨',
    'kit/python/sh.py:98': '同上（`run()` 版）',
    'kit/python/composition_flow.py:96': '清理路径：进程已结束',
    'kit/python/composition_flow.py:124': '清理路径：进程已结束',
    'kit/python/export_content.py:114': '可选产物缺失（不是必需产物）',
    'kit/python/extract_samples.py:161': '跳过一条读不到的样本',
    'kit/scripts/catalog.py:79': '目录扫描：单个条目读不到就跳过，不影响其余',
    'kit/scripts/coverage_check.py:42': '单个文件读不到就跳过它',
    'kit/scripts/daily_report.py:64': '单个证据包读不到就跳过它',
    'kit/scripts/evidence_pack.py:614': '可选产物缺失（不是必需产物）',
    'kit/scripts/server_snapshot.py:101': '快照单项缺失就跳过',
    'kit/scripts/verify_inputs.py:67': '设备不在线 ⇒ 这台设备没有 apk 身份',
    'kit/scripts/xlog_decode.py:62': '单条 xlog 解不开就跳过它',
}


def is_silent(handler):
    body = []
    for st in handler.body:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
            continue                       # docstring
        body.append(st)
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--allow', action='append', default=[],
                    help='额外的豁免（相对路径:行号），必须带理由')
    a = ap.parse_args(argv[1:])

    allow = dict(ALLOW)
    for extra in a.allow:
        if ':' not in extra:
            print(f'[silent] --allow 必须写成 `路径:行号`（现在只有 {extra!r}）')
            return 2
        path, line = extra.rsplit(':', 1)
        allow[path] = '（命令行豁免）'

    hits = []
    used = set()
    for pat in SCAN:
        for p in sorted(glob.glob(pat)):
            rel = os.path.relpath(p, ROOT)
            try:
                with open(p, encoding='utf-8', errors='replace') as f:
                    tree = ast.parse(f.read())
            except (OSError, SyntaxError, ValueError):
                continue
            for n in ast.walk(tree):
                if not isinstance(n, ast.ExceptHandler) or n.type is None:
                    continue
                tname = ast.unparse(n.type)
                if 'Exception' not in tname and 'BaseException' not in tname:
                    continue
                if not is_silent(n):
                    continue
                key = f'{rel}:{n.lineno}'
                if key in allow:
                    used.add(key)
                    continue
                hits.append(key)

    # **陈旧豁免也是错误**（2026-11-06 加）。
    #
    # 豁免表按 `路径:行号` 索引，而**行号会随代码移动** ——
    # 修一个 bug 让下面多了两行，豁免就指向了别的地方：
    # 真正静默的那处不再被豁免（红），而豁免表里躺着一条**永远不会触发的记录**。
    # 于是这张表会越长越大，而长大的豁免表就是"永远绿的门禁"。
    #
    # 修法：豁免必须**对得上一个真实存在的静默 handler**，否则红。
    stale = sorted(set(allow) - used)

    print(f'[silent] 完全静默的 `except Exception: pass`：{len(hits)} 处'
          f'（已登记豁免 {len(allow)} 条，其中对不上代码的 {len(stale)} 条）')
    for st in stale:
        print(f'  ✗   陈旧豁免：{st} —— 那一行现在不是静默的 `except` 了')
    for h in hits:
        print(f'  ✗   {h}')
    if stale:
        print('[silent]   修法：把陈旧豁免删掉。**留着它等于给自己一张空白通行证** —— '
              '下次那行真的变回静默时，门禁会沉默。')
    if hits or stale:
        print('[silent]   修法：至少把失败**说出来**（写进产物 / 返回值 / stderr）。')
        print('[silent]   "解不开"和"本来就那样"在产物里长得一样 ⇒ 读者会得出相反的结论。')
        print('[silent]   确实该静默的，加进 `ALLOW` 并写清理由。')
        return 1
    if a.verbose:
        print('[silent] 没有未登记的完全静默、也没有陈旧豁免 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
