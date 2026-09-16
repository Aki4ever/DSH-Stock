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
            "is_mock": self.is_mock
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
        turnover: float = 0.0
    ):
        self.date = date
        self.open = float(open_p)
        self.close = float(close_p)
        self.high = float(high_p)
        self.low = float(low_p)
        self.volume = float(volume)
        self.turnover = float(turnover)

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
    """生成具备真实特征的 Mock 离线行情数据（按代码哈希稳定生成）"""
    mock_db = {
        "sh000001": ("上证指数", 3058.62, 3045.20, 3048.10, 3065.80, 3042.15, 325410000, 395000000000),
        "sz399001": ("深证成指", 9560.85, 9510.30, 9520.00, 9590.20, 9495.50, 421500000, 482000000000),
        "sz399006": ("创业板指", 1880.45, 1865.10, 1868.00, 1892.50, 1860.20, 156000000, 195000000000),
        "hkHSI":    ("恒生指数", 17850.20, 17720.00, 17750.00, 17920.50, 17680.10, 120000000, 89000000000),
        "sh600519": ("贵州茅台", 1688.00, 1665.00, 1670.00, 1695.50, 1668.00, 28500, 4810000000),
        "sz300750": ("宁德时代", 205.80, 198.50, 200.00, 208.50, 199.20, 185000, 3780000000),
        "sz002594": ("比亚迪", 268.50, 262.00, 263.50, 271.00, 262.50, 98000, 2620000000),
        "sh601318": ("中国平安", 48.60, 47.90, 48.00, 48.95, 47.85, 450000, 2180000000),
        "sh688981": ("中芯国际", 89.20, 86.50, 87.00, 91.50, 86.80, 320000, 2850000000),
        "sz000001": ("平安银行", 12.85, 12.70, 12.72, 12.92, 12.68, 650000, 835000000)
    }

    if norm_code in mock_db:
        name, price, prev_close, open_p, high_p, low_p, vol, turnover = mock_db[norm_code]
    else:
        # 未收录的代码，通过哈希稳定算法生成拟真行情
        code_seed = sum(ord(c) for c in norm_code)
        name = f"标的_{norm_code}"
        base_p = 20.0 + (code_seed % 80)
        delta_pct = ((code_seed % 100) - 48) / 10.0  # -4.8% ~ +5.1%
        price = round(base_p * (1.0 + delta_pct / 100.0), 2)
        prev_close = base_p
        open_p = round(base_p * (1.0 + (delta_pct * 0.4) / 100.0), 2)
        high_p = round(max(price, open_p, prev_close) * 1.015, 2)
        low_p = round(min(price, open_p, prev_close) * 0.985, 2)
        vol = (code_seed * 123) % 200000 + 10000
        turnover = vol * price * 100

    change = round(price - prev_close, 2)
    change_pct = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0

    return StockQuote(
        code=norm_code,
        name=name,
        price=price,
        prev_close=prev_close,
        open_price=open_p,
        high=high_p,
        low=low_p,
        volume=vol,
        turnover=turnover,
        change=change,
        change_pct=change_pct,
        market="A",
        is_mock=True
    )


def fetch_quote_online(norm_code: str, timeout: float = 3.0) -> Optional[StockQuote]:
    """
    通过公开腾讯金融/新浪行情接口获取实时股票行情
    网络受阻或解析失败时返回 None
    """
    url = f"http://qt.gtimg.cn/q={norm_code}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://gu.qq.com"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("gbk", errors="ignore")
            # 格式：v_sh600519="1~贵州茅台~600519~1688.00~1670.00~1675.00~...~";
            if not data or "~" not in data:
                return None
            parts = data.split("=")[1].strip('";\n').split("~")
            if len(parts) < 35:
                return None

            name = parts[1]
            price = float(parts[3])
            prev_close = float(parts[4])
            open_p = float(parts[5])
            volume = float(parts[6])       # 手
            high_p = float(parts[33]) if len(parts) > 33 and parts[33] else max(price, open_p)
            low_p = float(parts[34]) if len(parts) > 34 and parts[34] else min(price, open_p)
            turnover = float(parts[37]) * 10000 if len(parts) > 37 and parts[37] else volume * price * 100
            timestamp = parts[30] if len(parts) > 30 and parts[30] else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            change = round(price - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0

            return StockQuote(
                code=norm_code,
                name=name,
                price=price,
                prev_close=prev_close,
                open_price=open_p,
                high=high_p,
                low=low_p,
                volume=volume,
                turnover=turnover,
                change=change,
                change_pct=change_pct,
                timestamp=timestamp,
                market=norm_code[:2].upper(),
                is_mock=False
            )
    except Exception:
        return None


def get_quote(code: str, allow_mock: bool = True, timeout: float = 2.5) -> StockQuote:
    """获取单只股票实时行情，具备自动网络穿透与离线 Mock 双模降级"""
    norm_code, _ = normalize_code(code)
    quote = fetch_quote_online(norm_code, timeout=timeout)
    if quote is not None:
        return quote
    if allow_mock:
        return generate_mock_quote(norm_code)
    raise RuntimeError(f"无法获取股票 {code} 的实时行情，且已禁用离线降级。")


def get_batch_quotes(codes: List[str], allow_mock: bool = True, timeout: float = 4.0) -> List[StockQuote]:
    """批量获取多只股票行情"""
    normalized_list = [normalize_code(c)[0] for c in codes]
    if not normalized_list:
        return []

    # 尝试单次合并请求
    combined_query = ",".join(normalized_list)
    url = f"http://qt.gtimg.cn/q={combined_query}"
    results: Dict[str, StockQuote] = {}

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
                "Referer": "http://gu.qq.com"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("gbk", errors="ignore")
            for line in content.split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                var_name, val = line.split("=", 1)
                item_code = var_name.replace("v_", "").strip()
                parts = val.strip('"').split("~")
                if len(parts) >= 35:
                    name = parts[1]
                    price = float(parts[3])
                    prev_close = float(parts[4])
                    open_p = float(parts[5])
                    volume = float(parts[6])
                    high_p = float(parts[33]) if len(parts) > 33 and parts[33] else max(price, open_p)
                    low_p = float(parts[34]) if len(parts) > 34 and parts[34] else min(price, open_p)
                    turnover = float(parts[37]) * 10000 if len(parts) > 37 and parts[37] else volume * price * 100
                    timestamp = parts[30] if len(parts) > 30 and parts[30] else ""
                    change = round(price - prev_close, 2)
                    change_pct = round((change / prev_close) * 100, 2) if prev_close > 0 else 0.0

                    results[item_code] = StockQuote(
                        code=item_code,
                        name=name,
                        price=price,
                        prev_close=prev_close,
                        open_price=open_p,
                        high=high_p,
                        low=low_p,
                        volume=volume,
                        turnover=turnover,
                        change=change,
                        change_pct=change_pct,
                        timestamp=timestamp,
                        market=item_code[:2].upper(),
                        is_mock=False
                    )
    except Exception:
        pass

    final_quotes: List[StockQuote] = []
    for c in normalized_list:
        if c in results:
            final_quotes.append(results[c])
        elif allow_mock:
            final_quotes.append(generate_mock_quote(c))
        else:
            raise RuntimeError(f"未能批量获取代码 {c} 的行情")

    return final_quotes


def generate_mock_kline(code: str, days: int = 60, end_price: Optional[float] = None) -> List[KLineBar]:
    """生成指定天数的拟真连续 K 线序列（用于指标计算与走势图绘制）"""
    norm_code, _ = normalize_code(code)
    quote = generate_mock_quote(norm_code)
    current_close = end_price if end_price is not None else quote.price

    bars: List[KLineBar] = []
    now = datetime.now()
    seed = sum(ord(c) for c in norm_code)

    # 逆推前推生成走势序列
    prices = [current_close]
    temp_p = current_close
    for i in range(days - 1):
        # 随机游走模拟（带均值回归倾向）
        pseudo_rnd = ((seed * (i + 1) * 37) % 100 - 49) / 100.0  # -0.49 ~ +0.50
        pct = pseudo_rnd * 0.035
        temp_p = max(5.0, temp_p / (1.0 + pct))
        prices.insert(0, temp_p)

    # 生成每个交易日的 K 线
    trade_date = now - timedelta(days=int(days * 1.5))
    day_count = 0

    for idx, close_p in enumerate(prices):
        while trade_date.weekday() >= 5:  # 跳过周末
            trade_date += timedelta(days=1)

        prev_p = prices[idx - 1] if idx > 0 else close_p * 0.99
        open_p = round(prev_p * (1.0 + (((seed * (idx + 3)) % 30 - 15) / 1000.0)), 2)
        high_p = round(max(open_p, close_p) * (1.0 + abs((seed * (idx + 7)) % 25) / 1000.0), 2)
        low_p = round(min(open_p, close_p) * (1.0 - abs((seed * (idx + 11)) % 25) / 1000.0), 2)
        vol = round(abs(((seed * (idx + 13)) % 50000) + 15000) * (close_p / 20.0), 1)

        bars.append(KLineBar(
            date=trade_date.strftime("%Y-%m-%d"),
            open_p=open_p,
            close_p=round(close_p, 2),
            high_p=high_p,
            low_p=low_p,
            volume=vol,
            turnover=round(vol * close_p * 100, 2)
        ))

        trade_date += timedelta(days=1)
        day_count += 1
        if day_count >= days:
            break

    return bars
