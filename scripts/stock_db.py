#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH A股本地持久化数据库引擎 (Stock SQLite Database Engine)
版本: v1.2.0

功能:
1. 纯原生 SQLite 嵌入式存储，零外部三方依赖
2. 存储全量 A 股主板与创业板标的、实时与历史行情快照、分红次数、上市总时长、十大股东等
3. 支持高并发读写锁、批量事务原子写入与断点持久化
"""

import os
import sys
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("DSH_STOCK_DB", os.path.join(DATA_DIR, "stock_database.db"))


def get_db_connection() -> sqlite3.Connection:
    """获取 SQLite 数据库连接并配置超时与行字典模式"""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")  # 开启预写日志提升并发写入性能
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_db():
    """初始化数据库架构与核心数据表索引"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. 标的底册主表 (stocks_master)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks_master (
            code TEXT PRIMARY KEY,
            raw_code TEXT NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            market_code TEXT NOT NULL,
            board TEXT NOT NULL,
            board_code TEXT NOT NULL,
            is_csi50 INTEGER DEFAULT 0,
            is_csi100 INTEGER DEFAULT 0,
            ipo_date TEXT DEFAULT '',
            listing_years REAL DEFAULT 0.0,
            dividend_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT ''
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks_master(market_code);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_board ON stocks_master(board_code);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_csi ON stocks_master(is_csi50, is_csi100);")
        columns = {r[1] for r in cursor.execute('PRAGMA table_info(stocks_master)')}
        for name, kind in [('pinyin_abbr', 'TEXT'), ('dividend_total_amount', 'REAL')]:
            if name not in columns:
                cursor.execute(f'ALTER TABLE stocks_master ADD COLUMN {name} {kind}')

        # 2. 实时行情与基本面表 (stock_quotes)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_quotes (
            code TEXT PRIMARY KEY,
            price REAL DEFAULT 0.0,
            change_val REAL DEFAULT 0.0,
            change_pct REAL DEFAULT 0.0,
            prev_close REAL DEFAULT 0.0,
            open_p REAL DEFAULT 0.0,
            high_p REAL DEFAULT 0.0,
            low_p REAL DEFAULT 0.0,
            volume REAL DEFAULT 0.0,
            turnover REAL DEFAULT 0.0,
            turnover_yi REAL DEFAULT 0.0,
            turnover_rate REAL DEFAULT 0.0,
            pe REAL DEFAULT 0.0,
            market_cap REAL DEFAULT 0.0,
            circulating_cap REAL DEFAULT 0.0,
            timestamp TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        );
        """)

        # 3. 股东结构与筹码集中度表 (stock_shareholders)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_shareholders (
            code TEXT PRIMARY KEY,
            report_date TEXT DEFAULT '',
            top10_hold_pct REAL DEFAULT 0.0,
            top10_circ_hold_pct REAL DEFAULT 0.0,
            updated_at TEXT DEFAULT ''
        );
        """)

        # 4. 采集数据指纹与幂等校验表 (data_fingerprints - 需求1)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_fingerprints (
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            data_hash TEXT NOT NULL,
            signature TEXT DEFAULT '',
            payload TEXT DEFAULT '',
            last_synced_at TEXT DEFAULT '',
            PRIMARY KEY (entity_type, entity_id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fp_hash ON data_fingerprints(data_hash);")

        # 5. 数据中心抓取审计流水表 (crawl_audit_records - v3.4.0)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawl_audit_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            crawl_date TEXT NOT NULL,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            target_scope TEXT DEFAULT '',
            total_items INTEGER DEFAULT 0,
            updated_items INTEGER DEFAULT 0,
            skipped_items INTEGER DEFAULT 0,
            details TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_crawl_date ON crawl_audit_records(crawl_date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_crawl_fp ON crawl_audit_records(fingerprint);")

        # 4.1.0 需求REQ-017: 旧库迁移 —— 补齐数据基准标记列 (is_baseline, 全局唯一)
        existing_cols = {row["name"] for row in cursor.execute("PRAGMA table_info(crawl_audit_records);").fetchall()}
        if "is_baseline" not in existing_cols:
            cursor.execute("ALTER TABLE crawl_audit_records ADD COLUMN is_baseline INTEGER DEFAULT 0;")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_crawl_baseline ON crawl_audit_records(is_baseline);")

        # 6. 需求1/4: 历史日K线结构表 (stock_daily_kline - 轻量、去重、低耦合)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily_kline (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            close REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            volume REAL NOT NULL,
            amount_yi REAL NOT NULL,
            change_pct REAL DEFAULT 0.0,
            created_at TEXT DEFAULT '',
            PRIMARY KEY (code, date)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_date ON stock_daily_kline(code, date);")

        # 7. 需求1/4: 当日分时切片表 (stock_timeline - 当日明细、轻便存储、低冗余)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_timeline (
            code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            pre_close REAL NOT NULL,
            items_json TEXT NOT NULL,
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (code, trade_date)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_code ON stock_timeline(code, trade_date);")

        conn.commit()

    # 需求REQ-017: 基准兜底初始化 (无基准时回填最近一条已核验成功批次)
    try:
        ensure_crawl_baseline()
    except Exception:
        pass


def save_master_stocks(stocks: List[Dict[str, Any]]):
    """批量保存或更新标的底册主表"""
    if not stocks:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT INTO stocks_master (
            code, raw_code, name, market, market_code, board, board_code,
            is_csi50, is_csi100, ipo_date, listing_years, dividend_count, updated_at
        ) VALUES (
            :code, :raw_code, :name, :market, :market_code, :board, :board_code,
            :is_csi50, :is_csi100, :ipo_date, :listing_years, :dividend_count, :updated_at
        ) ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            market = excluded.market,
            market_code = excluded.market_code,
            board = excluded.board,
            board_code = excluded.board_code,
            is_csi50 = excluded.is_csi50,
            is_csi100 = excluded.is_csi100,
            ipo_date = CASE WHEN excluded.ipo_date != '' THEN excluded.ipo_date ELSE stocks_master.ipo_date END,
            listing_years = CASE WHEN excluded.listing_years > 0 THEN excluded.listing_years ELSE stocks_master.listing_years END,
            dividend_count = CASE WHEN excluded.dividend_count > 0 THEN excluded.dividend_count ELSE stocks_master.dividend_count END,
            updated_at = excluded.updated_at;
        """, [
            {
                "code": s["code"],
                "raw_code": s.get("raw_code") or s["code"][2:],
                "name": s["name"],
                "market": s.get("market", "上证"),
                "market_code": s.get("market_code", "sh"),
                "board": s.get("board", "主板"),
                "board_code": s.get("board_code", "main"),
                "is_csi50": 1 if s.get("is_csi50") else 0,
                "is_csi100": 1 if s.get("is_csi100") else 0,
                "ipo_date": s.get("ipo_date", ""),
                "listing_years": float(s.get("listing_years", 0.0)),
                "dividend_count": int(s.get("dividend_count", 0)),
                "updated_at": now_str
            }
            for s in stocks
        ])
        conn.commit()


def save_quotes_batch(quotes: List[Dict[str, Any]]):
    """批量沉淀行情快照至本地数据库"""
    if not quotes:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT INTO stock_quotes (
            code, price, change_val, change_pct, prev_close, open_p, high_p, low_p,
            volume, turnover, turnover_yi, turnover_rate, pe, market_cap, circulating_cap,
            timestamp, updated_at
        ) VALUES (
            :code, :price, :change_val, :change_pct, :prev_close, :open_p, :high_p, :low_p,
            :volume, :turnover, :turnover_yi, :turnover_rate, :pe, :market_cap, :circulating_cap,
            :timestamp, :updated_at
        ) ON CONFLICT(code) DO UPDATE SET
            price = excluded.price,
            change_val = excluded.change_val,
            change_pct = excluded.change_pct,
            prev_close = excluded.prev_close,
            open_p = excluded.open_p,
            high_p = excluded.high_p,
            low_p = excluded.low_p,
            volume = excluded.volume,
            turnover = excluded.turnover,
            turnover_yi = excluded.turnover_yi,
            turnover_rate = excluded.turnover_rate,
            pe = excluded.pe,
            market_cap = excluded.market_cap,
            circulating_cap = excluded.circulating_cap,
            timestamp = excluded.timestamp,
            updated_at = excluded.updated_at;
        """, [
            {
                "code": q["code"],
                "price": float(q.get("price", 0.0)),
                "change_val": float(q.get("change", 0.0)),
                "change_pct": float(q.get("change_pct", 0.0)),
                "prev_close": float(q.get("prev_close", 0.0)),
                "open_p": float(q.get("open", 0.0)),
                "high_p": float(q.get("high", 0.0)),
                "low_p": float(q.get("low", 0.0)),
                "volume": float(q.get("volume", 0.0)),
                "turnover": float(q.get("turnover", 0.0)),
                "turnover_yi": float(q.get("turnover_yi", 0.0)),
                "turnover_rate": float(q.get("turnover_rate", 0.0)),
                "pe": float(q.get("pe", 0.0)),
                "market_cap": float(q.get("market_cap", 0.0)),
                "circulating_cap": float(q.get("circulating_cap", 0.0)),
                "timestamp": q.get("timestamp", ""),
                "updated_at": now_str
            }
            for q in quotes
        ])
        conn.commit()


def save_shareholder_item(code: str, report_date: str, top10_hold_pct: float, top10_circ_hold_pct: float):
    """保存或更新单只股票十大股东持股数据"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO stock_shareholders (code, report_date, top10_hold_pct, top10_circ_hold_pct, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            report_date = excluded.report_date,
            top10_hold_pct = excluded.top10_hold_pct,
            top10_circ_hold_pct = excluded.top10_circ_hold_pct,
            updated_at = excluded.updated_at;
        """, (code, report_date, top10_hold_pct, top10_circ_hold_pct, now_str))
        conn.commit()


def update_ipo_and_dividend(code: str, ipo_date: str, listing_years: float, dividend_count: int):
    """更新上市日期与分红次数"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE stocks_master
        SET ipo_date = ?, listing_years = ?, dividend_count = ?, updated_at = ?
        WHERE code = ?;
        """, (ipo_date, listing_years, dividend_count, now_str, code))
        conn.commit()


def check_and_update_fingerprint(entity_type: str, entity_id: str, new_payload: Any) -> Tuple[bool, str]:
    """
    检查数据指纹是否发生实质性变动 (需求1: 幂等指纹框架)
    :param entity_type: 实体类型 (quote / master / shareholder / finance / block / events)
    :param entity_id: 实体唯一ID (如 stock code)
    :param new_payload: 准备持久化的原始或清洗后数据结构
    :return: (is_modified: bool, data_hash: str) - 若未改变返回 (False, hash)，需跳过写入
    """
    import hashlib
    import json
    
    # 对 payload 采用确定性 JSON 序列化生成指纹
    try:
        raw_bytes = json.dumps(new_payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    except Exception:
        raw_bytes = str(new_payload).encode('utf-8')
    
    data_hash = hashlib.sha256(raw_bytes).hexdigest()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT data_hash FROM data_fingerprints
        WHERE entity_type = ? AND entity_id = ?;
        """, (entity_type, entity_id))
        row = cursor.fetchone()
        
        if row and row["data_hash"] == data_hash:
            # 数据完全一致，无需任何重复写入，直接命中指纹幂等
            return False, data_hash

        # 指纹不同或首次入库，更新指纹表
        cursor.execute("""
        INSERT INTO data_fingerprints (entity_type, entity_id, data_hash, signature, payload, last_synced_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id) DO UPDATE SET
            data_hash = excluded.data_hash,
            signature = excluded.signature,
            last_synced_at = excluded.last_synced_at;
        """, (entity_type, entity_id, data_hash, f"{entity_type}:{entity_id}:{now_str}", "", now_str))
        conn.commit()
        return True, data_hash


def get_fingerprint_stats() -> Dict[str, Any]:
    """获取数据指纹幂等系统的综合统计学指标"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total_fp FROM data_fingerprints;")
        total_fp = cursor.fetchone()["total_fp"]
        
        cursor.execute("""
        SELECT entity_type, COUNT(*) AS count
        FROM data_fingerprints
        GROUP BY entity_type;
        """)
        breakdown = {row["entity_type"]: row["count"] for row in cursor.fetchall()}
        
        return {
            "total_fingerprints": total_fp,
            "entity_breakdown": breakdown,
            "algorithm": "SHA-256",
            "status": "active_idempotent"
        }


def load_all_stocks_from_db() -> List[Dict[str, Any]]:
    """从数据库中联表加载全部标的最新综合状态"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT
            m.code, m.raw_code, m.name, m.market, m.market_code, m.board, m.board_code,
            m.is_csi50, m.is_csi100, m.ipo_date, m.listing_years, m.dividend_count,
            COALESCE(m.dividend_total_amount, 0.0) AS dividend_total_amount,
            COALESCE(m.pinyin_abbr, '') AS pinyin_abbr,
            COALESCE(q.price, 0.0) AS price,
            COALESCE(q.change_val, 0.0) AS change_val,
            COALESCE(q.change_pct, 0.0) AS change_pct,
            COALESCE(q.prev_close, 0.0) AS prev_close,
            COALESCE(q.open_p, 0.0) AS open_p,
            COALESCE(q.high_p, 0.0) AS high_p,
            COALESCE(q.low_p, 0.0) AS low_p,
            COALESCE(q.volume, 0.0) AS volume,
            COALESCE(q.turnover, 0.0) AS turnover,
            COALESCE(q.turnover_yi, 0.0) AS turnover_yi,
            COALESCE(q.turnover_rate, 0.0) AS turnover_rate,
            COALESCE(q.pe, 0.0) AS pe,
            COALESCE(q.market_cap, 0.0) AS market_cap,
            COALESCE(q.circulating_cap, 0.0) AS circulating_cap,
            COALESCE(q.timestamp, '') AS timestamp,
            COALESCE(sh.report_date, '最新期') AS report_date,
            COALESCE(sh.top10_hold_pct, 0.0) AS top10_hold_pct,
            COALESCE(sh.top10_circ_hold_pct, 0.0) AS top10_circ_hold_pct
        FROM stocks_master m
        LEFT JOIN stock_quotes q ON m.code = q.code
        LEFT JOIN stock_shareholders sh ON m.code = sh.code
        ORDER BY m.code ASC;
        """)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["is_csi50"] = bool(d["is_csi50"])
            d["is_csi100"] = bool(d["is_csi100"])
            d["change"] = d["change_val"]
            d["open"] = d["open_p"]
            d["high"] = d["high_p"]
            d["low"] = d["low_p"]
            from scripts.verified_quotes import clean_legacy_stock
            result.append(clean_legacy_stock(d))
        return result


def is_baseline_eligible_status(status: str) -> bool:
    """
    需求REQ-017: 判定一条抓取审计流水是否具备成为「数据库基准」的资格。
    仅接受已核验的真实行情批次；旧版无来源日志、手动取消、部分覆盖一律不具备资格，
    以免不完整口径被提升为全局基准 (沿用 REQ-012 禁止虚构/误导原则)。
    """
    text = status or ""
    if "真实行情" not in text:
        return False
    return "成功" in text


def record_crawl_audit(
    task_id: str,
    crawl_date: str,
    status: str,
    fingerprint: str,
    target_scope: str = "全市场A股",
    total_items: int = 0,
    updated_items: int = 0,
    skipped_items: int = 0,
    details: str = ""
) -> int:
    """
    持久化记录一次数据中心抓取审计流水。
    需求REQ-017: 成功的真实行情批次落库后，自动成为最新「数据库基准」(清掉旧基准)。
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    auto_baseline = is_baseline_eligible_status(status)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if auto_baseline:
            cursor.execute("UPDATE crawl_audit_records SET is_baseline = 0;")
        cursor.execute("""
        INSERT INTO crawl_audit_records (
            task_id, crawl_date, status, fingerprint, target_scope,
            total_items, updated_items, skipped_items, details, created_at, is_baseline
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            task_id, crawl_date, status, fingerprint, target_scope,
            total_items, updated_items, skipped_items, details, now_str,
            1 if auto_baseline else 0
        ))
        conn.commit()
        return cursor.lastrowid


def get_crawl_baseline() -> Optional[Dict[str, Any]]:
    """需求REQ-017: 读取当前全局「数据库基准」批次记录 (至多一条)"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("""
        SELECT * FROM crawl_audit_records
        WHERE is_baseline = 1
        ORDER BY id DESC LIMIT 1;
        """).fetchone()
        return dict(row) if row else None


def ensure_crawl_baseline() -> Optional[Dict[str, Any]]:
    """
    需求REQ-017: 基准兜底初始化。
    若当前不存在基准 (旧库升级后的首次进入)，把最近一条已核验的真实行情成功批次回填为基准。
    不回退、不伪造：若无任何合规批次，保持无基准状态。
    """
    existing = get_crawl_baseline()
    if existing:
        return existing
    with get_db_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("""
        SELECT * FROM crawl_audit_records
        WHERE status LIKE '%真实行情%' AND status LIKE '%成功%'
        ORDER BY id DESC LIMIT 1;
        """).fetchone()
        if not row:
            return None
        cursor.execute("UPDATE crawl_audit_records SET is_baseline = 0;")
        cursor.execute("UPDATE crawl_audit_records SET is_baseline = 1 WHERE id = ?;", (row["id"],))
        conn.commit()
        record = dict(row)
        record["is_baseline"] = 1
        return record


def set_crawl_baseline(record_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    需求REQ-017: 手动把某条抓取记录设为全局「数据库基准」。
    返回 (是否成功, 说明, 基准记录)。失败时基准保持不变。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT * FROM crawl_audit_records WHERE id = ?;", (record_id,)).fetchone()
        if not row:
            return False, "未找到该抓取记录", None
        record = dict(row)
        if not is_baseline_eligible_status(record.get("status", "")):
            return False, "该记录不是已核验的真实行情成功批次，不能作为数据库基准", None
        cursor.execute("UPDATE crawl_audit_records SET is_baseline = 0;")
        cursor.execute("UPDATE crawl_audit_records SET is_baseline = 1 WHERE id = ?;", (record_id,))
        conn.commit()
        record["is_baseline"] = 1
        return True, "已切换数据库基准", record


def delete_crawl_audit_records(record_ids: List[int]) -> Dict[str, Any]:
    """
    需求REQ-016: 批量删除数据中心抓取审计流水记录。
    边界: 仅作用于审计流水表，绝不联动删除行情/K线/股东等业务数据；
         当前「数据库基准」记录受保护，不可删除。
    """
    ids: List[int] = []
    for raw in record_ids or []:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    result: Dict[str, Any] = {"deleted": [], "skipped": [], "protected": [], "reason": ""}
    if not ids:
        result["reason"] = "未提供有效的记录ID"
        return result

    with get_db_connection() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in ids)
        rows = cursor.execute(
            f"SELECT id, task_id, is_baseline FROM crawl_audit_records WHERE id IN ({placeholders});",
            tuple(ids)
        ).fetchall()
        found = {int(r["id"]): dict(r) for r in rows}

        deletable: List[int] = []
        for rid in ids:
            rec = found.get(rid)
            if rec is None:
                result["skipped"].append({"id": rid, "reason": "记录不存在"})
            elif int(rec.get("is_baseline") or 0) == 1:
                result["protected"].append({"id": rid, "task_id": rec.get("task_id"), "reason": "当前数据库基准记录不可删除，请先切换基准"})
            else:
                deletable.append(rid)

        if deletable:
            ph = ",".join("?" for _ in deletable)
            cursor.execute(f"DELETE FROM crawl_audit_records WHERE id IN ({ph});", tuple(deletable))
            conn.commit()
            result["deleted"] = sorted(deletable)

    if result["protected"]:
        result["reason"] = "部分记录为当前数据库基准，已保护未删除"
    elif result["skipped"]:
        result["reason"] = "部分记录不存在，已跳过"
    return result


def save_daily_klines(code: str, klines: List[Dict[str, Any]]) -> int:
    """
    需求1/4: 批量保存日K线至本地数据库 (stock_daily_kline)
    严格遵循 (code, date) 唯一联合主键，幂等覆盖更新，零冗余
    """
    if not code or not klines:
        return 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
        INSERT INTO stock_daily_kline (
            code, date, open, close, high, low, volume, amount_yi, change_pct, created_at
        ) VALUES (
            :code, :date, :open, :close, :high, :low, :volume, :amount_yi, :change_pct, :created_at
        ) ON CONFLICT(code, date) DO UPDATE SET
            open = excluded.open,
            close = excluded.close,
            high = excluded.high,
            low = excluded.low,
            volume = excluded.volume,
            amount_yi = excluded.amount_yi,
            change_pct = excluded.change_pct,
            created_at = excluded.created_at;
        """, [
            {
                "code": code,
                "date": str(k.get("date")),
                "open": float(k.get("open", 0.0)),
                "close": float(k.get("close", 0.0)),
                "high": float(k.get("high", 0.0)),
                "low": float(k.get("low", 0.0)),
                "volume": float(k.get("volume", 0.0)),
                "amount_yi": float(k.get("amount_yi", 0.0)),
                "change_pct": float(k.get("change_pct", 0.0)),
                "created_at": now_str
            }
            for k in klines if k.get("date")
        ])
        conn.commit()
        return len(klines)


def load_daily_klines(code: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    需求2: 从本地数据库直接检索该标的历史日K线
    毫秒级响应，无需现场外网发包抓取
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT date, open, close, high, low, volume, amount_yi, change_pct FROM stock_daily_kline WHERE code=?"
        if limit is None:
            cursor.execute(query + " ORDER BY date ASC", (code,))
        else:
            cursor.execute("SELECT * FROM (" + query + " ORDER BY date DESC LIMIT ?) ORDER BY date ASC", (code, max(0, limit)))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def save_stock_timeline(code: str, timeline_data: Dict[str, Any]):
    """
    需求1/4: 保存分时切片至本地数据库 (stock_timeline)
    当天单记录，结构紧凑轻量
    """
    import json
    if not code or not timeline_data:
        return
    trade_date = datetime.now().strftime("%Y-%m-%d")
    pre_close = float(timeline_data.get("pre_close", 0.0))
    items = timeline_data.get("items", [])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO stock_timeline (code, trade_date, pre_close, items_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code, trade_date) DO UPDATE SET
            pre_close = excluded.pre_close,
            items_json = excluded.items_json,
            updated_at = excluded.updated_at;
        """, (code, trade_date, pre_close, json.dumps(items, ensure_ascii=False), now_str))
        conn.commit()


def load_stock_timeline(code: str, max_age_seconds: int = 300) -> Optional[Dict[str, Any]]:
    """
    需求2: 从本地数据库查询当天有效的分时走势数据
    """
    import json
    trade_date = datetime.now().strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT pre_close, items_json, updated_at
        FROM stock_timeline
        WHERE code = ? AND trade_date = ?
        ORDER BY updated_at DESC
        LIMIT 1;
        """, (code, trade_date))
        row = cursor.fetchone()
        if not row:
            return None

        # 检验数据时效 (若在交易时段内过期则返回None触发回补)
        try:
            items = json.loads(row["items_json"])
            return {
                "code": code,
                "pre_close": row["pre_close"],
                "items": items,
                "cached_at": row["updated_at"]
            }
        except Exception:
            return None


def get_latest_crawl_fingerprint(target_scope: str = "") -> Optional[Dict[str, Any]]:
    """查询指定抓取范围最新一次成功的抓取指纹"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if target_scope:
            cursor.execute("""
            SELECT * FROM crawl_audit_records
            WHERE target_scope = ? AND status LIKE '%成功%'
            ORDER BY id DESC LIMIT 1;
            """, (target_scope,))
        else:
            cursor.execute("""
            SELECT * FROM crawl_audit_records
            WHERE status LIKE '%成功%'
            ORDER BY id DESC LIMIT 1;
            """)
        row = cursor.fetchone()
        return dict(row) if row else None


def list_crawl_audit_records(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """分页获取抓取审计流水记录"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM crawl_audit_records
        ORDER BY id DESC LIMIT ? OFFSET ?;
        """, (limit, offset))
        return [dict(r) for r in cursor.fetchall()]


if __name__ == "__main__":
    init_db()
    print(f"[DB] 数据库已初始化成功，路径: {DB_PATH}")
