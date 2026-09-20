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
    load_all_stocks_from_db,
    save_daily_klines,
    load_daily_klines,
    save_stock_timeline,
    load_stock_timeline
)
from scripts.stock_data_engine import (
    StockQuote,
    KLineBar,
    normalize_code,
)
from scripts.stock_indicators import evaluate_stock
from scripts.stock_chart_svg import generate_stock_svg
from scripts.manual_crawler import CRAWLER_JOB
from scripts.real_chart_engine import fetch_real_daily_kline, fetch_real_timeline
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

        from scripts.shareholder_engine import Top10ShareholdersEngine
        Top10ShareholdersEngine.enrich_stock_holder_metrics(stock)

        # 3. 需求1/2/3: 日K线查询 - 本地数据库优先 (Local-DB-First)
        history = get_daily_history(norm, refresh=refresh)
        daily_bars = history["bars"]

        # 4. 需求1/2/3: 分时数据查询 - 本地数据库优先 (Local-DB-First)
        # 旧分时缓存同样没有来源证明，不再参与详情；仅使用本次真实来源响应。
        timeline_data = fetch_real_timeline(norm)

        # 5. 上市公司基本资料与深度财务报表
        company_profile = fetch_company_profile(norm, stock["name"], stock["market"], stock["board"])
        financial_reports = fetch_financial_statements(norm, stock["price"], stock["market_cap"], stock["pe"])

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
        # 需求1/2: 日交易额与日均交易额区间 (亿元)
        f_min_daily_amount = to_float(params.get("min_daily_amount"))
        f_max_daily_amount = to_float(params.get("max_daily_amount"))
        f_min_avg_daily_amount = to_float(params.get("min_avg_daily_amount"))
        f_max_avg_daily_amount = to_float(params.get("max_avg_daily_amount"))
        # 需求2: 上市时长区间 (年)
        f_min_listing_years = to_float(params.get("min_listing_years"))
        f_max_listing_years = to_float(params.get("max_listing_years"))
        # 需求2: 个人占比与机构占比筛选区间
        f_min_individual = to_float(params.get("min_individual_pct"))
        f_max_individual = to_float(params.get("max_individual_pct"))
        f_min_institution = to_float(params.get("min_institution_pct"))
        f_max_institution = to_float(params.get("max_institution_pct"))
        # 需求5: 盈利时长单选 (all / 1 / 2 / 3)
        profit_years = params.get("profit_years")
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

        # 阶段 2：检查行情，若处于 running 状态且有未拉取行情的标的则快速补充
        with SERVER_STATE_LOCK:
            current_state = SERVER_STATE
        if current_state == "running":
            unquoted = [c["code"] for c in filtered_candidates if not c.get("price")][:60]
            if unquoted:
                self.fetch_quotes_batch(unquoted)

        # 阶段 3：多维数值严格联合判定 (AND)
        matched = []
        for s in filtered_candidates:
            from scripts.shareholder_engine import Top10ShareholdersEngine
            Top10ShareholdersEngine.enrich_stock_holder_metrics(s)
            bounds = [('price',f_min_price,f_max_price),('market_cap',f_min_cap,f_max_cap),
                      ('circulating_cap',f_min_circ_cap,f_max_circ_cap),('pe',f_min_pe,f_max_pe),
                      ('top10_circ_hold_pct',f_min_top10_circ,f_max_top10_circ),('top10_hold_pct',f_min_top10,f_max_top10),
                      ('turnover_yi',f_min_daily_amount,f_max_daily_amount),('avg_daily_amount',f_min_avg_daily_amount,f_max_avg_daily_amount),
                      ('listing_years',f_min_listing_years,f_max_listing_years),('holder_individual_pct',f_min_individual,f_max_individual),
                      ('holder_institution_pct',f_min_institution,f_max_institution)]
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

        # 默认按总市值降序
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
            "baseline": caliber["baseline"],
            "page": page,
            "page_size": page_size,
            "server_state": current_state
        }
        stats['coverage']={k:sum(s.get(k) is not None for s in matched) for k in ('price','change_pct','market_cap','circulating_cap')}
        stats['quote_dates']=sorted({str(s.get('timestamp') or '')[:8] for s in matched if s.get('timestamp')})
        stats['snapshot_note']='行情为当前已获取快照；日期口径以数据中心「数据库基准」批次为准，未提供历史全市场行情截面'

        stats["shareholder_actions"] = {k: v for k, v in action_snapshot.items() if k != "records"}
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_data = matched[start_idx:end_idx]

        # 需求2与需求3: 批量注入分红/总市值(%)及股东异动三兄弟指标
        from scripts.shareholder_engine import Top10ShareholdersEngine
        for s in paged_data:
            Top10ShareholdersEngine.enrich_stock_holder_metrics(s)
            enrich_actions(s, action_snapshot)

        return paged_data, stats


# 单例初始化
DATA_MANAGER = StockDataManager()
SERVER_START_TIME = time.time()
SERVER_INSTANCE = None
SHUTDOWN_REQUESTED = False

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
            self._send_json(200, {
                "version": APP_VERSION,
                "info": VERSION_INFO
            })
            return

        # 3.1 独立爬虫状态 GET 兼容端点
        if url_path == "/api/crawler/status":
            self._send_json(200, CRAWLER_JOB.get_snapshot())
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
                    "version": APP_VERSION,
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
                h=get_daily_history(code)
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

        # 4. 服务端状态端点 (常显心跳检查)
        if url_path == "/api/status":
            with SERVER_STATE_LOCK:
                curr_state = SERVER_STATE

            uptime = int(time.time() - SERVER_START_TIME)
            caliber = resolve_data_caliber()
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
                # 需求REQ-017: 快照日期以「数据库基准」批次为准；真实行情日期单独如实暴露
                "snapshot_date": caliber["snapshot_date"],
                "snapshot_source": caliber["snapshot_source"],
                "quote_date": caliber["quote_date"],
                "baseline": caliber["baseline"],
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._send_json(200, data)
            return

        # 5. 动态配置元数据 Schema
        if url_path == "/api/filter_schema":
            schema = {
                "version": APP_VERSION,
                "dimensions": [
                    {"id": "shareholder_action", "name": "股东行为", "type": "select", "options": [{"value": "all", "label": "全部"}, {"value": "increase", "label": "增持"}, {"value": "decrease", "label": "减持"}, {"value": "both", "label": "同时增减持"}]},
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
    # 禁用激进自毁，防止偶发文件系统探测抖动导致服务意外退出
    pass


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
        ThreadingHTTPServer.allow_reuse_address = True
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
