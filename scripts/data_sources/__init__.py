#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票多维数据中心统一门面 (Unified Stock Data Hub)
版本: v1.0.0
整合五大维度：
1. 实时行情与历史日K (腾讯/东财/PyTDX)
2. 股东信息与户数变动 (东财DC)
3. 分红送配与除权除息 (东财分红中心)
4. 巨潮资讯官方公告与监管 (巨潮cninfo)
5. 大宗交易与席位异动 (东财大宗)
"""

from scripts.data_sources.safe_session import safe_session, AntiScrapingSession
from scripts.data_sources.kline_adapter import KlineAdapter
from scripts.data_sources.shareholder_adapter import ShareholderAdapter
from scripts.data_sources.dividend_adapter import DividendAdapter
from scripts.data_sources.announcement_adapter import AnnouncementAdapter
from scripts.data_sources.block_trade_adapter import BlockTradeAdapter

class StockDataHub:
    """多维数据中枢统一调用入口"""

    @classmethod
    def get_kline(cls, code: str, limit: int = 120, adjust: str = "qfq"):
        return KlineAdapter.get_daily_kline(code=code, limit=limit, adjust=adjust)

    @classmethod
    def get_holders(cls, code: str):
        return {
            "top10": ShareholderAdapter.get_top10_holders(code),
            "history_count": ShareholderAdapter.get_holder_count_history(code)
        }

    @classmethod
    def get_dividends(cls, code: str, limit: int = 10):
        return DividendAdapter.get_dividends(code=code, page_size=limit)

    @classmethod
    def get_announcements(cls, code: str, keyword: str = "", days: int = 90, limit: int = 15):
        return AnnouncementAdapter.get_announcements(code=code, keyword=keyword, days=days, page_size=limit)

    @classmethod
    def get_block_trades(cls, code: str = "", trade_date: str = "", limit: int = 15):
        if code:
            return BlockTradeAdapter.get_stock_block_trades(code=code, page_size=limit)
        return BlockTradeAdapter.get_market_latest_block_trades(trade_date=trade_date, page_size=limit)
