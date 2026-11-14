"""`bridge_urls.urls_of` 的退化正则必须真的能匹配。

2026-11-04 代码审查 P1：那一行写的是

    re.search(r'"url"\\\\s*:\\\\s*"([^"]+)"', args)

**raw string 里的 `\\\\` 是两个字符**（反斜杠 + 反斜杠），所以这个正则要求
参数文本里真的出现 `\\s`，而那只在"某人把 Python 正则当字面量写进字符串"时
才会发生。于是：

* 合法 JSON ⇒ 走第一个分支，没问题；
* **非 JSON 的 args** ⇒ 走这个退化正则 ⇒ **永远不匹配** ⇒ url 全丢。

而调用方看到的是"这个页面没有绝对 URL"，与"解析失败"完全一样。

这个文件钉住：退化路径**必须能从一段非 JSON 的 params 文本里拉出 URL**。
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', '..', 'scripts', 'bridge_urls.py')


def load():
    spec = importlib.util.spec_from_file_location('_bridge_urls_under_test', TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FallbackRegexMatches(unittest.TestCase):

    def setUp(self):
        self.m = load()

    def test_json_form(self):
        self.assertEqual(self.m.urls_of('{"url":"https://a/b?x=1"}'),
                         ['https://a/b?x=1'])

    def test_json_form_with_spaces(self):
        self.assertEqual(self.m.urls_of('{"url": "https://a/c"}'), ['https://a/c'])

    def test_non_json_fallback_still_finds_url(self):
        """**这就是旧写法丢掉的那一类**：不是合法 JSON，但里面确实有 url。"""
        got = self.m.urls_of('url : "https://a/d", other=1')
        self.assertEqual(got, ['https://a/d'])

    def test_non_json_fallback_with_newlines(self):
        got = self.m.urls_of('{\n  url:\n    "https://a/e"\n  x=1')
        self.assertEqual(got, ['https://a/e'])

    def test_no_url_returns_empty_not_error(self):
        self.assertEqual(self.m.urls_of('{"count":3}'), [])

    def test_link_and_src_keys(self):
        self.assertEqual(self.m.urls_of('{"link":"https://a/l"}'), ['https://a/l'])
        self.assertEqual(self.m.urls_of('{"src":"https://a/s"}'), ['https://a/s'])


if __name__ == '__main__':
    unittest.main()
