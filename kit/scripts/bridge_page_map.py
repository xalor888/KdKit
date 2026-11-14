#!/usr/bin/env python3
"""
kuaidui-kit / bridge_page_map.py — 「哪个页面在调用桥的哪个能力」，以及「它自己还请求了什么」。

抓取流里有两类记录：`page: <url>`（WebInjector 记录页面）与 `H5BRIDGE <action> count=N <args>`。
按**时间顺序**把每条 action 归到它最近的**前一个** page 上，就得到一张页面→能力的表；
`WEBREQ`（模块功能 `web_request_log` 记录的**页面自有请求**）走同一套时间戳合并，附在每个页面下方；
再用两张注册表（`work/feactions.txt` 215 个 `@FeAction`、`work/core_actions.txt` 44 个核心桥 action）
标注每条 action 属于**哪一层**。

    python3 kit/scripts/bridge_page_map.py --captures 'work/packs/*/capture*.txt' --out work/BRIDGE_PAGE_MAP.md
"""
import argparse
import glob
import os
import re
import subprocess
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


def registry_names():
    fe, core = set(), set()
    # 第一层的完整清单在 bridge_actions_full.txt（260 条 = @FeAction 214 + 注解生成器多出的 46）；
    # 旧表 feactions.txt 是它的子集 —— 缺它会把这些动作误标成"未登记"（2026-10-12 踩过）。
    for name, target in (('bridge_actions_full.txt', fe), ('feactions.txt', fe)):
        p = os.path.join(ROOT, 'work', name)
        if not os.path.exists(p):
            continue
        for line in textio.read_lines(p, encoding='utf-8'):
            if line.startswith('#'):
                continue
            m = re.match(r'^(\S+)\s*$', line.strip())
            if m:
                target.add(m.group(1))
    p = os.path.join(ROOT, 'work', 'core_actions.txt')
    if os.path.exists(p):
        for line in textio.read_lines(p, encoding='utf-8'):
            m = re.match(r'^(\S+)\s', line)
            if m and not line.startswith('#'):
                core.add(m.group(1))
    return fe, core


def short(url):
    try:
        u = urllib.parse.urlparse(url)
        tail = u.path.rsplit('/', 1)[-1] or u.path
        return f'{u.netloc}/{tail[:44]}'
    except Exception:
        return url[:60]


def main(argv):
    ap = argparse.ArgumentParser()
    # **两个 glob 都要列**（2026-11-03 修）：同上，漏 `.gz` 会静默少读一半抓取。
    ap.add_argument('--captures', nargs='+',
                    default=[os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt'),
                             os.path.join(ROOT, 'work', 'packs', '*', 'capture*.txt.gz')])
    ap.add_argument('--adb', default=None,
                    help='从该设备的模块日志里取 page: 行（抓取里只有 action，页面标记只在模块日志里 —— 2026-10-12 实测）')
    ap.add_argument('--out', default=None,
                        help='**不给 `--out` 会覆盖仓库里那份正式文档** —— 冒烟测试一律显式给 `--out /tmp/x.md`。')
    a = ap.parse_args(argv[1:])

    fe, core = registry_names()
    per_page = defaultdict(Counter)
    per_page_web = defaultdict(Counter)
    layer = Counter()
    pages_seen = set()

    # 两条流、同一个时钟：模块日志给 `page:`，抓取给 `H5BRIDGE`。按时间戳合并。
    def hhmmss(line):
        m = re.search(r'(\d{2}:\d{2}:\d{2}\.\d{3})', line)
        return m.group(1) if m else None

    events = []          # (time, 'page'|'action'|'web', payload)
    files = []
    for g in a.captures:
        files += glob.glob(g)
    for path in files:
        for ln in read_lines(path):
            m = re.search(r'H5BRIDGE (\S+) count=(\d+)', ln)
            _json_tail = None
            if m and m.group(1) == 'core_httpRequest':
                _j = re.search(r'(\{.*)$', ln)
                if _j:
                    _json_tail = _j.group(1)
            if m:
                t = hhmmss(ln)
                if t:
                    _u = None
                    if _json_tail:
                        _mm = __import__('re').search(r'"url"\s*:\s*"([^"]+)"', _json_tail)
                        if _mm:
                            _u = _mm.group(1).replace('\\/', '/')
                    events.append((t, 'action', (m.group(1), int(m.group(2)), _u)))
                continue
            m = re.search(r'WEBREQ (https?://\S+)', ln)
            if m:
                t = hhmmss(ln)
                if t:
                    u = m.group(1).split('?')[0]
                    pu = urllib.parse.urlparse(u)
                    host = pu.netloc
                    tail = pu.path.rsplit('/', 1)[-1]
                    label = host if (tail.endswith(('.js', '.css', '.png', '.jpg', '.ico', '.svg',
                                                    '.woff', '.woff2', '.html', '.webp'))
                                     ) else f'{host}{pu.path}'
                    events.append((t, 'web', label))

    page_src = ''
    if a.adb:
        out = subprocess.run(f'adb -s {a.adb} shell "grep -ah \'page: http\' /data/adb/lspd/log/modules_*.log"',
                             shell=True, capture_output=True, text=True, errors='replace', timeout=300, start_new_session=True)
        for ln in out.stdout.splitlines():
            m = re.search(r'T(\d{2}:\d{2}:\d{2}\.\d{3}).*page: (https?://\S+)', ln)
            if m:
                events.append((m.group(1), 'page', m.group(2)))
        page_src = f'（页面取自 `{a.adb}` 的模块日志）'
    events.sort(key=lambda e: (e[0], 0 if e[1] == 'page' else 1))

    per_page_req = defaultdict(Counter)   # 2026-10-13：文件里用的是 `from collections import …` ✓
    page = None
    for t, kind, payload in events:
        if kind == 'page':
            page = payload
            pages_seen.add(page)
        elif kind == 'web' and page:
            per_page_web[page][payload] += 1
        elif page:
            act, n = payload[0], payload[1]
            _url = payload[2] if len(payload) > 2 else None
            if _url:
                per_page_req[page][_url] += 1
            per_page[page][act] += n
            layer['core' if act in core else ('fe' if act in fe else '其它')] += 1

    out = ['# 页面 → 桥能力（自动生成）', '',
           # 生成器**必须**把自己怎么被调用写进产物里：否则没人能判断这份文件是不是过期了，
           # 也没人能复跑（2026-11-02 审查：`work/` 下 4 份自动生成文档都没有这一行）。
           # **头部写的 glob 必须是实际用的那些**（2026-11-03 修）。
           # 旧实现写死单个 `work/packs/*/capture*.txt`，而 `--captures` 早就接受
           # 多个（`pack_slim` 把旧包压成 `.gz` 之后必须两个都列）。
           # 于是头部说"输入：这一个 glob（1240 个文件）"，
           # 而门禁 ⑭ 按头部那个 glob 只展开到 349 个 ⇒ 判"过期"。
           # **一份文档对自己输入的说法不实**，比没有这一行更糟。
           *genstamp.header_line(a.captures, files).split('\n'),
           '* 复现：`python3 kit/scripts/bridge_page_map.py'
           + (f' --adb {a.adb}' if getattr(a, 'adb', None) else '')
           # **两个 glob 都要列**（2026-11-03 修）：`pack_slim.py` 会把旧包压成
           # `.txt.gz`，而读取侧（本文件 :33）本来就接受 `.gz`。只列 `*.txt` 的
           # 复现命令会让照着跑的人**漏掉一半输入**，还以为自己复现了。
           + ' --captures "work/packs/*/capture*.txt" "work/packs/*/capture*.txt.gz"'
           + ' --out work/BRIDGE_PAGE_MAP.md`',
           f'* 来源：{len(files)} 份抓取 {page_src}；按**时间戳**把 `H5BRIDGE <action>` 归到最近的 `page:`',
           '* 层次标注来自两张注册表：`work/feactions.txt`（`@FeAction`）与 `work/core_actions.txt`（核心桥）', '',
           f'* 覆盖 **{len(pages_seen)}** 个页面；动作层次分布：' +
           '、'.join(f'{k} {v}' for k, v in layer.most_common()), '']
    # 2026-10-13 修 ✓（`doc_dups` 的假阳性把这里暴露出来 ✓）：
    # `short()` 把尾部截到 44 字符 ✗ ⇒ **两个长 URL 会截成同名** ✗ ⇒ 标题看着重复 ✓。
    # 修法：**同名时补一个 4 位摘要** ✓ —— 既不改变常见情形 ✓，也**让同名可区分** ✓。
    _labels = {}
    for page, actions in sorted(per_page.items(), key=lambda kv: -sum(kv[1].values()))[:12]:
        total = sum(actions.values())
        _lab = short(page)
        if _lab in _labels:
            _lab = f'{_lab} #%s' % __import__('hashlib').md5(page.encode()).hexdigest()[:4]
        _labels[_lab] = page
        out += [f'## `{_lab}`（{total} 次调用 / {len(actions)} 个 action）', '',
                f'* 原页面：`{page[:120]}`', '',
                '| action | 层次 | 次数 |', '|---|---|---|']
        for act, n in actions.most_common(14):
            lv = '核心桥' if act in core else ('@FeAction' if act in fe else '未登记')
            out.append(f'| `{act}` | {lv} | {n} |')
        web = per_page_web.get(page)
        if web:
            # 把页面自有的去向分成四类 —— 这才回答"这个页面向外说了什么"
            def kind_of(u):
                if 'api.kuaiduizuoye.com' in u:
                    return '业务接口'
                if u.startswith('rumt-zh.com'):
                    return '埋点·第三方'
                if u.startswith('log.') or u.startswith('zyb-stats'):
                    return '埋点·一方'
                if any(x in u for x in ('cdn.', 'static.', 'sanxia-')):
                    return '静态资源'
                return '其它'
            groups = defaultdict(Counter)
            for u, n in web.items():
                groups[kind_of(u)][u] += n
            out += ['', f'**页面自有的去向（{sum(web.values())} 次）**：']
            for name in ('业务接口', '埋点·一方', '埋点·第三方', '静态资源', '其它'):
                g = groups.get(name)
                if not g:
                    continue
                top = sum(g.values())
                sample = '、'.join(f'`{u.split("/")[0]}{"/" + u.split("/")[1] if "/" in u else ""}`×{n}'
                                   for u, n in g.most_common(3))
                out.append(f'* **{name}** {top} 次 —— {sample}')
        out.append('')
    out += ['**怎么读**：这张表回答"页面能碰到的能力边界" —— 哪个页面用到核心桥（`core_*`）值得单独看，'
            '因为核心桥里才是真正有宿主能力的那批（`core_httpRequest`/`core_login`/`core_FIRE`…）。', '']
    # 2026-10-13 新增 ✓：**页面 → 端点**（数据一直都在 ✓，此前只数了动作名 ✗）
    out += ['', '---', '', '## 页面 → 端点（`core_httpRequest` 的目标 ✓）', '']
    _rows = []
    for pg, reqs in per_page_req.items():
        for u, n in reqs.items():
            _rows.append((pg, u, n))
    _rows.sort(key=lambda r: (-r[2], r[0]))
    if _rows:
        out += ['| 页面 | 端点 | 次数 |', '|---|---|---|']
        for pg, u, n in _rows[:40]:
            out.append(f'| `{short(pg)}` | `{u}` | {n} |')
    else:
        out.append('* （本轮抓取里没有 `core_httpRequest` ✓）')
    out.append('')
    text = '\n'.join(out) + '\n'
    target = a.out or os.path.join(ROOT, 'work', 'BRIDGE_PAGE_MAP.md')
    textio.write_text(target, text)
    print(f'[bridge] -> {target}（{len(pages_seen)} 页）')
    print('  层次分布:', dict(layer))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
