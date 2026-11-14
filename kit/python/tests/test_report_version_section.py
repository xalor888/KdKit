#!/usr/bin/env python3
"""
报告的 **§0 宿主版本** 段（2026-11-02，D4）。

为什么这一段值得单独立测试
--------------------------
整套钩子建立在某一版 App 的**混淆名**上（`dj.a` / `di.a` / `vm.g` …）。App 一自动更新，
这些名字会挪位，症状是"功能静默失效"而不是崩溃 —— 本模块最坏的故障形态。

而抓取里其实**一直有**这行证据：

    === KdKit host=7.9.0/1840 sdk=36 baseline=true

只是从来没有报告读它（`session_report.py` 里 grep 不到 `host=`），于是
"这轮结论属于哪个版本"这个问题在报告里无法回答。

三条分支必须都被钉住，因为它们的**后果不同**：

| 抓取里有什么 | 报告必须说 |
|---|---|
| `baseline=true` | 哪个版本、一致 ✓ |
| `baseline=false` | 🚨 版本漂移，且**指出下一步跑什么命令** |
| 没有这行 | ⚠ 无法确认版本（旧构建 / 模块没跑过） |

第三条最容易被写成"沉默"：什么都不说，读者就会把"没有记录"当成"功能没触发"。
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_PY = os.path.dirname(HERE)
if KIT_PY not in sys.path:
    sys.path.insert(0, KIT_PY)

REPORT = os.path.join(KIT_PY, 'session_report.py')


CAP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "fixtures", "all_prefixes.txt")


def run_report(lines):
    fd, path = tempfile.mkstemp(suffix='.txt')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        p = subprocess.run([sys.executable, REPORT, path], capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    finally:
        os.unlink(path)


def section0(out):
    """取出 §0 的正文（到下一个 `## ` 之前）。"""
    if '## 0. 宿主版本' not in out:
        return ''
    return out.split('## 0. 宿主版本', 1)[1].split('\n## ', 1)[0]


class VersionSection(unittest.TestCase):

    def test_baseline_ok(self):
        rc, out = run_report([
            '09:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
            '09:00:01.000 SIGN URL: https://a.example/p?a=1&sign=x',
        ])
        self.assertEqual(rc, 0, out[-600:])
        seg = section0(out)
        self.assertIn('7.9.0 (1840)', seg)
        self.assertIn('一致', seg)
        self.assertNotIn('版本漂移', seg)

    def test_drift_is_loud_and_actionable(self):
        rc, out = run_report([
            '09:00:00.000 === KdKit host=7.9.1/1850 sdk=36 baseline=false',
            '09:00:01.000 SIGN URL: https://a.example/p?a=1&sign=x',
        ])
        self.assertEqual(rc, 0, out[-600:])
        seg = section0(out)
        self.assertIn('7.9.1 (1850)', seg)
        self.assertIn('版本漂移', seg)
        # 光喊不够：必须告诉读者下一步怎么办，否则这条警告没有行动价值
        self.assertIn('check_hook_targets', seg)

    def test_missing_mark_is_a_warning_not_silence(self):
        rc, out = run_report([
            '09:00:01.000 SIGN URL: https://a.example/p?a=1&sign=x',
        ])
        self.assertEqual(rc, 0, out[-600:])
        seg = section0(out)
        self.assertIn('没有宿主版本行', seg)
        self.assertIn('无法确认', seg)

    def test_last_mark_wins_when_process_restarted(self):
        """一次抓取里可能有多个进程的记录（轮转 + 重启）；应看**最后**一次。"""
        rc, out = run_report([
            '09:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
            '09:05:00.000 === KdKit host=7.9.1/1850 sdk=36 baseline=false',
        ])
        self.assertEqual(rc, 0, out[-600:])
        seg = section0(out)
        self.assertIn('7.9.1 (1850)', seg)
        self.assertIn('版本漂移', seg)

    # ── 2026-11-02 补：跨版本的抓取不能"只看最后一条" ─────────────────────
    #
    # 旧实现只读 `_host_marks[-1]`。抓取跨了一次 App 升级时，报告会按**最后一个**
    # 版本下结论（"与基线一致 ✓"），而前面半份数据来自另一个版本 ——
    # "某功能没有记录"到底是"没触发"还是"钩子没挂上"，判据被悄悄换掉了。
    # 实测：设备上 35 605 行抓取里目前只有 7.9.0 一种，所以这条平时不会触发；
    # 但**下次 App 升级**就会，而那时正是最需要看清版本的时刻。

    def test_mixed_versions_are_called_out(self):
        rc, out = run_report([
            '09:00:00.000 === KdKit host=7.7.2/1811 sdk=36 baseline=false',
            '09:05:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
            '09:06:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
        ])
        self.assertEqual(rc, 0, out[-600:])
        seg = section0(out)
        self.assertIn('跨了 2 个宿主版本', seg)
        self.assertIn('7.7.2 (1811)', seg)      # 旧版本必须**出现在正文里**，不能只留最后一条
        self.assertIn('7.9.0 (1840)', seg)

    def test_single_version_has_no_mixed_warning(self):
        """单一版本不能顺手报"跨版本" —— 误报会让这条警告失去意义。"""
        rc, out = run_report([
            '09:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
            '09:05:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
        ])
        self.assertEqual(rc, 0, out[-600:])
        self.assertNotIn('跨了', section0(out))

    def test_section0_comes_before_the_rest(self):
        """§0 必须排在所有依赖它的结论之前 —— 它是"下面这些能不能信"的前提。"""
        rc, out = run_report([
            '09:00:00.000 === KdKit host=7.9.0/1840 sdk=36 baseline=true',
        ])
        self.assertEqual(rc, 0, out[-600:])
        self.assertLess(out.index('## 0. 宿主版本'), out.index('## 1. 接口面'))




class FaceBoardSection(unittest.TestCase):
    """§9：四张验收面的最近状态（来自 `after_login.sh` 的留档）。

    为什么单独测：报告读完仍不知道"这个仓库到底验过什么"，是最常见的
    "看起来有结论、其实没有" 的形态。§9 把这件事变成一句带时间戳的陈述，
    并且**超过 3 天必须告警** —— 一份 3 天前的"已验证"不能当今天的结论
    （宿主升一次级就可能全变）。
    """

    def _run(self, log_text):
        fd, lg = tempfile.mkstemp(suffix='.md')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(log_text)
        try:
            p = subprocess.run([sys.executable, REPORT, CAP, '--login-log', lg],
                               capture_output=True, text=True, timeout=300)
            return p.returncode, (p.stdout or '') + (p.stderr or '')
        finally:
            os.unlink(lg)

    LOG_OK = ('## 2026-11-02 15:11:33  serial=emulator-5558 宿主=7.9.0 rc=2\n\n```\n'
              '| C1 广告面 | 无法验证 | 游客态 |\n'
              '| C3 会员面 | 无法验证 | 游客态 identityIdV2=0 |\n```\n')

    def test_missing_log_is_a_warning_not_silence(self):
        p = subprocess.run([sys.executable, REPORT, CAP, '--login-log',
                            '/tmp/definitely-not-here-xyz.md'], capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, (p.stdout or '') + (p.stderr or ''))
        self.assertIn('没有留档', (p.stdout or '') + (p.stderr or ''))

    def test_present_log_is_reported_with_verdict(self):
        _rc, out = self._run(self.LOG_OK)
        self.assertIn('15:11:33', out)
        self.assertIn('无法验证', out)

    def test_stale_log_is_flagged(self):
        """过期留档必须被点名。**时间基准要经得起一天里的任何时刻**。

        旧实现用 `today - 5 天` + `09:00:00`，断言报告写 `5 天`。
        报告用的是 `timedelta.days`（**向下取整**），于是这句话只在当天
        09:00 之后成立 —— 2026-11-03 00:14 它真的红了（差 4 天 15 小时 ⇒ 4）。

        改成 `today - 5 天` + `00:00:00`：那个时刻到现在恒落在 [5, 6) 天，
        无论一天中的什么时候跑，取整结果都是 `5 天`。
        **一条只在某些时刻成立的断言，等于一条会自己坏的断言。**
        """
        import datetime
        old = (datetime.date.today() - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        _rc, out = self._run(f'## {old} 00:00:00  serial=s 宿主=7.9.0 rc=0\n\n```\n'
                             '| C1 广告面 | 已验证 | x |\n```\n')
        self.assertIn('这次留档已经', out)
        self.assertIn('5 天', out)

    def test_rc0_is_reported_as_all_verified(self):
        import datetime
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _rc, out = self._run(f'## {now}  serial=s 宿主=7.9.0 rc=0\n\n```\n'
                             '| C1 广告面 | 已验证 | x |\n```\n')
        self.assertIn('全部已验证', out)
        self.assertNotIn('这次留档已经', out)


if __name__ == '__main__':
    unittest.main()
