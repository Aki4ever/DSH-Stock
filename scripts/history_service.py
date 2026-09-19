"""按证券独立刷新、原子缓存、显式过期状态；旧无来源表永不参与。"""
import argparse
import json
import threading
import time

from scripts import stock_db
from scripts.market_history import canonical_code, fetch_daily_history, SCHEMA_VERSION

_locks = {}
_guard = threading.Lock()
_failures = {}


def _load(code):
    with stock_db.get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS verified_daily_history (code TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        row = conn.execute("SELECT payload FROM verified_daily_history WHERE code=?", (code,)).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row[0])
        if isinstance(value, dict) and value.get("code") == code and value.get("schema_version") == SCHEMA_VERSION:
            return value
    except (ValueError, TypeError):
        pass
    return None


def get_daily_history(code, *, refresh=False, max_age=300, fetcher=None):
    code = canonical_code(code)
    with _guard:
        lock = _locks.setdefault(code, threading.Lock())
    with lock:
        cached = _load(code)
        if not refresh and cached and time.time() - cached.get("fetched_epoch", 0) < max_age:
            return dict(cached, cache="hit")
        failed = _failures.get(code)
        if not refresh and failed and time.time() - failed[0] < 30:
            return failed[1]
        result = (fetcher or fetch_daily_history)(code)
        if result.get("code") != code:
            raise ValueError("行情证券标识与请求不一致")
        # 完整缓存不会被抓取一半的失败结果覆盖。
        if cached and cached.get("provider_history_complete") and not result.get("provider_history_complete"):
            result = dict(cached, status="stale", cache="stale", error=result.get("error") or "刷新未完成")
            _failures[code] = (time.time(), result)
            return result
        if result.get("bars"):
            with stock_db.get_db_connection() as conn:
                conn.execute("INSERT INTO verified_daily_history(code,payload) VALUES(?,?) ON CONFLICT(code) DO UPDATE SET payload=excluded.payload",
                             (code, json.dumps(result, ensure_ascii=False, allow_nan=False)))
        else:
            _failures[code] = (time.time(), result)
        return dict(result, cache="refreshed")


def main():
    parser = argparse.ArgumentParser(description="获取真实全历史日K线及覆盖状态（不复权）")
    parser.add_argument("code")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--include-bars", action="store_true")
    args = parser.parse_args()
    value = get_daily_history(args.code, refresh=args.refresh)
    print(json.dumps({k: v for k, v in value.items() if args.include_bars or k != "bars"}, ensure_ascii=False, indent=2))
    return 0 if value["status"] == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
