# -*- coding: utf-8 -*-
"""
REQ-019 缠论多周期买卖点引擎与雷达池 单元测试
全部使用构造的结构 fixture 直接驱动判定层，不联网、不写产品库。
重点在于证明每条规则都能被触发（含 3B/S3），以及不可执行信号被正确拒止。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import stock_db
from scripts.chanlun_signals import (  # noqa: E402
    MAX_ACTIONABLE_RISK_PCT, RULE_VERSION, apply_risk_budget, compute_resonance,
    dedupe_signals, detect_signals,
)


def pen(direction, start_time, end_time, start_price, end_price, start_index, end_index, status="confirmed"):
    return {"direction": direction, "start_time": start_time, "end_time": end_time,
            "start_price": start_price, "end_price": end_price, "start_index": start_index,
            "end_index": end_index, "high": max(start_price, end_price),
            "low": min(start_price, end_price), "macd_area": 1.0, "status": status}


def divergence(time_str, price, kind, previous_area, current_area, index=0, status="confirmed"):
    return {"time": time_str, "price": price, "kind": kind, "previous_area": previous_area,
            "current_area": current_area, "index": index, "status": status}


def analysis(pens, pivots=None, divergences=None, status="available", dates=None):
    return {"status": status, "pens": pens, "pivots": pivots or [], "divergences": divergences or [],
            "segments": [], "ma_entanglements": [], "dates": dates or [p["end_time"] for p in pens],
            "counts": {}, "rules": {"version": "1.0"}}


def pivot(zg, zd, end_index, start_time="2026-01-01", end_time="2026-01-10"):
    return {"zg": zg, "zd": zd, "start_index": 0, "end_index": end_index,
            "start_time": start_time, "end_time": end_time, "level": "bi", "status": "confirmed"}


# 3B 结构：中枢末笔为 p2，突破笔 p3 越过 ZG，回抽笔 p4 不跌破 ZG
PENS_3B = [
    pen(-1, "2026-01-02", "2026-01-05", 14, 10, 1, 3),
    pen(1, "2026-01-05", "2026-01-08", 10, 15, 3, 6),
    pen(-1, "2026-01-08", "2026-01-12", 15, 12, 6, 10),   # 中枢末笔
    pen(1, "2026-01-12", "2026-01-16", 12, 20, 10, 14),   # 突破笔 > ZG=16
    pen(-1, "2026-01-16", "2026-01-20", 20, 18, 14, 18),  # 回抽笔 >= ZG
    pen(1, "2026-01-20", "2026-01-24", 18, 21, 18, 22),
]
PIVOT_3B = [pivot(16, 11, end_index=10)]

# S3 结构：中枢末笔为 p2，跌破笔 p3 低于 ZD，反抽笔 p4 不回到 ZD
PENS_S3 = [
    pen(1, "2026-02-02", "2026-02-05", 10, 14, 1, 3),
    pen(-1, "2026-02-05", "2026-02-08", 14, 11, 3, 6),
    pen(1, "2026-02-08", "2026-02-12", 11, 15, 6, 10),    # 中枢末笔
    pen(-1, "2026-02-12", "2026-02-16", 15, 8, 10, 14),   # 跌破笔 < ZD=11
    pen(1, "2026-02-16", "2026-02-20", 8, 10, 14, 18),    # 反抽笔 <= ZD
    pen(-1, "2026-02-20", "2026-02-24", 10, 7, 18, 22),
]
PIVOT_S3 = [pivot(16, 11, end_index=10, start_time="2026-02-01", end_time="2026-02-12")]


class SignalRuleTests(unittest.TestCase):
    """六类买卖点规则必须都能被真实结构触发。"""

    def types(self, signals):
        return sorted({s["signal_type"] for s in signals})

    def test_3b_fires_on_breakout_with_pullback_holding_zg(self):
        signals = detect_signals(analysis(PENS_3B, PIVOT_3B), "sh600000", "测试", "daily",
                                 current_price=21)
        self.assertIn("3B", self.types(signals))
        sig = [s for s in signals if s["signal_type"] == "3B"][0]
        self.assertEqual(sig["side"], "buy")
        self.assertEqual(sig["stop_price"], 18.0, "3B 结构止损必须是回抽笔低点")
        self.assertIn("ZG=16", sig["reason"])
        self.assertEqual(len(sig["structure"]), 3, "3B 必须引用中枢末笔/突破笔/回抽笔三段结构")

    def test_s3_fires_on_breakdown_with_rebound_failing_zd(self):
        signals = detect_signals(analysis(PENS_S3, PIVOT_S3), "sh600000", "测试", "daily",
                                 current_price=7)
        self.assertIn("S3", self.types(signals))
        sig = [s for s in signals if s["signal_type"] == "S3"][0]
        self.assertEqual(sig["side"], "sell")
        self.assertEqual(sig["stop_price"], 10.0, "S3 结构止损必须是反抽笔高点")
        self.assertIn("ZD=11", sig["reason"])

    def test_1b_and_s1_fire_on_divergence(self):
        pens = [
            pen(-1, "2026-03-02", "2026-03-05", 14, 10, 1, 3),
            pen(1, "2026-03-05", "2026-03-08", 10, 14, 3, 6),
            pen(-1, "2026-03-08", "2026-03-12", 14, 9, 6, 10),   # 创新低 + 底背离标的
            pen(1, "2026-03-12", "2026-03-16", 9, 13, 10, 14),
            pen(1, "2026-03-16", "2026-03-20", 13, 18, 14, 17),  # 创新高 + 顶背离标的
            pen(-1, "2026-03-20", "2026-03-24", 18, 15, 17, 20),
        ]
        divs = [
            divergence("2026-03-12", 9, "底背离", 10.0, 3.0),
            divergence("2026-03-20", 18, "顶背离", 12.0, 4.0),
        ]
        signals = detect_signals(analysis(pens, [], divs), "sh600000", "测试", "daily", current_price=15)
        self.assertIn("1B", self.types(signals))
        self.assertIn("S1", self.types(signals))
        buy = [s for s in signals if s["signal_type"] == "1B"][0]
        sell = [s for s in signals if s["signal_type"] == "S1"][0]
        self.assertEqual(buy["stop_price"], 9.0)
        self.assertEqual(sell["stop_price"], 18.0)
        self.assertEqual(buy["area_ratio"], 0.3, "底背离必须记录面积比以支撑背驰结论")

    def test_2b_fires_on_failed_retest(self):
        # 单一 2B 结构：下跌笔(前低10) → 反弹笔(13) → 回调笔(11) 不破前低
        pens = [
            pen(-1, "2026-04-02", "2026-04-05", 15, 10, 1, 3),
            pen(1, "2026-04-05", "2026-04-08", 10, 13, 3, 6),
            pen(-1, "2026-04-08", "2026-04-12", 13, 11, 6, 10),
            pen(1, "2026-04-12", "2026-04-16", 11, 14, 10, 14),
        ]
        signals = detect_signals(analysis(pens), "sh600000", "测试", "daily", current_price=14)
        self.assertIn("2B", self.types(signals))
        buy = [s for s in signals if s["signal_type"] == "2B"][0]
        self.assertEqual(buy["stop_price"], 10.0, "2B 止损必须是前低")
        self.assertEqual(buy["side"], "buy")
        self.assertEqual(buy["status"], "confirmed", "回调笔之后仍有一笔，2B 应判为已确认")
        self.assertEqual(len(buy["structure"]), 3)

    def test_s2_fires_on_failed_retest(self):
        # 单一 S2 结构：上涨笔(前高17) → 回调笔(14) → 反抽笔(16) 不破前高
        pens = [
            pen(1, "2026-05-02", "2026-05-05", 12, 17, 1, 3),
            pen(-1, "2026-05-05", "2026-05-08", 17, 14, 3, 6),
            pen(1, "2026-05-08", "2026-05-12", 14, 16, 6, 10),
            pen(-1, "2026-05-12", "2026-05-16", 16, 12, 10, 14),
        ]
        signals = detect_signals(analysis(pens), "sh600000", "测试", "daily", current_price=12)
        self.assertIn("S2", self.types(signals))
        sell = [s for s in signals if s["signal_type"] == "S2"][0]
        self.assertEqual(sell["stop_price"], 17.0, "S2 止损必须是前高")
        self.assertEqual(sell["side"], "sell")

    def test_latest_occurrence_wins_when_multiple_patterns_exist(self):
        # 7 笔中包含两处 2B：较晚的一处（前低11）必须覆盖较早的一处（前低10）
        pens = [
            pen(-1, "2026-04-02", "2026-04-05", 15, 10, 1, 3),
            pen(1, "2026-04-05", "2026-04-08", 10, 13, 3, 6),
            pen(-1, "2026-04-08", "2026-04-12", 13, 11, 6, 10),
            pen(1, "2026-04-12", "2026-04-16", 11, 17, 10, 14),
            pen(-1, "2026-04-16", "2026-04-20", 17, 14, 14, 17),
            pen(1, "2026-04-20", "2026-04-24", 14, 16, 17, 20),
            pen(-1, "2026-04-24", "2026-04-28", 16, 12, 20, 23),
        ]
        signals = detect_signals(analysis(pens), "sh600000", "测试", "daily", current_price=12)
        two_b = [s for s in signals if s["signal_type"] == "2B"]
        self.assertEqual(len(two_b), 1, "同周期同类型必须去重为一条")
        self.assertEqual(two_b[0]["stop_price"], 11.0, "必须保留最新一处 2B 结构")
        self.assertIn("S2", self.types(signals))

    def test_3b_does_not_fire_when_pullback_breaks_zg(self):
        pens = list(PENS_3B)
        pens[4] = pen(-1, "2026-01-16", "2026-01-20", 20, 15, 14, 18)  # 回抽 15 < ZG=16
        signals = detect_signals(analysis(pens, PIVOT_3B), "sh600000", "测试", "daily", current_price=15)
        self.assertNotIn("3B", [s["signal_type"] for s in signals if s["status"] == "confirmed"])

    def test_s3_does_not_fire_when_rebound_reaches_zd(self):
        pens = list(PENS_S3)
        pens[4] = pen(1, "2026-02-16", "2026-02-20", 8, 13, 14, 18)  # 反抽 13 > ZD=11
        signals = detect_signals(analysis(pens, PIVOT_S3), "sh600000", "测试", "daily", current_price=13)
        self.assertNotIn("S3", [s["signal_type"] for s in signals if s["status"] == "confirmed"])

    def test_provisional_when_confirming_pen_is_last(self):
        # 回抽笔是最后一笔 → 结构尚未被后续笔确认
        pens = PENS_3B[:5]
        signals = detect_signals(analysis(pens, PIVOT_3B), "sh600000", "测试", "daily", current_price=18)
        three_b = [s for s in signals if s["signal_type"] == "3B"][0]
        self.assertEqual(three_b["status"], "provisional")

    def test_no_signal_when_analysis_unavailable_or_too_few_pens(self):
        self.assertEqual(detect_signals(analysis(PENS_3B, PIVOT_3B, status="insufficient"),
                                       "sh600000", "", "daily"), [])
        self.assertEqual(detect_signals(analysis(PENS_3B[:2]), "sh600000", "", "daily"), [])

    def test_dedupe_keeps_only_latest_per_period_and_type(self):
        dup = [
            {"period": "daily", "signal_type": "1B", "time": "2026-01-01"},
            {"period": "daily", "signal_type": "1B", "time": "2026-02-01"},
            {"period": "m30", "signal_type": "1B", "time": "2026-01-15"},
        ]
        out = dedupe_signals(dup)
        self.assertEqual(len(out), 2)
        daily = [s for s in out if s["period"] == "daily"][0]
        self.assertEqual(daily["time"], "2026-02-01", "同周期同类型必须只保留最新一条")

    def test_every_signal_carries_rule_version_and_disclaimer_source(self):
        signals = detect_signals(analysis(PENS_3B, PIVOT_3B), "sh600000", "测试", "daily", current_price=21)
        for sig in signals:
            self.assertEqual(sig["rule_version"], RULE_VERSION)
            self.assertEqual(sig["analysis_rules_version"], "1.0")
            self.assertTrue(sig["rule"])
            self.assertIn("structure_window", sig)


class ActionabilityTests(unittest.TestCase):
    """不可执行信号必须被拒止，且说明具体原因，不得给出误导性建议股数。"""

    def base(self, side="buy", entry=10.0, stop=9.0, status="confirmed"):
        return {"side": side, "entry_price": entry, "stop_price": stop, "status": status,
                "risk_pct": abs(entry - stop) / entry * 100}

    def test_normal_buy_is_actionable(self):
        sig = apply_risk_budget(self.base())
        self.assertTrue(sig["actionable"])
        self.assertGreater(sig["suggested_shares"], 0)
        self.assertEqual(sig["suggested_shares"] % 100, 0, "建议股数必须按 100 股整手")

    def test_buy_with_stop_above_entry_is_rejected_as_broken_structure(self):
        sig = apply_risk_budget(self.base(entry=10.0, stop=10.4))
        self.assertTrue(sig["structure_broken"])
        self.assertFalse(sig["actionable"])
        self.assertIsNone(sig["suggested_shares"])
        self.assertIn("结构已被证伪", sig["risk_budget_note"])

    def test_sell_with_stop_below_entry_is_rejected_as_broken_structure(self):
        sig = apply_risk_budget(self.base(side="sell", entry=10.0, stop=9.6))
        self.assertTrue(sig["structure_broken"])
        self.assertFalse(sig["actionable"])
        self.assertIn("结构已被证伪", sig["risk_budget_note"])

    def test_over_wide_stop_is_rejected(self):
        sig = apply_risk_budget(self.base(entry=10.0, stop=10.0 - 10.0 * (MAX_ACTIONABLE_RISK_PCT + 5) / 100))
        self.assertFalse(sig["actionable"])
        self.assertIsNone(sig["suggested_shares"])
        self.assertIn("超过", sig["risk_budget_note"])

    def test_provisional_signal_is_not_actionable(self):
        sig = apply_risk_budget(self.base(status="provisional"))
        self.assertFalse(sig["actionable"])
        self.assertIn("尚未确认", sig["risk_budget_note"])

    def test_missing_price_gives_no_position(self):
        sig = apply_risk_budget({"side": "buy", "entry_price": None, "stop_price": None, "status": "confirmed"})
        self.assertFalse(sig["actionable"])
        self.assertIsNone(sig["suggested_shares"])

    def test_position_is_capped_by_position_ratio(self):
        # 止损极近时风险预算允许的股数很大，必须被单只仓位上限压住
        sig = apply_risk_budget(self.base(entry=10.0, stop=9.999))
        self.assertTrue(sig["actionable"])
        self.assertLessEqual(sig["suggested_capital"], 1000000.0 * 0.30 + 10)


class ResonanceTests(unittest.TestCase):
    """区间套：只有落在同向日线结构区间内才算共振，否则显式降级。"""

    def daily(self, start, end, side="buy"):
        return {"signal_type": "1B" if side == "buy" else "S1", "side": side, "time": end,
                "status": "confirmed", "structure_window": {"start": start, "end": end}}

    def m30(self, time_str, side="buy"):
        return {"signal_type": "1B" if side == "buy" else "S1", "side": side, "time": time_str,
                "period": "m30", "status": "confirmed"}

    def test_signal_inside_daily_window_is_resonance(self):
        out = compute_resonance([self.daily("2026-01-05", "2026-01-20")], [self.m30("2026-01-12 10:30:00")])
        self.assertTrue(out[0]["resonance"])
        self.assertEqual(out[0]["resonance_level"], "daily+m30")
        self.assertIsNotNone(out[0]["daily_reference"])

    def test_signal_outside_daily_window_is_downgraded(self):
        out = compute_resonance([self.daily("2026-01-05", "2026-01-20")], [self.m30("2026-03-02 14:00:00")])
        self.assertFalse(out[0]["resonance"])
        self.assertEqual(out[0]["resonance_level"], "m30-only")
        self.assertIn("降级", out[0]["resonance_note"])
        self.assertIsNone(out[0]["daily_reference"])

    def test_opposite_side_never_resonates(self):
        out = compute_resonance([self.daily("2026-01-05", "2026-01-20", side="buy")],
                                [self.m30("2026-01-12 10:30:00", side="sell")])
        self.assertFalse(out[0]["resonance"], "买点与卖点不得互为区间套共振")

    def test_no_daily_signals_means_all_downgraded(self):
        out = compute_resonance([], [self.m30("2026-01-12 10:30:00")])
        self.assertFalse(out[0]["resonance"])

    def test_missing_time_is_downgraded_not_crashed(self):
        out = compute_resonance([self.daily("2026-01-05", "2026-01-20")], [self.m30(None)])
        self.assertFalse(out[0]["resonance"])


class RadarPersistenceTests(unittest.TestCase):
    """雷达池落库与查询必须在隔离的临时库上进行。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsh_radar_")
        self.patchers = [
            patch.object(stock_db, "DB_PATH", str(Path(self.tmp) / "test.db")),
            patch.object(stock_db, "DATA_DIR", self.tmp),
        ]
        for p in self.patchers:
            p.start()
        stock_db.init_db()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def signal(self, code="sh600519", period="daily", stype="1B", time_str="2026-09-18", resonance=False):
        return {"code": code, "name": "贵州茅台", "period": period, "signal_type": stype,
                "side": "buy" if stype.endswith("B") else "sell", "time": time_str,
                "entry_price": 1257.12, "stop_price": 1151.01, "target_price": 1295.0,
                "risk_pct": 8.44, "status": "confirmed", "resonance": resonance,
                "reason": "构造测试信号", "rule_version": RULE_VERSION,
                "structure": [], "structure_window": {"start": time_str, "end": time_str}}

    def test_persist_and_read_back_full_payload(self):
        n = stock_db.replace_chanlun_radar([self.signal(), self.signal(stype="S1", code="sz000001")])
        self.assertEqual(n, 2)
        rows = stock_db.list_chanlun_radar()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["signal"]["reason"], "构造测试信号", "必须能读回完整信号载荷")
        self.assertNotIn("payload", rows[0])

    def test_second_scan_replaces_instead_of_appending(self):
        stock_db.replace_chanlun_radar([self.signal(), self.signal(stype="S1")])
        stock_db.replace_chanlun_radar([self.signal(stype="2B")])
        rows = stock_db.list_chanlun_radar()
        self.assertEqual(len(rows), 1, "雷达池必须整体替换，不得残留上一轮过期信号")
        self.assertEqual(rows[0]["signal_type"], "2B")

    def test_filter_by_type_period_and_code(self):
        stock_db.replace_chanlun_radar([
            self.signal(stype="1B", period="daily", code="sh600519"),
            self.signal(stype="S1", period="m30", code="sz000001"),
        ])
        self.assertEqual(len(stock_db.list_chanlun_radar(signal_types=["1B"])), 1)
        self.assertEqual(len(stock_db.list_chanlun_radar(period="m30")), 1)
        self.assertEqual(len(stock_db.list_chanlun_radar(code="sh600519")), 1)
        self.assertEqual(len(stock_db.list_chanlun_radar(signal_types=["1B"], period="m30")), 0)

    def test_snapshot_reports_real_counts(self):
        stock_db.replace_chanlun_radar([
            self.signal(stype="1B"), self.signal(stype="1B", period="m30", code="sz000002"),
            self.signal(stype="S1", resonance=True),
        ])
        snap = stock_db.chanlun_radar_snapshot()
        self.assertEqual(snap["total"], 3)
        self.assertEqual(snap["by_signal_type"], {"1B": 2, "S1": 1})
        self.assertEqual(snap["by_period"], {"daily": 2, "m30": 1})
        self.assertEqual(snap["resonance_count"], 1)
        self.assertTrue(snap["computed_at"])

    def test_empty_scan_clears_pool_without_error(self):
        stock_db.replace_chanlun_radar([self.signal()])
        self.assertEqual(stock_db.replace_chanlun_radar([]), 0)
        self.assertEqual(stock_db.chanlun_radar_snapshot()["total"], 0)

    def test_radar_table_is_separate_from_business_tables(self):
        with stock_db.get_db_connection() as conn:
            conn.execute("INSERT INTO stocks_master (code, raw_code, name, market, market_code, board, board_code)"
                         " VALUES ('sh600519','600519','贵州茅台','sh','sh','main','main');")
            conn.commit()
        stock_db.replace_chanlun_radar([self.signal()])
        with stock_db.get_db_connection() as conn:
            survived = conn.execute("SELECT COUNT(*) c FROM stocks_master;").fetchone()["c"]
        self.assertEqual(survived, 1, "雷达池写入不得影响业务底册")

    def test_signal_key_is_stable_and_idempotent(self):
        sig = self.signal()
        stock_db.replace_chanlun_radar([sig, dict(sig)])
        self.assertEqual(stock_db.chanlun_radar_snapshot()["total"], 1, "同一信号重复写入必须幂等")

    def test_payload_roundtrip_is_valid_json(self):
        stock_db.replace_chanlun_radar([self.signal()])
        rows = stock_db.list_chanlun_radar()
        json.dumps(rows[0], ensure_ascii=False, default=str)  # 必须可序列化为 JSON


if __name__ == "__main__":
    unittest.main(verbosity=2)
