#!/usr/bin/env python3
"""
kuaidui-kit / core_http_paths.py — H5 页面借宿主通道到底取了哪些数据。

`core_httpRequest` 让页面用**宿主的已签名、带会话**的通道发请求（`TRIAGE §8.1`）。
上一轮量出"某个页面 63 次调用"，但没回答"取的是什么"。这个脚本把每次调用的 `url` 归并成路径计数：

    python3 kit/scripts/core_http_paths.py --captures 'work/packs/*/capture*.txt' [--out work/CORE_HTTP_REQUESTS.md]

只看 `core_httpRequest`（`core_openUrl` 那类是打开页面，不是取数据）。
"""
import argparse
import glob
import json
import os
import re
import sys
import urllib.parse
from collections import Counter, defaultdict

# 输入指纹：让"这份文档是否还对应现在的输入"可以被判断，而不用重跑生成器
# （`kit/python/genstamp.py`；设备相关文档靠它补上"无法离线复跑"那一档）。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'python'))
import textio                                  # noqa: E402  （.gz 感知读取，2026-11-03 收敛）
import genstamp  # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def read_lines(path):
    return textio.read_lines(path)      # 2026-11-03：四份逐字相同的读取器收敛成 `textio`
    # **必须写 `textio.` 而不是裸 `read_lines`**：本文件里就有同名函数，
    # 裸调用会无限递归（第一版就这么崩的，RecursionError）。


def main(argv):
    ap = argparse.ArgumentParser()
    # **两个 glob 都要列**（2026-11-03 修）：同上。
    ap.add_argument('--captures', nargs='+',
                    default=[os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt'),
                             os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt.gz')])
    ap.add_argument('--out', default=None,
                        help='**不给 `--out` 会覆盖仓库里那份正式文档** —— 冒烟测试一律显式给 `--out /tmp/x.md`。')
    a = ap.parse_args(argv[1:])

    per_path = Counter()
    per_host = Counter()
    absolute = 0
    bad = 0
    files = []
    for g in a.captures:
        files += glob.glob(g)

    for path in files:
        for ln in read_lines(path):
            m = re.search(r'H5BRIDGE core_httpRequest count=\d+ (\{.*\})\s*$', ln)
            if not m:
                continue
            try:
                doc = json.loads(m.group(1))
            except Exception:
                bad += 1
                continue
            url = doc.get('url') or doc.get('URL') or ''
            if not isinstance(url, str) or not url:
                bad += 1
                continue
            if url.startswith('http'):
                absolute += 1
                pu = urllib.parse.urlparse(url)
                per_host[pu.netloc] += 1
                per_path[pu.path] += 1
            else:
                per_path[url.split('?')[0]] += 1

    total = sum(per_path.values())
    out = ['# H5 页面借宿主通道取了什么（`core_httpRequest` 逐条归类）', '',
           # 产物里写清怎么复跑：没有这一行，就没人能判断这份文件是不是过期了。
           # 这条命令是**离线**的（不碰设备），所以 `check_generated_fresh.py` 能自动复跑比对。
           *genstamp.header_line(['work/packs/*/capture*.txt', 'work/packs/*/capture*.txt.gz'], files).split('\n'),
           '* 复现：`python3 kit/scripts/core_http_paths.py '
           '--captures "work/packs/*/capture*.txt" "work/packs/*/capture*.txt.gz" '
           '--out work/CORE_HTTP_REQUESTS.md`',
           f'* 样本：{len(files)} 份抓取；有效记录 **{total}** 条（解析失败 {bad} 条）',
           f'* 其中**绝对 URL** {absolute} 条' + ('（与 §8.0 的"绝对 URL 0"结论一致）' if absolute == 0
                                                 else '（注意：与 §8.0 的观测不同，需要复核）'), '',
           '## 按路径', '', '| 路径 | 次数 |', '|---|---|']
    for p, n in per_path.most_common(30):
        out.append(f'| `{p}` | {n} |')
    if per_host:
        out += ['', '## 按 host', '', '| host | 次数 |', '|---|---|']
        for h, n in per_host.most_common():
            out.append(f'| `{h}` | {n} |')
    out += ['', '**怎么读**：这张表就是"**H5 层的数据面**" —— 页面自己不实现签名，'
            '所有需要登录态/签名的数据都经这里取；要判断某个页面能做什么，看它的路径集合即可。', '']
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'CORE_HTTP_REQUESTS.md')
    open(target, 'w').write(text)
    print(f'[core-http] -> {target}（{total} 条 / {len(per_path)} 个路径）')
    for p, n in per_path.most_common(5):
        print(f'   {n:4d}  {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
