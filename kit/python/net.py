#!/usr/bin/env python3
"""
kuaidui-kit / net.py — 全库**唯一**的"要不要跳过 TLS 校验"决定点。

### 为什么需要

2026-11-03 代码审查 P1：

> 6 处**无条件**跳过 TLS 校验（`pageapi:43`、`composition_flow:50`、
> `export_content:64`、`extract_config:94`、`extract_samples:128`、`probe_paths:151`），
> 而 `kd_api` 是 `--insecure` 才跳 —— **同库两种默认**。

同一个仓库里，`kd_api.py` 要你显式给 `--insecure` 才跳过证书校验，
另外六个文件**问都不问**就跳。两种默认值的后果：

* 同一个请求，走 A 工具能成、走 B 工具不能成（或反过来），而差异不在代码逻辑里；
* 前面挂着代理/自签证书时，六个工具静默接受，`kd_api` 报错 ——
  于是"到底是服务端拒绝了，还是我的证书环境不对"这件事**无法从现象区分**；
* 新写一个工具的人会照抄旁边那份，把"无条件跳"继承下去。

### 用法

```python
from net import ssl_context
ctx = ssl_context()            # 默认**校验**；KD_INSECURE=1 时才跳
```

**默认值是校验**，与 `kd_api` 的 `--insecure` 语义一致（要跳得显式说）。
判据只有一处，门禁 ㉙ 负责盯着"不许再出现无条件跳过"。
"""
import os
import ssl

#: 环境变量名。用环境变量而不是每个脚本各加一个 `--insecure`：
#: 这六个脚本都是**被其它脚本/门禁调用的库函数**，加 CLI 参数要改一圈调用点，
#: 而"这一次运行要不要跳"本来就是一个运行期决定。
ENV = 'KD_INSECURE'


def insecure() -> bool:
    """这一次运行是否明确要求跳过证书校验。**默认 False（校验）**。"""
    v = os.environ.get(ENV, '').strip().lower()
    return v in ('1', 'true', 'yes', 'on')


def ssl_context():
    """`urlopen` 用的 context：默认校验，`KD_INSECURE=1` 才跳过。"""
    if insecure():
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def describe() -> str:
    """一句话说明当前模式 —— 给日志用，别让"跳没跳"只能靠猜。"""
    return (f'TLS 校验已跳过（{ENV}=1）' if insecure()
            else 'TLS 校验开启（默认）')
