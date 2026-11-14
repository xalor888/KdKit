#!/usr/bin/env python3
"""
kuaidui-kit / decrypt_capture.py — offline decryption of a KdKit capture.

`KdKit` 的 SignObserver 功能会把宿主进程里的签名参数、签名结果、RC4 密钥和
完整签名 URL 写进 快对 私有目录的 `files/kdkit_capture.txt`：

    adb shell cat /data/data/com.kuaiduizuoye.scan/files/kdkit_capture.txt > cap.txt
    python3 decrypt_capture.py cap.txt

前缀解析统一走 `capture_schema.py`（格式的唯一声明处），因此本脚本认得模块能写出的
**每一种**密钥行 —— 旧版只匹配 `RC4KEY…: <hex>`，`RC4KEYSTR` / `RC4KEY <hex> | len=`
（rc4_probe 的两条）整类被漏掉：

    RC4KEY b(<versionCode>): <hex 128>   sign_observer — nativeGetKey，按 epoch
    RC4KEY refreshed: <hex 128>          sign_observer — 热修后重读
    RC4KEYSTR <ascii> | len=<n>          rc4_probe     — RC4 构造器（String 重载）
    RC4KEY <hex> | len=<n>               rc4_probe     — RC4.setKey(byte[])

然后对每把密钥尝试解密：
  * 每个签名 URL 里那些"看起来像密文"的 query 字段（URL-decode → base64 → RC4），
  * `H5 DECRYPT in=` 负载，
  * `WEBREQ` 行里出现的 base64 形态的参数（页面自有接口也可能带密文），
并打印能解成可读文本的结果。两种密钥编码都试（128 字符串按 ASCII、按 hex 解码字节），
因为 `nativeGetKey` 的返回形态随安装而变。

`RC4PT` / `RC4UP` 行里的明文**不当作密钥**，只作为"同一段密文解出什么"的对照：
它们已经是模块在设备上解出来的结果，能直接验证本脚本的离线结果是否一致。
"""
import base64
import sys
import urllib.parse

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from capture_schema import iter_records  # noqa: E402
from kd_crypto import rc4  # noqa: E402
from device_entry_crypto import ENTRY_KEY, rc4 as rc4_entry  # noqa: E402


def entry_key_decrypt(b64):
    """Second scheme: com.baidu.device RC4Encrypt with the hardcoded PackageHelper.ENTRY_KEY."""
    try:
        raw = base64.b64decode(urllib.parse.unquote(b64) + '=' * (-len(b64) % 4))
    except Exception:
        return None
    pt = rc4_entry(ENTRY_KEY.encode(), raw)
    return pt if printable(pt) else None


def printable(b, thresh=0.85):
    if not b:
        return False
    good = sum(1 for c in b if 32 <= c < 127 or c in (9, 10, 13))
    return good / len(b) >= thresh


def try_decrypt(b64, key):
    """Return (form, plaintext_bytes) for every key encoding that yields text."""
    results = []
    for form, kbytes in (('ascii', key.encode()),
                         ('hex', bytes.fromhex(key) if re_fullmatch_hex(key) else b'')):
        if not kbytes:
            continue
        try:
            pol = base64.b64decode(b64 + '=' * (-len(b64) % 4))
        except Exception:
            continue
        pt = rc4(kbytes, pol)
        if printable(pt):
            results.append((form, pt))
    return results


def re_fullmatch_hex(s):
    return len(s) % 2 == 0 and all(c in '0123456789abcdefABCDEF' for c in s)


def collect(records):
    """Split a capture into the three things this script needs, in one pass."""
    keys, urls, h5, device_pt = [], [], [], []
    for rec in records:
        if rec.kind in ('RC4KEY', 'RC4KEYSTR'):
            k = rec.get('key') or ''
            if k and k not in keys:
                keys.append(k)
        elif rec.kind == 'SIGN_URL':
            u = rec.get('url')
            if u and u not in urls:
                urls.append(u)
        elif rec.kind == 'H5' and rec.get('dir') == 'in':
            h5.append(rec.get('value') or '')
        elif rec.kind in ('RC4PT', 'RC4UP') and rec.variant is None:
            device_pt.append((rec.kind, rec.get('text') or ''))
    return keys, urls, h5, device_pt


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    keys, urls, h5, device_pt = collect(iter_records(argv[1]))
    print(f'[dec] {len(keys)} RC4 key(s): ' + ', '.join(k[:24] + '…' for k in keys))
    print(f'[dec] {len(urls)} signed URL(s), {len(h5)} H5 payload(s), '
          f'{len(device_pt)} device-side plaintext(s)')

    # 0) 设备已经解出来的明文：先打出来，后面每条离线结论都能对着它核。
    for kind, text in device_pt[:10]:
        print(f'  [=] {kind} (设备解出): {text[:200]}')

    # 1) signed URLs -> encrypted-looking fields
    hits = 0
    for u in urls:
        p = urllib.parse.urlparse(u)
        fields = dict(urllib.parse.parse_qsl(p.query, keep_blank_values=True))
        sig, t, kak = fields.get('sign'), fields.get('_t_'), fields.get('kakorrhaphiophobia')
        cand = [v for k, v in fields.items()
                if k not in ('sign', '_t_', 'kakorrhaphiophobia')
                and v and all(c.isalnum() or c in '+/=%' for c in v) and len(v) >= 24]
        if not cand:
            print(f'  [ ] {p.netloc}{p.path}: no encrypted field (sign={sig})')
            continue
        for c in cand:
            raw = urllib.parse.unquote(c)
            pt = entry_key_decrypt(c)
            if pt is not None:
                hits += 1
                print(f'  [+] {p.netloc}{p.path}  key=ENTRY_KEY(PackageHelper)  sign={sig} t={t} kak={kak}')
                print(f'      plaintext: {pt[:600].decode("utf-8", "replace")}')
            for key in keys:
                for form, pt in try_decrypt(raw, key):
                    hits += 1
                    print(f'  [+] {p.netloc}{p.path}  key=nativeGetKey/{form}  sign={sig} t={t} kak={kak}')
                    print(f'      plaintext: {pt[:600].decode("utf-8", "replace")}')

    # 2) H5 payloads
    for value in h5:
        raw = urllib.parse.unquote(value)
        for key in keys:
            for form, pt in try_decrypt(raw, key):
                hits += 1
                print(f'  [+] H5 payload  key={form}: {pt[:400].decode("utf-8", "replace")}')

    if not hits:
        print('[dec] 没有任何字段被解开 —— 要么这轮确实没有加密负载（游客态常见），'
              '要么密钥行与负载不同轮（看 RC4KEY 的时间戳）。这不是"解不出来"的结论。')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
