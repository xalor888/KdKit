#!/usr/bin/env python3
"""
kuaidui-kit / index_evidence.py — one page that says where everything lives.

`work/` accumulates evidence across rounds: findings, per-round packs, captures, reports, JSON.
This walks it, groups the files by topic, and writes `work/INDEX.md`, so a later round (or another
person) can find the artifact for a topic without grepping the tree.

    python3 kit/scripts/index_evidence.py            # writes work/INDEX.md
    python3 kit/scripts/index_evidence.py --check    # exits 1 if the index is stale

Skipped: the two big decompilation trees (`work/apktool_out`, `work/jadx_out`) and the APK itself —
they are inputs, not evidence.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import argparse
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(ROOT, 'work')
# `src_backups` 不进索引（2026-11-03）：
#   ① 它是 `kit/` + `module/` 的**整份副本**，列进来只是把索引撑大一倍；
#   ② `preflight.sh` 每次建一个带时间戳的新目录、`--keep 10` 删旧的
#      ⇒ **路径集合每轮都变** ⇒ 门禁 ㉤ 每轮都红，直到重生成。
#   一份因为备份轮换而永远"过期"的索引，比没有索引更糟。
SKIP_DIRS = {'apktool_out', 'jadx_out', '__pycache__', '.git', 'src_backups'}
# **自己生成的东西不列入索引**（2026-11-03 修）。
#
# `INDEX.md` 与 `CATALOG.md` 都在 `work/` 底下，于是"写索引"这件事本身
# 会改掉索引要描述的对象（体积、mtime）⇒ 下一次 `--check` 永远 STALE。
# 实测：紧跟着重跑一次 `--check` 就红，diff 只有
#
#     | `INDEX.md` | 89K | 11-03 13:39 |
#
# 而 89K 是上一版的体积。**一份永远"过期"的索引比没有索引更糟** ——
# 它训练人忽略 `--check`。（今天第 4 次遇到"检查器/产物自指"，
# 前三次是 ㉘/㉙/㉜ 的正则匹配到自己。）
# `.test_run_cache.json` 是 `test_run.py` 的缓存（2026-11-03）——
# 它**每次跑都变**，列进索引会让 ㉤ 每轮都红。
# `gate_times.tsv` 也是计时落账的结果（2026-11-04）——
# 它每次 run_verify.sh 都变，列进索引会让 ㉤ 每轮都红。
# `negctl_times.tsv` 是负对照逐条计时的落账（2026-11-06）—— 每跑一次都变，
# 列进索引会让 ㉤ 每轮都红。
SKIP_FILES = {'.DS_Store', 'INDEX.md', 'CATALOG.md', '.test_run_cache.json',
              'gate_times.tsv', 'negctl_times.tsv'}

TOPICS = [
    ('总览 / 结论', [r'^TRIAGE\.md$', r'^API_SURFACE\.md$', r'^native_reversal\.md$',
                     r'^native_groundtruth\.md$', r'^INDEX\.md$']),
    ('反注入 / 原生', [r'^dpsdk/FINDINGS\.md$', r'^dpsdk/.*\.(png|md|txt|json|log)$', r'^maps.*\.txt$']),
    ('接口与协议', [r'^dpsdk/(kd_api|api|token|ad_|request_|probe_|pay_|string_|guard_).*',
                    r'^dpsdk/.*\.json$', r'^core_actions\.txt$', r'^feactions\.txt$']),
    ('桥 / H5', [r'^dpsdk/(capture_bridge|bridge_)', r'^h5/']),
    ('每轮证据包', [r'^packs/']),
    ('图表/截图', [r'\.png$']),
    ('其它抓取与日志', [r'^dpsdk/capture.*\.txt$', r'^dpsdk/.*\.log$', r'^dpsdk/logcat.*']),
]


def human(n):
    for unit in ('B', 'K', 'M'):
        if n < 1024:
            return f'{n:.0f}{unit}'
        n /= 1024
    return f'{n:.1f}G'


def collect():
    files = []
    for root, dirs, names in os.walk(WORK):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if n in SKIP_FILES:
                continue
            p = os.path.join(root, n)
            rel = os.path.relpath(p, WORK)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((rel, st.st_size, st.st_mtime))
    return files


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='fail if the index would change')
    ap.add_argument('--full', action='store_true',
                    help='--check 时比对整篇（含体积/mtime 列），而不是只比对路径集合。'
                         '默认后者：前者太脆 —— Pipeline 自己会写 work/')
    a = ap.parse_args(argv[1:])

    files = collect()
    rounds = []
    rm = textio.read_text(os.path.join(ROOT, 'ROADMAP.md'), encoding='utf-8')
    for m in re.finditer(r'^### (R\d+).*?：(.+)$', rm, re.M):
        rounds.append((m.group(1), m.group(2).strip()))

    packs = sorted({f.split('/')[1] for f, _s, _t in files if f.startswith('packs/') and '/' in f[6:]})

    out = ['# work/ 证据索引', '',
           f'* 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
           f'* 文件数：{len(files)}；总体积：{human(sum(s for _f, s, _t in files))}',
           f'* 轮次日志：{len(rounds)} 轮（`ROADMAP.md`）', '']

    out += ['## 按主题', '']
    used = set()
    for title, pats in TOPICS:
        rows = []
        for rel, size, mtime in sorted(files, key=lambda x: -x[2]):
            if rel in used:
                continue
            if any(re.search(p, rel) for p in pats):
                rows.append((rel, size, mtime))
        if not rows:
            continue
        used.update(r[0] for r in rows)
        out += [f'### {title}', '', '| 文件 | 体积 | 修改 |', '|---|---|---|']
        for rel, size, mtime in rows[:120]:
            out.append(f'| `{rel}` | {human(size)} | {datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")} |')
        if len(rows) > 120:
            out.append(f'| _（还有 {len(rows) - 120} 个）_ | | |')
        out.append('')

    big = [(rel, sz, t) for rel, sz, t in files if sz > 20 * 1024 * 1024]
    files = [(rel, sz, t) for rel, sz, t in files if sz <= 20 * 1024 * 1024]
    if big:
        out += ['## 超大原始转储（>20M，只归档不阅读）', '', '| 文件 | 体积 |', '|---|---|']
        for rel, size, _t in sorted(big, key=lambda x: -x[1]):
            out.append(f'| `{rel}` | {human(size)} |')
        out.append('')

    rest = [(rel, s, t) for rel, s, t in sorted(files, key=lambda x: -x[2]) if rel not in used]
    if rest:
        out += ['## 其它文件', '', '| 文件 | 体积 | 修改 |', '|---|---|---|']
        for rel, size, mtime in rest[:60]:
            out.append(f'| `{rel}` | {human(size)} | {datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M")} |')
        out.append('')

    out += ['## 证据包（每轮一条命令产出）', '',
            '| 包 | 内容 |', '|---|---|']
    for p in packs:
        idx = os.path.join(WORK, 'packs', p, 'index.md')
        brief = ''
        if os.path.exists(idx):
            line = next((l for l in textio.read_lines(idx, encoding='utf-8') if l.startswith('| `acceptance`')), '')
            brief = line.split('|')[2].strip() if line else ''
        out.append(f'| `packs/{p}` | {brief} |')
    out.append('')

    # 轮次 → 证据文件：把每轮正文里出现的、真实存在的路径抓出来
    path_rx = re.compile(r'`([\w./\-]+\.(?:md|txt|json|png|py|sh|kt|so|c))`')
    sections = re.split(r'^### ', rm, flags=re.M)[1:]
    round_files = []
    for sec in sections:
        head, _, body = sec.partition('\n')
        m = re.match(r'(R\d+)', head)
        if not m:
            continue
        files_found = []
        for cand in path_rx.findall(body):
            cand = cand.lstrip('/')
            # emit a repo-root-relative path so the table is unambiguous wherever it is read
            for base, prefix in ((ROOT, ''), (WORK, 'work/'), (os.path.join(ROOT, 'kit'), 'kit/')):
                if not cand.startswith(prefix):
                    continue
                rel = cand[len(prefix):] if prefix else cand
                if os.path.exists(os.path.join(base, rel)):
                    files_found.append(cand)
                    break
            else:
                # bare name that only exists under work/ → say so explicitly
                if os.path.exists(os.path.join(WORK, cand)):
                    files_found.append('work/' + cand)
        round_files.append((m.group(1), head.split('：')[-1].strip(), sorted(set(files_found))))

    out += ['## 轮次 → 证据文件', '',
            '（从 `ROADMAP.md` 每轮正文里抓出的、真实存在的路径；这是"想回看某一轮"的最快入口）', '',
            '| 轮次 | 主题 | 证据 |', '|---|---|---|']
    for rid, title, fl in round_files[-24:]:
        files_cell = '<br>'.join(f'`{f}`' for f in fl) if fl else '_(正文未列路径)_'
        out.append(f'| **{rid}** | {title[:40]} | {files_cell} |')
    out.append('')

    out += ['## 最近 12 轮', '']
    for rid, title in rounds[-12:]:
        out.append(f'* **{rid}** {title}')
    out += ['', '_由 `kit/scripts/index_evidence.py` 生成；`--check` 可用于判断索引是否过期。_', '']

    text = '\n'.join(out) + '\n'
    target = os.path.join(WORK, 'INDEX.md')
    if a.check:
        # **默认只比对"路径集合"**（2026-11-03 改）。
        #
        # 第一版比对整篇文本（除时间戳行），于是 `verify.sh` 自己往 `work/`
        # 写的任何东西都会让这道门禁在**跑完之后**变红 —— 实测就是：
        # 门禁按顺序跑，㉤ 之后还有几条会写 `work/baselines/…`。
        # 一道" Pipeline 自己弄脏自己"的门禁等于没有。
        #
        # 而索引的用途是"**某个文件在哪**"：路径集合才对得上这个用途。
        # 体积/mtime 是附赠，它们变旧不构成"索引指错地方"。
        # `--full` 仍然给严格比对（含体积列），供人工复查用。
        def paths_of(t):
            return {m for m in re.findall(r'`([^`]+)`', t)}

        old = open(target, encoding='utf-8').read() if os.path.exists(target) else ''
        if a.full:
            strip = lambda x: '\n'.join(l for l in x.splitlines()
                                        if not l.startswith('* 生成时间'))
            same = strip(old) == strip(text)
        else:
            same = paths_of(old) == paths_of(text)
        if not same:
            print('[index] STALE: work/INDEX.md 需要重新生成')
            if not a.full:
                miss = paths_of(text) - paths_of(old)
                extra = paths_of(old) - paths_of(text)
                if miss:
                    print(f'[index]   索引里没有的 {len(miss)} 个：'
                          + ', '.join(sorted(miss)[:5]))
                if extra:
                    print(f'[index]   索引里多出的 {len(extra)} 个：'
                          + ', '.join(sorted(extra)[:5]))
            return 1
        print('[index] up to date' + ('（整篇）' if a.full else '（路径集合）'))
        return 0
    textio.write_text(target, text)
    print(f'[index] -> {target}  ({len(files)} files, {len(rounds)} rounds, {len(packs)} pack(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
