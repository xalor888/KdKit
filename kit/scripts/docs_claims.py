#!/usr/bin/env python3
"""

# DOC-REALITY: SYSTEM_OVERVIEW.md 等文档里的数字 ↔ 代码算出的值
# （这一行是给 `check_doc_reality.py` 扫的登记标记 —— 新增"文档 ↔ 代码"断言时
#  必须加这一行，否则清单会漏掉它，R40 门禁表漂 8 道那类事就会重演。）
kuaidui-kit / docs_claims.py — 核对**文档里写下的数字**（2026-10-12 ✓，规则 27 ✓）。

由来：`SYSTEM_OVERVIEW.md` 里写着"**四张索引**"及其规模 ✓（如"**枚举 35 组**" ✓）。
**这些数字会过期** ✗ ⇒ 本脚本**逐条核对** ✓：文件在不在 ✓、规模对不对 ✓。

    python3 kit/scripts/docs_claims.py
退出码：0 = 都对得上 ✓；1 = 有对不上的 ✗。
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def counts():
    # 与"第 N 份导出"同一口径 ✓：README 里最后一次"第 N 份"即当前份数 ✓
    rd = open(os.path.join(ROOT, 'work', 'exports', 'README.md'), encoding='utf-8').read()
    ns = [int(m) for m in re.findall(r'第 (\d+) 份导出', rd)]
    exports = max(ns) if ns else len([f for f in os.listdir(os.path.join(ROOT, 'work', 'exports'))
                                      if f.endswith(('.csv', '.json'))])
    enums = len(json.load(open(os.path.join(ROOT, 'work', 'exports', 'param_enums.json'), encoding='utf-8')))
    # 只数"像域名的"（含点 ✓ 且含 .com/.cn/.net ✓），排除路径/文件名 ✓
    # 域名口径：反引号包着、含点、含 .com/.cn/.net。
    #
    # **排除名单**（2026-11-02 加）：`none.com` 是配置里的示例值，不是服务域；
    # 不排除它会让"被提及的域"这个数永远比重真实值多 1。
    # 排除是**显式列出**的，不是模糊匹配 —— 模糊排除等于把口径藏起来，
    # 下次数字对不上时没人知道为什么。
    _host_excl = {'none.com'}
    hosts = len(set(re.findall(r'`([a-z0-9.\-]+\.(?:com|cn|net))`',
                               open(os.path.join(ROOT, 'work', 'PARTNER_HOSTS.md'),
                                    encoding='utf-8').read())) - _host_excl)
    copy = sum(1 for _ in open(os.path.join(ROOT, 'work', 'exports', 'ui_copy_index.csv'), encoding='utf-8')) - 1
    routes = sum(1 for _ in open(os.path.join(ROOT, 'work', 'exports', 'zyb_routes.csv'), encoding='utf-8')) - 1
    # 顺带三条"别处写下的数字" ✓（2026-10-12 加 ✓，规则 27 ✓）
    # 只数"待触发清单"那张表（第 ①–⑨ 项、且第二列是"已就位的" ✓）
    aw = open(os.path.join(ROOT, 'work', 'AWAITING.md'), encoding='utf-8').read()
    awaiting = len(re.findall(r'^\| [①②③④⑤⑥⑦⑧⑨] \| \*\*`', aw, flags=re.M))
    tw = open(os.path.join(ROOT, 'work', 'TIME_WINDOWS.md'), encoding='utf-8').read()
    windows = len(re.findall(r'^\| \*\*[^*]+\*\* ✓ \|', tw, flags=re.M))
    ver = open(os.path.join(ROOT, 'module', 'VERIFICATION.md'), encoding='utf-8').read()
    # 2026-10-12 修：原来的 `[a-z_]+` **只匹配小写** ✗ ⇒ 漏掉 3 个带大写/数字的 id ✗
    # （同 R457 在 feature_agreement 里踩过的同一类坑 ✓）
    feat = len(re.findall(r'^\| `[A-Za-z0-9_]+`', ver, flags=re.M))
    # 2026-10-13 扩 ✓：**报告里的三个"当前事实"数字** ✓（R521 勘察出来的 ✓）
    rp = open(os.path.join(ROOT, 'REPORT.md'), encoding='utf-8').read()
    _enum_doc = int((re.search(r'\*\*(\d+)\s*组\*\* ✓（逐组有来源', rp) or [0, 0])[1]) if re.search(r'\*\*(\d+)\s*组\*\* ✓（逐组有来源', rp) else -1
    _meth_doc = int((re.search(r'方法面\*\* \| \*\*(\d+) 节\*\*', rp) or [0, 0])[1]) if re.search(r'方法面\*\* \| \*\*(\d+) 节\*\*', rp) else -1
    _ab_rows = sum(1 for _ in open(os.path.join(ROOT, 'work', 'exports', 'ab_experiments.csv'), encoding='utf-8')) - 1
    # 2026-10-13 再扩 ✓：报告里**文件背书**的"当前事实"数字 ✓（R523 勘察 + 核实 ✓，11/11 准 ✓）
    def _rows(rel):
        fp = os.path.join(ROOT, rel)
        return sum(1 for _ in open(fp, encoding='utf-8', errors='replace')) - 1 if os.path.exists(fp) else -1
    _FILE_NUMS = {
        '报告·AB实验': (_rows('work/exports/ab_experiments.csv'), 277),
        '报告·文案索引': (_rows('work/exports/ui_copy_index.csv'), 202),
        # 2026-10-15 改 ✓（R572 ✓）：205 → **451** ✓（**并入 H5 源码的 246 条** ✓）
        '报告·接口清单': (_rows('work/exports/endpoint_inventory.csv'), 451),
        '报告·路由表': (_rows('work/exports/zyb_routes.csv'), 81),
        '报告·地区树': (_rows('work/exports/location_tree.csv'), 331),
        '报告·考试检索': (_rows('work/exports/exam_searchconfig.csv'), 120),
        '报告·写作字段': (_rows('work/exports/writing_templates.csv'), 19),
    }
    _meth_real = len(re.findall(r'^## ', open(os.path.join(ROOT, 'work', 'METHODOLOGY.md'), encoding='utf-8').read(), flags=re.M))
    return {'exports': exports, 'enums': enums, 'hosts': hosts, 'copy': copy, 'routes': routes,
            'awaiting': awaiting, 'windows': windows, 'features': feat,
            'rep_enum': (_enum_doc, enums), 'rep_meth': (_meth_doc, _meth_real),
            'file_nums': _FILE_NUMS}


def main(argv):
    # **不接受任何参数**（2026-11-02 加）。
    #
    # 旧实现完全不看 `argv`：多打一个 `--bogus` 也照样 rc=0。
    # 而这两个工具都是"验证/刷新"类 —— 参数写错却返回成功，
    # 读的人会以为"核对过了"，实际**一次都没核对**。
    # 这和 `recover_device.sh` 静默忽略位置参数是同一类问题：
    # **静默忽略用户的输入，比报错危险得多**。
    if argv[1:]:
        sys.stderr.write('%s：本工具不接受参数，收到 %s\n' % (os.path.basename(argv[0]), argv[1:]))
        return 2

    ov = open(os.path.join(ROOT, 'work', 'SYSTEM_OVERVIEW.md'), encoding='utf-8').read()
    c = counts()
    bad = []
    checks = [
        ('枚举', r'(\d+)\s*组', c['enums']),
        ('文案', r'(\d+)\s*条', c['copy']),
        # 域：**改成校验**（2026-11-02）。
        #
        # 原来是"只提示，不判失败"，理由是"口径不同"（`真实服务域` vs `被提及的域`）。
        # 但实测那个理由站不住：文档写"22 个域被提及"，而按本脚本自己的口径算是 23 ——
        # 差 1，来源是 `PARTNER_HOSTS.md` 里有一个配置示例值 `none.com`。
        # **1 个单位的漂移正是"只提示"必然漏掉的东西**：没人会为 1 去核对。
        #
        # 现在：口径写进代码（含显式排除名单），并对文档里的"被提及"数判失败。
        # "真实服务域"那半个仍然只提示 —— 它靠正文里的散文结论，没有可计算的单一来源。
        ('域', r'(\d+)\s*个域被提及', c['hosts']),

        ('导出', r'(\d+)\s*份', c['exports']),
    ]
    for label, pat, actual in checks:
        m = re.search(pat, ov)
        if not m:
            continue
        claimed = int(m.group(1))
        if claimed != actual:
            bad.append((label, claimed, actual))
    # 报告里的两个"当前事实"数字 ✓（2026-10-13 扩 ✓）
    for _k, (_real, _claim) in c['file_nums'].items():
        if _real >= 0 and _real != _claim:
            bad.append((_k, _claim, _real))
    if c['rep_enum'][0] > 0 and c['rep_enum'][0] != c['rep_enum'][1]:
        bad.append(('报告·枚举', c['rep_enum'][0], c['rep_enum'][1]))
    if c['rep_meth'][0] > 0 and c['rep_meth'][0] != c['rep_meth'][1]:
        bad.append(('报告·方法面', c['rep_meth'][0], c['rep_meth'][1]))
    if bad:
        print(f'[claims] **{len(bad)} 处对不上** ✗（文档 vs 实际）：')
        for label, claimed, actual in bad:
            print(f'   {label}: 文档写 {claimed} ✗ / 实际 {actual} ✓')
        return 1
    print(f'[claims] 数字都对得上 ✓（枚举 {c["enums"]} / 文案 {c["copy"]} / 域 {c["hosts"]} / '
          f'导出 {c["exports"]} / 路由 {c["routes"]} / 待触发 {c["awaiting"]} / '
          f'时间窗 {c["windows"]} / 功能 {c["features"]}）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))


# 备注（2026-10-12）：本工具的**前四条**（枚举 / 文案 / 域 / 导出）口径已定 ✓ 且**纳入烟测** ✓；
# 另三条（待触发 / 时间窗 / 功能）**口径还没定稳** ✗ —— 只**展示** ✓，**不判失败** ✗。
# ⇒ 这正是**规则 20**（先定粒度 ✓）在工具里的应用 ✓：**没定粒度就不下判决** ✓。
