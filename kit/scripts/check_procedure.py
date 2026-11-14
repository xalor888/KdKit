#!/usr/bin/env python3
"""

# DOC-REALITY: PARADIGM.md「新增功能的标准动作」↔ 仓库里真实的路径/命令/域目录
kuaidui-kit / check_procedure.py — "新增功能的标准动作"里提到的每个文件/命令都必须存在。

### 为什么需要

流程文档**最容易过期，因为没有任何东西会报错**：
门禁表漂了会有 ⑱ 报，功能表漂了会有 ③ 报，而"按这 6 步做"这类文字
只在有人真的照做时才会暴露 —— 而照做的人发现第一步就找不到文件时，
通常的做法是**自己猜**，不是回来修文档。

于是流程文档的可信度会安静地腐烂，比数字漂移更危险：
数字错了顶多一个数不对，流程错了会让人按错的方式改代码。

### 它检查什么

| 判据 | 抓什么 |
|---|---|
| 反引号里的路径 | `README.md` / `FeatureRegistry.kt` / `kit/scripts/check_*.py` 等是否还在原处 |
| 反引号里的命令 | `./gw`、`python3 scripts/check_feature_parity.py` 引用的可执行/脚本是否存在 |
| 域目录列表 | 文档写的 `ads/pk/host/misc/web` 与 `features/` 下实际的目录一致 |

    python3 kit/scripts/check_procedure.py
退出码：0 = 都对得上；1 = 有找不到的路径 / 域目录不一致。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(ROOT, 'module', 'PARADIGM.md')
FEATURES = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit', 'features')

SECTION = re.compile(r'\*\*新增功能的标准动作\*\*：\n(.*?)\n\n', re.S)
BACKTICK = re.compile(r'`([^`]+)`')
#: 整串匹配域目录列表 —— 用子串匹配时，`ads/pk/host/misc/web/net` 里
#: 仍然能匹配到前 5 个，于是多加一个域也发现不了（负对照 2 当场漏过）。
DOMAINS = re.compile(r'（([a-z]+(?:/[a-z]+)+)）')

#: **正向**判断"这个反引号 token 是不是在说一个路径/文件"。
#:
#: 第一版用黑名单（排除 `object` / `FeatureRegistry.all` / `true` …），
#: 结果每加一步说明就会多几个假阳性（实测加 3 步进来 4 个误报）。
#: 黑名单追着内容跑，永远慢一步。改成正向：像路径的才查。
PATH_LIKE = re.compile(r'^[A-Za-z0-9_./-]+$')
EXT = ('.py', '.md', '.kt', '.sh', '.txt', '.json', '.xml', '.img', '.apk', '.csv', '.log')


def looks_like_path(tok):
    if not tok or any(c in tok for c in ' \t()，,'):
        return False
    if '/' in tok:
        return True
    return tok.endswith(EXT)


def candidates(tok):
    """一个反引号 token 可能是哪些真实路径。

    文档里的路径**混用了多种 cwd**：`README.md` 相对 `module/`、
    `kit/scripts/check_*.py` 相对仓库根、`scripts/check_feature_parity.py`
    在"cwd=module/"的前提下又写成相对 `module/` 的 `scripts/`。
    所以要把几种前缀组合都试一遍 —— 少试一种就会把**正确的文档**报成过期
    （第一版就是这么误报了 `./gw` 与 `scripts/check_feature_parity.py` 两条）。
    """
    base = tok.lstrip('./')
    out = [tok, base,
           os.path.join('module', base),
           os.path.join('kit', base),
           os.path.join('module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit', base)]
    # `scripts/x.py` 在 cwd=module/ 时也可能指 `module/scripts/x.py`
    if '/' in base:
        head, _, tail = base.partition('/')
        out.append(os.path.join('module', head, tail))
        out.append(os.path.join('kit', head, tail))
    return out


def main(argv):
    if not os.path.isfile(DOC):
        print('[procedure] 找不到 module/PARADIGM.md')
        return 1
    with open(DOC, encoding='utf-8') as f:
        text = f.read()
    m = SECTION.search(text)
    if not m:
        print('[procedure] **在 PARADIGM.md 里找不到「新增功能的标准动作」这一节**'
              '（标题变了？流程文档挪位了没人知道）')
        return 1
    body = m.group(1)

    bad = []
    # ① 反引号里的路径/命令
    for tok in BACKTICK.findall(body):
        if not looks_like_path(tok):
            continue
        # 形如 `./gw assembleDebug` / `python3 scripts/x.py` 的是**命令**，
        # 由下面那个循环按"命令里的脚本"处理；在这里当路径查必然假阳性。
        if tok.split()[0] in ('python3', 'python', './gw', 'bash', 'adb'):
            continue
        if not any(os.path.exists(os.path.join(ROOT, c)) for c in candidates(tok)):
            bad.append(('路径/命令不存在', tok))

    # ② 命令里的脚本（`python3 scripts/check_feature_parity.py` / `./gw`）
    for cmd in BACKTICK.findall(body):
        if not cmd.startswith(('python3', './', 'python')):
            continue
        for word in cmd.split():
            if word.endswith('.py') or word.startswith('./'):
                if not any(os.path.exists(os.path.join(ROOT, c))
                           for c in candidates(word)):
                    bad.append(('命令里的脚本不存在', f'{cmd} → {word}'))

    # ③ 域目录
    dm = DOMAINS.search(body)
    if dm:
        want = set(dm.group(1).split('/'))
        have = {d for d in os.listdir(FEATURES)
                if os.path.isdir(os.path.join(FEATURES, d)) and d != '__pycache__'} \
            if os.path.isdir(FEATURES) else set()
        if want != have:
            bad.append(('域目录不一致', f'文档 {sorted(want)} ↔ 实际 {sorted(have)}'))

    if bad:
        print(f'[procedure] **{len(bad)} 处对不上**（流程文档过期，照做的人会卡住或猜）：')
        for what, tok in bad:
            print(f'   {what}: `{tok}`')
        return 1
    print('[procedure] 「新增功能的标准动作」里提到的路径/命令/域目录都存在 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
