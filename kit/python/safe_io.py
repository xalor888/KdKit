#!/usr/bin/env python3
"""
kuaidui-kit / safe_io.py —— "**写入必回读**"（2026-10-12 加）。

为什么需要：本会话里**三次**出现"补丁脚本打印成功、但内容没落盘" ✗
（根因各不相同：中文引号导致语法错 ✗ / 锚点不匹配 ✗ / 后续写入覆盖 ✗ —— 见 `ONBOARDING.md` 排查表 ✓）。
共同点是：**都靠"打印"判断成功** ✗。⇒ 把纪律变成机制 ✓：**写完立刻回读，并断言内容在** ✓。

用法（脚本里）：

    from safe_io import write_verified

    write_verified('work/HANDOVER.md', new_text, must_contain=['3.3d 枚举与小配置线'])
    # 不满足就抛 RuntimeError ⇒ 不会被"打印成功"骗过去 ✓

命令行用法（临时补丁也适用 ✓）：

    python3 kit/python/safe_io.py --file work/X.md --must-contain 关键词1 关键词2 --show-head 3
"""
import argparse
import os
import sys


def _norm(s):
    """归一化（2026-10-12 加 ✓）：去反引号/空白/星号/括号 + 小写 ✓。

    由来：`must_contain` 的**精确匹配**把"**反引号差异**"误判成"缺失" ✗
    —— 本会话已因此产生 **3 次假警报** ✗（R334/R345/R346 ✓）。
    ⇒ 与 `coverage_check.py` 同一套容忍规则 ✓。
    """
    import re as _re
    return _re.sub(r"[\s`*'\"（）()\[\]]", '', str(s)).lower()


def write_verified(path, text, must_contain=(), encoding='utf-8'):
    """写入并**回读**；`must_contain` 里任一关键词缺失 ⇒ 抛错（不静默）✓。

    **注意：校验失败时文件已经写下去了**（2026-11-03 补上这句说明）。
    这是有意的 —— 坏内容留在原地才看得见“到底写了什么”，
    而调用方拿到的是一场异常，不会误以为写成了。
    第一版测试断言“校验不过就不该有文件”，那是把“没写”当成了安全；
    实际上**写错了但看得见**比**静默退回旧内容**更接近我们要的。
    """
    with open(path, 'w', encoding=encoding) as f:
        f.write(text)
    back = open(path, encoding=encoding, errors='replace').read()
    _nb = _norm(back)
    missing = [k for k in must_contain if _norm(k) not in _nb]
    if missing:
        raise RuntimeError(f'write_verified: 回读失败 ✗ {path} 缺 {missing} '
                           f'（写入 {len(text)} 字符，回读 {len(back)} 字符）')
    return len(back)


def append_verified(path, text, must_contain=(), encoding='utf-8'):
    """追加并回读 ✓（文档追加的常用形态）。"""
    with open(path, 'a', encoding=encoding) as f:
        f.write(text)
    back = open(path, encoding=encoding, errors='replace').read()
    _nb = _norm(back)
    missing = [k for k in must_contain if _norm(k) not in _nb]
    if missing:
        raise RuntimeError(f'append_verified: 回读失败 ✗ {path} 缺 {missing}')
    return len(back)


def patch_at_anchor(path, anchor, replacement, must_contain=(), encoding='utf-8'):
    """**锚点先验证，再打补丁**（2026-10-12 加 ✓）。

    由来：本会话"**锚点按猜的写**" ✗ 发生多次（R324/R334 ✓），
    且给过工具（`anchors.py` ✓）之后**仍犯 2 次** ✗ ⇒ "**工具 ≠ 习惯**" ✓。
    ⇒ 把验证**塞进打补丁这一步** ✓：锚点不在 ⇒ **直接抛错** ✓，没机会写错 ✗。

        from safe_io import patch_at_anchor
        patch_at_anchor('REPORT.md', '## 1 目标画像', '## 1 目标画像（改）', ['目标画像'])
    """
    txt = open(path, encoding=encoding, errors='replace').read()
    if anchor not in txt:
        near = [ln for ln in txt.split('\n') if ln.startswith('#') and anchor.strip('# ')[:6] in ln][:5]
        raise RuntimeError(f'patch_at_anchor: 锚点不存在 ✗ {anchor[:70]!r}'
                           + (f'；相近锚点：{near}' if near else '（无相近锚点 ✓）'))
    out = txt.replace(anchor, replacement, 1)
    return write_verified(path, out, must_contain=must_contain, encoding=encoding)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--must-contain', nargs='*', default=[])
    ap.add_argument('--show-head', type=int, default=0)
    a = ap.parse_args(argv[1:])
    if not os.path.exists(a.file):
        print(f'[safe_io] ✗ 文件不存在：{a.file}')
        return 2
    txt = open(a.file, encoding='utf-8', errors='replace').read()
    _nt = _norm(txt)
    miss = [k for k in a.must_contain if _norm(k) not in _nt]
    print(f'[safe_io] {a.file}：{len(txt)} 字符；检查 {len(a.must_contain)} 个关键词 ⇒ '
          + ('全部命中 ✓' if not miss else f'缺失 {miss} ✗'))
    if a.show_head:
        for ln in txt.split('\n')[:a.show_head]:
            print('   ', ln[:110])
    return 1 if miss else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
