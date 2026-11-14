#!/usr/bin/env python3
"""
kuaidui-kit / device_entry_crypto.py

The **device-identity** crypto path of com.kuaiduizuoye.scan 7.7.2 — a *third*,
completely static scheme, distinct from the two native-key paths in
`kd_crypto.py` (RC4 key from `libbaseutil.so nativeGetKey`, bound to the install).

Found by reading `com.baidu.device.DeviceIdHelper` (§R1 findings):

    request = RC4Encrypt.encryptString(json.toString(), new RC4(PackageHelper.ENTRY_KEY))
            = Base64_NO_WRAP( RC4(key, utf8(json)) )
    Getdid.Input.buildInput(request)  ->  GET /userident/user/getdid?&param=<urlencoded>

with the key hardcoded in the dex:

    PackageHelper.ENTRY_KEY = "msyx6nw$jwk12.76alvkf"

The same key is used by `TomDigest.encryptString/decryptString` for the local
`files/IU.ud` device-id cache and for the obfuscated package-name list, so this
one constant opens several strings at once.

Usage:
    python3 device_entry_crypto.py decrypt '<base64>'         # URL-decoded first if needed
    python3 device_entry_crypto.py decrypt-url '<full url>'
    python3 device_entry_crypto.py encrypt '<json>'
"""
import base64
import sys
import urllib.parse

ENTRY_KEY = "msyx6nw$jwk12.76alvkf"


def rc4(key: bytes, data: bytes) -> bytes:
    """com.baidu.device.utils.RC4 / RC4Encrypt — classic RC4, fresh state per call."""
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for b in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def decrypt(b64: str, key: str = ENTRY_KEY) -> str:
    """解密一个（可能被 URL 编码过的）base64 密文。

    **padding 必须按 `unquote` 之后的长度算**（2026-11-03 修，代码审查 P1）。

    旧实现：

        base64.b64decode(urllib.parse.unquote(b64) + '=' * (-len(b64) % 4))

    `unquote` 只会**缩短**字符串（`%2B`→`+`、`%3D`→`=`），
    所以按**编码前**的长度算 padding 会**多补**。实测 29 种原始长度里
    15 种算错（多补 2 个 `=`）。

    现在之所以还没炸，是 Python 的 `b64decode` 对多余 padding 很宽容；
    而 Android 的 `Base64.decode(s, NO_WRAP)` 不宽容 ——
    “Python 解得开、设备上解不开”正是最难查的那一类。

    **测试钉的是算出来的 padding 本身**，不是 roundtrip ——
    否则这条 bug 会因为“恰好还能用”而一直被掩盖。
    """
    return rc4(key.encode(), b64d(b64)).decode('utf-8', 'replace')


def b64d(b64: str) -> bytes:
    """URL 解码 + 按**解码后**的长度补 padding + base64 解码。

    单独成函数是为了能测：`decrypt` 一路到 `rc4` 就看不见中间那步了，
    而 bug 恰恰在中间那步（2026-11-03：测试第一版自己重算了 padding，
    于是改回旧公式它照样绿 —— **测了概念，没测代码**）。
    """
    unq = urllib.parse.unquote(b64)
    return base64.b64decode(unq + '=' * (-len(unq) % 4))


def encrypt(plain: str, key: str = ENTRY_KEY) -> str:
    return base64.b64encode(rc4(key.encode(), plain.encode())).decode()


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    op, arg = argv[1], argv[2]
    key = argv[3] if len(argv) > 3 else ENTRY_KEY
    if op == 'decrypt':
        print(decrypt(arg, key))
    elif op == 'decrypt-url':
        q = urllib.parse.parse_qs(urllib.parse.urlparse(arg).query, keep_blank_values=True)
        print(decrypt(q['param'][0], key))
    elif op == 'encrypt':
        print(encrypt(arg, key))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    assert decrypt(encrypt('{"a":1}')) == '{"a":1}'
    sys.exit(main(sys.argv))
