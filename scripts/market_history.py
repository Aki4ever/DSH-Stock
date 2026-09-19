"""可追溯的全历史日线。逐页回溯到来源尽头，不混入旧缓存或模拟数据。"""
import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

SCHEMA_VERSION = 1
PAGE_SIZE = 640
SOURCE = "腾讯证券"
SOURCE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def canonical_code(code):
    code = str(code).lower().strip()
    if re.fullmatch(r"(sh|sz|bj)\d{6}", code):
        return code
    if re.fullmatch(r"\d{6}", code):
        return ("sh" if code.startswith(("5", "6", "9")) else
                "bj" if code.startswith(("4", "8")) else "sz") + code
    raise ValueError("股票代码须为六位数字或带 sh/sz/bj 前缀")


def request_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.load(response)


def parse_bar(raw, today):
    day = date.fromisoformat(str(raw[0]))
    o, c, h, lo, vol = map(float, raw[1:6])
    if day > today or not all(math.isfinite(x) for x in (o, c, h, lo, vol)):
        raise ValueError("行情含未来日期或非有限数字")
    if min(o, c, h, lo) <= 0 or vol < 0 or h < max(o, c, lo) or lo > min(o, c, h):
        raise ValueError("行情价格或成交量校验失败")
    return {"date": day.isoformat(), "open": o, "close": c, "high": h, "low": lo,
            "volume": vol, "amount_yi": None, "change_pct": None}


def fetch_daily_history(code, *, transport=None, today=None, max_pages=64):
    """不复权日线；空的历史页才证明来源已穷尽。故障/页数保护返回 partial。"""
    code = canonical_code(code)
    transport = transport or request_json
    today = today or date.today()
    end = today
    bars = {}
    exhausted = False
    error = None
    pages = 0
    started = time.monotonic()
    for _ in range(max_pages):
        if time.monotonic() - started > 60:
            error = "本次历史抓取超时，覆盖尚未证实完整"
            break
        url = SOURCE_URL + "?" + urllib.parse.urlencode({"param": f"{code},day,,{end.isoformat()},{PAGE_SIZE},"})
        try:
            response = transport(url)
            if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
                raise ValueError("来源响应格式异常")
            if response.get("code", 0) != 0:
                raise ValueError("来源拒绝请求")
            # 必须命中请求的完整交易所代码，不接受第一个证券或其他代码。
            security = (response.get("data") or {}).get(code)
            if not isinstance(security, dict) or "day" not in security:
                raise ValueError("来源未返回对应证券的不复权行情")
            raw = security["day"]
            if not isinstance(raw, list):
                raise ValueError("来源行情格式异常")
            pages += 1
            if not raw:
                exhausted = True
                break
            page = [parse_bar(item, today) for item in raw]
            if any(item["date"] > end.isoformat() for item in page):
                raise ValueError("来源忽略分页日期，已停止以防重复历史")
            oldest = min(item["date"] for item in page)
            for item in page:
                bars[item["date"]] = item
            end = date.fromisoformat(oldest) - timedelta(days=1)
        except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
            error = str(exc)
            break
    if not exhausted and error is None:
        error = "达到分页保护上限，历史覆盖尚未证实完整"
    ordered = [bars[key] for key in sorted(bars)]
    for previous, current in zip(ordered, ordered[1:]):
        current["change_pct"] = round((current["close"] / previous["close"] - 1) * 100, 2)
    return {"code": code, "schema_version": SCHEMA_VERSION, "source": SOURCE,
            "source_url": SOURCE_URL, "adjustment": "none", "adjustment_label": "不复权",
            "status": "available" if exhausted and ordered else "partial" if ordered else "unavailable",
            "provider_history_complete": exhausted and bool(ordered),
            "coverage_start": ordered[0]["date"] if ordered else None,
            "coverage_end": ordered[-1]["date"] if ordered else None,
            "count": len(ordered), "pages": pages, "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "fetched_epoch": time.time(), "error": error, "bars": ordered}
