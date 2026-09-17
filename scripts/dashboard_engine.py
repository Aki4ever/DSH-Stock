#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 全市场 A 股宏观全景仪表盘统计聚合引擎 (Dashboard Aggregation Engine)
版本: v1.6.0

功能:
针对全市场 4,601 只 A 股，高精度聚合计算 10 大核心维度的 4 大统计学指标:
[ 最小值 (Min), 最大值 (Max), 平均值 (Mean), 中位数 (Median) ]

10 大量化维度:
1. 市值 / 总市值 (亿)
2. 流通市值 (亿)
3. 最新股价 (元)
4. 市盈率 PE
5. 最新涨跌幅 (%)
6. 当日振幅 (%)
7. 累计分红次数 (次)
8. 上市总时长 (年)
9. 十大流通股东占比 (%)
10. 十大股东占比 (%)

附加宏观分布透视:
- 全市场涨跌家数统计 (上涨、下跌、平盘、涨停>9.5%、跌停<-9.5%)
- 涨跌幅区间梯度分布 (8个梯度直方图)
- 市值梯队金字塔 (超千亿、300-1000亿、100-300亿、50-100亿、50亿以下)
"""

import math
import statistics
from typing import Dict, List, Any


def compute_dim_stats(values: List[float], digits: int = 2) -> Dict[str, float]:
    """计算单个维度的最小值、最大值、平均值、中位数"""
    valid = [v for v in values if v is not None and not math.isnan(v)]
    if not valid:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "count": 0}
    
    valid.sort()
    v_min = round(valid[0], digits)
    v_max = round(valid[-1], digits)
    v_mean = round(sum(valid) / len(valid), digits)
    v_median = round(statistics.median(valid), digits)
    return {
        "min": v_min,
        "max": v_max,
        "mean": v_mean,
        "median": v_median,
        "count": len(valid)
    }


def compute_market_overview(stocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成全景仪表盘完整统计数据"""
    if not stocks:
        return {}

    total_count = len(stocks)

    # 提取各维度数据列表
    market_caps = []
    circ_caps = []
    prices = []
    pes = []
    changes = []
    amplitudes = []
    dividends = []
    listing_years_list = []
    top10_circs = []
    top10_holds = []

    # 涨跌分布计数
    up_count = 0
    down_count = 0
    flat_count = 0
    limit_up_count = 0
    limit_down_count = 0

    # 涨跌幅梯度直方图 buckets
    buckets = {
        "down_deep": 0,    # < -7%
        "down_mid": 0,     # -7% ~ -3%
        "down_mild": 0,    # -3% ~ 0%
        "flat": 0,         # == 0%
        "up_mild": 0,      # 0% ~ 3%
        "up_mid": 0,       # 3% ~ 7%
        "up_high": 0       # > 7%
    }

    # 市值梯队金字塔
    cap_tiers = {
        "mega": 0,      # >= 1000 亿
        "large": 0,     # 300 ~ 1000 亿
        "mid": 0,       # 100 ~ 300 亿
        "small": 0,     # 50 ~ 100 亿
        "micro": 0      # < 50 亿
    }

    total_market_cap_sum = 0.0
    total_circ_cap_sum = 0.0

    for s in stocks:
        cap = float(s.get("market_cap") or 0.0)
        circ = float(s.get("circulating_cap") or 0.0)
        p = float(s.get("price") or 0.0)
        pe = float(s.get("pe") or 0.0)
        chg = float(s.get("change_pct") or 0.0)
        high = float(s.get("high") or p)
        low = float(s.get("low") or p)
        prev = float(s.get("prev_close") or p)
        div = float(s.get("dividend_count") or 0.0)
        years = float(s.get("listing_years") or 0.0)
        t_circ = float(s.get("top10_circ_hold_pct") or 0.0)
        t_hold = float(s.get("top10_hold_pct") or 0.0)

        # 振幅计算
        amp = round(((high - low) / prev * 100.0), 2) if prev > 0 else abs(chg)

        if cap > 0: market_caps.append(cap); total_market_cap_sum += cap
        if circ > 0: circ_caps.append(circ); total_circ_cap_sum += circ
        if p > 0: prices.append(p)
        if pe > 0: pes.append(pe)
        changes.append(chg)
        amplitudes.append(amp)
        dividends.append(div)
        listing_years_list.append(years)
        if t_circ > 0: top10_circs.append(t_circ)
        if t_hold > 0: top10_holds.append(t_hold)

        # 统计涨跌
        if chg > 0.001:
            up_count += 1
            if chg >= 9.5: limit_up_count += 1
        elif chg < -0.001:
            down_count += 1
            if chg <= -9.5: limit_down_count += 1
        else:
            flat_count += 1

        # 梯度直方图归类
        if chg <= -7.0: buckets["down_deep"] += 1
        elif -7.0 < chg <= -3.0: buckets["down_mid"] += 1
        elif -3.0 < chg < 0: buckets["down_mild"] += 1
        elif chg == 0: buckets["flat"] += 1
        elif 0 < chg <= 3.0: buckets["up_mild"] += 1
        elif 3.0 < chg <= 7.0: buckets["up_mid"] += 1
        else: buckets["up_high"] += 1

        # 市值梯队归类
        if cap >= 1000: cap_tiers["mega"] += 1
        elif cap >= 300: cap_tiers["large"] += 1
        elif cap >= 100: cap_tiers["mid"] += 1
        elif cap >= 50: cap_tiers["small"] += 1
        else: cap_tiers["micro"] += 1

    # 聚合 10 大维度核心指标
    dimensions = {
        "market_cap": {
            "title": "总市值",
            "unit": "亿元",
            "stats": compute_dim_stats(market_caps, digits=1),
            "desc": "全市场上市公司总资产市场公允估值"
        },
        "circulating_cap": {
            "title": "流通市值",
            "unit": "亿元",
            "stats": compute_dim_stats(circ_caps, digits=1),
            "desc": "可在二级市场上自由流通交易的股票市值"
        },
        "price": {
            "title": "最新股价",
            "unit": "元",
            "stats": compute_dim_stats(prices, digits=2),
            "desc": "全市场每股实时交易价格分布"
        },
        "pe": {
            "title": "市盈率 PE",
            "unit": "倍",
            "stats": compute_dim_stats(pes, digits=1),
            "desc": "当前股价与每股收益的比率 (仅统计盈利标的)"
        },
        "change_pct": {
            "title": "最新涨跌幅",
            "unit": "%",
            "stats": compute_dim_stats(changes, digits=2),
            "desc": "全市场所有标的日内收益率分布"
        },
        "amplitude": {
            "title": "当日振幅",
            "unit": "%",
            "stats": compute_dim_stats(amplitudes, digits=2),
            "desc": "日内最高价与最低价波动的相对空间"
        },
        "dividend_count": {
            "title": "分红次数",
            "unit": "次",
            "stats": compute_dim_stats(dividends, digits=1),
            "desc": "上市以来累计实施现金或股利分配次数"
        },
        "listing_years": {
            "title": "上市总时长",
            "unit": "年",
            "stats": compute_dim_stats(listing_years_list, digits=1),
            "desc": "从 IPO 上市至今的总存续时间跨度"
        },
        "top10_circ_pct": {
            "title": "十大流通股东占比",
            "unit": "%",
            "stats": compute_dim_stats(top10_circs, digits=2),
            "desc": "主力机构与前十大流通主体筹码锁定度"
        },
        "top10_hold_pct": {
            "title": "十大股东占比",
            "unit": "%",
            "stats": compute_dim_stats(top10_holds, digits=2),
            "desc": "核心控制人与大股东总持股权益集中度"
        }
    }

    return {
        "summary": {
            "total_stocks": total_count,
            "total_market_cap": round(total_market_cap_sum, 1),
            "total_circ_cap": round(total_circ_cap_sum, 1),
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "limit_up_count": limit_up_count,
            "limit_down_count": limit_down_count,
            "up_ratio": round((up_count / total_count * 100.0), 1) if total_count > 0 else 0.0
        },
        "dimensions": dimensions,
        "charts": {
            "change_distribution": buckets,
            "market_cap_tiers": cap_tiers
        }
    }
