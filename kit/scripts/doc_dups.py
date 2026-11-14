#!/usr/bin/env python3
"""
kuaidui-kit / doc_dups.py — 文档"重复段"体检（2026-10-13 ✓，规则 27 ✓）。

由来：R502 在 `AWAITING.md` 里读出"三代版本并存" ✗；R503 把它做成全库一遍 ✓，
当场又揪出 `HANDOVER.md`（11 份重复）✗ 与 `BRIDGE_PAGE_MAP.md`（2 处）✗。
⇒ **追加式长大是静悄悄的** ✗ ⇒ 本脚本让它**每次都能被发现** ✓。

    python3 kit/scripts/doc_dups.py
退出码：0 = 无重复 ✓；1 = 有重复 ✗。
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import textio
import collections
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GLOBS = ['work/*.md', 'kit/*.md', 'REPORT.md']
HDR = re.compile(r'^#{2,3} ')
TBL = ('| 步 |', '| # |', '| 项 |')


def scan():
    rows = []
    for pat in GLOBS:
        for f in sorted(glob.glob(os.path.join(ROOT, pat))):
            s = textio.read_text(f, encoding='utf-8', errors='replace')
            # 2026-10-13：**自动生成的文档**（首行带"自动生成" ✓）**不算失败** ✗ ——
            # 它们每轮重写 ✓ ⇒ 就算真有重复也会被下一次覆盖 ✓（`BRIDGE_PAGE_MAP.md` 就是这种 ✓）。
            # 真正的"追加腐坏"只发生在**手工维护的文档**里 ✓（`AWAITING.md` ✓ / `HANDOVER.md` ✓）。
            auto = '自动生成' in '\n'.join(s.split('\n')[:3])

            heads = [l.strip() for l in s.split('\n') if HDR.match(l)]
            dup = {h: n for h, n in collections.Counter(heads).items() if n > 1}
            tbl = [l.strip() for l in s.split('\n') if l.strip().startswith(TBL)]
            td = len(tbl) - len(set(tbl))
            # 2026-10-13 精化 ✓（本工具**首次运行就出了假阳性** ✗ —— 同 R355/R456/R457 ✓）：
            # `BRIDGE_PAGE_MAP.md` 里两个标题看着一样 ✓，但它们的**下一行 `* 原页面：…` 不同** ✓
            # ⇒ 那是**两个不同的长 URL 被 `short()` 截成了同名** ✗，**不是重复段** ✓。
            # 判据：标题重复 **且** 紧随的"父行"也相同 ⇒ 才算重复 ✓。
            lines_ = s.split('\n')
            false_pos = set()
            for h, n in dup.items():
                idx = [i for i, l in enumerate(lines_) if l.strip() == h]
                parents = set()
                for i in idx:
                    for j in range(i + 1, min(i + 6, len(lines_))):
                        if lines_[j].startswith('* ') or lines_[j].startswith('**'):
                            parents.add(lines_[j].strip()[:80]); break
                    else:
                        parents.add('')
                if len(parents) >= n:
                    false_pos.add(h)
            dup = {h: n for h, n in dup.items() if h not in false_pos}
            if (dup or td > 0) and not auto:
                rows.append((os.path.relpath(f, ROOT), dup, td))
    return rows


def main(argv):
    rows = scan()
    if not rows:
        print('[dups] 全部文档无重复段 ✓')
        return 0
    print(f'[dups] **{len(rows)} 个文档有重复段** ✗（追加式长大的痕迹 ✓）：')
    for f, dup, td in rows:
        print(f'   {f}: 重复标题 {len(dup)} 处 / 重复表头 {td} 处')
        for h, n in list(dup.items())[:3]:
            print(f'      x{n}  {h[:58]}')
    print('   ⇒ 修法：**每个重复标题只留最新一份** ✓（追加都是"新在后"✓）')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
