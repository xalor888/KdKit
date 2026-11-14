#!/usr/bin/env python3
"""
kuaidui-kit / test_run.py — **跑一次 Python 测试套件，并把结果缓存给其它门禁读**。

### 为什么需要

2026-11-03 实测：`bash module/scripts/verify.sh` 要 **842 秒**，
而单跑一次 Python 测试套件是 **177 秒**。三道门禁各跑一遍：

| 门禁 | 它要什么 |
|---|---|
| ①b 抓取解析器 | 套件是绿的 |
| ㉥ 跳过数在限内 | 每条 skip 的**理由**与条数 |
| ㉦ 覆盖数不缩水 | 测试总条数 |

**同一个 177 秒跑了三遍，只为了读三个数。** 这是今天加门禁时自己造成的。

### 做法

跑一次，把 `{rc, count, skips}` 写进 `work/.test_run_cache.json`；
三道门禁都读它。缓存**不是**“上次的结果永远有效” —— 判据是：

* 同一个 Python 解释器（`sys.executable` 相同）；
* 年龄 < `MAX_AGE`（默认 3600 秒）；
* 任何 `kit/python/**/*.py` 或 `kit/scripts/**.py` 比缓存新 ⇒ **立即视为过期**。

第三条是关键：改了代码之后缓存必须失效，否则这道缓存会变成
“跑的是旧代码的结论”——今天已经在 `.pyc` 上栽过一次（R93/R108）。

### 用法

    python3 kit/scripts/test_run.py --ensure           # 有新鲜缓存就复用，否则跑
    python3 kit/scripts/test_run.py --ensure --quiet   # 同上，不打印套件输出
    python3 kit/scripts/test_run.py --refresh          # 强制重跑
    python3 kit/scripts/test_run.py --show             # 只打印缓存内容（不跑）

退出码：0 = 套件绿；1 = 套件红；2 = 跑不了（解释器缺失等）。
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(ROOT, 'work', '.test_run_cache.json')
TESTS = os.path.join(ROOT, 'kit', 'python', 'tests')

#: 缓存最多活这么久。超过就重跑 —— 不是“因为懒”，是因为一次跑 3 分钟，
#: 而一轮里可能改好几次代码。
MAX_AGE = 3600

SKIP_MARK = '... skipped '


def source_fingerprint():
    """所有 Python 源文件的**内容指纹**。

    **为什么不用 mtime**（2026-11-04 改）：

    第一版用 `max(mtime)` 判"代码有没有变"。但 `run_negative_controls.py`
    的注入-还原会把文件的 mtime 顶到"现在"——即使我显式 `os.utime` 还原，
    实测仍有文件带着新 mtime 活下来（`device_entry_crypto.py` 那次）。
    于是**紧跟在 ㉖ 之后的 ㉥ 每次都重跑一遍 150 秒的套件**。

    内容指纹是**语义**判据：内容逐字节没变，缓存就该有效 ——
    不管 mtime 被谁碰过。200 个文件算 sha256 大约 0.1 秒，比误判一次的代价小得多。
    """
    import hashlib
    h = hashlib.sha256()
    paths = []
    for pat in ('kit/python/*.py', 'kit/python/tests/*.py', 'kit/scripts/*.py'):
        paths += glob.glob(os.path.join(ROOT, pat))
    for p in sorted(paths):
        h.update(os.path.relpath(p, ROOT).encode())
        h.update(b'\0')
        try:
            with open(p, 'rb') as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(b'<unreadable>')
    return h.hexdigest()[:32]


def read_cache():
    try:
        with open(CACHE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def cache_is_fresh(c):
    if not c:
        return False, '没有缓存'
    if c.get('python') != sys.executable:
        return False, f'解释器变了（{c.get("python")} ≠ {sys.executable}）'
    age = time.time() - c.get('finished', 0)
    if age > MAX_AGE:
        return False, f'缓存 {age:.0f}s 前写的，超过 {MAX_AGE}s'
    want = source_fingerprint()
    if c.get('src_hash') != want:
        return False, f'源码内容变了（{c.get("src_hash", "?")[:8]} → {want[:8]}）'
    return True, f'缓存 {age:.0f}s 前写的，源码内容逐字节相同'


def parse_output(out):
    """从 `unittest -v` 的输出里抽出条数与每条 skip 的理由。"""
    count = 0
    skips = {}
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('Ran ') and ' test' in s:
            try:
                count = int(s.split()[1])
            except (IndexError, ValueError):
                pass
        i = s.find(SKIP_MARK)
        if i >= 0:
            reason = s[i + len(SKIP_MARK):].strip()
            if reason.startswith("'") and reason.endswith("'"):
                reason = reason[1:-1]
            if reason:
                skips[reason] = skips.get(reason, 0) + 1
    return count, skips


def ensure_suite(quiet=False):
    """**有新鲜缓存就复用，否则才跑**。

    原来三道门禁各自调 `run_suite()` —— 于是同一个 150 秒的套件
    在一轮里跑了三遍。`verify.sh` 因此多花 5 分钟（842 秒里的一大块）。

    这就是这道门禁存在的意义：**跑一次，三道门禁读同一份结果**。
    """
    if in_negctl():
        print('[test-run] 负对照进行中 ⇒ 不用缓存，直接跑', file=sys.stderr)
        return run_suite(quiet=quiet)
    c = read_cache()
    ok, why = cache_is_fresh(c)
    if ok:
        if not quiet:
            print(f'[test-run] 复用缓存：{c["count"]} 条 / rc={c["rc"]}（{why}）',
                  file=sys.stderr)
        return c
    if not quiet:
        print(f'[test-run] 需要重跑：{why}', file=sys.stderr)
    return run_suite(quiet=quiet)


#: 负对照跑的时候**不写缓存**（2026-11-03）。
#:
#: `run_negative_controls.py` 会临时删掉一条测试来证明"㉦ 能红"。
#: 那期间跑出来的套件是 445 条 —— 如果把它写进缓存，
#: 紧跟着 ㉦ 读到的就是 445 < 下限 446 ⇒ **负对照把自己的门禁毒死了**。
#: 实测就是这么红的（1085 秒那一次的 ㉦）。
NEGCTL_ENV = 'KD_NEGCTL'


def in_negctl():
    return os.environ.get(NEGCTL_ENV) == '1'


def run_suite(quiet=False):
    started = time.time()
    p = subprocess.run([sys.executable, '-m', 'unittest', 'discover',
                        '-s', TESTS, '-v'],
                       capture_output=True, text=True, timeout=3600, cwd=ROOT)
    out = (p.stdout or '') + (p.stderr or '')
    finished = time.time()
    count, skips = parse_output(out)
    rec = {'rc': p.returncode, 'count': count, 'skips': skips,
           'started': started, 'finished': finished,
           'duration': round(finished - started, 1),
           'python': sys.executable,
           'src_hash': source_fingerprint()}
    if not in_negctl():
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, CACHE)
    else:
        print('[test-run] 负对照进行中 ⇒ 不写缓存（会把临时删掉的测试记进条数）',
              file=sys.stderr)
    if not quiet:
        sys.stdout.write(out)
    print(f'[test-run] {count} 条 / {len(skips)} 种跳过 / {rec["duration"]}s '
          f'/ rc={rec["rc"]}', file=sys.stderr)
    return rec


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--ensure', action='store_true', help='有新鲜缓存就复用，否则跑')
    ap.add_argument('--refresh', action='store_true', help='强制重跑')
    ap.add_argument('--show', action='store_true', help='只打印缓存，不跑')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv[1:])

    if a.show:
        c = read_cache()
        if not c:
            print('[test-run] 没有缓存')
            return 2
        ok, why = cache_is_fresh(c)
        print(f'[test-run] 缓存：{c["count"]} 条 / rc={c["rc"]} / '
              f'{c["duration"]}s；{why}')
        for r, n in sorted(c.get('skips', {}).items(), key=lambda x: -x[1]):
            print(f'    {n} 条  {r[:70]}')
        return 0 if ok else 2

    if a.refresh:
        rec = run_suite(quiet=a.quiet)
    elif a.ensure:
        c = read_cache()
        ok, why = cache_is_fresh(c)
        if ok:
            print(f'[test-run] 复用缓存：{c["count"]} 条 / rc={c["rc"]}（{why}）',
                  file=sys.stderr)
            rec = c
        else:
            print(f'[test-run] 需要重跑：{why}', file=sys.stderr)
            rec = run_suite(quiet=a.quiet)
    else:
        ap.error('要么 --ensure/--refresh，要么 --show')

    return 0 if rec.get('rc') == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
