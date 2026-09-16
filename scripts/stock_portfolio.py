#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 股票持仓投资组合管理与风险预警中枢 (Stock Portfolio & Alert Center)
版本: v1.0.0
遵循规范: rules/system/meta_rules.md 第五条（自律安全）、第十三条（风险揭示）
"""

import os
import json
from typing import List, Dict, Any, Optional, Tuple
from scripts.stock_data_engine import StockQuote, get_quote, get_batch_quotes


class PositionItem:
    """单只持仓标的明细"""
    def __init__(
        self,
        code: str,
        name: str,
        shares: int,
        cost_price: float,
        current_price: float,
        prev_close: float,
        buy_date: str = "",
        notes: str = ""
    ):
        self.code = code
        self.name = name
        self.shares = int(shares)
        self.cost_price = float(cost_price)
        self.current_price = float(current_price)
        self.prev_close = float(prev_close) if prev_close > 0 else self.current_price
        self.buy_date = buy_date
        self.notes = notes

        # 计算市值与成本
        self.market_value = round(self.shares * self.current_price, 2)
        self.total_cost = round(self.shares * self.cost_price, 2)

        # 累计浮动盈亏
        self.total_pnl = round(self.market_value - self.total_cost, 2)
        self.total_pnl_pct = round((self.total_pnl / self.total_cost) * 100, 2) if self.total_cost > 0 else 0.0

        # 当日盈亏变动
        self.daily_pnl = round(self.shares * (self.current_price - self.prev_close), 2)
        self.daily_pnl_pct = round(((self.current_price - self.prev_close) / self.prev_close) * 100, 2) if self.prev_close > 0 else 0.0

        # 占总持仓市值权重
        self.weight_pct = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "shares": self.shares,
            "cost_price": self.cost_price,
            "current_price": self.current_price,
            "prev_close": self.prev_close,
            "market_value": self.market_value,
            "total_cost": self.total_cost,
            "total_pnl": self.total_pnl,
            "total_pnl_pct": self.total_pnl_pct,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl_pct,
            "weight_pct": self.weight_pct,
            "buy_date": self.buy_date,
            "notes": self.notes
        }


class PortfolioSummary:
    """投资组合全景汇总"""
    def __init__(self, positions: List[PositionItem]):
        self.positions = positions
        self.total_cost = round(sum(p.total_cost for p in positions), 2)
        self.total_market_value = round(sum(p.market_value for p in positions), 2)
        self.total_floating_pnl = round(self.total_market_value - self.total_cost, 2)
        self.total_floating_pnl_pct = round(
            (self.total_floating_pnl / self.total_cost) * 100, 2
        ) if self.total_cost > 0 else 0.0
        self.today_floating_pnl = round(sum(p.daily_pnl for p in positions), 2)

        # 回填每只股票在组合中的仓位权重
        if self.total_market_value > 0:
            for p in self.positions:
                p.weight_pct = round((p.market_value / self.total_market_value) * 100, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_market_value": self.total_market_value,
            "total_cost": self.total_cost,
            "total_floating_pnl": self.total_floating_pnl,
            "total_floating_pnl_pct": self.total_floating_pnl_pct,
            "today_floating_pnl": self.today_floating_pnl,
            "position_count": len(self.positions),
            "positions": [p.to_dict() for p in self.positions]
        }


class AlertMessage:
    """风险预警消息"""
    def __init__(self, level: str, code: str, name: str, title: str, description: str, suggestion: str):
        self.level = level  # INFO, WARNING, DANGER, SUCCESS
        self.code = code
        self.name = name
        self.title = title
        self.description = description
        self.suggestion = suggestion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "suggestion": self.suggestion
        }


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """读取股票工程总配置"""
    if config_path is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config", "stock_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_portfolio_summary(config_path: Optional[str] = None, allow_mock: bool = True) -> Tuple[PortfolioSummary, List[AlertMessage]]:
    """
    根据配置文件加载持仓底册，联网获取实时行情并生成全景投资组合报告与预警清单
    """
    cfg = load_config(config_path)
    raw_positions = cfg.get("portfolio", [])
    alert_rules = cfg.get("alert_rules", {})

    tp_ratio = alert_rules.get("take_profit_ratio", 0.20) * 100.0  # +20%
    sl_ratio = alert_rules.get("stop_loss_ratio", -0.08) * 100.0   # -8%
    surge_ratio = alert_rules.get("daily_surge_ratio", 0.05) * 100.0
    plunge_ratio = alert_rules.get("daily_plunge_ratio", -0.05) * 100.0

    codes = [item["code"] for item in raw_positions]
    quotes = get_batch_quotes(codes, allow_mock=allow_mock)
    quotes_map = {q.code: q for q in quotes}

    positions: List[PositionItem] = []
    alerts: List[AlertMessage] = []

    for raw in raw_positions:
        code = raw["code"]
        name = raw.get("name", code)
        shares = raw.get("shares", 0)
        cost = raw.get("cost_price", 0.0)
        buy_date = raw.get("buy_date", "")
        notes = raw.get("notes", "")

        q = quotes_map.get(code)
        curr_price = q.price if q else cost
        prev_close = q.prev_close if q else curr_price

        pos = PositionItem(
            code=code,
            name=name,
            shares=shares,
            cost_price=cost,
            current_price=curr_price,
            prev_close=prev_close,
            buy_date=buy_date,
            notes=notes
        )
        positions.append(pos)

        # 触发预警检测
        # 1. 累计止盈预警
        if pos.total_pnl_pct >= tp_ratio:
            alerts.append(AlertMessage(
                level="SUCCESS",
                code=code,
                name=name,
                title="🎯 达到目标止盈线",
                description=f"累计收益率达到 {pos.total_pnl_pct:.2f}% (超设定目标 {tp_ratio:.1f}%)，浮盈 +{pos.total_pnl:,.2f} 元",
                suggestion="建议分批止盈锁定胜果，或上移动态移动止盈保护线"
            ))
        # 2. 累计止损预警
        elif pos.total_pnl_pct <= sl_ratio:
            alerts.append(AlertMessage(
                level="DANGER",
                code=code,
                name=name,
                title="🚨 触及硬性止损线",
                description=f"累计亏损率达到 {pos.total_pnl_pct:.2f}% (已击穿预警线 {sl_ratio:.1f}%)，浮亏 {pos.total_pnl:,.2f} 元",
                suggestion="坚决执行风控纪律，排查基本面恶化风险，避免深度套牢"
            ))

        # 3. 当日大幅异动预警
        if pos.daily_pnl_pct >= surge_ratio:
            alerts.append(AlertMessage(
                level="INFO",
                code=code,
                name=name,
                title="⚡ 日内放量大涨异动",
                description=f"今日单日暴涨 +{pos.daily_pnl_pct:.2f}%，单日贡献收益 +{pos.daily_pnl:,.2f} 元",
                suggestion="观察量能是否持续健康放大，警惕高位获利盘回吐"
            ))
        elif pos.daily_pnl_pct <= plunge_ratio:
            alerts.append(AlertMessage(
                level="WARNING",
                code=code,
                name=name,
                title="⚠️ 日内深度杀跌异动",
                description=f"今日单日暴跌 {pos.daily_pnl_pct:.2f}%，单日侵蚀收益 {pos.daily_pnl:,.2f} 元",
                suggestion="排查是否有突发消息面利空或行业黑天鹅，切忌盲目急抄底"
            ))

    summary = PortfolioSummary(positions)
    return summary, alerts
