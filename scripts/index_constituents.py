#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
需求 REQ-009 / 成分股筛选：指数成分股真实名单抓取器（可核验来源，零三方依赖）。

为什么需要这个脚本（真实缺口）：
    Web 端「成分股：中证50 / 中证100」筛选项此前恒返回 0 行，链路三处断点：
      ① `config/constituents.json` 只有手写名单，**没有 `verified_source` / `as_of`** →
         `scripts/stock_web_server.py` 的加载门直接跳过，`csi50_set/csi100_set` 恒为空集；
      ② `scripts/verified_quotes.py::clean_legacy_stock` 把 `is_csi50/is_csi100` 一律置 None，
         于是即使库里已有名单，内存里也全被清空；
      ③ 没有把名单写回 SQLite 的**可复现入口**（原先只有一次性 `populate_db.py` 全量灌库）。
    本脚本负责第 ① 与第 ③ 步：从**真实可核验的公开接口**抓取名单并落盘 + 写回数据库，
    并强制记录来源与数据日期，使「名单是否已核验」变成可判定的物理事实。

数据来源（真实 HTTP，非硬编码）：
    东方财富数据中心 · 指数成分报表
    `https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_INDEX_COMPONENT`
    `filter=(INDEX_CODE="<指数代码>")`
    实测（2026-10-01）：000300 → 300 只；930050 → 50 只；000903 → 100 只。

口径诚实性约束：
    - 抓到多少就写多少，**绝不补造**；只数与预期不符时打印警告但如实落盘实际条数。
    - 落盘必带 `verified_source`（含 URL）与 `as_of`（本次抓取日期），否则加载门会拒绝。
    - 只写 `stocks_master` 的 `is_csi50/is_csi100` 两个标记位，**不动**任何行情/股东/日线数据；
      `--dry-run` 只抓取与打印，零写库。

用法：
    python3 scripts/index_constituents.py --fetch                # 抓取并写 config/constituents.json
    python3 scripts/index_constituents.py --sync-db              # 按 config 名单写回 SQLite 标记位
    python3 scripts/index_constituents.py --fetch --sync-db      # 一步到位（推荐）
    python3 scripts/index_constituents.py --dry-run --fetch      # 只抓取与打印，不落盘
    python3 scripts/index_constituents.py --show                 # 只看当前 config 状态
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CONFIG_PATH = os.path.join(BASE_DIR, "config", "constituents.json")
DB_PATH = os.environ.get("DSH_STOCK_DB", os.path.join(BASE_DIR, "data", "stock_database.db"))

DC_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_NAME = "RPT_INDEX_COMPONENT"
PAGE_SIZE = 500
TIMEOUT = 15

# 产品三个档位 → 真实指数代码 + 官方名称 + 预期只数（用于「如实告警」而非「补造」）
CATALOG = {
    "csi50":  {"index_code": "930050", "index_name": "中证A50",  "expect": 50},
    "csi100": {"index_code": "000903", "index_name": "中证A100", "expect": 100},
    "csi300": {"index_code": "000300", "index_name": "沪深300",  "expect": 300},
}


def _http_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://data.eastmoney.com/",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    if not payload.get("success"):
        # 上游明确报错（未返回 result）时必须是失败，不得当成"空名单"静默通过
        raise RuntimeError(f"上游返回失败: {payload.get('message') or payload}")
    return payload


def fetch_index_members(index_code: str) -> list[str]:
    """分页拉取某指数的全部成分股，返回 6 位代码列表（保持来源顺序）。"""
    codes: list[str] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({
            "reportName": REPORT_NAME,
            "columns": "ALL",
            "filter": f'(INDEX_CODE="{index_code}")',
            "pageNumber": page,
            "pageSize": PAGE_SIZE,
            "source": "WEB",
            "client": "WEB",
        })
        payload = _http_json(f"{DC_URL}?{query}")
        result = payload.get("result") or {}
        rows = result.get("data") or []
        if not rows:
            break
        for row in rows:
            code = str(row.get("SECURITY_CODE") or "").strip()
            if len(code) == 6 and code.isdigit() and code not in codes:
                codes.append(code)
        if len(rows) < PAGE_SIZE or len(codes) >= int(result.get("count") or 0):
            break
        page += 1
    return codes


def to_prefixed(code: str) -> str:
    """6 位代码 → 带市场前缀（沪 sh / 深 sz / 北 bj），与工程内其它名单口径一致。"""
    if code.startswith(("60", "68", "51", "58", "90")):
        return "sh" + code
    if code.startswith(("00", "30", "12", "15", "16", "18", "39")):
        return "sz" + code
    if code.startswith(("43", "83", "87", "92")):
        return "bj" + code
    return "sh" + code


def build_config(today: str) -> dict:
    data: dict = {}
    sources: list[str] = []
    for key, meta in CATALOG.items():
        codes = fetch_index_members(meta["index_code"])
        prefixed = [to_prefixed(c) for c in codes]
        data[key] = prefixed
        sources.append(f'{meta["index_name"]}({meta["index_code"]})')
        flag = "✅" if len(prefixed) == meta["expect"] else "⚠️"
        print(f"  {flag} {key:7s} {meta['index_name']}({meta['index_code']}): "
              f"抓到 {len(prefixed)} 只（预期 {meta['expect']}）")
    config = {
        "_说明": "指数成分股真实名单。由 scripts/index_constituents.py 从公开可核验接口抓取，"
                 "禁止手工填写；手工编辑后必须重跑本脚本以免来源与名单不一致。",
        "verified_source": f"东方财富数据中心 {REPORT_NAME} · " + " + ".join(sources),
        "verified_source_url": f"{DC_URL}?reportName={REPORT_NAME}&filter=(INDEX_CODE=\"<指数代码>\")",
        "as_of": today,
        **data,
    }
    return config


def sync_db(config: dict, dry_run: bool = False) -> dict:
    """把名单写回 stocks_master 的两个标记位；只动这两列。"""
    csi50 = set(config.get("csi50") or [])
    csi100 = set(config.get("csi100") or [])
    csi300 = set(config.get("csi300") or [])
    master = csi100 | csi300  # 更宽的口径用于提示（不写库）
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    try:
        total = conn.execute("SELECT COUNT(*) FROM stocks_master").fetchone()[0]
        stats = {}
        for col, want in (("is_csi50", csi50), ("is_csi100", csi100)):
            before = conn.execute(f"SELECT COUNT(*) FROM stocks_master WHERE {col}=1").fetchone()[0]
            if dry_run:
                after = before
            else:
                conn.execute(f"UPDATE stocks_master SET {col}=0")
                for code in sorted(want):
                    conn.execute(f"UPDATE stocks_master SET {col}=1 WHERE code=?", (code,))
                conn.commit()
                after = conn.execute(f"SELECT COUNT(*) FROM stocks_master WHERE {col}=1").fetchone()[0]
            missing = len(want) - after if not dry_run else None
            stats[col] = {"before": before, "after": after, "wanted": len(want),
                          "not_in_master": missing}
        stats["master_rows"] = total
        stats["csi100_or_csi300_union"] = len(master)
    finally:
        conn.close()
    return stats


def show() -> int:
    print(f"配置: {CONFIG_PATH}")
    if not os.path.exists(CONFIG_PATH):
        print("  ❌ 文件不存在")
        return 1
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    verified = bool(config.get("verified_source")) and bool(config.get("as_of"))
    print(f"  已核验(verified_source + as_of 齐备): {verified}")
    print(f"  来源: {config.get('verified_source') or '（缺失）'}")
    print(f"  数据日期 as_of: {config.get('as_of') or '（缺失）'}")
    for key in ("csi50", "csi100", "csi300"):
        print(f"  {key}: {len(config.get(key) or [])} 只")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        for col in ("is_csi50", "is_csi100"):
            n = conn.execute(f"SELECT COUNT(*) FROM stocks_master WHERE {col}=1").fetchone()[0]
            print(f"  DB {col}=1: {n} 行")
    finally:
        conn.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="指数成分股真实名单抓取与写回（可核验来源）")
    parser.add_argument("--fetch", action="store_true", help="从公开接口抓取并写入 config/constituents.json")
    parser.add_argument("--sync-db", action="store_true", help="按 config 名单写回 SQLite 标记位")
    parser.add_argument("--dry-run", action="store_true", help="只抓取/只演算，不落盘、不写库")
    parser.add_argument("--show", action="store_true", help="只显示当前配置与数据库状态")
    args = parser.parse_args(argv)

    if args.show or not (args.fetch or args.sync_db):
        return show()

    if args.fetch:
        print(f"[抓取] 来源: {DC_URL} reportName={REPORT_NAME}")
        config = build_config(date.today().isoformat())
        if args.dry_run:
            print("[dry-run] 未写入 config 文件")
        else:
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(f"[落盘] {CONFIG_PATH}")
    else:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            config = json.load(handle)

    if args.sync_db:
        stats = sync_db(config, dry_run=args.dry_run)
        print(f"[写库] {DB_PATH} 标的底册 {stats['master_rows']} 行")
        for col in ("is_csi50", "is_csi100"):
            item = stats[col]
            note = "" if item["not_in_master"] in (0, None) else \
                f" ⚠️ 名单中有 {item['not_in_master']} 只不在底册（未获行情/已退市，如实保留名单）"
            print(f"  {col}: {item['before']} → {item['after']} 行"
                  f"（名单 {item['wanted']} 只，dry_run={args.dry_run}）{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
