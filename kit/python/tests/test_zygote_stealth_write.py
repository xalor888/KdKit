#!/usr/bin/env python3
"""
`10_zygote_stealth.js` 的写回语义 —— 不许用 `writeUtf8String`。

Why this file exists
--------------------
2026-11-03 代码审查 P1：

> `10_zygote_stealth.js:63` `writeUtf8String` 额外写 `\0`，
> 把 `/proc/self/status` 原文的 `\n` 覆盖成 NUL ⇒ 伪造 TracerPid 的效果不可靠。

Frida 的 `writeUtf8String(s)` 写的是 `s` **再加一个 NUL 终止符**。
于是 `i + clean.length` 那一字节 —— 原本是这一行结尾的 `\n` —— 被 NUL 覆盖：

    TracerPid:\t0000\0Uid:\t…            ← 旧
    TracerPid:\t0000\nUid:\t…            ← 新

应用按 `\n` 切行时会把这两行并成一行。有些解析器无所谓，
有些连 `Uid` 都读不出来 —— 于是"TracerPid 伪造成功"变得**不可靠**，
而现象是偶发退出，与"没伪装住"一模一样。

这条测试用 node 把两种写法的**结果字节**都比出来，
再断言脚本里用的是逐字节那一种。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCRIPT = os.path.join(ROOT, 'kit', 'hooks', '10_zygote_stealth.js')

NODE = shutil.which('node')

#: 两种写法的结果（node 侧算，Python 侧只做断言）
PROBE = r"""
var line = 'TracerPid:\t1234';
var clean = line.replace(/[0-9]/g, '0');
var orig = Buffer.from('TracerPid:\t1234\nUid:\t0\n', 'latin1');
var i = 0;

// 旧：writeUtf8String(s) == s + NUL
var b1 = Buffer.from(orig);
for (var k = 0; k < clean.length; k++) b1[i + k] = clean.charCodeAt(k);
b1[i + clean.length] = 0;

// 新：writeByteArray(bytes) == 正好这些字节
var b2 = Buffer.from(orig);
var bytes = [];
for (var k = 0; k < clean.length; k++) bytes.push(clean.charCodeAt(k) & 0xFF);
for (var k = 0; k < bytes.length; k++) b2[i + k] = bytes[k];

console.log(JSON.stringify({
  old: b1.toString('latin1'), neu: b2.toString('latin1')
}));
"""


@unittest.skipUnless(NODE, '没有 node —— 这条测的是 JS 写回语义')
class WriteBackSemantics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        p = subprocess.run([NODE, '-e', PROBE], capture_output=True, text=True, timeout=60)
        cls.out = p.stdout.strip()

    def test_old_formula_eats_the_newline(self):
        """旧写法确实把 `\n` 吃成了 NUL —— 钉住"那个 bug 是真的"。

        node 输出的是 JSON：`\t` 与 `\n` 在文本里是**两个字符**
        （反斜杠 + 字母），不是真正的制表符/换行。所以断言用 raw string。
        """
        self.assertIn(r'\u0000Uid', self.out)


    def test_script_uses_byte_write(self):
        """脚本里必须用 `writeByteArray`，不能再出现 `writeUtf8String` 调用。

        **只在代码行里判**：注释里为了说明问题会提到 `writeUtf8String`，
        那不算（今天已经为"注释里的坏味道被当成缺陷"修过 4 个检查器）。
        """
        with open(SCRIPT, encoding='utf-8') as _f:
            src = _f.read()
        code = '\n'.join(l for l in src.split('\n')
                         if not l.strip().startswith('//') and not l.strip().startswith('*'))
        self.assertIn('writeByteArray', code)
        self.assertNotIn('.writeUtf8String(', code,
                         '又回到 writeUtf8String ⇒ /proc/self/status 的换行会被 NUL 吃掉')


if __name__ == '__main__':
    unittest.main()
