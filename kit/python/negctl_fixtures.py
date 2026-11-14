#!/usr/bin/env python3
"""
kuaidui-kit / negctl_fixtures.py — **装着故意写坏的代码**的文件清单。

### 为什么需要

`run_negative_controls.py` 里存着每一道门禁的"故障注入"样本：
为了证明某道门禁真的会红，它会把一段**已知有问题的代码**临时写进被测文件。

于是任何"扫全库找坏味道"的检查器都会把这些样本当成真缺陷：

| 门禁 | 被自己的负对照绊倒 |
|---|---|
| ㉘ 签名请求体组装一致 | `run_negative_controls.py` 里存着一处 `startswith('_t_')` |
| ㉙ TLS 只有一个决定点 | 同一个文件里存着一处 `_create_unverified_context()` |

**后果是那道门禁永远红** —— 而一道永远红的门禁会被直接跳过。
今天已经为此修过 4 个检查器，每次都是"加了门禁才发现要排除"。

所以把清单抽成**一处**：新检查器照抄这一行，就不会重蹈覆辙。

### 用法

```python
from negctl_fixtures import is_fixture, FIXTURES
if is_fixture(path):
    continue
```

### 为什么排除它们是安全的

那些坏代码**不会被执行**：`run_negative_controls.py` 只是把它们
**临时写进别的文件、跑一次检查、再还原**。它们躺在 fixture 文件里，
唯一的"执行"是被当成字符串读出来。
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

#: 仓库相对路径。加新条目时**必须写理由** —— 否则半年后没人知道
#: 为什么这个文件可以豁免，于是有人把它当成"反正也豁免了"的口子。
FIXTURES = {
    'kit/scripts/run_negative_controls.py':
        '门禁负对照的故障注入样本库；其中的坏代码不会被执行，'
        '只是被临时写进别的文件再还原',
}


def is_fixture(path):
    """`path`（绝对或仓库相对）是否是装着故意写坏代码的文件。"""
    rel = os.path.relpath(os.path.abspath(path), ROOT)
    return rel in FIXTURES
