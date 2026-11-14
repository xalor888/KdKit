#!/usr/bin/env python3
"""
kuaidui-kit / bridge_urls.py — do the H5 bridge actions ever carry *absolute* URLs?

`core_httpRequest` lets a page borrow the host's signed, session-bearing network stack (TRIAGE §8.1).
Whether that is a real exposure depends on what pages actually send: a relative path stays on the
app's own host, an absolute URL can point anywhere. This scans the captured bridge records and
classifies every URL-ish argument, so the question is answered with counts instead of intuition.

    python3 kit/scripts/bridge_urls.py work/packs/*/capture*.txt work/dpsdk/capture_bridge_*.txt
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio                                  # noqa: E402  （.gz 感知读取，2026-11-03 收敛）
import argparse
import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict


def read_lines(path):
    """抓取文件可能被 `pack_slim.py` 压成 .gz（证据不删、只压缩），两个形态都要能读。"""
    return textio.read_lines(path)      # 2026-11-03：四份逐字相同的读取器收敛成 `textio`
    # **必须写 `textio.` 而不是裸 `read_lines`**：本文件里就有同名函数，
    # 裸调用会无限递归（第一版就这么崩的，RecursionError）。

URLISH = re.compile(r'(https?://[^\s"\\]+)')
ACTIONS_WITH_URL = ('core_httpRequest', 'core_openUrl', 'core_openBrowser', 'core_downloader',
                    'core_fetchImg', 'core_openWindow', 'core_showImgBrowser', 'core_getUrl')


def urls_of(args: str):
    """拉出参数里的 url 字段（可能不是合法 JSON，退化为正则）。"""
    out = []
    try:
        doc = json.loads(args)
        if isinstance(doc, dict):
            for k in ('url', 'link', 'src', 'imgUrl'):
                v = doc.get(k)
                if isinstance(v, str) and v:
                    out.append(v)
    except Exception:
        # **原始串里的 `\\s` 是"反斜杠 + s"，不是空白**（2026-11-04 修，代码审查 P1）。
        #
        # 旧写法是 `r'"url"\\s*:\\s*"([^"]+)"'` —— raw string 里 `\\` 是两个字面字符，
        # 于是这个正则要求参数文本里真的出现 `\s`，而那永远不会发生
        # ⇒ **非 JSON 形态的 args 里 url 全丢**，报告显示"绝对 URL 0 条"，
        # 而真相是"解析失败"，两者看起来一样。
        #
        # 判据：`r'\s'` 才是空白；`r'\\s'` 是字面反斜杠 + s。
        # 键名**带不带引号都认**：真实抓取里 JSON 形态是 `"url":"…"`，
        # 而截断/拼接坏掉的行常是裸 `url:"…"`。只认带引号的会把后者全丢，
        # 而"这个页面没有绝对 URL"与"解析失败"看起来一样。
        m = re.search(r'(?:"url"|\burl)\s*:\s*"([^"]+)"', args)
        if m:
            out.append(m.group(1))
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('captures', nargs='+')
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv[1:])

    per_action = defaultdict(Counter)      # action -> Counter(relative/absolute)
    abs_hosts = Counter()
    samples_rel, samples_abs = [], []
    raw_abs = 0

    for path in a.captures:
        try:
            lines = read_lines(path)
        except OSError:
            continue
        for ln in lines:
            m = re.search(r'H5BRIDGE (\S+) count=(\d+) (.*)$', ln)
            if not m:
                continue
            action, args = m.group(1), m.group(3)
            if action not in ACTIONS_WITH_URL:
                continue
            for u in urls_of(args):
                if u.startswith(('http://', 'https://')):
                    per_action[action]['absolute'] += 1
                    h = urllib.parse.urlparse(u).netloc
                    abs_hosts[h] += 1
                    if len(samples_abs) < 6:
                        samples_abs.append((action, u[:110]))
                else:
                    per_action[action]['relative'] += 1
                    if len(samples_rel) < 6:
                        samples_rel.append((action, u[:110]))
            # 附带：参数里出现的裸 URL（不只在 url 字段里）
            for u in URLISH.findall(args):
                raw_abs += 1

    out = ['# H5 桥的 URL 参数：相对 vs 绝对（来自抓取样本）', '',
           f'* 样本文件：{len(a.captures)} 个（`work/packs/*/capture*.txt`、`work/dpsdk/capture_bridge_*.txt`）', '',
           '| action | 相对路径 | 绝对 URL |', '|---|---|---|']
    for action in ACTIONS_WITH_URL:
        c = per_action.get(action)
        if not c:
            continue
        out.append(f'| `{action}` | {c["relative"]} | **{c["absolute"]}** |')
    out += ['', f'* 绝对 URL 出现的域名：' + (', '.join(f'`{h}`×{n}' for h, n in abs_hosts.most_common(10)) or '无'),
            f'* 参数文本里出现的裸 URL 总数（含非 url 字段）：{raw_abs}', '',
            '## 相对路径样例', '']
    for act, u in samples_rel:
        out.append(f'* `{act}`：`{u}`')
    out += ['', '## 绝对 URL 样例', '']
    out += [f'* `{act}`：`{u}`' for act, u in samples_abs] or ['* （无）']
    out += ['', '**读法**：`core_httpRequest` 若**只有相对路径**，说明页面把"请求谁"交给了宿主（风险面 = 宿主自己的域）；'
            '绝对 URL 才会把请求引向宿主之外。这条结论决定了 §8.3 里那条"没有 host 白名单"到底有多严重。', '']
    text = '\n'.join(out) + '\n'
    if a.out:
        open(a.out, 'w').write(text)
        print(f'[urls] -> {a.out}')
    print(text[:1200])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
