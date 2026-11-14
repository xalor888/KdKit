#!/usr/bin/env python3
"""
kuaidui-kit / kd_crypto.py

Offline re-implementation of the payload crypto used by com.kuaiduizuoye.scan
7.7.2 (1811), reconstructed from yl.f ("RC4Helper") and
com.baidu.android.common.security.RC4.

    decrypt(s, key) = RC4(key, base64decode(s))          # yl.f.g  -> yl.f.n
    encrypt(s, key) = base64( RC4(key, utf8(s)) )        # yl.f.h  -> yl.f.t

The RC4 key is produced by libbaseutil.so:
    key = NativeHelper.nativeGetKey(str(versionCode))
Get it once from a live device with the Frida hooks in kit/hooks:
    frida -U -f com.kuaiduizuoye.scan -l hooks/02_net_sign.js
    -> [sign] RC4 key for input 1811 -> <KEY>

Usage:
    python3 kd_crypto.py decrypt <KEY> '<base64>'
    python3 kd_crypto.py encrypt <KEY> '<plaintext>'
    python3 kd_crypto.py rc4 <KEY> '<raw string>'
"""
import base64
import sys


def rc4(key, data):
    """Byte-exact port of com.baidu.android.common.security.RC4.

    **空 key 显式报错**（2026-11-03 修）：原来是 `i % klen` 直接
    `ZeroDivisionError: division by zero`。移植是忠实的（Android 那份
    同样会崩），但那个错因指向“除法”，而真正的问题是“你没给密钥” ——
    调用方（`kd_api.decode_token`）会以为是算法问题。
    """
    if not key:
        raise ValueError('rc4: key 为空 —— 上游解出来的密钥不对，'
                         '不是算法问题（旧报错是 ZeroDivisionError，指向错地方）')
    state = list(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + state[i] + key[i % klen]) & 0xFF
        state[i], state[j] = state[j], state[i]
    x = y = 0
    out = bytearray(len(data))
    for n, b in enumerate(data):
        x = (x + 1) & 0xFF
        y = (y + state[x]) & 0xFF
        state[x], state[y] = state[y], state[x]
        out[n] = b ^ state[(state[x] + state[y]) & 0xFF]
    return bytes(out)


def _b64d(s):
    """Android `Base64.decode(s, NO_WRAP)`；解不动时**退回原始字节**。

    **兜底以前是死的**（2026-11-03 修）：`base64.b64decode` 对 `'!!!!'`
    这类输入不抛异常，而是返回 `b''` ⇒ `except` 分支永远不执行 ⇒
    “解不动就退回原文”这个承诺从来没兑现过，而 docstring 一直这么写。

    现在先问一句“解出来的东西合不合理”：**输入里一个 base64 字符都没有，
    却解出了空字节**，那就是没解动 —— 这种输入按原文算。
    """
    padded = s + '=' * (-len(s) % 4)
    try:
        out = base64.b64decode(padded)
    except Exception:
        return s.encode()
    # `b64decode` 对非 base64 字符是静默忽略的：`'!!!!'` → `b''`。
    # 那种输入本该走原文兜底，否则密钥/密文会被换成空字节，
    # 而下游只看到“解出来是空串”，查不到原因。
    import re as _re
    if not out and _re.search(r'[A-Za-z0-9+/=]', s) is None:
        return s.encode()
    return out


def decrypt(cipher_b64, key):
    return rc4(key.encode(), _b64d(cipher_b64)).decode('utf-8', 'replace')


def encrypt(plain, key):
    return base64.b64encode(rc4(key.encode(), plain.encode())).decode()


def main(argv):
    if len(argv) != 4 or argv[1] not in ('decrypt', 'encrypt', 'rc4'):
        print(__doc__)
        return 1
    op, key, data = argv[1], argv[2], argv[3]
    if op == 'decrypt':
        print(decrypt(data, key))
    elif op == 'encrypt':
        print(encrypt(data, key))
    else:
        print(rc4(key.encode(), data.encode()).hex())
    return 0


if __name__ == '__main__':
    assert decrypt(encrypt('kuaidui', 'K'), 'K') == 'kuaidui'  # RC4 is symmetric
    sys.exit(main(sys.argv))
