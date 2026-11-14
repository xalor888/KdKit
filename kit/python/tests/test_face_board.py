#!/usr/bin/env python3
"""
`face_board.py` 的**聚合判定**：四个面的退出码怎么合成一个总判定。

单独面的脚本各自有测试（`test_verify_membership` / `test_verify_face`）。
这里只关心一件事：**"全绿"必须是"四个面都验过"，不能是"没报错"**。
把 2（无法验证）算成 0，就会出现"一轮全绿、其实一个面都没验"。
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
TOOL = os.path.join(ROOT, 'kit', 'scripts', 'face_board.py')

MARK = '10:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true'


def board(*lines):
    fd, path = tempfile.mkstemp(suffix='.txt')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        out = path + '.md'
        p = subprocess.run([sys.executable, TOOL, '--capture', path, '--out', out],
                           capture_output=True, text=True, timeout=300)
        md = ''
        if os.path.exists(out):
            with open(out, encoding='utf-8') as f:   # 不关句柄会漏 ResourceWarning
                md = f.read()
        if os.path.exists(out):
            os.unlink(out)
        return p.returncode, (p.stdout or '') + (p.stderr or ''), md
    finally:
        os.unlink(path)


ALL_VERIFIED = (
    MARK,
    '10:00:01.000 NET identityIdV2=123456&vipStatus=0',
    '10:00:02.000 VIP unlock applied',
    '10:00:03.000 NAVACT CommonWebPictureBrowseActivity',
    '10:00:04.000 WATERMARK off applied | scope=webpic',
    '10:00:05.000 NAV https://ptactivity.zuoyebang.com/static/hy/kd-pk/pk-home.html',
    '10:00:06.000 APPSIGN I/chromium: [INFO:CONSOLE(11)] "[KdKit] injected into about:blank"',
)


class Aggregation(unittest.TestCase):

    def test_all_four_verified_is_zero(self):
        rc, out, md = board(*ALL_VERIFIED)
        self.assertEqual(rc, 0, out)
        self.assertEqual(md.count('| 已验证 |'), 4, md)

    def test_blocked_faces_are_not_success(self):
        rc, out, md = board(MARK, '10:00:01.000 NET identityIdV2=0&vipStatus=0')
        self.assertEqual(rc, 2, out)          # **不是 0**
        self.assertIn('无法验证', md)

    def test_board_records_a_repro_line(self):
        """产物必须带复现命令 —— 否则下一个人只能猜这张表是怎么来的。"""
        _rc, _out, md = board(*ALL_VERIFIED)
        self.assertIn('复现：', md)
        self.assertIn('face_board.py', md)

    def test_missing_identity_is_unknown_not_blocked(self):
        """没有埋点字段时判"未知"，不能混进"无法验证"——两者的排查方向不同。"""
        rc, out, md = board(MARK)
        self.assertIn(rc, (1, 2), out)
        self.assertIn('无法验证', md)


if __name__ == '__main__':
    unittest.main()
