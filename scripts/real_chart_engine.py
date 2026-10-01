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


# 需求REQ-028: 分钟K线（5/15/30 分钟）真实来源
# 腾讯分钟K线接口，每根格式为 [时间(yyyymmddHHMM), 开, 收, 高, 低, 成交量(手), {}, 第8字段]
# 第8字段单位无法与成交量/成交价互相印证（实测 ratio ((开+收+高+低)/4)*量*100 / 第8字段 ≈ 1.6e8，
# 既非元也非万元、亿元），故一律不采信该字段，改用本 K 线自身的均价 × 成交量得出成交额，
# 并在返回中标注 amount_derived=true（需求REQ-025 口径），绝不把来源不明的数字当真实成交额。
# 需求REQ-035: 新增 1 分钟颗粒度（m1），来源同为腾讯分钟K线接口（实测可返回真实 1 分钟区间K线）
MINUTE_KLINE_INTERVALS = {"m1": 1, "m5": 5, "m15": 15, "m30": 30}
# 需求REQ-035: 单次可取上限（实测 m1/m5 请求 800 根可完整返回；超过上限来源会回落，故设 800 为稳妥上限）
MINUTE_KLINE_MAX_LIMIT = 800
MINUTE_KLINE_ENDPOINT = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
MINUTE_KLINE_CACHE_TTL = 120


def fetch_real_minute_kline(code: str, interval: str, limit: int = 200) -> Dict[str, Any]:
    """需求REQ-028: 真实分钟K线；每根K线为一个时间区间（开/收/高/低/量/额）。"""
    from scripts.market_history import canonical_code
    from scripts.verified_sources import request_json, meta, number, cache_get, cache_put
    interval = str(interval or "").lower().strip()
    if interval not in MINUTE_KLINE_INTERVALS:
        raise ValueError("不支持的分钟周期，仅支持 m1 / m5 / m15 / m30")
    minutes = MINUTE_KLINE_INTERVALS[interval]
    symbol = canonical_code(code)
    limit = max(1, min(int(limit or 200), MINUTE_KLINE_MAX_LIMIT))

    cache_key = f"minute_kline:{symbol}:{interval}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict) and cached.get("payload") and (time.time() - float(cached.get("at") or 0)) < MINUTE_KLINE_CACHE_TTL:
        bars = (cached["payload"] or {}).get("bars") or []
        if bars:
            return dict(meta(cached["payload"].get("source") or "腾讯证券分钟K线", "available"), code=symbol,
                        interval=interval, minutes=minutes, bars=bars[-limit:], amount_derived=True,
                        cache="hit", volume_unit="手")

    try:
        payload = request_json(f"{MINUTE_KLINE_ENDPOINT}?param={symbol},{interval},,{limit}")
        raw = (payload.get("data") or {}).get(symbol) or {}
        rows = raw.get(interval) or []
        bars = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            stamp = str(row[0])
            if len(stamp) != 12 or not stamp.isdigit():
                continue
            o, c, h, l = number(row[1]), number(row[2]), number(row[3]), number(row[4])
            volume = number(row[5])
            if None in (o, c, h, l) or o <= 0 or c <= 0 or h <= 0 or l <= 0:
                continue
            avg_price = (o + c + h + l) / 4.0
            # 成交额＝该K线均价 × 该K线成交量（手→股），来源未提供可用成交额字段
            amount_yi = (avg_price * volume * 100 / 1e8) if (volume and volume > 0) else None
            bars.append({
                "date": f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}",
                "time": f"{stamp[8:10]}:{stamp[10:12]}",
                "datetime": f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[8:10]}:{stamp[10:12]}",
                "open": o, "close": c, "high": h, "low": l,
                "price": c, "volume": volume, "avg_price": avg_price,
                "amount_yi": amount_yi, "amount_derived": amount_yi is not None,
                "amount_unit": "亿元",
            })
        if not bars:
            raise ValueError("来源未返回有效分钟K线")
        cache_put(cache_key, {"at": time.time(), "payload": {"source": "腾讯证券分钟K线", "bars": bars[-limit:]}})
        return dict(meta("腾讯证券分钟K线", "available"), code=symbol, interval=interval, minutes=minutes,
                    bars=bars[-limit:], amount_derived=True, cache="miss", volume_unit="手")
    except Exception as exc:
        return dict(meta("腾讯证券分钟K线", "unavailable", str(exc)), code=symbol, interval=interval,
                    minutes=minutes, bars=[], amount_derived=True, volume_unit="手")


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
