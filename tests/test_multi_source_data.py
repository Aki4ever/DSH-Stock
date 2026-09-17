#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多维数据采集模块自动化测试套件 (Test Multi-Source Data Adapters)
验证项目:
1. 防反爬会话与 Header 轮换
2. 历史前复权 K 线采集与结构验证
3. 十大股东与股东户数历史采集
4. 分红送配与除息排期
5. 巨潮官方公告与 PDF 直链
6. 大宗交易与席位异动透视
7. 网络异常或模拟降级处理
"""

import os
import sys
import unittest
from unittest.mock import patch

# 确保项目根目录在 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.data_sources.safe_session import AntiScrapingSession, safe_session
from scripts.data_sources.kline_adapter import KlineAdapter
from scripts.data_sources.shareholder_adapter import ShareholderAdapter
from scripts.data_sources.dividend_adapter import DividendAdapter
from scripts.data_sources.announcement_adapter import AnnouncementAdapter
from scripts.data_sources.block_trade_adapter import BlockTradeAdapter
from scripts.data_sources import StockDataHub


class TestMultiSourceDataAdapters(unittest.TestCase):

    def test_safe_session_headers_and_limit(self):
        """测试防反爬会话机制：UA轮换、Headers合法性与频控保护"""
        session = AntiScrapingSession(min_interval=0.01, max_interval=0.05)
        headers = session.build_headers(referer="http://test.com", is_json=True)
        self.assertIn("User-Agent", headers)
        self.assertIn("Mozilla", headers["User-Agent"])
        self.assertEqual(headers["Referer"], "http://test.com")
        self.assertIn("application/json", headers["Accept"])

    def test_kline_adapter(self):
        """测试历史日K线获取与字段对齐"""
        kline = KlineAdapter.get_daily_kline("600519", limit=5)
        if kline:
            item = kline[-1]
            self.assertIn("date", item)
            self.assertIn("open", item)
            self.assertIn("close", item)
            self.assertIn("volume", item)
            self.assertGreater(item["close"], 0.0)

    def test_shareholder_adapter(self):
        """测试十大股东与股东户数历史趋势获取"""
        res = ShareholderAdapter.get_top10_holders("600519", page_size=5)
        self.assertEqual(res["code"], "600519")
        if res.get("holders"):
            top1 = res["holders"][0]
            self.assertEqual(top1["rank"], 1)
            self.assertGreater(top1["hold_ratio"], 0.0)

        history = ShareholderAdapter.get_holder_count_history("600519", count=3)
        if history:
            h0 = history[0]
            self.assertIn("period", h0)
            self.assertIn("holder_num", h0)
            self.assertGreater(h0["holder_num"], 0)

    def test_dividend_adapter(self):
        """测试历年分红方案与实施进度获取"""
        divs = DividendAdapter.get_dividends("600519", page_size=3)
        if divs:
            d0 = divs[0]
            self.assertEqual(d0["code"], "600519")
            self.assertIn("plan_detail", d0)
            self.assertIn("progress", d0)

    def test_announcement_adapter(self):
        """测试巨潮官方公告接口与PDF直链"""
        notices = AnnouncementAdapter.get_announcements("600519", days=180, page_size=5)
        if notices:
            n0 = notices[0]
            self.assertEqual(n0["code"], "600519")
            self.assertTrue(len(n0["title"]) > 0)
            self.assertTrue(n0["pdf_url"].startswith("http://static.cninfo.com.cn/"))

    def test_block_trade_adapter(self):
        """测试大宗交易获取与折溢价计算"""
        trades = BlockTradeAdapter.get_stock_block_trades("600519", page_size=5)
        if trades:
            t0 = trades[0]
            self.assertEqual(t0["code"], "600519")
            self.assertIn("deal_price", t0)
            self.assertIn("premium_ratio", t0)
            self.assertIn("buyer", t0)

    def test_stock_data_hub_facade(self):
        """测试统一门面 StockDataHub"""
        holders = StockDataHub.get_holders("600519")
        self.assertIn("top10", holders)
        self.assertIn("history_count", holders)

    def test_adapter_resilience_on_network_failure(self):
        """测试当网络完全断开时各适配器的容灾降级鲁棒性"""
        with patch.object(safe_session, "get_json", return_value=None):
            with patch.object(safe_session, "post_json", return_value=None):
                self.assertEqual(KlineAdapter.get_daily_kline("600519"), [])
                self.assertEqual(DividendAdapter.get_dividends("600519"), [])
                self.assertEqual(AnnouncementAdapter.get_announcements("600519"), [])
                self.assertEqual(BlockTradeAdapter.get_stock_block_trades("600519"), [])
                h_res = ShareholderAdapter.get_top10_holders("600519")
                self.assertEqual(h_res["holders"], [])


if __name__ == "__main__":
    unittest.main()
