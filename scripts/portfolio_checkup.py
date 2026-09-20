#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-021: 持仓组合风险体检与动态止盈止损 (v1)
============================================================
前置：**持仓必须已核实**。`config/stock_config.json` 中 `portfolio` 非空但 `portfolio_verified`
不等于 `true` 时，本模块**拒绝产出任何结论**并说明原因——绝不把样例/占位持仓当成真实持仓，
也绝不替用户把「已核实」标记打上。

体检规则（每条规则独立输出触发状态与所用真实数值）
--------------------------------------------------
静态规则（阈值来自 `alert_rules`，可配置）：
- S1 止盈达标：累计收益率 ≥ take_profit_ratio（默认 +20%）
- S2 止损击穿：累计收益率 ≤ stop_loss_ratio（默认 -8%）
- S3 日内异动：当日涨跌幅 ≥ daily_surge_ratio（默认 +5%）或 ≤ daily_plunge_ratio（默认 -5%）

动态规则（阈值来自 `dynamic_rules`，可配置）：
- D1 MA20 破位：最新收盘价跌破 MA20
- D2 日线卖点：日线出现 S1 / S2 / S3 卖点（复用 REQ-019 引擎，规则版本随信号携带）
- D3 移动止盈回撤：自持仓期内最高价回撤 ≥ trailing_drawdown_ratio（默认 8%）

口径与边界
----------
- 行情：真实多源行情，`allow_mock` 恒为 False；任一必需字段缺失即抛错，不补 0、不猜。
- 日线：可信不复权历史。来源不可用回落 `stale` 缓存时，MA20 与移动止盈仍可计算（慢变量），
  但会标注 `data_status` 与 `data_last_bar_date`，并提示该日期不一定是最新交易日。
- 峰值口径：`buy_date` 之后（含）的日线最高价；若 `buy_date` 早于来源覆盖起点，
  明确标注 `peak_coverage_incomplete=true`，不假装覆盖完整。
- 输出为按既定纪律逐条触发的结构化事实与资金口径，**不构成投资建议，不承诺收益**。
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, BASE_DIR)

# 模块级导入：既与 stock_portfolio.py 的既有做法一致，也让真实来源可被测试注入替换
from scripts.stock_data_engine import get_batch_quotes          # noqa: E402
from scripts.chanlun_signals import analyze_code, fetch_daily_bars  # noqa: E402

RULE_VERSION = "REQ-021/v1"

DEFAULT_STATIC_RULES = {
    "take_profit_ratio": 0.20,
    "stop_loss_ratio": -0.08,
    "daily_surge_ratio": 0.05,
    "daily_plunge_ratio": -0.05,
}

DEFAULT_DYNAMIC_RULES = {
    "ma_period": 20,
    "trailing_drawdown_ratio": 0.08,
    "enable_ma_breakdown": True,
    "enable_chanlun_sell": True,
    "enable_trailing_stop": True,
}

LEVEL_ORDER = {"DANGER": 0, "WARNING": 1, "SUCCESS": 2, "INFO": 3}


def _round(value, digits=2):
    if value is None:
        return None
    return round(float(value), digits)


def _rule(rule_id: str, label: str, level: str, triggered: bool, detail: str,
          values: Optional[Dict[str, Any]] = None, status: str = "evaluated") -> Dict[str, Any]:
    """
    单条规则的统一输出结构。
    status: evaluated（已判定）| unavailable（数据未获取，无法判定）| disabled（规则关闭）
    """
    return {"rule_id": rule_id, "label": label, "level": level, "triggered": bool(triggered),
            "status": status, "detail": detail, "values": values or {}}


def resolve_config_path(config_path: Optional[str] = None) -> str:
    """
    解析持仓配置文件路径。优先级：显式参数 > DSH_STOCK_CONFIG 环境变量 > 默认路径。
    环境变量用于同一台机器上维护多份持仓底册（例如实盘/模拟分开），
    也使自动化测试能在不触碰真实底册的前提下验证完整渲染路径。
    """
    if config_path:
        return config_path
    # 空字符串环境变量等同未设置，否则会得到空路径
    return (os.environ.get("DSH_STOCK_CONFIG") or "").strip() or \
        os.path.join(BASE_DIR, "config", "stock_config.json")


def load_stock_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    with open(resolve_config_path(config_path), "r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_portfolio(raw_positions: List[Dict[str, Any]], verified_flag: Any) -> Tuple[bool, str]:
    """持仓核实门禁。返回 (是否可体检, 说明)。"""
    if not raw_positions:
        return False, "持仓底册为空，未配置任何持仓，无可体检内容"
    if verified_flag is not True:
        return False, ("持仓底册尚未确认为真实持仓（config/stock_config.json 的 portfolio_verified 不为 true）。"
                       "本项目不对未核实持仓产出任何盈亏或风险结论——请核实每条持仓的代码、股数、成本价与买入日期后，"
                       "由持仓本人将该标记置为 true")
    return True, "持仓底册已确认为真实持仓"


def _position_static_rules(position: Dict[str, Any], static: Dict[str, Any]) -> List[Dict[str, Any]]:
    pnl_pct = position["total_pnl_pct"]
    daily_pct = position["daily_pnl_pct"]
    tp = static["take_profit_ratio"] * 100.0
    sl = static["stop_loss_ratio"] * 100.0
    surge = static["daily_surge_ratio"] * 100.0
    plunge = static["daily_plunge_ratio"] * 100.0
    rules: List[Dict[str, Any]] = []

    rules.append(_rule(
        "S1_take_profit", "止盈达标", "SUCCESS", pnl_pct >= tp,
        (f"累计收益率 {_round(pnl_pct)}% 已达设定止盈线 {_round(tp)}%，浮盈 {_round(position['total_pnl'])} 元"
         if pnl_pct >= tp else f"累计收益率 {_round(pnl_pct)}% 未达止盈线 {_round(tp)}%"),
        {"total_pnl_pct": _round(pnl_pct), "threshold_pct": _round(tp), "total_pnl": _round(position["total_pnl"])}))

    rules.append(_rule(
        "S2_stop_loss", "止损击穿", "DANGER", pnl_pct <= sl,
        (f"累计亏损率 {_round(pnl_pct)}% 已击穿设定止损线 {_round(sl)}%，浮亏 {_round(position['total_pnl'])} 元"
         if pnl_pct <= sl else f"累计收益率 {_round(pnl_pct)}% 未触及止损线 {_round(sl)}%"),
        {"total_pnl_pct": _round(pnl_pct), "threshold_pct": _round(sl), "total_pnl": _round(position["total_pnl"])}))

    rose = daily_pct >= surge
    fell = daily_pct <= plunge
    rules.append(_rule(
        "S3_daily_move", "日内异动", "INFO" if rose else "WARNING", rose or fell,
        (f"当日{'上涨' if rose else '下跌'} {_round(abs(daily_pct))}%，超过异动阈值 "
         f"{_round(surge if rose else abs(plunge))}%，当日盈亏 {_round(position['daily_pnl'])} 元"
         if (rose or fell) else f"当日涨跌幅 {_round(daily_pct)}%，未达异动阈值"),
        {"daily_pnl_pct": _round(daily_pct), "threshold_pct": _round(surge if rose else abs(plunge)),
         "daily_pnl": _round(position["daily_pnl"])}))
    return rules


def _position_dynamic_rules(position: Dict[str, Any], dynamic: Dict[str, Any],
                            bars: Optional[List[Dict[str, Any]]], bars_error: Optional[str],
                            data_status: str, coverage_start: Optional[str],
                            sell_signals: Optional[List[Dict[str, Any]]],
                            sell_error: Optional[str]) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    buy_date = str(position.get("buy_date") or "")
    current_price = position["current_price"]

    # ---- D1 MA20 破位 ----
    ma_period = int(dynamic.get("ma_period", 20))
    if not dynamic.get("enable_ma_breakdown", True):
        rules.append(_rule("D1_ma_breakdown", f"MA{ma_period} 破位", "WARNING", False,
                           "该规则已在配置中关闭", status="disabled"))
    elif not bars or len(bars) < ma_period:
        rules.append(_rule("D1_ma_breakdown", f"MA{ma_period} 破位", "WARNING", False,
                           f"日线可用 {len(bars) if bars else 0} 根，不足 {ma_period} 根，无法计算均线，"
                           f"不判定破位（{bars_error or '数据未获取'}）", status="unavailable"))
    else:
        window = [b["close"] for b in bars[-ma_period:]]
        ma_value = sum(window) / len(window)
        below = current_price < ma_value
        rules.append(_rule(
            "D1_ma_breakdown", f"MA{ma_period} 破位", "WARNING", below,
            (f"现价 {_round(current_price)} 低于 MA{ma_period} {_round(ma_value)}"
             f"（偏离 {_round((current_price - ma_value) / ma_value * 100)}%）"
             if below else f"现价 {_round(current_price)} 仍站上 MA{ma_period} {_round(ma_value)}"),
            {"ma_period": ma_period, "ma_value": _round(ma_value), "current_price": _round(current_price),
             "deviation_pct": _round((current_price - ma_value) / ma_value * 100) if ma_value else None,
             "data_status": data_status, "data_last_bar_date": str(bars[-1].get("date") or "")[:10]}))

    # ---- D2 日线卖点 ----
    if not dynamic.get("enable_chanlun_sell", True):
        rules.append(_rule("D2_chanlun_sell", "日线卖点", "WARNING", False, "该规则已在配置中关闭", status="disabled"))
    elif sell_signals is None:
        rules.append(_rule("D2_chanlun_sell", "日线卖点", "WARNING", False,
                           f"日线结构信号未获取，无法判定卖点（{sell_error or '数据未获取'}）", status="unavailable"))
    else:
        triggered = len(sell_signals) > 0
        types = "、".join(sorted({s["signal_type"] for s in sell_signals})) if triggered else ""
        actionable = [s for s in sell_signals if s.get("actionable")]
        detail = (f"日线出现卖点 {types}；其中可执行 {len(actionable)} 条"
                  if triggered else "日线未出现 S1/S2/S3 卖点")
        rules.append(_rule(
            "D2_chanlun_sell", "日线卖点", "WARNING", triggered, detail,
            {"signal_types": sorted({s["signal_type"] for s in sell_signals}) if triggered else [],
             "signal_count": len(sell_signals), "actionable_count": len(actionable),
             "signals": [{"signal_type": s["signal_type"], "time": s.get("time"),
                          "status": s.get("status"), "actionable": s.get("actionable"),
                          "stop_price": s.get("stop_price"), "reason": s.get("reason"),
                          "rule_version": s.get("rule_version")} for s in sell_signals]}))

    # ---- D3 移动止盈回撤 ----
    ratio = float(dynamic.get("trailing_drawdown_ratio", 0.08))
    if not dynamic.get("enable_trailing_stop", True):
        rules.append(_rule("D3_trailing_stop", "移动止盈回撤", "WARNING", False,
                           "该规则已在配置中关闭", status="disabled"))
    elif not bars:
        rules.append(_rule("D3_trailing_stop", "移动止盈回撤", "WARNING", False,
                           f"日线未获取，无法确定持仓期最高价，不回退用现价冒充峰值（{bars_error or '数据未获取'}）",
                           status="unavailable"))
    else:
        held = [b for b in bars if not buy_date or str(b.get("date") or "")[:10] >= buy_date]
        coverage_incomplete = bool(buy_date and coverage_start and buy_date < str(coverage_start))
        if not held:
            rules.append(_rule("D3_trailing_stop", "移动止盈回撤", "WARNING", False,
                               f"日线覆盖区间内没有 {buy_date} 之后的K线，无法确定持仓期最高价", status="unavailable"))
        else:
            peak = max(b["high"] for b in held)
            drawdown = (peak - current_price) / peak * 100 if peak > 0 else 0.0
            triggered = drawdown >= ratio * 100.0
            note = "；注意来源覆盖起点晚于买入日，峰值可能被低估" if coverage_incomplete else ""
            rules.append(_rule(
                "D3_trailing_stop", "移动止盈回撤", "WARNING", triggered,
                (f"自持仓期最高价 {_round(peak)} 回撤 {_round(drawdown)}%，已达移动止盈阈值 "
                 f"{_round(ratio * 100)}%{note}"
                 if triggered else f"自持仓期最高价 {_round(peak)} 回撤 {_round(drawdown)}%，未达阈值 {_round(ratio * 100)}%{note}"),
                {"peak_price": _round(peak), "peak_date": max(held, key=lambda b: b["high"]).get("date"),
                 "current_price": _round(current_price), "drawdown_pct": _round(drawdown),
                 "threshold_pct": _round(ratio * 100), "buy_date": buy_date,
                 "peak_coverage_incomplete": coverage_incomplete,
                 "data_status": data_status, "data_last_bar_date": str(bars[-1].get("date") or "")[:10]}))
    return rules


def run_checkup(config_path: Optional[str] = None, *, allow_stale: bool = True) -> Dict[str, Any]:
    """
    执行持仓体检。未核实的持仓底册会直接返回 status='unverified'，不产出任何结论。
    """
    config = load_stock_config(config_path)
    raw_positions = config.get("portfolio") or []
    verified = config.get("portfolio_verified")

    report: Dict[str, Any] = {
        "rule_version": RULE_VERSION,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "static_rules": {**DEFAULT_STATIC_RULES, **(config.get("alert_rules") or {})},
        "dynamic_rules": {**DEFAULT_DYNAMIC_RULES, **(config.get("dynamic_rules") or {})},
        "positions": [], "summary": {}, "warnings": [],
        "disclaimer": ("体检结果是按既定纪律逐条触发的结构化事实与资金口径，不构成投资建议，"
                       "不承诺收益；未触发的规则不代表没有风险。"),
    }

    ok, reason = verify_portfolio(raw_positions, verified)
    if not ok:
        return dict(report, status="unverified", verified=False, reason=reason,
                    portfolio_declared_count=len(raw_positions))

    static = report["static_rules"]
    dynamic = report["dynamic_rules"]

    codes = [str(item["code"]) for item in raw_positions]
    # allow_mock 恒为 False：真实行情缺失必须暴露，不允许补造
    quotes = get_batch_quotes(codes, allow_mock=False)
    quotes_map = {q.code: q for q in quotes}

    positions: List[Dict[str, Any]] = []
    all_rules: List[Dict[str, Any]] = []

    for raw in raw_positions:
        code = str(raw["code"])
        name = raw.get("name") or code
        quote = quotes_map.get(code)
        if quote is None:
            report["warnings"].append(f"{code} {name}：真实行情未获取，该持仓跳过体检，不计入任何结论")
            continue

        shares = int(raw.get("shares") or 0)
        cost_price = float(raw.get("cost_price") or 0.0)
        buy_date = str(raw.get("buy_date") or "")
        current_price = float(quote.price)
        prev_close = float(quote.prev_close)
        market_value = _round(shares * current_price)
        total_cost = _round(shares * cost_price)
        total_pnl = _round(market_value - total_cost)
        total_pnl_pct = _round((total_pnl / total_cost) * 100) if total_cost > 0 else None
        daily_pnl = _round(shares * (current_price - prev_close))
        daily_pnl_pct = _round((current_price - prev_close) / prev_close * 100) if prev_close > 0 else None

        position = {
            "code": code, "name": name, "shares": shares, "cost_price": _round(cost_price),
            "buy_date": buy_date, "notes": raw.get("notes") or "",
            "current_price": _round(current_price), "prev_close": _round(prev_close),
            "market_value": market_value, "total_cost": total_cost,
            "total_pnl": total_pnl, "total_pnl_pct": total_pnl_pct,
            "daily_pnl": daily_pnl, "daily_pnl_pct": daily_pnl_pct,
            "quote_source": getattr(quote, "source", "") or "",
        }

        # ---- 日线数据（MA / 峰值 / 卖点共用同一次取数） ----
        daily = fetch_daily_bars(code)
        bars = daily["bars"]
        bars_error = daily["error"]
        data_status = daily["data_status"]
        if data_status == "stale":
            report["warnings"].append(
                f"{code} {name}：日线来源当前不可用，已回落使用此前核验过的真实历史"
                f"（覆盖至 {daily['coverage_end']}）。慢变量规则仍可参考，但该日期不一定是最新交易日")
        if bars and data_status != "available" and not allow_stale:
            bars, bars_error, data_status = [], bars_error or "数据非最新且不允许使用缓存", "unavailable"

        sell_signals: Optional[List[Dict[str, Any]]] = None
        sell_error: Optional[str] = None
        if dynamic.get("enable_chanlun_sell", True):
            if not bars:
                sell_error = bars_error or "日线未获取"
            else:
                try:
                    analysis = analyze_code(code, name, daily_bars=bars, m30_bars=[])
                    sell_signals = [s for s in (analysis.get("signals") or [])
                                    if s.get("side") == "sell" and s.get("period") == "daily"]
                    if analysis.get("errors", {}).get("daily"):
                        sell_error = analysis["errors"]["daily"]
                except Exception as exc:  # noqa: BLE001
                    sell_error = f"日线结构计算失败: {exc}"

        rules = _position_static_rules(position, static)
        rules += _position_dynamic_rules(position, dynamic, bars, bars_error, data_status,
                                         daily.get("coverage_start"), sell_signals, sell_error)

        position["rules"] = rules
        position["triggered_rules"] = [r["rule_id"] for r in rules if r["triggered"]]
        levels = [r["level"] for r in rules if r["triggered"]]
        position["highest_level"] = min(levels, key=lambda x: LEVEL_ORDER.get(x, 9)) if levels else None
        position["unavailable_rules"] = [r["rule_id"] for r in rules if r["status"] == "unavailable"]
        position["data_status"] = data_status
        position["data_last_bar_date"] = str(bars[-1].get("date") or "")[:10] if bars else None
        all_rules.extend(rules)
        positions.append(position)

    total_market_value = _round(sum(p["market_value"] for p in positions))
    total_cost = _round(sum(p["total_cost"] for p in positions))
    for p in positions:
        p["weight_pct"] = _round(p["market_value"] / total_market_value * 100) if total_market_value else None

    triggered = [r for r in all_rules if r["triggered"]]
    report["positions"] = positions
    report["summary"] = {
        "position_count": len(positions),
        "skipped_count": len(raw_positions) - len(positions),
        "total_market_value": total_market_value,
        "total_cost": total_cost,
        "total_floating_pnl": _round(total_market_value - total_cost),
        "total_floating_pnl_pct": _round((total_market_value - total_cost) / total_cost * 100) if total_cost else None,
        "today_floating_pnl": _round(sum(p["daily_pnl"] for p in positions)),
        "triggered_count": len(triggered),
        "triggered_by_rule": {rid: sum(1 for r in triggered if r["rule_id"] == rid)
                              for rid in sorted({r["rule_id"] for r in triggered})},
        "unavailable_count": sum(1 for r in all_rules if r["status"] == "unavailable"),
        "danger_count": sum(1 for r in triggered if r["level"] == "DANGER"),
        "warning_count": sum(1 for r in triggered if r["level"] == "WARNING"),
    }
    report["status"] = "available" if positions else "unavailable"
    if not positions:
        report["reason"] = "全部持仓的真实行情均未获取，本轮未产出任何体检结论"
    return report


def format_report(report: Dict[str, Any]) -> str:
    if report["status"] == "unverified":
        return (f"⛔ 无法体检：{report['reason']}\n"
                f"   持仓底册声明的条数：{report['portfolio_declared_count']}（未计入任何统计）\n"
                f"   规则版本：{report['rule_version']}")
    lines = [f"💼 持仓组合风险体检（规则版本 {report['rule_version']}）",
             f"计算时间：{report['computed_at']}"]
    s = report["summary"]
    lines.append(f"持仓 {s['position_count']} 只（跳过 {s['skipped_count']} 只）· "
                 f"市值 {s['total_market_value']:,.2f} · 浮动盈亏 {s['total_floating_pnl']:,.2f}"
                 f"（{s['total_floating_pnl_pct']}%）· 当日盈亏 {s['today_floating_pnl']:,.2f}")
    lines.append(f"触发规则 {s['triggered_count']} 条：危险 {s['danger_count']} / 警示 {s['warning_count']}；"
                 f"无法判定 {s['unavailable_count']} 条")
    lines.append("")
    for p in report["positions"]:
        head = (f"【{p['name']} {p['code']}】{p['shares']}股 成本 {p['cost_price']}"
                f" 现价 {p['current_price']} 盈亏 {p['total_pnl']}（{p['total_pnl_pct']}%）"
                f" 当日 {p['daily_pnl_pct']}% 仓位 {p['weight_pct']}%")
        lines.append(head)
        if not p["rules"]:
            lines.append("  └─ 未配置任何规则")
        for r in p["rules"]:
            mark = "🔴" if r["triggered"] and r["level"] == "DANGER" else (
                "🟡" if r["triggered"] and r["level"] == "WARNING" else (
                    "🟢" if r["triggered"] else "⚪"))
            if r["status"] == "unavailable":
                mark = "❓"
            elif r["status"] == "disabled":
                mark = "⏸"
            lines.append(f"  {mark} [{r['rule_id']}] {r['label']}：{r['detail']}")
        if p["data_status"] != "available":
            lines.append(f"  ⚠️ 日线数据状态 {p['data_status']}（最后一根 {p['data_last_bar_date']}）")
    for w in report["warnings"]:
        lines.append(f"⚠️ {w}")
    lines.append("")
    lines.append(report["disclaimer"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="REQ-021 持仓组合风险体检与动态止盈止损")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--config", default=None, help="指定持仓配置文件路径")
    parser.add_argument("--no-stale", action="store_true",
                        help="日线数据非最新时拒绝使用缓存，相关规则判为无法判定")
    args = parser.parse_args(argv)
    try:
        report = run_checkup(args.config, allow_stale=not args.no_stale)
    except RuntimeError as exc:
        print(f"⛔ 体检中止：{exc}")
        return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"⛔ 体检中止：{exc}")
        return 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(format_report(report))
    return 0 if report["status"] == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
