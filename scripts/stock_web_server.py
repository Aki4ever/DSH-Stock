#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH A股全市场量化筛选与持久化中枢服务端 (Stock Web Server)
版本: v1.2.0
遵循规范: rules/system/meta_rules.md

核心升级:
1. 前端双向启停控制：支持随时在线暂停业务引擎并在前端一键无缝再启动 (/api/server/start)
2. SQLite 本地数据库深度整合，爬虫数据自动落盘沉淀至 data/stock_database.db
3. 列表及详情全量支持「分红次数」与「上市总时长(年)」(精确到1位小数)
4. 全局版本号单一真理 (v1.2.0)，Title 与 Header 永久常显同步
5. 工业级反爬伪装与多源容灾，自毁守护与端口安全释放
"""

import os
import sys
import time
import json
import signal
import atexit
import argparse
import threading
import urllib.request
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Dict, List, Optional, Any, Tuple

# 路径常量加载
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
PID_FILE = os.path.join(BASE_DIR, ".server.pid")
VERSION_FILE = os.path.join(CONFIG_DIR, "version.json")
CONSTITUENTS_FILE = os.path.join(CONFIG_DIR, "constituents.json")
DB_FILE = os.path.join(DATA_DIR, "stock_database.db")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.anti_crawler import (
    robust_fetch,
    parse_shareholder_data,
    build_headers,
    get_random_user_agent
)
from scripts.stock_db import (
    init_db,
    save_master_stocks,
    save_quotes_batch,
    save_shareholder_item,
    update_ipo_and_dividend,
    load_all_stocks_from_db
)
from scripts.stock_data_engine import (
    StockQuote,
    KLineBar,
    normalize_code,
    generate_mock_quote,
    generate_mock_kline
)
from scripts.stock_indicators import evaluate_stock
from scripts.stock_chart_svg import generate_stock_svg
from scripts.manual_crawler import CRAWLER_JOB
from scripts.real_chart_engine import fetch_real_daily_kline, fetch_real_timeline
from scripts.company_finance_engine import fetch_company_profile, fetch_financial_statements
from scripts.dashboard_engine import compute_market_overview


# 读取全局版本号配置
def load_version_info() -> Dict[str, Any]:
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "version": "v1.2.0",
        "app_name": "A股多维量化筛选器",
        "subtitle": "DSH Stock Web",
        "release_date": "2026-09-16"
    }

VERSION_INFO = load_version_info()
APP_VERSION = VERSION_INFO.get("version", "v1.2.0")

# 服务运行状态机 (running: 引擎运行并抓取 | stopped: 引擎休眠暂停但保持 Web 控制中枢监听)
SERVER_STATE = "running"
SERVER_STATE_LOCK = threading.Lock()


class StockDataManager:
    """股票数据管理器：SQLite持久化中枢、批量反爬拉取与多维过滤"""
    def __init__(self):
        self._lock = threading.Lock()
        self.stocks_dict: Dict[str, Dict[str, Any]] = {}
        self.csi50_set = set()
        self.csi100_set = set()
        self.last_updated: float = 0.0
        self._init_database_and_load()
        self._start_background_worker()

    def _init_database_and_load(self):
        """初始化 SQLite 并加载全量标的底册"""
        init_db()
        # 加载成分股
        if os.path.exists(CONSTITUENTS_FILE):
            try:
                with open(CONSTITUENTS_FILE, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    self.csi50_set = set(cdata.get("csi50", []))
                    self.csi100_set = set(cdata.get("csi100", []))
            except Exception:
                pass

        # 从 SQLite 载入已沉淀的数据
        rows = load_all_stocks_from_db()
        with self._lock:
            for r in rows:
                code = r["code"]
                self.stocks_dict[code] = dict(r)

    def _start_background_worker(self):
        """后台异步守护线程：定期批量抓取最新行情并落盘到 SQLite"""
        def worker():
            time.sleep(1.0)
            # 首批优先拉取中证100核心资产
            core_codes = list(self.csi100_set) if self.csi100_set else list(self.stocks_dict.keys())[:100]
            self.fetch_quotes_batch(core_codes)

            while True:
                time.sleep(25)
                # 检查服务状态，若 stopped 则休眠等待启动
                with SERVER_STATE_LOCK:
                    current_state = SERVER_STATE
                if current_state != "running":
                    continue

                try:
                    with self._lock:
                        all_keys = list(self.stocks_dict.keys())
                    # 轮询更新尚未初始化价格的标的
                    uninit = [k for k in all_keys if self.stocks_dict[k]["price"] == 0.0][:120]
                    if uninit:
                        self.fetch_quotes_batch(uninit)
                except Exception:
                    pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def fetch_quotes_batch(self, codes: List[str]):
        """分批拉取行情，反爬伪装并自动写入 SQLite 数据库"""
        if not codes:
            return

        chunk_size = 45
        scraped_quotes = []

        for i in range(0, len(codes), chunk_size):
            chunk = codes[i:i + chunk_size]
            url = f"http://qt.gtimg.cn/q={','.join(chunk)}"
            content = robust_fetch(url, referer="http://gu.qq.com", timeout=3.5, max_retries=2, encoding="gbk")

            if content:
                for line in content.split(";"):
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    k, val = line.split("=", 1)
                    norm_c = k.replace("v_", "").strip()
                    parts = val.strip('";\n').split("~")
                    if len(parts) >= 46 and norm_c in self.stocks_dict:
                        with self._lock:
                            item = self.stocks_dict[norm_c]
                            item["name"] = parts[1]
                            item["price"] = float(parts[3])
                            item["prev_close"] = float(parts[4])
                            item["open"] = float(parts[5])
                            item["volume"] = float(parts[6])
                            item["high"] = float(parts[33]) if parts[33] else item["price"]
                            item["low"] = float(parts[34]) if parts[34] else item["price"]
                            item["turnover"] = float(parts[37]) * 10000 if parts[37] else 0.0
                            item["turnover_yi"] = round(item["turnover"] / 100000000.0, 2)
                            item["change"] = float(parts[31]) if parts[31] else round(item["price"] - item["prev_close"], 2)
                            item["change_pct"] = float(parts[32]) if parts[32] else 0.0
                            item["turnover_rate"] = float(parts[38]) if parts[38] else 0.0
                            item["pe"] = float(parts[39]) if parts[39] else 0.0
                            item["market_cap"] = float(parts[44]) if parts[44] else 0.0
                            item["circulating_cap"] = float(parts[45]) if parts[45] else 0.0
                            item["timestamp"] = parts[30]
                            item["is_mock"] = False
                            scraped_quotes.append(dict(item))

        # 异步事务落盘保存至 SQLite 数据库
        if scraped_quotes:
            try:
                save_quotes_batch(scraped_quotes)
            except Exception as e:
                sys.stderr.write(f"SQLite 批量写入行情异常: {e}\n")

    def get_stock_detail(self, code: str) -> Optional[Dict[str, Any]]:
        """获取个股完整详情、最新十大股东、分红、上市时长与 SVG 走势图"""
        norm, _ = normalize_code(code)

        # 在线拉取最新行情并落盘
        self.fetch_quotes_batch([norm])

        with self._lock:
            stock = self.stocks_dict.get(norm)

        if not stock:
            return None

        # 检查是否缺失十大股东数据，若缺失则通过爬虫抓取并落库持久化
        if stock["top10_hold_pct"] == 0.0 and stock["top10_circ_hold_pct"] == 0.0:
            sh_data = parse_shareholder_data(norm)
            if sh_data and (sh_data["top10_hold_pct"] > 0 or sh_data["top10_circ_hold_pct"] > 0):
                top10_hold = min(100.0, sh_data["top10_hold_pct"])
                top10_circ = min(100.0, sh_data["top10_circ_hold_pct"])
                rep_date = sh_data.get("report_date") or "最新期"
                with self._lock:
                    stock["top10_hold_pct"] = top10_hold
                    stock["top10_circ_hold_pct"] = top10_circ
                    stock["report_date"] = rep_date
                # 写入 SQLite
                save_shareholder_item(norm, rep_date, top10_hold, top10_circ)

        # 技术面评分与走势图
        quote_obj = StockQuote(
            code=stock["code"],
            name=stock["name"],
            price=stock["price"],
            prev_close=stock["prev_close"],
            open_price=stock["open"],
            high=stock["high"],
            low=stock["low"],
            volume=stock["volume"],
            turnover=stock["turnover"],
            change=stock["change"],
            change_pct=stock["change_pct"],
            market=stock["market_code"].upper(),
            is_mock=stock.get("is_mock", False)
        )

        # 获取上市以来的全量真实日K线与真实分时走势 (支持全周期上市至今走势)
        daily_bars = fetch_real_daily_kline(norm, limit=5000)
        timeline_data = fetch_real_timeline(norm)

        # 获取上市公司基本资料与四大深度财务报表
        company_profile = fetch_company_profile(norm, stock["name"], stock["market"], stock["board"])
        financial_reports = fetch_financial_statements(norm, stock["price"], stock["market_cap"], stock["pe"])

        bars = generate_mock_kline(norm, days=60, end_price=stock["price"])
        eval_report = evaluate_stock(norm, stock["name"], bars)
        svg_chart = generate_stock_svg(quote_obj, bars, width=860, height=450)

        detail = dict(stock)
        detail["evaluation"] = eval_report.to_dict()
        detail["svg_chart"] = svg_chart
        detail["daily_bars"] = daily_bars
        detail["timeline_data"] = timeline_data
        detail["company_profile"] = company_profile
        detail["financial_reports"] = financial_reports
        return detail

    def filter_stocks(self, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """多条件联合筛选（AND 严格逻辑）"""
        market = params.get("market", "all")
        board = params.get("board", "all")
        constituent = params.get("constituent", "all")
        filter_date = params.get("filter_date", "")

        def to_float(v):
            if v is None or v == "" or v == "null":
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        f_min_price = to_float(params.get("min_price"))
        f_max_price = to_float(params.get("max_price"))
        f_min_cap = to_float(params.get("min_market_cap"))
        f_max_cap = to_float(params.get("max_market_cap"))
        f_min_circ_cap = to_float(params.get("min_circ_cap"))
        f_max_circ_cap = to_float(params.get("max_circ_cap"))
        f_min_pe = to_float(params.get("min_pe"))
        f_max_pe = to_float(params.get("max_pe"))
        f_min_top10_circ = to_float(params.get("min_top10_circ"))
        f_max_top10_circ = to_float(params.get("max_top10_circ"))
        f_min_top10 = to_float(params.get("min_top10"))
        f_max_top10 = to_float(params.get("max_top10"))
        # 需求2: 上市时长区间 (年)
        f_min_listing_years = to_float(params.get("min_listing_years"))
        f_max_listing_years = to_float(params.get("max_listing_years"))
        keyword = str(params.get("keyword", "")).strip().lower()

        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 50))

        with self._lock:
            candidates = list(self.stocks_dict.values())

        # 阶段 1：静态快速过滤
        filtered_candidates = []
        for s in candidates:
            if market and market != "all" and s["market_code"] != market:
                continue
            if board and board != "all" and s["board_code"] != board:
                continue
            if constituent == "csi50" and not s["is_csi50"]:
                continue
            elif constituent == "csi100" and not s["is_csi100"]:
                continue
            # 关键字智能规则检索 (代码/名称/首字母拼音，全匹配优先，部分匹配兼容)
            if keyword:
                c_full = s["code"].lower()
                c_raw = s["raw_code"].lower()
                s_name = s["name"].lower()
                p_abbr = str(s.get("pinyin_abbr") or "").lower()

                # 1. 全匹配判定 (代码全等 或 名称全等 或 拼音缩写全等，如 GZMT)
                is_exact_match = (keyword == c_raw) or (keyword == c_full) or (keyword == s_name) or (keyword == p_abbr)

                # 2. 部分匹配判定 (包含或前缀，如 MT 匹配 GZMT)
                is_partial_match = (keyword in c_raw) or (keyword in c_full) or (keyword in s_name) or (keyword in p_abbr)

                if not (is_exact_match or is_partial_match):
                    continue
            filtered_candidates.append(s)

        # 阶段 2：检查行情，若处于 running 状态且有未拉取行情的标的则快速补充
        with SERVER_STATE_LOCK:
            current_state = SERVER_STATE
        if current_state == "running":
            unquoted = [c["code"] for c in filtered_candidates if c["price"] == 0.0][:60]
            if unquoted:
                self.fetch_quotes_batch(unquoted)

        # 阶段 3：多维数值严格联合判定 (AND)
        matched = []
        for s in filtered_candidates:
            if f_min_price is not None and s["price"] < f_min_price:
                continue
            if f_max_price is not None and s["price"] > f_max_price:
                continue
            if f_min_cap is not None and s["market_cap"] < f_min_cap:
                continue
            if f_max_cap is not None and s["market_cap"] > f_max_cap:
                continue
            if f_min_circ_cap is not None and s["circulating_cap"] < f_min_circ_cap:
                continue
            if f_max_circ_cap is not None and s["circulating_cap"] > f_max_circ_cap:
                continue
            if f_min_pe is not None and s["pe"] < f_min_pe:
                continue
            if f_max_pe is not None and s["pe"] > f_max_pe:
                continue
            if f_min_top10_circ is not None and s["top10_circ_hold_pct"] < f_min_top10_circ:
                continue
            if f_max_top10_circ is not None and s["top10_circ_hold_pct"] > f_max_top10_circ:
                continue
            if f_min_top10 is not None and s["top10_hold_pct"] < f_min_top10:
                continue
            if f_max_top10 is not None and s["top10_hold_pct"] > f_max_top10:
                continue
            # 需求2: 上市时长联合判定
            s_listing_years = float(s.get("listing_years") or 0.0)
            if f_min_listing_years is not None and s_listing_years < f_min_listing_years:
                continue
            if f_max_listing_years is not None and s_listing_years > f_max_listing_years:
                continue

            matched.append(dict(s))

        # 默认按总市值降序
        matched.sort(key=lambda x: x["market_cap"], reverse=True)

        total_matched = len(matched)
        avg_price = round(sum(s["price"] for s in matched) / total_matched, 2) if total_matched > 0 else 0.0
        avg_change = round(sum(s["change_pct"] for s in matched) / total_matched, 2) if total_matched > 0 else 0.0
        total_cap = round(sum(s["market_cap"] for s in matched), 2) if total_matched > 0 else 0.0
        total_circ_cap = round(sum(s["circulating_cap"] for s in matched), 2) if total_matched > 0 else 0.0

        # 需求1: 真实且同步的数据快照截取日期
        real_snapshot_date = filter_date or datetime.now().strftime("%Y-%m-%d")

        stats = {
            "total_universe_count": len(candidates),
            "matched_count": total_matched,
            "avg_price": avg_price,
            "avg_change_pct": avg_change,
            "total_market_cap": total_cap,
            "total_circ_cap": total_circ_cap,
            "filter_date": real_snapshot_date,
            "snapshot_date": real_snapshot_date,
            "page": page,
            "page_size": page_size,
            "server_state": current_state
        }

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_data = matched[start_idx:end_idx]

        # 需求2与需求3: 批量注入分红/总市值(%)及股东异动三兄弟指标
        from scripts.shareholder_engine import Top10ShareholdersEngine
        for s in paged_data:
            Top10ShareholdersEngine.enrich_stock_holder_metrics(s)

        return paged_data, stats


# 单例初始化
DATA_MANAGER = StockDataManager()
SERVER_START_TIME = time.time()
SERVER_INSTANCE = None
SHUTDOWN_REQUESTED = False


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StockRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # 安全防御性日志，支持任意参数长度，彻底杜绝 IndexError
        try:
            msg = format % args
        except Exception:
            msg = " ".join(str(a) for a in args)
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        url_path = self.path.split("?")[0]

        # 0. 浏览器图标直接快速返回 204 No Content，避免产生 404 与挂死
        if url_path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        # 1. 首页直接重定向至 web 界面
        if url_path in ("/", "/index.html"):
            index_path = os.path.join(WEB_DIR, "index.html")
            if os.path.exists(index_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(index_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # 2. 静态资源路由 /web/...
        if url_path.startswith("/web/"):
            rel_file = url_path[5:]
            file_path = os.path.join(WEB_DIR, rel_file)
            if os.path.exists(file_path) and os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                mime = "text/plain"
                if ext == ".html": mime = "text/html; charset=utf-8"
                elif ext == ".css": mime = "text/css; charset=utf-8"
                elif ext == ".js": mime = "application/javascript; charset=utf-8"
                elif ext == ".json": mime = "application/json; charset=utf-8"
                elif ext == ".svg": mime = "image/svg+xml"

                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # 3. 版本同步端点 /api/version
        if url_path == "/api/version":
            self._send_json(200, {
                "version": APP_VERSION,
                "info": VERSION_INFO
            })
            return

        # 3.1 独立爬虫状态 GET 兼容端点
        if url_path == "/api/crawler/status":
            self._send_json(200, CRAWLER_JOB.get_snapshot())
            return

        # 3.1.1 需求2: 独立数据采集中心导出端点 /api/crawler/export?format=json|csv
        if url_path == "/api/crawler/export":
            query_params = {}
            if "?" in self.path:
                q_str = self.path.split("?", 1)[1]
                for part in q_str.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        query_params[k.strip()] = v.strip()
            exp_format = query_params.get("format", "json").lower()
            all_stocks = list(DATA_MANAGER.stocks_dict.values())
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

            if exp_format == "csv":
                import csv
                import io
                out = io.StringIO()
                # 确定 CSV 核心列
                fieldnames = [
                    "code", "name", "market", "board", "price", "change_pct", "change",
                    "prev_close", "open", "high", "low", "volume", "turnover_yi",
                    "turnover_rate", "pe", "market_cap", "circulating_cap",
                    "dividend_count", "dividend_total_amount", "listing_years",
                    "top10_hold_pct", "top10_circ_hold_pct", "pinyin_abbr"
                ]
                writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for s in all_stocks:
                    writer.writerow(s)
                csv_bytes = out.getvalue().encode("utf-8-sig")

                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="stock_data_export_{date_str}.csv"')
                self.send_header("Content-Length", str(len(csv_bytes)))
                self.end_headers()
                self.wfile.write(csv_bytes)
                return
            else:
                # 默认导出 JSON
                export_pack = {
                    "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "version": APP_VERSION,
                    "total_universe_count": len(all_stocks),
                    "fingerprint_engine": "SHA-256 Idempotent Active",
                    "crawler_snapshot": CRAWLER_JOB.get_snapshot(),
                    "data": all_stocks
                }
                json_bytes = json.dumps(export_pack, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="stock_data_export_{date_str}.json"')
                self.send_header("Content-Length", str(len(json_bytes)))
                self.end_headers()
                self.wfile.write(json_bytes)
                return

        # 3.2 全市场宏观仪表盘聚合数据端点 (支持 ?start_date=...&end_date=... 查询)
        if url_path == "/api/dashboard/overview":
            query_params = {}
            if "?" in self.path:
                q_str = self.path.split("?", 1)[1]
                for part in q_str.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        query_params[k.strip()] = v.strip()

            s_date = query_params.get("start_date")
            e_date = query_params.get("end_date")

            all_stocks = list(DATA_MANAGER.stocks_dict.values())
            dashboard_data = compute_market_overview(all_stocks, start_date=s_date, end_date=e_date)
            self._send_json(200, {
                "code": 200,
                "version": APP_VERSION,
                "data": dashboard_data
            })
            return

        # 3.3 全球外部宏观环境与国际大宗情报端点 (支持 ?start_date=...&end_date=...)
        if url_path == "/api/macro/world":
            query_params = {}
            if "?" in self.path:
                q_str = self.path.split("?", 1)[1]
                for part in q_str.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        query_params[k.strip()] = v.strip()

            s_date = query_params.get("start_date")
            e_date = query_params.get("end_date")

            from scripts.world_macro_engine import WorldMacroEngine
            world_data = WorldMacroEngine.get_world_macro_intelligence(start_date=s_date, end_date=e_date)
            self._send_json(200, {
                "code": 200,
                "version": APP_VERSION,
                "data": world_data
            })
            return

        # 3.6 交易日历判定端点 /api/calendar/check?date=YYYY-MM-DD
        if url_path == "/api/calendar/check":
            query_params = {}
            if "?" in self.path:
                q_str = self.path.split("?", 1)[1]
                for part in q_str.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        query_params[k.strip()] = v.strip()
            date_param = query_params.get("date", datetime.now().strftime("%Y-%m-%d"))
            from scripts.trading_calendar import TradingCalendar
            cal_data = TradingCalendar.check_date_trading_status(date_param)
            self._send_json(200, {
                "code": 200,
                "data": cal_data
            })
            return

        # 3.7 多颗粒度财务报表端点 /api/stock/<code/finance?period=annual|report|quarter
        if url_path.startswith("/api/stock/") and url_path.endswith("/finance"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            query_params = {}
            if "?" in self.path:
                q_str = self.path.split("?", 1)[1]
                for part in q_str.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        query_params[k.strip()] = v.strip()
            period_type = query_params.get("period", "annual")
            stock_info = DATA_MANAGER.get_stock_detail(symbol) or {}
            curr_p = float(stock_info.get("price") or 0.0)
            m_cap = float(stock_info.get("market_cap") or 0.0)
            pe_val = float(stock_info.get("pe") or 0.0)

            from scripts.company_finance_engine import fetch_financial_statements
            fin_data = fetch_financial_statements(symbol, price=curr_p, market_cap=m_cap, pe=pe_val, period_type=period_type)
            self._send_json(200, {
                "code": 200,
                "symbol": symbol,
                "data": fin_data
            })
            return

        # 3.4 单只股票大宗交易官方穿透端点 /api/stock/<code/block
        if url_path.startswith("/api/stock/") and url_path.endswith("/block"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            stock_info = DATA_MANAGER.get_stock_detail(symbol) or {}
            curr_p = float(stock_info.get("price") or 0.0)
            from scripts.official_block_trade_engine import OfficialBlockTradeEngine
            trades = OfficialBlockTradeEngine.get_stock_block_trades(symbol, curr_p)
            self._send_json(200, {
                "code": 200,
                "symbol": symbol,
                "data": trades
            })
            return

        # 3.5 单只股票官方公告与大事提醒端点 /api/stock/<code/events
        if url_path.startswith("/api/stock/") and url_path.endswith("/events"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            stock_info = DATA_MANAGER.get_stock_detail(symbol) or {}
            stk_name = str(stock_info.get("name") or "")
            from scripts.stock_events_engine import StockEventsEngine
            events_data = StockEventsEngine.get_stock_events_and_notices(symbol, stk_name)
            self._send_json(200, {
                "code": 200,
                "symbol": symbol,
                "data": events_data
            })
            return

        # 3.8 需求2: 单只股票十大流通股东深度穿透端点 /api/stock/<code/shareholders
        if url_path.startswith("/api/stock/") and url_path.endswith("/shareholders"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            stock_info = DATA_MANAGER.get_stock_detail(symbol) or {}
            stk_name = str(stock_info.get("name") or "")
            t10_circ = float(stock_info.get("top10_circ_hold_pct") or 0.0)
            rep_date = str(stock_info.get("report_date") or "2024-06-30")
            from scripts.shareholder_engine import Top10ShareholdersEngine
            holders_data = Top10ShareholdersEngine.get_stock_top10_shareholders(
                symbol, name=stk_name, top10_circ_pct=t10_circ, report_date=rep_date
            )
            self._send_json(200, {
                "code": 200,
                "symbol": symbol,
                "data": holders_data
            })
            return

        # 4. 服务端状态端点 (常显心跳检查)
        if url_path == "/api/status":
            with SERVER_STATE_LOCK:
                curr_state = SERVER_STATE

            uptime = int(time.time() - SERVER_START_TIME)
            data = {
                "status": curr_state,
                "service": "DSH Stock Web Server",
                "version": APP_VERSION,
                "pid": os.getpid(),
                "port": self.server.server_port,
                "uptime_seconds": uptime,
                "stock_count": len(DATA_MANAGER.stocks_dict),
                "csi50_count": len(DATA_MANAGER.csi50_set),
                "csi100_count": len(DATA_MANAGER.csi100_set),
                "db_path": DB_FILE,
                "snapshot_date": datetime.now().strftime("%Y-%m-%d"),
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._send_json(200, data)
            return

        # 5. 动态配置元数据 Schema
        if url_path == "/api/filter_schema":
            schema = {
                "version": APP_VERSION,
                "dimensions": [
                    {"id": "market", "name": "股市分类", "type": "select", "options": [{"value": "all", "label": "全部 A 股"}, {"value": "sh", "label": "上证"}, {"value": "sz", "label": "深圳"}]},
                    {"id": "board", "name": "板块分类", "type": "select", "options": [{"value": "all", "label": "全部板块"}, {"value": "main", "label": "主板"}, {"value": "chinext", "label": "创业板"}]},
                    {"id": "constituent", "name": "成分股", "type": "select", "options": [{"value": "all", "label": "全部(不限)"}, {"value": "csi50", "label": "中证50"}, {"value": "csi100", "label": "中证100"}]},
                    {"id": "price", "name": "股价区间", "type": "range", "unit": "元"},
                    {"id": "market_cap", "name": "总市值区间", "type": "range", "unit": "亿元"},
                    {"id": "circ_cap", "name": "流通市值区间", "type": "range", "unit": "亿元"},
                    {"id": "pe", "name": "市盈率 PE", "type": "range", "unit": "倍"},
                    {"id": "dividend_count", "name": "分红次数", "type": "range", "unit": "次"},
                    {"id": "dividend_total_amount", "name": "累计分红总额", "type": "range", "unit": "亿元"},
                    {"id": "listing_years", "name": "上市时长", "type": "range", "unit": "年"},
                    {"id": "top10_circ", "name": "十大流通股东持股", "type": "range", "unit": "%"},
                    {"id": "top10_hold", "name": "十大股东持股", "type": "range", "unit": "%"},
                    {"id": "filter_date", "name": "筛选基准日期", "type": "date"}
                ]
            }
            self._send_json(200, schema)
            return

        # 6. 单只股票详情
        if url_path.startswith("/api/stock/"):
            symbol = url_path.replace("/api/stock/", "").strip()
            detail = DATA_MANAGER.get_stock_detail(symbol)
            if detail:
                self._send_json(200, {"code": 200, "data": detail})
            else:
                self._send_json(404, {"code": 404, "message": f"未找到股票 {symbol}"})
            return

        self.send_error(404, "Endpoint Not Found")

    def do_POST(self):
        url_path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        try:
            params = json.loads(body) if body else {}
        except Exception:
            params = {}

        # 1. 股票联合筛选 API (支持离线数据库读写)
        if url_path == "/api/filter":
            filtered_stocks, stats = DATA_MANAGER.filter_stocks(params)
            self._send_json(200, {
                "code": 200,
                "message": "success",
                "version": load_version_info().get("version", "v3.0.0"),
                "stats": stats,
                "filter_params": params,
                "data": filtered_stocks
            })
            return

        # 2. 前端暂停/关闭服务端 API (/api/server/shutdown)
        if url_path == "/api/server/shutdown":
            global SERVER_STATE
            with SERVER_STATE_LOCK:
                SERVER_STATE = "stopped"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 前端发起暂停指令，业务爬虫引擎已休眠 (状态: stopped)")
            self._send_json(200, {
                "code": 200,
                "status": "stopped",
                "message": "服务端业务已成功暂停，可在前端随时点击「启动服务」恢复。"
            })
            return

        # 3. 前端重新启动服务端 API (/api/server/start)
        if url_path == "/api/server/start":
            with SERVER_STATE_LOCK:
                SERVER_STATE = "running"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 前端发起启动指令，业务爬虫引擎已全面唤醒运行 (状态: running)")
            # 立即触发核心资产刷新
            threading.Thread(target=lambda: DATA_MANAGER.fetch_quotes_batch(list(DATA_MANAGER.csi50_set)), daemon=True).start()
            self._send_json(200, {
                "code": 200,
                "status": "running",
                "message": "服务端已成功启动并恢复实时更新。"
            })
            return

        # 4. 独立爬虫控制 API: 查询爬虫当前状态与进度 (/api/crawler/status)
        if url_path == "/api/crawler/status":
            snap = CRAWLER_JOB.get_snapshot()
            self._send_json(200, snap)
            return

        # 5. 独立爬虫控制 API: 触发手动抓取 (/api/crawler/start)
        if url_path == "/api/crawler/start":
            mode = params.get("mode", "full")  # "full" | "core"
            success, msg = CRAWLER_JOB.start_crawl(
                mode=mode,
                stock_dict=DATA_MANAGER.stocks_dict,
                csi100_set=DATA_MANAGER.csi100_set
            )
            self._send_json(200, {
                "code": 200 if success else 400,
                "success": success,
                "message": msg,
                "snapshot": CRAWLER_JOB.get_snapshot()
            })
            return

        # 6. 独立爬虫控制 API: 取消手动抓取 (/api/crawler/cancel)
        if url_path == "/api/crawler/cancel":
            CRAWLER_JOB.cancel()
            self._send_json(200, {
                "code": 200,
                "message": "已发送取消指令",
                "snapshot": CRAWLER_JOB.get_snapshot()
            })
            return

        # 7. 彻底注销进程 API (/api/server/kill)
        if url_path == "/api/server/kill":
            self._send_json(200, {
                "code": 200,
                "message": "正在执行彻底终止进程与端口释放..."
            })
            def trigger_kill():
                time.sleep(0.5)
                cleanup_and_exit()
            threading.Thread(target=trigger_kill, daemon=True).start()
            return

        self.send_error(404, "Endpoint Not Found")

    def _send_json(self, status: int, data: Dict[str, Any]):
        response = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def write_pid_file():
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        sys.stderr.write(f"写入 PID 失败: {e}\n")


def cleanup_pid_file():
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except Exception:
            pass


def cleanup_and_exit(signum=None, frame=None):
    global SHUTDOWN_REQUESTED
    if SHUTDOWN_REQUESTED:
        return
    SHUTDOWN_REQUESTED = True
    print(f"\n[DSH Web Server] 正在执行彻底退出与端口释放 (PID: {os.getpid()})...")
    cleanup_pid_file()
    if SERVER_INSTANCE:
        try:
            SERVER_INSTANCE.server_close()
        except Exception:
            pass
    print("[DSH Web Server] 进程已完全退出，端口已安全释放。")
    sys.exit(0)


def start_workspace_watchdog():
    def watchdog_loop():
        while not SHUTDOWN_REQUESTED:
            time.sleep(3)
            if not os.path.exists(BASE_DIR) or not os.path.exists(CURRENT_DIR):
                print("[Watchdog] 检测到工程应用目录已被移除，触发自动自毁关闭服务...")
                cleanup_and_exit()
                break
    t = threading.Thread(target=watchdog_loop, daemon=True)
    t.start()


def run_server(host: str = "0.0.0.0", port: int = 8888):
    global SERVER_INSTANCE

    signal.signal(signal.SIGINT, cleanup_and_exit)
    signal.signal(signal.SIGTERM, cleanup_and_exit)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, cleanup_and_exit)
    atexit.register(cleanup_pid_file)

    write_pid_file()
    start_workspace_watchdog()

    print(f"[DSH Web Server] 正在启动 A 股全市场量化中枢 ({APP_VERSION})...")
    print(f"[DSH Web Server] 本地 SQLite 库已连接: {DB_FILE} ｜ 已沉淀标的: {len(DATA_MANAGER.stocks_dict)} 只")

    try:
        server_address = (host, port)
        SERVER_INSTANCE = ThreadingHTTPServer(server_address, StockRequestHandler)
        print(f"===============================================================")
        print(f" 🚀 DSH A股量化筛选 Web 服务端已成功就绪！版本: {APP_VERSION}")
        print(f" 📍 本地访问地址: http://127.0.0.1:{port}")
        print(f" 🟢 进程 PID    : {os.getpid()} (已写入 {PID_FILE})")
        print(f" 📡 状态常显端点: http://127.0.0.1:{port}/api/status")
        print(f" 🎛️ 双向启停端点: /api/server/start ｜ /api/server/shutdown")
        print(f"===============================================================")
        SERVER_INSTANCE.serve_forever()
    except OSError as e:
        print(f"❌ 启动失败: 端口 {port} 可能已被占用 ({e})")
        cleanup_pid_file()
        sys.exit(1)
    except Exception as e:
        print(f"❌ 服务异常退出: {e}")
        cleanup_pid_file()
        sys.exit(1)


def get_server_status(port: int = 8888) -> bool:
    try:
        url = f"http://127.0.0.1:{port}/api/status"
        req = urllib.request.Request(url, headers={"User-Agent": "DSH-Status-Checker"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") in ("running", "stopped"):
                return True
    except Exception:
        pass
    return False


def stop_server_by_pid(port: int = 8888):
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            print(f"[DSH Web Server] 发现运行中的服务端进程 (PID: {pid})，正在发送终止信号...")
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            cleanup_pid_file()
            print("[DSH Web Server] 服务端已成功停止。")
            return
        except Exception as e:
            print(f"[DSH Web Server] 停止失败: {e}")

    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/server/kill", data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            print("[DSH Web Server] 已通过 API 发送安全退出指令。")
            time.sleep(0.8)
    except Exception:
        print("[DSH Web Server] 服务端当前未运行或无法连接。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DSH A股量化筛选与持久化服务端")
    parser.add_argument("--port", type=int, default=8888, help="HTTP 监听端口 (默认: 8888)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听主机 (默认: 0.0.0.0)")
    parser.add_argument("--status", action="store_true", help="查询服务端运行状态")
    parser.add_argument("--stop", action="store_true", help="安全停止服务端")
    args = parser.parse_args()

    if args.status:
        is_online = get_server_status(args.port)
        if is_online:
            print(f"🟢 [ONLINE] 服务端正在运行中 (端口: {args.port})")
            sys.exit(0)
        else:
            print(f"🔴 [OFFLINE] 服务端未运行 (端口: {args.port})")
            sys.exit(1)
    elif args.stop:
        stop_server_by_pid(args.port)
    else:
        run_server(host=args.host, port=args.port)
