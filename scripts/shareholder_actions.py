"""按公告日期汇总实际股东增减持；不从持股比例或随机种子推断。"""
import argparse
import json
import math
import threading
import time
import urllib.parse
from datetime import date, datetime, timedelta

from scripts import stock_db
from scripts.market_history import canonical_code, request_json

SOURCE_URL = "https://data.eastmoney.com/executive/gdzjc.html"
API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_lock = threading.Lock()
_memo = {}


def parse_record(item, start, end):
    direction = {"增持": "increase", "减持": "decrease"}.get(item.get("DIRECTION"))
    name = str(item.get("HOLDER_NAME") or "").strip()
    notice = str(item.get("NOTICE_DATE") or "")[:10]
    trade_end = str(item.get("END_DATE") or "")[:10]
    quantity = float(item.get("CHANGE_NUM") or 0)
    # 无实际数量、未来计划不计入；公告窗与实际变动日期分别保留。
    if not direction or not name or not math.isfinite(quantity) or quantity <= 0:
        return None
    if not start <= notice <= end or not trade_end or trade_end > end:
        return None
    date.fromisoformat(notice)
    date.fromisoformat(trade_end)
    return {"code": canonical_code(item["SECURITY_CODE"]), "name": name,
            "direction": direction, "notice_date": notice, "start_date": str(item.get("START_DATE") or "")[:10],
            "end_date": trade_end, "quantity_wan": quantity, "source_url": SOURCE_URL}


def fetch_actions(days=365, *, transport=None, today=None):
    if days not in (90, 365):
        raise ValueError("股东统计窗口仅支持90天或365天")
    today = today or date.today()
    start, end = (today - timedelta(days=days - 1)).isoformat(), today.isoformat()
    transport = transport or request_json
    records = {}
    complete = False
    error = None
    raw_count = 0
    expected_count = None
    try:
        for page in range(1, 101):
            params = {"reportName": "RPT_SHARE_HOLDER_INCREASE", "columns": "ALL", "pageNumber": page,
                      "pageSize": 500, "sortColumns": "NOTICE_DATE,SECURITY_CODE,HOLDER_NAME,END_DATE", "sortTypes": "-1,1,1,-1",
                      "filter": f"(NOTICE_DATE>='{start}')(NOTICE_DATE<='{end}')", "source": "WEB", "client": "WEB"}
            payload = transport(API_URL + "?" + urllib.parse.urlencode(params))
            if not isinstance(payload, dict):
                raise ValueError("股东来源响应格式异常")
            result = payload.get("result") or {}
            if not payload.get("success") or not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise ValueError("股东来源未返回有效数据")
            total = int(result.get("count", -1))
            pages = int(result.get("pages", 0))
            if expected_count is not None and total != expected_count:
                raise ValueError("抓取期间来源记录数变化，请稍后刷新")
            expected_count = total
            raw_count += len(result["data"])
            for item in result["data"]:
                record = parse_record(item, start, end)
                if record:
                    key = tuple(record[k] for k in ("code", "name", "direction", "notice_date", "start_date", "end_date", "quantity_wan"))
                    records[key] = record
            if page >= pages:
                if total < 0 or raw_count != total:
                    raise ValueError("股东分页条数校验失败")
                complete = True
                break
        if not complete:
            error = "股东历史达到分页保护上限"
    except (ValueError, TypeError, KeyError, OSError) as exc:
        error = str(exc)
    grouped = {}
    for record in records.values():
        grouped.setdefault(record["code"], []).append(record)
    return {"schema_version": 1, "days": days, "window_start": start, "window_end": end,
            "basis": "公告日期内披露且已有实际数量的股东增减持", "source": "东方财富Choice",
            "source_url": SOURCE_URL, "complete": complete,
            "status": "available" if complete else "partial" if grouped else "unavailable",
            "fetched_epoch": time.time(), "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(records), "error": error, "records": grouped}


def get_actions(days=365, *, refresh=False, fetcher=None):
    days = int(days)
    if days not in (90, 365):
        raise ValueError("股东统计窗口仅支持90天或365天")
    with _lock:
        cached = _memo.get(days)
        if cached and not refresh and time.time() - cached[0] < 300:
            return cached[1]
        with stock_db.get_db_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS verified_shareholder_actions (days INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            row = conn.execute("SELECT payload FROM verified_shareholder_actions WHERE days=?", (days,)).fetchone()
        old = json.loads(row[0]) if row else None
        if old and not refresh and time.time() - old.get("fetched_epoch", 0) < 3600 and old["window_end"] == date.today().isoformat():
            _memo[days] = (time.time(), old)
            return old
        result = (fetcher or fetch_actions)(days)
        if result["complete"]:
            with stock_db.get_db_connection() as conn:
                conn.execute("INSERT INTO verified_shareholder_actions(days,payload) VALUES(?,?) ON CONFLICT(days) DO UPDATE SET payload=excluded.payload",
                             (days, json.dumps(result, ensure_ascii=False, allow_nan=False)))
        elif old and old.get("complete"):
            result = dict(old, status="stale", error=result["error"])
        _memo[days] = (time.time(), result)
        return result


def enrich_actions(stock, snapshot):
    stock["code"] = canonical_code(stock["code"])
    records = snapshot["records"].get(stock["code"], [])
    for direction, key in (("increase", "increase_holders"), ("decrease", "decrease_holders")):
        stock[key] = sorted({r["name"] for r in records if r["direction"] == direction})
    stock["shareholder_actions"] = records
    stock["shareholder_action_status"] = snapshot["status"]
    stock["shareholder_action_meta"] = {k: v for k, v in snapshot.items() if k != "records"}
    return stock


def main():
    parser = argparse.ArgumentParser(description="真实股东增减持记录（按公告日期统计）")
    parser.add_argument("--code")
    parser.add_argument("--days", type=int, choices=(90, 365), default=365)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    value = get_actions(args.days, refresh=args.refresh)
    output = enrich_actions({"code": canonical_code(args.code)}, value) if args.code else {k:v for k,v in value.items() if k != "records"}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if value["status"] == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
