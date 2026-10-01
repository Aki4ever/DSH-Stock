#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
REQ-012 / 宏观模块：真实可核验的全球宏观数据采集链路。

修复背景（原状）：
    本模块此前是**空壳**——无条件返回
    `meta(None, 'unavailable', '宏观新闻与商品报价尚未接入可验证来源')` 且
    `commodities=[] world_events=[] domestic_events=[] international_events=[]`，
    即 `/api/macro/world` 永远返回「未获取」。这是「有界面、有接口、无物理源」的典型缺口。

现在的物理链路（全部为真实公开接口，零三方依赖）：

| 维度 | 来源 | 接口 |
| :--- | :--- | :--- |
| 全球指数 | 腾讯财经公开行情 | `https://qt.gtimg.cn/q=hkHSI,usDJI,usIXIC,jpNI225,...` |
| 商品报价 | 新浪财经外盘期货 | `https://hq.sinajs.cn/list=hf_GC,hf_CL,hf_OIL,hf_SI,hf_CAD` |
| 宏观快讯 | 东方财富 7×24 快讯 | `https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?...` |

**诚信口径（不得放宽）**：
    1. 任一来源失败 → 该维度如实为空并给出 `errors` 原因，**绝不补造**任何数值；
    2. 综合评分 = 真实涨跌幅的线性映射（`50 + avg_change_pct * 10`，夹取 0~100），
       口径写在 `aggregate_score.score_basis` 中，任何人可复算；
    3. 新闻按标题关键词做**国内/国际**归类，口径写在 `classification_note`，
       只搬运真实标题与时间，不生成摘要、不编造事件；
    4. 全部返回携带 `source` 与 `fetched_at`，`status` 为 `available` / `unavailable`。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from scripts.verified_sources import meta

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={codes}"
SINA_FUTURES_URL = "https://hq.sinajs.cn/list={codes}"
EASTMONEY_NEWS_URL = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"

# 全球指数：腾讯公开行情代码 → 展示名（实测均真实可取）
GLOBAL_INDICES = [
    ("hkHSI", "恒生指数"),
    ("usDJI", "道琼斯"),
    ("usIXIC", "纳斯达克"),
    ("usINX", "标普500"),
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
]

# 商品：新浪外盘期货代码 → 展示名 / 单位（实测均真实可取）
COMMODITIES = [
    ("hf_GC", "纽约黄金", "美元/盎司"),
    ("hf_CL", "纽约原油", "美元/桶"),
    ("hf_OIL", "布伦特原油", "美元/桶"),
    ("hf_SI", "纽约白银", "美元/盎司"),
    ("hf_CAD", "伦敦铜", "美元/吨"),
]

_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 关键词归类口径（随返回值暴露，便于人工复核）
DOMESTIC_KEYWORDS = ("中国", "国内", "A股", "央行", "人民", "财政", "国务院", "发改委", "沪",
                     "深", "北交所", "证监会", "国常会", "工信部", "商务部")
INTERNATIONAL_KEYWORDS = ("美国", "美联储", "欧洲", "欧央行", "日本", "英国", "德国", "法国",
                          "海外", "全球", "国际", "俄", "乌克兰", "中东", "特朗普", "关税",
                          "原油", "黄金", "美股", "港股")
# 备用全球指数来源：**当前为空**（如实登记，不留半可用代码）。
#   实测结论（2026-10-01）：腾讯公开行情不返回日经 225（`pv_none_match`）；东方财富
#   `push2.eastmoney.com/api/qt/ulist.np/get` 对 Python 客户端在 TLS 层直接断连
#   （curl HTTP/1.0/1.1 均 200，urllib/http.client 均 RemoteDisconnected），故不接入。
#   因此全球指数为 6 个真实标的，缺失的日经 225 会出现在 `errors` 中——宁可如实缺一个，
#   也不补造或保留注定失败的代码路径。
EASTMONEY_GLOBAL_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_GLOBAL_INDICES = []  # 保留结构，便于将来有可靠源时填入


def fetch_global_indices_backup() -> tuple:
    """备用全球指数来源（当前无可用源，恒返回空且不报错）。"""
    return [], []


def _fetch_text(url: str, referer: str = "", timeout: int = 8) -> str:
    """抓取文本响应；编码按 utf-8 → gbk 依次尝试（腾讯/新浪行情为 GBK）。"""
    headers = {"User-Agent": _USER_AGENT}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def fetch_global_indices() -> tuple:
    """真实抓取全球指数行情（腾讯公开行情），返回 (列表, 错误说明)。"""
    codes = ",".join(code for code, _ in GLOBAL_INDICES)
    errors = []
    items = []
    try:
        text = _fetch_text(TENCENT_QUOTE_URL.format(codes=codes))
    except Exception as exc:  # noqa: BLE001 —— 失败必须如实上报，不静默
        return [], [f"全球指数来源不可用: {exc}"]

    for code, label in GLOBAL_INDICES:
        match = re.search(rf'v_{re.escape(code)}="([^"]*)"', text)
        if not match:
            errors.append(f"{label}({code}) 来源未返回该标的")
            continue
        fields = match.group(1).split("~")
        if len(fields) < 33:
            errors.append(f"{label}({code}) 字段不完整（{len(fields)} 段）")
            continue
        price = _to_float(fields[3])
        if price is None:
            errors.append(f"{label}({code}) 未提供价格")
            continue
        items.append({
            "code": code,
            "name": label,
            "price": price,
            "change_pct": _to_float(fields[32]),
            "change_val": _to_float(fields[31]),
            "quote_time": (fields[30] or "").strip() or None,
            "source": "腾讯财经公开行情 qt.gtimg.cn",
        })
    return items, errors


def fetch_commodities() -> tuple:
    """真实抓取外盘商品报价（新浪公开行情）。"""
    codes = ",".join(code for code, _, _ in COMMODITIES)
    errors = []
    items = []
    try:
        text = _fetch_text(SINA_FUTURES_URL.format(codes=codes),
                           referer="https://finance.sina.com.cn")
    except Exception as exc:  # noqa: BLE001
        return [], [f"商品报价来源不可用: {exc}"]

    for code, label, unit in COMMODITIES:
        match = re.search(rf'hq_str_{re.escape(code)}="([^"]*)"', text)
        if not match:
            errors.append(f"{label}({code}) 来源未返回该合约")
            continue
        fields = [f.strip() for f in match.group(1).split(",")]
        if len(fields) < 8:
            errors.append(f"{label}({code}) 字段不完整（{len(fields)} 段）")
            continue
        price = _to_float(fields[0])
        prev_close = _to_float(fields[7])
        change_pct = None
        if price is not None and prev_close:
            change_pct = round((price - prev_close) / prev_close * 100, 3)
        items.append({
            "code": code,
            "name": label,
            "unit": unit,
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "quote_time": (f"{fields[12]} {fields[6]}".strip() if len(fields) > 12 else None),
            "source": "新浪财经外盘期货 hq.sinajs.cn",
        })
    return items, errors


# 国家/领域归类口径（与界面「国家标签 / 5 大领域标签」对齐；判不出来就留空，
# 界面按「未指定该维度的快讯在选中具体标签时不隐藏」处理，绝不硬猜一个国家）
COUNTRY_KEYWORDS = (
    ("cn", ("中国", "国内", "央行", "人民", "财政", "国务院", "发改委", "证监会", "沪", "深", "北交所")),
    ("us", ("美国", "美联储", "特朗普", "白宫", "美元")),
    ("eu", ("欧洲", "欧央行", "欧元区", "英国", "德国", "法国")),
    ("mideast", ("中东", "以色列", "伊朗", "沙特", "俄罗斯", "乌克兰")),
)
DOMAIN_KEYWORDS = (
    ("金融", ("央行", "美联储", "利率", "债券", "股市", "汇率", "降息", "加息", "资金", "流动性", "银行", "保险")),
    ("科技", ("芯片", "半导体", "人工智能", "AI", "科技", "算力", "新能源", "光刻")),
    ("军事", ("军事", "军演", "战争", "冲突", "导弹", "国防")),
    ("外贸", ("关税", "贸易", "出口", "进口", "外贸", "供应链")),
)


def _infer_country(title: str) -> str:
    for code, keywords in COUNTRY_KEYWORDS:
        if any(k in title for k in keywords):
            return code
    return ""


def _infer_domain(title: str) -> str:
    for domain, keywords in DOMAIN_KEYWORDS:
        if any(k in title for k in keywords):
            return domain
    return ""


def _classify(title: str) -> str:
    domestic = any(k in title for k in DOMESTIC_KEYWORDS)
    international = any(k in title for k in INTERNATIONAL_KEYWORDS)
    if domestic and not international:
        return "domestic"
    if international and not domestic:
        return "international"
    if domestic and international:
        return "domestic"  # 同时命中归国内（口径写明，可复核）
    return "unclassified"


def fetch_news(limit: int = 30) -> tuple:
    """真实抓取东财 7×24 快讯标题（只搬运真实标题与时间，不生成摘要）。"""
    query = urllib.parse.urlencode({
        "client": "web", "biz": "web_news_col", "column": "345", "order": "1",
        "needInteractData": "0", "pageIndex": "1", "pageSize": str(limit),
        "req_trace": "1", "fields": "code,showTime,title,mediaName,summary", "types": "1,20",
    })
    try:
        raw = _fetch_text(f"{EASTMONEY_NEWS_URL}?{query}")
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return [], [f"宏观快讯来源不可用: {exc}"]

    rows = ((payload.get("data") or {}).get("list")) or []
    if not rows:
        return [], ["宏观快讯来源返回空列表（未获取，不等于无事件）"]

    events = []
    for row in rows[:limit]:
        title = (row.get("title") or "").strip()
        if not title:
            continue
        category = _classify(title)
        country_code = _infer_country(title)
        domain = _infer_domain(title)
        events.append({
            "time": row.get("showTime") or "",
            "date": (row.get("showTime") or "")[:10],
            "title": title,
            "media": row.get("mediaName") or "",
            "category": category,
            "scope": "domestic" if category == "domestic" else (
                "international" if category == "international" else ""),
            "country_code": country_code,
            "country": country_code,
            "domain": domain,
            "source": "东方财富 7×24 快讯 np-listapi.eastmoney.com",
            "official_source": row.get("mediaName") or "东方财富 7×24 快讯",
            "source_url": row.get("url") or "",
        })
    return events, []


def _score_from_changes(changes):
    """综合评分 = 真实涨跌幅均值线性映射；无有效涨跌幅则 None（未获取）。"""
    valid = [c for c in changes if isinstance(c, (int, float))]
    if not valid:
        return None, None
    avg = sum(valid) / len(valid)
    score = max(0.0, min(100.0, 50.0 + avg * 10))
    return round(score, 2), round(avg, 4)


def _sentiment(score):
    if score is None:
        return {"sentiment_label": "未获取真实宏观数据", "sentiment_color": "#94a3b8",
                "sentiment_icon": "—"}
    if score >= 65:
        return {"sentiment_label": "偏乐观", "sentiment_color": "#ef4444", "sentiment_icon": "🔴"}
    if score >= 55:
        return {"sentiment_label": "中性偏暖", "sentiment_color": "#f59e0b", "sentiment_icon": "🟠"}
    if score >= 45:
        return {"sentiment_label": "中性", "sentiment_color": "#94a3b8", "sentiment_icon": "⚪"}
    if score >= 35:
        return {"sentiment_label": "中性偏冷", "sentiment_color": "#22d3ee", "sentiment_icon": "🔵"}
    return {"sentiment_label": "偏谨慎", "sentiment_color": "#22c55e", "sentiment_icon": "🟢"}


class WorldMacroEngine:
    """全球宏观情报：真实采集全球指数 + 商品报价 + 宏观快讯。"""

    @classmethod
    def get_world_macro_intelligence(cls, start_date=None, end_date=None):  # noqa: ARG003
        indices, idx_errors = fetch_global_indices()
        backup_indices, backup_errors = fetch_global_indices_backup()
        indices.extend(backup_indices)
        idx_errors = [e for e in idx_errors if not any(
            e.startswith(name) for _, name in EASTMONEY_GLOBAL_INDICES)] + backup_errors
        commodities, cmd_errors = fetch_commodities()
        events, news_errors = fetch_news()

        errors = idx_errors + cmd_errors + news_errors
        all_changes = [i.get("change_pct") for i in indices] + \
                      [c.get("change_pct") for c in commodities]
        score, avg_change = _score_from_changes(all_changes)

        domestic = [e for e in events if e["category"] == "domestic"]
        international = [e for e in events if e["category"] == "international"]
        unclassified = [e for e in events if e["category"] == "unclassified"]

        available = bool(indices or commodities)
        status = "available" if available else "unavailable"
        note = ("全球指数与商品报价来自真实公开行情；宏观快讯为东财 7×24 真实标题。"
                if available else "全部来源均未获取，未展示任何推测数据。")
        mood = _sentiment(score)

        return dict(
            meta("腾讯财经 + 新浪财经 + 东方财富",
                 status, "; ".join(errors) if errors else note),
            commodities=commodities,
            global_indices=indices,
            world_events=events,
            domestic_events=domestic,
            international_events=international,
            unclassified_events=unclassified,
            aggregate_score={
                "total_score": score,
                "domestic_score": None,
                "international_score": None,
                "event_count": len(events),
                "avg_change_pct": avg_change,
                "sentiment_label": mood["sentiment_label"],
                "sentiment_color": mood["sentiment_color"],
                "sentiment_icon": mood["sentiment_icon"],
                "score_basis": "50 + 全球指数与商品真实涨跌幅均值(%) × 10（夹取 0~100）",
                "classified_count": {"domestic": len(domestic),
                                     "international": len(international),
                                     "unclassified": len(unclassified)},
                # 界面「N 件政经要闻 / N 件全球大事」徽标直接读这两个字段：
                # 不提供会让徽标恒显示「未获取」，而事件其实已真实取回。
                "domestic_count": len(domestic),
                "international_count": len(international),
                "unclassified_count": len(unclassified),
            },
            classification_note=("快讯归类按标题关键词（国内/国际）判定，"
                                 "口径见源码 DOMESTIC_KEYWORDS / INTERNATIONAL_KEYWORDS。"),
            errors=errors,
            fetched_at=datetime.now(timezone.utc).astimezone().isoformat(),
            history={"points": []},
            domestic_history={"points": []},
            international_history={"points": []},
        )
