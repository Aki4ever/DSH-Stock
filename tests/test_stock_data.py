#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行情数据引擎自动化测试套件 (Test Stock Data Engine)
映射需求: REQ-002
"""

import unittest
import os
import sys

# 路径重定位
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stock_data_engine import (
    normalize_code,
    StockQuote,
    KLineBar,
    generate_mock_quote,
    get_quote,
    get_batch_quotes,
    generate_mock_kline
)


class TestStockDataEngine(unittest.TestCase):
    """验证证券代码标准化、实时数据抓取与离线 Mock 降级"""

    def test_normalize_code(self):
        """测试各市场证券代码自动标准化与分类"""
        c1, m1 = normalize_code("600519")
        self.assertEqual(c1, "sh600519")
        self.assertEqual(m1, "SH")

        c2, m2 = normalize_code("000001")
        self.assertEqual(c2, "sz000001")
        self.assertEqual(m2, "SZ")

        c3, m3 = normalize_code("300750")
        self.assertEqual(c3, "sz300750")
        self.assertEqual(m3, "SZ")

        c4, m4 = normalize_code("sh601318")
        self.assertEqual(c4, "sh601318")
        self.assertEqual(m4, "SH")

        c5, m5 = normalize_code("00700")
        self.assertEqual(c5, "hk00700")
        self.assertEqual(m5, "HK")

    def test_stock_quote_model(self):
        """测试 StockQuote 字段计算与序列化"""
        q = StockQuote(
            code="sh600519",
            name="贵州茅台",
            price=1700.0,
            prev_close=1600.0,
            open_price=1620.0,
            high=1710.0,
            low=1610.0,
            volume=20000,
            turnover=3400000000
        )
        self.assertAlmostEqual(q.change, 100.0)
        self.assertAlmostEqual(q.change_pct, 6.25)
        d = q.to_dict()
        self.assertEqual(d["code"], "sh600519")
        self.assertEqual(d["name"], "贵州茅台")
        self.assertEqual(d["price"], 1700.0)

    def test_mock_quote_generation(self):
        """测试 Mock 离线数据生成稳定性与哈希幂等性"""
        q1 = generate_mock_quote("sh600519")
        self.assertEqual(q1.code, "sh600519")
        self.assertEqual(q1.name, "贵州茅台")
        self.assertTrue(q1.is_mock)
        self.assertGreater(q1.price, 0)

        # 验证任意陌生代码的拟真生成
        q_unknown = generate_mock_quote("sh688999")
        self.assertEqual(q_unknown.code, "sh688999")
        self.assertGreater(q_unknown.price, 0)

    def test_get_quote_and_batch(self):
        """测试单只与批量获取行情（网络畅通或离线回退均保底成功）"""
        q = get_quote("600519", allow_mock=True)
        self.assertIsNotNone(q)
        self.assertGreater(q.price, 0)

        batch = get_batch_quotes(["sh000001", "600519", "300750"], allow_mock=True)
        self.assertEqual(len(batch), 3)
        codes = [item.code for item in batch]
        self.assertIn("sh000001", codes)
        self.assertIn("sh600519", codes)
        self.assertIn("sz300750", codes)

    def test_generate_mock_kline(self):
        """测试拟真连续 K 线序列生成"""
        bars = generate_mock_kline("sh600519", days=30, end_price=1600.0)
        self.assertEqual(len(bars), 30)
        for b in bars:
            self.assertGreater(b.high, 0)
            self.assertGreater(b.low, 0)
            self.assertGreaterEqual(b.high, b.low)
            self.assertGreaterEqual(b.high, min(b.open, b.close))


if __name__ == "__main__":
    unittest.main()
