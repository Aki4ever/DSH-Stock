"""R07 回归 (REQ-040)：缠论三类买卖点识别。

口径铁律（与本项目既有 RULES 一致，不得放宽）：
1. **第一类买卖点** 必须建立在「趋势」之上 —— 两个同向且互不重叠的连续中枢；
   离开最后一个中枢的段相对进入段出现趋势背驰（价格创新极值 + MACD 绝对柱面积缩小）。
   项目 RULES 已明确「笔背离 ≠ 完整趋势背驰」，因此禁止用单笔背离冒充第一类买卖点。
2. **第二类买卖点** 必须紧跟第一类：之后第一次次级别回抽/反弹不创新极值。
3. **第三类买卖点** 必须是离开中枢后的回抽不重新回到中枢区间（买点回抽低点 > ZG，卖点反抽高点 < ZD）。
4. **无未来函数**：任一点位的判定只允许使用该点及其之前的数据；截断数据重算，历史点位必须逐条一致。
5. **点位必须落在真实极值上**：买点价格＝该根 K 线最低价，卖点价格＝该根 K 线最高价，
   绝不允许凭空生成价格；识别不到就是没有，不以任何方式补造。
6. 既有字段（pens/segments/pivots/divergences/ma_entanglements/ma/dates/counts/rules/parameters）
   结构与取值必须保持不变，本轮只新增 buy_sell_points 及 counts 中的分类计数。

数据来源：`tests/fixtures/r07_real_daily_slice.json` —— 贵州茅台(sh600519) 2017-12-08~2021-03-25
共 800 根**真实**日K切片（离线夹具，测试不触网、不写产品库）；另含本地构造的合成序列用于边界与反向验证。
"""
import json
import os
import unittest

from scripts.chanlun_analysis import analyze_bars, BS_LABELS, build_buy_sell_points

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "r07_real_daily_slice.json")
ALL_TYPES = ("buy1", "buy2", "buy3", "sell1", "sell2", "sell3")

# 夹具在「仅用自身 800 根」独立计算下的买卖点快照（防回归；由本测试首次生成后固化）
EXPECTED_SNAPSHOT = [
    ("sell3", "2018-08-28", 693.78),
    ("buy1", "2018-11-28", 545.5),
    ("sell3", "2018-12-13", 606.88),
    ("buy2", "2018-12-25", 553.61),
    ("buy3", "2019-03-08", 733.65),
    ("sell1", "2019-05-15", 933.0),
    ("buy3", "2019-05-23", 856.22),
    ("sell2", "2019-05-29", 924.95),
    ("sell1", "2019-09-25", 1188.87),
    ("buy3", "2019-10-10", 1109.02),
    ("sell1", "2020-06-08", 1435.0),
    ("buy3", "2020-06-15", 1381.0),
    ("sell1", "2020-09-02", 1828.0),
    ("buy3", "2020-09-23", 1621.02),
    ("sell2", "2020-10-13", 1750.62),
    ("buy3", "2021-03-09", 1900.18),
]


def load_fixture_bars():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["bars"]


def synth_bars(pivots, leg=8, start="2020-01-01"):
    """构造确定性的锯齿序列（每段 leg 根，段内线性插值），用于边界与反向验证。"""
    import datetime
    d0 = datetime.date.fromisoformat(start)
    bars, day, price = [], 0, pivots[0]
    for target in pivots[1:]:
        for k in range(1, leg + 1):
            prev = price
            price = prev + (target - prev) * (k / leg)
            o, c = prev, price
            bars.append({"date": (d0 + datetime.timedelta(days=day)).isoformat(),
                         "open": round(o, 2), "close": round(c, 2),
                         "high": round(max(o, c) * 1.002 + 0.02, 2),
                         "low": round(min(o, c) * 0.998 - 0.02, 2), "volume": 10000})
            day += 1
    return bars


class TestBuySellPointStructure(unittest.TestCase):
    """REQ-040 结构完整性：字段、索引、时间、标签。"""

    @classmethod
    def setUpClass(cls):
        cls.bars = load_fixture_bars()
        cls.analysis = analyze_bars(cls.bars, code="sh600519")
        cls.points = cls.analysis["buy_sell_points"]

    def test_fixture_is_real_daily_slice(self):
        self.assertEqual(len(self.bars), 800, "夹具必须是 800 根真实日K切片")
        self.assertEqual(self.bars[0]["date"], "2017-12-08")
        self.assertEqual(self.bars[-1]["date"], "2021-03-25")

    def test_point_fields_complete(self):
        self.assertTrue(self.points, "夹具必须能识别出买卖点")
        for p in self.points:
            for key in ("type", "label", "index", "time", "price", "reason", "status"):
                self.assertIn(key, p, f"买卖点缺少字段 {key}")
            self.assertIn(p["type"], ALL_TYPES)
            self.assertEqual(p["label"], BS_LABELS[p["type"]], "标签必须与类型一致")
            self.assertIsInstance(p["index"], int)
            self.assertTrue(0 <= p["index"] < len(self.bars), "索引必须落在数据范围内")
            self.assertEqual(p["time"], self.bars[p["index"]]["date"], "时间必须等于该索引的交易日")
            self.assertIn(p["status"], ("confirmed", "provisional"))
            self.assertTrue(p["reason"].strip(), "每个点必须给出判定依据，不允许无理由标记")

    def test_points_sorted_by_index(self):
        idx = [p["index"] for p in self.points]
        self.assertEqual(idx, sorted(idx), "买卖点必须按时间顺序排列")

    def test_counts_match_points(self):
        counts = self.analysis["counts"]
        self.assertEqual(counts["buy_sell_points"], len(self.points))
        for t in ALL_TYPES:
            self.assertEqual(counts[t], sum(1 for p in self.points if p["type"] == t),
                             f"counts[{t}] 必须与实例数量一致")

    def test_all_six_types_present(self):
        got = {p["type"] for p in self.points}
        self.assertEqual(got, set(ALL_TYPES), f"夹具必须覆盖六类买卖点，实际 {sorted(got)}")


class TestPointTruthfulness(unittest.TestCase):
    """REQ-040 真实性：标记必须锚定在真实K线极值上，且价格无编造。"""

    @classmethod
    def setUpClass(cls):
        cls.bars = load_fixture_bars()
        cls.points = analyze_bars(cls.bars, code="sh600519")["buy_sell_points"]

    def test_buy_at_low_sell_at_high(self):
        for p in self.points:
            bar = self.bars[p["index"]]
            want = bar["low"] if p["type"].startswith("buy") else bar["high"]
            self.assertAlmostEqual(p["price"], want, places=4,
                                   msg=f"{p['type']} {p['time']} 价格必须等于该根K线的{'最低' if p['type'].startswith('buy') else '最高'}价")

    def test_price_within_bar_range(self):
        for p in self.points:
            bar = self.bars[p["index"]]
            self.assertLessEqual(bar["low"] - 1e-9, p["price"])
            self.assertLessEqual(p["price"], bar["high"] + 1e-9)

    def test_snapshot_regression(self):
        got = [(p["type"], p["time"], p["price"]) for p in self.points]
        self.assertEqual(got, EXPECTED_SNAPSHOT,
                         "买卖点结果发生变化：若非算法调整，说明识别被意外改动")


class TestChanlunDefinitions(unittest.TestCase):
    """REQ-040 严格性：逐类用 pens / pivots 独立复核缠论定义。"""

    @classmethod
    def setUpClass(cls):
        cls.bars = load_fixture_bars()
        cls.analysis = analyze_bars(cls.bars, code="sh600519")
        cls.pens = cls.analysis["pens"]
        cls.pivots = cls.analysis["pivots"]
        cls.points = cls.analysis["buy_sell_points"]

    def _first_pen_from(self, index, direction=None):
        for p in self.pens:
            if p["start_index"] < index:
                continue
            if direction is not None and p["direction"] != direction:
                continue
            return p
        return None

    def _last_pen_before(self, index, direction):
        found = None
        for p in self.pens:
            if p["end_index"] <= index and p["direction"] == direction:
                found = p
        return found

    def test_first_type_requires_trend_and_weakening(self):
        """第一类：必须存在两个不重叠中枢的趋势结构，且离开段创新极值 + MACD 面积缩小。"""
        firsts = [p for p in self.points if p["type"] in ("buy1", "sell1")]
        self.assertTrue(firsts, "夹具必须存在第一类买卖点")
        for p in firsts:
            down = p["type"] == "buy1"
            matched = None
            for k in range(1, len(self.pivots)):
                prev, last = self.pivots[k - 1], self.pivots[k]
                if down and not last["zg"] < prev["zd"]:
                    continue
                if not down and not last["zd"] > prev["zg"]:
                    continue
                leave = self._first_pen_from(last["end_index"], -1 if down else 1)
                if not leave or leave["end_index"] != p["index"]:
                    continue
                enter = self._last_pen_before(last["start_index"], -1 if down else 1)
                if not enter or enter["macd_area"] <= 0:
                    continue
                extreme = leave["end_price"] < enter["end_price"] if down else leave["end_price"] > enter["end_price"]
                if extreme and leave["macd_area"] < enter["macd_area"]:
                    matched = (prev, last, enter, leave)
                    break
            self.assertIsNotNone(matched, f"{p['type']} {p['time']} 未找到满足「趋势+趋势背驰」的结构依据")

    def test_second_type_follows_first_and_holds_extreme(self):
        """第二类：必须紧跟同类第一类买卖点，且回抽不创新极值。"""
        seconds = [p for p in self.points if p["type"] in ("buy2", "sell2")]
        self.assertTrue(seconds, "夹具必须存在第二类买卖点")
        for p in seconds:
            down = p["type"] == "buy2"
            firsts = [q for q in self.points if q["type"] == ("buy1" if down else "sell1") and q["index"] <= p["index"]]
            self.assertTrue(firsts, f"{p['type']} {p['time']} 之前必须存在对应的第一类买卖点")
            first = firsts[-1]
            back = self._first_pen_from(first["index"], -1 if down else 1)
            self.assertIsNotNone(back, "第二类必须对应第一类之后的第一笔反向回抽/反弹")
            self.assertEqual(back["end_index"], p["index"], "第二类必须落在该回抽笔的终点")
            if down:
                self.assertGreater(p["price"], first["price"], "第二类买点不得跌破第一类买点")
            else:
                self.assertLess(p["price"], first["price"], "第二类卖点不得突破第一类卖点")

    def test_third_type_does_not_return_into_pivot(self):
        """第三类：必须存在中枢，且回抽不重新回到中枢区间。"""
        thirds = [p for p in self.points if p["type"] in ("buy3", "sell3")]
        self.assertTrue(thirds, "夹具必须存在第三类买卖点")
        for p in thirds:
            down = p["type"] == "buy3"     # 买点：向上离开后回调不回中枢（低点 > ZG）
            matched = False
            for c in self.pivots:
                leave = self._first_pen_from(c["end_index"], 1 if down else -1)
                if not leave:
                    continue
                beyond = leave["end_price"] > c["zg"] if down else leave["end_price"] < c["zd"]
                if not beyond:
                    continue
                back = self._first_pen_from(leave["end_index"], -1 if down else 1)
                if not back or back["end_index"] != p["index"]:
                    continue
                held = back["end_price"] > c["zg"] if down else back["end_price"] < c["zd"]
                if held:
                    matched = True
                    break
            self.assertTrue(matched, f"{p['type']} {p['time']} 未找到满足「离开中枢后回抽不回中枢」的结构依据")

    def test_reason_quotes_real_pivot_bounds(self):
        """判定依据里引用的中枢上下沿必须是真实中枢数值（可核对、不虚构）。"""
        bounds = {(round(c["zd"], 2), round(c["zg"], 2)) for c in self.pivots}
        for p in self.points:
            if p["type"] not in ("buy3", "sell3"):
                continue
            found = any(f"¥{zd:.2f}" in p["reason"] and f"¥{zg:.2f}" in p["reason"] for zd, zg in bounds)
            self.assertTrue(found, f"{p['type']} {p['time']} 的判定依据未引用真实中枢边界：{p['reason']}")


class TestNoFutureFunction(unittest.TestCase):
    """REQ-040 无未来函数：截断数据重算，历史点位必须逐条一致。"""

    def test_truncation_stability(self):
        bars = load_fixture_bars()
        full = analyze_bars(bars, code="x")["buy_sell_points"]
        cut = 550
        short = analyze_bars(bars[:600], code="x")["buy_sell_points"]
        f = [(p["type"], p["index"], p["price"]) for p in full if p["index"] <= cut]
        s = [(p["type"], p["index"], p["price"]) for p in short if p["index"] <= cut]
        self.assertEqual(f, s, "截断到 600 根后，550 根之前的历史买卖点必须与全量完全一致（否则存在未来函数）")

    def test_progressive_truncation_monotonic(self):
        """逐步截断：已确认的历史点位不得随数据增加而消失或改变。"""
        bars = load_fixture_bars()
        base = analyze_bars(bars[:700], code="x")["buy_sell_points"]
        more = analyze_bars(bars, code="x")["buy_sell_points"]
        cut = 620
        b = [(p["type"], p["index"], p["price"]) for p in base if p["index"] <= cut and p["status"] == "confirmed"]
        m = {(p["type"], p["index"], p["price"]) for p in more if p["status"] == "confirmed"}
        for item in b:
            self.assertIn(item, m, f"新增数据后历史已确认点位发生变化：{item}")


class TestAntiOvermarking(unittest.TestCase):
    """REQ-040 不滥发：无对应结构时必须不产生标记。"""

    def test_monotonic_uptrend_has_no_third_buy(self):
        """单边上涨（无中枢回抽结构）不得产生第三类买点。"""
        seq = [50 + i * 6 for i in range(14)]
        analysis = analyze_bars(synth_bars(seq), code="up")
        self.assertEqual(analysis["counts"]["buy3"], 0, "单边上涨不得产生第三类买点")
        self.assertEqual(analysis["counts"]["buy1"], 0, "单边上涨不得产生第一类买点")

    def test_downtrend_divergence_produces_first_buy_only(self):
        """标准下跌趋势背驰：必须产出第一类买点，且不得凭空产出第一类卖点。"""
        seq = [100, 70, 78, 68, 76, 60, 66, 52, 58, 46, 52, 40, 46, 34, 40]
        analysis = analyze_bars(synth_bars(seq), code="down")
        self.assertEqual(analysis["counts"]["buy1"], 1, "下跌趋势背驰必须产出第一类买点")
        self.assertEqual(analysis["counts"]["sell1"], 0, "下跌趋势中不得产出第一类卖点")

    def test_flat_series_produces_no_points(self):
        """横盘无波动：不得产生任何买卖点（禁止硬造）。"""
        seq = [50, 50, 50, 50, 50, 50, 50, 50]
        analysis = analyze_bars(synth_bars(seq), code="flat")
        self.assertEqual(analysis["counts"]["buy_sell_points"], 0, "无结构时不得产生任何买卖点")

    def test_insufficient_bars_is_safe(self):
        """数据不足：不抛错，且不产生买卖点。"""
        bars = load_fixture_bars()[:30]
        analysis = analyze_bars(bars, code="short")
        self.assertEqual(analysis["counts"]["buy_sell_points"], 0)


class TestExistingFieldsUnchanged(unittest.TestCase):
    """REQ-040 向后兼容：既有字段结构与语义完全不变（缠论雷达等既有链路不受影响）。"""

    def test_legacy_fields_present(self):
        bars = load_fixture_bars()
        analysis = analyze_bars(bars, code="sh600519")
        for key in ("pens", "segments", "pivots", "divergences", "ma_entanglements", "ma", "dates",
                    "counts", "rules", "parameters", "status", "bar_count", "code", "computed_on"):
            self.assertIn(key, analysis, f"既有字段 {key} 丢失")
        self.assertEqual(analysis["bar_count"], len(bars))
        self.assertEqual(analysis["dates"], [b["date"] for b in bars])
        self.assertEqual(analysis["status"], "available")

    def test_rules_extended_not_replaced(self):
        analysis = analyze_bars(load_fixture_bars(), code="x")
        self.assertEqual(analysis["rules"]["version"], "1.0", "规则版本不得被静默变更")
        for key in ("pen", "segment", "pivot", "divergence", "ma_entanglement", "buy_sell"):
            self.assertIn(key, analysis["rules"], f"规则说明缺少 {key}")
        self.assertIn("趋势背驰", analysis["rules"]["buy_sell"])

    def test_pivot_and_pen_fields_unchanged(self):
        analysis = analyze_bars(load_fixture_bars(), code="x")
        self.assertEqual(set(analysis["pens"][0].keys()),
                         {"start_time", "end_time", "start_price", "end_price", "start_index",
                          "end_index", "high", "low", "direction", "macd_area", "status"})
        self.assertEqual(set(analysis["pivots"][0].keys()),
                         {"start_time", "end_time", "zg", "zd", "level", "start_index", "end_index", "status"})

    def test_build_buy_sell_points_is_pure(self):
        """纯函数：同一输入两次调用结果一致，且不修改传入的笔/中枢。"""
        analysis = analyze_bars(load_fixture_bars(), code="x")
        pens = [dict(p) for p in analysis["pens"]]
        pivots = [dict(c) for c in analysis["pivots"]]
        first = build_buy_sell_points(pens, pivots)
        second = build_buy_sell_points(pens, pivots)
        self.assertEqual(first, second)
        self.assertEqual(pens, analysis["pens"], "不得修改传入的笔")
        self.assertEqual(pivots, analysis["pivots"], "不得修改传入的中枢")


if __name__ == "__main__":
    unittest.main()
