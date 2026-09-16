#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票技术指标计算与 100 分制多空量化评分引擎 (Stock Indicators & Scoring)
版本: v1.0.0
遵循规范: rules/system/meta_rules.md 第十四条（质量门禁）
"""

import math
from typing import List, Dict, Any, Optional, Tuple
from scripts.stock_data_engine import KLineBar


def calculate_ma(prices: List[float], window: int) -> List[Optional[float]]:
    """计算简单移动平均线 (Simple Moving Average)"""
    ma_values: List[Optional[float]] = []
    for i in range(len(prices)):
        if i + 1 < window:
            ma_values.append(None)
        else:
            window_slice = prices[i + 1 - window : i + 1]
            ma_values.append(round(sum(window_slice) / window, 3))
    return ma_values


def calculate_ema(prices: List[float], window: int) -> List[float]:
    """计算指数移动平均线 (Exponential Moving Average)"""
    if not prices:
        return []
    alpha = 2.0 / (window + 1)
    ema_values: List[float] = [prices[0]]
    for p in prices[1:]:
        ema_val = alpha * p + (1.0 - alpha) * ema_values[-1]
        ema_values.append(round(ema_val, 4))
    return ema_values


def calculate_macd(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[List[float], List[float], List[float]]:
    """
    计算 MACD 指标
    返回: (DIF, DEA, MACD柱线)
    """
    if len(prices) < slow:
        # 数据不足时返回零填充
        zeros = [0.0] * len(prices)
        return zeros, zeros, zeros

    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    dif = [round(f - s, 4) for f, s in zip(ema_fast, ema_slow)]
    dea = calculate_ema(dif, signal)
    macd_bar = [round(2.0 * (d - a), 4) for d, a in zip(dif, dea)]
    return dif, dea, macd_bar


def calculate_rsi(prices: List[float], period: int = 6) -> List[Optional[float]]:
    """计算相对强弱指标 (Relative Strength Index)"""
    if len(prices) <= period:
        return [None] * len(prices)

    rsi_values: List[Optional[float]] = [None] * period
    gains: List[float] = []
    losses: List[float] = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    if avg_loss == 0.0:
        first_rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        first_rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi_values.append(round(first_rsi, 2))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        rsi_values.append(round(rsi, 2))

    return rsi_values


def calculate_boll(
    prices: List[float],
    period: int = 20,
    multiplier: float = 2.0
) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    """
    计算布林线 (Bollinger Bands)
    返回: (上轨 Upper, 中轨 Mid/MA20, 下轨 Lower)
    """
    mid = calculate_ma(prices, period)
    upper: List[Optional[float]] = []
    lower: List[Optional[float]] = []

    for i in range(len(prices)):
        m = mid[i]
        if m is None:
            upper.append(None)
            lower.append(None)
        else:
            window_slice = prices[i + 1 - period : i + 1]
            variance = sum((x - m) ** 2 for x in window_slice) / period
            std_dev = math.sqrt(variance)
            upper.append(round(m + multiplier * std_dev, 2))
            lower.append(round(m - multiplier * std_dev, 2))

    return upper, mid, lower


def calculate_kdj(
    bars: List[KLineBar],
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[List[float], List[float], List[float]]:
    """
    计算 KDJ 随机指标
    返回: (K, D, J)
    """
    k_vals: List[float] = []
    d_vals: List[float] = []
    j_vals: List[float] = []

    curr_k = 50.0
    curr_d = 50.0

    for i in range(len(bars)):
        start_idx = max(0, i + 1 - n)
        slice_bars = bars[start_idx : i + 1]
        highest_h = max(b.high for b in slice_bars)
        lowest_l = min(b.low for b in slice_bars)
        close_p = bars[i].close

        if highest_h == lowest_l:
            rsv = 50.0
        else:
            rsv = (close_p - lowest_l) / (highest_h - lowest_l) * 100.0

        curr_k = (m1 - 1) / m1 * curr_k + 1.0 / m1 * rsv
        curr_d = (m2 - 1) / m2 * curr_d + 1.0 / m2 * curr_k
        curr_j = 3.0 * curr_k - 2.0 * curr_d

        k_vals.append(round(curr_k, 2))
        d_vals.append(round(curr_d, 2))
        j_vals.append(round(curr_j, 2))

    return k_vals, d_vals, j_vals


class QuantitativeReport:
    """量化分析与多空评级报告模型"""
    def __init__(
        self,
        code: str,
        name: str,
        current_price: float,
        score: float,
        grade: str,
        action: str,
        dimension_scores: Dict[str, float],
        signals: List[str],
        indicators_snapshot: Dict[str, Any]
    ):
        self.code = code
        self.name = name
        self.current_price = current_price
        self.score = round(score, 1)
        self.grade = grade
        self.action = action
        self.dimension_scores = dimension_scores
        self.signals = signals
        self.indicators_snapshot = indicators_snapshot

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "current_price": self.current_price,
            "score": self.score,
            "grade": self.grade,
            "action": self.action,
            "dimension_scores": self.dimension_scores,
            "signals": self.signals,
            "indicators_snapshot": self.indicators_snapshot
        }


def evaluate_stock(code: str, name: str, bars: List[KLineBar]) -> QuantitativeReport:
    """
    对指定股票进行 100 分制多空量化评分与信号检测
    维度划分:
      1. 趋势面 (35分)
      2. 动量面 (25分)
      3. 均线与支撑面 (20分)
      4. 波动与风险面 (20分)
    """
    if not bars:
        raise ValueError("K线数据不能为空")

    closes = [b.close for b in bars]
    curr_price = closes[-1]

    # 计算各指标
    ma5 = calculate_ma(closes, 5)
    ma10 = calculate_ma(closes, 10)
    ma20 = calculate_ma(closes, 20)
    ma60 = calculate_ma(closes, 60)
    dif, dea, macd_bar = calculate_macd(closes)
    rsi6 = calculate_rsi(closes, 6)
    rsi12 = calculate_rsi(closes, 12)
    upper, mid, lower = calculate_boll(closes, 20)
    k_vals, d_vals, j_vals = calculate_kdj(bars)

    signals: List[str] = []

    # 1. 趋势面评估 (满分 35 分)
    trend_score = 15.0
    c_ma5 = ma5[-1]
    c_ma10 = ma10[-1]
    c_ma20 = ma20[-1]

    if c_ma5 and c_ma10 and c_ma20:
        if c_ma5 > c_ma10 > c_ma20:
            trend_score = 35.0
            signals.append("均线呈多头排列 (MA5 > MA10 > MA20)")
        elif c_ma5 > c_ma10 and curr_price > c_ma20:
            trend_score = 28.0
            signals.append("短期均线金叉上行且站上 MA20")
        elif c_ma5 < c_ma10 < c_ma20:
            trend_score = 6.0
            signals.append("均线呈空头排列 (MA5 < MA10 < MA20)")
        elif curr_price < c_ma20:
            trend_score = 12.0
            signals.append("价格运行于 MA20 生命线下方")
        else:
            trend_score = 20.0
            signals.append("均线系统处于中性震荡胶着态")

    # 2. 动量面评估 (满分 25 分)
    momentum_score = 12.0
    c_dif = dif[-1]
    c_dea = dea[-1]
    c_macd = macd_bar[-1]
    prev_macd = macd_bar[-2] if len(macd_bar) > 1 else c_macd

    if c_dif > c_dea and c_macd > 0:
        if c_macd > prev_macd:
            momentum_score = 25.0
            signals.append("MACD 零轴上方红柱持续扩张 (强势进攻)")
        else:
            momentum_score = 20.0
            signals.append("MACD 红柱略微收敛但保持多头")
    elif c_dif > c_dea and c_macd <= 0:
        momentum_score = 16.0
        signals.append("MACD 绿柱缩短酝酿低位金叉")
    elif c_dif < c_dea and c_macd < 0:
        if c_macd < prev_macd:
            momentum_score = 4.0
            signals.append("MACD 零轴下方绿柱扩张 (空头杀跌)")
        else:
            momentum_score = 9.0
            signals.append("MACD 处于空头区间但绿柱有所收敛")

    # 3. 均线与支撑面 (满分 20 分)
    support_score = 10.0
    c_mid = mid[-1]
    c_upper = upper[-1]
    c_lower = lower[-1]

    if c_mid and c_upper and c_lower:
        if curr_price >= c_upper:
            support_score = 15.0
            signals.append("价格突破布林线上轨 (进入加速段或超买警示)")
        elif curr_price >= c_mid:
            support_score = 19.0
            signals.append("价格运行于布林中轨上方，支撑牢固")
        elif curr_price <= c_lower:
            support_score = 8.0
            signals.append("价格触及布林下轨 (超跌寻底)")
        else:
            support_score = 12.0

    # 4. 波动与风险面 (满分 20 分)
    volatility_score = 12.0
    c_rsi = rsi6[-1] if rsi6 and rsi6[-1] is not None else 50.0

    if 45.0 <= c_rsi <= 68.0:
        volatility_score = 20.0
        signals.append(f"RSI-6 ({c_rsi:.1f}) 处于最佳良性进攻区间")
    elif c_rsi > 80.0:
        volatility_score = 10.0
        signals.append(f"RSI-6 ({c_rsi:.1f}) 处于极度超买区 (防范回调风险)")
    elif c_rsi < 25.0:
        volatility_score = 14.0
        signals.append(f"RSI-6 ({c_rsi:.1f}) 处于严重超卖区 (具备反弹动能)")
    elif c_rsi < 40.0:
        volatility_score = 8.0
        signals.append(f"RSI-6 ({c_rsi:.1f}) 动能偏弱")
    else:
        volatility_score = 16.0

    # 综合总分
    total_score = trend_score + momentum_score + support_score + volatility_score
    total_score = max(0.0, min(100.0, total_score))

    # 判定评级与操作指引
    if total_score >= 85.0:
        grade = "【强烈看多 · Strong Bullish】"
        action = "多头共振共振加速，建议积极顺势跟进或坚定持股"
    elif total_score >= 70.0:
        grade = "【偏多进攻 · Bullish】"
        action = "上升通道保持完好，逢回调中轨附近可分批介入"
    elif total_score >= 50.0:
        grade = "【震荡蓄势 · Neutral】"
        action = "多空相对平衡，建议多看少动，控制半仓观望"
    elif total_score >= 35.0:
        grade = "【偏空防御 · Bearish】"
        action = "下行承压明显，反弹注意逢高减仓避险"
    else:
        grade = "【高危回避 · Strong Bearish】"
        action = "趋势破位形态恶化，严守止损纪律，空仓回避"

    snapshot = {
        "ma5": round(c_ma5, 2) if c_ma5 else None,
        "ma10": round(c_ma10, 2) if c_ma10 else None,
        "ma20": round(c_ma20, 2) if c_ma20 else None,
        "macd_dif": round(c_dif, 3),
        "macd_dea": round(c_dea, 3),
        "macd_bar": round(c_macd, 3),
        "rsi6": round(c_rsi, 1),
        "boll_upper": round(c_upper, 2) if c_upper else None,
        "boll_mid": round(c_mid, 2) if c_mid else None,
        "boll_lower": round(c_lower, 2) if c_lower else None,
        "kdj_k": round(k_vals[-1], 1) if k_vals else None,
        "kdj_d": round(d_vals[-1], 1) if d_vals else None,
        "kdj_j": round(j_vals[-1], 1) if j_vals else None
    }

    dim_scores = {
        "trend": round(trend_score, 1),
        "momentum": round(momentum_score, 1),
        "support": round(support_score, 1),
        "volatility": round(volatility_score, 1)
    }

    return QuantitativeReport(
        code=code,
        name=name,
        current_price=curr_price,
        score=total_score,
        grade=grade,
        action=action,
        dimension_scores=dim_scores,
        signals=signals,
        indicators_snapshot=snapshot
    )
