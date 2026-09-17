#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富分红送配采集适配器 (Eastmoney Dividend Adapter)
版本: v1.0.0
特点:
1. 获取股票历年分红方案、派息金额与转送股比例
2. 锁定分红全生命周期节点：董事会预案 -> 股东大会通过 -> 实施分配 -> 股权登记日 -> 除权除息日
"""

import sys
import os
from typing import List, Dict, Any, Optional

from scripts.data_sources.safe_session import safe_session

EASTMONEY_DIVIDEND_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_REFERER = "https://data.eastmoney.com/yjfp/"

class DividendAdapter:
    """分红送配采集器"""

    @staticmethod
    def get_dividends(code: str, page_size: int = 10) -> List[Dict[str, Any]]:
        """
        获取指定股票历年分红明细与最新方案
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")

        params = {
            "reportName": "RPT_SHAREBONUS_DET",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{clean_code}")',
            "pageNumber": 1,
            "pageSize": page_size,
            "sortTypes": "-1",
            "sortColumns": "REPORT_DATE",
            "source": "WEB",
            "client": "WEB"
        }

        resp = safe_session.get_json(
            EASTMONEY_DIVIDEND_URL,
            params=params,
            referer=EASTMONEY_REFERER,
            timeout=6.0
        )

        results = []
        if not resp or not isinstance(resp, dict) or not resp.get("success"):
            return results

        data_list = (resp.get("result") or {}).get("data") or []
        for item in data_list:
            rep_date = (item.get("REPORT_DATE") or "").split(" ")[0]
            rec_date = (item.get("EQUITY_RECORD_DATE") or "").split(" ")[0]
            ex_date = (item.get("EX_DIVIDEND_DATE") or "").split(" ")[0]
            notice_date = (item.get("NOTICE_DATE") or "").split(" ")[0]
            plan_profile = item.get("IMPL_PLAN_PROFILE") or item.get("PLAN_EXPLAIN") or "不分配不转增"
            pretax_cash = float(item.get("PRETAX_BONUS_RMB") or 0.0)

            results.append({
                "code": clean_code,
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "report_period": rep_date,
                "plan_detail": plan_profile,
                "cash_ratio": pretax_cash, # 每10股税前分红金额(元)
                "record_date": rec_date if rec_date != "-" else "",
                "ex_dividend_date": ex_date if ex_date != "-" else "",
                "notice_date": notice_date,
                "progress": item.get("ASSIGN_PROGRESS", "预案"),
                "source": "东方财富分红中心"
            })

        return results
