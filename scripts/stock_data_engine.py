#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票实时与历史行情数据引擎 (Stock Data Engine)
版本: v1.0.0
遵循规范: rules/system/meta_rules.md 第五条（自律安全）、第十八条（DSH生态赋能）
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple


class StockQuote:
    """股票实时行情数据模型"""
    def __init__(
        self,
        code: str,
        name: str,
        price: float,
        prev_close: float,
        open_price: float,
        high: float,
        low: float,
        volume: float,
        turnover: float,
        change: float = 0.0,
        change_pct: float = 0.0,
        timestamp: str = "",
        market: str = "A",
        is_mock: bool = False
    ):
        self.code = code
        self.name = name
        self.price = float(price)
        self.prev_close = float(prev_close) if prev_close > 0 else self.price
        self.open_price = float(open_price)
        self.high = float(high)
        self.low = float(low)
        self.volume = float(volume)        # 成交量（手或股）
        self.turnover = float(turnover)    # 成交额（元）
        self.change = float(change) if change != 0.0 else round(self.price - self.prev_close, 2)
        if prev_close > 0 and change_pct == 0.0:
            self.change_pct = round(((self.price - self.prev_close) / self.prev_close) * 100, 2)
        else:
            self.change_pct = float(change_pct)
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.market = market
        self.is_mock = is_mock

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "prev_close": self.prev_close,
            "open_price": self.open_price,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "turnover": self.turnover,
            "change": self.change,
            "change_pct": self.change_pct,
            "timestamp": self.timestamp,
            "market": self.market,
            "is_mock": self.is_mock,
            "source": getattr(self, "source", None)
        }

    def __repr__(self) -> str:
        sign = "+" if self.change >= 0 else ""
        return f"<StockQuote {self.code} {self.name} {self.price:.2f} ({sign}{self.change_pct:.2f}%)>"


class KLineBar:
    """K线单根柱线数据模型"""
    def __init__(
        self,
        date: str,
        open_p: float,
        close_p: float,
        high_p: float,
        low_p: float,
        volume: float,
        turnover: Optional[float] = None
    ):
        self.date = date
        self.open = float(open_p)
        self.close = float(close_p)
        self.high = float(high_p)
        self.low = float(low_p)
        self.volume = float(volume)
        self.turnover = float(turnover) if turnover is not None else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "open": self.open,
            "close": self.close,
            "high": self.high,
            "low": self.low,
            "volume": self.volume,
            "turnover": self.turnover
        }


def normalize_code(code: str) -> Tuple[str, str]:
    """
    标准化股票代码为带市场前缀的形式与市场分类
    例如: 600519 -> sh600519, 000001 -> sz000001, 00700 -> hk00700
    返回: (normalized_code, market)
    """
    clean_code = code.strip().lower()
    if clean_code.startswith(("sh", "sz", "bj", "hk", "us")):
        prefix = clean_code[:2]
        raw_code = clean_code[2:]
        return clean_code, prefix.upper()

    # 纯数字判断市场
    if len(clean_code) == 5:
        return f"hk{clean_code}", "HK"
    elif clean_code.startswith(("60", "68", "90")):
        return f"sh{clean_code}", "SH"
    elif clean_code.startswith(("00", "30", "20")):
        return f"sz{clean_code}", "SZ"
    elif clean_code.startswith(("8", "4", "92")):
        return f"bj{clean_code}", "BJ"
    else:
        # 默认作为沪深处理
        return f"sh{clean_code}", "SH"


def generate_mock_quote(norm_code: str) -> StockQuote:
    raise RuntimeError("产品禁止生成模拟行情；测试请使用隔离fixture")


def fetch_quote_online(norm_code: str, timeout: float = 2.5):
    try:
        return get_batch_quotes([norm_code], timeout=timeout)[0]
    except (RuntimeError,ValueError):
        return None



def get_quote(code: str, allow_mock: bool = False, timeout: float = 2.5) -> StockQuote:
    """获取单只股票实时行情，仅使用真实行情；来源缺失时明确报错"""
    norm_code, _ = normalize_code(code)
    quote = fetch_quote_online(norm_code, timeout=timeout)
    if quote is not None:
        return quote
    if allow_mock:
        return generate_mock_quote(norm_code)
    raise RuntimeError(f"无法获取股票 {code} 的实时行情，且已禁用离线降级。")


def get_batch_quotes(codes, allow_mock=False, timeout=4.0):
    from scripts.verified_quotes import fetch_quotes
    normalized=list(dict.fromkeys(normalize_code(c)[0] for c in codes))
    rows={r['code']:r for r in fetch_quotes(normalized)}
    result=[]
    required=('price','prev_close','open','high','low','volume','turnover')
    for code in normalized:
        r=rows.get(code)
        if r is None or any(r.get(k) is None for k in required) or r['prev_close']<=0:
            raise RuntimeError('真实行情字段未获取完整：'+code)
        q=StockQuote(code,r['name'],r['price'],r['prev_close'],r['open'],r['high'],r['low'],r['volume'],r['turnover'],
            timestamp=r['timestamp'],market=code[:2].upper())
        q.source=r['quote_meta']['source']; result.append(q)
    return result



def generate_mock_kline(code: str, days: int = 60, end_price: Optional[float] = None) -> List[KLineBar]:
    raise RuntimeError("产品禁止生成模拟行情；测试请使用隔离fixture")


def get_real_kline(code, days=60, end_price=None):
    from scripts.history_service import get_daily_history
    value = get_daily_history(code)
    if value['status'] != 'available':
        raise RuntimeError('真实历史行情不可用：' + str(value.get('error')))
    return [KLineBar(b['date'], b['open'], b['close'], b['high'], b['low'], b['volume'], b['amount_yi']*1e8 if b.get('amount_yi') is not None else None) for b in value['bars'][-days:]]
