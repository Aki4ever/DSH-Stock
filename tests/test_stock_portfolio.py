#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资组合与风险预警自动化测试套件 (Test Stock Portfolio & Alerts)
映射需求: REQ-004
"""

import unittest
from unittest.mock import patch
from tests.market_fixtures import generate_mock_quote
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stock_portfolio import (
    PositionItem,
    PortfolioSummary,
    AlertMessage,
    load_config,
    build_portfolio_summary
)


class TestStockPortfolio(unittest.TestCase):
    """测试持仓收益率计算、组合市值权重与多维预警判定"""

    def test_position_item_pnl(self):
        # 盈利样本
        p1 = PositionItem(
            code="sh600519",
            name="贵州茅台",
            shares=100,
            cost_price=1500.0,
            current_price=1800.0,
            prev_close=1750.0
        )
        self.assertEqual(p1.market_value, 180000.0)
        self.assertEqual(p1.total_cost, 150000.0)
        self.assertEqual(p1.total_pnl, 30000.0)
        self.assertEqual(p1.total_pnl_pct, 20.0)
        self.assertEqual(p1.daily_pnl, 5000.0)

        # 亏损样本
        p2 = PositionItem(
            code="sz002594",
            name="比亚迪",
            shares=200,
            cost_price=300.0,
            current_price=240.0,
            prev_close=250.0
        )
        self.assertEqual(p2.total_pnl, -12000.0)
        self.assertEqual(p2.total_pnl_pct, -20.0)
        self.assertEqual(p2.daily_pnl, -2000.0)

    def test_portfolio_summary_weights(self):
        p1 = PositionItem("sh600519", "贵州茅台", 100, 1000.0, 1000.0, 1000.0)  # 市值 100,000
        p2 = PositionItem("sz300750", "宁德时代", 500, 200.0, 200.0, 200.0)     # 市值 100,000
        summary = PortfolioSummary([p1, p2])
        self.assertEqual(summary.total_market_value, 200000.0)
        self.assertEqual(summary.total_cost, 200000.0)
        self.assertEqual(p1.weight_pct, 50.0)
        self.assertEqual(p2.weight_pct, 50.0)

    def test_load_config(self):
        cfg = load_config()
        self.assertIn("watchlist", cfg)
        self.assertIn("portfolio", cfg)
        self.assertIn("alert_rules", cfg)
        self.assertGreater(len(cfg["watchlist"]), 0)

    # 以下用例一律使用隔离 fixture 底册，不依赖真实 config/stock_config.json 的内容——
    # 配置本就应该可以被改（例如清空占位持仓），测试不得因此失败。
    FIXTURE = {
        "portfolio_verified": True,
        "portfolio": [
            {"code": "sh600519", "name": "贵州茅台", "shares": 100, "cost_price": 1000.0, "buy_date": "2026-06-15"},
            {"code": "sz300750", "name": "宁德时代", "shares": 500, "cost_price": 200.0, "buy_date": "2026-07-20"},
        ],
        "alert_rules": {"take_profit_ratio": 0.20, "stop_loss_ratio": -0.08,
                        "daily_surge_ratio": 0.05, "daily_plunge_ratio": -0.05},
    }

    def test_build_portfolio_summary_and_alerts(self):
        cfg=dict(self.FIXTURE)
        with patch('scripts.stock_portfolio.load_config',return_value=cfg),patch('scripts.stock_portfolio.get_batch_quotes',return_value=[generate_mock_quote(p['code']) for p in cfg['portfolio']]):
            summary, alerts = build_portfolio_summary()
        self.assertGreater(summary.total_market_value, 0)
        self.assertGreater(len(summary.positions), 0)
        # 确认预警返回列表对象类型正确
        for a in alerts:
            self.assertIsInstance(a, AlertMessage)
            self.assertIn(a.level, ["INFO", "WARNING", "DANGER", "SUCCESS"])

    def test_unverified_positions_and_missing_prices_blocked(self):
        # 1. 已填持仓但未核实 → 拒绝
        cfg=dict(self.FIXTURE);cfg['portfolio_verified']=False
        with patch('scripts.stock_portfolio.load_config',return_value=cfg):
            with self.assertRaises(RuntimeError):build_portfolio_summary()
        # 2. 已核实但真实行情未获取 → 拒绝，且不得输出 0 盈亏
        cfg=dict(self.FIXTURE)
        with patch('scripts.stock_portfolio.load_config',return_value=cfg),patch('scripts.stock_portfolio.get_batch_quotes',return_value=[]):
            with self.assertRaises(RuntimeError):build_portfolio_summary()

    def test_empty_portfolio_is_refused_without_zero_totals(self):
        # 空底册必须拒绝：绝不能输出「共 0 只持仓 / ¥0.00」这种会被读成组合价值为 0 的结果
        cfg={"portfolio": [], "portfolio_verified": False, "alert_rules": {}}
        with patch('scripts.stock_portfolio.load_config',return_value=cfg):
            with self.assertRaises(RuntimeError) as ctx:
                build_portfolio_summary()
        self.assertIn("持仓底册为空", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
