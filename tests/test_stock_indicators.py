#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标与量化评分引擎自动化测试套件 (Test Stock Indicators & Scoring)
映射需求: REQ-003
"""

import unittest
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stock_data_engine import generate_mock_kline
from scripts.stock_indicators import (
    calculate_ma,
    calculate_ema,
    calculate_macd,
    calculate_rsi,
    calculate_boll,
    calculate_kdj,
    evaluate_stock
)


class TestStockIndicators(unittest.TestCase):
    """验证经典技术指标数学公式与 100 分制多空模型"""

    def test_calculate_ma(self):
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
        ma3 = calculate_ma(prices, 3)
        self.assertIsNone(ma3[0])
        self.assertIsNone(ma3[1])
        self.assertAlmostEqual(ma3[2], 11.0)
        self.assertAlmostEqual(ma3[3], 12.0)
        self.assertAlmostEqual(ma3[4], 13.0)
        self.assertAlmostEqual(ma3[5], 14.0)

    def test_calculate_ema(self):
        prices = [10.0, 12.0, 14.0, 16.0]
        ema = calculate_ema(prices, 3)
        self.assertEqual(len(ema), 4)
        self.assertEqual(ema[0], 10.0)
        self.assertGreater(ema[-1], ema[0])

    def test_calculate_macd(self):
        prices = [float(i) for i in range(1, 40)]
        dif, dea, bar = calculate_macd(prices, 12, 26, 9)
        self.assertEqual(len(dif), len(prices))
        self.assertEqual(len(dea), len(prices))
        self.assertEqual(len(bar), len(prices))
        # 持续单边上涨序列，MACD 柱应为正向
        self.assertGreater(dif[-1], 0)

    def test_calculate_rsi(self):
        prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
        rsi6 = calculate_rsi(prices, 6)
        self.assertEqual(len(rsi6), len(prices))
        # 连续上涨无下跌，RSI-6 应达到 100
        self.assertEqual(rsi6[-1], 100.0)

    def test_calculate_boll(self):
        prices = [20.0 + (i % 5) for i in range(30)]
        upper, mid, lower = calculate_boll(prices, 20, 2.0)
        self.assertEqual(len(upper), len(prices))
        last_u = upper[-1]
        last_m = mid[-1]
        last_l = lower[-1]
        self.assertIsNotNone(last_u)
        self.assertIsNotNone(last_m)
        self.assertIsNotNone(last_l)
        self.assertGreater(last_u, last_m)
        self.assertGreater(last_m, last_l)

    def test_calculate_kdj(self):
        bars = generate_mock_kline("600519", days=20, end_price=1600.0)
        k, d, j = calculate_kdj(bars)
        self.assertEqual(len(k), 20)
        self.assertEqual(len(d), 20)
        self.assertEqual(len(j), 20)
        for val in k:
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 100.0)

    def test_evaluate_stock_scoring(self):
        """测试 100 分制综合评分、评级区间与操作指引输出"""
        bars = generate_mock_kline("600519", days=60, end_price=1680.0)
        rep = evaluate_stock("sh600519", "贵州茅台", bars)
        self.assertGreaterEqual(rep.score, 0.0)
        self.assertLessEqual(rep.score, 100.0)
        self.assertIn("分", f"{rep.score}分")
        self.assertTrue(len(rep.grade) > 0)
        self.assertTrue(len(rep.action) > 0)
        self.assertTrue(len(rep.signals) > 0)
        # 验证各维度子得分
        dims = rep.dimension_scores
        self.assertIn("trend", dims)
        self.assertIn("momentum", dims)
        self.assertIn("support", dims)
        self.assertIn("volatility", dims)


if __name__ == "__main__":
    unittest.main()
