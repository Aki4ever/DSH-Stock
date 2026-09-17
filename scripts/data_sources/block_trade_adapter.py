#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富大宗交易数据采集适配器 (Eastmoney Block Trade Adapter)
版本: v1.0.0
特点:
1. 获取每日收盘后（15:30）两市大宗交易全量明细
2. 获取指定股票的历史大宗交易记录
3. 计算折溢价率、识别买卖营业部特征（重点区分机构席位与游资营业部）
"""

import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from scripts.data_sources.safe_session import safe_session

# 东方财富大宗交易明细公开接口
EASTMONEY_BLOCK_TRADE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_REFERER = "https://data.eastmoney.com/dzjy/dzjy_mrmx.html"

class BlockTradeAdapter:
    """大宗交易数据采集器"""

    @staticmethod
    def get_stock_block_trades(code: str, page_size: int = 15) -> List[Dict[str, Any]]:
        """
        获取指定股票最近的大宗交易成交明细
        :param code: 股票代码 (如 '600519')
        :param page_size: 条数限制
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        
        params = {
            "reportName": "RPT_DATA_BLOCKTRADE",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,DEAL_PRICE,PREMIUM_RATIO,DEAL_VOLUME,DEAL_AMT,BUYER_NAME,SELLER_NAME",
            "filter": f'(SECURITY_CODE="{clean_code}")',
            "pageNumber": 1,
            "pageSize": page_size,
            "sortTypes": "-1",
            "sortColumns": "TRADE_DATE",
            "source": "WEB",
            "client": "WEB"
        }

        resp = safe_session.get_json(
            EASTMONEY_BLOCK_TRADE_URL,
            params=params,
            referer=EASTMONEY_REFERER,
            timeout=6.0
        )

        results = []
        if not resp or not isinstance(resp, dict) or not resp.get("success"):
            return results

        data_list = (resp.get("result") or {}).get("data") or []
        for item in data_list:
            trade_date = item.get("TRADE_DATE", "")
            if trade_date and " " in trade_date:
                trade_date = trade_date.split(" ")[0]

            close_p = float(item.get("CLOSE_PRICE") or 0.0)
            deal_p = float(item.get("DEAL_PRICE") or 0.0)
            premium_r = float(item.get("PREMIUM_RATIO") or 0.0)
            # 若接口折溢价未直接给，手动算折溢价率 = (成交价 - 收盘价) / 收盘价 * 100
            if premium_r == 0.0 and close_p > 0:
                premium_r = round(((deal_p - close_p) / close_p) * 100, 2)

            buyer = item.get("BUYER_NAME", "未知席位")
            seller = item.get("SELLER_NAME", "未知席位")

            results.append({
                "code": item.get("SECURITY_CODE", clean_code),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "trade_date": trade_date,
                "close_price": close_p,
                "deal_price": deal_p,
                "premium_ratio": premium_r,
                "volume_hand": round(float(item.get("DEAL_VOLUME") or 0.0) / 100, 2), # 手
                "amount_wan": round(float(item.get("DEAL_AMT") or 0.0) / 10000, 2),   # 万元
                "buyer": buyer,
                "seller": seller,
                "is_buyer_org": "机构专用" in buyer,
                "is_seller_org": "机构专用" in seller,
                "source": "东方财富大宗数据中心"
            })

        return results

    @staticmethod
    def get_market_latest_block_trades(trade_date: Optional[str] = None, page_size: int = 20) -> List[Dict[str, Any]]:
        """
        获取全市场最新一天的重点大宗交易
        """
        filter_str = f'(TRADE_DATE=\'{trade_date}\')' if trade_date else ""
        params = {
            "reportName": "RPT_DATA_BLOCKTRADE",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,DEAL_PRICE,PREMIUM_RATIO,DEAL_VOLUME,DEAL_AMT,BUYER_NAME,SELLER_NAME",
            "pageNumber": 1,
            "pageSize": page_size,
            "sortTypes": "-1",
            "sortColumns": "DEAL_AMT", # 按成交额降序排序
            "source": "WEB",
            "client": "WEB"
        }
        if filter_str:
            params["filter"] = filter_str

        resp = safe_session.get_json(
            EASTMONEY_BLOCK_TRADE_URL,
            params=params,
            referer=EASTMONEY_REFERER,
            timeout=6.0
        )

        results = []
        if not resp or not isinstance(resp, dict) or not resp.get("success"):
            return results

        data_list = (resp.get("result") or {}).get("data") or []
        for item in data_list:
            t_date = (item.get("TRADE_DATE") or "").split(" ")[0]
            close_p = float(item.get("CLOSE_PRICE") or 0.0)
            deal_p = float(item.get("DEAL_PRICE") or 0.0)
            premium_r = float(item.get("PREMIUM_RATIO") or 0.0)
            if premium_r == 0.0 and close_p > 0:
                premium_r = round(((deal_p - close_p) / close_p) * 100, 2)

            buyer = item.get("BUYER_NAME", "")
            seller = item.get("SELLER_NAME", "")

            results.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "trade_date": t_date,
                "close_price": close_p,
                "deal_price": deal_p,
                "premium_ratio": premium_r,
                "amount_wan": round(float(item.get("DEAL_AMT") or 0.0) / 10000, 2),
                "buyer": buyer,
                "seller": seller,
                "is_buyer_org": "机构专用" in buyer,
                "is_seller_org": "机构专用" in seller,
                "source": "东方财富大宗数据中心"
            })
        return results
