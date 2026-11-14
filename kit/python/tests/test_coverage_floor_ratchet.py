#!/usr/bin/env python3
"""
Offline tests: ㉦ 的下限必须是"棘轮"（历史最大值），不是一张静态表。

Why this file exists
--------------------
2026-11-09 实测：`FLOORS['python 测试'] = 487`，而套件实际 **499** 条。
于是"删掉一条测试"在 ㉖ 的负对照里**仍然是绿的** —— 有 12 条的余量可以无声消失。

而 ㉦ 存在的唯一理由就是：**变红会叫人，变绿也会叫人，只有"少了一个数"不叫人**。
一张静态表天生会松：每加一条测试就多一格余量。所以下限取 `max(FLOORS, 基线)`，
基线由门禁自己往上棘轮（只升不降）；负对照期间**不写**（临时删掉的条数不许变成新基线）。

判据提成纯函数 `decide()` 就是为了这里能测，而不必跑 150 秒的套件。

Run:

    python3 -m unittest discover -s kit/python/tests -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, '..', '..', 'scripts', 'check_coverage_floors.py')


def _tool():
    spec = importlib.util.spec_from_file_location('check_coverage_floors', TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class RatchetDecide(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.t = _tool()

    def test_deletion_below_baseline_is_red(self):
        """基线 130、现在 129 ⇒ 红（这正是"删掉一条测试"必须被抓到的形状）。"""
        bad, raised = self.t.decide({'python 测试': 129},
                                    {'python 测试': 100}, {'python 测试': 130})
        self.assertEqual(bad, [('python 测试', 129, 130)])
        self.assertEqual(raised, {})

    def test_growth_raises_baseline(self):
        """长到 140 ⇒ 不是红，而是把基线抬到 140。"""
        bad, raised = self.t.decide({'python 测试': 140},
                                    {'python 测试': 100}, {'python 测试': 130})
        self.assertEqual(bad, [])
        self.assertEqual(raised, {'python 测试': 140})

    def test_slack_above_static_floor_is_closed_by_baseline(self):
        """静态下限 487、基线 499、现在 498 ⇒ 红（静态表的那段余量被基线关掉）。"""
        bad, _ = self.t.decide({'python 测试': 498}, {'python 测试': 487},
                               {'python 测试': 499})
        self.assertEqual(bad, [('python 测试', 498, 499)])

    def test_no_baseline_falls_back_to_static_floor(self):
        """没有基线（新克隆）⇒ 退回静态下限，至少不假装更严。"""
        bad, raised = self.t.decide({'python 测试': 490}, {'python 测试': 489}, {})
        self.assertEqual(bad, [])
        self.assertEqual(raised, {'python 测试': 490})

    def test_negctl_is_detected_from_env(self):
        """`in_negctl()` 必须认 `KD_NEGCTL=1` —— 否则负对照会把自己的临时条数写成新基线。"""
        old = os.environ.get('KD_NEGCTL')
        try:
            os.environ['KD_NEGCTL'] = '1'
            self.assertTrue(self.t.in_negctl())
            os.environ.pop('KD_NEGCTL', None)
            self.assertFalse(self.t.in_negctl())
        finally:
            if old is None:
                os.environ.pop('KD_NEGCTL', None)
            else:
                os.environ['KD_NEGCTL'] = old


class BaselineWritesAreMonotonic(unittest.TestCase):
    """**写盘这一处**必须兜住"只升不降"（2026-11-09 04:30 实测基线被写成 504，
    而真实条数 508 —— 那个 504 是在另一条链的注入窗口里算出来的）。

    基线被压低 ⇒ 有 4 条测试可以悄悄删掉而 ㉦ 全绿，而且它**看起来是绿的**。
    `decide()` 的"只升不降"只是口头承诺：真正的兜底要在 `write_baseline()`。
    """

    def setUp(self):
        import tempfile
        self.t = _tool()
        self.dir = tempfile.mkdtemp(prefix='floor-baseline-')
        self.path = os.path.join(self.dir, '.coverage_baseline.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_lower_value_is_rejected(self):
        """已记录 510，写 504 ⇒ 文件仍是 510（低值写不进来）。"""
        self.t.write_baseline({'python 测试': 510}, self.path)
        merged = self.t.write_baseline({'python 测试': 504}, self.path)
        self.assertEqual(merged['python 测试'], 510)
        self.assertEqual(self.t.read_baseline(self.path)['python 测试'], 510)

    def test_higher_value_is_accepted(self):
        """已记录 500，写 510 ⇒ 抬上去（棘轮正常转动）。"""
        self.t.write_baseline({'python 测试': 500}, self.path)
        merged = self.t.write_baseline({'python 测试': 510}, self.path)
        self.assertEqual(merged['python 测试'], 510)
        self.assertEqual(self.t.read_baseline(self.path)['python 测试'], 510)

    def test_other_keys_are_preserved(self):
        """只写一个键时，别的键不许被抹掉（曾经 `base.update` 差点整体覆盖）。"""
        self.t.write_baseline({'python 测试': 500, '负对照': 48}, self.path)
        merged = self.t.write_baseline({'python 测试': 510}, self.path)
        self.assertEqual(merged['负对照'], 48)

    def test_inflight_marker_is_recognised(self):
        """跨进程标记：`work/.negctl.inflight` 里 pid 活着 ⇒ 认为"正在跑"。"""
        import json
        marker = os.path.join(self.dir, '.negctl.inflight')
        with open(marker, 'w', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'started': 0, 'cases': ['x'], 'paths': []}, f)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            '_st', os.path.join(HERE, '..', '..', 'python', 'negctl_state.py'))
        st = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(st)
        self.assertIsNotNone(st.active_pid(marker), '活着的 pid 应被认成"正在跑"')
        dead = os.path.join(self.dir, '.dead.json')
        with open(dead, 'w', encoding='utf-8') as f:
            json.dump({'pid': 999999999, 'started': 0, 'cases': ['x'], 'paths': []}, f)
        self.assertIsNone(st.active_pid(dead), '不存在的 pid 应被认成"不在跑"')

if __name__ == '__main__':
    unittest.main()
