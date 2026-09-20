#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 真实行情引擎 (Real Chart & Quotes Engine)
版本: v4.3.0

核心原则 (铁律):
1. 100% 源自真实金融市场数据，严禁任何伪造、推测、mock或容灾生成假数据；
2. 构建多源冗余通道自动故障转移 (Failover):
   - 日K线: 通道A(腾讯证券官方复权日K) -> 通道B(东方财富官方日K) -> 通道C(新浪财经)
   - 分时走势: 通道A(腾讯证券官方高频分时) -> 通道B(新浪财经实时分时)
3. 真实抓取失败或官方未披露时，严格返回空数据 (None / [])，由前端向用户显示严正文案警示！
"""

import os
import sys
import json
import time
import urllib.request
from typing import Dict, List, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def fetch_real_daily_kline(code: str, limit=None) -> List[Dict[str, Any]]:
    """真实不复权全历史；兼容调用方显式要求最近 N 根。"""
    from scripts.history_service import get_daily_history
    bars = get_daily_history(code)["bars"]
    return bars[-limit:] if limit and limit > 0 else bars


def fetch_real_timeline(code: str) -> Dict[str, Any]:
    """腾讯来源实际分时；缺字段保留空值，失败不以5分钟K线冒充分时。"""
    from datetime import date
    from scripts.market_history import canonical_code
    from scripts.verified_sources import request_json, meta, number
    symbol = canonical_code(code)
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
    try:
        payload = request_json(url, {"code": symbol})
        raw = payload.get("data", {}).get(symbol, {})
        minute = raw.get("data") or {}
        trading_date = str(minute.get("date") or "")
        if not trading_date or trading_date.replace("-", "") > date.today().strftime("%Y%m%d"):
            raise ValueError("分时来源日期缺失或在未来")
        quote = (raw.get("qt") or {}).get(symbol) or []
        pre_close = number(quote[4]) if len(quote)>4 else None
        if pre_close is None or pre_close<=0: raise ValueError("昨收字段未提供，分时基准不可核验")
        items = []
        last_volume = last_amount = 0
        for line in minute.get("data") or []:
            fields = line.split()
            if len(fields)<3: continue
            clock, price, volume = fields[0], number(fields[1]), number(fields[2])
            amount = number(fields[3]) if len(fields)>3 else None
            if price is None or price<=0 or len(clock)!=4 or not clock.isdigit(): continue
            if not ("0930" <= clock <= "1130" or "1300" <= clock <= "1500"): continue
            interval_volume = volume-last_volume if volume is not None and last_volume is not None and volume>=last_volume else None
            interval_amount = amount-last_amount if amount is not None and last_amount is not None and amount>=last_amount else None
            items.append({"time":clock[:2]+":"+clock[2:], "price":price, "volume":interval_volume, "cumulative_volume":volume,
                "amount_yi": interval_amount/1e8 if interval_amount is not None else None, "cumulative_amount_yi":amount/1e8 if amount is not None else None,
                "avg_price": amount/(volume*100) if amount is not None and volume and volume>0 else None,
                "change_pct": (price/pre_close-1)*100 if pre_close and pre_close>0 else None})
            last_volume, last_amount = volume, amount
        return dict(meta("腾讯证券分时", "available" if items else "unavailable"), code=symbol,
                    pre_close=pre_close, items=items, date=trading_date, source_url=url, volume_unit="手")
    except Exception as exc:
        return dict(meta("腾讯证券分时", "unavailable", str(exc)), code=symbol, pre_close=None, items=[], date=None)
