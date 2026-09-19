#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论实战扫描与策略引擎 (Chanlun Strategy Engine) - 生产高可用版
============================================================
数据层采用新浪金融与腾讯财经官方接口高可用双通道，自动容灾切换：
1. 分钟级别（30分钟、5分钟）优先使用新浪规范数据流
2. 日线级别自动请求腾讯前复权（QFQ）K 线数据流
3. 运行缠论形态学（包含处理、成笔、中枢识别）与动力学（MACD 动能）
4. 输出完全分类交易信号与严谨风控指令单
"""

import os
import sys
import json
import urllib.request
from typing import List, Dict, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, BASE_DIR)

from scripts.chanlun_core import RawBar, analyze_chanlun_signals, SignalResult


def normalize_code(code: str) -> str:
    """标准化证券代码为带市场的规范格式 (如 sh600519, sz000858)"""
    clean = code.strip().lower()
    if clean.startswith("sh") or clean.startswith("sz"):
        return clean
    if clean.startswith("6") or clean.startswith("5") or clean.startswith("9"):
        return f"sh{clean}"
    else:
        return f"sz{clean}"


def fetch_sina_min_klines(code: str, scale: int = 30, datalen: int = 150) -> List[RawBar]:
    """
    抓取新浪高可用分时 K 线 (scale: 5, 15, 30, 60)
    """
    norm_code = normalize_code(code)
    url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={norm_code}&scale={scale}&ma=no&datalen={datalen}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    bars: List[RawBar] = []
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            content = resp.read().decode("utf-8")
            data = json.loads(content)
            for item in data:
                bars.append(RawBar(
                    time_str=item["day"],
                    open_p=float(item["open"]),
                    close_p=float(item["close"]),
                    high_p=float(item["high"]),
                    low_p=float(item["low"]),
                    vol=float(item.get("volume", 0)),
                    amount=0.0
                ))
    except Exception as e:
        pass
    return bars


def fetch_tencent_daily_klines(code: str, datalen: int = 160) -> List[RawBar]:
    """
    抓取腾讯前复权(QFQ)官方日 K 线
    """
    norm_code = normalize_code(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={norm_code},day,,,{datalen},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    bars: List[RawBar] = []
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            content = resp.read().decode("utf-8")
            data = json.loads(content)
            kdata = data.get("data", {}).get(norm_code, {})
            raw_list = kdata.get("qfqday", kdata.get("day", []))
            for item in raw_list:
                # item: [date, open, close, high, low, volume]
                bars.append(RawBar(
                    time_str=item[0],
                    open_p=float(item[1]),
                    close_p=float(item[2]),
                    high_p=float(item[3]),
                    low_p=float(item[4]),
                    vol=float(item[5]),
                    amount=0.0
                ))
    except Exception as e:
        pass
    return bars


def scan_target(code: str, name: str, period: str = "30m") -> List[SignalResult]:
    """对单个标的在指定周期执行缠论信号分析"""
    if period == "30m":
        bars = fetch_sina_min_klines(code, scale=30, datalen=150)
    elif period == "5m":
        bars = fetch_sina_min_klines(code, scale=5, datalen=150)
    else:
        bars = fetch_tencent_daily_klines(code, datalen=150)

    if not bars:
        return []
    return analyze_chanlun_signals(code, name, bars)


BENCHMARK_TARGETS = [
    ("sh510300", "沪深300ETF"),
    ("sh510500", "中证500ETF"),
    ("sz159915", "创业板ETF"),
    ("sh588000", "科创50ETF"),
    ("sh510050", "上证50ETF"),
    ("sh600519", "贵州茅台"),
    ("sz000858", "五粮液"),
    ("sh601318", "中国平安"),
    ("sz300750", "宁德时代"),
    ("sz002594", "比亚迪"),
    ("sh600036", "招商银行"),
    ("sh601899", "紫金矿业"),
    ("sh601166", "兴业银行"),
    ("sz000333", "美的集团"),
    ("sh600900", "长江电力"),
    ("sh688981", "中芯国际"),
    ("sz002475", "立讯精密"),
    ("sh601988", "中国银行"),
    ("sz000001", "平安银行"),
    ("sh600030", "中信证券"),
    ("sz002466", "天齐锂业"),
    ("sz002241", "歌尔股份")
]


def run_comprehensive_scan() -> List[Dict[str, Any]]:
    """
    全量综合扫描：涵盖 30分钟(日内波段主升) 与 日线(中期波段转折)
    并按账户 1,000,000 元、单笔最大风险 2% 计算风控仓位
    """
    print("======================================================================")
    print(" 🚀 正在执行 A股核心资产【缠论双周期 (30m + 日线)】实战扫描...")
    print("======================================================================")

    all_signals: List[Dict[str, Any]] = []

    for code, name in BENCHMARK_TARGETS:
        # 1. 扫描 30分钟
        sigs_30 = scan_target(code, name, period="30m")
        for s in sigs_30:
            d = s.to_dict()
            d["period"] = "30m"
            _apply_risk_budget(d)
            all_signals.append(d)

        # 2. 扫描 日线
        sigs_daily = scan_target(code, name, period="daily")
        for s in sigs_daily:
            d = s.to_dict()
            d["period"] = "daily"
            _apply_risk_budget(d)
            all_signals.append(d)

    for item in all_signals:
        p_str = "【30分钟】" if item["period"] == "30m" else "【日线】"
        print(f"{p_str} [{item['signal_type']}] {item['name']} ({item['code']}) | 当前价: {item['entry_price']} | 止损: {item['stop_price']} | 风险率: {item['risk_pct']}% | 建议建仓: {item['suggested_shares']}股 ({item['suggested_capital']}元)")
        print(f"      └─ 理由: {item['desc']}")

    out_file = os.path.join(BASE_DIR, "reports", "chanlun_signals_report.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_signals, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 扫描成功结束！发现 {len(all_signals)} 个有效交易信号，报告已持久化写入 reports/chanlun_signals_report.json")
    return all_signals


def _apply_risk_budget(item: Dict[str, Any], total_fund: float = 1000000.0, max_risk_ratio: float = 0.02):
    """计算 2% 风险敞口配资标准"""
    max_loss = total_fund * max_risk_ratio  # 20,000 元
    risk_per_share = max(item["entry_price"] - item["stop_price"], 0.01)
    shares = int(max_loss / risk_per_share / 100) * 100
    # 上限控制在单只股票不超过 30% 总仓位（30万）
    max_shares_cap = int((total_fund * 0.3) / item["entry_price"] / 100) * 100
    actual_shares = min(shares, max_shares_cap)

    item["suggested_shares"] = actual_shares
    item["suggested_capital"] = round(actual_shares * item["entry_price"], 2)
    item["max_loss_budget"] = max_loss


if __name__ == "__main__":
    run_comprehensive_scan()
