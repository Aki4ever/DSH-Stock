#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-019: 缠论多周期买卖点引擎与信号雷达池 (v1)
============================================================
1. 买卖点完全分类：1B/2B/3B 买点 + S1/S2/S3 卖点（严格对称）
2. 区间套：日线定方向 + 30分钟定买点的嵌套确认；不满足嵌套时降级为单周期信号并显式标注
3. 结构化输出：signal_type / period / entry / stop / target / risk_pct / 建议股数 / 确认状态 / 规则版本 / 结构引用
4. 雷达池：批量扫描并落库，支持按类型/周期/时间窗查询

口径声明（不得越界表述）：
- 全部结构来自 scripts/chanlun_analysis.py 这一唯一计算入口；本模块只做买卖点判定与组合，不重复实现形态学。
- 中枢明确为「笔级中枢」，背离明确为「笔背离」，不等于完整趋势背驰。
- 数据缺失即不产出信号，绝不臆造价格、成交量或成交额。
- 本模块不承诺任何收益或胜率，输出仅为结构化事实与风控参数。
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

from scripts.chanlun_analysis import RULES as ANALYSIS_RULES, analyze_bars  # noqa: E402

RULE_VERSION = "REQ-019/v1"

SIGNAL_META = {
    "1B": {"side": "buy", "name": "第一类买点", "rule": "向下笔价格创出新低且MACD绝对柱面积减弱（笔级底背离）"},
    "2B": {"side": "buy", "name": "第二类买点", "rule": "下跌笔→反弹笔→回调笔，回调低点高于前一下跌笔低点"},
    "3B": {"side": "buy", "name": "第三类买点", "rule": "向上笔突破笔中枢上沿ZG，随后回抽笔低点不低于ZG"},
    "S1": {"side": "sell", "name": "第一类卖点", "rule": "向上笔价格创出新高且MACD绝对柱面积减弱（笔级顶背离）"},
    "S2": {"side": "sell", "name": "第二类卖点", "rule": "上涨笔→回调笔→反抽笔，反抽高点低于前一上涨笔高点"},
    "S3": {"side": "sell", "name": "第三类卖点", "rule": "向下笔跌破笔中枢下沿ZD，随后反抽笔高点不高于ZD"},
}

DEFAULT_TOTAL_FUND = 1000000.0
DEFAULT_MAX_RISK_RATIO = 0.02
DEFAULT_MAX_POSITION_RATIO = 0.30
MIN_BARS = 30
RESONANCE_WINDOW_PENS = 6
# 结构止损距离超过该比例时，仓位被压缩到极小，标注为「止损距离过大」而不是给出误导性的建议股数
MAX_ACTIONABLE_RISK_PCT = 15.0


def _round(value, digits=2):
    if value is None:
        return None
    return round(float(value), digits)


def _pen_index_by_end_index(pens: List[Dict[str, Any]], end_index: int) -> Optional[int]:
    for i, pen in enumerate(pens):
        if pen.get("end_index") == end_index:
            return i
    return None


def _structure_ref(pens: List[Dict[str, Any]], indices: List[int]) -> List[Dict[str, Any]]:
    """把参与判定的笔，收敛为可追溯的结构引用"""
    out = []
    for i in indices:
        if i is None or i < 0 or i >= len(pens):
            continue
        p = pens[i]
        out.append({
            "start_time": p["start_time"],
            "end_time": p["end_time"],
            "start_price": p["start_price"],
            "end_price": p["end_price"],
            "direction": p["direction"],
            "status": p.get("status"),
        })
    return out


def _make_signal(code, name, period, signal_type, pens, pen_indices,
                 entry_price, stop_price, target_price, reason,
                 status, pivot=None, extra=None) -> Dict[str, Any]:
    meta = SIGNAL_META[signal_type]
    is_buy = meta["side"] == "buy"
    risk_pct = None
    if entry_price and stop_price:
        risk_pct = ((entry_price - stop_price) / entry_price * 100) if is_buy else ((stop_price - entry_price) / entry_price * 100)
    structure = _structure_ref(pens, pen_indices)
    window_start = min((s["start_time"] for s in structure), default=None)
    window_end = max((s["end_time"] for s in structure), default=None)
    signal = {
        "code": code,
        "name": name,
        "period": period,
        "signal_type": signal_type,
        "signal_name": meta["name"],
        "side": meta["side"],
        "rule": meta["rule"],
        "rule_version": RULE_VERSION,
        "analysis_rules_version": ANALYSIS_RULES["version"],
        "time": structure[-1]["end_time"] if structure else None,
        "entry_price": _round(entry_price),
        "stop_price": _round(stop_price),
        "target_price": _round(target_price),
        "risk_pct": _round(risk_pct),
        "status": status,
        "reason": reason,
        "structure": structure,
        "structure_window": {"start": window_start, "end": window_end},
        "pivot": pivot,
    }
    if extra:
        signal.update(extra)
    return signal


def _pivot_ref(pivot: Dict[str, Any]) -> Dict[str, Any]:
    if not pivot:
        return None
    return {
        "start_time": pivot.get("start_time"), "end_time": pivot.get("end_time"),
        "zg": _round(pivot.get("zg")), "zd": _round(pivot.get("zd")),
        "level": pivot.get("level"), "status": pivot.get("status"),
    }


def detect_signals(analysis: Dict[str, Any], code: str, name: str, period: str,
                   current_price: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    从唯一计算入口的五类结构输出中判定买卖点。
    只使用 pens / pivots / divergences；不自行实现包含处理、分型、成笔或中枢。
    """
    if not analysis or analysis.get("status") != "available":
        return []
    pens = analysis.get("pens") or []
    pivots = analysis.get("pivots") or []
    divergences = analysis.get("divergences") or []
    dates = analysis.get("dates") or []
    if len(pens) < 3:
        return []

    entry = current_price if current_price is not None else pens[-1]["end_price"]
    signals: List[Dict[str, Any]] = []
    last_pen_is_final = lambda idx: idx >= len(pens) - 1  # noqa: E731

    # ---------------- 1B / S1: 笔级背离（与 build_divergences 规则完全一致，按笔定位以便判断确认状态） ----------------
    for div in divergences:
        pen_idx = None
        for i, pen in enumerate(pens):
            if pen["end_time"] == div["time"] and abs(pen["end_price"] - div["price"]) < 1e-9:
                pen_idx = i
                break
        if pen_idx is None:
            continue
        confirmed = not last_pen_is_final(pen_idx)  # 存在后续反向笔 → 已确认
        status = "confirmed" if confirmed else "provisional"
        ratio = (div["current_area"] / div["previous_area"]) if div.get("previous_area") else None
        area_text = f"{_round(div['current_area'], 4)} vs 前一同向笔 {_round(div['previous_area'], 4)}"
        if div["kind"] == "底背离":
            stop = div["price"]
            pivot = _pivot_ref(pivots[-1]) if pivots else None
            target = pivot["zg"] if (pivot and pivot["zg"] and pivot["zg"] > entry) else None
            signals.append(_make_signal(
                code, name, period, "1B", pens, [pen_idx], entry, stop, target,
                f"向下笔创出新低但MACD绝对柱面积减弱（{area_text}）" + ("" if target else "；上方无已识别笔中枢上沿，未给出目标位"),
                status, pivot))
        elif div["kind"] == "顶背离":
            stop = div["price"]
            pivot = _pivot_ref(pivots[-1]) if pivots else None
            target = pivot["zd"] if (pivot and pivot["zd"] and pivot["zd"] < entry) else None
            signals.append(_make_signal(
                code, name, period, "S1", pens, [pen_idx], entry, stop, target,
                f"向上笔创出新高但MACD绝对柱面积减弱（{area_text}）" + ("" if target else "；下方无已识别笔中枢下沿，未给出目标位"),
                status, pivot))
        if area_text and ratio is not None:
            signals[-1]["area_ratio"] = _round(ratio, 4)

    # ---------------- 2B / S2: 回踩不破前低 / 反抽不破前高 ----------------
    for i in range(max(0, len(pens) - 9), len(pens) - 2):
        a, b, c = pens[i], pens[i + 1], pens[i + 2]
        confirmed = not last_pen_is_final(i + 2)
        status = "confirmed" if confirmed else "provisional"
        if a["direction"] == -1 and b["direction"] == 1 and c["direction"] == -1:
            if c["end_price"] > a["end_price"] and b["end_price"] > a["end_price"]:
                stop = a["end_price"]
                pivot = _pivot_ref(pivots[-1]) if pivots else None
                target = pivot["zg"] if (pivot and pivot["zg"] and pivot["zg"] > entry) else None
                signals.append(_make_signal(
                    code, name, period, "2B", pens, [i, i + 1, i + 2], entry, stop, target,
                    f"底部反弹后回踩不创新低（前低 {_round(a['end_price'])} → 回踩 {_round(c['end_price'])}）",
                    status, pivot))
        if a["direction"] == 1 and b["direction"] == -1 and c["direction"] == 1:
            if c["end_price"] < a["end_price"] and b["end_price"] < a["end_price"]:
                stop = a["end_price"]
                pivot = _pivot_ref(pivots[-1]) if pivots else None
                target = pivot["zd"] if (pivot and pivot["zd"] and pivot["zd"] < entry) else None
                signals.append(_make_signal(
                    code, name, period, "S2", pens, [i, i + 1, i + 2], entry, stop, target,
                    f"顶部回调后反抽不创新高（前高 {_round(a['end_price'])} → 反抽 {_round(c['end_price'])}）",
                    status, pivot))

    # ---------------- 3B / S3: 笔中枢突破/跌破与回抽确认 ----------------
    for pivot in pivots:
        k = _pen_index_by_end_index(pens, pivot["end_index"])
        if k is None:
            continue
        zg, zd = pivot["zg"], pivot["zd"]
        nxt = pens[k + 1] if k + 1 < len(pens) else None
        after = pens[k + 2] if k + 2 < len(pens) else None
        pivot_ref = _pivot_ref(pivot)

        # 3B：突破 ZG 后回抽不跌破 ZG
        if nxt and nxt["direction"] == 1 and nxt["end_price"] > zg:
            if after and after["direction"] == -1 and after["end_price"] >= zg:
                status = "confirmed" if not last_pen_is_final(k + 2) else "provisional"
                signals.append(_make_signal(
                    code, name, period, "3B", pens, [k, k + 1, k + 2], entry, after["end_price"], None,
                    f"向上笔突破笔中枢上沿 ZG={_round(zg)}，回抽低点 {_round(after['end_price'])} 未跌破 ZG",
                    status, pivot_ref))
            elif not after or k + 1 == len(pens) - 1:
                # 刚完成突破、回抽尚未出现：仅作待确认提示，不冒充已完成的三买
                signals.append(_make_signal(
                    code, name, period, "3B", pens, [k, k + 1], entry, zg, None,
                    f"向上笔已突破笔中枢上沿 ZG={_round(zg)}，回抽确认笔尚未形成（待确认）",
                    "provisional", pivot_ref, extra={"stage": "breakout_pending_pullback"}))

        # S3：跌破 ZD 后反抽不回 ZD
        if nxt and nxt["direction"] == -1 and nxt["end_price"] < zd:
            if after and after["direction"] == 1 and after["end_price"] <= zd:
                status = "confirmed" if not last_pen_is_final(k + 2) else "provisional"
                signals.append(_make_signal(
                    code, name, period, "S3", pens, [k, k + 1, k + 2], entry, after["end_price"], None,
                    f"向下笔跌破笔中枢下沿 ZD={_round(zd)}，反抽高点 {_round(after['end_price'])} 未回到 ZD",
                    status, pivot_ref))
            elif not after or k + 1 == len(pens) - 1:
                signals.append(_make_signal(
                    code, name, period, "S3", pens, [k, k + 1], entry, zd, None,
                    f"向下笔已跌破笔中枢下沿 ZD={_round(zd)}，反抽确认笔尚未形成（待确认）",
                    "provisional", pivot_ref, extra={"stage": "breakdown_pending_rebound"}))

    # ---------------- 风险预算与去重 ----------------
    for signal in signals:
        apply_risk_budget(signal)
    return dedupe_signals(signals)


def dedupe_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一周期同一类型只保留最新一条，避免同一结构被重复计数。"""
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for signal in signals:
        key = (signal["period"], signal["signal_type"])
        cur = best.get(key)
        if cur is None or (signal.get("time") or "") > (cur.get("time") or ""):
            best[key] = signal
    ordered = sorted(best.values(), key=lambda s: (s["period"], s["signal_type"]))
    return ordered


def apply_risk_budget(signal: Dict[str, Any], total_fund: float = DEFAULT_TOTAL_FUND,
                      max_risk_ratio: float = DEFAULT_MAX_RISK_RATIO,
                      max_position_ratio: float = DEFAULT_MAX_POSITION_RATIO) -> Dict[str, Any]:
    """
    单笔最大风险敞口配资计算（沿用 REQ-007 的 2% 口径），并判定该信号当前是否可执行。

    可执行性判定（缺一不可，任一不满足即不得给出建议仓位）：
    1. 结构未破坏：买点的结构止损必须低于当前价，卖点的结构止损必须高于当前价。
       若买点止损高于当前价，说明价格已跌破该买点赖以成立的笔低点，该结构已被证伪。
    2. 止损距离可用：risk_pct 必须为正且不超过 MAX_ACTIONABLE_RISK_PCT，
       否则任何仓位都会被压到无意义的小数，给出股数反而误导。
    3. 结构已确认：status 必须为 confirmed；待确认（provisional）结构只作提示。

    仅输出资金管理参数，不构成投资建议、不承诺收益。
    """
    entry = signal.get("entry_price")
    stop = signal.get("stop_price")
    is_buy = signal.get("side") == "buy"
    signal["risk_budget"] = None
    signal["suggested_shares"] = None
    signal["suggested_capital"] = None

    if not entry or not stop or entry <= 0:
        signal["actionable"] = False
        signal["risk_budget_note"] = "缺少入场价或结构止损价，未计算建议仓位"
        return signal

    # 1. 结构破坏判定：价格已越过结构止损位
    structure_broken = (stop >= entry) if is_buy else (stop <= entry)
    signal["structure_broken"] = bool(structure_broken)
    if structure_broken:
        signal["actionable"] = False
        side_text = "买点赖以成立的笔低点" if is_buy else "卖点赖以成立的笔高点"
        signal["risk_budget_note"] = (
            f"结构已被证伪：当前价 {_round(entry)} 已穿越{side_text} {_round(stop)}，"
            f"该信号不作为可执行{'买' if is_buy else '卖'}点，也不给出建议股数"
        )
        return signal

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        signal["actionable"] = False
        signal["risk_budget_note"] = "止损价与入场价重合，未计算建议仓位"
        return signal

    risk_pct = (risk_per_share / entry) * 100
    if risk_pct > MAX_ACTIONABLE_RISK_PCT:
        signal["actionable"] = False
        signal["risk_budget_note"] = (
            f"结构止损距离 {_round(risk_pct)}% 超过 {MAX_ACTIONABLE_RISK_PCT}% 上限，"
            f"按该结构建仓的风险敞口过大，不给出建议股数"
        )
        return signal

    if signal.get("status") != "confirmed":
        signal["actionable"] = False
        signal["risk_budget_note"] = "结构尚未确认（待确认），仅作观察提示，不给出建议仓位"
        return signal

    max_loss = total_fund * max_risk_ratio
    shares = int(max_loss / risk_per_share / 100) * 100
    cap_shares = int((total_fund * max_position_ratio) / entry / 100) * 100
    shares = max(0, min(shares, cap_shares))
    signal["risk_budget"] = {
        "total_fund": total_fund, "max_risk_ratio": max_risk_ratio,
        "max_position_ratio": max_position_ratio, "max_loss_budget": _round(max_loss),
        "risk_per_share": _round(risk_per_share, 3),
    }
    signal["actionable"] = shares > 0
    signal["suggested_shares"] = shares
    signal["suggested_capital"] = _round(shares * entry)
    signal["risk_budget_note"] = (f"按单笔最大亏损 {_round(max_loss)} 元、"
                                  f"单只不超过总资金 {int(max_position_ratio*100)}% 计算")
    if shares == 0:
        signal["risk_budget_note"] += "；按 100 股整手取整后为 0 股，资金规模下无法按该结构建仓"
    return signal


# ============================================================
# 数据获取：全部为真实公开来源，缺失即返回空并说明，不推造
# ============================================================

def normalize_code(code: str) -> str:
    clean = (code or "").strip().lower()
    if clean.startswith(("sh", "sz", "bj")):
        return clean
    if clean.startswith(("6", "5", "9")):
        return f"sh{clean}"
    return f"sz{clean}"


def fetch_daily_bars(code: str, refresh: bool = False) -> Dict[str, Any]:
    """
    日线使用与产品同一套可信不复权历史服务（REQ-008/012 口径），不使用前复权数据。

    返回统一结构：
      {"bars": [...], "error": str|None, "data_status": "available"|"partial"|"stale"|"unavailable",
       "coverage_end": "YYYY-MM-DD"|None, "source": str, "provider_history_complete": bool}

    新鲜度口径（关键，不得含糊）：
    - `available` / `partial`：本次来源响应成功，覆盖区间可追溯到 `coverage_end`。
    - `stale`：来源当前不可用，回落到的**是此前已核验并落库的真实完整历史**。数据本身真实，
      但 `coverage_end` 可能不是最新交易日。结构解构可以继续使用它，
      但任何依赖「最新交易日」的判断（例如当日放量）都必须据此拒绝执行，不得把历史信号
      当作当日信号推送。
    - `unavailable`：无任何可用数据，调用方不得产出信号。
    """
    try:
        from scripts.history_service import get_daily_history
        payload = get_daily_history(code, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        return {"bars": [], "error": f"可信历史服务异常: {exc}", "data_status": "unavailable",
                "coverage_end": None, "source": "", "provider_history_complete": False}
    if not isinstance(payload, dict):
        return {"bars": [], "error": "可信历史服务未返回数据", "data_status": "unavailable",
                "coverage_end": None, "source": "", "provider_history_complete": False}

    status = payload.get("status")
    bars = payload.get("bars") or []
    meta = {
        "data_status": status or "unavailable",
        "coverage_end": payload.get("coverage_end"),
        "source": payload.get("source") or "",
        "provider_history_complete": bool(payload.get("provider_history_complete")),
    }
    if status in ("available", "partial", "stale") and bars:
        return dict(meta, bars=bars, error=(payload.get("error") or None) if status == "stale" else None)
    return dict(meta, bars=[], data_status="unavailable",
                error=payload.get("error") or "日线来源未获取")


def fetch_min30_bars(code: str, datalen: int = 320) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """30 分钟真实 K 线（新浪公开接口）；来源未获取时返回空并说明，不推造。"""
    from scripts.chanlun_strategy_engine import fetch_sina_min_klines
    raw = fetch_sina_min_klines(code, scale=30, datalen=datalen)
    if not raw:
        return [], "30分钟K线来源未获取"
    bars = []
    for bar in raw:
        bars.append({"date": bar.time_str, "open": bar.open, "close": bar.close,
                     "high": bar.high, "low": bar.low, "volume": bar.vol or 0})
    return bars, None


# ============================================================
# 区间套：日线定方向 + 30分钟定买点
# ============================================================

def _date_of(time_str: Optional[str]) -> Optional[str]:
    if not time_str:
        return None
    return str(time_str)[:10]


def compute_resonance(daily_signals: List[Dict[str, Any]],
                      m30_signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    区间套确认：
    - 30分钟信号必须落在日线对应笔/中枢区间（结构窗口）内，才算区间套共振；
    - 否则保留该信号但标记为单周期降级信号，并写明降级原因，绝不冒充共振结论。
    """
    out: List[Dict[str, Any]] = []
    for m30 in m30_signals:
        t = _date_of(m30.get("time"))
        label = m30.get("signal_name") or f"{m30.get('signal_type')}类{'买' if m30.get('side') == 'buy' else '卖'}点"
        best = None
        for daily in daily_signals:
            if daily["side"] != m30["side"]:
                continue
            window = daily.get("structure_window") or {}
            start, end = _date_of(window.get("start")), _date_of(window.get("end"))
            if not start or not end or not t:
                continue
            if start <= t <= end:
                best = daily
                break
        if best is not None:
            ref_window = best.get("structure_window") or {}
            out.append(dict(m30,
                            resonance=True,
                            resonance_level="daily+m30",
                            resonance_note=f"30分钟{label}落在日线{m30['signal_type']}结构区间 "
                                           f"{_date_of(ref_window.get('start'))} ~ {_date_of(ref_window.get('end'))} 内",
                            daily_reference={
                                "signal_type": best["signal_type"], "side": best["side"],
                                "time": best.get("time"), "status": best.get("status"),
                                "structure_window": ref_window,
                            }))
        else:
            out.append(dict(m30,
                            resonance=False,
                            resonance_level="m30-only",
                            resonance_note="30分钟信号未落在任何同向日线结构区间内，降级为单周期信号，不作为区间套共振结论",
                            daily_reference=None))
    return out


def analyze_code(code: str, name: str = "", *, daily_bars=None, m30_bars=None,
                 refresh: bool = False, periods=(5, 10, 20)) -> Dict[str, Any]:
    """
    对单只证券做双周期结构解构与买卖点判定。
    任一周期来源未获取时，该周期不产出信号并如实标注状态。
    """
    code = normalize_code(code)
    result: Dict[str, Any] = {
        "code": code, "name": name, "rule_version": RULE_VERSION,
        "periods": {}, "signals": [], "errors": {},
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    daily_bars = daily_bars if daily_bars is not None else None
    if daily_bars is None:
        daily_meta = fetch_daily_bars(code, refresh=refresh)
        daily_bars = daily_meta["bars"]
        result["data_quality"] = {"daily": {k: v for k, v in daily_meta.items() if k != "bars"}}
        if daily_meta["error"]:
            result["errors"]["daily"] = daily_meta["error"]
        if daily_meta["data_status"] == "stale":
            result.setdefault("warnings", []).append(
                f"日线来源当前不可用，已回落使用此前核验过的真实完整历史（覆盖至 {daily_meta['coverage_end']}）；"
                f"结构结论可用，但该日期不一定是最新交易日，请勿当作当日实时信号")
    m30_bars = m30_bars if m30_bars is not None else None
    if m30_bars is None:
        m30_bars, m30_err = fetch_min30_bars(code)
        if m30_err:
            result["errors"]["m30"] = m30_err

    daily_analysis = None
    m30_analysis = None
    if daily_bars and len(daily_bars) >= MIN_BARS:
        try:
            daily_analysis = analyze_bars(daily_bars, code=code, periods=tuple(periods))
        except ValueError as exc:
            result["errors"]["daily"] = f"日线结构计算被拒绝: {exc}"
    elif not result["errors"].get("daily"):
        result["errors"]["daily"] = f"日线可用K线不足 {MIN_BARS} 根，不产出日线信号"

    if m30_bars and len(m30_bars) >= MIN_BARS:
        try:
            m30_analysis = analyze_bars(m30_bars, code=code, periods=tuple(periods))
        except ValueError as exc:
            result["errors"]["m30"] = f"30分钟结构计算被拒绝: {exc}"
    elif not result["errors"].get("m30"):
        result["errors"]["m30"] = f"30分钟可用K线不足 {MIN_BARS} 根，不产出30分钟信号"

    if daily_analysis:
        result["periods"]["daily"] = {
            "status": daily_analysis["status"], "bar_count": daily_analysis["bar_count"],
            "counts": daily_analysis["counts"], "last_close": _round(daily_bars[-1]["close"]),
            "last_bar_date": str(daily_bars[-1].get("date") or "")[:10],
            "data_status": (result.get("data_quality", {}).get("daily") or {}).get("data_status", "available"),
        }
    if m30_analysis:
        result["periods"]["m30"] = {
            "status": m30_analysis["status"], "bar_count": m30_analysis["bar_count"],
            "counts": m30_analysis["counts"], "last_close": _round(m30_bars[-1]["close"]),
            "last_bar_date": str(m30_bars[-1].get("date") or "")[:10],
            "data_status": "available",
        }

    daily_signals = []
    if daily_analysis:
        daily_signals = detect_signals(daily_analysis, code, name, "daily",
                                       current_price=daily_bars[-1]["close"])
    m30_signals = []
    if m30_analysis:
        m30_signals = detect_signals(m30_analysis, code, name, "m30",
                                     current_price=m30_bars[-1]["close"])

    daily_status = (result.get("data_quality", {}).get("daily") or {}).get("data_status", "available")
    daily_last = str(daily_bars[-1].get("date") or "")[:10] if daily_bars else None
    for signal in daily_signals:
        signal["data_status"] = daily_status
        signal["data_last_bar_date"] = daily_last
    result["signals"] = daily_signals + compute_resonance(daily_signals, m30_signals)
    result["counts"] = {
        "daily": len(daily_signals), "m30": len(m30_signals),
        "resonance": sum(1 for s in result["signals"] if s.get("resonance") is True),
        "total": len(result["signals"]),
    }
    result["status"] = "available" if (daily_analysis or m30_analysis) else "unavailable"
    result["disclaimer"] = ("输出为基于笔级中枢与笔背离的工程化结构事实与风控参数，"
                            "不构成投资建议，不承诺收益或胜率；"
                            "中枢为笔级中枢、背离为笔背离，不等于完整趋势背驰。")
    return result


# ============================================================
# 雷达池：批量扫描 + 落库 + 查询
# ============================================================

DEFAULT_RADAR_POOL = [
    ("sh510300", "沪深300ETF"), ("sh510500", "中证500ETF"), ("sz159915", "创业板ETF"),
    ("sh588000", "科创50ETF"), ("sh510050", "上证50ETF"),
    ("sh600519", "贵州茅台"), ("sz000858", "五粮液"), ("sh601318", "中国平安"),
    ("sz300750", "宁德时代"), ("sz002594", "比亚迪"), ("sh600036", "招商银行"),
    ("sh601899", "紫金矿业"), ("sh601166", "兴业银行"), ("sz000333", "美的集团"),
    ("sh600900", "长江电力"), ("sh688981", "中芯国际"), ("sz002475", "立讯精密"),
    ("sh601988", "中国银行"), ("sz000001", "平安银行"), ("sh600030", "中信证券"),
]


def run_radar(codes: Optional[List[Tuple[str, str]]] = None, *, refresh: bool = False,
              only_signals: bool = True, persist: bool = True,
              progress=None) -> Dict[str, Any]:
    """批量扫描雷达池并把信号落库。返回结构化结果，未获取的证券如实记录错误。"""
    pool = codes or DEFAULT_RADAR_POOL
    scanned, failed, all_signals = [], [], []
    for index, (code, name) in enumerate(pool, start=1):
        if progress:
            progress(index, len(pool), code)
        try:
            report = analyze_code(code, name, refresh=refresh)
        except Exception as exc:  # noqa: BLE001
            failed.append({"code": code, "name": name, "error": f"扫描异常: {exc}"})
            continue
        entry = {
            "code": report["code"], "name": name, "status": report["status"],
            "counts": report.get("counts"), "errors": report.get("errors"),
            "periods": report.get("periods"),
        }
        scanned.append(entry)
        if report.get("errors"):
            failed.append({"code": code, "name": name, "error": report["errors"]})
        for signal in report["signals"]:
            all_signals.append(signal)

    persisted = 0
    if persist:
        try:
            from scripts import stock_db
            persisted = stock_db.replace_chanlun_radar(all_signals)
        except Exception as exc:  # noqa: BLE001
            failed.append({"code": "-", "name": "雷达池落库", "error": f"落库失败: {exc}"})

    return {
        "rule_version": RULE_VERSION,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scanned_count": len(scanned), "signal_count": len(all_signals),
        "persisted_count": persisted,
        "signals": all_signals if not only_signals else all_signals,
        "scanned": scanned,
        "failures": failed,
        "disclaimer": ("雷达池仅呈现结构化结构事实与风控参数，不构成投资建议，不承诺收益；"
                       "「未获取」表示来源未返回，不代表无信号。"),
    }


def format_signal_line(signal: Dict[str, Any]) -> str:
    arrow = "买" if signal["side"] == "buy" else "卖"
    period = "日线" if signal["period"] == "daily" else "30分钟"
    resonance = ""
    if signal.get("resonance") is True:
        resonance = " 【区间套共振】"
    elif signal.get("resonance") is False:
        resonance = " 【单周期·已降级】"
    status = "已确认" if signal["status"] == "confirmed" else "待确认"
    target = f" 目标: {signal['target_price']}" if signal.get("target_price") else " 目标: 未获取"
    if signal.get("actionable"):
        position = f" 建议股数: {signal['suggested_shares']}"
    else:
        position = f" 不可执行({signal.get('risk_budget_note') or '未给出建议仓位'})"
    name_part = f" {signal['name']}" if signal.get("name") else ""
    return (f"[{signal['signal_type']}·{arrow}] {period}{name_part} ({signal['code']})"
            f" 现价: {signal['entry_price']} 结构止损: {signal['stop_price']} 结构距离: {signal['risk_pct']}%"
            f"{target}{position} ({status}){resonance}\n"
            f"      └─ {signal['reason']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="REQ-019 缠论多周期买卖点引擎与雷达池")
    parser.add_argument("code", nargs="?", help="证券代码；省略则运行全池雷达扫描")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--refresh", action="store_true", help="强制刷新日线可信缓存")
    parser.add_argument("--no-persist", action="store_true", help="仅扫描不落库")
    parser.add_argument("--pool", default="", help="自定义雷达池，逗号分隔的代码")
    args = parser.parse_args(argv)

    if args.code:
        report = analyze_code(args.code, "", refresh=args.refresh)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        print(f"证券 {report['code']} 规则版本 {report['rule_version']}")
        for period, info in report["periods"].items():
            print(f"  {period}: {info['bar_count']} 根, 结构 {info['counts']}")
        for key, err in report["errors"].items():
            print(f"  ⚠️ {key} 未获取/不可用: {err}")
        if not report["signals"]:
            print("  未识别到符合规则的买卖点（不等于无信号，也不代表无风险）")
        for signal in report["signals"]:
            print(format_signal_line(signal))
        return 0

    codes = None
    if args.pool.strip():
        codes = [(normalize_code(c), "") for c in args.pool.split(",") if c.strip()]
    result = run_radar(codes, refresh=args.refresh, persist=not args.no_persist)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"雷达池扫描完成：{result['scanned_count']} 只，信号 {result['signal_count']} 条，落库 {result['persisted_count']} 条")
    for signal in result["signals"]:
        print(format_signal_line(signal))
    for failure in result["failures"]:
        print(f"  ⚠️ {failure['code']} {failure['name']}: {failure['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
