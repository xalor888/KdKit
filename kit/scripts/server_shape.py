#!/usr/bin/env python3
"""
kuaidui-kit / server_shape.py — 服务端"形状"的漂移监控。

客户端代码不变，服务端也能把行为改掉（配置改版、列表增删字段、A/B 换档）。这类变化不会让任何
测试变红，但会让**基于旧形状写的结论失效**。所以：对固定的若干条接口，记录"形状指纹" ——

  * `errNo`
  * `data` 顶层字段集合（排序后取哈希）
  * 每个"列表型"字段的元素个数

`--save` 建基线；默认与基线比对并列出变化。与 `path_diff`（客户端请求面）互补：
那个看"客户端发什么"，这个看"服务端回什么形状"。

    python3 kit/scripts/server_shape.py --adb emulator-5558 --save
    python3 kit/scripts/server_shape.py --adb emulator-5558
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'kit', 'python'))
import capture_schema
import textio
from device import PKG as PKG_CONST
from device import PREFS as PREFS_CONST
import net as _net  # noqa: E402  （TLS 决定点，见 kit/python/net.py）

BASE = os.path.join(ROOT, 'work', 'baselines', 'server_shape.json')

PATHS = ['/init/init/fesearchtree', '/kdapi/conf/searchtree', '/kdapi/conf/appconfig',
         '/kdapi/conf/appbannersv3', '/kdapi/conf/mycard', '/kdapi/conf/abtest',
         '/kdchat/api/chatrecommendconf', '/kdcore/submit/homebookv2',
         '/pluto/app/hotfix', '/userident/user/getdid']


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--adb', required=True)
    ap.add_argument('--capture', default=None)
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args(argv[1:])

    import kd_api
    import subprocess
    # 与其它文件同一个来源（`device.PKG`，2026-11-03 收敛）。
    # 那句 55 vs 56 的教训仍然有效，只是现在只有一个地方能打错：
    # 'com.kuaiduizuoye.scan' 少一个 u 就变成"文件不存在"。
    PKG = PKG_CONST
                           # 而报错长得像 SELinux 问题（2026-10-12 实测踩了 20 分钟）→ 统一用常量拼
    DATA = f'/data/data/{PKG}'
    cap = a.capture or os.path.join(ROOT, 'work', 'packs', '_server_shape_capture.txt')
    if not a.capture:
        CAPF = f'{DATA}/files/kdkit_capture.txt'
        out = ''
        # 用 shell=True 走"和证据包同一条路"：同样的 adb、同样的引号处理。
        # （2026-10-12 实测：subprocess 列表调用与 shell 调用在这台设备上表现不同 —— 列表调用读不到 App 私有目录）
        for flag in (f'cat {CAPF}', f"su -c 'cat {CAPF}'"):
            out = subprocess.run(f'adb -s {a.adb} shell "{flag}"', shell=True, timeout=180,
                                 capture_output=True, text=True, errors='replace', start_new_session=True).stdout
            if len(out) > 1000:
                break
        if len(out) < 1000:
            print(f'[shape] 抓取文件读不到（{len(out)} 字节）→ 先跑一次证据包或检查设备')
            return 2
        textio.write_text(cap, out)
    # 签名材料：优先用**最近证据包里已存的那两份**（历史上成功读到过，最省事）；
    # 没有才去读设备的 LibPreference —— 注意设备读取有 SELinux 上下文坑（见文件末注释）
    import glob as _glob, subprocess as _sp
    ta = os.path.join(ROOT, 'work', 'packs', '_ss_a.txt')
    tb = os.path.join(ROOT, 'work', 'packs', '_ss_b.txt')

    def _cached():
        cands = sorted(_glob.glob(os.path.join(ROOT, 'work', 'packs', '*', 'reverify_signA.txt')) +
                       _glob.glob(os.path.join(ROOT, 'work', 'packs', '*', '*signA.txt')),
                       key=os.path.getmtime, reverse=True)
        for ca in cands:
            cb = ca.replace('signA', 'signB')
            if os.path.exists(cb) and os.path.getsize(ca) > 100:
                # 令牌有轮换：只用最近的（先看它的 rc4 key 是否与本次抓取一致由调用方保证）
                textio.write_text(ta, textio.read_text(ca))
                textio.write_text(tb, textio.read_text(cb))
                return True
        return False

    if not _cached():
        PREFS = PREFS_CONST
        xml = ''
        # 先普通 cat，失败再走 su —— 两条路都用同一份路径常量。
        # 注：曾把一次失败归因于"SELinux 上下文不同"，后来证实是路径少打一个字符；
        # 所以 su 只当兜底，不作因果解释（该说法当前标记为 unverified）。
        for flag in (f'cat {PREFS}', f"su -c 'cat {PREFS}'"):
            # start_new_session：超时时把整个进程组杀掉，否则 `adb` 会活着继续挂
            # （2026-11-02 实测：`shell=True` + timeout 只杀 shell 本身）。
            xml = _sp.run(f'adb -s {a.adb} shell "{flag}"', shell=True, timeout=180,
                          capture_output=True, text=True, errors='replace',
                          start_new_session=True).stdout
            if len(xml) >= 100:
                break
        for key, dst in (('KEY_ANTISPAM_SIGN_A', ta), ('KEY_ANTISPAM_SIGN_B', tb)):
            m2 = re.search(key + r'"[^>]*>([^<]*)', xml)
            textio.write_text(dst, m2.group(1).strip() if m2 else '')
        if len(xml) < 100:
            print('[shape] 读设备 prefs 失败（SELinux 上下文坑），且本地没有缓存令牌 → 先跑一次证据包')
            return 2

    A, X = kd_api.sign_material(a.adb, os.path.join(ROOT, 'work', 'packs', '_ss_a.txt'),
                                os.path.join(ROOT, 'work', 'packs', '_ss_b.txt'))
    import re
    txt = textio.read_text(cap, encoding='utf-8', errors='replace')
    key = ''
    m = re.search(r'RC4KEY b\((\d+)\): ([0-9a-f]+)', txt)
    if m:
        key = m.group(1)
    urls = capture_schema.sign_urls(txt.splitlines())

    shape = {}
    for path in PATHS:
        cand = [u for u in urls if urllib.parse.urlparse(u).path == path]
        if not cand:
            shape[path] = {'seen': False}
            continue
        pu = urllib.parse.urlparse(cand[-1])
        q = dict(urllib.parse.parse_qsl(pu.query, keep_blank_values=True))
        kak = q.get('kakorrhaphiophobia', '0'); now = int(time.time())
        signed = [f'{k}={v}' for k, v in urllib.parse.parse_qsl(pu.query, keep_blank_values=True)
                  if k not in ('sign', '_t_', 'kakorrhaphiophobia')] + [f'_t_={now}', f'kakorrhaphiophobia={kak}']
        sign, _p = kd_api.sign_for(A, X, signed)
        body = '&'.join(urllib.parse.quote(f, safe='=') for f in signed if not f.startswith(('_t_', 'kakorrhaphiophobia')))
        doc = None
        for post in (True, False):
            try:
                import urllib.request as _ur
                import net as _net
                if post:
                    req = _ur.Request(f'https://{pu.netloc}{path}',
                        data=(body + f'&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}').encode(),
                        headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity',
                                 'Content-Type': 'application/x-www-form-urlencoded'})
                else:
                    req = _ur.Request(f'https://{pu.netloc}{path}?&{body}&sign={sign}&_t_={now}&kakorrhaphiophobia={kak}',
                        headers={'User-Agent': 'okhttp/4.9.0', 'Accept-Encoding': 'identity'})
                # 统一走 `net.ssl_context()`（2026-11-03 修）：这里原来无条件跳，
                # 而 `kd_api` 要 `--insecure` 才跳 —— 同库两种默认。
                with _ur.urlopen(req, timeout=20, context=_net.ssl_context()) as r:
                    doc = json.loads(r.read().decode('utf-8', 'replace'))
                break
            except Exception:
                doc = None
        if not isinstance(doc, dict):
            shape[path] = {'seen': False}
            continue
        d = doc.get('data')
        keys = sorted(d) if isinstance(d, dict) else []
        lists = {}
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list):
                    lists[k] = len(v)
        shape[path] = {'errNo': doc.get('errNo'),
                       'keys_sha': hashlib.sha256('|'.join(keys).encode()).hexdigest()[:16],
                       'keys_n': len(keys), 'lists': lists}

    if a.save:
        os.makedirs(os.path.dirname(BASE), exist_ok=True)
        json.dump(shape, open(BASE, 'w'), indent=1, ensure_ascii=False)
        print(f'[shape] 基线已写入（{len(shape)} 条接口）')
        return 0

    old = json.loads(textio.read_text(BASE)) if os.path.exists(BASE) else {}
    changed = []
    for path, now_s in shape.items():
        was = old.get(path)
        if was is None:
            changed.append((path, '基线里没有（新）'))
        elif (was.get('keys_sha'), was.get('lists'), was.get('errNo')) != \
                (now_s.get('keys_sha'), now_s.get('lists'), now_s.get('errNo')):
            det = []
            if was.get('keys_sha') != now_s.get('keys_sha'):
                det.append(f'字段集 {was.get("keys_n")}→{now_s.get("keys_n")}')
            if was.get('lists') != now_s.get('lists'):
                det.append(f'列表 {was.get("lists")} → {now_s.get("lists")}')
            if was.get('errNo') != now_s.get('errNo'):
                det.append(f'errNo {was.get("errNo")}→{now_s.get("errNo")}')
            changed.append((path, '；'.join(det)))
    live = [p for p, v in shape.items() if v.get('keys_n')]
    if not live:
        print(f'[shape] 没有任何接口取到形状（{len(shape)} 条全部 missing）—— 这不算"没变化"，是这次没跑通')
        return 2
    print(f'[shape] {len(shape)} 条接口（其中 {len(live)} 条取到形状）；形状变化 {len(changed)} 条')
    for p, why in changed:
        print(f'[shape]   {p}: {why}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
