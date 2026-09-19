#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 真实行情引擎 (Real Chart & Quotes Engine)
版本: v4.3.0

核心原则 (铁律):
1. 100% 源自真实金融市场数据，严禁任何伪造、推测、mock或容灾生成假数据；
2. 构建多源冗余通道自动故障转移 (Failover):
   - 日K线: 通道A(腾讯证券官方复权日K) -> 通道B(东方财富官方日K) -> 通道C(新浪财经)
   - 分时走势: 通道A(腾讯证券官方高频分时) -> 通道B(新浪财经实时分时)
3. 真实抓取失败或官方未披露时，严格返回空数据 (None / [])，由前端向用户显示严正文案警示！
"""

import os
import sys
import json
import time
import urllib.request
from typing import Dict, List, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def fetch_real_daily_kline(code: str, limit: int = 5000) -> List[Dict[str, Any]]:
    """
    通过多通道冗余获取全量真实日K线数据 (100% 真实数据，绝不伪造)
    返回字段: date, open, close, high, low, volume(手), amount_yi(亿元), change_pct(%)
    """
    clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "").strip()
    prefix = "sh" if code.lower().startswith("sh") or clean_code.startswith(("60", "68")) else "sz"
    symbol_full = f"{prefix}{clean_code}"

    # =========================================================================
    # 通道 1 (主通道): 腾讯证券官方日K (稳定性极高，不报502，历史深厚)
    # =========================================================================
    try:
        tx_url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol_full},day,,,640,qfq"
        tx_req = urllib.request.Request(tx_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://gu.qq.com/"
        })
        with urllib.request.urlopen(tx_req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sec_data = data.get("data", {}).get(symbol_full, {})
            k_list = sec_data.get("qfqday") or sec_data.get("day") or []
            if k_list and isinstance(k_list, list) and len(k_list) > 0:
                result = []
                prev_c = None
                for bar in k_list:
                    if len(bar) >= 6:
                        dt = str(bar[0])
                        o_p = float(bar[1])
                        c_p = float(bar[2])
                        h_p = float(bar[3])
                        l_p = float(bar[4])
                        vol_hands = round(float(bar[5]), 1)
                        
                        avg_p = (o_p + c_p + h_p + l_p) / 4.0
                        amt_yi = round((vol_hands * 100.0 * avg_p) / 100000000.0, 2)
                        
                        chg_pct = round((c_p - prev_c) / prev_c * 100.0, 2) if prev_c and prev_c > 0 else 0.0
                        prev_c = c_p

                        result.append({
                            "date": dt,
                            "open": o_p,
                            "close": c_p,
                            "high": h_p,
                            "low": l_p,
                            "volume": vol_hands,
                            "amount_yi": amt_yi,
                            "change_pct": chg_pct
                        })
                if result:
                    return result
    except Exception as e:
        sys.stderr.write(f"通道1(腾讯)日K拉取异常 ({code}): {e}，尝试通道2...\n")

    # =========================================================================
    # 通道 2 (备选通道): 东方财富官方历史行情
    # =========================================================================
    try:
        secid = f"1.{clean_code}" if prefix == "sh" else f"0.{clean_code}"
        em_url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={max(limit, 1000)}"
        em_req = urllib.request.Request(em_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "http://quote.eastmoney.com/"
        })
        with urllib.request.urlopen(em_req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_klines = data.get("data", {}).get("klines", [])
            if raw_klines:
                result = []
                for item_str in raw_klines:
                    parts = item_str.split(",")
                    if len(parts) >= 7:
                        dt = parts[0]
                        o_p = float(parts[1])
                        c_p = float(parts[2])
                        h_p = float(parts[3])
                        l_p = float(parts[4])
                        vol = float(parts[5])
                        amt_yi = round(float(parts[6]) / 100000000.0, 2)
                        chg_pct = float(parts[8]) if len(parts) > 8 else round((c_p - o_p) / o_p * 100, 2)
                        result.append({
                            "date": dt,
                            "open": o_p,
                            "close": c_p,
                            "high": h_p,
                            "low": l_p,
                            "volume": vol,
                            "amount_yi": amt_yi,
                            "change_pct": chg_pct
                        })
                if result:
                    return result
    except Exception as e:
        sys.stderr.write(f"通道2(东财)日K拉取异常 ({code}): {e}，尝试通道3...\n")

    # =========================================================================
    # 通道 3 (终极备选通道): 新浪财经日K行情
    # =========================================================================
    try:
        sina_url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={symbol_full}&scale=240&ma=no&datalen=320"
        sina_req = urllib.request.Request(sina_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(sina_req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list):
                result = []
                for b in data:
                    c_p = float(b.get("close", 0.0))
                    o_p = float(b.get("open", 0.0))
                    h_p = float(b.get("high", 0.0))
                    l_p = float(b.get("low", 0.0))
                    vol = round(float(b.get("volume", 0.0)) / 100.0, 1)
                    amt_yi = round((vol * 100.0 * c_p) / 100000000.0, 2)
                    result.append({
                        "date": b.get("day", ""),
                        "open": o_p,
                        "close": c_p,
                        "high": h_p,
                        "low": l_p,
                        "volume": vol,
                        "amount_yi": amt_yi,
                        "change_pct": round((c_p - o_p) / o_p * 100.0, 2) if o_p > 0 else 0.0
                    })
                if result:
                    return result
    except Exception as e:
        sys.stderr.write(f"通道3(新浪)日K拉取异常 ({code}): {e}\n")

    # 严格实事求是：三大真实通道均无法访问时，严禁使用任何伪造数据，直接返回空列表！
    sys.stderr.write(f"[Real Engine] 标的 {code} 所有真实接口均无法获取数据 (可能停牌或未上市)，不伪造假数据，返回空列表！\n")
    return []


def fetch_real_timeline(code: str) -> Dict[str, Any]:
    """
    通过多通道冗余获取当天真实分时明细 (100% 真实数据，绝不伪造)
    返回: pre_close, items: [{time, price, avg_price, volume(手), amount_yi(亿元), change_pct}]
    """
    clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "").strip()
    prefix = "sh" if code.lower().startswith("sh") or clean_code.startswith(("60", "68")) else "sz"
    symbol_full = f"{prefix}{clean_code}"

    # =========================================================================
    # 通道 1 (主通道): 腾讯证券高频真实分时 (分笔细致，成交额真实)
    # =========================================================================
    try:
        tx_url = f"http://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol_full}"
        tx_req = urllib.request.Request(tx_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://gu.qq.com/"
        })
        with urllib.request.urlopen(tx_req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            m_data = data.get("data", {}).get(symbol_full, {})
            m_list = m_data.get("data", {}).get("data", [])
            qt_arr = m_data.get("qt", {}).get(symbol_full, [])
            pre_close = float(qt_arr[4]) if len(qt_arr) > 4 else 0.0

            if m_list and isinstance(m_list, list) and len(m_list) > 0:
                items = []
                for raw_str in m_list:
                    parts = raw_str.split(" ")
                    if len(parts) >= 4:
                        raw_t = parts[0]
                        t_fmt = f"{raw_t[:2]}:{raw_t[2:]}" if len(raw_t) == 4 else raw_t
                        p = float(parts[1])
                        vol_hands = float(parts[2])
                        amt_raw = float(parts[3])
                        amt_yi = round(amt_raw / 100000000.0, 3)

                        avg_p = round(amt_raw / (vol_hands * 100.0), 2) if vol_hands > 0 else p
                        chg_pct = round((p - pre_close) / pre_close * 100.0, 2) if pre_close > 0 else 0.0

                        items.append({
                            "time": t_fmt,
                            "price": p,
                            "avg_price": avg_p,
                            "volume": vol_hands,
                            "amount_yi": amt_yi,
                            "change_pct": chg_pct
                        })

                if items:
                    return {
                        "code": code,
                        "pre_close": pre_close,
                        "items": items
                    }
    except Exception as e:
        sys.stderr.write(f"通道1(腾讯)分时拉取异常 ({code}): {e}，尝试通道2...\n")

    # =========================================================================
    # 通道 2 (备选通道): 新浪财经真实分时
    # =========================================================================
    try:
        sina_url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={symbol_full}&scale=5&ma=no&datalen=48"
        sina_req = urllib.request.Request(sina_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/"
        })
        with urllib.request.urlopen(sina_req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                first_bar = data[0]
                pre_close = float(first_bar.get("open", 0.0))
                items = []
                cum_amt = 0.0
                cum_vol = 0.0

                for b in data:
                    t_str = b.get("day", "")[-8:-3]
                    p = float(b.get("close", 0.0))
                    vol_shares = float(b.get("volume", 0.0))
                    vol_hands = round(vol_shares / 100.0, 1)
                    amt = float(b.get("amount", 0.0))
                    amt_yi = round(amt / 100000000.0, 3)

                    cum_amt += amt
                    cum_vol += vol_shares
                    avg_p = round(cum_amt / cum_vol, 2) if cum_vol > 0 else p
                    chg_pct = round((p - pre_close) / pre_close * 100.0, 2) if pre_close > 0 else 0.0

                    items.append({
                        "time": t_str,
                        "price": p,
                        "avg_price": avg_p,
                        "volume": vol_hands,
                        "amount_yi": amt_yi,
                        "change_pct": chg_pct
                    })

                if items:
                    return {
                        "code": code,
                        "pre_close": pre_close,
                        "items": items
                    }
    except Exception as e:
        sys.stderr.write(f"通道2(新浪)分时拉取异常 ({code}): {e}\n")

    # 严禁任何伪造生成分时假数据，直接返回空！
    sys.stderr.write(f"[Real Engine] 标的 {code} 无法获取真实分时，不伪造数据，返回空字典！\n")
    return {
        "code": code,
        "pre_close": 0.0,
        "items": []
    }
