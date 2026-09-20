"""R03 回归 (REQ-016/017)：数据中心多选删除与数据库基准。

所有构造数据仅写入隔离的临时数据库，绝不触碰产品库 data/stock_database.db。
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import stock_db


class DataCenterBaselineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = str(Path(self._tmp.name) / "isolated.db")
        self._patcher = patch.object(stock_db, "DB_PATH", self.db_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self._data_patcher = patch.object(stock_db, "DATA_DIR", self._tmp.name)
        self._data_patcher.start()
        self.addCleanup(self._data_patcher.stop)
        stock_db.init_db()

    def _record(self, task_id, status, crawl_date="2026-09-20 10:00:00"):
        return stock_db.record_crawl_audit(
            task_id=task_id, crawl_date=crawl_date, status=status,
            fingerprint=f"fp-{task_id}", target_scope="已收录前100只",
            total_items=100, updated_items=100, skipped_items=0, details="测试批次"
        )

    # ---------- REQ-017 数据基准 ----------

    def test_successful_real_quote_batch_becomes_baseline_automatically(self):
        self.assertIsNone(stock_db.get_crawl_baseline())
        self._record("t1", "成功(真实行情全量)")
        first = stock_db.get_crawl_baseline()
        self.assertIsNotNone(first)
        self.assertEqual(first["task_id"], "t1")

        # 再抓一次 → 基准自动前移到最新批次，且全局唯一
        self._record("t2", "成功(真实行情全量)")
        second = stock_db.get_crawl_baseline()
        self.assertEqual(second["task_id"], "t2")
        baseline_rows = [r for r in stock_db.list_crawl_audit_records(limit=50) if r.get("is_baseline")]
        self.assertEqual(len(baseline_rows), 1)

    def test_partial_and_cancelled_batches_never_become_baseline(self):
        self._record("legacy", "成功(指纹一致/免抓)")
        self._record("partial", "部分覆盖(真实行情未获取完整)")
        self._record("cancel", "用户手动取消(真实行情部分获取)")
        self.assertIsNone(stock_db.get_crawl_baseline())

    def test_manual_switch_persists_and_rejects_ineligible_records(self):
        self._record("ok1", "成功(真实行情全量)")
        legacy_id = self._record("legacy", "成功(指纹一致/免抓)")
        ok2_id = self._record("ok2", "成功(真实行情全量)")

        # 手动切回较早的合规批次
        ok1_id = [r["id"] for r in stock_db.list_crawl_audit_records(limit=50) if r["task_id"] == "ok1"][0]
        success, message, record = stock_db.set_crawl_baseline(ok1_id)
        self.assertTrue(success, message)
        self.assertEqual(stock_db.get_crawl_baseline()["task_id"], "ok1")

        # 旧版未核验日志被拒绝，且原基准保持不变
        success, message, record = stock_db.set_crawl_baseline(legacy_id)
        self.assertFalse(success)
        self.assertIn("不能作为数据库基准", message)
        self.assertEqual(stock_db.get_crawl_baseline()["task_id"], "ok1")

        # 不存在的记录被拒绝
        success, message, _ = stock_db.set_crawl_baseline(999999)
        self.assertFalse(success)
        self.assertEqual(stock_db.get_crawl_baseline()["task_id"], "ok1")

        self.assertTrue(stock_db.set_crawl_baseline(ok2_id)[0])

    def test_ensure_baseline_backfills_latest_eligible_without_fabricating(self):
        # 无任何合规批次 → 不回退、不伪造
        self._record("legacy", "成功(指纹一致/免抓)")
        self.assertIsNone(stock_db.ensure_crawl_baseline())

        self._record("ok1", "成功(真实行情全量)")
        self._record("ok2", "成功(真实行情全量)")
        self.assertEqual(stock_db.ensure_crawl_baseline()["task_id"], "ok2")
        # 已有基准时保持稳定，不被重复写入改变
        self.assertEqual(stock_db.ensure_crawl_baseline()["task_id"], "ok2")

    # ---------- REQ-016 多选删除 ----------

    def test_delete_removes_only_requested_audit_rows(self):
        ids = [self._record(f"t{i}", "成功(指纹一致/免抓)") for i in range(4)]
        outcome = stock_db.delete_crawl_audit_records([ids[0], ids[2]])
        self.assertEqual(outcome["deleted"], sorted([ids[0], ids[2]]))
        remaining = {r["id"] for r in stock_db.list_crawl_audit_records(limit=50)}
        self.assertEqual(remaining, {ids[1], ids[3]})

    def test_baseline_record_is_protected_from_deletion(self):
        self._record("t1", "成功(真实行情全量)")
        baseline = stock_db.get_crawl_baseline()
        other = self._record("t2", "成功(指纹一致/免抓)")

        outcome = stock_db.delete_crawl_audit_records([baseline["id"], other])
        self.assertEqual(outcome["deleted"], [other])
        self.assertEqual([p["id"] for p in outcome["protected"]], [baseline["id"]])
        self.assertEqual(stock_db.get_crawl_baseline()["id"], baseline["id"])

    def test_delete_tolerates_missing_and_invalid_ids(self):
        kept = self._record("t1", "成功(指纹一致/免抓)")
        outcome = stock_db.delete_crawl_audit_records([999999, "abc", None, kept])
        self.assertEqual(outcome["deleted"], [kept])
        self.assertEqual(len(outcome["skipped"]), 1)
        self.assertEqual(outcome["skipped"][0]["id"], 999999)

        empty = stock_db.delete_crawl_audit_records([])
        self.assertEqual(empty["deleted"], [])
        self.assertIn("未提供有效的记录ID", empty["reason"])

    def test_delete_never_touches_business_data_tables(self):
        """删除审计流水绝不能联动删除行情/K线等业务数据。"""
        with stock_db.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO stocks_master (code, raw_code, name, market, market_code, board, board_code)
                VALUES ('sh600519','600519','贵州茅台','sh','sh','main','main');
            """)
            conn.execute("""
                INSERT INTO stock_daily_kline (code, date, open, close, high, low, volume, amount_yi, change_pct, created_at)
                VALUES ('sh600519','2026-09-18',10,11,12,9,100,1.5,1.0,'2026-09-18 15:00:00');
            """)
            conn.commit()

        rid = self._record("t1", "成功(指纹一致/免抓)")
        stock_db.delete_crawl_audit_records([rid])

        with stock_db.get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM stocks_master;").fetchone()["c"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM stock_daily_kline;").fetchone()["c"], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM crawl_audit_records;").fetchone()["c"], 0)

    def test_is_baseline_column_migrates_onto_legacy_schema(self):
        """旧库(无 is_baseline 列)升级后必须可用，且历史日志不被擅自提升为基准。"""
        with TemporaryDirectory() as legacy_dir:
            legacy_path = str(Path(legacy_dir) / "legacy.db")
            import sqlite3
            conn = sqlite3.connect(legacy_path)
            conn.execute("""
                CREATE TABLE crawl_audit_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, crawl_date TEXT NOT NULL,
                    status TEXT NOT NULL, fingerprint TEXT NOT NULL, target_scope TEXT DEFAULT '',
                    total_items INTEGER DEFAULT 0, updated_items INTEGER DEFAULT 0, skipped_items INTEGER DEFAULT 0,
                    details TEXT DEFAULT '', created_at TEXT DEFAULT ''
                );
            """)
            conn.execute("""
                INSERT INTO crawl_audit_records (task_id, crawl_date, status, fingerprint)
                VALUES ('old1','2026-09-19 10:00:00','成功(指纹一致/免抓)','fpx');
            """)
            conn.commit()
            conn.close()

            with patch.object(stock_db, "DB_PATH", legacy_path), patch.object(stock_db, "DATA_DIR", legacy_dir):
                stock_db.init_db()
                with stock_db.get_db_connection() as c2:
                    cols = {r["name"] for r in c2.execute("PRAGMA table_info(crawl_audit_records);").fetchall()}
                self.assertIn("is_baseline", cols)
                self.assertIsNone(stock_db.get_crawl_baseline())


if __name__ == "__main__":
    unittest.main()
