#!/usr/bin/env python3
"""
kuaidui-kit / verify_face.py — 水印面（C2）与 PK 面（C5）的判定工具。

> **2026-11-03 重建说明**：本文件曾被 `run_negative_controls.py` 的
> “新建文件”用例误删（我对一个**已存在**的文件用了 `old=None`，
> 于是它被覆盖成注入文本、跑完又被删掉）。重建依据是
> `kit/scripts/__pycache__/verify_face.cpython-314.pyc` 里的常量与名字
> （`FACES` 两张面的 title / reached / fired / hint 全部在里面），
> 以及 `kit/python/tests/test_verify_face.py` 的 6 条测试 ——
> **那 6 条就是本文件的行为规格**。若两者有冲突，以测试为准。

退出码契约与 `verify_membership.py` 同一套：

    0 = 已验证        1 = 矛盾（判据互相打脸）     2 = **无法验证**

### 为什么 `reached` 的判据是 `NAVACT` 而不是类名

第一版把 `reached` 写成“行内出现 `CommonWebPictureBrowseActivity`”，
于是匹配到了 `[KdKit] hooked …CommonWebPictureBrowseActivity.o2 [gate=…]` ——
那是**装钩子**的日志。56 次假“到达”把结论从“页面没到过”翻成了“到过但没生效”，
而两者对应的排查方向完全不同。

`NAVACT` 是导航面写的抓取行，只在页面真的起来之后才出现。
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import textio
from device import PKG as PKG_CONST
from sh import sh                                                   # noqa: E402

# 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）
PKG = PKG_CONST
FACES = {
    'watermark': {
        'title': 'C2 大图页水印',
        # `NAVACT` 是导航面写的抓取行，页面真的起来才有。
        # 只看 `PictureBrowse` 这个词太宽（装钩子的日志里也有）。
        'reached': re.compile(r'NAVACT\s+\S*PictureBrowse'),
        'fired': re.compile(r'WATERMARK off applied \| scope=webpic'),
        'hint': '在 App 内打开任意题目大图（H5 的 GotoPictureBrowseWebAction 入口），'
                '并确认设置页里 `web_picture_watermark` 是开的。',
    },
    'pk': {
        'title': 'C5 口算 PK',
        'reached': re.compile(r'kd-pk'),
        'fired': re.compile(r'\[KdKit\] injected into'),
        'hint': '首页 → 口算PK 进入 PK 大厅（`…/kd-pk/pk-home.html`），'
                '并确认 `pk_assist` 是开的。对局需要登录，但注入这一半不需要。',
    },
}


def pull_capture(adb):
    """当前 + 上一份轮转 —— 与 `verify_membership` 同一个理由。"""
    base = f'/data/data/{PKG}/files/kdkit_capture.txt'
    out = []
    for path in (base[:-4] + '.prev.txt', base):
        txt = sh(f'adb -s {adb} shell "cat {path} 2>/dev/null"')
        if txt.strip():
            out.append(txt)
    return ''.join(out)


def pull_logcat(adb):
    """PK 面的生效证据在 logcat 里（注入动作本身不落抓取）。"""
    return sh(f'adb -s {adb} logcat -d 2>/dev/null | '
              f'grep -aE "injected into|kd-pk|chromium.*KdKit"')


def count(rx, text):
    return len(rx.findall(text))


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--face', required=True, choices=sorted(FACES))
    ap.add_argument('--adb', default=None)
    ap.add_argument('--capture', default=None)
    ap.add_argument('--logcat-file', default=None)
    ap.add_argument('--json', action='store_true',
                    help='机器可读输出（给 face_board.py 用）')
    a = ap.parse_args(argv[1:])

    if not a.adb and not (a.capture or a.logcat_file):
        print('需要 --adb，或 --capture/--logcat-file', file=sys.stderr)
        return 2

    face = FACES[a.face]
    text = ''
    if a.capture:
        text = textio.read_text(a.capture)  # 2026-11-03：--capture 可给 .txt.gz
    if a.logcat_file:
        text += '\n' + open(a.logcat_file, encoding='utf-8', errors='replace').read()
    if a.adb:
        text += '\n' + pull_capture(a.adb)
        if a.face == 'pk':
            text += '\n' + pull_logcat(a.adb)

    reached = count(face['reached'], text)
    fired = count(face['fired'], text)

    print(f'[face] {face["title"]}：到达 {reached} 次 / 生效 {fired} 次')

    # 措辞与 `verify_membership.py` 对齐：测试按这三个词断言。
    if reached == 0:
        code, state, detail = 2, 'blocked', '目标页面从没到达过'
    elif fired == 0:
        code, state, detail = 2, 'unverified', '**未验证**：页面到过，但没有生效记录'
    else:
        code, state, detail = 0, 'verified', f'**已验证**：到达 {reached} 次、生效 {fired} 次'

    print(f'[face] 结论：{detail}')
    if code != 0:
        print(f'[face] 下一步：{face["hint"]}')

    if a.json:
        import json
        print(json.dumps({'face': a.face, 'code': code, 'state': state,
                          'detail': detail, 'reached': reached, 'fired': fired},
                         ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv))
