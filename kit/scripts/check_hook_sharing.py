#!/usr/bin/env python3
"""

# DOC-REALITY: 多功能钩同一方法 ↔ PARADIGM.md §10 共享表
# （这一行是给 `check_doc_reality.py` 扫的登记标记 —— 新增"文档 ↔ 代码"断言时
#  必须加这一行，否则清单会漏掉它，R40 门禁表漂 8 道那类事就会重演。）
kuaidui-kit / check_hook_sharing.py — 谁和谁钩了同一个方法？

## 为什么需要这道检查

模块里 34 个功能各自装钩子。当**两个功能钩住同一个方法**时，会出现一类
肉眼看不见的问题：

* 一个功能的 `onBefore` 里写了 `param.result = …`（短路），另一个功能可能
  再也读不到这次调用 —— 取决于 Xposed 的回调顺序与是否继续分发；
* 上报的"钩子数"会重复计数（同一个方法算两次），让"装了 N 个钩子"这个数字失去意义。

这类问题**不会让门禁变红、不会崩溃、不会打日志**。它只是让某个功能安静地少收数据。

2026-10-26 实测：`HybridWebView.dispatchAction` 被 `BridgeGuard` 与 `H5BridgeLog`
同时钩住，前者在拦截时会 `param.result = null`。两者都用 `hookAllBefore`，
所以目前"都还能读到 args"，但这个结论**没有任何地方记录过**，也没有测试守住。

## 它检查什么

只做一件事：列出被**多个不同源文件**指向的同一钩点，并要求它们在
`module/PARADIGM.md` 的共享表里登记。

同一文件内的重复（例如 `AdFeatures.kt` 里两个 object 钩 `aj.a.*`）不算跨功能，
不要求登记 —— 那是同一个作者在同一处写的一段逻辑。

## 用法

```bash
python3 kit/scripts/check_hook_sharing.py            # 人读
python3 kit/scripts/check_hook_sharing.py --strict   # 有未登记共享就 exit 1
```
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

sys.path.insert(0, HERE)
import hook_vocab as vocab  # noqa: E402

# 与 check_hook_targets.py 同一个解析器 —— 不重复实现，避免两处口径漂移。
# **字符类里必须有 `)`**（2026-11-02 修）。
#:
#: 旧写法 `[\w(~-]+` 漏了右括号，于是状态列 `OK(platform)` / `OK(load)` / `USED(self)`
#: **整行匹配失败** —— 实测 126 个目标里 51 个看不见（全部是 platform/load 两类）。
#: 后果不是"少报几条"：门禁 ⑧ 从建成起就只看到 75/126 个钩点，
#: 于是 `android.webkit.WebView.loadUrl`（NavLog 与 WebInjector 都钩它）
#: 这种真实共享**从来没进过共享表**。
#:
#: 这是"判据的范围比它以为的窄"的又一例（今天早些时候 ⑱ 的 Unicode 区间也是这类）。
_TARGET_RE = re.compile(r'\s+[\w()~-]+\s+([\w.$]+)\s+\(([^:)]+):(\d+)\)')


# 进程内缓存：`check_hook_targets.py` 一次约 8 秒。测试里多个 TestCase 都会问
# 同一个问题，不缓存就按"问的次数"重复付费。
# 只缓存成功结果 —— 失败时返回空会让"工具坏了"看起来像"没有共享"。
_SHARED_CACHE: dict = {}


def shared_targets(targets_json=None):
    """`{target: [(file, line), …]}` —— 只保留 ≥2 个**不同文件**的。

    `targets_json`：**同一轮里**门禁 ④ 已经写出的 `check_hook_targets.py --json` 报告。
    给了就直接读，不再起子进程重扫。

    为什么值得省：`check_hook_targets.py` 一次约 19 秒（扫 61338 个类的 smali）。
    它原本在一轮 `verify.sh` 里被跑**两次** —— ④ 一次，本工具作为子进程再一次。
    19 秒的重复扫描不改变任何结论，只是让每轮门禁多等 19 秒。

    **只接受同一轮的产物**：调用方传的是本轮 ④ 刚写的临时文件，
    所以不存在"缓存过期导致假通过"的问题 —— 这一点与 `--cache` 类的跨轮缓存有本质区别。
    """
    if 'v' in _SHARED_CACHE:
        return _SHARED_CACHE['v']
    if targets_json:
        try:
            with open(targets_json, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            print(f'[sharing] ⚠ 读不到 {targets_json}（{e}）⇒ 退回自行扫描')
        else:
            by = defaultdict(list)
            for r in data.get('rows', []):
                # `where` 的形态是 `features/host/VipUnlock.kt:82` —— **必须只取文件部分**。
                #
                # 第一版把整串塞进"文件"槽，于是同一个类在**同一个文件**里的两行
                # （`VipUnlock.kt:82` 与 `:88`）被算成两个不同文件 ⇒ 27 处假"跨文件共享"，
                # 而正确结论是 2 处。门禁红在"复用路径的解析"上，而不是代码上 ——
                # 这类错误比漏报更贵：它会让 ⑧ 长期处于红的状态，直到有人学会忽略它。
                where = (r.get('where', '') or '').split(':')[0]
                # 键必须是 **class.method**，不能只用 class。
                #
                # `android.app.Activity` 被 NavLog 钩 `onCreate`、被 SkipOnboarding 钩
                # `onResume` —— 两个不同的钩点，只是碰巧在同一个类上。
                # 第一版（只按 class 聚合）把它算成"跨文件共享"，而正确结论是不算。
                # 文本路径的 `_TARGET_RE` 抓的正是 `class.method`，两条路径必须一致。
                usage = r.get('usage') if isinstance(r.get('usage'), dict) else {}
                if usage.get('verdict') == 'TYPE-ONLY':
                    continue
                meth = r.get('method') or ''
                key = r['class'] + ('.' + meth if meth else '')
                by[key].append((where, ''))
            result = {k: v for k, v in by.items() if len({f for f, _ in v}) > 1}
            if 'v' not in _SHARED_CACHE:
                _SHARED_CACHE['v'] = result
            print(f'[sharing] 复用门禁 ④ 的报告：{targets_json}'
                  f'（省掉一次 ~19s 的 smali 扫描）')
            return result
    out = subprocess.run([sys.executable, os.path.join(HERE, 'check_hook_targets.py')],
                         capture_output=True, text=True, cwd=ROOT, timeout=600).stdout
    by = defaultdict(list)
    for line in out.splitlines():
        m = _TARGET_RE.match(line)
        if not m:
            continue
        # **TYPE-ONLY 不是钩点**：它只是"把这个类当类型用"（字段/参数/new）。
        # `HybridWebView$ReturnCallback` 在三个文件里都以类型出现，但它**不是**被钩的方法 ——
        # 真正被钩的是 `$ReturnCallback.call`，而那个只被 H5BridgeLog 一个文件钩。
        # 不排除 TYPE-ONLY 就会报出一堆"共享"，而共享表要回答的是
        # "两个功能钩同一个方法时会互相影响吗"——类型引用不影响。
        if '[TYPE-ONLY]' in line:
            continue
        by[m.group(1)].append((m.group(2).strip(), m.group(3)))
    result = {k: v for k, v in by.items() if len({f for f, _ in v}) > 1}
    if out:                       # 只在解析真的产出内容时缓存
        _SHARED_CACHE['v'] = result
    return result


def registered_participants():
    """从共享表里读出 **每个钩点登记了哪些参与者**（按文件名）。

    为什么需要它（2026-11-02）：原来的判据只看"这个**方法名**在 §10 出现过"。
    于是给 `dispatchAction` **再加第三个**参与者时，门禁依然是 `[OK]` ——
    它只能回答"这个点被登记过"，不能回答"**现在参与的人**都被登记过"。
    而风险恰恰取决于具体组合：谁在 before、谁会短路、短路后别人还能不能读到。

    表格形如：

        | `HybridWebView.dispatchAction` | `BridgeGuard`（`BridgeGuard.kt:69`） | `H5BridgeLog`（`H5BridgeLog.kt:39`） |

    ⇒ `{'HybridWebView.dispatchAction': {'BridgeGuard.kt', 'H5BridgeLog.kt'}}`
    """
    doc = os.path.join(ROOT, 'module', 'PARADIGM.md')
    if not os.path.isfile(doc):
        return {}
    import re as _re
    text = vocab.read_text(doc)
    m = _re.search(r'^##+\s*\d*\.?\s*钩点共享', text, _re.M)
    if not m:
        return {}
    i = m.start()
    j = text.find('\n## ', i + 1)
    section = text[i:j if j > 0 else len(text)]
    out = {}
    for row in section.splitlines():
        if not row.strip().startswith('|'):
            continue
        cells = [c.strip() for c in row.strip().strip('|').split('|')]
        if len(cells) < 2:
            continue
        head = _re.search(r'`([\w.$]+)`', cells[0])
        if not head:
            continue
        files = set(_re.findall(r'`([\w.]+\.[a-z]{2,3}):\d+`', row))
        if files:
            out[head.group(1)] = files
    return out


def doc_shared_targets():
    """`PARADIGM.md` §10 表格里登记的钩点（取反引号包着的第一列）。

    为什么需要**反方向**：主判据只遍历"代码里现在共享的钩点"，于是
    某一天两个功能不再钩同一个方法时，表格里那一行**永远留着** ——
    读者会以为还存在一处需要留意相互作用的共享，而代码里已经没有这回事。
    """
    doc = os.path.join(ROOT, 'module', 'PARADIGM.md')
    if not os.path.isfile(doc):
        return set()
    import re as _re
    text = vocab.read_text(doc)
    m = _re.search(r'^##+\s*\d*\.?\s*钩点共享', text, _re.M)
    if not m:
        return set()
    i = m.start()
    j = text.find('\n## ', i + 1)
    section = text[i:j if j > 0 else len(text)]
    out = set()
    for line in section.splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 3:            # 表头/分隔行没有三列
            continue
        g = _re.search(r'`([\w.$]+)`', cells[0])
        if g:
            out.add(g.group(1))
    return out


def registered_targets():
    """`PARADIGM.md` 共享表里登记过的钩点（按方法名匹配，够用且不脆弱）。"""
    doc = os.path.join(ROOT, 'module', 'PARADIGM.md')
    if not os.path.isfile(doc):
        return set()
    # 用 `hook_vocab.read_text`（唯一读文件入口）。裸 `open().read()` 会留下
    # 未关闭的句柄：在 `-q` 的 unittest 里它变成一条 ResourceWarning，
    # 混在门禁输出里；句柄多时还会撞 `Too many open files`。
    # 第 17 轮已经在别处清过一次同类泄漏（49931 条警告把真失败埋了），这里是第二处。
    text = vocab.read_text(doc)
    # 只认 `## 钩点共享` 这一节
    # 按**关键字**定位，不要求标题精确等于 `## 钩点共享` ——
    # 章节编号会变（实际是 `## 10. 钩点共享`），写死标题会让登记全部失效，
    # 而失效的表现是"工具说没登记"，人会去重复登记而不是怀疑工具。
    import re as _re
    m = _re.search(r'^##+\s*\d*\.?\s*钩点共享', text, _re.M)
    if not m:
        return set()
    i = m.start()
    j = text.find('\n## ', i + 1)
    section = text[i:j if j > 0 else len(text)]
    return set(re.findall(r'`([\w.$]+)`', section))


def main(argv):
    ap = argparse.ArgumentParser(description='列出被多个功能共享的钩点')
    ap.add_argument('--targets-json', default=None,
                    help='复用门禁 ④ 刚写出的 check_hook_targets.py --json 报告'
                         '（同一轮内有效；不给就自行扫描，约 19s）')
    ap.add_argument('--strict', action='store_true',
                    help='有未登记的跨文件共享就 exit 1')
    a = ap.parse_args(argv[1:])

    shared = shared_targets(a.targets_json)
    if not shared:
        print('[sharing] 没有被多个文件共享的钩点')
        return 0

    known = registered_targets()
    parts = registered_participants()
    missing = []
    print('[sharing] 跨文件共享的钩点：')
    for target, hits in sorted(shared.items()):
        # 登记时写短名（`HybridWebView.dispatchAction`）比写全限定名更好读，
        # 所以这里按**后缀**匹配：任一登记项是 target 的结尾即算已登记。
        key = next((k for k in known if target == k or target.endswith('.' + k)), None)

        # **参与者也要登记**：方法名登记过 ≠ 现在这些人登记过。
        who = sorted({os.path.basename(f) for f, _ in hits})
        reg = set()
        for k, v in parts.items():
            if target == k or target.endswith('.' + k):
                reg |= v
        # **"表里有这一行但没登任何人"必须算未登记**（2026-11-02 修）。
        #
        # 旧写法 `if (key and reg)`：`reg` 为空时 `extra` 直接被算成 `[]`，
        # 于是"行在、参与者被删空"与"行在且参与者齐全"长得一模一样 —— 门禁照样 `[OK]`。
        # 这个洞是负对照总检抓到的：把 `H5BridgeLog`（`:41`）从表格里删掉，⑧ 仍然绿。
        extra = [w for w in who if w not in reg] if key else []
        mark = 'OK' if key and not extra else ('**未登记**' if not key else '**参与者未登记**')
        print(f'  [{mark}] {target}')
        if extra:
            if True:
                print(f'      代码里的参与者：{", ".join(who)}')
                _reg_s = ", ".join(sorted(reg)) or "（未解析出）"
                print(f'      §10 登记的：    {_reg_s}')
                print(f'      多出来的：      {", ".join(extra)}')
                missing.append(f'{target}（多出参与者 {", ".join(extra)}）')
        for f, ln in hits:
            print(f'      {f}:{ln}')
        if mark != 'OK' and not any(m.startswith(target) for m in missing):
            missing.append(target)

    if missing:
        print()
        print(f'[sharing] {len(missing)} 处未在 `module/PARADIGM.md` 的「钩点共享」节登记：')
        for t in missing:
            print(f'  - {t}')
        print('  （"参与者未登记"= 这个钩点上出现了 §10 没写到的源文件；'
              '它的 before/after、会不会短路，都没人记录过。）')
        print('  登记时要写清：两者各用 before 还是 after、谁可能短路、')
        print('  短路后另一个功能还能不能读到这次调用。')
        return 1 if a.strict else 0

    # **反方向**：表里登记的钩点，代码里必须仍然真的共享（≥2 个不同文件）。
    # 只有正向判据时，"不再共享"会在文档里留下一个永不消失的行。
    stale = []
    for target in sorted(doc_shared_targets()):
        if not any(t == target or t.endswith('.' + target) for t in shared):
            stale.append(target)
    if stale:
        print(f'\n[sharing] **{len(stale)} 处登记了但代码里已不共享**（表在描述过去的事实）：')
        for t in stale:
            print(f'  - {t}')
        print('  删掉那一行，或注明"历史上曾共享，现已不共享"并说明原因。')
        return 1 if a.strict else 0

    print(f'\n[sharing] 全部 {len(shared)} 处均已在 PARADIGM.md 登记')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
