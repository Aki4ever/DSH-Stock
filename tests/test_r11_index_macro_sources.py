#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R11 物理层补强测试：把两个「有界面、有接口、无物理源」的功能钉在真实链路上。

覆盖：
    A. 成分股（中证A50 / 中证A100）：
       - `config/constituents.json` 必须带 `verified_source` + `as_of`（否则加载门拒绝）；
       - 名单只能来自 `scripts/index_constituents.py` 的抓取口径，**不是手写常量**；
       - 抓取器解析、市场前缀归一、落盘结构、写库只动两个标记位（用临时库，零写产品库）；
       - `clean_legacy_stock(..., keep_constituent=True)` 保留名单标记，默认仍置空（旧行为不变）。
    B. 宏观模块：
       - 三个真实来源的解析器（腾讯指数 / 新浪商品 / 东财快讯）在**构造响应**下的解析正确性；
       - 任一来源失败 → 如实为空并给出 errors，**不补造数值**；
       - 综合评分口径可复算（50 + 平均涨跌幅×10，夹取 0~100）；
       - 不可用时不返回任何伪造评分。

在线冒烟（真实 HTTP，默认跳过；设 `DSH_LIVE_TESTS=1` 开启）：
    真实调用三个来源与指数成分接口，断言解析出非空真实数据。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts import index_constituents as ic  # noqa: E402
from scripts import world_macro_engine as wm  # noqa: E402

LIVE = os.environ.get("DSH_LIVE_TESTS") == "1"


class ConstituentConfigTest(unittest.TestCase):
    """A1：落盘名单必须是「已核验」形态，否则 Web 加载门会静默丢弃。"""

    def test_config_has_verified_source_and_as_of(self):
        path = BASE_DIR / "config" / "constituents.json"
        self.assertTrue(path.exists(), "config/constituents.json 必须存在")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(data.get("verified_source"), "缺少 verified_source → 加载门拒绝")
        self.assertTrue(data.get("as_of"), "缺少 as_of → 加载门拒绝")
        self.assertIn("RPT_INDEX_COMPONENT", data.get("verified_source", ""),
                      "来源必须写明真实接口名，便于复核")

    def test_expected_rosters_present(self):
        data = json.loads((BASE_DIR / "config" / "constituents.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data.get("csi50") or []), 50, "中证A50 应为 50 只")
        self.assertEqual(len(data.get("csi100") or []), 100, "中证A100 应为 100 只")

    def test_loader_gate_accepts_file(self):
        """服务端加载门（同时要求两个字段）必须通过。"""
        data = json.loads((BASE_DIR / "config" / "constituents.json").read_text(encoding="utf-8"))
        self.assertTrue(bool(data.get("verified_source")) and bool(data.get("as_of")))


class ConstituentParserTest(unittest.TestCase):
    """A2：抓取器解析与归一化（构造响应，离线可复现）。"""

    def test_market_prefix_normalization(self):
        self.assertEqual(ic.to_prefixed("600519"), "sh600519")
        self.assertEqual(ic.to_prefixed("688981"), "sh688981")
        self.assertEqual(ic.to_prefixed("000001"), "sz000001")
        self.assertEqual(ic.to_prefixed("300750"), "sz300750")
        self.assertEqual(ic.to_prefixed("920222"), "bj920222")

    def test_fetch_index_members_paginates(self):
        """分页必须翻到底：首页满页 → 继续请求第二页。"""
        pages = {
            1: {"success": True, "result": {"count": 3, "data": [
                {"SECURITY_CODE": "600519"}, {"SECURITY_CODE": "600000"}]}},
            2: {"success": True, "result": {"count": 3, "data": [{"SECURITY_CODE": "000001"}]}},
        }
        calls = []

        def fake(url):
            page = int(url.split("pageNumber=")[1].split("&")[0])
            calls.append(page)
            return pages[page]

        with mock.patch.object(ic, "PAGE_SIZE", 2), mock.patch.object(ic, "_http_json", side_effect=fake):
            codes = ic.fetch_index_members("000300")
        self.assertEqual(codes, ["600519", "600000", "000001"])
        self.assertEqual(calls, [1, 2], "必须分页取全，不能只取首页")

    def test_fetch_raises_on_upstream_failure(self):
        """上游 success=false（如报表名不存在）必须抛错，不得被当成「空名单」静默通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "resp.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"success": False, "message": "报表配置不存在"}, handle)
            with mock.patch.object(
                    ic.urllib.request, "urlopen",
                    side_effect=lambda url, timeout=None: mock.MagicMock(
                        __enter__=lambda s_: mock.MagicMock(
                            read=lambda: open(path, "rb").read()),
                        __exit__=lambda *a: False)):
                with self.assertRaises(RuntimeError):
                    ic.fetch_index_members("930050")

    def test_sync_db_only_touches_two_flag_columns(self):
        """写库只动 is_csi50 / is_csi100，行情/名称等列必须原样不动。"""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "probe.db")
            conn = sqlite3.connect(db)
            conn.execute("""CREATE TABLE stocks_master (
                code TEXT PRIMARY KEY, name TEXT, price REAL,
                is_csi50 INTEGER DEFAULT 0, is_csi100 INTEGER DEFAULT 0)""")
            conn.execute("INSERT INTO stocks_master VALUES ('sh600519','贵州茅台',1234.5,1,0)")
            conn.execute("INSERT INTO stocks_master VALUES ('sz000001','平安银行',11.5,0,0)")
            conn.commit()
            conn.close()

            with mock.patch.object(ic, "DB_PATH", db):
                stats = ic.sync_db({"csi50": ["sz000001"], "csi100": ["sh600519", "sz000001"]})

            conn = sqlite3.connect(db)
            rows = dict((r[0], r[1:]) for r in conn.execute(
                "SELECT code, name, price, is_csi50, is_csi100 FROM stocks_master"))
            conn.close()
            self.assertEqual(rows["sh600519"][0], "贵州茅台", "名称被改动")
            self.assertEqual(rows["sh600519"][1], 1234.5, "行情被改动")
            self.assertEqual(rows["sh600519"][2:], (0, 1), "标记位应更新为 csi100")
            self.assertEqual(rows["sz000001"][2:], (1, 1))
            self.assertEqual(stats["is_csi50"]["after"], 1)
            self.assertEqual(stats["is_csi100"]["after"], 2)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "probe.db")
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE stocks_master (code TEXT, is_csi50 INTEGER DEFAULT 0, is_csi100 INTEGER DEFAULT 0)")
            conn.execute("INSERT INTO stocks_master VALUES ('sh600519',1,1)")
            conn.commit()
            conn.close()
            with mock.patch.object(ic, "DB_PATH", db):
                ic.sync_db({"csi50": ["sz000001"]}, dry_run=True)
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT is_csi50 FROM stocks_master WHERE code='sh600519'").fetchone()
            conn.close()
            self.assertEqual(row[0], 1, "dry-run 不得写库")


class CleanLegacyConstituentTest(unittest.TestCase):
    """A3：名单标记的保留/清空语义（默认旧行为不变）。"""

    def test_default_still_strips_constituent(self):
        from scripts.verified_quotes import clean_legacy_stock
        row = clean_legacy_stock({"code": "sh600519", "is_csi50": True, "is_csi100": True})
        self.assertIsNone(row["is_csi50"])
        self.assertIsNone(row["is_csi100"])
        self.assertEqual(row["constituent_status"], "unverified")

    def test_keep_constituent_preserves_verified_roster(self):
        from scripts.verified_quotes import clean_legacy_stock
        row = clean_legacy_stock({"code": "sh600519", "is_csi50": True, "is_csi100": False},
                                 keep_constituent=True)
        self.assertTrue(row["is_csi50"])
        self.assertFalse(row["is_csi100"])
        self.assertEqual(row["constituent_status"], "verified")
        other = clean_legacy_stock({"code": "sz000002", "is_csi50": False, "is_csi100": False},
                                   keep_constituent=True)
        self.assertEqual(other["constituent_status"], "not_listed")


class MacroParserTest(unittest.TestCase):
    """B1：三个真实来源的解析正确性（构造响应，离线可复现）。"""

    @staticmethod
    def _tencent_line(code, price, change_val, change_pct):
        fields = [""] * 33
        fields[1] = code
        fields[3] = str(price)
        fields[30] = "2026-10-01 11:51:00"
        fields[31] = str(change_val)
        fields[32] = str(change_pct)
        return 'v_' + code + '="' + "~".join(fields) + '";'

    TENCENT_FIXTURE = (
        _tencent_line.__func__("hkHSI", 24613.27, 89.70, 0.37) + "\n" +
        _tencent_line.__func__("usDJI", 50645.71, -260.34, -0.51) + "\n"
    ) if False else None  # 实际内容在 setUpClass 中构造（见下）

    SINA_FIXTURE = (
        'var hq_str_hf_GC="4188.352,,4189.900,4190.200,4222.800,4169.400,23:51:08,4186.700,4190.100,0,2,3,2026-10-01,纽约黄金,0";\n'
        'var hq_str_hf_CL="92.961,,92.950,92.970,92.970,88.790,23:51:08,90.420,90.400,0,7,12,2026-10-01,纽约原油,0";\n'
    )
    NEWS_FIXTURE = json.dumps({
        "data": {"list": [
            {"showTime": "2026-10-01 20:00:00", "title": "央行开展逆回购操作 维护流动性合理充裕",
             "mediaName": "财联社"},
            {"showTime": "2026-10-01 19:00:00", "title": "美联储官员称通胀仍需观察", "mediaName": "华尔街见闻"},
            {"showTime": "2026-10-01 18:00:00", "title": "某公司发布三季度业绩预告", "mediaName": "证券时报"},
        ]}
    }, ensure_ascii=False)

    @classmethod
    def setUpClass(cls):
        cls.TENCENT_FIXTURE = "\n".join([
            cls._tencent_line("hkHSI", 24613.27, 89.70, 0.37),
            cls._tencent_line("usDJI", 50645.71, -260.34, -0.51),
        ])

    def test_tencent_parser(self):
        with mock.patch.object(wm, "_fetch_text", return_value=self.TENCENT_FIXTURE):
            with mock.patch.object(wm, "GLOBAL_INDICES",
                                   [("hkHSI", "恒生指数"), ("usDJI", "道琼斯"), ("jpNI225", "日经225")]):
                items, errors = wm.fetch_global_indices()
        self.assertEqual([i["name"] for i in items], ["恒生指数", "道琼斯"])
        self.assertEqual(items[0]["price"], 24613.27)
        self.assertEqual(items[1]["change_pct"], -0.51)
        self.assertTrue(any("日经225" in e for e in errors), "缺失标的必须如实报错")

    def test_sina_parser_computes_change_from_prev_close(self):
        with mock.patch.object(wm, "_fetch_text", return_value=self.SINA_FIXTURE):
            with mock.patch.object(wm, "COMMODITIES",
                                   [("hf_GC", "纽约黄金", "美元/盎司"), ("hf_CL", "纽约原油", "美元/桶")]):
                items, errors = wm.fetch_commodities()
        self.assertEqual(errors, [])
        gold = items[0]
        self.assertAlmostEqual(gold["change_pct"], (4188.352 - 4186.700) / 4186.700 * 100, places=3)
        self.assertEqual(gold["unit"], "美元/盎司")

    def test_news_classification(self):
        with mock.patch.object(wm, "_fetch_text", return_value=self.NEWS_FIXTURE):
            events, errors = wm.fetch_news()
        self.assertEqual(errors, [])
        self.assertEqual([e["category"] for e in events],
                         ["domestic", "international", "unclassified"])

    def test_source_failure_yields_empty_and_reason(self):
        with mock.patch.object(wm, "_fetch_text", side_effect=OSError("network down")):
            items, errors = wm.fetch_global_indices()
            commodities, cmd_errors = wm.fetch_commodities()
            events, news_errors = wm.fetch_news()
        self.assertEqual(items, [])
        self.assertEqual(commodities, [])
        self.assertEqual(events, [])
        self.assertTrue(errors and cmd_errors and news_errors, "每个来源失败都必须给出原因")

    def test_score_math_is_recomputable(self):
        score, avg = wm._score_from_changes([1.0, -1.0, 2.0])
        self.assertAlmostEqual(avg, 2.0 / 3, places=4)
        self.assertAlmostEqual(score, round(50 + (2.0 / 3) * 10, 2), places=2)

    def test_score_clamped_and_none_when_no_data(self):
        self.assertEqual(wm._score_from_changes([100.0])[0], 100.0)
        self.assertEqual(wm._score_from_changes([-100.0])[0], 0.0)
        self.assertEqual(wm._score_from_changes([None, None]), (None, None))

    def test_engine_returns_no_fabricated_score_when_all_sources_fail(self):
        with mock.patch.object(wm, "fetch_global_indices", return_value=([], ["idx down"])), \
             mock.patch.object(wm, "fetch_global_indices_backup", return_value=([], [])), \
             mock.patch.object(wm, "fetch_commodities", return_value=([], ["cmd down"])), \
             mock.patch.object(wm, "fetch_news", return_value=([], ["news down"])):
            data = wm.WorldMacroEngine.get_world_macro_intelligence()
        self.assertEqual(data["status"], "unavailable")
        self.assertIsNone(data["aggregate_score"]["total_score"])
        self.assertEqual(data["global_indices"], [])
        self.assertEqual(data["commodities"], [])
        self.assertEqual(data["world_events"], [])
        self.assertIn("idx down", data["errors"])

    def test_engine_composes_score_from_real_payload(self):
        indices = [{"code": "x", "name": "X", "price": 1.0, "change_pct": 1.0, "source": "s"}]
        commodities = [{"code": "y", "name": "Y", "price": 1.0, "change_pct": -1.0, "source": "s"}]
        with mock.patch.object(wm, "fetch_global_indices", return_value=(indices, [])), \
             mock.patch.object(wm, "fetch_global_indices_backup", return_value=([], [])), \
             mock.patch.object(wm, "fetch_commodities", return_value=(commodities, [])), \
             mock.patch.object(wm, "fetch_news", return_value=([], [])):
            data = wm.WorldMacroEngine.get_world_macro_intelligence()
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["aggregate_score"]["total_score"], 50.0)
        self.assertEqual(data["aggregate_score"]["avg_change_pct"], 0.0)
        self.assertIn("50 +", data["aggregate_score"]["score_basis"])


@unittest.skipUnless(LIVE, "在线冒烟：设置 DSH_LIVE_TESTS=1 后才真实请求上游")
class LiveSourceSmokeTest(unittest.TestCase):
    """真实 HTTP 冒烟：证明这些链路**当下真的可达**（非永久门禁，依赖外网）。"""

    def test_live_constituents(self):
        codes = ic.fetch_index_members("930050")
        self.assertEqual(len(codes), 50, f"中证A50 应取到 50 只，实得 {len(codes)}")

    def test_live_macro(self):
        indices, _ = wm.fetch_global_indices()
        commodities, _ = wm.fetch_commodities()
        events, _ = wm.fetch_news()
        self.assertGreaterEqual(len(indices), 5, "全球指数应至少取到 5 个真实标的")
        self.assertGreaterEqual(len(commodities), 3, "商品应至少取到 3 个真实合约")
        self.assertGreaterEqual(len(events), 5, "宏观快讯应至少取到 5 条真实标题")
        for item in indices:
            self.assertIsInstance(item["price"], float)
            self.assertTrue(item["source"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
