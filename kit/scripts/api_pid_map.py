#!/usr/bin/env python3
"""
kuaidui-kit / api_pid_map.py — 接口路径 ↔ 业务域 `__pid` 的映射（从 smali 静态提取）。

## 为什么需要

宿主每个请求类（`Xxx$Input`）在自己的构造器里写死两个常量：

```smali
const-string v0, "/kdapi/popup/gradeupgrade"
iput-object v0, p0, .../InputBase;->__url:Ljava/lang/String;
const-string v0, ""
iput-object v0, p0, .../InputBase;->__pid:Ljava/lang/String;
```

`__url` 是路径，`__pid` 是**业务域标签**（`saas-passport` / `cube` / `vip` / `sell` … 或空）。

这个映射在两类工作里都要用：

1. **重放接口**（`SIGNED_SURFACE.md`）：判断重放失败是签名问题还是 pid 带错了。
   此前重放工具完全不看 pid —— 而它可能是服务端分流校验的依据。
2. **读抓取**：`WEBREQ /kdapi/xxx` 一眼看出属于哪个域，比猜路径前缀可靠。

## 用法

```bash
python3 kit/scripts/api_pid_map.py --smali work/apktool_out            # 人读
python3 kit/scripts/api_pid_map.py --smali work/apktool_out --json     # 机器读
python3 kit/scripts/api_pid_map.py --smali work/apktool_out --path /kdapi/popup/gradeupgrade
```

## 边界（重要）

* 只解析**字面量**写入。pid 若是运行时拼出来的，这里看不到 —— 那类请求会显示 `?`。
* 一个路径可能被多个类声明（不同 pid），这里**全部保留**，不合并成一条。
* 这是静态事实，不证明运行时真的发出去了。
"""
import argparse
import glob
import json
import os
import re
import sys

# 允许 `iput-object` 与 `const-string` 之间有最多 3 行（Robust 的 PatchProxy 常插在中间）。
# 注意：不能用 `str.format` —— 正则里的 `{0,3}` 会被当成占位符。
_CONST_THEN_IPUT = (r'const-string ([vp]\d+), "([^"]*)"\s*\n'
                    r'(?:[^\n]*\n){0,3}?[^\n]*iput-object \1, [vp]\d+, '
                    r'%s->__%s:')


def _field_re(cls, field):
    return re.compile(_CONST_THEN_IPUT % (re.escape(cls), field))


URL_RE = _field_re('Lcom/baidu/homework/common/net/model/v1/common/InputBase;', 'url')
PID_RE = _field_re('Lcom/baidu/homework/common/net/model/v1/common/InputBase;', 'pid')
METHOD_RE = re.compile(
    r'const ([vp]\d+), (0x[0-9a-f]+|\d+)\s*\n'
    r'(?:[^\n]*\n){0,3}?[^\n]*iput(?:-object)? \1, [vp]\d+, '
    r'Lcom/baidu/homework/common/net/model/v1/common/InputBase;->__method:')


def smali_roots(root):
    out = [root] if os.path.isdir(os.path.join(root, 'com')) else []
    for d in sorted(os.listdir(root)):
        p = os.path.join(root, d)
        if os.path.isdir(p) and (d == 'smali' or re.fullmatch(r'smali_classes\d+', d)):
            out.append(p)
    return out


def scan(root):
    """`[{url, pid, cls, file}]` —— 每个 (类, 路径) 一条。pid 缺失时为 None。"""
    rows = []
    for base in smali_roots(root):
        for path in glob.iglob(os.path.join(base, '**', '*Input.smali'), recursive=True):
            try:
                with open(path, encoding='utf-8', errors='replace') as fh:
                    text = fh.read()
            except OSError:
                continue
            if '__url' not in text:
                continue
            m = URL_RE.search(text)
            if not m:
                continue
            url = m.group(2)
            p = PID_RE.search(text)
            rows.append({
                'url': url,
                'pid': (p.group(2) if p else None),
                'cls': _class_of(text) or os.path.basename(path)[:-6],
                'file': os.path.relpath(path, root),
            })
    rows.sort(key=lambda r: (r['url'], r['pid'] or ''))
    return rows


def _class_of(text):
    m = re.search(r'^\.class [\w ]*L([\w/$]+);', text, re.M)
    return m.group(1).replace('/', '.') if m else None


def lookup(rows, path):
    """某个路径的全部声明（可能多个 pid）。"""
    return [r for r in rows if r['url'] == path]


def main(argv):
    ap = argparse.ArgumentParser(description='接口路径 ↔ __pid 业务域映射')
    ap.add_argument('--smali', default='work/apktool_out')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--path', help='只查这一个路径')
    a = ap.parse_args(argv[1:])

    if not os.path.isdir(a.smali):
        print(f'找不到 {a.smali}', file=sys.stderr)
        return 2
    rows = scan(a.smali)

    if a.path:
        hits = lookup(rows, a.path)
        if not hits:
            print(f'{a.path}: 没有 Input 类声明它（可能是动态拼接的 URL）')
            return 1
        for h in hits:
            print(f"  pid={h['pid'] if h['pid'] is not None else '?'}  {h['cls']}")
        return 0

    if a.json:
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return 0

    # 人读：按 pid 分组，空的排最后
    from collections import defaultdict
    by = defaultdict(list)
    for r in rows:
        by[r['pid']].append(r['url'])
    order = sorted(by, key=lambda k: (k is None, k or ''))
    for pid in order:
        label = '(空 pid)' if pid in (None, '') else pid
        print(f'## {label}  ({len(by[pid])} 条)')
        for u in sorted(set(by[pid]))[:6]:
            print(f'   {u}')
        if len(set(by[pid])) > 6:
            print(f'   … 另有 {len(set(by[pid])) - 6} 条')
        print()
    print(f'[pid] {len(rows)} 个 (类, 路径) 声明，{len({r["url"] for r in rows})} 个唯一路径，'
          f'{len({r["pid"] for r in rows})} 种 pid')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
