#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东方财富股东信息与户数采集适配器 (Eastmoney Shareholder Adapter)
版本: v1.0.0
特点:
1. 获取最新一期十大股东持股名单、持股变动与股份性质
2. 获取历史股东户数变动趋势、户均持股金额及筹码集中度
"""

import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from scripts.data_sources.safe_session import safe_session

EASTMONEY_DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_REFERER = "https://data.eastmoney.com/gdfx/gdcj.html"

class ShareholderAdapter:
    """股东与筹码集中度采集器"""

    @staticmethod
    def get_top10_holders(code: str, page_size: int = 10) -> Dict[str, Any]:
        """
        获取指定股票最新一期十大股东持股名单
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        
        params = {
            "reportName": "RPT_F10_EH_HOLDERS",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{clean_code}")',
            "pageNumber": 1,
            "pageSize": page_size,
            "sortTypes": "-1,1",
            "sortColumns": "END_DATE,HOLDER_RANK",
            "source": "WEB",
            "client": "WEB"
        }

        resp = safe_session.get_json(
            EASTMONEY_DC_URL,
            params=params,
            referer=EASTMONEY_REFERER,
            timeout=6.0
        )

        output = {
            "code": clean_code,
            "name": "",
            "period": "",
            "holders": []
        }

        if not resp or not isinstance(resp, dict) or not resp.get("success"):
            return output

        data_list = (resp.get("result") or {}).get("data") or []
        if not data_list:
            return output

        # 取最新一个报告期
        latest_period = (data_list[0].get("END_DATE") or "").split(" ")[0]
        output["period"] = latest_period
        output["name"] = data_list[0].get("SECURITY_NAME_ABBR", "")

        for item in data_list:
            curr_period = (item.get("END_DATE") or "").split(" ")[0]
            if curr_period != latest_period:
                continue

            change_str = item.get("HOLD_NUM_CHANGE", "不变")
            if not change_str or change_str == "0":
                change_str = "不变"

            output["holders"].append({
                "rank": int(item.get("HOLDER_RANK") or len(output["holders"]) + 1),
                "name": item.get("HOLDER_NAME", "未知"),
                "hold_num_wan": round(float(item.get("HOLD_NUM") or 0.0) / 10000, 2), # 万股
                "hold_ratio": float(item.get("HOLD_NUM_RATIO") or 0.0),               # 占比 %
                "change": change_str,
                "share_type": item.get("SHARES_TYPE", "流通A股")
            })

        return output

    @staticmethod
    def get_holder_count_history(code: str, count: int = 6) -> List[Dict[str, Any]]:
        """
        获取股东户数历史变动趋势与筹码集中度
        """
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")

        params = {
            "reportName": "RPT_F10_EH_HOLDERNUM",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{clean_code}")',
            "pageNumber": 1,
            "pageSize": count,
            "sortTypes": "-1",
            "sortColumns": "END_DATE",
            "source": "WEB",
            "client": "WEB"
        }

        resp = safe_session.get_json(
            EASTMONEY_DC_URL,
            params=params,
            referer=EASTMONEY_REFERER,
            timeout=6.0
        )

        results = []
        if not resp or not isinstance(resp, dict) or not resp.get("success"):
            return results

        data_list = (resp.get("result") or {}).get("data") or []
        for item in data_list:
            period = (item.get("END_DATE") or "").split(" ")[0]
            results.append({
                "period": period,
                "holder_num": int(item.get("HOLDER_TOTAL_NUM") or 0),
                "change_ratio": float(item.get("TOTAL_NUM_RATIO") or 0.0), # 户数变动比例%
                "avg_hold_num": round(float(item.get("AVG_FREE_SHARES") or 0.0), 1),
                "focus_level": item.get("HOLD_FOCUS", "一般")
            })

        return results
