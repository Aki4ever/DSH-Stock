# -*- coding: utf-8 -*-
"""
R09 (REQ-046) 单测：顶栏「行情日期」精确到分的数据链路。

覆盖：
  1. parse_quote_timestamp：14 位来源时间戳 → 精确到分；8 位 → 如实降级为「日」；不可解析 → None（前端显示未获取）
  2. current_quote_datetime：取全部标的中最新的来源时间戳；无任何时间戳时返回 None
  3. resolve_data_caliber：新增 quote_datetime 字段，且与「数据库基准批次」snapshot_date 两个口径互不冒充

全部为构造数据，不触网、不写产品库。
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DSH_DISABLE_BACKGROUND", "1")

from scripts import stock_web_server as srv


class QuoteTimestampParseTests(unittest.TestCase):
    """REQ-046: 来源时间戳解析口径"""

    def test_fourteen_digits_is_minute_precision(self):
        parsed = srv.parse_quote_timestamp("20260923153400")
        self.assertEqual(parsed["date"], "2026-09-23")
        self.assertEqual(parsed["time"], "15:34")
        self.assertEqual(parsed["datetime"], "2026-09-23 15:34")
        self.assertEqual(parsed["display"], "2026年9月23日 15:34")
        self.assertEqual(parsed["precision"], "minute")
        self.assertEqual(parsed["raw"], "20260923153400")

    def test_twelve_digits_is_minute_precision(self):
        parsed = srv.parse_quote_timestamp("202609230935")
        self.assertEqual(parsed["time"], "09:35")
        self.assertEqual(parsed["precision"], "minute")

    def test_eight_digits_degrades_to_day_without_inventing_time(self):
        parsed = srv.parse_quote_timestamp("20260923")
        self.assertEqual(parsed["date"], "2026-09-23")
        self.assertIsNone(parsed["time"])
        self.assertEqual(parsed["datetime"], "2026-09-23")
        self.assertEqual(parsed["display"], "2026年9月23日")
        self.assertEqual(parsed["precision"], "day")

    def test_separator_form_is_accepted(self):
        parsed = srv.parse_quote_timestamp("2026-09-23 15:34:00")
        self.assertEqual(parsed["datetime"], "2026-09-23 15:34")
        self.assertEqual(parsed["precision"], "minute")

    def test_unparsable_returns_none_never_falls_back_to_local_clock(self):
        for value in ("", None, "bad", "1234", "-"):
            self.assertIsNone(srv.parse_quote_timestamp(value), f"{value!r} 必须解析为 None")


def _manager(stamps):
    """构造只带 timestamp 的 DATA_MANAGER 替身"""
    return type("M", (), {"stocks_dict": {f"s{i}": {"timestamp": t} for i, t in enumerate(stamps)}})()


class CurrentQuoteDatetimeTests(unittest.TestCase):
    """REQ-046: 取最新真实快照时间，缺失即 None"""

    def test_picks_latest_stamp(self):
        with patch.object(srv, "DATA_MANAGER", _manager(["20260918161436", "20260923153400", "20260923161500"])):
            parsed = srv.current_quote_datetime()
        self.assertEqual(parsed["datetime"], "2026-09-23 16:15")
        self.assertEqual(parsed["precision"], "minute")

    def test_no_timestamp_returns_none(self):
        with patch.object(srv, "DATA_MANAGER", _manager([])):
            self.assertIsNone(srv.current_quote_datetime())
        with patch.object(srv, "DATA_MANAGER", _manager([None, ""])):
            self.assertIsNone(srv.current_quote_datetime())

    def test_date_only_source_stays_day_precision(self):
        with patch.object(srv, "DATA_MANAGER", _manager(["20260923"])):
            parsed = srv.current_quote_datetime()
        self.assertEqual(parsed["precision"], "day")
        self.assertIsNone(parsed["time"])


class DataCaliberTests(unittest.TestCase):
    """REQ-046 / REQ-017: 真实行情时间与基准批次日期必须分别暴露，互不冒充"""

    def test_caliber_exposes_quote_datetime(self):
        baseline = {"id": 13, "task_id": "crawl_test", "crawl_date": "2026-09-23 21:43:39",
                    "status": "成功(真实行情全量)", "fingerprint": "x", "target_scope": "已收录A股",
                    "total_items": 4601, "updated_items": 4601, "skipped_items": 0,
                    "details": "", "is_baseline": 1}
        with patch.object(srv, "DATA_MANAGER", _manager(["20260923153400"])), \
             patch("scripts.stock_db.ensure_crawl_baseline", return_value=baseline):
            caliber = srv.resolve_data_caliber()
        self.assertEqual(caliber["quote_datetime"]["datetime"], "2026-09-23 15:34")
        self.assertEqual(caliber["quote_date"], "2026-09-23")
        self.assertEqual(caliber["snapshot_date"], "2026-09-23")
        self.assertEqual(caliber["snapshot_source"], "baseline")

    def test_caliber_quote_datetime_is_none_when_no_snapshot(self):
        baseline = {"id": 13, "task_id": "crawl_test", "crawl_date": "2026-09-23 21:43:39",
                    "status": "成功(真实行情全量)", "fingerprint": "x", "target_scope": "已收录A股",
                    "total_items": 4601, "updated_items": 4601, "skipped_items": 0,
                    "details": "", "is_baseline": 1}
        with patch.object(srv, "DATA_MANAGER", _manager([])), \
             patch("scripts.stock_db.ensure_crawl_baseline", return_value=baseline):
            caliber = srv.resolve_data_caliber()
        self.assertIsNone(caliber["quote_datetime"])
        self.assertIsNone(caliber["quote_date"])
        # 基准日期照旧存在：行情时间缺失不得改写基准口径
        self.assertEqual(caliber["snapshot_date"], "2026-09-23")


if __name__ == "__main__":
    unittest.main()
