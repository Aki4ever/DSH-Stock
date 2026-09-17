#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富高精度前复权历史K线采集适配器 (Eastmoney K-Line Adapter)
版本: v1.0.0
特点:
1. 获取股票或大盘指数的历史日K、周K、分时K线
2. 原生支持前复权 (fqt=1) 计算，消除除权除息导致的技术图形失真
3. 严格防反爬与请求超时降级保护
"""

import sys
import os
from typing import List, Dict, Any, Optional

from scripts.data_sources.safe_session import safe_session

EASTMONEY_KLINE_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
EASTMONEY_KLINE_REFERER = "http://quote.eastmoney.com/"

class KlineAdapter:
    """历史K线数据采集器"""

    @staticmethod
    def _get_secid(code: str) -> str:
        """根据股票代码前缀转换为东财 secid (1.600519, 0.000001)"""
        clean = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        if clean.startswith(("6", "9", "5")): # 上交所 (含科创板/基金)
            return f"1.{clean}"
        elif clean.startswith(("0", "3", "1", "2")): # 深交所
            return f"0.{clean}"
        elif clean.startswith(("8", "4", "92")): # 北交所
            return f"0.{clean}"
        return f"1.{clean}"

    @staticmethod
    def get_daily_kline(
        code: str,
        limit: int = 120,
        adjust: str = "qfq"  # qfq: 前复权, hfq: 后复权, none: 不复权
    ) -> List[Dict[str, Any]]:
        """
        获取历史日K线
        :param code: 股票代码 (如 600519 或 sh600519)
        :param limit: K线根数
        :param adjust: 复权类型 ('qfq', 'hfq', 'none')
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        secid = KlineAdapter._get_secid(clean_code)

        fqt_map = {"qfq": "1", "hfq": "2", "none": "0"}
        fqt_val = fqt_map.get(adjust, "1")

        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", # 101 为日K
            "fqt": fqt_val,
            "end": "20500101",
            "lmt": limit
        }

        resp = safe_session.get_json(
            EASTMONEY_KLINE_URL,
            params=params,
            referer=EASTMONEY_KLINE_REFERER,
            timeout=6.0
        )

        results = []
        if not resp or not isinstance(resp, dict):
            return results

        data = resp.get("data") or {}
        klines = data.get("klines") or []
        
        # 格式："2026-09-15,1630.00,1650.00,1660.00,1625.00,21000,345000000.00,2.15"
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                results.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]), # 手
                    "turnover": float(parts[6]) if len(parts) > 6 else 0.0,
                    "amplitude": float(parts[7]) if len(parts) > 7 else 0.0,
                    "change_pct": float(parts[8]) if len(parts) > 8 else 0.0,
                })

        return results
