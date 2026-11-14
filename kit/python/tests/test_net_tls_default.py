#!/usr/bin/env python3
"""
Offline tests: the TLS decision point (`kit/python/net.py`) and the seven modules that use it.

Why this file exists
--------------------
2026-11-03 代码审查 P1：**6 处无条件跳过 TLS 校验**，而 `kd_api` 是 `--insecure`
才跳 —— 同库两种默认。修法是把九处全部改成走 `net.ssl_context()`，
默认**校验**，`KD_INSECURE=1` 才跳。

那次重构动了 7 个模块、9 个调用点，而它们**此前一条测试都没有**。
"改完了、能 import"不等于"改对了" —— 今天已经在
`test_acceptance_skip_state`（没设 cwd，工具早退但断言全过）和
`check_doc_commands`（把 `.py` 换成解释器后忘了查脚本路径）上
两次抓到"检查在错误环境下仍然通过"。

这几条把重构的**契约**钉住：

* 默认是校验，不是跳过；
* `KD_INSECURE=1` 才跳过；
* `kd_api --insecure` 仍然有效（转成"或环境变量"）；
* 七个模块都真的走这个决定点，没有谁绕过它。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib
import os
import ssl
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, '..', '..')
sys.path.insert(0, os.path.join(KIT, 'python'))

#: 那次重构改动的七个模块
MODULES = ['net', 'kd_api', 'pageapi', 'probe_paths', 'composition_flow',
           'export_content', 'extract_config', 'extract_samples']


def _fresh(name):
    """每次都重新 import —— `net.insecure()` 读环境变量，缓存模块会串味。"""
    for m in list(sys.modules):
        if m == name or m.endswith('.' + name):
            del sys.modules[m]
    return importlib.import_module(name)


class DefaultIsVerify(unittest.TestCase):
    """默认值必须是**校验**，不是跳过。"""

    def tearDown(self):
        os.environ.pop('KD_INSECURE', None)

    def test_default_verifies(self):
        net = _fresh('net')
        self.assertFalse(net.insecure(), '默认必须校验 —— 否则同库两种默认又回来了')
        ctx = net.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED,
                         '默认 context 必须要求证书')
        self.assertTrue(ctx.check_hostname, '默认必须校主机名')

    def test_env_opts_out(self):
        net = _fresh('net')
        os.environ['KD_INSECURE'] = '1'
        self.assertTrue(net.insecure())
        ctx = net.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

    def test_env_values(self):
        net = _fresh('net')
        for v in ('1', 'true', 'TRUE', 'yes', 'on'):
            os.environ['KD_INSECURE'] = v
            self.assertTrue(net.insecure(), f'{v!r} 应视为"跳"')
        for v in ('0', 'false', 'no', '', 'off', 'nope'):
            os.environ['KD_INSECURE'] = v
            self.assertFalse(net.insecure(), f'{v!r} 应视为"不跳"')

    def test_describe_mentions_the_mode(self):
        net = _fresh('net')
        self.assertIn('校验', net.describe())
        os.environ['KD_INSECURE'] = '1'
        self.assertIn('跳过', net.describe())


class AllModulesUseTheSinglePoint(unittest.TestCase):
    """七个模块都走同一个决定点，没有谁绕过。"""

    def test_modules_import(self):
        for name in MODULES:
            try:
                _fresh(name)
            except Exception as e:                          # noqa: BLE001
                self.fail(f'{name} import 失败：{type(e).__name__}: {e}')

    def test_no_bypass_left(self):
        """`kit/python/` 与 `kit/scripts/` 下不许再直接造不校验的 context。

        用 AST 而不是文本匹配：`('_t_', …)` 那类字符串字面量正是要找的目标，
        "去掉字符串"会把目标一起去掉（2026-11-03 在 ㉘ 上就这么失效过一次）。
        """
        import ast
        import glob
        # `net.py` 自己是唯一允许造它的地方；`is_fixture` 排除负对照样本。
        # 路径按 `KIT` 相对算，所以前缀是 `python/` 而不是 `kit/python/`。
        allowed = {'python/net.py'}
        sys.path.insert(0, os.path.join(KIT, 'python'))
        from negctl_fixtures import is_fixture
        bad = []
        for pat in (os.path.join(KIT, 'python', '*.py'),
                    os.path.join(KIT, 'scripts', '*.py')):
            for p in glob.glob(pat):
                rel = os.path.relpath(p, KIT)
                if rel in allowed or is_fixture(p):
                    continue
                try:
                    with open(p, encoding="utf-8", errors="replace") as _fh:
                        tree = ast.parse(_fh.read())
                except (SyntaxError, ValueError):
                    continue
                for n in ast.walk(tree):
                    if (isinstance(n, ast.Attribute)
                            and n.attr == '_create_unverified_context'):
                        bad.append(f'{rel}:{n.lineno}')
        self.assertEqual(bad, [], f'这些地方绕过了统一决定点：{bad}')

    def test_kd_api_still_accepts_insecure_flag(self):
        """`--insecure` 是给命令行的，重构后**不许消失**。"""
        import subprocess
        p = subprocess.run([sys.executable, os.path.join(KIT, 'python', 'kd_api.py'),
                            '--help'], capture_output=True, text=True, timeout=120)
        self.assertIn('--insecure', (p.stdout or '') + (p.stderr or ''),
                      'kd_api 丢了 --insecure ⇒ 原来靠它的人全断')


if __name__ == '__main__':
    unittest.main()
