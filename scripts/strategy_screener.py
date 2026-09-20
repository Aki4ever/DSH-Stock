#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-020: 策略选股引擎 (v1)
============================================================
已实现策略
----------
`dip-divergence-breakout`「底背驰 + 放量突破中枢」

三条判据必须**同时**成立，缺一不可：
1. **底背驰**：最近若干笔内存在笔级底背离（向下笔创新低且 MACD 绝对柱面积较前一同向笔减弱）。
2. **放量突破中枢**：最新收盘价站上最近一个已确认笔中枢的上沿 ZG，突破幅度达到阈值，
   且突破发生在底背离之后——先衰竭、后突破，才是本策略要的多头结构。
3. **放量**：当日成交量 ≥ 前 N 日均量 × K（N 默认 20，K 默认 1.5）。

口径与边界（不得越界表述）
--------------------------
- 形态仍由 `scripts/chanlun_analysis.py` 唯一计算入口产出；本模块只做条件筛选与证据组装。
- 成交量来自可信不复权日线的真实成交量字段；**成交额来源未提供即不参与判定**，绝不用
  成交量×收盘价之类的推算值冒充成交额。
- 数据不足（K 线不足、均量为 0、无已确认中枢、无底背离）一律不产出命中，并给出未命中原因，
  绝不降低标准凑命中。
- 输出为结构化事实与风控参数，**不构成投资建议，不承诺收益或胜率**。
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
from scripts.chanlun_signals import (  # noqa: E402
    DEFAULT_RADAR_POOL, apply_risk_budget, fetch_daily_bars, normalize_code,
)

RULE_VERSION = "REQ-020/v1"

STRATEGY_META: Dict[str, Dict[str, Any]] = {
    "dip-divergence-breakout": {
        "name": "底背驰 + 放量突破中枢",
        "side": "buy",
        "desc": "笔级底背离衰竭后，放量突破最近一个已确认笔中枢上沿 ZG",
        "defaults": {
            "divergence_lookback": 8,      # 在最近多少笔内寻找底背离
            "min_breakout_pct": 0.5,       # 收盘价超出 ZG 的最小幅度(%)
            "volume_window": 20,           # 均量窗口（不含当日）
            "volume_ratio": 1.5,           # 当日量 / 均量 的最小倍数
        },
    },
}

# 默认选股池：复用雷达池，再补充一批不同板块的权重与成长标的，避免池子过度集中在宽基 ETF
DEFAULT_SCREEN_POOL: List[Tuple[str, str]] = list(DEFAULT_RADAR_POOL) + [
    ("sh601012", "隆基绿能"), ("sz002415", "海康威视"), ("sh600276", "恒瑞医药"),
    ("sz300059", "东方财富"), ("sh601888", "中国中免"), ("sz000651", "格力电器"),
    ("sh601668", "中国建筑"), ("sh600887", "伊利股份"), ("sz002304", "洋河股份"),
    ("sh603259", "药明康德"),
]


def _round(value, digits=2):
    if value is None:
        return None
    return round(float(value), digits)


def _trading_date_of(bar: Dict[str, Any]) -> str:
    return str(bar.get("date") or "")[:10]


def evaluate_dip_divergence_breakout(bars: List[Dict[str, Any]], analysis: Dict[str, Any],
                                     params: Dict[str, Any], current_price: float) -> Dict[str, Any]:
    """
    判定「底背驰 + 放量突破中枢」。返回 {'hit': bool, 'reason': str, 'evidence': {...}}。
    任何一条判据不成立都会在 reason 中说明具体是哪一条、差多少，便于人工复核。
    """
    lookback = int(params.get("divergence_lookback", 8))
    min_breakout = float(params.get("min_breakout_pct", 0.5))
    vol_window = int(params.get("volume_window", 20))
    vol_ratio = float(params.get("volume_ratio", 1.5))

    pens = analysis.get("pens") or []
    pivots = analysis.get("pivots") or []
    divergences = analysis.get("divergences") or []

    # ---- 判据 3 先算：放量（最容易因数据不足而直接不成立） ----
    if len(bars) < vol_window + 1:
        return {"hit": False, "reason": f"可用K线 {len(bars)} 根，不足 {vol_window + 1} 根，无法计算 {vol_window} 日均量"}
    history = bars[-(vol_window + 1):-1]
    volumes = [b.get("volume") for b in history]
    if any(v is None or v <= 0 for v in volumes):
        return {"hit": False, "reason": f"前 {vol_window} 日存在缺失或为 0 的成交量，按真实数据原则不做放量判定"}
    avg_volume = sum(volumes) / len(volumes)
    today_volume = bars[-1].get("volume")
    if today_volume is None or today_volume <= 0:
        return {"hit": False, "reason": "最新交易日成交量为缺失或 0，不做放量判定"}
    actual_ratio = today_volume / avg_volume if avg_volume > 0 else 0.0
    volume_ok = actual_ratio >= vol_ratio

    # ---- 判据 1：最近 lookback 笔内存在笔级底背离 ----
    recent_pens = pens[-lookback:] if lookback > 0 else pens
    recent_window_start = recent_pens[0]["start_time"] if recent_pens else None
    bottom_divs = [d for d in divergences
                   if d.get("kind") == "底背离" and recent_window_start
                   and str(d.get("time")) >= str(recent_window_start)]
    if not bottom_divs:
        return {"hit": False, "reason": f"最近 {lookback} 笔内没有笔级底背离，多头衰竭结构不成立",
                "evidence": {"volume_ratio_actual": _round(actual_ratio, 2), "volume_ok": volume_ok}}
    latest_div = bottom_divs[-1]

    # ---- 判据 2：放量突破已确认笔中枢上沿 ZG，且突破在底背离之后 ----
    confirmed_pivots = [p for p in pivots if p.get("status") == "confirmed"]
    if not confirmed_pivots:
        return {"hit": False, "reason": "没有已确认的笔中枢，无法判定突破（待确认中枢不参与判定）",
                "evidence": {"divergence_time": latest_div.get("time")}}
    pivot = confirmed_pivots[-1]
    zg, zd = pivot.get("zg"), pivot.get("zd")
    if not zg or zg <= 0:
        return {"hit": False, "reason": "最近一个已确认笔中枢的上沿 ZG 无效，不判定突破"}
    breakout_pct = (current_price - zg) / zg * 100
    breakout_ok = current_price > zg and breakout_pct >= min_breakout
    after_divergence = str(latest_div.get("time") or "") <= str(bars[-1].get("date") or "")
    # 突破必须在背离之后：中枢结束时间不得早于背离，否则是「先突破后衰竭」的反向结构
    pivot_after_divergence = str(pivot.get("end_time") or "") >= str(latest_div.get("time") or "")

    evidence = {
        "divergence_time": latest_div.get("time"),
        "divergence_price": latest_div.get("price"),
        "divergence_previous_area": _round(latest_div.get("previous_area"), 4),
        "divergence_current_area": _round(latest_div.get("current_area"), 4),
        "divergence_area_ratio": _round((latest_div.get("current_area") or 0) / latest_div.get("previous_area"), 4)
                                 if latest_div.get("previous_area") else None,
        "pivot_zg": _round(zg),
        "pivot_zd": _round(zd),
        "pivot_end_time": pivot.get("end_time"),
        "pivot_status": pivot.get("status"),
        "breakout_pct": _round(breakout_pct),
        "min_breakout_pct": min_breakout,
        "close": _round(current_price),
        "volume": today_volume,
        "avg_volume": _round(avg_volume, 0),
        "volume_window": vol_window,
        "volume_ratio_actual": _round(actual_ratio, 2),
        "volume_ratio_required": vol_ratio,
        "volume_ok": volume_ok,
        "breakout_ok": breakout_ok,
        "pivot_after_divergence": pivot_after_divergence,
    }

    if not pivot_after_divergence:
        return {"hit": False, "reason": f"最近一个已确认笔中枢（结束于 {pivot.get('end_time')}）早于底背离"
                                        f"（{latest_div.get('time')}），属于先突破后衰竭的反向结构，不命中",
                "evidence": evidence}
    if not breakout_ok:
        return {"hit": False,
                "reason": f"收盘 {_round(current_price)} 未有效突破中枢上沿 ZG={_round(zg)}"
                          f"（当前幅度 {_round(breakout_pct)}%，要求 ≥ {min_breakout}%）",
                "evidence": evidence}
    if not volume_ok:
        return {"hit": False,
                "reason": f"放量不足：当日量 / {vol_window}日均量 = {_round(actual_ratio, 2)} 倍，"
                          f"低于要求的 {vol_ratio} 倍",
                "evidence": evidence}
    if not after_divergence:
        return {"hit": False, "reason": "最新交易日早于底背离时间，判定顺序异常", "evidence": evidence}

    return {"hit": True, "evidence": evidence,
            "reason": f"笔级底背离（面积 {evidence['divergence_previous_area']} → {evidence['divergence_current_area']}）"
                      f"后放量 {evidence['volume_ratio_actual']} 倍突破笔中枢上沿 ZG={evidence['pivot_zg']}"
                      f"，突破幅度 {evidence['breakout_pct']}%"}


def screen_security(code: str, name: str = "", *, bars: Optional[List[Dict[str, Any]]] = None,
                    strategy: str = "dip-divergence-breakout", params: Optional[Dict[str, Any]] = None,
                    refresh: bool = False, periods=(5, 10, 20)) -> Dict[str, Any]:
    """对单只证券执行策略判定，返回结构化命中或未命中原因。"""
    if strategy not in STRATEGY_META:
        raise ValueError(f"未知策略 {strategy}")
    meta = STRATEGY_META[strategy]
    merged = dict(meta["defaults"])
    merged.update(params or {})
    code = normalize_code(code)

    outcome: Dict[str, Any] = {"code": code, "name": name, "strategy": strategy,
                               "strategy_name": meta["name"], "rule_version": RULE_VERSION,
                               "params": merged, "status": "evaluated", "hit": False}

    if bars is None:
        daily = fetch_daily_bars(code, refresh=refresh)
        bars = daily["bars"]
        outcome["data_quality"] = {k: v for k, v in daily.items() if k != "bars"}
        if daily["error"]:
            outcome["errors"] = {"daily": daily["error"]}
        if not bars:
            return dict(outcome, status="unavailable", reason=daily["error"] or "日线来源未获取")
        if daily["data_status"] == "stale":
            # 本策略的判据全部依赖「最新交易日」：最新收盘价突破、当日成交量放量。
            # 用非最新的缓存数据判定，会把历史某天的结构当成今天的信号推送，属于误导，必须拒绝。
            return dict(outcome, status="unavailable",
                        reason=f"日线来源当前不可用（{daily['error'] or '刷新失败'}），"
                               f"仅有覆盖至 {daily['coverage_end']} 的历史缓存。本策略依赖最新交易日的"
                               f"收盘突破与当日放量，不以历史数据冒充当日信号，因此本轮不判定",
                        data_quality=outcome["data_quality"])
    min_bars = max(int(merged["volume_window"]) + 1, 30)
    if len(bars) < min_bars:
        return dict(outcome, status="unavailable",
                    reason=f"可用日线 {len(bars)} 根，不足判定所需的 {min_bars} 根")

    try:
        analysis = analyze_bars(bars, code=code, periods=tuple(periods))
    except ValueError as exc:
        return dict(outcome, status="unavailable", reason=f"结构计算被拒绝: {exc}")
    if analysis.get("status") != "available":
        return dict(outcome, status="unavailable", reason="结构数据不足，无法判定")

    current_price = bars[-1]["close"]
    verdict = evaluate_dip_divergence_breakout(bars, analysis, merged, current_price)
    if not verdict["hit"]:
        return dict(outcome, reason=verdict["reason"], evidence=verdict.get("evidence"))

    evidence = verdict["evidence"]
    signal = {
        "strategy": strategy,
        "strategy_name": meta["name"],
        "code": code, "name": name, "side": meta["side"],
        "signal_type": "底背驰放量突破",
        "period": "daily",
        "trade_date": _trading_date_of(bars[-1]),
        "close": _round(current_price),
        "entry_price": _round(current_price),
        # 突破失败的定义就是跌回中枢上沿之内，因此结构止损取 ZG 本身
        "stop_price": evidence["pivot_zg"],
        "target_price": None,
        "pivot_zg": evidence["pivot_zg"],
        "pivot_zd": evidence["pivot_zd"],
        "volume_ratio": evidence["volume_ratio_actual"],
        "volume_window": evidence["volume_window"],
        "reason": verdict["reason"],
        "evidence": evidence,
        "structure": {
            "divergence": {"time": evidence["divergence_time"], "price": evidence["divergence_price"],
                           "area_ratio": evidence["divergence_area_ratio"]},
            "pivot": {"zg": evidence["pivot_zg"], "zd": evidence["pivot_zd"],
                      "end_time": evidence["pivot_end_time"], "status": evidence["pivot_status"]},
        },
        "rule_version": RULE_VERSION,
        "analysis_rules_version": ANALYSIS_RULES["version"],
        "hit": True,
        "target_note": "本策略以突破中枢上沿为唯一结构依据，未给出目标位，不臆造上方目标价",
    }
    if signal["entry_price"] and signal["stop_price"]:
        signal["risk_pct"] = _round((signal["entry_price"] - signal["stop_price"]) / signal["entry_price"] * 100)
    apply_risk_budget(signal)
    return dict(outcome, hit=True, reason=verdict["reason"], evidence=evidence, signal=signal)


def run_screen(pool: Optional[List[Tuple[str, str]]] = None, *, strategy: str = "dip-divergence-breakout",
               params: Optional[Dict[str, Any]] = None, refresh: bool = False, persist: bool = True,
               progress=None) -> Dict[str, Any]:
    """批量运行策略选股。未命中与不可用都逐条保留原因，便于人工复核。"""
    universe = pool or DEFAULT_SCREEN_POOL
    hits, evaluated, unavailable = [], [], []
    for index, (code, name) in enumerate(universe, start=1):
        if progress:
            progress(index, len(universe), code)
        try:
            result = screen_security(code, name, strategy=strategy, params=params, refresh=refresh)
        except Exception as exc:  # noqa: BLE001
            unavailable.append({"code": code, "name": name, "reason": f"评估异常: {exc}"})
            continue
        summary = {"code": result["code"], "name": name, "status": result["status"],
                   "hit": result["hit"], "reason": result.get("reason", "")}
        if result["status"] == "unavailable":
            unavailable.append(summary)
        elif result["hit"]:
            hits.append(result["signal"])
        else:
            evaluated.append(summary)

    persisted = 0
    if persist:
        try:
            from scripts import stock_db
            persisted = stock_db.replace_screen_results(hits)
        except Exception as exc:  # noqa: BLE001
            unavailable.append({"code": "-", "name": "选股结果落库", "reason": f"落库失败: {exc}"})

    return {
        "strategy": strategy,
        "strategy_name": STRATEGY_META.get(strategy, {}).get("name", strategy),
        "rule_version": RULE_VERSION,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "universe_count": len(universe),
        "hit_count": len(hits),
        "miss_count": len(evaluated),
        "unavailable_count": len(unavailable),
        "persisted_count": persisted,
        "hits": hits,
        "misses": evaluated,
        "unavailable": unavailable,
        "disclaimer": ("命中为结构化条件筛选结果，不构成投资建议，不承诺收益或胜率；"
                       "未命中表示不满足当前判据，不代表该证券没有机会或没有风险；"
                       "未获取表示来源未返回数据，需人工复核。"),
    }


def format_hit_line(hit: Dict[str, Any]) -> str:
    position = (f"建议股数: {hit['suggested_shares']}" if hit.get("actionable")
                else f"不可执行({hit.get('risk_budget_note') or '未给出建议仓位'})")
    return (f"[命中] {hit.get('name') or ''} {hit['code']} 收盘 {hit['close']}"
            f" | ZG={hit['pivot_zg']} 突破 {hit['evidence']['breakout_pct']}%"
            f" | 量比 {hit['volume_ratio']}×({hit['evidence']['volume_window']}日)"
            f" | 结构距离 {hit.get('risk_pct')}% | {position}\n"
            f"      └─ {hit['reason']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="REQ-020 策略选股引擎")
    parser.add_argument("--strategy", default="dip-divergence-breakout",
                        choices=sorted(STRATEGY_META.keys()), help="策略名称")
    parser.add_argument("--pool", default="", help="自定义选股池，逗号分隔代码")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--notify", default="", help="命中后下发告警的通道：feishu,dingtalk / all")
    parser.add_argument("--dry-run", action="store_true", help="只校验告警配置与签名，不实际发送")
    parser.add_argument("--volume-ratio", type=float, default=None, help="覆盖放量倍数 K")
    parser.add_argument("--volume-window", type=int, default=None, help="覆盖均量窗口 N")
    args = parser.parse_args(argv)

    params: Dict[str, Any] = {}
    if args.volume_ratio is not None:
        params["volume_ratio"] = args.volume_ratio
    if args.volume_window is not None:
        params["volume_window"] = args.volume_window

    pool = None
    if args.pool.strip():
        pool = [(normalize_code(c), "") for c in args.pool.split(",") if c.strip()]

    result = run_screen(pool, strategy=args.strategy, params=params or None,
                        refresh=args.refresh, persist=not args.no_persist)

    notify_outcome = None
    if args.notify.strip():
        from scripts.alert_channels import notify_hits
        channels = None
        if args.notify.strip().lower() != "all":
            channels = [c.strip() for c in args.notify.split(",") if c.strip()]
        notify_outcome = notify_hits(result["hits"], channels, dry_run=args.dry_run)
        result["notify"] = notify_outcome

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"策略「{result['strategy_name']}」规则版本 {result['rule_version']}")
    print(f"选股池 {result['universe_count']} 只 → 命中 {result['hit_count']} 只 / "
          f"未命中 {result['miss_count']} 只 / 未获取 {result['unavailable_count']} 只，落库 {result['persisted_count']} 条")
    for hit in result["hits"]:
        print(format_hit_line(hit))
    if not result["hits"]:
        print("  本轮没有命中。可展开 --json 查看每只标的的具体未命中原因。")
    for item in result["unavailable"][:10]:
        print(f"  ⚠️ 未获取 {item['code']} {item.get('name', '')}: {item['reason']}")
    if notify_outcome:
        print(f"告警：候选 {notify_outcome.get('candidate_count', 0)} 条，"
              f"实际下发 {notify_outcome.get('sent', 0)} 条，冷却跳过 {notify_outcome.get('skipped', 0)} 条")
        if notify_outcome.get("reason"):
            print(f"  {notify_outcome['reason']}")
        for item in notify_outcome.get("results", [])[:8]:
            mark = "✅" if item.get("ok") else "❌"
            print(f"  {mark} {item.get('label') or item.get('channel')}: {item.get('reason') or '发送成功'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
