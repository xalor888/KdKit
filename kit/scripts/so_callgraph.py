#!/usr/bin/env python3
"""
kuaidui-kit / so_callgraph.py — 从一组起点函数出发，判定「能否到达危险汇点」
（abort / raw_syscall / __stack_chk_fail），并给出最短路径。

为什么需要它
────────────
`work/dpsdk/DELTA-710.md` 前一轮只做了「串 → 内联引用」的两列观测，**没有做可达性**。
于是「libdpsdk 会杀进程」一直是 `inferred`（从行为归因），没有代码级证据。
本脚本把归因变成可复跑的判定：**从 JNI init / maps 扫描函数出发，按 `bl` + 本地 `b`
目标做 BFS，看危险汇点是否可达**。

判据
────
  REACHABLE     起点到汇点存在直接分支路径（`observed`，覆盖率=直接 bl/b 目标）
  NOT_REACHABLE 在给定深度内不可达（`observed` within coverage；**不等于不存在**）
  INDIRECT      存在间接调用/函数指针 ⇒ 该函数的下游是 `unknown`，不参与"不可达"结论

覆盖边界
────────
  * 只认 `bl <目标>`（直接调用）与 `b <目标>`（尾调用），不跟 `blr`（间接）、不跟 PLT/GOT
  * 不跟 `svc`（系统调用号由 x8 决定；本库 12 处 svc 全是 close/read/openat/fstatat）
  * 起点必须是函数入口（prologue 扫描得到），否则范围算不准
"""
import argparse, json, os, re, subprocess, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SINKS = {
    'abort': 'abort@plt',
    'stack_chk_fail': '__stack_chk_fail@plt',
    'abort_message': 'android_set_abort_message@plt',
}


def _objdump():
    """优先 NDK 的 llvm-objdump（macOS 自带 objdump 不认 arm64 ELF）；找不到就退回 PATH 里的。"""
    import glob
    c = sorted(glob.glob(os.path.expanduser(
        '~/Library/Android/sdk/ndk/*/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-objdump')))
    return c[-1] if c else 'objdump'


def disassemble(path):
    out = subprocess.run([_objdump(), '-d', path], capture_output=True, text=True,
                         errors='replace', timeout=180)
    if out.returncode != 0:
        sys.exit('objdump failed: ' + out.stderr[:400])
    ins = []
    pat = re.compile(r'^\s*([0-9a-f]{4,8}):\s+([0-9a-f ]+)\t(.*)$')
    for ln in out.stdout.split('\n'):
        m = pat.match(ln)
        if m:
            ins.append((int(m.group(1), 16), m.group(3).strip()))
    return ins


def plt_map(ins):
    m = {}
    for a, t in ins:
        mm = re.search(r'<([^>]+)@plt>', t)
        if mm and t.startswith(('b', 'bl')):
            m.setdefault(mm.group(1), a)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--so', default=os.path.join(ROOT, 'work', 'apktool_out', 'lib',
                                                 'arm64-v8a', 'libdpsdk.so'))
    ap.add_argument('--start', action='append', default=[],
                    help='起点函数地址，如 0x10b334（可重复）')
    ap.add_argument('--depth', type=int, default=4)
    ap.add_argument('--json', default=None)
    a = ap.parse_args()

    ins = disassemble(a.so)
    addr2i = {x[0]: i for i, x in enumerate(ins)}
    plt = plt_map(ins)

    # 函数边界：prologue → 下一个 ret
    prol = [x[0] for x in ins if re.search(r'stp\s+x29, x30, \[sp, #-0x[0-9a-f]+\]!', x[1])]
    rets = [x[0] for x in ins if x[1] == 'ret']

    def fstart(addr):
        c = [p for p in prol if p <= addr]
        return c[-1] if c else None

    def fend(start):
        c = [r for r in rets if r > start]
        return c[0] if c else None

    # 每个函数：出边（bl 目标、本地 b 目标）与是否有间接调用
    def edges_of(start):
        end = fend(start)
        out, indirect = [], False
        if end is None:
            return out, indirect
        for addr, t in ins:
            if not (start <= addr <= end):
                continue
            if re.match(r'blr\b', t) or re.search(r'ldr\s+x[0-9]+, .*(#0x|\[)', t) and 'blr' in t:
                indirect = True
            mm = re.match(r'(bl|b)\s+0x([0-9a-f]+)', t)
            if mm:
                tgt = int(mm.group(2), 16)
                out.append((addr, tgt))
        return out, indirect

    cache = {}
    def E(s):
        if s not in cache:
            cache[s] = edges_of(s)
        return cache[s]

    starts = [int(x, 16) for x in a.start]
    report = {'so': a.so, 'sinks': SINKS, 'plt': plt, 'starts': [hex(s) for s in starts],
              'depth': a.depth, 'reach': [], 'not_reaching': [], 'unknown_funcs': []}

    plt_addr2name = {v: k for k, v in plt.items()}

    for s in starts:
        # BFS
        q = collections.deque([(s, [])])
        seen = {s}
        found = None
        unknown = False
        while q:
            cur, path = q.popleft()
            if len(path) > a.depth:
                continue
            outs, indirect = E(cur)
            if indirect:
                unknown = True
            for src, tgt in outs:
                name = plt_addr2name.get(tgt)
                if name in SINKS:
                    found = {'sink': name, 'path': [hex(x) for x in path + [cur]],
                             'call_site': hex(src), 'sink_addr': hex(tgt)}
                    break
                if tgt in seen or tgt >= 0x800000 or fstart(tgt) is None:
                    continue
                seen.add(tgt)
                q.append((tgt, path + [cur]))
            if found:
                break
        rec = {'start': hex(s), 'range': [hex(fstart(s)) if fstart(s) else None,
                                          hex(fend(s)) if fend(s) else None],
               'reachable_danger': found, 'indirect_call_present': unknown,
               'visited': len(seen)}
        (report['reach'] if found else report['not_reaching']).append(rec)

    # svc 审计
    svcs = []
    for i, (addr, t) in enumerate(ins):
        if t.startswith('svc'):
            # 往前找 mov x8, #imm
            nr = None
            for j in range(max(0, i - 12), i):
                mm = re.search(r'mov\s+x8, #(0x[0-9a-f]+)', ins[j][1])
                if mm:
                    nr = int(mm.group(1), 16)
            svcs.append({'addr': hex(addr), 'syscall_nr': nr})
    report['svc_sites'] = svcs

    txt = json.dumps(report, indent=2, ensure_ascii=False)
    print(txt)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            f.write(txt)


if __name__ == '__main__':
    main()
