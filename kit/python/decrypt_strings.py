#!/usr/bin/env python3
"""
kuaidui-kit / decrypt_strings.py — 还原 App 里那些"看起来像密文"的单字段字符串。

很多字段（书名、图片 URL、标题…）在响应里不是明文，而是 `yl.f` 层的单值加密：
`yl.f.n(String)`。实测（2026-10-11）它就是：

    plaintext = RC4( nativeGetKey(versionCode), base64decode(cipher) )

与请求签名用的是同一把负载密钥（同一 epoch）。因此**离线可还原**：拿到当前 key（抓取里的
`RC4KEY b(<vc>): …` 行）即可。

    # 1) 用抓取自校验：把 capture 里所有 `H5 n in/out` 对解一遍，报告匹配率
    python3 kit/python/decrypt_strings.py --verify work/packs/r82/capture.txt

    # 2) 单条/多条还原（key 来自抓取或直接给）
    python3 kit/python/decrypt_strings.py --capture cap.txt 'k5Uq8w7CjX/EUqGPPJQzFMvglY//ZFzF6QhjewYzWW6JJsoxtLxFpOiaDKKA'
"""
import argparse
import base64
import re
import sys

HERE = __file__.rsplit('/', 1)[0]
sys.path.insert(0, HERE)
import textio
from kd_crypto import rc4  # noqa: E402

KEY_LINE = re.compile(r'RC4KEY b\((\d+)\): ([0-9a-f]+)')
PAIR = re.compile(r'H5 n in: (\S+)[^\n]*\n[^\n]*H5 n out: ([^\n]*)')


def key_from(path=None, key=None):
    if key:
        return key.strip().encode()
    if not path:
        return None                 # 调用方会打印"给 --key 或 --capture"
    txt = textio.read_text(path)   # 2026-11-03：path 可给 .txt.gz
    m = KEY_LINE.search(txt)
    return m.group(1).encode() if m else None


def decrypt_with_key(key: bytes, cipher: str) -> str:
    """**key 在前**（2026-11-03 改名，代码审查 P2“同名不同契约”）。

    三个模块都有一个 `decrypt`，而参数顺序**不一样**：

        decrypt_strings   decrypt(key, cipher)        ← key 在前
        kd_crypto         decrypt(cipher_b64, key)
        device_entry_crypto decrypt(b64, key)

    三者参数都是字符串 ⇒ **调换顺序不会报错**，只会解出一串垃圾。
    今天已经为“同名不同契约”栽过一次（`sh()` 收不收 list，12 个文件中招），
    那一次的契约差别还会抛异常；这一次**静默**。

    所以把这个函数改名成把参数顺序写进名字的形式，让误调在阅读时就能发现。
    """
    raw = base64.b64decode(cipher + '=' * (-len(cipher) % 4))
    return rc4(key, raw).decode('utf-8', 'replace')


# 旧名留着，但**立刻炸**：宁可让误调当场失败，也不要它静默解出垃圾。
def decrypt(key, cipher):                                          # noqa: D401
    raise TypeError(
        'decrypt_strings.decrypt(key, cipher) 已改名 —— 它的 key 在**前**，'
        '而 kd_crypto / device_entry_crypto 的 decrypt 密文在前。'
        '两者参数都是 str，调换顺序不会报错、只会解出垃圾。'
        '请改用 decrypt_with_key(key, cipher)。')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('values', nargs='*')
    ap.add_argument('--capture', default=None)
    ap.add_argument('--key', default=None)
    ap.add_argument('--verify', default=None, help='用抓取里的 H5 n in/out 对自校验，报告匹配率')
    a = ap.parse_args(argv[1:])

    key = key_from(a.capture or a.verify, a.key)
    if not key:
        print('[decrypt] 找不到 key（给 --key 或含 RC4KEY 行的 --capture）')
        return 2
    print(f'[decrypt] key 头 16 位：{key[:16].decode()}')

    if a.verify:
        txt = open(a.verify, encoding='utf-8', errors='replace').read()
        pairs = PAIR.findall(txt)
        ok = 0
        failed = []
        for c, p in pairs:
            try:
                if decrypt_with_key(key, c).strip() == p.strip():
                    ok += 1
                else:
                    failed.append((c, '解出来但对不上'))
            except Exception as e:                       # noqa: BLE001
                # **不能静默**（2026-11-06，代码审查 P1）。
                #
                # 旧实现 `except Exception: pass` 把"解密抛异常"和"没匹配上"
                # 混成同一件事：两个都只是"少算一个 ok"。
                # 而 `ok/总数` 那个比例**看不出是哪一种** ——
                # 密钥错了（抛异常）和样本本来就不匹配（值不同），
                # 排查方向完全相反。
                failed.append((c, f'{type(e).__name__}: {e}'))
        print(f'[decrypt] 自校验：{ok}/{len(pairs)} 对匹配（H5 n in/out）')
        if failed:
            # 说清**两类失败各多少** —— 比例只说"差了几个"。
            n_exc = sum(1 for _c, why in failed if ':' in why and '解出来但对不上' not in why)
            n_mismatch = len(failed) - n_exc
            print(f'[decrypt]   失败明细：{len(failed)} 条 '
                  f'（抛异常 {n_exc} / 解出来但对不上 {n_mismatch}）')
            for c, why in failed[:3]:
                print(f'[decrypt]     {c[:40]}… → {why[:90]}')
            if n_exc:
                print('[decrypt]   **有解密抛异常** ⇒ 密钥多半不对；'
                      '若全是"对不上" ⇒ 密钥能解开但样本不是同一份。')
        return 0 if pairs and ok == len(pairs) else 1

    for v in a.values:
        try:
            print(decrypt_with_key(key, v))
        except Exception as e:
            print(f'[decrypt] {v[:20]}… 失败：{e}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
