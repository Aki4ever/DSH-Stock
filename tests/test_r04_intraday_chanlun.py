"""R04 回归 (REQ-024)：分时级别缠论分析入口。

口径铁律：
1. 分时点视为 1 根 K 线（开=收=高=低=该分钟价），复用同一套缠论算法，不另起一套；
2. 级别必须显式标注为「分时级别」，不得与日线级别混读；
3. 来源未提供分时明细或缺有效成交价时，必须如实返回 unavailable 与原因，
   绝不伪造结构（禁止用日线或推测数据冒充分时）。
所有分时数据均为测试内构造，不触网、不写产品库。
"""
import unittest
from unittest.mock import patch

from scripts import stock_web_server


def _timeline(items, date="20260918", source="构造分时来源", error=None):
    payload = {"source": source, "status": "available" if items else "unavailable", "date": date, "items": items}
    if error:
        payload["error"] = error
    return payload


def _minute_items(count=80, start="09:30"):
    """构造连续分钟点：价格按正弦波动，保证分型/笔具备可识别结构。"""
    import math
    hh, mm = int(start.split(":")[0]), int(start.split(":")[1])
    items = []
    for i in range(count):
        total = hh * 60 + mm + i
        clock = f"{total // 60:02d}:{total % 60:02d}"
        price = round(10 + math.sin(i / 6.0) * 0.8 + i * 0.002, 2)
        items.append({"time": clock, "price": price, "volume": 100 + i, "amount_yi": 0.01 + i * 0.001})
    return items


class IntradayChanlunTests(unittest.TestCase):
    def test_uses_minute_points_as_bars_and_labels_intraday_level(self):
        items = _minute_items()
        with patch.object(stock_web_server, "fetch_real_timeline", return_value=_timeline(items)):
            result = stock_web_server.build_intraday_chanlun("sh600519")
        self.assertEqual(result["level"], "intraday", "级别必须显式标注为分时级别")
        self.assertIn("不等于日线级别", result["level_note"], "必须说明分时级别与日线级别的区别")
        self.assertEqual(result["bar_count"], len(items), "每根分时点必须折算为 1 根 K 线")
        for key in ("pens", "segments", "pivots", "divergences", "ma_entanglements"):
            self.assertIn(key, result, f"五类缠论结构必须齐备: {key}")
        self.assertEqual(result["dates"][0], "2026-09-18 09:30", "分时K线必须带唯一且可排序的日期")
        self.assertEqual(len(set(result["dates"])), len(result["dates"]), "分时K线日期必须唯一")

    def test_dates_are_strictly_increasing_for_analyze_bars(self):
        items = _minute_items(count=60)
        with patch.object(stock_web_server, "fetch_real_timeline", return_value=_timeline(items)):
            result = stock_web_server.build_intraday_chanlun("sh600519")
        dates = result["dates"]
        self.assertEqual(dates, sorted(dates), "分时K线日期必须严格递增")
        self.assertEqual(dates, sorted(set(dates)), "分时K线日期必须无重复")

    def test_unavailable_when_source_provides_no_items(self):
        with patch.object(stock_web_server, "fetch_real_timeline",
                          return_value=_timeline([], date=None, error="腾讯分时不可用")):
            result = stock_web_server.build_intraday_chanlun("sh600519")
        self.assertEqual(result["status"], "unavailable", "无分时明细必须如实 unavailable")
        self.assertEqual(result["counts"], {}, "不可用时不得产出任何结构计数")
        self.assertIn("腾讯分时不可用", result["error"], "必须保留来源给出的真实原因")

    def test_unavailable_when_all_prices_invalid(self):
        items = [{"time": "09:30", "price": None}, {"time": "09:31", "price": 0}]
        with patch.object(stock_web_server, "fetch_real_timeline", return_value=_timeline(items)):
            result = stock_web_server.build_intraday_chanlun("sh600519")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("缺少有效成交价", result["error"])

    def test_invalid_prices_are_skipped_not_invented(self):
        items = [{"time": "09:30", "price": 10.0}, {"time": "09:31", "price": None}, {"time": "09:32", "price": 10.2}]
        with patch.object(stock_web_server, "fetch_real_timeline", return_value=_timeline(items)):
            result = stock_web_server.build_intraday_chanlun("sh600519")
        self.assertEqual(result["bar_count"], 2, "无效价格必须被剔除而不是补造")
        self.assertNotIn("09:31", " ".join(result["dates"]), "被剔除的分钟点不得出现在分析结果中")

    def test_missing_trade_date_is_unavailable(self):
        items = _minute_items(count=10)
        with patch.object(stock_web_server, "fetch_real_timeline", return_value=_timeline(items, date=None)):
            result = stock_web_server.build_intraday_chanlun("sh600519")
        self.assertEqual(result["status"], "unavailable", "分时交易日缺失时不得产出结构")


if __name__ == "__main__":
    unittest.main()
