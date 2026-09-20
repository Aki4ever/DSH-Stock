# -*- coding: utf-8 -*-
"""
REQ-021 持仓组合风险体检 单元测试
全部离线：行情与日线均为注入的真实形状 fixture，不联网、不读真实持仓配置。
重点在于：未核实持仓必须拒绝出结论；「无法判定」绝不能被呈现为「未触发」；
        峰值覆盖不完整必须标注而不是假装完整。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import portfolio_checkup  # noqa: E402
from scripts.portfolio_checkup import (  # noqa: E402
    DEFAULT_DYNAMIC_RULES, DEFAULT_STATIC_RULES, RULE_VERSION, _position_dynamic_rules,
    _position_static_rules, format_report, load_stock_config, resolve_config_path,
    run_checkup, verify_portfolio,
)


class FakeQuote:
    def __init__(self, code, price, prev_close, source="腾讯证券公开行情"):
        self.code, self.price, self.prev_close, self.source = code, price, prev_close, source


def position(code="sh600519", shares=100, cost=10.0, price=12.0, prev_close=11.9, buy_date="2026-01-05"):
    market_value = shares * price
    total_cost = shares * cost
    return {
        "code": code, "name": "测试标的", "shares": shares, "cost_price": cost,
        "buy_date": buy_date, "notes": "", "current_price": price, "prev_close": prev_close,
        "market_value": round(market_value, 2), "total_cost": round(total_cost, 2),
        "total_pnl": round(market_value - total_cost, 2),
        "total_pnl_pct": round((market_value - total_cost) / total_cost * 100, 2) if total_cost else None,
        "daily_pnl": round(shares * (price - prev_close), 2),
        "daily_pnl_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close else None,
    }


def bars(closes, start_day=1, highs=None):
    out = []
    for i, close in enumerate(closes):
        high = highs[i] if highs else close * 1.001
        out.append({"date": f"2026-02-{start_day + i:02d}", "open": close, "close": close,
                    "high": high, "low": close * 0.999, "volume": 1000, "amount_yi": None})
    return out


class PortfolioGateTests(unittest.TestCase):
    """门禁：未核实的持仓底册不得产出任何结论。"""

    def test_empty_portfolio_is_refused(self):
        ok, reason = verify_portfolio([], None)
        self.assertFalse(ok)
        self.assertIn("为空", reason)

    def test_unverified_portfolio_is_refused_with_actionable_reason(self):
        ok, reason = verify_portfolio([{"code": "sh600519"}], None)
        self.assertFalse(ok)
        self.assertIn("portfolio_verified", reason)
        self.assertIn("由持仓本人", reason, "必须指明由用户本人确认，而不是系统代为标记")

    def test_falsy_flag_variants_are_all_refused(self):
        for flag in (None, False, 0, "true", "True", 1):
            ok, _ = verify_portfolio([{"code": "sh600519"}], flag)
            self.assertFalse(ok, f"portfolio_verified={flag!r} 不得被视为已核实")

    def test_explicit_true_is_accepted(self):
        ok, _ = verify_portfolio([{"code": "sh600519"}], True)
        self.assertTrue(ok)

    def test_unverified_run_produces_no_positions_or_pnl_numbers(self):
        cfg_path = self._write_config({"portfolio": [{"code": "sh600519", "shares": 100, "cost_price": 10}],
                                       "portfolio_verified": False})
        with patch.object(portfolio_checkup, "get_batch_quotes") as fake:
            report = run_checkup(cfg_path)
        fake.assert_not_called()
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["positions"], [])
        self.assertEqual(report["summary"], {}, "未核实时不得产出任何汇总数字")
        self.assertEqual(report["portfolio_declared_count"], 1)
        self.assertIn("无法体检", format_report(report))

    def test_config_is_never_mutated_by_checkup(self):
        payload = {"portfolio": [{"code": "sh600519", "shares": 100, "cost_price": 10}],
                   "portfolio_verified": False}
        cfg_path = self._write_config(payload)
        before = Path(cfg_path).read_text(encoding="utf-8")
        run_checkup(cfg_path)
        self.assertEqual(Path(cfg_path).read_text(encoding="utf-8"), before,
                         "体检绝不能反过来修改用户配置（尤其不得自行打上已核实标记）")

    def _write_config(self, payload):
        path = Path(tempfile.mkdtemp()) / "stock_config.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)


class StaticRuleTests(unittest.TestCase):
    def static(self):
        return dict(DEFAULT_STATIC_RULES)

    def find(self, rules, rule_id):
        return [r for r in rules if r["rule_id"] == rule_id][0]

    def test_take_profit_triggers_at_or_above_threshold(self):
        rules = _position_static_rules(position(cost=10.0, price=12.0), self.static())  # +20%
        self.assertTrue(self.find(rules, "S1_take_profit")["triggered"])

    def test_take_profit_not_triggered_below_threshold(self):
        rules = _position_static_rules(position(cost=10.0, price=11.9), self.static())
        self.assertFalse(self.find(rules, "S1_take_profit")["triggered"])

    def test_stop_loss_triggers_at_or_below_threshold(self):
        rules = _position_static_rules(position(cost=10.0, price=9.2), self.static())  # -8%
        self.assertTrue(self.find(rules, "S2_stop_loss")["triggered"])

    def test_stop_loss_not_triggered_above_threshold(self):
        rules = _position_static_rules(position(cost=10.0, price=9.3), self.static())
        self.assertFalse(self.find(rules, "S2_stop_loss")["triggered"])

    def test_daily_surge_and_plunge_both_trigger_s3(self):
        up = _position_static_rules(position(cost=10.0, price=10.0, prev_close=9.4), self.static())
        down = _position_static_rules(position(cost=10.0, price=10.0, prev_close=10.6), self.static())
        self.assertTrue(self.find(up, "S3_daily_move")["triggered"])
        self.assertTrue(self.find(down, "S3_daily_move")["triggered"])

    def test_small_daily_move_does_not_trigger(self):
        rules = _position_static_rules(position(cost=10.0, price=10.0, prev_close=10.05), self.static())
        self.assertFalse(self.find(rules, "S3_daily_move")["triggered"])

    def test_every_static_rule_reports_the_real_numbers_used(self):
        rules = _position_static_rules(position(), self.static())
        self.assertEqual(len(rules), 3)
        for rule in rules:
            self.assertEqual(rule["status"], "evaluated")
            self.assertTrue(rule["detail"])
            self.assertTrue(rule["values"])


class DynamicRuleTests(unittest.TestCase):
    def dynamic(self, **over):
        return {**DEFAULT_DYNAMIC_RULES, **over}

    def find(self, rules, rule_id):
        return [r for r in rules if r["rule_id"] == rule_id][0]

    def test_ma_breakdown_triggers_when_price_below_ma(self):
        b = bars([10.0] * 20)
        rules = _position_dynamic_rules(position(price=9.5), self.dynamic(), b, None, "available",
                                       "2026-01-01", None, None)
        rule = self.find(rules, "D1_ma_breakdown")
        self.assertTrue(rule["triggered"])
        self.assertAlmostEqual(rule["values"]["ma_value"], 10.0, places=2)
        self.assertLess(rule["values"]["deviation_pct"], 0)

    def test_ma_breakdown_not_triggered_when_price_above_ma(self):
        b = bars([10.0] * 20)
        rules = _position_dynamic_rules(position(price=10.5), self.dynamic(), b, None, "available",
                                        "2026-01-01", None, None)
        self.assertFalse(self.find(rules, "D1_ma_breakdown")["triggered"])

    def test_ma_rule_is_unavailable_not_untriggered_when_bars_missing(self):
        rules = _position_dynamic_rules(position(), self.dynamic(), [], "来源未获取", "unavailable",
                                        None, None, None)
        rule = self.find(rules, "D1_ma_breakdown")
        self.assertFalse(rule["triggered"])
        self.assertEqual(rule["status"], "unavailable",
                         "缺数据必须标为无法判定，不能与「未触发」混为一谈")
        self.assertIn("来源未获取", rule["detail"])

    def test_ma_rule_disabled_when_configured_off(self):
        rules = _position_dynamic_rules(position(), self.dynamic(enable_ma_breakdown=False),
                                        bars([10.0] * 20), None, "available", None, None, None)
        self.assertEqual(self.find(rules, "D1_ma_breakdown")["status"], "disabled")

    def test_chanlun_sell_rule_reports_signal_types_and_actionability(self):
        signals = [{"signal_type": "S1", "time": "2026-02-10", "status": "confirmed",
                    "actionable": True, "stop_price": 13.0, "reason": "顶背离", "rule_version": "REQ-019/v1"},
                   {"signal_type": "S3", "time": "2026-02-11", "status": "provisional",
                    "actionable": False, "stop_price": 12.5, "reason": "跌破中枢", "rule_version": "REQ-019/v1"}]
        rules = _position_dynamic_rules(position(), self.dynamic(), bars([10.0] * 20), None, "available",
                                        None, signals, None)
        rule = self.find(rules, "D2_chanlun_sell")
        self.assertTrue(rule["triggered"])
        self.assertEqual(rule["values"]["signal_types"], ["S1", "S3"])
        self.assertEqual(rule["values"]["actionable_count"], 1)
        self.assertEqual(len(rule["values"]["signals"]), 2)
        self.assertIn("rule_version", rule["values"]["signals"][0])

    def test_chanlun_sell_rule_unavailable_when_signals_missing(self):
        rules = _position_dynamic_rules(position(), self.dynamic(), bars([10.0] * 20), None, "available",
                                        None, None, "结构计算失败")
        rule = self.find(rules, "D2_chanlun_sell")
        self.assertEqual(rule["status"], "unavailable")
        self.assertIn("结构计算失败", rule["detail"])

    def test_trailing_stop_triggers_on_drawdown_from_held_period_peak(self):
        b = bars([10.0] * 19 + [10.0], highs=[10.0] * 19 + [10.0])
        b[-1]["high"] = 14.0   # 持仓期最高价
        rules = _position_dynamic_rules(position(price=12.0, buy_date="2026-02-01"), self.dynamic(),
                                        b, None, "available", "2026-01-01", None, None)
        rule = self.find(rules, "D3_trailing_stop")
        self.assertTrue(rule["triggered"])
        self.assertEqual(rule["values"]["peak_price"], 14.0)
        self.assertAlmostEqual(rule["values"]["drawdown_pct"], 14.29, places=1)

    def test_trailing_stop_ignores_bars_before_buy_date(self):
        b = bars([10.0] * 20)
        b[0]["high"] = 50.0     # 买入日之前的极端高点，必须被排除
        b[-1]["date"] = "2026-02-20"
        rules = _position_dynamic_rules(position(price=10.0, buy_date="2026-02-15"), self.dynamic(),
                                        b, None, "available", "2026-01-01", None, None)
        rule = self.find(rules, "D3_trailing_stop")
        self.assertLess(rule["values"]["peak_price"], 50.0, "买入日之前的最高价不得计入持仓期峰值")

    def test_trailing_stop_marks_incomplete_peak_coverage(self):
        b = bars([10.0] * 20, start_day=10)
        rules = _position_dynamic_rules(position(price=9.0, buy_date="2015-01-05"), self.dynamic(),
                                        b, None, "available", "2026-02-10", None, None)
        rule = self.find(rules, "D3_trailing_stop")
        self.assertTrue(rule["values"]["peak_coverage_incomplete"])
        self.assertIn("可能被低估", rule["detail"])

    def test_trailing_stop_unavailable_without_bars(self):
        rules = _position_dynamic_rules(position(), self.dynamic(), [], "来源未获取", "unavailable",
                                        None, None, None)
        rule = self.find(rules, "D3_trailing_stop")
        self.assertEqual(rule["status"], "unavailable")
        self.assertIn("不回退用现价冒充峰值", rule["detail"])

    def test_trailing_stop_unavailable_when_no_bars_after_buy_date(self):
        b = bars([10.0] * 20, start_day=1)
        rules = _position_dynamic_rules(position(buy_date="2026-06-01"), self.dynamic(), b, None,
                                        "available", "2026-02-01", None, None)
        self.assertEqual(self.find(rules, "D3_trailing_stop")["status"], "unavailable")

    def test_data_status_is_carried_into_rule_values(self):
        b = bars([10.0] * 20)
        rules = _position_dynamic_rules(position(price=9.0), self.dynamic(), b, None, "stale",
                                        "2026-01-01", None, None)
        self.assertEqual(self.find(rules, "D1_ma_breakdown")["values"]["data_status"], "stale")
        self.assertEqual(self.find(rules, "D3_trailing_stop")["values"]["data_status"], "stale")


class FullCheckupTests(unittest.TestCase):
    """端到端：注入真实形状行情与日线，验证汇总、跳过与权重。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / "stock_config.json"

    def write(self, portfolio, verified=True, **extra):
        payload = {"portfolio": portfolio, "portfolio_verified": verified,
                   "alert_rules": {"take_profit_ratio": 0.20, "stop_loss_ratio": -0.08,
                                   "daily_surge_ratio": 0.05, "daily_plunge_ratio": -0.05}}
        payload.update(extra)
        self.cfg.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(self.cfg)

    def test_full_run_computes_totals_weights_and_triggers(self):
        cfg = self.write([
            {"code": "sh600519", "name": "甲", "shares": 100, "cost_price": 10.0, "buy_date": "2026-01-05"},
            {"code": "sz000001", "name": "乙", "shares": 100, "cost_price": 20.0, "buy_date": "2026-01-05"},
        ])
        quotes = [FakeQuote("sh600519", 12.0, 11.9), FakeQuote("sz000001", 8.0, 7.8)]
        daily = {"bars": bars([10.0] * 20), "error": None, "data_status": "available",
                 "coverage_start": "2026-01-01", "coverage_end": "2026-02-20",
                 "source": "腾讯证券", "provider_history_complete": True}
        with patch.object(portfolio_checkup, "get_batch_quotes", return_value=quotes), \
             patch.object(portfolio_checkup, "fetch_daily_bars", return_value=daily), \
             patch.object(portfolio_checkup, "analyze_code", return_value={"signals": [], "errors": {}}):
            report = run_checkup(cfg)
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["rule_version"], RULE_VERSION)
        s = report["summary"]
        self.assertEqual(s["position_count"], 2)
        self.assertEqual(s["total_market_value"], 2000.0)
        self.assertEqual(s["total_cost"], 3000.0)
        self.assertEqual(s["total_floating_pnl"], -1000.0)
        weights = [p["weight_pct"] for p in report["positions"]]
        self.assertAlmostEqual(sum(weights), 100.0, places=1)
        self.assertTrue(report["disclaimer"])

    def test_missing_quote_skips_position_and_warns(self):
        cfg = self.write([
            {"code": "sh600519", "name": "甲", "shares": 100, "cost_price": 10.0, "buy_date": "2026-01-05"},
            {"code": "sz000001", "name": "乙", "shares": 100, "cost_price": 20.0, "buy_date": "2026-01-05"},
        ])
        quotes = [FakeQuote("sh600519", 12.0, 11.9)]  # 乙 的行情缺失
        daily = {"bars": bars([10.0] * 20), "error": None, "data_status": "available",
                 "coverage_start": "2026-01-01", "coverage_end": "2026-02-20",
                 "source": "s", "provider_history_complete": True}
        with patch.object(portfolio_checkup, "get_batch_quotes", return_value=quotes), \
             patch.object(portfolio_checkup, "fetch_daily_bars", return_value=daily), \
             patch.object(portfolio_checkup, "analyze_code", return_value={"signals": [], "errors": {}}):
            report = run_checkup(cfg)
        self.assertEqual(report["summary"]["position_count"], 1)
        self.assertEqual(report["summary"]["skipped_count"], 1)
        self.assertEqual(report["summary"]["total_market_value"], 1200.0,
                         "未获取行情的持仓不得计入市值")
        self.assertTrue(any("sz000001" in w for w in report["warnings"]))

    def test_all_quotes_missing_yields_unavailable_not_zero_pnl(self):
        cfg = self.write([{"code": "sh600519", "name": "甲", "shares": 100, "cost_price": 10.0}])
        with patch.object(portfolio_checkup, "get_batch_quotes", return_value=[]):
            report = run_checkup(cfg)
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["positions"], [])
        self.assertIn("未产出任何体检结论", report["reason"])

    def test_stale_daily_data_is_warned_and_still_marked(self):
        cfg = self.write([{"code": "sh600519", "name": "甲", "shares": 100, "cost_price": 10.0,
                           "buy_date": "2026-01-05"}])
        quotes = [FakeQuote("sh600519", 12.0, 11.9)]
        daily = {"bars": bars([10.0] * 20), "error": "HTTP 501", "data_status": "stale",
                 "coverage_start": "2026-01-01", "coverage_end": "2026-02-20",
                 "source": "腾讯证券", "provider_history_complete": True}
        with patch.object(portfolio_checkup, "get_batch_quotes", return_value=quotes), \
             patch.object(portfolio_checkup, "fetch_daily_bars", return_value=daily), \
             patch.object(portfolio_checkup, "analyze_code", return_value={"signals": [], "errors": {}}):
            report = run_checkup(cfg)
        self.assertEqual(report["positions"][0]["data_status"], "stale")
        self.assertTrue(any("日线来源当前不可用" in w for w in report["warnings"]))
        self.assertIn("不一定是最新交易日", " ".join(report["warnings"]))

    def test_no_stale_flag_downgrades_rules_to_unavailable(self):
        cfg = self.write([{"code": "sh600519", "name": "甲", "shares": 100, "cost_price": 10.0,
                           "buy_date": "2026-01-05"}])
        quotes = [FakeQuote("sh600519", 12.0, 11.9)]
        daily = {"bars": bars([10.0] * 20), "error": "HTTP 501", "data_status": "stale",
                 "coverage_start": "2026-01-01", "coverage_end": "2026-02-20",
                 "source": "s", "provider_history_complete": True}
        with patch.object(portfolio_checkup, "get_batch_quotes", return_value=quotes), \
             patch.object(portfolio_checkup, "fetch_daily_bars", return_value=daily), \
             patch.object(portfolio_checkup, "analyze_code", return_value={"signals": [], "errors": {}}):
            report = run_checkup(cfg, allow_stale=False)
        pos = report["positions"][0]
        self.assertIn("D1_ma_breakdown", pos["unavailable_rules"])
        self.assertIn("D3_trailing_stop", pos["unavailable_rules"])

    def test_env_var_override_and_empty_env_var_edge_case(self):
        import os as _os
        cfg = self.write([], verified=False)
        # 显式参数优先
        self.assertEqual(portfolio_checkup.resolve_config_path(cfg), cfg)
        # 空/空白环境变量等同未设置，不得解析为空路径
        old = _os.environ.get("DSH_STOCK_CONFIG")
        try:
            for value in ("", "   "):
                _os.environ["DSH_STOCK_CONFIG"] = value
                resolved = portfolio_checkup.resolve_config_path()
                self.assertTrue(resolved.endswith("stock_config.json"), resolved)
                self.assertNotEqual(resolved.strip(), "")
            _os.environ["DSH_STOCK_CONFIG"] = cfg
            self.assertEqual(portfolio_checkup.resolve_config_path(), cfg)
        finally:
            if old is None:
                _os.environ.pop("DSH_STOCK_CONFIG", None)
            else:
                _os.environ["DSH_STOCK_CONFIG"] = old

    def test_stock_portfolio_uses_same_path_precedence(self):
        import os as _os
        from scripts import stock_portfolio
        cfg = self.write([], verified=False)
        old = _os.environ.get("DSH_STOCK_CONFIG")
        try:
            _os.environ["DSH_STOCK_CONFIG"] = ""
            self.assertTrue(stock_portfolio.load_config()["system"]["project_name"])
            _os.environ["DSH_STOCK_CONFIG"] = cfg
            self.assertEqual(stock_portfolio.load_config()["portfolio"], [],
                             "两条 CLI 路径必须读出同一份底册")
        finally:
            if old is None:
                _os.environ.pop("DSH_STOCK_CONFIG", None)
            else:
                _os.environ["DSH_STOCK_CONFIG"] = old

    def test_empty_portfolio_reason_is_explicit(self):
        cfg = self.write([])
        with patch.object(portfolio_checkup, "get_batch_quotes") as fake:
            report = run_checkup(cfg)
        fake.assert_not_called()
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["portfolio_declared_count"], 0)
        self.assertIn("未配置任何持仓", report["reason"])

    def test_config_loader_reads_real_shape(self):
        cfg = self.write([{"code": "sh600519", "shares": 1, "cost_price": 1}])
        loaded = load_stock_config(cfg)
        self.assertIn("portfolio", loaded)
        with self.assertRaises(OSError):
            load_stock_config(str(self.tmp / "nope.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
