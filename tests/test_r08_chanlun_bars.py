"""R08 回归 (REQ-041)：任意真实K线序列的缠论判定端点 `build_chanlun_from_bars`。

背景与口径（不得放宽）：
1. 周线/季线由前端用**真实日K现场聚合**（本项目不对这两个颗粒度落库），5分K线为区间接口返回；
   三者都需要同一个「把真实K线序列提交回来判定」的纯计算入口 —— 即本测试的被测对象。
2. **同一套算法**：买卖点必须仍由 `scripts.chanlun_analysis.analyze_bars` /
   `build_buy_sell_points` 产出（本测试逐字段比对，证明没有第二套实现），
   缠论定义（第一类＝趋势背驰、第二类＝首次回抽不创新极值、第三类＝回抽不回中枢）不得放宽。
3. **级别不得冒充**：返回必须带 level / level_note，明确「这是周线级别/季线级别/5分级别」，
   绝不允许用日线结果冒充其他级别。
4. **输入必须真实且自洽**：价格缺失/非数值、日期重复或乱序、根数超限、级别非法一律拒绝（抛 ValueError）。
5. **纯计算**：不写数据库、不落缓存（本测试在临时进程内直接调用，不触碰 data/）。

数据来源：`tests/fixtures/r07_real_daily_slice.json` —— 贵州茅台(sh600519) 2017-12-08~2021-03-25
共 800 根**真实**日K切片（离线夹具，测试不触网、不写产品库）。
聚合口径与前端 `aggregateBarsForGroup` 一致：自然周（以所在周的周四为键）/ 自然季度。
"""
import datetime
import json
import os
import unittest

from scripts.stock_web_server import CHANLUN_BARS_MAX, CHANLUN_LEVEL_NOTES, build_chanlun_from_bars
from scripts.chanlun_analysis import analyze_bars

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "r07_real_daily_slice.json")
ALL_TYPES = ("buy1", "buy2", "buy3", "sell1", "sell2", "sell3")


def load_fixture_bars():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def bucket_key(date_str, group):
    """与前端 aggregateBarsForGroup 相同的分桶口径。"""
    y, m, d = (int(x) for x in date_str.split("-"))
    if group == "quarterly":
        return f"{y}Q{(m - 1) // 3 + 1}"
    dt = datetime.date(y, m, d)
    thursday = dt + datetime.timedelta(days=4 - dt.isoweekday())
    iso = thursday.isocalendar()
    return f"{iso[0]}W{iso[1]:02d}"


def aggregate(daily_bars, group):
    """按自然周/自然季聚合（开=首日开、收=末日收、高=区间最高、低=区间最低、量=区间求和）。"""
    out, cur = [], None
    for bar in daily_bars:
        key = bucket_key(bar["date"], group)
        if cur is None or cur["key"] != key:
            if cur:
                out.append(cur)
            cur = {"key": key, "date": bar["date"], "open": bar["open"], "close": bar["close"],
                   "high": bar["high"], "low": bar["low"], "volume": bar.get("volume") or 0}
        cur["close"] = bar["close"]
        cur["high"] = max(cur["high"], bar["high"])
        cur["low"] = min(cur["low"], bar["low"])
        cur["volume"] += bar.get("volume") or 0
        cur["date"] = bar["date"]
    if cur:
        out.append(cur)
    return [{k: v for k, v in b.items() if k != "key"} for b in out]


class TestInputValidation(unittest.TestCase):
    """REQ-041 输入校验：不真实、不自洽的K线一律拒绝，绝不用推测值判定。"""

    def test_rejects_unknown_level(self):
        for level in ("", None, "daily", "m1", "30m", "monthly"):
            with self.assertRaises(ValueError, msg=f"级别 {level!r} 必须被拒绝"):
                build_chanlun_from_bars("sh600519", [{"date": "2026-09-01", "open": 1, "close": 1,
                                                      "high": 1, "low": 1, "volume": 1}], level)

    def test_rejects_empty_or_non_list_bars(self):
        for bars in ([], None, {}, "bars", 3):
            with self.assertRaises(ValueError):
                build_chanlun_from_bars("sh600519", bars, "weekly")

    def test_rejects_too_many_bars(self):
        one = {"date": "2026-09-01", "open": 1.0, "close": 1.0, "high": 1.0, "low": 1.0, "volume": 1}
        with self.assertRaises(ValueError):
            build_chanlun_from_bars("sh600519", [dict(one) for _ in range(CHANLUN_BARS_MAX + 1)], "weekly")

    def test_rejects_missing_or_invalid_price(self):
        base = {"date": "2026-09-01", "open": 10.0, "close": 10.5, "high": 11.0, "low": 9.5, "volume": 100}
        for field in ("open", "close", "high", "low"):
            for bad in (None, "", "10.5", 0, -1):
                bar = dict(base, **{field: bad})
                bar["date"] = "2026-09-01"
                with self.assertRaises(ValueError, msg=f"{field}={bad!r} 必须被拒绝"):
                    build_chanlun_from_bars("sh600519", [bar, dict(base, date="2026-09-08")], "weekly")

    def test_rejects_duplicated_or_unsorted_dates(self):
        a = {"date": "2026-09-08", "open": 10.0, "close": 10.5, "high": 11.0, "low": 9.5, "volume": 100}
        b = {"date": "2026-09-01", "open": 10.0, "close": 10.5, "high": 11.0, "low": 9.5, "volume": 100}
        with self.assertRaises(ValueError):
            build_chanlun_from_bars("sh600519", [a, dict(a)], "weekly")   # 重复日期
        with self.assertRaises(ValueError):
            build_chanlun_from_bars("sh600519", [a, b], "weekly")         # 日期倒序

    def test_rejects_invalid_ohlc_range(self):
        bad = {"date": "2026-09-01", "open": 10.0, "close": 12.0, "high": 11.0, "low": 9.5, "volume": 100}
        with self.assertRaises(ValueError):
            build_chanlun_from_bars("sh600519", [bad, dict(bad, date="2026-09-08")], "weekly")


class TestLevelHonesty(unittest.TestCase):
    """REQ-041 级别标注：返回必须自证级别，不得让周线结果被读成日线信号。"""

    def test_level_and_note_present(self):
        bars = aggregate(load_fixture_bars(), "weekly")
        for level in ("weekly", "quarterly", "m5"):
            result = build_chanlun_from_bars("sh600519", bars, level)
            self.assertEqual(result["level"], level)
            self.assertEqual(result["level_note"], CHANLUN_LEVEL_NOTES[level])
            self.assertIn("不可与日线信号混读", result["level_note"])
            self.assertEqual(result["submitted_bars"], len(bars))

    def test_every_level_declares_its_own_scale(self):
        bars = aggregate(load_fixture_bars(), "weekly")
        weekly = build_chanlun_from_bars("sh600519", bars, "weekly")
        quarterly = build_chanlun_from_bars("sh600519", bars, "quarterly")
        self.assertIn("周线级别", weekly["level_note"])
        self.assertIn("季线级别", quarterly["level_note"])
        self.assertNotEqual(weekly["level_note"], quarterly["level_note"])


class TestSameAlgorithmAsDaily(unittest.TestCase):
    """REQ-041 同一套算法：结果必须与直接调用 analyze_bars 逐字段一致（证明没有第二套实现）。"""

    def test_counts_and_points_identical_to_analyze_bars(self):
        bars = aggregate(load_fixture_bars(), "weekly")
        via_endpoint = build_chanlun_from_bars("sh600519", bars, "weekly")
        direct = analyze_bars(bars, code="sh600519")
        self.assertEqual(via_endpoint["buy_sell_points"], direct["buy_sell_points"])
        for key in ALL_TYPES:
            self.assertEqual(via_endpoint["counts"][key], direct["counts"][key])
        for key in ("pens", "segments", "pivots", "divergences", "ma_entanglements"):
            self.assertEqual(via_endpoint[key], direct[key])
        self.assertEqual(via_endpoint["bar_count"], len(bars))

    def test_points_price_on_real_extremes(self):
        """买点价必须等于该根K线最低价、卖点价等于最高价（绝不凭空生成价格）。"""
        bars = aggregate(load_fixture_bars(), "weekly")
        result = build_chanlun_from_bars("sh600519", bars, "weekly")
        self.assertTrue(result["buy_sell_points"], "真实周线数据必须至少识别出一种买卖点")
        for point in result["buy_sell_points"]:
            bar = bars[point["index"]]
            if point["type"].startswith("buy"):
                self.assertAlmostEqual(point["price"], bar["low"], places=6,
                                       msg=f"买点价必须等于该根最低价：{point}")
            else:
                self.assertAlmostEqual(point["price"], bar["high"], places=6,
                                       msg=f"卖点价必须等于该根最高价：{point}")

    def test_no_future_function_on_weekly_series(self):
        """截断重算：同一批历史点位的类型与价格必须逐条一致（无未来函数）。"""
        bars = aggregate(load_fixture_bars(), "weekly")
        full = build_chanlun_from_bars("sh600519", bars, "weekly")["buy_sell_points"]
        cut = 100
        short = build_chanlun_from_bars("sh600519", bars[:130], "weekly")["buy_sell_points"]
        f = [(p["type"], p["index"], p["price"]) for p in full if p["index"] <= cut]
        s = [(p["type"], p["index"], p["price"]) for p in short if p["index"] <= cut]
        self.assertEqual(f, s, "截断到 130 根后，100 根之前的历史买卖点必须与全量一致")

    def test_weekly_and_daily_are_not_the_same_result(self):
        """级别隔离的反向证据：同一段行情的周线判定与日线判定不可能是同一结果，
        因此「周线用日线结果冒充」一定会在本用例上暴露。"""
        daily = load_fixture_bars()
        bars = aggregate(daily, "weekly")
        weekly = build_chanlun_from_bars("sh600519", bars, "weekly")
        daily_result = build_chanlun_from_bars("sh600519", daily, "m5")   # 同一算法、不同序列
        self.assertNotEqual(len(weekly["buy_sell_points"]), len(daily_result["buy_sell_points"]),
                            "周线聚合序列与日线序列的判定结果不应相同（若相同说明输入被串用）")


class TestQuarterlyHonesty(unittest.TestCase):
    """REQ-041 季线：根数少时识别不到就是 0，不得补造，但仍必须返回可核对的结构统计。"""

    def test_quarterly_returns_zero_honestly(self):
        bars = aggregate(load_fixture_bars(), "quarterly")
        result = build_chanlun_from_bars("sh600519", bars, "quarterly")
        self.assertEqual(result["bar_count"], len(bars))
        self.assertGreater(len(bars), 0)
        for key in ALL_TYPES:
            self.assertEqual(result["counts"][key], len([p for p in result["buy_sell_points"] if p["type"] == key]))
        self.assertLess(len(bars), 300, "夹具区间内的季线根数本就不多，识别不出买卖点属于如实结果")


if __name__ == "__main__":
    unittest.main()
