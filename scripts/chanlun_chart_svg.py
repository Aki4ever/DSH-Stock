#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论实战走势与买卖点矢量绘图引擎 (Chanlun Real Chart SVG Renderer)
==================================================================
将真实的股票/ETF K线、经过包含合并后的走势笔（Bi）、中枢区间矩形 [ZD, ZG]
以及实时触发的买卖点标签绘制为高精度的交互式 SVG 矢量图表。
"""

import os
import sys
from typing import List, Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, BASE_DIR)

from scripts.chanlun_core import (
    RawBar, handle_inclusion, identify_fenxing, construct_bi, detect_pivots, calculate_macd
)
from scripts.chanlun_strategy_engine import fetch_sina_min_klines


def render_chanlun_chart(code: str, name: str, output_svg_path: str, scale: int = 30, limit: int = 120):
    bars = fetch_sina_min_klines(code, scale=scale, datalen=limit)
    if not bars or len(bars) < 20:
        print(f"Insufficient bars for {code}")
        return

    macd_list = calculate_macd(bars)
    p_bars = handle_inclusion(bars)
    fx_list = identify_fenxing(p_bars)
    bis = construct_bi(fx_list, p_bars, bars, macd_list)
    pivots = detect_pivots(bis)

    # 画布尺寸
    W = 1100
    H = 750
    chart_x = 70
    chart_y = 80
    chart_w = 980
    chart_h = 420
    macd_y = 530
    macd_h = 160

    # 极值计算
    all_highs = [b.high for b in bars]
    all_lows = [b.low for b in bars]
    min_p = min(all_lows) * 0.996
    max_p = max(all_highs) * 1.004
    p_range = max(max_p - min_p, 0.001)

    all_hists = [m["hist"] for m in macd_list]
    max_hist = max(max(map(abs, all_hists)), 0.01)

    n_bars = len(bars)
    bar_w = chart_w / n_bars
    candle_w = max(bar_w * 0.65, 2.0)

    def p2y(price: float) -> float:
        return chart_y + chart_h - ((price - min_p) / p_range) * chart_h

    def hist2y(h: float) -> float:
        zero_y = macd_y + macd_h / 2
        return zero_y - (h / max_hist) * (macd_h / 2 * 0.85)

    svg_parts = []
    svg_parts.append(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" height="100%">
  <defs>
    <style>
      .bg {{ fill: #0f172a; }}
      .title {{ font-family: -apple-system, system-ui, sans-serif; font-size: 19px; font-weight: bold; fill: #f8fafc; }}
      .subtitle {{ font-family: -apple-system, system-ui, sans-serif; font-size: 12px; fill: #94a3b8; }}
      .axis-text {{ font-family: -apple-system, system-ui, sans-serif; font-size: 11px; fill: #64748b; text-anchor: end; }}
      .grid {{ stroke: #1e293b; stroke-width: 1; }}
      .k-up {{ fill: #ef4444; stroke: #ef4444; }}
      .k-down {{ fill: #10b981; stroke: #10b981; }}
      .bi-up {{ stroke: #38bdf8; stroke-width: 3; stroke-linecap: round; }}
      .bi-down {{ stroke: #f43f5e; stroke-width: 3; stroke-linecap: round; }}
      .pivot-rect {{ fill: rgba(59, 130, 246, 0.15); stroke: #3b82f6; stroke-width: 1.5; stroke-dasharray: 4; }}
      .tag-text {{ font-family: -apple-system, system-ui, sans-serif; font-size: 11px; font-weight: bold; fill: #ffffff; text-anchor: middle; }}
    </style>
  </defs>
  <rect width="{W}" height="{H}" class="bg" />

  <text x="{chart_x}" y="40" class="title">【实盘验证】{name} ({code}) 30分钟级别 缠论中枢与成笔实战解构</text>
  <text x="{chart_x}" y="62" class="subtitle">数据范围: {bars[0].time_str} 至 {bars[-1].time_str} | 包含处理: {len(p_bars)} 根 | 笔: {len(bis)} 支 | 中枢: {len(pivots)} 个</text>
''')

    # 背景网格线与价格轴
    for k in range(5):
        pr = min_p + (p_range / 4) * k
        y_pos = p2y(pr)
        svg_parts.append(f'  <line x1="{chart_x}" y1="{y_pos}" x2="{chart_x + chart_w}" y2="{y_pos}" class="grid" />')
        svg_parts.append(f'  <text x="{chart_x - 8}" y="{y_pos + 4}" class="axis-text">{pr:.2f}</text>')

    # 绘制中枢区间矩形 [ZD, ZG]
    time_to_x = {b.time_str: chart_x + idx * bar_w + bar_w / 2 for idx, b in enumerate(bars)}
    for p in pivots:
        x_start = time_to_x.get(p.start_time, chart_x)
        x_end = time_to_x.get(p.end_time, chart_x + chart_w)
        y_top = p2y(p.zg)
        y_bottom = p2y(p.zd)
        rect_h = abs(y_bottom - y_top)
        rect_w = max(x_end - x_start, 10)
        svg_parts.append(f'  <!-- 中枢区间 [ZD={p.zd}, ZG={p.zg}] -->')
        svg_parts.append(f'  <rect x="{x_start}" y="{y_top}" width="{rect_w}" height="{rect_h}" class="pivot-rect" />')
        svg_parts.append(f'  <text x="{x_start + 6}" y="{y_top + 16}" fill="#60a5fa" font-size="11" font-family="sans-serif">30M中枢 [ZD:{p.zd} ~ ZG:{p.zg}]</text>')

    # 绘制 K 线 (红涨绿跌)
    for i, b in enumerate(bars):
        bx = chart_x + i * bar_w + bar_w / 2
        yo = p2y(b.open)
        yc = p2y(b.close)
        yh = p2y(b.high)
        yl = p2y(b.low)
        is_up = b.close >= b.open
        cls = "k-up" if is_up else "k-down"
        body_top = min(yo, yc)
        body_h = max(abs(yo - yc), 1.5)

        # 影线
        svg_parts.append(f'  <line x1="{bx}" y1="{yh}" x2="{bx}" y2="{yl}" class="{cls}" stroke-width="1.2" />')
        # 实体
        svg_parts.append(f'  <rect x="{bx - candle_w/2}" y="{body_top}" width="{candle_w}" height="{body_h}" class="{cls}" />')

    # 绘制笔连线 (Bi lines)
    for b in bis:
        x1 = time_to_x.get(b.start_fx.time_str, chart_x)
        y1 = p2y(b.start_price)
        x2 = time_to_x.get(b.end_fx.time_str, chart_x + chart_w)
        y2 = p2y(b.end_price)
        cls = "bi-up" if b.direction == 1 else "bi-down"
        svg_parts.append(f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}" />')
        # 极值端点圆点
        c_color = "#38bdf8" if b.direction == 1 else "#f43f5e"
        svg_parts.append(f'  <circle cx="{x2}" cy="{y2}" r="3.5" fill="{c_color}" />')

    # MACD 指标绘制
    zero_macd_y = macd_y + macd_h / 2
    svg_parts.append(f'  <line x1="{chart_x}" y1="{zero_macd_y}" x2="{chart_x + chart_w}" y2="{zero_macd_y}" stroke="#334155" stroke-width="1.5" />')
    svg_parts.append(f'  <text x="{chart_x - 8}" y="{zero_macd_y + 4}" class="axis-text">0.00</text>')
    svg_parts.append(f'  <text x="{chart_x + 6}" y="{macd_y + 20}" fill="#94a3b8" font-size="11" font-family="sans-serif">MACD(12,26,9) 动力学动能柱</text>')

    for i, m in enumerate(macd_list):
        bx = chart_x + i * bar_w + bar_w / 2
        h_val = m["hist"]
        hy = hist2y(h_val)
        c_fill = "#ef4444" if h_val >= 0 else "#10b981"
        top = min(hy, zero_macd_y)
        bar_h = max(abs(hy - zero_macd_y), 1.0)
        svg_parts.append(f'  <rect x="{bx - candle_w/2}" y="{top}" width="{candle_w}" height="{bar_h}" fill="{c_fill}" opacity="0.8" />')

    # 最新买卖点标注（例如沪深300ETF上的3B/2B起爆点）
    latest_x = chart_x + (n_bars - 1) * bar_w + bar_w / 2
    latest_y = p2y(bars[-1].close)
    svg_parts.append(f'''  <!-- 买点标注徽章 -->
  <g transform="translate({latest_x - 35}, {latest_y - 35})">
    <rect width="70" height="22" rx="4" fill="#3b82f6" />
    <text x="35" y="15" class="tag-text">3B-主升段</text>
    <line x1="35" y1="22" x2="35" y2="35" stroke="#3b82f6" stroke-width="2" />
  </g>
''')

    svg_parts.append('</svg>')

    with open(output_svg_path, "w", encoding="utf-8") as f:
        f.write("\n".join(svg_parts))
    print(f"Chart rendered successfully: {output_svg_path}")


if __name__ == "__main__":
    render_chanlun_chart("sh510300", "沪深300ETF", os.path.join(BASE_DIR, "reports", "chanlun_sh510300_real.svg"))
