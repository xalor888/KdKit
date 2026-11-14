#!/usr/bin/env python3
"""
`skip_onboarding` 的重试链**不能挂在 View 上**（2026-11-02，P2-8）。

缺陷回顾
--------
```kotlin
if (tries[0]++ < 6) v?.postDelayed(this, 700)      // v 为 null ⇒ 什么都不做
root()?.postDelayed(run, 500) ?: run.run()
```

`onResume` 那一刻 `window.decorView` 常常还没挂上。这时 `v` 是 null：

* 重试链挂在 `v` 上 ⇒ **没人再排下一次**；
* 初次调度走 `?: run.run()` ⇒ 立刻跑一次、立刻结束。

于是"只要第一次拿不到 decorView，这个功能就再也不试了"，而且**一行日志都没有**。

为什么用源码断言而不是行为测试
------------------------------
这条 bug 的触发条件是"decorView 恰好在 onResume 时为 null"——在模拟器上不可按需复现
（实测设备上它反而是 true）。而这类"链表接在一根可能为 null 的对象上"的退化，
用**结构断言**是唯一稳定可判的：重试必须挂在 Handler 上，不能挂在 View 上。

    python3 -m unittest discover -s kit/python/tests -v
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SRC = os.path.join(ROOT, 'module', 'app', 'src', 'main', 'java', 'dev', 'xalor', 'kdkit',
                   'features', 'host', 'SkipOnboarding.kt')


def strip_comments(src):
    """去掉 KDoc 块注释与行注释，只留可执行代码（粗略但足够应付本文件的断言）。"""
    out, in_block = [], False
    for line in src.splitlines():
        st = line.strip()
        if in_block:
            if '*/' in st:
                in_block = False
            continue
        if st.startswith('/**') or st.startswith('/*'):
            if '*/' not in st:
                in_block = True
            continue
        if st.startswith('//'):
            continue
        out.append(line)
    return '\n'.join(out)


class RetryChainIsNotTiedToTheView(unittest.TestCase):

    def setUp(self):
        if not os.path.isfile(SRC):
            self.skipTest(f'{SRC} 不存在（模块源码结构变了？）')
        with open(SRC, encoding='utf-8') as f:
            raw = f.read()
        self.src = raw
        # **注释里会引用旧代码**（KDoc 解释"以前是怎么写的"）——结构断言必须只看真代码，
        # 否则"把 bug 写进注释"就会被误判成"bug 还在"。
        self.code = strip_comments(raw)

    def test_retry_uses_main_handler(self):
        self.assertIn('mainHandler.postDelayed', self.code,
                      '重试链必须挂在主线程 Handler 上 —— 挂在 View 上时，'
                      'decorView 为 null 会让整条链静默断掉')

    def test_no_view_bound_retry_left(self):
        # 旧写法：`v?.postDelayed(this, …)` / `v.postDelayed(this, …)`
        bad = re.findall(r'\bv\??\.postDelayed\(', self.code)
        self.assertEqual(bad, [], '还残留"把重试挂到 v 上"的写法 —— 这正是 P2-8')

    def test_giveup_is_recorded(self):
        """重试用尽必须留下证据（日志 + 抓取），否则"没找到"和"没跑"无法区分。"""
        self.assertIn('重试', self.code)
        self.assertIn('ONBOARD giveup', self.code,
                      '超时没有写抓取行 ⇒ 报告里看不出"试过但没命中"')

    def test_first_schedule_does_not_depend_on_decorview(self):
        """初次调度不能是 `root()?.postDelayed(...) ?: run.run()`。"""
        self.assertNotIn('?: run.run()', self.code,
                         '初次调度仍在依赖 decorView；为 null 时会立刻跑一次就结束')


if __name__ == '__main__':
    unittest.main()
