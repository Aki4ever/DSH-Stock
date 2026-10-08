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
from urllib.parse import parse_qs, urlsplit
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
def _default_pid_file() -> str:
    """
    PID 文件按端口区分。默认端口 8888 沿用 .server.pid（保持既有运维习惯与向后兼容），
    其他端口使用 .server-<port>.pid —— 避免同机多实例（多账户/多底册）互相覆盖 PID 文件，
    进而让 stop_server.sh / watchdog 停错或误判进程。
    """
    port = str(os.environ.get("DSH_STOCK_PORT") or "8888")
    name = ".server.pid" if port == "8888" else f".server-{port}.pid"
    return os.path.join(BASE_DIR, name)


PID_FILE = os.environ.get("DSH_PID_FILE") or _default_pid_file()
VERSION_FILE = os.path.join(CONFIG_DIR, "version.json")
CONSTITUENTS_FILE = os.path.join(CONFIG_DIR, "constituents.json")
DB_FILE = os.environ.get("DSH_STOCK_DB", os.path.join(DATA_DIR, "stock_database.db"))

# 需求REQ-118: 股票列表默认每页 15 条（超出由分页控件翻页）；显式传 `page_size` 时以调用方为准
LIST_PAGE_SIZE = 15

# 需求REQ-120: 列表「全量排序」白名单（与 `web/index.html` 里带 `onclick="handleHeaderSort(...)"`
# 的 `data-col` **逐字同名**，避免前后端两套口径）。
# 为什么要白名单 + 显式报错：REQ-117 的教训是「参数已声明、实现里没登记」→ 传参被静默忽略，
# 页面看起来在排序其实没排。这里非法字段一律 400，绝不静默。
SORTABLE_TEXT_FIELDS = (
    "raw_code", "name", "industry", "ipo_date", "report_date", "holder_num_date",
)
# 需求REQ-121~124: 新增四列同样可排序（值为亿元；缺失=「未获取」，排序时恒末位）
SORTABLE_NUMERIC_FIELDS = (
    "price", "change_pct", "market_cap", "circulating_cap", "pe", "industry_pe_score",
    "dividend_count", "dividend_total_amount", "div_to_cap_pct", "listing_years", "div_freq",
    "goodwill", "goodwill_to_cap_pct", "top10_circ_hold_pct", "top3_hold_pct",
    "holder_individual_pct", "holder_institution_pct",
    "holder_new_count", "holder_change_count", "holder_exit_count",
    "top10_hold_pct", "holder_num_latest", "holder_num_prev", "holder_num_change",
    "ar_current", "ar_prev", "inventory_current", "inventory_prev",
)
LIST_SORT_FIELDS = SORTABLE_TEXT_FIELDS + SORTABLE_NUMERIC_FIELDS


def _sort_value(stock, field, numeric):
    """取排序值；缺失（None/空串/无法转数）一律返回 None → 由调用方排到末位。"""
    value = stock.get(field)
    if value is None or value == "":
        return None
    if numeric:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return str(value)


def sort_matched_rows(rows, sort_by, sort_dir):
    """需求REQ-120: 对**全量命中集**排序（服务端在分页切片之前调用）。

    规则（唯一口径，前端不再本地排序）：
      · 缺失值（未获取/None/空）**恒排末位**——升序降序都一样，避免「未获取」霸屏；
      · 同值以 `code` 升序 tie-break ⇒ 分页边界确定，翻页不重不漏；
      · `sort_dir='desc'` 只影响有值项的相对顺序。
    """
    numeric = sort_by in SORTABLE_NUMERIC_FIELDS
    present, missing = [], []
    for stock in rows:
        (present if _sort_value(stock, sort_by, numeric) is not None else missing).append(stock)
    present.sort(key=lambda s: str(s.get("code") or ""))
    present.sort(key=lambda s: _sort_value(s, sort_by, numeric), reverse=(sort_dir == "desc"))
    missing.sort(key=lambda s: str(s.get("code") or ""))
    return present + missing

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 需求REQ-102/103: 压力线连续天数筛选（算法唯一权威源在 pressure_line，取数/缓存/扫描在 pressure_scan）
from scripts import pressure_scan
from scripts.pressure_line import (
    PRESSURE_WINDOW,
    PRESSURE_MIN_WINDOW,
    PRESSURE_MAX_WINDOW,
    parse_streak_days,
)

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
    load_all_stocks_from_db,
    load_industry_summary,
    save_daily_klines,
    load_daily_klines,
    save_stock_timeline,
    load_stock_timeline,
    # 需求REQ-117: 底册基本面来源白名单（覆盖度统计对外展示同一口径）
    VERIFIED_FUNDAMENTAL_SOURCES,
)
from scripts.stock_data_engine import (
    StockQuote,
    KLineBar,
    normalize_code,
)
from scripts.stock_indicators import evaluate_stock
from scripts.stock_chart_svg import generate_stock_svg
from scripts.manual_crawler import CRAWLER_JOB
from scripts.real_chart_engine import fetch_real_daily_kline, fetch_real_timeline, fetch_real_timeline_history
from scripts.history_service import get_daily_history
from scripts.shareholder_actions import get_actions, enrich_actions
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
APP_VERSION = VERSION_INFO.get("version", "v1.2.0")   # 仅作进程启动日志的初始值

# 需求REQ-054: config/version.json 是**唯一版本权威**，且必须在运行期即时生效。
# 历史缺陷（BUG-006）：版本在模块导入时被读进内存，发布新版本后运行中的服务端仍返回旧版本，
# 导致「页面徽标/标题 = 旧版本」而「config/version.json = 新版本」的不一致状态，直到手工重启才恢复。
# 现改为按文件 mtime+size 做失效判断：文件一改，下一个请求即返回新版本，无需重启。
_VERSION_CACHE: Dict[str, Any] = {"stamp": None, "info": VERSION_INFO}


def current_version_info() -> Dict[str, Any]:
    """返回**当前**版本信息；文件被改动后立即生效（mtime+size 作为失效判据）。"""
    try:
        stat = os.stat(VERSION_FILE)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return _VERSION_CACHE["info"]
    if _VERSION_CACHE["stamp"] != stamp:
        _VERSION_CACHE["info"] = load_version_info()
        _VERSION_CACHE["stamp"] = stamp
    return _VERSION_CACHE["info"]


def current_version() -> str:
    return current_version_info().get("version", APP_VERSION)

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
        if os.environ.get("DSH_DISABLE_BACKGROUND") != "1":
            self._start_background_worker()

    def _init_database_and_load(self):
        """初始化 SQLite 并加载全量标的底册"""
        init_db()
        # 加载成分股
        if os.path.exists(CONSTITUENTS_FILE):
            try:
                with open(CONSTITUENTS_FILE, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                    if cdata.get("verified_source") and cdata.get("as_of"):
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
                    uninit = [k for k in all_keys if not self.stocks_dict[k].get("price")][:120]
                    if uninit:
                        self.fetch_quotes_batch(uninit)
                except Exception:
                    pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def fetch_quotes_batch(self, codes):
        from scripts.verified_quotes import fetch_quotes
        for row in fetch_quotes(codes):
            with self._lock:
                if row['code'] in self.stocks_dict:
                    self.stocks_dict[row['code']].update(row)

    def get_stock_detail(self, code: str, refresh: bool = False, shareholder_days: int = 365) -> Optional[Dict[str, Any]]:
        """
        需求2/3/4: 获取个股完整详情
        原则:
        1. 优先从本地数据库读取数据 (Local-DB-First)；
        2. 当本地数据库查不到或核心时序数据为空时，数据中心自动触发按需抓取流程，并持久化入库落盘；
        3. 轻便、低耦合、零现场盲目拉取。
        """
        norm, _ = normalize_code(code)

        with self._lock:
            stock = self.stocks_dict.get(norm)

        # 1. 本地股票底册检查与按需补全
        if not stock:
            # 本地内存与底册无此标的，触发按需单股抓取补全
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 本地数据库未命中标的 {norm}，数据中心启动按需抓取入库流程...")
            self.fetch_quotes_batch([norm])
            with self._lock:
                stock = self.stocks_dict.get(norm)

        if not stock:
            return None

        # 需求REQ-107: 五路取数**并行**（原先串行 ≈770ms），且各自带分级 TTL 缓存。
        # 日K改走 kline_store 关系库快路径（读优先 / 单页有界首屏 / 增量刷新），
        # 消灭「已缓存标的每 5 分钟重复 13 页全量回溯 ≈2.0s」这一主因。
        from scripts.detail_fastpath import gather_detail_inputs
        history, timeline_data, company_profile, financial_reports, enrich_error = \
            gather_detail_inputs(norm, stock, refresh=refresh)
        if enrich_error:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {norm} 股东指标 enrich 降级：{enrich_error}")

        daily_bars = history["bars"]
        # 为每根日K线补全换手率 (turnover_rate, 单位 %)
        circ_cap_val = float(stock.get("circulating_cap") or 0.0)
        price_val = float(stock.get("price") or 0.0)
        circ_shares = (circ_cap_val * 100000000.0 / price_val) if (circ_cap_val > 0 and price_val > 0) else 0.0
        latest_turnover_rate = float(stock.get("turnover_rate") or 0.0)
        if daily_bars:
            for idx, b in enumerate(daily_bars):
                if b.get("turnover_rate") is None or b.get("turnover_rate") == 0.0:
                    if idx == len(daily_bars) - 1 and latest_turnover_rate > 0:
                        b["turnover_rate"] = latest_turnover_rate
                    elif circ_shares > 0:
                        b["turnover_rate"] = round((float(b.get("volume") or 0.0) * 100.0 / circ_shares) * 100.0, 2)
                    else:
                        b["turnover_rate"] = 0.0

        # 技术面指标与评分必须基于真实历史K线数据，严禁生成任何mock假数据
        real_bars_objs = []
        if daily_bars:
            for b in daily_bars[-60:]:
                real_bars_objs.append(KLineBar(
                    date=b["date"],
                    open_p=b["open"],
                    close_p=b["close"],
                    high_p=b["high"],
                    low_p=b["low"],
                    volume=b["volume"],
                    turnover=b["amount_yi"] * 100000000.0 if b.get("amount_yi") is not None else None
                ))
        eval_report = evaluate_stock(norm, stock["name"], real_bars_objs) if real_bars_objs else None
        svg_chart = ""

        detail = dict(stock)
        detail["evaluation"] = eval_report.to_dict() if eval_report else None
        detail["svg_chart"] = svg_chart
        detail["daily_bars"] = daily_bars
        from scripts.chanlun_analysis import analyze_bars
        detail["chanlun"] = analyze_bars(daily_bars, code=norm)
        detail["history_meta"] = {k: v for k, v in history.items() if k != "bars"}
        detail["timeline_data"] = timeline_data
        detail["company_profile"] = company_profile
        detail["financial_reports"] = financial_reports
        enrich_actions(detail, get_actions(shareholder_days))
        return detail

    def filter_stocks(self, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """多条件联合筛选（AND 严格逻辑）"""
        market = params.get("market", "all")
        board = params.get("board", "all")
        constituent = params.get("constituent", "all")
        st_filter = params.get("st", "all") # 需求4: "all" | "st" | "non_st"
        filter_date = params.get("filter_date", "")
        # 需求REQ-111: 行业筛选（与仪表盘 REQ-110 同源同口径：stocks_master.industry 一级行业精确等值）
        industry_filter = str(params.get("industry", "all") or "all").strip() or "all"
        shareholder_action = params.get("shareholder_action", "all")
        if shareholder_action not in ("all", "increase", "decrease", "both"):
            raise ValueError("股东行为仅支持全部、增持、减持、同时增减持")
        action_snapshot = get_actions(int(params.get("shareholder_days", 365)))

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
        # 需求REQ-113: 前3大股东合计持股区间 (%，闭区间；两端留空 = 不限制)
        f_min_top3 = to_float(params.get("min_top3"))
        f_max_top3 = to_float(params.get("max_top3"))
        if f_min_top3 is not None and f_max_top3 is not None and f_min_top3 > f_max_top3:
            raise ValueError("前3大股东合计持股：下限不能大于上限")
        # 需求1/2: 日交易额与日均交易额区间 (亿元)
        f_min_daily_amount = to_float(params.get("min_daily_amount"))
        f_max_daily_amount = to_float(params.get("max_daily_amount"))
        f_min_avg_daily_amount = to_float(params.get("min_avg_daily_amount"))
        f_max_avg_daily_amount = to_float(params.get("max_avg_daily_amount"))
        # 需求2: 上市时长区间 (年)
        f_min_listing_years = to_float(params.get("min_listing_years"))
        f_max_listing_years = to_float(params.get("max_listing_years"))
        # 需求REQ-117: 分红次数 / 累计分红总额区间。
        # 这两个维度**早已在 /api/filter_schema 里声明**（type=range），但 bounds 里从未登记 →
        # 传参被静默忽略（声明与实现不一致的"死维度"）。本批随真实值放行一并补齐。
        f_min_dividend_count = to_float(params.get("min_dividend_count"))
        f_max_dividend_count = to_float(params.get("max_dividend_count"))
        f_min_dividend_total = to_float(params.get("min_dividend_total_amount"))
        f_max_dividend_total = to_float(params.get("max_dividend_total_amount"))
        # 需求2: 个人占比与机构占比筛选区间
        f_min_individual = to_float(params.get("min_individual_pct"))
        f_max_individual = to_float(params.get("max_individual_pct"))
        f_min_institution = to_float(params.get("min_institution_pct"))
        f_max_institution = to_float(params.get("max_institution_pct"))
        # 需求5: 盈利时长单选 (all / 1 / 2 / 3)
        profit_years = params.get("profit_years")
        # 需求REQ-102/103: 压力线连续天数（连续跌破 / 连续冲高）；None = 不参与筛选
        breakdown_days = parse_streak_days(params.get("breakdown_days"), "连续跌破天数")
        breakout_days = parse_streak_days(params.get("breakout_days"), "连续冲高天数")
        pressure_enabled = breakdown_days is not None or breakout_days is not None
        keyword = str(params.get("keyword", "")).strip().lower()

        page = int(params.get("page", 1))
        # 需求REQ-118: 列表默认每页 15 条（显式传参仍生效，保留 CLI/导出能力，不做硬钳制）
        page_size = int(params.get("page_size", LIST_PAGE_SIZE))
        if page_size <= 0:
            raise ValueError("每页条数必须为正整数")
        if page <= 0:
            raise ValueError("页码必须为正整数")
        # 需求REQ-120: 全量排序参数（白名单 + 非法值显式报错，绝不静默忽略）
        sort_by = str(params.get("sort_by") or "").strip()
        sort_dir = str(params.get("sort_dir") or "desc").strip().lower()
        if sort_by and sort_by not in LIST_SORT_FIELDS:
            raise ValueError(f"不支持的排序字段：{sort_by}")
        if sort_by and sort_dir not in ("asc", "desc"):
            raise ValueError("排序方向仅支持 asc / desc")

        with self._lock:
            candidates = list(self.stocks_dict.values())

        # 需求REQ-112: 行业 PE 分位（1~100）。分母恒为「该股所属行业的全行业样本」——
        # 必须用**全市场**候选计算：先筛后算会让同一只股票在不同筛选条件下分值漂移（缺陷）。
        from scripts.industry_pe_rank import compute_industry_pe_scores
        industry_pe_scores = compute_industry_pe_scores(candidates)
        for s in candidates:
            info = industry_pe_scores.get(s["code"])
            s["industry_pe_score"] = info["score"] if info else None
            s["industry_pe_rank"] = info["rank"] if info else None
            s["industry_pe_sample_size"] = info["sample_size"] if info else None
            s["industry_pe_peers_cheaper"] = info.get("peers_cheaper") if info else None
            s["industry_pe_industry"] = info["industry"] if info else None

        # 阶段 1：静态快速过滤
        filtered_candidates = []
        for s in candidates:
            if market and market != "all" and s["market_code"] != market:
                continue
            if board and board != "all" and s["board_code"] != board:
                continue
            # 需求REQ-111: 行业筛选（与仪表盘 REQ-110 同一比较口径：一级行业精确等值；
            # 行业为「未采集」的标的永不命中任何具体行业）
            if industry_filter != "all" and (s.get("industry") or "未采集") != industry_filter:
                continue
            if constituent == "csi50" and not s["is_csi50"]:
                continue
            elif constituent == "csi100" and not s["is_csi100"]:
                continue
            # 需求4: 股票列表 ST 维度过滤 (ST / 非ST / 全部)
            if st_filter == "st":
                is_st = ("ST" in s["name"].upper())
                if not is_st:
                    continue
            elif st_filter == "non_st":
                is_st = ("ST" in s["name"].upper())
                if is_st:
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

        # 需求REQ-102/103: 压力线连续天数判定集合 = 阶段1静态过滤后的候选；
        # 只读「当天」缓存（未测算与无法测算必须分开统计，且都不参与命中判定）。
        pressure_rows: Dict[str, Dict[str, Any]] = {}
        if pressure_enabled:
            pressure_rows = pressure_scan.fresh_rows([c["code"] for c in filtered_candidates],
                                                      window=PRESSURE_WINDOW)

        # 阶段 2：检查行情，若处于 running 状态且有未拉取行情的标的则快速补充
        with SERVER_STATE_LOCK:
            current_state = SERVER_STATE
        if current_state == "running":
            unquoted = [c["code"] for c in filtered_candidates if not c.get("price")][:60]
            if unquoted:
                self.fetch_quotes_batch(unquoted)

        # 阶段 3：多维数值严格联合判定 (AND)
        matched = []
        pressure_hits = 0
        for s in filtered_candidates:
            # 需求REQ-102/103: 压力线连续天数（只读缓存；未测算/无法测算一律不命中，绝不凑数）
            if pressure_enabled:
                prow = pressure_rows.get(s["code"])
                if not prow or prow.get("status") != "available":
                    continue
                if breakdown_days is not None and (prow.get("below_days") or 0) < breakdown_days:
                    continue
                if breakout_days is not None and (prow.get("above_days") or 0) < breakout_days:
                    continue
                pressure_hits += 1
            from scripts.shareholder_engine import Top10ShareholdersEngine
            Top10ShareholdersEngine.enrich_stock_holder_metrics(s)
            bounds = [('price',f_min_price,f_max_price),('market_cap',f_min_cap,f_max_cap),
                      ('circulating_cap',f_min_circ_cap,f_max_circ_cap),('pe',f_min_pe,f_max_pe),
                      ('top10_circ_hold_pct',f_min_top10_circ,f_max_top10_circ),('top10_hold_pct',f_min_top10,f_max_top10),
                      ('top3_hold_pct',f_min_top3,f_max_top3),
                      ('turnover_yi',f_min_daily_amount,f_max_daily_amount),('avg_daily_amount',f_min_avg_daily_amount,f_max_avg_daily_amount),
                      ('listing_years',f_min_listing_years,f_max_listing_years),('holder_individual_pct',f_min_individual,f_max_individual),
                      ('holder_institution_pct',f_min_institution,f_max_institution),
                      # 需求REQ-117: 补登记两个「已声明未生效」的分红维度（未核验= None → 有界时不命中）
                      ('dividend_count',f_min_dividend_count,f_max_dividend_count),
                      ('dividend_total_amount',f_min_dividend_total,f_max_dividend_total)]
            if any((lo is not None or hi is not None) and (s.get(key) is None or
                   (lo is not None and s[key]<lo) or (hi is not None and s[key]>hi)) for key,lo,hi in bounds):
                continue
            if profit_years and profit_years!='all' and (s.get('profit_years') is None or s['profit_years']<int(profit_years)):
                continue

            matched.append(dict(s))

        # 股东行为在全量候选中筛选，再统计和分页。
        if shareholder_action == "both":
            matched = [s for s in matched if any(
                row["direction"] == "increase"
                for row in action_snapshot["records"].get(s["code"], [])) and any(
                row["direction"] == "decrease"
                for row in action_snapshot["records"].get(s["code"], []))]
        elif shareholder_action != "all":
            matched = [s for s in matched if any(
                row["direction"] == shareholder_action
                for row in action_snapshot["records"].get(s["code"], []))]

        # 需求REQ-120: 把「原先只对当前页注入」的两处指标**上移到全量命中集**——
        # 旧实现只对 `paged_data` 注入 `增持/减持股东`（`enrich_actions`）与 `股东人数` 四列
        # （`attach_holder_counts`），于是这些列在服务端**只有当前页有值**，跨页排序必然错。
        # 两处都只是一次快照读 + 内存查表，**零新增触网**。
        for s in matched:
            enrich_actions(s, action_snapshot)
        holder_num_stats = self.attach_holder_counts(matched)

        # 需求REQ-120: 全量排序（缺失值恒末位 + code 升序 tie-break）；不传参时保持旧行为（市值降序）
        if sort_by:
            matched = sort_matched_rows(matched, sort_by, sort_dir)
        else:
            matched.sort(key=lambda x: x.get("market_cap") or -1, reverse=True)

        total_matched = len(matched)
        def aggregate(field, average=False):
            values=[s[field] for s in matched if s.get(field) is not None]
            return round(sum(values)/(len(values) if average else 1),2) if values else None
        avg_price = aggregate('price', True)
        avg_change = aggregate('change_pct', True)
        total_cap = aggregate('market_cap')
        total_circ_cap = aggregate('circulating_cap')

        # 需求REQ-017: 快照截取日期以「数据库基准」批次为准 (不再由请求参数或本地时钟推断)
        caliber = resolve_data_caliber()
        real_snapshot_date = caliber["snapshot_date"]
        if not real_snapshot_date:
            real_snapshot_date = filter_date or None

        stats = {
            "total_universe_count": len(candidates),
            "matched_count": total_matched,
            "avg_price": avg_price,
            "avg_change_pct": avg_change,
            "total_market_cap": total_cap,
            "total_circ_cap": total_circ_cap,
            "filter_date": real_snapshot_date,
            "snapshot_date": real_snapshot_date,
            "snapshot_source": caliber["snapshot_source"],
            "quote_date": caliber["quote_date"],
            "quote_datetime": caliber["quote_datetime"],
            "baseline": caliber["baseline"],
            "page": page,
            "page_size": page_size,
            "server_state": current_state
        }
        stats['coverage']={k:sum(s.get(k) is not None for s in matched) for k in ('price','change_pct','market_cap','circulating_cap')}
        stats['quote_dates']=sorted({str(s.get('timestamp') or '')[:8] for s in matched if s.get('timestamp')})
        stats['snapshot_note']='行情为当前已获取快照；日期口径以数据中心「数据库基准」批次为准，未提供历史全市场行情截面'

        # 需求REQ-111: 行业筛选口径与显式提示（未知/未采集行业 → 结果为空，绝不静默回退全市场）
        if industry_filter != "all":
            industry_universe = sum(1 for c in candidates if (c.get("industry") or "未采集") == industry_filter)
            stats["industry"] = {
                "industry": industry_filter,
                "universe_matched_stocks": industry_universe,
                "total_stocks": len(candidates),
                "note": None if industry_universe else f"行业「{industry_filter}」未采集或不存在，结果为空（不回退全市场）",
            }
        else:
            stats["industry"] = {"industry": "all", "universe_matched_stocks": len(candidates),
                                 "total_stocks": len(candidates), "note": None}

        # 需求REQ-112: 行业 PE 分值覆盖面（未采集必须显式对外，绝不填 0 冒充）
        stats["industry_pe"] = {
            "scored_count": sum(1 for c in candidates if c.get("industry_pe_score") is not None),
            "uncollected_count": sum(1 for c in candidates if c.get("industry_pe_score") is None),
            "total_stocks": len(candidates),
            "caliber": "同行业内 pe>0 样本的百分位：score = round(严格更低 PE 只数/(n-1)*99)+1；1=行业最低 PE（并列恒为 1），100=行业最高 PE（无并列时）；pe<=0/缺失=未采集",
        }

        # 需求REQ-113: 前3大股东覆盖面（口径：最新一期十大股东披露 rank1~3 合计；缺任一名=未采集）
        stats["top3_holders"] = {
            "available_count": sum(1 for s in matched if s.get("top3_hold_pct") is not None),
            "uncollected_count": sum(1 for s in matched if s.get("top3_hold_pct") is None),
            "matched_count": len(matched),
            "caliber": "最新一期十大股东披露 rank1~3 持股比例之和（%）；1~3 名不齐=未采集，不参与筛选",
        }

        stats["shareholder_actions"] = {k: v for k, v in action_snapshot.items() if k != "records"}

        # 需求REQ-102/103: 压力线筛选覆盖面与扫描状态（未测算/无法测算必须显式对外，禁止当「未命中」）
        if pressure_enabled:
            candidate_codes = [c["code"] for c in filtered_candidates]
            measured_codes, unmeasurable = [], 0
            base_dates = []
            for code in candidate_codes:
                row = pressure_rows.get(code)
                if not row:
                    continue
                if row.get("status") == "available":
                    measured_codes.append(code)
                    if row.get("base_date"):
                        base_dates.append(str(row["base_date"]))
                else:
                    unmeasurable += 1
            measured = len(measured_codes)
            # 需求REQ-104: 两个计数必须互斥 ——
            #   unmeasured  = 当天**没有任何行**（还没轮到它测算）
            #   unmeasurable = 当天**有行但不可用**（no_amount / insufficient_history / fetch_failed）
            # 旧实现用「候选 − measured」统计 unmeasured，导致有失败行的标的被双计（verifier D5）。
            unmeasured_codes = [c for c in candidate_codes if c not in pressure_rows]
            failed_codes = [c for c in candidate_codes
                            if (pressure_rows.get(c) or {}).get("status") not in (None, "available")]
            retry_codes = unmeasured_codes + failed_codes
            candidate_count = len(candidate_codes)
            scan = (pressure_scan.start_scan(retry_codes, window=PRESSURE_WINDOW)
                    if retry_codes else pressure_scan.scan_status())
            conflict = breakdown_days is not None and breakout_days is not None
            note = ("压力线＝图表「自动线 1 根」（日线 60 根 · 不复权 · 成交额缺来源时按均价×成交量估算）"
                    "· 比较价＝收盘价 · 连续天数取「≥ x 天」")
            if retry_codes:
                note += f" · 未测算/无法测算 {len(retry_codes)} 只未参与命中判定，扫描完成后自动刷新"
            if conflict:
                note = ("⚠️ 连续跌破与连续冲高互斥（同一天收盘不可能同时低于且高于同一根线），结果必然为空 · " + note)
            stats["pressure"] = {
                "window": PRESSURE_WINDOW,
                "breakdown_days": breakdown_days,
                "breakout_days": breakout_days,
                "candidate_count": candidate_count,
                "measured_count": measured,
                "unmeasured_count": len(unmeasured_codes),
                "unmeasurable_count": unmeasurable,
                "hit_count": pressure_hits,
                "coverage": round(measured / candidate_count, 6) if candidate_count else 0.0,
                "base_date_min": min(base_dates) if base_dates else None,
                "base_date_max": max(base_dates) if base_dates else None,
                "conflict": conflict,
                "note": note,
                "scan": scan,
            }
        else:
            stats["pressure"] = None

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_data = matched[start_idx:end_idx]

        # 需求REQ-120: 当前页**不再重复注入**——`enrich_stock_holder_metrics`（筛选阶段已对
        # 全部候选执行）、`enrich_actions`、`attach_holder_counts` 都已上移到排序前的全量命中集，
        # 否则会出现「服务端只有当前页有值」的双口径（也正是跨页排序失效的根因）。
        # 需求REQ-119: 列表四列「股东人数(最近一次)/(上一次)/日期(最近一次)/变化」
        # 需求REQ-120: 该统计口径由「当前页」改为**全量命中集**（覆盖率对外数字更大也更诚实）
        stats["holder_num"] = holder_num_stats
        # 需求REQ-120: 排序口径下发（前端据此显示指示器，便于核验「排的是全量还是当页」）
        stats["sort"] = {
            "sort_by": sort_by or "market_cap",
            "sort_dir": sort_dir if sort_by else "desc",
            "default": not bool(sort_by),
            "missing_last": True,
            "tie_break": "code ASC",
            "scope": "全量命中集（分页切片之前）",
            "allowed_fields": list(LIST_SORT_FIELDS),
        }
        # 需求REQ-117: 底册基本面放行覆盖度（如实对外，便于核验「不是没修、是真没采到」）
        stats["fundamentals"] = {
            "listing_verified": sum(1 for s in matched if s.get("ipo_date")),
            "dividend_count_verified": sum(1 for s in matched if s.get("dividend_count") is not None),
            "dividend_total_verified": sum(1 for s in matched if s.get("dividend_total_amount") is not None),
            "goodwill_verified": sum(1 for s in matched if s.get("goodwill") is not None),
            "matched_count": total_matched,
            "sources": list(VERIFIED_FUNDAMENTAL_SOURCES),
            "caliber": "仅放行带核验标记（*_verified_at 非空且来源白名单）的底册值；历史生成值（legacy_generated）不放行，显示「未获取」",
        }
        # 需求REQ-121~124: 应收/存货四列覆盖度与**未获取原因分类**（如实对外，不美化）
        ar_status = {}
        inventory_status = {}
        for s in matched:
            ar_status[s.get("ar_status") or "not_collected"] = ar_status.get(s.get("ar_status") or "not_collected", 0) + 1
            inventory_status[s.get("inventory_status") or "not_collected"] = \
                inventory_status.get(s.get("inventory_status") or "not_collected", 0) + 1
        stats["balance"] = {
            "ar_verified": sum(1 for s in matched if s.get("ar_current") is not None),
            "ar_prev_verified": sum(1 for s in matched if s.get("ar_prev") is not None),
            "inventory_verified": sum(1 for s in matched if s.get("inventory_current") is not None),
            "inventory_prev_verified": sum(1 for s in matched if s.get("inventory_prev") is not None),
            "ar_reasons": ar_status,
            "inventory_reasons": inventory_status,
            "matched_count": total_matched,
            "unit": "亿元",
            "caliber": "同花顺 F10 资产负债表「应收账款」「存货」（精确行名优先，退化为含票据的合并行时标注）；"
                       "当期＝该股最新报告期，上年＝上年同期（缺则回退上一年年报 12-31）；取不到给原因码，不补 0",
        }
        # 需求REQ-125: 三列（新进/变动/退出）口径、覆盖度与原因分类。
        # 刻意**只从 `matched` 行自身聚合**（不走缓存读取）：
        #   ① 统计口径与列表展示严格同源（同一批 `holder_*_status`）；
        #   ② 单测/离线夹具无需触碰产品库缓存即可判定（R19 夹具铁律「不读产品库」）。
        from scripts import shareholder_changes as change_mod
        exit_reasons = {}
        for s in matched:
            reason = s.get("holder_exit_status") or "pending"
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        stats["holder_changes"] = {
            "source": change_mod.CHANGE_SOURCE,
            "exit_source": change_mod.EXIT_SOURCE,
            "caliber": change_mod.CALIBER,
            "status_text": dict(change_mod.STATUS_TEXT),
            "matched_new_available": sum(1 for s in matched if s.get("holder_new_status") == "ok"),
            "matched_change_available": sum(1 for s in matched if s.get("holder_change_status") == "ok"),
            "matched_exit_available": sum(1 for s in matched if s.get("holder_exit_status") == "ok"),
            "exit_reasons": exit_reasons,
            "matched_count": total_matched,
        }
        return paged_data, stats

    @staticmethod
    def attach_holder_counts(rows):
        """需求REQ-119：为列表行注入股东人数四列（**一次**读全市场快照，绝不逐股请求）。

        口径与既有「股东人数」面板同源（`RPT_HOLDERNUMLATEST`）：
          · `holder_num_latest` = 快照 `HOLDER_NUM`（该标的**最新一期**，各标的期次不同）
          · `holder_num_prev`   = 快照 `PRE_HOLDER_NUM`（来源自带上一期）
          · `holder_num_date`   = 快照 `END_DATE`（最近一次的报告期，逐列给出，不做统一对齐）
          · `holder_num_change` = 最新 − 上一次；无上期（缺失或 ≤0）→ **None（前端渲染空单元格）**
        冷缓存（快照未采集）时四列一律 None，并如实下发 `status=unavailable`；**不触网**。
        """
        from scripts.data_sources.holdernum_market import get_market_holder_num
        try:
            market = get_market_holder_num(allow_fetch=False)
        except Exception as exc:
            market = {"status": "unavailable", "rows": [], "as_of": None, "error": str(exc)}

        index = {}
        for item in market.get("rows") or []:
            code = item.get("code")
            if code and code not in index:
                index[code] = item

        available = comparable = mismatch = 0
        for stock in rows:
            snapshot = index.get(stock.get("code")) or {}
            latest = snapshot.get("holder_num")
            prev = snapshot.get("prev_holder_num")
            change = None
            if latest is not None and prev is not None and prev > 0:
                change = latest - prev
                comparable += 1
                source_change = snapshot.get("change_num")
                if source_change is not None and abs(source_change - change) > 0.5:
                    mismatch += 1
            stock["holder_num_latest"] = latest
            stock["holder_num_prev"] = prev
            stock["holder_num_date"] = snapshot.get("end_date")
            stock["holder_num_change"] = change
            if latest is not None:
                available += 1

        return {
            "status": market.get("status"),
            "as_of": market.get("as_of"),
            "source": "东方财富股东户数数据中心 (RPT_HOLDERNUMLATEST)",
            "available_count": available,
            "missing_count": len(rows) - available,
            "comparable_count": comparable,
            "change_mismatch_count": mismatch,
            "snapshot_rows": len(index),
            "caliber": "快照最新一期（各标的期次不同，日期列给出各自期末日）；变化 = 最新 − 上一次；无上期或缺失 = 空（不补 0）",
        }


# 单例初始化
DATA_MANAGER = StockDataManager()
SERVER_START_TIME = time.time()
SERVER_INSTANCE = None
SHUTDOWN_REQUESTED = False


def build_intraday_chanlun(code: str, timeline_fetcher=None) -> Dict[str, Any]:
    """需求REQ-024: 分时级别缠论分析（唯一计算入口，端点与测试共用）。

    口径铁律:
    1. 分时点视为 1 根 K 线（开=收=高=低=该分钟成交价），级别明确为「分时级别」；
    2. 复用 scripts.chanlun_analysis.analyze_bars 同一套形态学/动力学算法，不另起一套；
    3. 来源未提供分时明细或缺少有效成交价时，返回 status=unavailable 并附原因，
       绝不以日线或任何推测数据冒充分时结构。

    需求REQ-107: 分时改走 `stock_timeline` 缓存（命中零外网），与详情页同源同缓存。
    `timeline_fetcher` 为**显式来源注入点**：一旦注入，则**绕过缓存**、直接采用该来源，
    以保证「分时口径」类用例可在不触网、不依赖产品库的状态下确定性复跑（R04 用例明文要求）。
    """
    from scripts.chanlun_analysis import analyze_bars
    from scripts.detail_fastpath import cached_timeline
    if timeline_fetcher is not None:
        timeline = cached_timeline(code, fetcher=timeline_fetcher, use_cache=False)
    else:
        # 生产路径：默认来源仍取模块级 `fetch_real_timeline`，保留既有 monkeypatch 接缝
        timeline = cached_timeline(code, fetcher=fetch_real_timeline)
    items = timeline.get("items") or []
    trade_date = str(timeline.get("date") or "").replace("-", "")
    if not items or not trade_date:
        return {
            "status": "unavailable",
            "level": "intraday",
            "error": timeline.get("error") or "来源未提供当日分时明细，无法生成分时级别缠论",
            "counts": {},
            "bars": [],
        }
    bars = []
    for item in items:
        price = item.get("price")
        if price is None or price <= 0:
            continue
        # analyze_bars 要求日期唯一且递增：分时用「交易日 + 分钟」保证字典序与时间序一致
        stamp = f"{trade_date[0:4]}-{trade_date[4:6]}-{trade_date[6:8]} {item.get('time')}"
        bars.append({"date": stamp, "open": price, "close": price,
                     "high": price, "low": price, "volume": item.get("volume") or 0})
    if not bars:
        return {
            "status": "unavailable",
            "level": "intraday",
            "error": "分时明细缺少有效成交价，无法生成分时级别缠论",
            "counts": {},
            "bars": [],
        }
    analysis = analyze_bars(bars, code=code)
    analysis["level"] = "intraday"
    analysis["level_note"] = "分时级别：笔＝分钟级笔，不等于日线级别，不可与日线信号混读"
    analysis["source"] = timeline.get("source")
    analysis["trade_date"] = trade_date
    return analysis


# ============================================================
# 需求REQ-028: 分钟K线（5/15/30 分钟）端点实现
# 口径: 每根K线 = 一个真实时间区间（开/收/高/低/量）；成交额一律由该K线均价×成交量推出并标记为估算。
# ============================================================

def build_minute_kline(code: str, interval: str, limit: int = 200) -> Dict[str, Any]:
    """需求REQ-028: 分钟K线数据（唯一取数入口，端点与测试共用）。"""
    from scripts.real_chart_engine import fetch_real_minute_kline, MINUTE_KLINE_INTERVALS
    interval = str(interval or "m5").lower().strip()
    if interval not in MINUTE_KLINE_INTERVALS:
        raise ValueError("不支持的分钟周期，仅支持 m1 / m5 / m15 / m30")
    result = fetch_real_minute_kline(code, interval, limit=limit)
    result["level"] = f"{MINUTE_KLINE_INTERVALS[interval]}minute"
    result["level_note"] = (f"{MINUTE_KLINE_INTERVALS[interval]} 分钟级别：每根K线为一个真实时间区间"
                            "（开/收/高/低/量），不等于日线级别，不可与日线信号混读")
    result["amount_note"] = ("来源未提供可互相印证的成交额字段，成交额由本K线均价 × 成交量推出并标记为估算"
                             "（amount_derived=true）；来源自带的第8字段与成交量/成交价无法印证，故不采信")
    return result


# ============================================================
# 需求REQ-041: 任意真实K线序列的缠论分析（周线 / 季线 / 5分K线）
# 背景: 周线与季线由前端用真实日K现场聚合（本项目对这两个颗粒度不落库），
#       5分K线为区间接口返回，三者都没有「日线历史」那样的后端缓存，
#       因此新增本纯计算入口，供前端把真实K线序列提交回来做缠论判定。
# 铁律:
#   1. 复用 scripts.chanlun_analysis.analyze_bars 同一套形态学/动力学算法，
#      买卖点仍由同一 build_buy_sell_points 严格按缠论定义产出，绝不另起一套、绝不放宽判定；
#   2. 只接受调用方提交的真实K线：价格缺失/非数值、日期重复或乱序一律拒绝（400），
#      绝不用日线结果或任何推测数据冒充该级别的结构；
#   3. 本入口只做计算，不写数据库、不落缓存（保持「零数据库写入」口径）。
# ============================================================

CHANLUN_BARS_MAX = 20000

CHANLUN_LEVEL_NOTES = {
    "weekly": "周线级别：每根K线＝1个自然周（由真实日K现场聚合），笔＝周线笔，不可与日线信号混读",
    "quarterly": "季线级别：每根K线＝1个自然季度（由真实日K现场聚合），笔＝季线笔，不可与日线信号混读",
    "m5": "5分级别：每根K线＝5分钟真实时间区间，笔＝5分钟笔，不可与日线信号混读",
}


def build_chanlun_from_bars(code: str, bars, level: str) -> Dict[str, Any]:
    """需求REQ-041: 由调用方提交的真实K线序列现场计算缠论（唯一计算入口，端点与测试共用）。"""
    level_key = str(level or "").strip().lower()
    if level_key not in CHANLUN_LEVEL_NOTES:
        raise ValueError("不支持的缠论级别，仅支持 weekly / quarterly / m5")
    if not isinstance(bars, list) or not bars:
        raise ValueError("未提交任何K线，无法进行缠论判定")
    if len(bars) > CHANLUN_BARS_MAX:
        raise ValueError(f"提交的K线根数({len(bars)})超过上限 {CHANLUN_BARS_MAX}")
    normalized = []
    for item in bars:
        if not isinstance(item, dict):
            raise ValueError("K线数据格式不正确，必须是对象数组")
        normalized.append({
            "date": item.get("date"),
            "open": item.get("open"),
            "close": item.get("close"),
            "high": item.get("high"),
            "low": item.get("low"),
            "volume": item.get("volume") or 0,
        })
    from scripts.chanlun_analysis import analyze_bars
    analysis = analyze_bars(normalized, code=code or "")
    analysis["level"] = level_key
    analysis["level_note"] = CHANLUN_LEVEL_NOTES[level_key]
    analysis["submitted_bars"] = len(normalized)
    return analysis


# ============================================================
# 需求REQ-019: 缠论雷达池全池扫描的后台任务状态
# 状态只记录真实进度与真实结果计数；失败项逐个保留原因，不做吞并。
# ============================================================
CHANLUN_RADAR_LOCK = threading.Lock()
CHANLUN_RADAR_STATE: Dict[str, Any] = {
    "status": "idle",          # idle | running | done | failed
    "total": 0,
    "done": 0,
    "current": "",
    "started_at": None,
    "finished_at": None,
    "signal_count": 0,
    "persisted_count": 0,
    "failures": [],
    "error": None,
}


def _chanlun_radar_worker(codes=None, refresh: bool = False):
    """后台执行全池扫描；逐只更新进度，异常逐条记录，不静默吞掉。"""
    from scripts.chanlun_signals import run_radar

    def progress(index, total, code):
        with CHANLUN_RADAR_LOCK:
            CHANLUN_RADAR_STATE["done"] = index - 1
            CHANLUN_RADAR_STATE["total"] = total
            CHANLUN_RADAR_STATE["current"] = code

    try:
        result = run_radar(codes, refresh=refresh, persist=True, progress=progress)
        with CHANLUN_RADAR_LOCK:
            CHANLUN_RADAR_STATE.update({
                "status": "done", "total": result["scanned_count"], "done": result["scanned_count"],
                "current": "", "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "signal_count": result["signal_count"], "persisted_count": result["persisted_count"],
                "failures": result["failures"], "error": None,
            })
    except Exception as exc:  # noqa: BLE001
        with CHANLUN_RADAR_LOCK:
            CHANLUN_RADAR_STATE.update({
                "status": "failed", "current": "",
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": f"雷达池扫描失败: {exc}",
            })


def start_chanlun_radar_scan(codes=None, refresh: bool = False) -> Tuple[bool, str]:
    """启动雷达池扫描；已有扫描在跑时拒绝重复启动，返回 (是否启动, 说明)。"""
    with CHANLUN_RADAR_LOCK:
        if CHANLUN_RADAR_STATE["status"] == "running":
            return False, f"雷达池扫描已在进行中（{CHANLUN_RADAR_STATE['done']}/{CHANLUN_RADAR_STATE['total']}）"
        CHANLUN_RADAR_STATE.update({
            "status": "running", "total": 0, "done": 0, "current": "",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "finished_at": None,
            "signal_count": 0, "persisted_count": 0, "failures": [], "error": None,
        })
    threading.Thread(target=_chanlun_radar_worker, args=(codes, refresh), daemon=True).start()
    return True, "雷达池扫描已启动"


# ============================================================
# 需求REQ-020: 策略选股与告警下发任务状态
# ============================================================
SCREENER_LOCK = threading.Lock()
SCREENER_STATE: Dict[str, Any] = {
    "status": "idle",          # idle | running | done | failed
    "strategy": "dip-divergence-breakout",
    "total": 0,
    "done": 0,
    "current": "",
    "started_at": None,
    "finished_at": None,
    "hit_count": 0,
    "miss_count": 0,
    "unavailable_count": 0,
    "persisted_count": 0,
    "unavailable": [],
    "notify": None,
    "error": None,
}


def _screener_worker(pool=None, strategy: str = "dip-divergence-breakout",
                     notify_channels=None, refresh: bool = False, dry_run: bool = False):
    from scripts.strategy_screener import run_screen

    def progress(index, total, code):
        with SCREENER_LOCK:
            SCREENER_STATE["done"] = index - 1
            SCREENER_STATE["total"] = total
            SCREENER_STATE["current"] = code

    try:
        result = run_screen(pool, strategy=strategy, refresh=refresh, persist=True, progress=progress)
        notify_outcome = None
        if notify_channels:
            from scripts.alert_channels import notify_hits
            try:
                notify_outcome = notify_hits(result["hits"], notify_channels, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                notify_outcome = {"sent": 0, "reason": f"告警下发异常: {exc}", "results": []}
        with SCREENER_LOCK:
            SCREENER_STATE.update({
                "status": "done", "total": result["universe_count"], "done": result["universe_count"],
                "current": "", "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "hit_count": result["hit_count"], "miss_count": result["miss_count"],
                "unavailable_count": result["unavailable_count"],
                "persisted_count": result["persisted_count"],
                "unavailable": result["unavailable"], "notify": notify_outcome, "error": None,
            })
    except Exception as exc:  # noqa: BLE001
        with SCREENER_LOCK:
            SCREENER_STATE.update({
                "status": "failed", "current": "",
                "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": f"策略选股失败: {exc}",
            })


def start_screener_run(pool=None, strategy: str = "dip-divergence-breakout",
                       notify_channels=None, refresh: bool = False, dry_run: bool = False) -> Tuple[bool, str]:
    with SCREENER_LOCK:
        if SCREENER_STATE["status"] == "running":
            return False, f"策略选股已在进行中（{SCREENER_STATE['done']}/{SCREENER_STATE['total']}）"
        SCREENER_STATE.update({
            "status": "running", "strategy": strategy, "total": 0, "done": 0, "current": "",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "finished_at": None,
            "hit_count": 0, "miss_count": 0, "unavailable_count": 0, "persisted_count": 0,
            "unavailable": [], "notify": None, "error": None,
        })
    threading.Thread(target=_screener_worker, args=(pool, strategy, notify_channels, refresh, dry_run),
                     daemon=True).start()
    return True, "策略选股已启动"



# ====================================================
# 需求REQ-017: 数据基准 (Baseline) 口径辅助函数
# 说明: 基准只决定「系统认定正在使用的采集批次」这一口径，
#      绝不改写、不伪造任何行情/K线数值；行情真实日期始终单独呈现。
# ====================================================

def normalize_crawl_date(value: Optional[str]) -> Optional[str]:
    """把抓取时间戳统一归一化为 YYYY-MM-DD 日期口径"""
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def current_quote_date() -> Optional[str]:
    """读取当前实际行情快照的真实交易日 (不由基准改写)"""
    quote_dates = sorted({
        str(s.get("timestamp"))[:8]
        for s in DATA_MANAGER.stocks_dict.values() if s.get("timestamp")
    })
    if not quote_dates:
        return None
    return normalize_crawl_date(quote_dates[-1])


def parse_quote_timestamp(raw: Any) -> Optional[Dict[str, Any]]:
    """
    需求REQ-046: 把来源行情时间戳解析为「精确到分」的真实快照时间。
    来源给到 14 位（YYYYMMDDHHMMSS）时精确到分；只给 8 位（YYYYMMDD）时如实降级为「日」；
    无法解析时返回 None（前端显示「未获取」，绝不用本地时钟或基准批次冒充行情时间）。
    """
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) < 8:
        return None
    date = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 12:
        hhmm = f"{digits[8:10]}:{digits[10:12]}"
        return {
            "raw": str(raw),
            "date": date,
            "time": hhmm,
            "datetime": f"{date} {hhmm}",
            "display": f"{int(digits[0:4])}年{int(digits[4:6])}月{int(digits[6:8])}日 {hhmm}",
            "precision": "minute",
            "source": "quote_snapshot",
        }
    return {
        "raw": str(raw),
        "date": date,
        "time": None,
        "datetime": date,
        "display": f"{int(digits[0:4])}年{int(digits[4:6])}月{int(digits[6:8])}日",
        "precision": "day",
        "source": "quote_snapshot",
    }


def current_quote_datetime() -> Optional[Dict[str, Any]]:
    """读取当前行情快照的真实时间（取全部标的中最新的来源时间戳，精确到分）。"""
    stamps = [
        str(s.get("timestamp"))
        for s in DATA_MANAGER.stocks_dict.values() if s.get("timestamp")
    ]
    if not stamps:
        return None
    return parse_quote_timestamp(max(stamps))


def serialize_baseline(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """把基准审计记录序列化为前端可用结构"""
    if not record:
        return None
    return {
        "id": int(record.get("id")) if record.get("id") is not None else None,
        "task_id": record.get("task_id"),
        "crawl_date": normalize_crawl_date(record.get("crawl_date")),
        "raw_crawl_date": record.get("crawl_date"),
        "status": record.get("status"),
        "fingerprint": record.get("fingerprint"),
        "target_scope": record.get("target_scope"),
        "total_items": record.get("total_items"),
        "updated_items": record.get("updated_items"),
        "skipped_items": record.get("skipped_items"),
        "details": record.get("details"),
        "is_baseline": bool(int(record.get("is_baseline") or 0)),
    }


def resolve_data_caliber() -> Dict[str, Any]:
    """
    汇总当前数据口径: 以「数据库基准」为准，同时如实暴露真实行情日期。
    基准缺失时明确置空，不回退到其他批次冒充。
    """
    from scripts.stock_db import ensure_crawl_baseline
    try:
        baseline = ensure_crawl_baseline()
    except Exception:
        baseline = None
    quote_date = current_quote_date()
    return {
        "baseline": serialize_baseline(baseline),
        "quote_date": quote_date,
        # 需求REQ-046: 真实行情快照时间（精确到分）；来源只给日期时 precision=day
        "quote_datetime": current_quote_datetime(),
        "snapshot_date": normalize_crawl_date(baseline.get("crawl_date")) if baseline else None,
        "snapshot_source": "baseline" if baseline else "unavailable",
    }


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
            # 需求REQ-054: 逐请求读取权威文件，版本变更无需重启
            self._send_json(200, {
                "version": current_version(),
                "info": current_version_info()
            })
            return

        # 3.1 独立爬虫状态 GET 兼容端点
        if url_path == "/api/crawler/status":
            self._send_json(200, CRAWLER_JOB.get_snapshot())
            return

        # 3.0.1 需求REQ-102/103: 压力线扫描状态（前端轮询用；只读，无副作用）
        if url_path == "/api/pressure/scan-status":
            status = pressure_scan.scan_status()
            status["cached_count"] = pressure_scan.cached_count(window=PRESSURE_WINDOW)
            self._send_json(200, {
                "code": 200,
                "version": current_version(),
                "data": status,
            })
            return

        # 3.0.2 需求REQ-102/103: 单只标的压力线实时测算（不读缓存，供前端/真机同源比对）
        if url_path == "/api/pressure/measure":
            query = parse_qs(urlsplit(self.path).query)
            symbol = (query.get("code") or [""])[0].strip()
            raw_window = (query.get("window") or [str(PRESSURE_WINDOW)])[0].strip()
            if not symbol:
                self._send_json(400, {"code": 400, "message": "缺少 code 参数"})
                return
            try:
                window = int(raw_window)
            except (TypeError, ValueError):
                self._send_json(400, {"code": 400, "message": f"window 仅支持 {PRESSURE_MIN_WINDOW}~{PRESSURE_MAX_WINDOW} 的整数"})
                return
            if window < PRESSURE_MIN_WINDOW or window > PRESSURE_MAX_WINDOW:
                self._send_json(400, {"code": 400, "message": f"window 仅支持 {PRESSURE_MIN_WINDOW}~{PRESSURE_MAX_WINDOW} 的整数"})
                return
            try:
                from scripts.market_history import canonical_code
                symbol = canonical_code(symbol)
            except ValueError as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
                return
            try:
                result = pressure_scan.measure_code(symbol, window=window)
            except ValueError as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
                return
            self._send_json(200, {
                "code": 200,
                "version": current_version(),
                "data": result,
            })
            return

        # 3.1.0 需求1: 数据中心抓取审计列表端点 /api/crawler/audit-list (ID、抓取日期、抓取状态、抓取指纹)
        if url_path == "/api/crawler/audit-list":
            from scripts.stock_db import (
                list_crawl_audit_records, get_latest_crawl_fingerprint,
                get_crawl_baseline, ensure_crawl_baseline, is_baseline_eligible_status
            )
            records = list_crawl_audit_records(limit=30)
            baseline = ensure_crawl_baseline()
            baseline_id = int(baseline["id"]) if baseline else None
            for rec in records:
                raw_status = rec.get("status") or ""
                verified = "真实行情" in raw_status
                rec["verification_status"] = "verified-quotes" if verified else "legacy-unverified"
                if not verified:
                    rec["status"] = "旧版日志（数据未核验）"
                    rec["details"] = "历史操作记录，仅供审计，不能证明数据真实或覆盖完整。"
                # 需求REQ-016/017: 基准标记与可否设为基准/可否删除，均由后端权威判定
                rec["is_baseline"] = bool(int(rec.get("is_baseline") or 0))
                rec["can_set_baseline"] = verified and is_baseline_eligible_status(raw_status)
                rec["can_delete"] = not rec["is_baseline"]
                rec["crawl_date_display"] = normalize_crawl_date(rec.get("crawl_date")) or rec.get("crawl_date") or ""
            latest_fp = get_latest_crawl_fingerprint()
            self._send_json(200, {
                "records": records,
                "total": len(records),
                "latest_fingerprint": latest_fp,
                "baseline_id": baseline_id,
                "baseline_task_id": baseline.get("task_id") if baseline else None,
                "baseline_crawl_date": normalize_crawl_date(baseline.get("crawl_date")) if baseline else None,
                "freshness_check": "audit-only"
            })
            return

        # 3.1.1 需求REQ-017: 读取当前数据基准 /api/crawler/baseline
        if url_path == "/api/crawler/baseline":
            from scripts.stock_db import ensure_crawl_baseline
            baseline = ensure_crawl_baseline()
            self._send_json(200, {
                "code": 200,
                "baseline": serialize_baseline(baseline),
                "quote_date": current_quote_date(),
            })
            return

        # 3.1.0.1 需求1/2: 一级「股东研究」全景列表端点 /api/shareholders/list
        if url_path == "/api/shareholders/list":
            from scripts.shareholder_engine import Top10ShareholdersEngine
            query_params = {}
            if "?" in self.path:
                q_str = self.path.split("?", 1)[1]
                for part in q_str.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        query_params[k.strip()] = urllib.parse.unquote(v.strip())

            kw = query_params.get("keyword", "").strip().lower()
            cat = query_params.get("category", "all").strip().lower()
            sort_by = query_params.get("sort_by", "total_holding_amount") # total_holding_amount | company_count
            sort_dir = query_params.get("sort_dir", "desc")

            # 需求REQ-108: 显式限次增量采集（?refresh=1&max_pages=6）。
            # 默认不触网；只在用户点击「采集新披露」时从 next_page 续采有限页，失败显式报错、不落 0。
            refresh_note = None
            if str(query_params.get("refresh", "")).strip().lower() in ("1", "true", "yes"):
                from scripts.shareholder_engine import refresh_holder_snapshot
                try:
                    refresh_note = refresh_holder_snapshot(max_pages=int(query_params.get("max_pages") or 6))
                except (ValueError, TypeError):
                    refresh_note = {"status": "error", "error": "max_pages 必须为整数", "new_records": 0}

            all_stocks = list(DATA_MANAGER.stocks_dict.values())
            # 聚合股东数据 (缓存或实时聚合)
            shareholders_raw = Top10ShareholdersEngine.aggregate_market_shareholders(all_stocks)

            # 计算需求1的6大概览指标 (基于全量聚合数据)
            overview_stats = Top10ShareholdersEngine.get_shareholders_overview(shareholders_raw)

            # 筛选
            shareholders = list(shareholders_raw)
            if cat in ("individual", "institution"):
                shareholders = [h for h in shareholders if h["category"] == cat]
            if kw:
                shareholders = [
                    h for h in shareholders
                    if kw in h["holder_name"].lower() or any(kw in c["name"].lower() for c in h["companies"])
                ]

            # 排序
            reverse = (sort_dir == "desc")
            if sort_by == "company_count":
                shareholders.sort(key=lambda x: (x["company_count"], (x.get("total_holding_amount") or 0)), reverse=reverse)
            else:
                shareholders.sort(key=lambda x: ((x.get("total_holding_amount") or 0), x["company_count"]), reverse=reverse)

            try:
                page=max(1,int(query_params.get("page",1)))
                page_size=max(1,min(200,int(query_params.get("page_size",50))))
            except (ValueError, TypeError):
                self._send_json(400, {"status":"error","message":"分页参数必须为整数"}); return
            self._send_json(200, {
                "page":page,"page_size":page_size,
                "total": len(shareholders),
                "overview": overview_stats,
                "refresh": refresh_note,
                "metadata": {k:v for k,v in __import__("scripts.shareholder_engine",fromlist=["get_holder_snapshot"]).get_holder_snapshot(allow_fetch=False).items() if k!="rows"},
                "data": shareholders[(page-1)*page_size:page*page_size]
            })
            return

        # 3.1.0.2 需求2/3/4/5/6: 指数列表与详情 API /api/index/list 与 /api/index/{code}
        if url_path == "/api/index/list":
            from scripts.index_engine import IndexEngine
            indices = IndexEngine.get_indices_list()
            self._send_json(200, {
                "total": len(indices),
                "data": indices
            })
            return

        # 需求REQ-028: 指数分钟K线端点 /api/index/<code>/minute-kline（与个股同一口径与同一来源）
        if url_path.startswith("/api/index/") and url_path.endswith("/minute-kline"):
            query = parse_qs(urlsplit(self.path).query)
            symbol = url_path.replace("/api/index/", "").replace("/minute-kline", "").strip()
            interval = (query.get("interval") or ["m5"])[0]
            try:
                limit = int((query.get("limit") or ["200"])[0])
            except (TypeError, ValueError):
                limit = 200
            try:
                self._send_json(200, {"code": 200, "symbol": symbol,
                                      "data": build_minute_kline(symbol, interval, limit=limit)})
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
            return

        if url_path.startswith("/api/index/"):
            from scripts.index_engine import IndexEngine
            code = url_path.replace("/api/index/", "").strip()
            detail = IndexEngine.get_index_detail(code)
            if detail:
                self._send_json(200, {
                    "code": 200,
                    "data": detail
                })
            else:
                self._send_json(404, {"error": "Index Not Found"})
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
                    "version": current_version(),
                    "total_universe_count": len(all_stocks),
                    "fingerprint_engine": "采集批次标识；真实字段来源见quote_meta",
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
            # 需求REQ-110: 行业筛选（默认 all）。过滤在**服务端同一入口**完成，
            # 仪表盘整页指标（5档阶梯/晴雨表/维度矩阵/Top10流通/分布图）随之天然联动。
            industry = urllib.parse.unquote(query_params.get("industry", "all")).strip() or "all"

            all_stocks = list(DATA_MANAGER.stocks_dict.values())
            industry_note = None
            if industry != "all":
                matched = [s for s in all_stocks if (s.get("industry") or "未采集") == industry]
                if not matched:
                    # 行业名不存在 / 尚未采集：显式如实返回，绝不静默回退成全市场。
                    self._send_json(200, {
                        "code": 200,
                        "version": current_version(),
                        "data": {"status": "unavailable", "source": "行业筛选",
                                 "error": f"行业「{industry}」未采集或不存在，无法统计（不回退全市场）",
                                 "industry": industry, "dimensions": {}, "summary": {}, "charts": {}}
                    })
                    return
                industry_note = {"industry": industry, "matched_stocks": len(matched), "total_stocks": len(all_stocks)}
                all_stocks = matched

            dashboard_data = compute_market_overview(all_stocks, start_date=s_date, end_date=e_date)
            if industry_note:
                dashboard_data = dict(dashboard_data, industry=industry, industry_filter=industry_note)
            self._send_json(200, {
                "code": 200,
                "version": current_version(),
                "data": dashboard_data
            })
            return

        # 3.2.1 需求REQ-110: 已采集行业清单（供仪表盘行业 Tab 与筛选复用）
        if url_path == "/api/industries":
            summary = load_industry_summary()
            self._send_json(200, {
                "code": 200,
                "version": current_version(),
                "source": "东方财富数据中心：证券基本信息 RPT_F10_BASIC_ORGINFO",
                "total_stocks": summary["total_stocks"],
                "collected_stocks": summary["collected_stocks"],
                "uncollected_stocks": summary["uncollected_stocks"],
                "items": summary["items"],
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
                "version": current_version(),
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

        # 3.6.0 需求REQ-019: 缠论多周期买卖点雷达池端点
        # 注意：必须先于下面的通用 /api/chanlun/<code> 结构端点匹配
        if url_path == "/api/chanlun/radar":
            q = parse_qs(urlsplit(self.path).query)
            code = (q.get("code", [""])[0] or "").strip()
            types = [t for t in (q.get("types", [""])[0] or "").replace("，", ",").split(",") if t.strip()]
            period = (q.get("period", [""])[0] or "").strip()
            limit = int(q.get("limit", ["500"])[0] or 500)
            from scripts import stock_db
            if code:
                # 指定证券：实时按双周期重新解构，返回含区间套判定的事实结果
                from scripts.chanlun_signals import analyze_code
                report = analyze_code(code, "", refresh=q.get("refresh", [""])[0] in ("1", "true"))
                signals = report.get("signals") or []
                if types:
                    signals = [s for s in signals if s["signal_type"] in types]
                if period:
                    signals = [s for s in signals if s["period"] == period]
                self._send_json(200, {
                    "code": 200, "message": "success", "mode": "live",
                    "rule_version": report.get("rule_version"),
                    "target": {"code": report.get("code")},
                    "periods": report.get("periods"), "errors": report.get("errors"),
                    "counts": report.get("counts"),
                    "snapshot": None,
                    "data": signals,
                    "disclaimer": report.get("disclaimer"),
                })
                return
            records = stock_db.list_chanlun_radar(signal_types=types or None, period=period, limit=limit)
            self._send_json(200, {
                "code": 200, "message": "success", "mode": "radar",
                "snapshot": stock_db.chanlun_radar_snapshot(),
                "scan": dict(CHANLUN_RADAR_STATE),
                "data": [r.get("signal") for r in records if r.get("signal")],
                "disclaimer": ("雷达池为最近一次全池扫描的结构化事实快照，不构成投资建议，不承诺收益；"
                               "池中无该证券记录可能因为来源未获取，需结合扫描明细中的失败项判断。"),
            })
            return

        if url_path == "/api/chanlun/radar/scan-status":
            from scripts import stock_db
            self._send_json(200, {
                "code": 200, "message": "success",
                "scan": dict(CHANLUN_RADAR_STATE),
                "snapshot": stock_db.chanlun_radar_snapshot(),
            })
            return

        # 3.6.2 需求REQ-020: 策略选股结果与告警通道状态
        if url_path == "/api/screener/results":
            from scripts import stock_db
            from scripts.strategy_screener import STRATEGY_META
            q = parse_qs(urlsplit(self.path).query)
            strategy = (q.get("strategy", [""])[0] or "").strip()
            code = (q.get("code", [""])[0] or "").strip()
            limit = int(q.get("limit", ["500"])[0] or 500)
            records = stock_db.list_screen_results(strategy=strategy, code=code, limit=limit)
            self._send_json(200, {
                "code": 200, "message": "success",
                "strategies": [{"key": k, "name": v["name"], "side": v["side"],
                                "desc": v["desc"], "defaults": v["defaults"]} for k, v in STRATEGY_META.items()],
                "snapshot": stock_db.screen_results_snapshot(),
                "scan": dict(SCREENER_STATE),
                "data": [r.get("hit") for r in records if r.get("hit")],
                "disclaimer": ("命中为结构化条件筛选结果，不构成投资建议，不承诺收益或胜率；"
                               "未命中不代表该证券没有机会或没有风险。"),
            })
            return

        if url_path == "/api/screener/scan-status":
            from scripts import stock_db
            self._send_json(200, {"code": 200, "message": "success",
                                  "scan": dict(SCREENER_STATE),
                                  "snapshot": stock_db.screen_results_snapshot()})
            return

        # 3.6.3 需求REQ-021: 持仓组合风险体检
        if url_path == "/api/portfolio/checkup":
            from scripts.portfolio_checkup import run_checkup
            try:
                report = run_checkup()
            except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
                self._send_json(200, {"code": 200, "message": "success", "status": "error",
                                      "reason": f"体检中止：{exc}",
                                      "rule_version": "REQ-021/v1", "positions": [], "summary": {}})
                return
            self._send_json(200, dict(report, code=200, message="success"))
            return

        if url_path == "/api/notify/status":
            from scripts.alert_channels import channel_status, load_notify_config
            config = load_notify_config()
            self._send_json(200, {
                "code": 200, "message": "success",
                "enabled": bool(config.get("enabled")),
                "cooldown_minutes": config.get("cooldown_minutes"),
                "max_per_run": config.get("max_per_run"),
                "channels": channel_status(config),
                "note": ("Webhook 与加签密钥只从 config/notify_config.json 读取，既不入库也不入版本控制；"
                         "此处只返回是否已配置与脱敏目标提示。"),
            })
            return

        if url_path == "/api/notify/history":
            from scripts import stock_db
            limit = int((parse_qs(urlsplit(self.path).query).get("limit", ["50"])[0]) or 50)
            self._send_json(200, {"code": 200, "message": "success",
                                  "data": stock_db.list_alert_dispatch(limit=limit),
                                  "note": "只记录真实下发结果与脱敏目标提示，不含任何密钥。"})
            return

        if url_path.startswith('/api/chanlun/'):
            try:
                from scripts.chanlun_analysis import analyze_bars
                code=url_path.rsplit('/',1)[-1]
                # 需求REQ-107: 改走关系库快路径（读优先 + 单页有界首屏 + 增量），
                # 替代 get_daily_history 在缓存过期时的 13 页全量回溯（实测 ≈2.0s）
                from scripts.kline_store import get_chart_history
                h=get_chart_history(code)
                q=parse_qs(urlsplit(self.path).query)
                result=analyze_bars(h['bars'],code=h['code'],periods=tuple(int(x) for x in q.get('ma_periods',['5,10,20'])[0].split(',')),threshold_pct=float(q.get('threshold',['1'])[0]),min_bars=int(q.get('min_bars',['3'])[0]))
                result['history_meta']={k:v for k,v in h.items() if k!='bars'}
                self._send_json(200,result)
            except (ValueError,TypeError) as exc:self._send_json(400,{'error':str(exc)})
            return

        if url_path.startswith('/api/stock/') and url_path.endswith('/dividends'):
            from scripts.verified_disclosures import dividends
            try: self._send_json(200, {'code':200,'data':dividends(url_path.split('/')[3])})
            except ValueError as exc:self._send_json(400,{'error':str(exc)})
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
            stock_info = DATA_MANAGER.stocks_dict.get(symbol, {})
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
            stock_info = DATA_MANAGER.stocks_dict.get(symbol, {})
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
            stock_info = DATA_MANAGER.stocks_dict.get(symbol, {})
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
            stock_info = DATA_MANAGER.stocks_dict.get(symbol, {})
            stk_name = str(stock_info.get("name") or "")
            t10_circ = float(stock_info.get("top10_circ_hold_pct") or 0.0)
            rep_date = stock_info.get("report_date")
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

        # 3.9 需求REQ-114: 个股股东明细端点 /api/stock/<code>/holder-detail
        # 十大流通股东 + 十大股东，各自多期披露（默认 6 期）+ 累计口径 + 较上期增减 + 退出分组。
        # 来源：东方财富 F10 股东中心 RPT_F10_EH_FREEHOLDERS / RPT_F10_EH_HOLDERS（24h 缓存，非每次触网）。
        if url_path.startswith("/api/stock/") and url_path.endswith("/holder-detail"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            q = parse_qs(urlsplit(self.path).query)
            refresh = str(q.get("refresh", ["0"])[0]).lower() in ("1", "true", "yes")
            from scripts.shareholder_engine import Top10ShareholdersEngine
            try:
                detail = Top10ShareholdersEngine.get_stock_holder_detail(symbol, refresh=refresh)
            except ValueError as exc:
                self._send_json(400, {"code": 400, "error": str(exc)})
                return
            self._send_json(200, {"code": 200, "symbol": symbol, "data": detail})
            return

        # 3.10 需求REQ-116: 个股股东人数端点 /api/stock/<code>/holder-count
        # 户数/股价双轴走势 + 6 期指标（户数/较上期/人均流通股/人均流通变化/人均持股金额）+ 行业平均（工程口径，附样本数）。
        if url_path.startswith("/api/stock/") and url_path.endswith("/holder-count"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            q = parse_qs(urlsplit(self.path).query)
            refresh = str(q.get("refresh", ["0"])[0]).lower() in ("1", "true", "yes")
            try:
                count = max(1, min(int(q.get("count", ["6"])[0] or 6), 12))
            except (TypeError, ValueError):
                count = 6
            stock_info = DATA_MANAGER.stocks_dict.get(symbol, {})
            from scripts.shareholder_engine import HolderCountEngine
            data = HolderCountEngine.get_holder_count(symbol, name=str(stock_info.get("name") or ""), count=count, refresh=refresh)
            self._send_json(200, {"code": 200, "symbol": symbol, "data": data})
            return

        # 3.11 需求REQ-116: 全市场股东户数增减量排名端点 /api/holder-count/rank
        # 口径：来源 RPT_HOLDERNUMLATEST 最新一期户数较上期变化率；样本=已采集且存在于本地行业表的标的。
        if url_path == "/api/holder-count/rank":
            q = parse_qs(urlsplit(self.path).query)
            try:
                limit = max(1, min(int(q.get("limit", ["20"])[0] or 20), 100))
            except (TypeError, ValueError):
                limit = 20
            from scripts.shareholder_engine import HolderCountEngine
            self._send_json(200, {"code": 200, "data": HolderCountEngine.get_holder_count_rank(limit=limit)})
            return

        # 4. 服务端状态端点 (常显心跳检查)
        if url_path == "/api/status":
            with SERVER_STATE_LOCK:
                curr_state = SERVER_STATE

            uptime = int(time.time() - SERVER_START_TIME)
            caliber = resolve_data_caliber()
            data = {
                "status": curr_state,
                "service": "DSH Stock Web Server",
                "version": current_version(),
                "pid": os.getpid(),
                "port": self.server.server_port,
                "uptime_seconds": uptime,
                "stock_count": len(DATA_MANAGER.stocks_dict),
                "csi50_count": len(DATA_MANAGER.csi50_set),
                "csi100_count": len(DATA_MANAGER.csi100_set),
                "db_path": DB_FILE,
                # 需求REQ-017: 快照日期以「数据库基准」批次为准；真实行情日期单独如实暴露
                "snapshot_date": caliber["snapshot_date"],
                "snapshot_source": caliber["snapshot_source"],
                "quote_date": caliber["quote_date"],
                # 需求REQ-046: 真实行情快照时间（精确到分，来源只给日期时为 day 精度）
                "quote_datetime": caliber["quote_datetime"],
                "baseline": caliber["baseline"],
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._send_json(200, data)
            return

        # 5. 动态配置元数据 Schema
        if url_path == "/api/filter_schema":
            schema = {
                "version": current_version(),
                "dimensions": [
                    {"id": "shareholder_action", "name": "股东行为", "type": "select", "options": [{"value": "all", "label": "全部"}, {"value": "increase", "label": "增持"}, {"value": "decrease", "label": "减持"}, {"value": "both", "label": "同时增减持"}]},
                    {"id": "market", "name": "股市分类", "type": "select", "options": [{"value": "all", "label": "全部 A 股"}, {"value": "sh", "label": "上证"}, {"value": "sz", "label": "深圳"}]},
                    {"id": "board", "name": "板块分类", "type": "select", "options": [{"value": "all", "label": "全部板块"}, {"value": "main", "label": "主板"}, {"value": "chinext", "label": "创业板"}]},
                    # 需求REQ-111: 行业筛选（选项不在 schema 内硬编码，统一取 /api/industries，避免两套口径）
                    {"id": "industry", "name": "所属行业", "type": "select", "options_url": "/api/industries", "hint": "与仪表盘「行业」Tab 同源同序；默认「全部」；未采集行业不回退全市场"},
                    {"id": "constituent", "name": "成分股", "type": "select", "options": [{"value": "all", "label": "全部(不限)"}, {"value": "csi50", "label": "中证A50"}, {"value": "csi100", "label": "中证A100"}]},
                    {"id": "price", "name": "股价区间", "type": "range", "unit": "元"},
                    {"id": "market_cap", "name": "总市值区间", "type": "range", "unit": "亿元"},
                    {"id": "circ_cap", "name": "流通市值区间", "type": "range", "unit": "亿元"},
                    {"id": "pe", "name": "市盈率 PE", "type": "range", "unit": "倍"},
                    {"id": "dividend_count", "name": "分红次数", "type": "range", "unit": "次"},
                    {"id": "dividend_total_amount", "name": "累计分红总额", "type": "range", "unit": "亿元"},
                    {"id": "listing_years", "name": "上市时长", "type": "range", "unit": "年"},
                    {"id": "top10_circ", "name": "十大流通股东持股", "type": "range", "unit": "%"},
                    {"id": "top10_hold", "name": "十大股东持股", "type": "range", "unit": "%"},
                    # 需求REQ-113: 前3大股东合计持股区间（默认不限制）
                    {"id": "top3", "name": "前3大股东合计持股", "type": "range", "unit": "%", "hint": "留空=不限制；口径=最新一期十大股东披露 rank1~3 持股比例之和；1~3 名不齐=未采集，不参与筛选"},
                    {"id": "breakdown_days", "name": "连续跌破压力线天数", "type": "number", "unit": "天", "range": [1, 60]},
                    {"id": "breakout_days", "name": "连续冲高压力线天数", "type": "number", "unit": "天", "range": [1, 60]},
                    {"id": "filter_date", "name": "筛选基准日期", "type": "date"}
                ]
            }
            self._send_json(200, schema)
            return

        # 3.9.1 需求REQ-126: 分时端点 /api/stock/<code>/timeline?date=YYYYMMDD
        # 口径：`date` 省略 ⇒ 最近交易日（旧行为不变）；给日期 ⇒ 该交易日 1 分钟分时
        #       （来源 `appstock/app/day/query`，一次请求覆盖最近 5 个交易日，命中本地
        #       `stock_timeline` 即零外网）；窗口外 / 停牌 / 来源失败一律 `unavailable` + 原因，
        #       **绝不返回空数组冒充成功，也绝不用 5分K或日K近似顶替**。
        if url_path.startswith("/api/stock/") and url_path.endswith("/timeline"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            q = parse_qs(urlsplit(self.path).query)
            want_date = (q.get("date") or [""])[0].strip()
            try:
                from scripts.detail_fastpath import cached_timeline
                data = cached_timeline(symbol, fetcher=fetch_real_timeline,
                                       date=want_date or None,
                                       history_fetcher=fetch_real_timeline_history)
                self._send_json(200, {"code": 200, "symbol": symbol, "data": data})
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
            return

        # 6. 单只股票详情
        # 3.9 需求REQ-024: 分时级别缠论分析端点 /api/stock/<code>/intraday-chanlun
        # 口径: 分时点视为 1 根K线（开=收=高=低=该分钟价），复用 scripts.chanlun_analysis 同一套算法，
        #       不在前端另起一套；级别明确为「分时级别」，与日线级别严格区分。
        if url_path.startswith("/api/stock/") and url_path.endswith("/intraday-chanlun"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            try:
                self._send_json(200, {"code": 200, "symbol": symbol, "data": build_intraday_chanlun(symbol)})
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
            return

        # 3.10 需求REQ-028: 分钟K线端点 /api/stock/<code>/minute-kline?interval=m5|m15|m30&limit=200
        # 口径: 每根K线为一个真实时间区间；成交额由均价×成交量推出并标记为估算，端点内不做任何拟合或填充。
        if url_path.startswith("/api/stock/") and url_path.endswith("/minute-kline"):
            parts = url_path.split("/")
            symbol = parts[3] if len(parts) >= 4 else ""
            query = parse_qs(urlsplit(self.path).query)
            interval = (query.get("interval") or ["m5"])[0]
            try:
                limit = int((query.get("limit") or ["200"])[0])
            except (TypeError, ValueError):
                limit = 200
            try:
                self._send_json(200, {"code": 200, "symbol": symbol,
                                      "data": build_minute_kline(symbol, interval, limit=limit)})
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
            return

        if url_path.startswith("/api/stock/"):
            symbol = url_path.replace("/api/stock/", "").strip()
            query = parse_qs(urlsplit(self.path).query)
            try:
                detail = DATA_MANAGER.get_stock_detail(symbol, refresh=query.get("refresh") == ["1"],
                                                       shareholder_days=int(query.get("shareholder_days", [365])[0]))
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
                return
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
            try:
                filtered_stocks, stats = DATA_MANAGER.filter_stocks(params)
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
                return
            self._send_json(200, {
                "code": 200,
                "message": "success",
                "version": load_version_info().get("version", "v3.0.0"),
                "stats": stats,
                "filter_params": params,
                "data": filtered_stocks
            })
            return

        # 需求REQ-102/103: 请求停止压力线后台扫描（当前标的走完即停，已测算结果保留）
        if url_path == "/api/pressure/scan-cancel":
            self._send_json(200, {"code": 200, "data": pressure_scan.cancel_scan()})
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

        # 6.5 需求REQ-019: 启动缠论雷达池全池扫描 (/api/chanlun/radar/scan)
        if url_path == "/api/chanlun/radar/scan":
            pool = params.get("codes")
            codes = None
            if isinstance(pool, list) and pool:
                from scripts.chanlun_signals import normalize_code
                codes = [(normalize_code(str(c)), "") for c in pool if str(c).strip()]
            started, msg = start_chanlun_radar_scan(codes, refresh=bool(params.get("refresh")))
            self._send_json(200 if started else 409, {
                "code": 200 if started else 409,
                "success": started,
                "message": msg,
                "scan": dict(CHANLUN_RADAR_STATE),
            })
            return

        # 6.5b 需求REQ-041: 任意真实K线序列的缠论分析（周线/季线/5分K线现场判定，纯计算不落库）
        if url_path == "/api/chanlun/bars":
            try:
                data = build_chanlun_from_bars(
                    str(params.get("code") or ""), params.get("bars"), params.get("level"))
            except (ValueError, TypeError) as exc:
                self._send_json(400, {"code": 400, "message": str(exc)})
                return
            self._send_json(200, {"code": 200, "message": "success", "data": data})
            return

        # 6.6 需求REQ-020: 启动策略选股 (/api/screener/scan)
        if url_path == "/api/screener/scan":
            pool = params.get("codes")
            codes = None
            if isinstance(pool, list) and pool:
                from scripts.chanlun_signals import normalize_code
                codes = [(normalize_code(str(c)), "") for c in pool if str(c).strip()]
            notify_raw = params.get("notify")
            notify_channels = None
            if isinstance(notify_raw, list):
                notify_channels = [str(c).strip() for c in notify_raw if str(c).strip()] or None
            elif isinstance(notify_raw, str) and notify_raw.strip() and notify_raw.strip().lower() != "all":
                notify_channels = [c.strip() for c in notify_raw.split(",") if c.strip()]
            elif isinstance(notify_raw, str) and notify_raw.strip().lower() == "all":
                notify_channels = ["feishu", "dingtalk"]
            started, msg = start_screener_run(
                codes, strategy=str(params.get("strategy") or "dip-divergence-breakout"),
                notify_channels=notify_channels,
                refresh=bool(params.get("refresh")), dry_run=bool(params.get("dry_run")))
            self._send_json(200 if started else 409, {
                "code": 200 if started else 409, "success": started, "message": msg,
                "scan": dict(SCREENER_STATE),
            })
            return

        # 7. 需求REQ-016: 数据中心抓取记录批量删除 (/api/crawler/audit-delete)
        if url_path == "/api/crawler/audit-delete":
            from scripts.stock_db import delete_crawl_audit_records, list_crawl_audit_records
            raw_ids = params.get("ids")
            if raw_ids is None:
                raw_ids = params.get("record_ids") or []
            if not isinstance(raw_ids, list):
                self._send_json(400, {"code": 400, "message": "ids 必须为数组"})
                return
            outcome = delete_crawl_audit_records(raw_ids)
            ok = bool(outcome["deleted"]) and not outcome["protected"] and not outcome["skipped"]
            self._send_json(200, {
                "code": 200,
                "success": ok,
                "message": (
                    f"已删除 {len(outcome['deleted'])} 条抓取审计记录"
                    if outcome["deleted"] else "没有可删除的记录"
                ),
                "deleted": outcome["deleted"],
                "skipped": outcome["skipped"],
                "protected": outcome["protected"],
                "reason": outcome["reason"],
                "records": list_crawl_audit_records(limit=30),
            })
            return

        # 8. 需求REQ-017: 手动切换数据库基准 (/api/crawler/baseline)
        if url_path == "/api/crawler/baseline":
            from scripts.stock_db import set_crawl_baseline, ensure_crawl_baseline
            record_id = params.get("id")
            if record_id is None:
                record_id = params.get("record_id")
            if record_id is None:
                self._send_json(400, {"code": 400, "message": "缺少基准记录 id"})
                return
            success, message, _record = set_crawl_baseline(int(record_id))
            baseline = ensure_crawl_baseline()
            caliber = resolve_data_caliber()
            self._send_json(200 if success else 400, {
                "code": 200 if success else 400,
                "success": success,
                "message": message,
                "baseline": serialize_baseline(baseline),
                "snapshot_date": caliber["snapshot_date"],
                "snapshot_source": caliber["snapshot_source"],
                "quote_date": caliber["quote_date"],
                "quote_datetime": caliber["quote_datetime"],
            })
            return

        # 9. 彻底注销进程 API (/api/server/kill)
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
        response = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
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
    """
    只在 PID 文件**仍然属于自己**时才删除。

    为什么必须校验归属（REQ-128 实测缺陷，2026-10-08）：
        旧实现无条件 os.remove(PID_FILE)。当端口已被占用（重复实例抢 8888 失败）时，
        失败实例走 `except OSError → cleanup_pid_file()`，把**健康实例**的 PID 文件删掉，
        留痕实证：server.log 里 `🟢 进程 PID: 13464 (已写入 .server.pid)` 之后紧跟
        `❌ 启动失败: 端口 8888 可能已被占用 ([Errno 48])`，随后 .server.pid 消失，
        而监听进程 13464 仍在 —— stop_server.sh / watchdog 失去权威 PID 句柄。
    """
    try:
        if not os.path.exists(PID_FILE):
            return
        with open(PID_FILE, "r") as f:
            owner = f.read().strip()
        if owner == str(os.getpid()):
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
    # 禁用激进自毁，防止偶发文件系统探测抖动导致服务意外退出
    pass


def resolve_bind_host(cli_host: str | None = None) -> str:
    """需求REQ-049: 服务端默认**只绑定本机回环**（安全默认）。

    历史默认值是 0.0.0.0（对整个局域网开放且无鉴权）。本产品是单人本机工具，
    因此默认收紧为 127.0.0.1；确需其它设备访问时，用 `DSH_STOCK_HOST=0.0.0.0`
    （或显式 `--host 0.0.0.0`）自行放开，并在文档中说明该决定。
    """
    env_host = (os.environ.get("DSH_STOCK_HOST") or "").strip()
    if env_host:
        return env_host
    if cli_host and cli_host.strip():
        return cli_host.strip()
    return "127.0.0.1"


def run_server(host: str = "127.0.0.1", port: int = 8888):
    global SERVER_INSTANCE

    signal.signal(signal.SIGINT, cleanup_and_exit)
    signal.signal(signal.SIGTERM, cleanup_and_exit)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, cleanup_and_exit)
    atexit.register(cleanup_pid_file)

    # 需求REQ-128: PID 文件必须**绑定端口成功之后**才写。
    # 旧实现先写 PID 再 bind（第 2274 行），重复实例会在抢端口失败前就把健康实例的
    # PID 覆盖成自己的死 PID；成功后写 + cleanup 校验归属，双保险。
    start_workspace_watchdog()

    print(f"[DSH Web Server] 正在启动 A 股全市场量化中枢 ({current_version()})...")
    print(f"[DSH Web Server] 本地 SQLite 库已连接: {DB_FILE} ｜ 已沉淀标的: {len(DATA_MANAGER.stocks_dict)} 只")

    try:
        server_address = (host, port)
        ThreadingHTTPServer.allow_reuse_address = True
        SERVER_INSTANCE = ThreadingHTTPServer(server_address, StockRequestHandler)
        write_pid_file()
        print(f"===============================================================")
        print(f" 🚀 DSH A股量化筛选 Web 服务端已成功就绪！版本: {current_version()}")
        print(f" 📍 本地访问地址: http://127.0.0.1:{port}")
        exposed = host not in ("127.0.0.1", "localhost", "::1")
        print(f" 🔒 监听绑定    : {host}:{port}" + ("（⚠️ 已放开到非回环地址，局域网可达且当前无鉴权）" if exposed else "（仅本机回环，局域网不可达）"))
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
    parser.add_argument("--host", type=str, default=None,
                        help="监听主机 (默认: 127.0.0.1 仅本机回环；可用 DSH_STOCK_HOST 覆盖，放开到 0.0.0.0 即局域网可达)")
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
        run_server(host=resolve_bind_host(args.host), port=args.port)
