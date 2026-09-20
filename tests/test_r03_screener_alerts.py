# -*- coding: utf-8 -*-
"""
REQ-020 策略选股引擎 + 飞书/钉钉告警通道 单元测试
全部离线：构造 K 线与结构 fixture 直接驱动判定层，告警一律不产生真实网络请求。
重点在于证明每条判据都能单独否决命中，以及密钥绝不外泄、未配置绝不假装成功。
"""
import base64
import hashlib
import hmac
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import alert_channels, stock_db, strategy_screener  # noqa: E402
from scripts.alert_channels import (  # noqa: E402
    alert_key_of, channel_status, dingtalk_signature, dispatch, feishu_signature,
    format_hit_alert, load_notify_config, mask_webhook, notify_hits, send_message,
)
from scripts.chanlun_signals import RULE_VERSION as SIGNAL_RULE_VERSION  # noqa: E402


def make_bars(count=60, *, base=10.0, last_close=12.0, last_volume=3000.0, volume=1000.0):
    """构造真实形状的日线：前期横盘、最后一根为突破+放量日。"""
    bars = []
    for i in range(count):
        close = base + (i % 5) * 0.02
        bars.append({"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": close,
                     "close": close, "high": close * 1.01, "low": close * 0.99,
                     "volume": volume, "amount_yi": None, "change_pct": None})
    bars[-1]["close"] = last_close
    bars[-1]["high"] = last_close * 1.01
    bars[-1]["volume"] = last_volume
    return bars


def make_analysis(*, with_divergence=True, pivot_status="confirmed",
                  pivot_zg=11.0, pivot_zd=9.5, pivot_end="2026-02-10",
                  divergence_time="2026-02-01"):
    pens = [
        {"start_time": "2026-01-05", "end_time": "2026-01-20", "start_price": 13.0, "end_price": 10.0,
         "direction": -1, "status": "confirmed", "start_index": 2, "end_index": 12,
         "high": 13.0, "low": 10.0, "macd_area": 2.0},
        {"start_time": "2026-01-20", "end_time": "2026-02-05", "start_price": 10.0, "end_price": 12.0,
         "direction": 1, "status": "confirmed", "start_index": 12, "end_index": 22,
         "high": 12.0, "low": 10.0, "macd_area": 1.5},
        {"start_time": "2026-02-05", "end_time": "2026-02-25", "start_price": 12.0, "end_price": 9.6,
         "direction": -1, "status": "provisional", "start_index": 22, "end_index": 32,
         "high": 12.0, "low": 9.6, "macd_area": 0.8},
    ]
    divergences = []
    if with_divergence:
        divergences.append({"time": divergence_time, "price": 9.6, "index": 32, "direction": -1,
                            "kind": "底背离", "status": "provisional",
                            "previous_area": 2.0, "current_area": 0.8, "reference_time": "2026-01-20"})
    pivots = [{"start_time": "2026-01-05", "end_time": pivot_end, "zg": pivot_zg, "zd": pivot_zd,
               "level": "pen", "start_index": 2, "end_index": 22, "status": pivot_status}]
    return {"status": "available", "pens": pens, "pivots": pivots, "divergences": divergences,
            "segments": [], "ma_entanglements": [],
            "dates": [b["date"] for b in make_bars()], "counts": {},
            "rules": {"version": "1.0"}, "ma": {}, "bar_count": 60}


PARAMS = {"divergence_lookback": 8, "min_breakout_pct": 0.5, "volume_window": 20, "volume_ratio": 1.5}


class ScreenerCriteriaTests(unittest.TestCase):
    """三条判据都必须能单独否决命中——任一条件不成立就不许凑出命中。"""

    def evaluate(self, bars=None, analysis=None, params=None, price=12.0):
        return strategy_screener.evaluate_dip_divergence_breakout(
            bars if bars is not None else make_bars(last_close=price),
            analysis if analysis is not None else make_analysis(),
            {**PARAMS, **(params or {})}, price)

    def test_hit_when_all_three_criteria_met(self):
        out = self.evaluate()
        self.assertTrue(out["hit"], out.get("reason"))
        ev = out["evidence"]
        self.assertGreater(ev["breakout_pct"], PARAMS["min_breakout_pct"])
        self.assertGreaterEqual(ev["volume_ratio_actual"], PARAMS["volume_ratio"])
        self.assertEqual(ev["divergence_time"], "2026-02-01")

    def test_miss_without_bottom_divergence(self):
        out = self.evaluate(analysis=make_analysis(with_divergence=False))
        self.assertFalse(out["hit"])
        self.assertIn("底背离", out["reason"])

    def test_miss_when_divergence_outside_lookback_window(self):
        # 底背离时间早于最近 1 笔的起点 → 落在回溯窗口之外
        out = self.evaluate(analysis=make_analysis(divergence_time="2025-12-01"), params={"divergence_lookback": 1})
        self.assertFalse(out["hit"])
        self.assertIn("底背离", out["reason"])

    def test_miss_when_close_below_pivot_zg(self):
        out = self.evaluate(price=10.5)
        self.assertFalse(out["hit"])
        self.assertIn("未有效突破", out["reason"])

    def test_miss_when_breakout_pct_below_threshold(self):
        # 收盘 11.02，ZG=11.0 → 幅度 0.18% < 要求 0.5%
        out = self.evaluate(price=11.02)
        self.assertFalse(out["hit"])
        self.assertIn("未有效突破", out["reason"])

    def test_miss_when_volume_ratio_insufficient(self):
        out = self.evaluate(bars=make_bars(last_close=12.0, last_volume=1200.0))
        self.assertFalse(out["hit"])
        self.assertIn("放量不足", out["reason"])
        self.assertFalse(out["evidence"]["volume_ok"])

    def test_miss_when_pivot_is_not_confirmed(self):
        out = self.evaluate(analysis=make_analysis(pivot_status="provisional"))
        self.assertFalse(out["hit"])
        self.assertIn("已确认的笔中枢", out["reason"])

    def test_miss_when_pivot_ended_before_divergence(self):
        # 中枢结束时间早于底背离 → 属于先突破后衰竭的反向结构
        out = self.evaluate(analysis=make_analysis(pivot_end="2026-01-10", divergence_time="2026-02-20"))
        self.assertFalse(out["hit"])
        self.assertIn("反向结构", out["reason"])

    def test_miss_when_not_enough_bars(self):
        out = self.evaluate(bars=make_bars(count=15), analysis=make_analysis())
        self.assertFalse(out["hit"])
        self.assertIn("不足", out["reason"])

    def test_miss_when_volume_missing_and_no_fabricated_amount(self):
        bars = make_bars(last_close=12.0)
        for bar in bars[-21:-1]:
            bar["volume"] = 0
        out = self.evaluate(bars=bars)
        self.assertFalse(out["hit"])
        self.assertIn("成交量", out["reason"])

    def test_evidence_carries_every_real_number_used(self):
        ev = self.evaluate()["evidence"]
        for key in ("divergence_previous_area", "divergence_current_area", "divergence_area_ratio",
                    "pivot_zg", "pivot_zd", "breakout_pct", "volume", "avg_volume",
                    "volume_window", "volume_ratio_actual", "volume_ratio_required", "close"):
            self.assertIn(key, ev)
            self.assertIsNotNone(ev[key], f"{key} 不得为空")


class ScreenerSecurityTests(unittest.TestCase):
    """单只证券判定的端到端（离线注入 bars）。"""

    def test_stale_history_is_refused_instead_of_masquerading_as_today(self):
        stale = {"bars": make_bars(last_close=12.0), "error": "HTTP 501", "data_status": "stale",
                 "coverage_end": "2026-09-18", "source": "腾讯证券", "provider_history_complete": True}
        with patch.object(strategy_screener, "fetch_daily_bars", return_value=stale):
            result = strategy_screener.screen_security("sh600519", "贵州茅台")
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["hit"])
        self.assertIn("不以历史数据冒充当日信号", result["reason"])

    def test_unavailable_history_reports_source_error(self):
        gone = {"bars": [], "error": "HTTP Error 501", "data_status": "unavailable",
                "coverage_end": None, "source": "", "provider_history_complete": False}
        with patch.object(strategy_screener, "fetch_daily_bars", return_value=gone):
            result = strategy_screener.screen_security("sh600519", "贵州茅台")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("HTTP Error 501", result["reason"])

    def test_hit_carries_risk_budget_and_structure_refs(self):
        fresh = {"bars": make_bars(last_close=12.0), "error": None, "data_status": "available",
                 "coverage_end": "2026-09-18", "source": "腾讯证券", "provider_history_complete": True}
        with patch.object(strategy_screener, "fetch_daily_bars", return_value=fresh), \
             patch.object(strategy_screener, "analyze_bars", return_value=make_analysis()):
            result = strategy_screener.screen_security("sh600519", "贵州茅台")
        self.assertTrue(result["hit"], result.get("reason"))
        hit = result["signal"]
        self.assertEqual(hit["rule_version"], strategy_screener.RULE_VERSION)
        self.assertEqual(hit["analysis_rules_version"], "1.0")
        self.assertEqual(hit["stop_price"], 11.0, "结构止损必须是中枢上沿 ZG")
        self.assertIsNone(hit["target_price"], "本策略不臆造目标位")
        self.assertIn("target_note", hit)
        self.assertTrue(hit["structure"]["pivot"]["zg"])
        self.assertIn("risk_budget_note", hit)

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaises(ValueError):
            strategy_screener.screen_security("sh600519", "", strategy="not-a-strategy")

    def test_format_hit_line_never_prints_shares_for_non_actionable(self):
        hit = {"code": "sh600519", "name": "贵州茅台", "strategy": "s", "strategy_name": "n",
               "close": 10.0, "pivot_zg": 11.0, "volume_ratio": 2.0, "risk_pct": -3.0,
               "actionable": False, "risk_budget_note": "结构已被证伪", "reason": "r",
               "evidence": {"breakout_pct": 1.0, "volume_window": 20}}
        text = strategy_screener.format_hit_line(hit)
        self.assertIn("不可执行", text)
        self.assertNotIn("建议股数:", text)


class AlertChannelTests(unittest.TestCase):
    """密钥保护、未配置不假装成功、签名正确性。"""

    SECRET = "dsh-test-secret-please-rotate"
    WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/abcdef12-3456-7890-abcd-ef1234567890"

    def test_feishu_signature_matches_independent_hmac(self):
        ts = 1758000000
        expected = base64.b64encode(
            hmac.new(f"{ts}\n{self.SECRET}".encode(), digestmod=hashlib.sha256).digest()).decode()
        self.assertEqual(feishu_signature(self.SECRET, ts), expected)

    def test_dingtalk_signature_matches_independent_hmac_and_is_url_encoded(self):
        ts = 1758000000
        raw = base64.b64encode(
            hmac.new(self.SECRET.encode(), f"{ts}\n{self.SECRET}".encode(), hashlib.sha256).digest()).decode()
        self.assertEqual(dingtalk_signature(self.SECRET, ts), urllib.parse.quote_plus(raw))

    def test_mask_webhook_never_reveals_full_token(self):
        masked = mask_webhook(self.WEBHOOK)
        self.assertIn("open.feishu.cn", masked)
        self.assertNotIn("abcdef12", masked)
        self.assertLess(len(masked), len(self.WEBHOOK))
        self.assertEqual(mask_webhook(""), "")

    def test_unconfigured_channel_reports_not_configured_without_request(self):
        config = json.loads(json.dumps(alert_channels.DEFAULT_CONFIG))
        with patch.object(alert_channels, "_post_json") as fake:
            out = send_message("测试", "feishu", config)
        fake.assert_not_called()
        self.assertFalse(out["sent"])
        self.assertFalse(out["configured"])
        self.assertIn("未配置", out["reason"])

    def test_non_https_webhook_is_refused(self):
        config = json.loads(json.dumps(alert_channels.DEFAULT_CONFIG))
        config["feishu"]["webhook"] = "http://open.feishu.cn/hook/token1234"
        with patch.object(alert_channels, "_post_json") as fake:
            out = send_message("测试", "feishu", config)
        fake.assert_not_called()
        self.assertFalse(out["ok"])
        self.assertIn("https", out["reason"])

    def test_dry_run_validates_without_any_network_call(self):
        config = json.loads(json.dumps(alert_channels.DEFAULT_CONFIG))
        config["feishu"] = {"webhook": self.WEBHOOK, "secret": self.SECRET}
        with patch.object(alert_channels, "_post_json") as fake:
            out = send_message("测试文本", "feishu", config, dry_run=True)
        fake.assert_not_called()
        self.assertTrue(out["ok"])
        self.assertFalse(out["sent"])
        self.assertTrue(out["dry_run"])
        self.assertTrue(out["signed"])

    def test_config_status_never_contains_secret_or_raw_webhook(self):
        config = json.loads(json.dumps(alert_channels.DEFAULT_CONFIG))
        config["feishu"] = {"webhook": self.WEBHOOK, "secret": self.SECRET}
        dumped = json.dumps(channel_status(config), ensure_ascii=False)
        self.assertNotIn(self.SECRET, dumped)
        self.assertNotIn("abcdef12", dumped)

    def test_unknown_channel_is_rejected(self):
        out = send_message("测试", "wechat")
        self.assertFalse(out["ok"])
        self.assertIn("未知通道", out["reason"])

    def test_dispatch_without_any_configured_channel_returns_explicit_reason(self):
        config = json.loads(json.dumps(alert_channels.DEFAULT_CONFIG))
        out = dispatch("测试", None, config)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["sent"])
        self.assertIn("未配置任何告警通道", out[0]["reason"])

    def test_load_config_falls_back_to_safe_defaults_on_bad_file(self):
        tmp = Path(tempfile.mkdtemp()) / "broken.json"
        tmp.write_text("{not json", encoding="utf-8")
        config = load_notify_config(str(tmp))
        self.assertFalse(config["enabled"])
        self.assertEqual(config["feishu"]["webhook"], "")
        missing = load_notify_config(str(Path(tempfile.mkdtemp()) / "nope.json"))
        self.assertFalse(missing["enabled"])

    def test_alert_text_states_facts_and_disclaimer(self):
        hit = {"strategy": "dip-divergence-breakout", "strategy_name": "底背驰 + 放量突破中枢",
               "code": "sh600519", "name": "贵州茅台", "side": "buy", "signal_type": "底背驰放量突破",
               "period": "daily", "close": 12.0, "pivot_zg": 11.0, "volume_ratio": 2.1,
               "volume_window": 20, "reason": "依据文本", "entry_price": 12.0, "stop_price": 11.0,
               "risk_pct": 8.33, "actionable": True, "suggested_shares": 200,
               "rule_version": SIGNAL_RULE_VERSION}
        text = format_hit_alert(hit)
        for token in ("贵州茅台", "sh600519", "ZG：11.0", "2.1 倍", "200", "不构成投资建议"):
            self.assertIn(token, text)

    def test_alert_key_is_stable_per_structure(self):
        hit = {"strategy": "s", "code": "sh600519", "signal_type": "底背驰放量突破",
               "period": "daily", "trade_date": "2026-09-18"}
        self.assertEqual(alert_key_of(hit), alert_key_of(dict(hit)))
        self.assertNotEqual(alert_key_of(hit), alert_key_of(dict(hit, trade_date="2026-09-19")))


class AlertPersistenceTests(unittest.TestCase):
    """冷却与流水必须在隔离临时库上验证；且流水里绝不能出现任何密钥。"""

    SECRET = "dsh-super-secret-token"
    WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=deadbeefcafe1234"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsh_alert_")
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

    def config(self, enabled=True, cooldown=240):
        return {"enabled": enabled, "cooldown_minutes": cooldown, "max_per_run": 20,
                "timeout_seconds": 5,
                "feishu": {"webhook": self.WEBHOOK, "secret": self.SECRET},
                "dingtalk": {"webhook": "", "secret": ""}}

    def hit(self, **over):
        base = {"strategy": "dip-divergence-breakout", "strategy_name": "底背驰 + 放量突破中枢",
                "code": "sh600519", "name": "贵州茅台", "side": "buy", "signal_type": "底背驰放量突破",
                "period": "daily", "trade_date": "2026-09-18", "close": 12.0, "pivot_zg": 11.0,
                "volume_ratio": 2.0, "volume_window": 20, "reason": "r", "entry_price": 12.0,
                "stop_price": 11.0, "risk_pct": 8.33, "actionable": True, "suggested_shares": 200,
                "rule_version": SIGNAL_RULE_VERSION}
        base.update(over)
        return base

    def test_disabled_switch_sends_nothing(self):
        result = notify_hits([self.hit()], ["feishu"], self.config(enabled=False))
        self.assertFalse(result["enabled"])
        self.assertEqual(result["sent"], 0)
        self.assertIn("未启用", result["reason"])
        self.assertEqual(stock_db.list_alert_dispatch(), [])

    def test_successful_send_is_logged_and_persists_no_secret(self):
        with patch.object(alert_channels, "_post_json", return_value=(True, 200, "")):
            result = notify_hits([self.hit()], ["feishu"], self.config())
        self.assertEqual(result["sent"], 1)
        rows = stock_db.list_alert_dispatch()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ok"], 1)
        dumped = json.dumps(rows, ensure_ascii=False)
        self.assertNotIn(self.SECRET, dumped)
        self.assertNotIn("deadbeefcafe1234", dumped, "流水不得记录完整令牌")
        self.assertIn("oapi.dingtalk.com", rows[0]["target_hint"])

    def test_failed_send_is_logged_and_does_not_start_cooldown(self):
        with patch.object(alert_channels, "_post_json", return_value=(False, 500, "HTTP 500 boom")):
            result = notify_hits([self.hit()], ["feishu"], self.config())
        self.assertEqual(result["sent"], 0)
        rows = stock_db.list_alert_dispatch()
        self.assertEqual(rows[0]["ok"], 0)
        self.assertIn("boom", rows[0]["error"])
        key = alert_key_of(self.hit())
        self.assertEqual(stock_db.alert_cooldown_remaining(key, "feishu", 240), 0,
                         "失败的下发不得占用冷却窗口")

    def test_cooldown_suppresses_duplicate_after_success(self):
        with patch.object(alert_channels, "_post_json", return_value=(True, 200, "")):
            first = notify_hits([self.hit()], ["feishu"], self.config(cooldown=240))
            second = notify_hits([self.hit()], ["feishu"], self.config(cooldown=240))
        self.assertEqual(first["sent"], 1)
        self.assertEqual(second["sent"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertIn("冷却", second["results"][0]["reason"])
        self.assertEqual(len(stock_db.list_alert_dispatch()), 1, "冷却期内不得重复下发")

    def test_force_bypasses_cooldown(self):
        with patch.object(alert_channels, "_post_json", return_value=(True, 200, "")):
            notify_hits([self.hit()], ["feishu"], self.config(cooldown=240))
            forced = notify_hits([self.hit()], ["feishu"], self.config(cooldown=240), force=True)
        self.assertEqual(forced["sent"], 1)

    def test_different_trade_date_is_a_new_alert(self):
        with patch.object(alert_channels, "_post_json", return_value=(True, 200, "")):
            notify_hits([self.hit()], ["feishu"], self.config())
            later = notify_hits([self.hit(trade_date="2026-09-21")], ["feishu"], self.config())
        self.assertEqual(later["sent"], 1, "不同交易日的同一结构应视为新告警")

    def test_non_actionable_hits_are_never_pushed(self):
        with patch.object(alert_channels, "_post_json", return_value=(True, 200, "")) as fake:
            result = notify_hits([self.hit(actionable=False)], ["feishu"], self.config())
        fake.assert_not_called()
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["non_actionable_skipped"], 1)
        self.assertIn("无满足可执行条件", result["reason"])

    def test_max_per_run_caps_dispatch(self):
        hits = [self.hit(code=f"sh60000{i}", trade_date=f"2026-09-1{i}") for i in range(5)]
        config = self.config()
        config["max_per_run"] = 2
        with patch.object(alert_channels, "_post_json", return_value=(True, 200, "")):
            result = notify_hits(hits, ["feishu"], config)
        self.assertEqual(result["sent"], 2)
        self.assertEqual(result["overflow"], 3)

    def test_dry_run_writes_nothing_to_log(self):
        with patch.object(alert_channels, "_post_json") as fake:
            result = notify_hits([self.hit()], ["feishu"], self.config(), dry_run=True)
        fake.assert_not_called()
        self.assertEqual(stock_db.list_alert_dispatch(), [])
        self.assertTrue(result["dry_run"])


class ScreenResultPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dsh_screen_")
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

    def hit(self, code="sh600519", date="2026-09-18", score=1.0):
        return {"strategy": "dip-divergence-breakout", "code": code, "name": "贵州茅台",
                "trade_date": date, "score": score, "close": 12.0, "volume_ratio": 2.0,
                "pivot_zg": 11.0, "reason": "构造命中"}

    def test_replace_and_read_back(self):
        self.assertEqual(stock_db.replace_screen_results([self.hit()]), 1)
        rows = stock_db.list_screen_results()
        self.assertEqual(rows[0]["hit"]["reason"], "构造命中")
        self.assertNotIn("payload", rows[0])

    def test_second_scan_replaces_instead_of_appending(self):
        stock_db.replace_screen_results([self.hit(), self.hit(code="sz000001")])
        stock_db.replace_screen_results([self.hit(code="sh600036")])
        rows = stock_db.list_screen_results()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "sh600036")

    def test_ordering_uses_real_volume_ratio_not_an_invented_score(self):
        # 只按真实量比降序排序；score 字段即使被写入也不得影响顺序（不引入人造评分）
        stock_db.replace_screen_results([
            self.hit(code="sh600001"), self.hit(code="sz000002"),
            self.hit(code="sh600003"), self.hit(code="sz000004"),
        ])
        rows = stock_db.list_screen_results()
        ratios = [r["volume_ratio"] for r in rows]
        self.assertEqual(ratios, sorted(ratios, reverse=True), "命中清单必须按真实量比降序")
        self.assertTrue(all(r["volume_ratio"] is not None for r in rows))

    def test_filter_by_strategy_and_code(self):
        stock_db.replace_screen_results([self.hit(), self.hit(code="sz000001")])
        self.assertEqual(len(stock_db.list_screen_results(code="sz000001")), 1)
        self.assertEqual(len(stock_db.list_screen_results(strategy="nope")), 0)
        self.assertEqual(stock_db.screen_results_snapshot()["total"], 2)

    def test_empty_result_clears_without_error(self):
        stock_db.replace_screen_results([self.hit()])
        self.assertEqual(stock_db.replace_screen_results([]), 0)
        self.assertEqual(stock_db.screen_results_snapshot()["total"], 0)

    def test_screen_tables_do_not_touch_business_tables(self):
        with stock_db.get_db_connection() as conn:
            conn.execute("INSERT INTO stocks_master (code, raw_code, name, market, market_code, board, board_code)"
                         " VALUES ('sh600519','600519','贵州茅台','sh','sh','main','main');")
            conn.commit()
        stock_db.replace_screen_results([self.hit()])
        stock_db.record_alert_dispatch("k", "feishu", True, 200, "hint", "")
        with stock_db.get_db_connection() as conn:
            survived = conn.execute("SELECT COUNT(*) c FROM stocks_master;").fetchone()["c"]
        self.assertEqual(survived, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
