#!/usr/bin/env python3
"""
Offline test: `aj.a.p()`（7.7.2 里叫 `bk.a.p()`）的调用点必须按"结果被谁消费"分类，而不是按印象。

为什么需要
----------
第 26 轮核 `vip_unlock` 的作用面时，先看了 6 个调用点，发现结果都进
`Boolean;->toString`，就写下"17 处全部只用于打点"。跑全量脚本后是
**3 处真闸门 + 14 处打点** —— `aj/f` 里 VIP 为真就 `return-void`。
结论方向反了，差一点进文档。

判据（机械、可复跑）
--------------------
`invoke-static {}, Lbk/a;->p()Z` 之后拿 `move-result r`，再看 `r` 的去向：

* `if-* r`  ⇒ **GATE**：结果决定控制流，`vip_unlock` 改它会改变行为；
* `Boolean;->toString` / `StringBuilder;->append` ⇒ **STAT**：只是埋点。

本文件把这两个数字钉住。数字变了（宿主换版、加了新分支）就红，逼人重新归类，
而不是让"17 处全打点"这种错的量词继续躺在文档里。

未验证：这 3 处是否**穷尽**了服务端授权点 —— 客户端判定 ≠ 服务端授权。

Run:

    python3 -m unittest kit/python/tests/test_vip_call_sites.py -v
"""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
APK = os.path.join(ROOT, 'work', 'apktool_out')

CALL = re.compile(r'invoke-static \{\}, Laj/a;->p\(\)Z')   # 7.9.0：旧 bk.a → 新 aj.a
MOVE = re.compile(r'\s*move-result(?:-object|-wide)? ([vp]\d+)')
#: 注意：这里必须留 `{reg}` 占位符**等运行时再编译**。写成 `re.compile(...{reg}...)`
#: 会把 `{reg}` 当成字面量，稍后调 `.format()` 直接 `AttributeError`。
IF_ON = r'\bif-(?:eqz|nez|eq|ne|lt|gt|le|ge)\s+{reg}\b'
METHOD_END = re.compile(r'^\.end method')

#: 没有指令层面的 liveness 分析，就必然在"窗口太窄"和"窗口太宽"之间来回摇摆：
#:   * 取 14~16 行 ⇒ `oj/t0:721` 的消费点在 20 行外，被归成 UNKNOWN；
#:   * 取"整个方法" ⇒ 寄存器**被重新赋值**后出现的无关 `if-*` 也被算进来，
#:     GATE 从 3 虚增到 6（实测）。
#: 正确做法：从 `move-result reg` 往后走，**遇到 reg 被重新写入就停**，
#: 停之前先看 reg 是被 `if-*` 消费（GATE）还是被 toString/append 消费（STAT）。
#: 这就是一个最小可用的"下一次定义"分析，足够回答"结果被谁消费"这一个问题。
_DEST_FIRST = re.compile(
    r'^\s*(?:move(?:-object|-wide|-result)?(?:/\w+)?|const(?:/[\w-]+)?|'
    r'new-instance|add-int|sub-int|mul-int|div-int|rem-int|xor-int|and-int|or-int|'
    r'shl-int|shr-int|ushr-int|neg-int|not-int|int-to-\w+|array-length|'
    r'instance-of|check-cast|aget|aput)\s+([vp]\d+)')
_DEST_LAST = re.compile(
    r'^\s*(?:iget[\w/-]*|sget[\w/-]*|move-result(?:-object|-wide)?)\s+.*?([vp]\d+)\s*$')


def _writes_reg(line, reg):
    """这条指令是否**写**了 `reg`（用于判定"上一次结果已经死了"）。"""
    m = _DEST_FIRST.match(line)
    if m and m.group(1) == reg:
        return True
    m = _DEST_LAST.match(line)
    if m and m.group(1) == reg:
        return True
    return False


def classify(root):
    """返回 [(相对路径, 行号, 类别)]。类别 ∈ {GATE, STAT, UNKNOWN}。"""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith('.smali'):
                continue
            path = os.path.join(dirpath, f)
            try:
                with open(path, encoding='utf-8', errors='replace') as fh:
                    lines = fh.read().splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines):
                if not CALL.search(ln):
                    continue
                reg = None
                for j in range(i + 1, min(i + 8, len(lines))):
                    m = MOVE.match(lines[j])
                    if m:
                        reg = m.group(1)
                        break
                if reg is None:
                    out.append((os.path.relpath(path, root), i + 1, 'UNKNOWN'))
                    continue
                kind = 'UNKNOWN'
                for j in range(i + 1, min(i + 400, len(lines))):
                    cur = lines[j]
                    stripped = cur.strip()
                    if not stripped or stripped.startswith('.') or stripped.startswith('#'):
                        continue                    # .line / .locals / 注释不影响数据流
                    if METHOD_END.match(cur):
                        break
                    if re.search(IF_ON.format(reg=re.escape(reg)), cur):
                        kind = 'GATE'
                        break
                    if 'Boolean;->toString' in cur or 'StringBuilder;->append' in cur:
                        kind = 'STAT'
                        break
                    # reg 被重新写入 ⇒ 上一次的结果已经死了，不再往后看
                    if _writes_reg(cur, reg) and 'move-result' not in cur:
                        break
                out.append((os.path.relpath(path, root), i + 1, kind))
    return out


@unittest.skipUnless(os.path.isdir(APK), 'work/apktool_out 不存在（未解码 APK）')
class VipCallSiteCensus(unittest.TestCase):
    # **`setUpClass` 而非 `setUp`**：`classify(APK)` 会扫全 APK 的 smali，
    # 单次约 13 秒。放在 `setUp` 里会按**测试方法**重复执行 ——
    # 这个类有 4 个方法 ⇒ 白跑 3 次（实测整个文件 54 秒，其中 40 秒是重复）。
    #
    # 为什么这不是"过早优化"：门禁从 35 秒涨到 146 秒后，人就会开始少跑它。
    # 一道"太慢所以懒得跑"的门禁，等于没有门禁。
    rows: list = []

    @classmethod
    def setUpClass(cls):
        cls.rows = classify(APK)

    def test_total_is_17(self):
        """调用点总数钉住。变了 ⇒ 宿主改了 VIP 判定，`vip_unlock` 要重新核。"""
        self.assertEqual(len(self.rows), 17,
                         f'aj.a.p() 调用点从 17 变成 {len(self.rows)}：'
                         '逐条重新归类，并更新 OPTIMIZATION §33.5')

    def test_exactly_three_are_real_gates(self):
        gates = [f'{p}:{n}' for p, n, k in self.rows if k == 'GATE']
        self.assertEqual(sorted(gates), [
            'smali_classes5/ai/c.smali:282',    # 7.9.0：旧 xi.c → 新 ai.c
            'smali_classes5/di/f.smali:2305',   # 7.9.0：旧 aj.f → 新 di.f（同一行）
            'smali_classes5/qi/d.smali:1038',   # 7.9.0：旧 oj.d → 新 qi.d
        ], '真闸门（结果决定控制流）的清单变了 —— vip_unlock 的作用面要重新表述')

    def test_rest_are_telemetry(self):
        """其余必须全部是打点，且**没有**未定性的。"""
        unknown = [f'{p}:{n}' for p, n, k in self.rows if k == 'UNKNOWN']
        self.assertEqual(unknown, [],
                         f'这些调用点无法归类（结果既没进 if-* 也没进 toString）: {unknown}')
        stat = sum(1 for _p, _n, k in self.rows if k == 'STAT')
        self.assertEqual(stat, 14, f'打点类应为 14，实际 {stat}')

    def test_no_gate_hides_behind_string_concat(self):
        """回归守卫：曾经把 3 个闸门误判成"全部打点"。

        断言"GATE 必须先于 STAT 被检查"——即只要同一处出现 `if-* r`，
        无论后面是否也拼了字符串，都必须算 GATE。用一个真实闸门验证。
        """
        a = [r for r in self.rows if r[0].endswith('di/f.smali')]
        self.assertEqual(len(a), 1, 'di/f 里应只有一处 p() 调用')
        self.assertEqual(a[0][2], 'GATE', 'di/f:2305 是早退闸门，不能被归成打点')


if __name__ == '__main__':
    unittest.main(verbosity=2)
