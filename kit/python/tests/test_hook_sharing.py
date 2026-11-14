#!/usr/bin/env python3
"""
Tests for `kit/scripts/check_hook_sharing.py` — the ⑧ gate.

## 为什么这道门值得一份测试

钩点冲突**不会让任何别的门变红**：不崩溃、不打日志、钩子数照常。
唯一症状是"某个功能安静地少收数据"，要等有人拿抓取对照才发现。

所以这份测试守的不是工具本身，而是**"工具还会不会发现新冲突"**这个能力。

Run: python3 -m unittest discover -s kit/python/tests -v
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'scripts'))

import check_hook_sharing as chs  # noqa: E402


class RecognisesSharing(unittest.TestCase):

    # 类级缓存：`shared_targets()` 会跑一遍 `check_hook_targets.py`（约 8 秒）。
    # 放 `setUp` 里会按方法重复 —— 上一轮刚在 test_vip_call_sites 上踩过同一个坑
    # （门禁从 35s 涨到 146s 的一半原因就是它）。
    shared: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.shared = chs.shared_targets()

    def test_finds_the_known_pair(self):
        """`BridgeGuard` 与 `H5BridgeLog` 都钩 `HybridWebView.dispatchAction*`。

        这是当前唯一的跨文件共享。若它消失，说明有人改了钩法 —— 那也需要知道
        （要么是好事，要么是 `check_hook_targets` 的解析坏了）。
        """
        names = {t.split('.')[-1] for t in self.shared}
        self.assertIn('dispatchAction', names)
        self.assertIn('dispatchActionToListeners', names)

    def test_same_file_duplicates_are_excluded(self):
        """同文件内的重复不算跨功能共享。

        `AdFeatures.kt` 里两个 object 也钩了同样的 `aj.a.d/f/h` ——
        那是同一个作者在同一处写的一段逻辑，不该要求登记。
        """
        for target in self.shared:
            files = {f for f, _ in self.shared[target]}
            self.assertGreater(len(files), 1,
                               f'{target} 只出现在 {files}，不该被算作跨文件共享')


class RegistrationIsHonoured(unittest.TestCase):

    def test_current_repo_is_fully_registered(self):
        """真仓库当前不该有未登记共享（⑧ 门的实际断言）。"""
        shared = chs.shared_targets()
        known = chs.registered_targets()
        self.assertTrue(known, 'PARADIGM.md 的「钩点共享」节没解析出任何登记项')
        missing = [
            t for t in shared
            if not any(t == k or t.endswith('.' + k) for k in known)
        ]
        self.assertEqual(missing, [],
                         f'这些共享钩点没在 PARADIGM.md §10 登记：{missing}')

    def test_short_names_are_accepted(self):
        """登记写短名（`HybridWebView.x`）就该被认，不必写全限定名。

        工具第一版要求全等，于是文档里写了短名却报"未登记" ——
        那会让人去重复登记，而不是怀疑工具。
        """
        known = chs.registered_targets()
        full = 'com.baidu.homework.common.ui.widget.HybridWebView.dispatchAction'
        self.assertTrue(
            any(full == k or full.endswith('.' + k) for k in known),
            '短名登记没被认出来',
        )


if __name__ == '__main__':
    unittest.main()
