#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段二 · 关系引擎实测
====================
只断言行为（通过 / 被拒 / 查到 / 抓出），不核对打印文字。

口径：
  * 每个用例独立临时库，互不污染；
  * 被拒的写入必须连磁盘都不留痕（事务回滚），用例会复查边数；
  * 最后一个用例专门测「绕过 API 直插 SQL」的脏数据能否被 check 抓出——
    因为真实世界里，脏数据通常不是从API进来的，是从别处灌进来的。
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from relation_engine import Engine, Rejected  # noqa: E402

TYPES = os.path.join(ROOT, "rules", "relations.default.json")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "g.db")
        self.e = Engine(self.db)
        self.e.init_schema()
        self.e.load_types(TYPES)
        for eid, kind, label in [
            ("E1", "法人", "需求方A"),
            ("E2", "资源", "算力池B"),
            ("E3", "公共主体", "民生节点C"),
            ("E4", "法人", "中间商D"),
            ("E5", "资产", "标的物P"),
        ]:
            self.e.add_entity(eid, kind, label)

    def tearDown(self):
        self.e.close()

    def edge_count(self):
        return self.e.conn.execute("SELECT COUNT(*) c FROM edge").fetchone()["c"]


class TestConstraints(Base):
    def test_ownership_exclusive(self):
        self.e.add_edge("E1", "E5", "ownership", evidence="材料A p12")
        with self.assertRaises(Rejected):
            self.e.add_edge("E2", "E5", "ownership", evidence="材料B p3")
        self.assertEqual(self.edge_count(), 1, "被拒的边不得落库")

    def test_ownership_share_allowed(self):
        self.e.add_edge("E1", "E5", "ownership", weight=0.6)
        self.e.add_edge("E2", "E5", "ownership", weight=0.4)   # 份额共存：允许
        self.assertEqual(self.edge_count(), 2)
        with self.assertRaises(Rejected):                       # 再叠独占：拒
            self.e.add_edge("E3", "E5", "ownership")
        self.assertEqual(self.edge_count(), 2)

    def test_ownership_no_share_after_exclusive(self):
        self.e.add_edge("E1", "E5", "ownership")
        with self.assertRaises(Rejected):
            self.e.add_edge("E2", "E5", "ownership", weight=0.3)
        self.assertEqual(self.edge_count(), 1)

    def test_priority_cycle_rejected(self):
        self.e.add_edge("E1", "E2", "priority")
        self.e.add_edge("E2", "E3", "priority")
        with self.assertRaises(Rejected) as cm:
            self.e.add_edge("E3", "E1", "priority")
        self.assertIn("成环", str(cm.exception))
        self.assertEqual(self.edge_count(), 2)

    def test_compensation_requires_harm(self):
        with self.assertRaises(Rejected) as cm:
            self.e.add_edge("E1", "E2", "compensation", evidence="拟议补偿方案")
        self.assertIn("前置关系缺失", str(cm.exception))
        self.assertEqual(self.edge_count(), 0, "前置缺失时必须零落库")
        # 先落损害边，再补偿 → 通过
        self.e.add_edge("E1", "E2", "harm", evidence="材料C p7")
        self.e.add_edge("E1", "E2", "compensation", evidence="拟议补偿方案")
        self.assertEqual(self.edge_count(), 2)

    def test_compensation_wrong_pair_rejected(self):
        self.e.add_edge("E1", "E2", "harm")
        with self.assertRaises(Rejected):        # 损害对象不匹配
            self.e.add_edge("E3", "E2", "compensation")
        self.assertEqual(self.edge_count(), 1)

    def test_self_loop_rejected(self):
        with self.assertRaises(Rejected) as cm:
            self.e.add_edge("E1", "E1", "mutual_aid")
        self.assertIn("自环", str(cm.exception))

    def test_unknown_type_rejected(self):
        with self.assertRaises(Rejected) as cm:
            self.e.add_edge("E1", "E2", "no_such_type")
        self.assertIn("未注册", str(cm.exception))

    def test_unknown_entity_rejected(self):
        with self.assertRaises(Rejected):
            self.e.add_edge("E1", "E9", "trust")

    def test_duplicate_entity_rejected(self):
        with self.assertRaises(Rejected):
            self.e.add_entity("E1", "其他", "重复ID")

    def test_bad_kind_rejected(self):
        with self.assertRaises(Rejected):
            self.e.add_entity("E6", "外星人", "非法类别")


class TestQuery(Base):
    def test_neighbors_both_directions(self):
        self.e.add_edge("E1", "E2", "supply_demand")
        self.e.add_edge("E3", "E1", "allocation", weight=0.2)
        nb1 = self.e.neighbors("E1")
        self.assertEqual(len(nb1), 2)
        dirs = {n["dir"] for n in nb1}
        self.assertEqual(dirs, {"→", "←"})

    def test_path(self):
        self.e.add_edge("E1", "E2", "trust")
        self.e.add_edge("E2", "E3", "transfer")
        steps = self.e.path("E1", "E3")
        self.assertIsNotNone(steps)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["rtype"], "trust")
        self.assertEqual(steps[1]["to"], "E3")

    def test_path_none(self):
        self.e.add_edge("E1", "E2", "trust")
        self.assertIsNone(self.e.path("E1", "E5"))

    def test_expired_edge_invisible(self):
        self.e.add_edge("E1", "E2", "trust", valid_to="2000-01-01T00:00:00+08:00")
        self.assertEqual(self.e.neighbors("E1"), [])
        self.assertIsNone(self.e.path("E1", "E2"))


class TestDirtyData(Base):
    def test_check_catches_sql_injected_duplicate(self):
        """绕过 API 直插两条独占 ownership → check 必须抓出来。"""
        self.e.add_edge("E1", "E5", "ownership")
        self.e.conn.execute(
            "INSERT INTO edge(src,dst,rtype,weight,evidence,valid_from,valid_to,created_at)"
            " VALUES('E2','E5','ownership',NULL,NULL,NULL,NULL,'2026-11-22')")
        self.assertEqual(self.edge_count(), 2)
        probs = self.e.violations()
        self.assertTrue(len(probs) >= 1, "直插的重复独占边必须被 check 抓出")
        self.assertTrue(any("ownership" in p or "重复" in p for p in probs), probs)

    def test_check_catches_cycle(self):
        self.e.add_edge("E1", "E2", "priority")
        self.e.add_edge("E2", "E3", "priority")
        self.e.conn.execute(
            "INSERT INTO edge(src,dst,rtype,weight,evidence,valid_from,valid_to,created_at)"
            " VALUES('E3','E1','priority',NULL,NULL,NULL,NULL,'2026-11-22')")
        probs = self.e.violations()
        self.assertTrue(any("存在环" in p for p in probs), f"应当报出环，实际 {probs}")

    def test_check_clean_on_good_data(self):
        self.e.add_edge("E1", "E2", "supply_demand")
        self.e.add_edge("E1", "E2", "harm")
        self.e.add_edge("E1", "E2", "compensation")
        self.assertEqual(self.e.violations(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
