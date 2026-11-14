#!/usr/bin/env python3
"""Mars xlog 解码器（2026-10-15 写 ✓，R579 ✓）。

来历：R578 发现 `files/tdLogDir/*.xlog` 是 App 自己的 4 天日志，
头是明文（`log_appenderOpen__Lcom_tencent_mars_xlog…`），载荷按帧打包。
Mars xlog 帧格式（公开规范）：
  * 文件头：magic(1) + ...
  * 每帧：magic(1) + len(2, 小端) + payload(len)
      magic 0x07 => 明文
      magic 0x08 => 压缩（通常是 zlib；解压后前 1 字节可能再是 0x07）
  * 也兼容"整段 zlib"的变体
用法：python3 kit/scripts/xlog_decode.py <file.xlog> [--limit N]
"""
import sys, zlib

MAGIC_PLAIN, MAGIC_ZLIB, MAGIC_ZSTD = 0x07, 0x08, 0x09

def frames(b):
    i = 0
    # 跳过文件头：找到第一个 0x07 或 0x08（帧 magic）
    while i < len(b) and b[i] not in (MAGIC_PLAIN, MAGIC_ZLIB):
        i += 1
        if i > 512:      # 头太长 ⇒ 换法：全文找
            break
    while i + 3 <= len(b):
        m = b[i]
        if m not in (MAGIC_PLAIN, MAGIC_ZLIB, MAGIC_ZSTD):
            i += 1
            continue
        n = int.from_bytes(b[i+1:i+3], 'little')
        if n == 0 or i + 3 + n > len(b):
            i += 1
            continue
        payload = b[i+3:i+3+n]
        yield m, payload
        i += 3 + n

def decode(payload, magic):
    if magic == MAGIC_PLAIN:
        return payload
    # 0x08 => zlib ✓ ; 0x09 => zstd ✓（2026-10-15 补 ✓，R579 ✓）
    if magic == MAGIC_ZLIB:
        for attempt in (payload, payload[1:] if payload else b''):
            try:
                d = zlib.decompress(attempt)
                if d and d[0] == MAGIC_PLAIN:
                    d = d[1:]
                return d
            except Exception:
                continue
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        for attempt in (payload, payload[1:] if payload else b''):
            try:
                d = dctx.decompress(attempt, max_output_size=1 << 22)
                if d and d[0] == MAGIC_PLAIN:
                    d = d[1:]
                return d
            except Exception:
                continue
    except Exception:
        pass
    # 兜底：也许整段就是明文（含可打印字符）✓
    if sum(1 for c in payload[:120] if 32 <= c < 127) > 100:
        return payload
    return None

def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    path = sys.argv[1]
    limit = 50
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    b = open(path, 'rb').read()
    print(f'# {path}: {len(b)} B')
    nf = nok = 0
    shown = 0
    for magic, payload in frames(b):
        nf += 1
        d = decode(payload, magic)
        if d is None:
            continue
        nok += 1
        try:
            txt = d.decode('utf-8', 'replace')
        except Exception:
            txt = repr(d)
        for line in txt.split('\n'):
            if not line.strip():
                continue
            if shown < limit:
                print(line.rstrip())
                shown += 1
    print(f'# 帧 {nf} ✓ / 解出 {nok} ✓ / 打印 {shown} 行（--limit 调）', file=sys.stderr)
    return 0

if __name__ == '__main__':
    sys.exit(main())
