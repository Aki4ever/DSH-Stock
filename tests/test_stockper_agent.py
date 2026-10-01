#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent stockper 专属单元测试套件
验证范围:
1. 知识库结构与五大维度字段完整性
2. 维度别名归一化逻辑
3. 横向对比报告 Markdown 生成契约
4. 问询推荐意图解析与渠道推荐输出
5. 五大维度真实数据抓取调度与聚合计算 (十大流通股东合计占比等)
"""

import unittest
import sys
import os

# 路径对齐
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.stockper_agent import StockperAgent, STOCKPER_KNOWLEDGE_BASE


class TestStockperAgent(unittest.TestCase):
    """Stockper Agent 核心功能与数据调度测试"""

    def setUp(self):
        self.agent = StockperAgent()

    def test_01_knowledge_base_integrity(self):
        """测试知识库完整性：五大维度必须全部存在且字段完备"""
        expected_dims = ["block_trade", "shareholders", "dividend", "kline", "finance"]
        for dim in expected_dims:
            self.assertIn(dim, STOCKPER_KNOWLEDGE_BASE, f"知识库缺失核心维度: {dim}")
            dim_info = STOCKPER_KNOWLEDGE_BASE[dim]
            self.assertTrue(dim_info.get("dimension_name"), f"{dim} 缺失 dimension_name")
            self.assertTrue(dim_info.get("official_authority"), f"{dim} 缺失 official_authority")
            self.assertTrue(dim_info.get("recommended_channel"), f"{dim} 缺失 recommended_channel")
            
            channels = dim_info.get("channels", [])
            self.assertGreaterEqual(len(channels), 2, f"{dim} 的渠道数量应不少于2个")
            
            has_recommended = False
            for ch in channels:
                self.assertIn("name", ch)
                self.assertIn("interface", ch)
                self.assertIn("fetched_info", ch)
                self.assertIn("validity", ch)
                self.assertIn("risks", ch)
                self.assertIn("advantages", ch)
                self.assertIn("disadvantages", ch)
                if ch.get("recommended"):
                    has_recommended = True
            self.assertTrue(has_recommended, f"{dim} 必须标注至少一个 recommended 首选工程渠道")

    def test_02_dimension_normalization(self):
        """测试自然语言与中英文维度归一化"""
        self.assertEqual(self.agent.normalize_dimension("大宗交易"), "block_trade")
        self.assertEqual(self.agent.normalize_dimension("大宗"), "block_trade")
        self.assertEqual(self.agent.normalize_dimension("十大流通股东占比"), "shareholders")
        self.assertEqual(self.agent.normalize_dimension("股东"), "shareholders")
        self.assertEqual(self.agent.normalize_dimension("分红"), "dividend")
        self.assertEqual(self.agent.normalize_dimension("除权除息"), "dividend")
        self.assertEqual(self.agent.normalize_dimension("K线图"), "kline")
        self.assertEqual(self.agent.normalize_dimension("日K"), "kline")
        self.assertEqual(self.agent.normalize_dimension("财务报表"), "finance")
        self.assertEqual(self.agent.normalize_dimension("财报"), "finance")
        self.assertIsNone(self.agent.normalize_dimension("比特币期货"))

    def test_03_get_comparison_report(self):
        """测试横向对比报告生成"""
        report_all = self.agent.get_comparison()
        self.assertIn("# 📊 A股核心信息公开抓取渠道权威度与横向对比表", report_all)
        self.assertIn("大宗交易", report_all)
        self.assertIn("十大流通股东占比", report_all)
        self.assertIn("分红送配", report_all)
        self.assertIn("K线图行情", report_all)
        self.assertIn("财务报表", report_all)

        report_single = self.agent.get_comparison("block_trade")
        self.assertIn("维度：大宗交易", report_single)
        self.assertNotIn("维度：财务报表", report_single)

    def test_04_ask_recommendations(self):
        """测试问询应答推荐引擎"""
        res = self.agent.ask("大宗交易从哪里获取更权威？")
        self.assertIn("block_trade", res["matched_dimensions"])
        self.assertEqual(len(res["recommendations"]), 1)
        rec = res["recommendations"][0]
        self.assertEqual(rec["dimension"], "block_trade")
        self.assertIn("上海证券交易所", rec["official_authority"])
        self.assertIn("东方财富数据中心", rec["recommended_channel"])
        self.assertIn("RPT_DATA_BLOCKTRADE", rec["recommended_interface"])

    def test_05_ask_with_stock_code_and_fetch(self):
        """测试带股票代码的问询，自动负责调用真实数据获取"""
        res = self.agent.ask("请问 600519 的十大流通股东去哪里获取更权威，并获取最新占比？")
        self.assertEqual(res["detected_code"], "600519")
        self.assertIn("shareholders", res["matched_dimensions"])
        self.assertIsNotNone(res["fetched_data"])
        self.assertIn("shareholders", res["fetched_data"])
        sh_data = res["fetched_data"]["shareholders"]
        self.assertEqual(sh_data["code"], "600519")
        self.assertGreater(sh_data["top10_total_ratio"], 50.0) # 茅台前十大流通股东占比超50%
        self.assertGreaterEqual(len(sh_data["holders"]), 5)

    def test_06_fetch_block_trade_data(self):
        """测试大宗交易数据抓取与字段映射"""
        data = self.agent.fetch_data("block_trade", "600519", limit=3)
        self.assertEqual(data["dimension"], "block_trade")
        self.assertEqual(data["code"], "600519")
        self.assertIn("records", data)
        self.assertIn("summary", data)
        if data["records"]:
            first = data["records"][0]
            self.assertIn("trade_date", first)
            self.assertIn("deal_price", first)
            self.assertIn("premium_ratio", first)

    def test_07_fetch_dividend_data(self):
        """测试分红送配数据抓取与字段映射"""
        data = self.agent.fetch_data("dividend", "600519", limit=3)
        self.assertEqual(data["dimension"], "dividend")
        self.assertEqual(data["code"], "600519")
        self.assertIn("records", data)
        if data["records"]:
            first = data["records"][0]
            self.assertIn("plan_detail", first)
            self.assertIn("report_period", first)

    def test_08_fetch_kline_data(self):
        """测试K线行情数据抓取与字段映射"""
        data = self.agent.fetch_data("kline", "600519", limit=5)
        self.assertEqual(data["dimension"], "kline")
        self.assertEqual(data["adjust_type"], "qfq")
        self.assertGreaterEqual(data["bar_count"], 1)
        latest = data["latest_kline"]
        self.assertTrue(latest.get("close") is not None)
        self.assertTrue(latest.get("date") is not None)

    def test_09_fetch_finance_data(self):
        """测试财务报表数据抓取与三张表字段映射"""
        data = self.agent.fetch_data("finance", "600519")
        self.assertEqual(data["dimension"], "finance")
        self.assertIn("income_statement", data)
        self.assertIn("balance_sheet", data)
        self.assertIn("cash_flow_statement", data)
        self.assertTrue(len(data.get("report_periods", [])) > 0)


if __name__ == "__main__":
    unittest.main()
